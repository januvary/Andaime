"""
Base SQLite database class with connection management, retries, and backups.
"""

import sqlite3
import time
import threading
import shutil
from abc import ABC, abstractmethod
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, ParamSpec, TypeVar

from andaime.paths import resolve_db_path
from andaime.error_handler import ErrorHandler, ErrorLevel

_P = ParamSpec("_P")
_R = TypeVar("_R")


def db_op(op_type: str = "read") -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorator(func: Callable[_P, _R]) -> Callable[_P, _R]:
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            db: Any = args[0]  # type: ignore[assignment]
            return db._retry_on_transient_error(
                lambda: func(*args, **kwargs),
                operation_type=op_type,
            )

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper

    return decorator


class BaseDatabase(ABC):
    def __init__(
        self, db_path: str | None = None, entity_name: str = "registros"
    ) -> None:
        if db_path is None:
            db_path = self._resolve_default_db_path()
            ErrorHandler.log(
                f"{self.__class__.__name__}: Usando banco de dados: {db_path}",
                level=ErrorLevel.INFO,
                context="Database",
            )

        self.db_path = db_path
        self._entity_name = entity_name
        self.conn: sqlite3.Connection | None = None
        self._conn_open_time: float | None = None
        self._lock = threading.RLock()
        self._initialize()

    @abstractmethod
    def _create_schema(self) -> None:
        pass

    def _ensure_schema_version(self) -> int:
        with self._cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS _schema_meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            self._commit()
            cur.execute("SELECT value FROM _schema_meta WHERE key = 'version'")
            row = cur.fetchone()
        if row is None:
            return 0
        stored = int(row["value"] if isinstance(row, dict) else row[0])
        return stored

    def _set_schema_version(self, version: int) -> None:
        with self._cursor() as cur:
            cur.execute(
                "INSERT OR REPLACE INTO _schema_meta (key, value) VALUES (?, ?)",
                ("version", str(version)),
            )
            self._commit()

    def _resolve_default_db_path(self) -> str:
        return resolve_db_path("database.db", create_dir=True)

    def __enter__(self) -> "BaseDatabase":
        return self

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> Literal[False]:
        self.close()
        return False

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()

    def _setup_pragmas(self) -> None:
        with self._cursor() as cur:
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=TRUNCATE")
            cur.execute("PRAGMA synchronous=FULL")
            cur.execute("PRAGMA cache_size=-2000")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.execute("PRAGMA temp_store=MEMORY")

    def _initialize(self) -> None:
        max_retries = 5

        for attempt in range(max_retries):
            try:
                self.conn = sqlite3.connect(
                    self.db_path,
                    check_same_thread=False,
                    timeout=30,
                )
                self.conn.row_factory = sqlite3.Row
                self._conn_open_time = time.time()
                self._create_schema()
                self._setup_pragmas()

                self._log_initialization_success()
                return

            except sqlite3.OperationalError as e:
                error_str = str(e)
                is_io_error = (
                    "disk I/O error" in error_str or "database is locked" in error_str
                )
                is_last_attempt = attempt == max_retries - 1

                if is_io_error and not is_last_attempt:
                    delay = 2**attempt
                    ErrorHandler.log(
                        f"Erro de I/O ao conectar {self.__class__.__name__} "
                        f"(tentativa {attempt + 1}/{max_retries}). "
                        f"Aguardando {delay}s...",
                        level=ErrorLevel.WARNING,
                        context="Database",
                    )
                    time.sleep(delay)
                else:
                    ErrorHandler.handle_database_error(
                        e,
                        operation=f"Falha ao abrir banco: {self.db_path}",
                    )
                    raise

    def _log_initialization_success(self) -> None:
        ErrorHandler.log(
            f"{self.__class__.__name__} inicializado com sucesso",
            level=ErrorLevel.INFO,
            context="Database",
        )

    def _is_connection_healthy(self) -> bool:
        try:
            with self._lock:
                if self.conn is None:
                    return False
                cursor = self.conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                return True
        except (sqlite3.OperationalError, sqlite3.ProgrammingError, AttributeError):
            return False

    def _reconnect_unlocked(self) -> None:
        if self.db_path == ":memory:":
            return

        if self.conn:
            with suppress(Exception):
                self.conn.close()

        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self._conn_open_time = time.time()

            with self._cursor() as cur:
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA journal_mode=TRUNCATE")
                cur.execute("PRAGMA synchronous=FULL")
                cur.execute("PRAGMA busy_timeout=10000")
                cur.execute("PRAGMA cache_size=-2000")
                cur.execute("PRAGMA temp_store=MEMORY")

            ErrorHandler.log(
                f"Conexão {self.__class__.__name__} renovada",
                level=ErrorLevel.INFO,
                context="Database",
            )
        except Exception as e:
            ErrorHandler.handle_database_error(
                e,
                operation=f"reconectar ao banco de {self._entity_name}",
            )
            raise

    def _refresh_connection(self) -> None:
        with self._lock:
            self._reconnect_unlocked()

    def _ensure_connection(self) -> None:
        with self._lock:
            if not self._is_connection_healthy():
                self._reconnect_unlocked()

    def _get_cursor(self) -> sqlite3.Cursor:
        with self._lock:
            assert self.conn is not None, "Database connection not initialized"
            return self.conn.cursor()

    def _get_connection(self) -> sqlite3.Connection:
        with self._lock:
            assert self.conn is not None, "Database connection not initialized"
            return self.conn

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        cursor = self._get_cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def _fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        with self._cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    def _fetch_value(self, sql: str, params: tuple = ()) -> Any:
        with self._cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None

    def _execute_write(self, sql: str, params: tuple = ()) -> bool:
        with self._cursor() as cur:
            cur.execute(sql, params)
        self._commit()
        return True

    def _execute_insert(self, sql: str, params: tuple = ()) -> int:
        with self._cursor() as cur:
            cur.execute(sql, params)
            last_id = cur.lastrowid
        self._commit()
        return last_id

    def _fetch_by_id(self, table: str, row_id: int) -> dict | None:
        return self._fetch_one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))

    def _fetch_all_table(self, table: str, order_by: str = "") -> list[dict]:
        sql = f"SELECT * FROM {table}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        return self._fetch_all(sql)

    def _fetch_count(self, table: str, where: str = "", params: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        val = self._fetch_value(sql, params)
        return val if val is not None else 0

    def _insert_row(self, table: str, **kwargs) -> int:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        return self._execute_insert(sql, tuple(kwargs.values()))

    def _update_row(self, table: str, row_id: int, **kwargs) -> bool:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE {table} SET {sets} WHERE id = ?"
        return self._execute_write(sql, tuple(kwargs.values()) + (row_id,))

    def _delete_row(self, table: str, row_id: int, guards: list[tuple[str, str]] = []) -> bool:
        for guard_table, fk_col in guards:
            if self._fetch_count(guard_table, f"{fk_col} = ?", (row_id,)) > 0:
                return False
        return self._execute_write(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    def _commit(self) -> None:
        with self._lock:
            assert self.conn is not None, "Database connection not initialized"
            self.conn.commit()

    def _rollback(self) -> None:
        with self._lock:
            assert self.conn is not None, "Database connection not initialized"
            self.conn.rollback()

    def _retry_on_transient_error(
        self,
        operation: Callable,
        max_retries: int = 3,
        operation_type: str = "operation",
    ) -> Any:
        for attempt in range(max_retries):
            try:
                return operation()
            except sqlite3.OperationalError as e:
                error_str = str(e)
                is_transient = (
                    "database is locked" in error_str
                    or "disk I/O error" in error_str
                    or "unable to open database" in error_str
                )

                if is_transient and attempt < max_retries - 1:
                    delay = (2**attempt) * 0.5
                    ErrorHandler.log(
                        f"Problema durante {operation_type} (tentativa {attempt + 1}/{max_retries}), "
                        f"tentando novamente em {delay:.1f}s...",
                        level=ErrorLevel.WARNING,
                        context="Database",
                    )
                    time.sleep(delay)
                else:
                    raise

    def _backup_database(self) -> None:
        try:
            backup_dir = Path(self.db_path).parent / "backups"
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            db_name = Path(self.db_path).stem
            backup_path = backup_dir / f"{db_name}_{timestamp}.db"

            shutil.copy2(self.db_path, backup_path)

            backups = sorted(backup_dir.glob(f"{db_name}_*.db"))
            for old_backup in backups[:-10]:
                old_backup.unlink()

            ErrorHandler.log(
                f"Backup de {db_name} criado: {backup_path}",
                level=ErrorLevel.INFO,
                context="Database",
            )
        except Exception as e:
            ErrorHandler.log(
                f"Erro ao criar backup: {e}",
                level=ErrorLevel.WARNING,
                context="Database",
            )

    def close(self, skip_backup: bool = False) -> None:
        if self.conn:
            try:
                if not skip_backup:
                    self._backup_database()
                self.conn.close()
                self.conn = None
                ErrorHandler.log(
                    f"{self.__class__.__name__} conexão fechada",
                    level=ErrorLevel.INFO,
                    context="Database",
                )
            except Exception as e:
                ErrorHandler.log(
                    f"Erro ao fechar {self.__class__.__name__}: {e}",
                    level=ErrorLevel.WARNING,
                    context="Database",
                )
                self.conn = None
