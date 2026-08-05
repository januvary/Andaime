"""
Base SQLite database class with connection management, retries, and backups.
"""

import os
import re
import sqlite3
import sys
import threading
import time
import shutil
from abc import ABC, abstractmethod
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, ParamSpec, TypeVar, cast

from andaime.paths import resolve_db_path
from andaime.error_handler import ErrorHandler, ErrorLevel

_P = ParamSpec("_P")
_R = TypeVar("_R")


# Tipos de filesystem de rede conhecidos (coluna fstype do /proc/mounts).
# WAL do SQLite é não-confiável nestes filesystems (riscos de hang e
# corrupção documentados), então usamos rollback-journal (DELETE) neles.
_NETWORK_FS_TYPES = frozenset(
    {
        "cifs",
        "smbfs",
        "smb2",
        "smb3",
        "nfs",
        "nfs4",
        "ncpfs",
        "fuse.sshfs",
        "fuse.curlftpfs",
        "fuse.gvfs-fuse-daemon",
        "davfs",
        "lustre",
        "gpfs",
        "ocfs2",
    }
)

# DRIVE_REMOTE do GetDriveTypeW (Windows).
_DRIVE_REMOTE = 4


def _decode_mount_point(raw: str) -> str:
    """Decodifica escapes octais do /proc/mounts (ex.: \\040 -> espaço)."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), raw)


def _read_proc_mounts() -> list[tuple[str, str, str]]:
    """
    Lê /proc/mounts e devolve (device, mount_point, fstype) por linha.

    Isolado em função própria para permitir teste sem /proc/mounts real.
    """
    entries: list[tuple[str, str, str]] = []
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                entries.append((parts[0], _decode_mount_point(parts[1]), parts[2]))
    except OSError:
        pass
    return entries


def _is_network_path(path: str) -> bool:
    """
    Detecta se o caminho está num filesystem de rede (SMB/CIFS/NFS/etc.).

    O modo WAL do SQLite é não-confiável em shares de rede: a coordenação
    via arquivo ``-shm`` memory-mapped quebra, causando hangs (e risco de
    corrupção) em acesso multi-processo. Usa-se rollback-journal (DELETE)
    nesses casos.

    Args:
        path: Caminho do arquivo de banco.

    Returns:
        True se o caminho parecer estar num filesystem de rede.
        False se for local ou se não for possível determinar (default WAL).
    """
    raw = str(path)

    # Windows: UNC (\\server\share ou //server/share) é sempre rede.
    # Checamos o path bruto — Path.resolve() normaliza prefixes/drives.
    if sys.platform == "win32":
        if raw.startswith("\\\\") or raw.startswith("//"):
            return True
        drive_match = re.match(r"^([A-Za-z]:)", raw)
        if drive_match:
            try:
                import ctypes

                drive = drive_match.group(1)
                return (
                    ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\") == _DRIVE_REMOTE
                )
            except Exception:
                pass
        return False

    # Linux: usa /proc/mounts — match pelo número de dispositivo (st_dev),
    # que é robusto a espaços/caracteres no caminho do mount.
    if sys.platform.startswith("linux") and os.path.exists("/proc/mounts"):
        try:
            resolved = str(Path(raw).resolve())
            target_dev = os.stat(resolved).st_dev
        except OSError:
            return False
        for _device, mount_point, fstype in _read_proc_mounts():
            try:
                if os.stat(mount_point).st_dev == target_dev:
                    if fstype in _NETWORK_FS_TYPES:
                        return True
            except OSError:
                continue
        return False

    # Outros SOs (macOS, etc.): não determinamos — assume local (WAL).
    return False


def db_op(op_type: str = "read") -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    def decorator(func: Callable[_P, _R]) -> Callable[_P, _R]:
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            db: Any = args[0]
            return cast(
                _R,
                db._retry_on_transient_error(
                    lambda: func(*args, **kwargs),
                    operation_type=op_type,
                ),
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
        self._backup_retention = 10
        self.conn: sqlite3.Connection | None = None
        self._conn_open_time: float | None = None
        self._lock = threading.RLock()
        self._in_transaction = False
        self._initialize()

    @abstractmethod
    def _create_schema(self) -> None:
        pass

    def _ensure_schema_meta(self) -> None:
        with self._cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS _schema_meta "
                "(key TEXT PRIMARY KEY, value TEXT)"
            )
        self._commit()

    def _ensure_schema_version(self) -> int:
        self._ensure_schema_meta()
        with self._cursor() as cur:
            cur.execute("SELECT value FROM _schema_meta WHERE key = 'version'")
            row = cur.fetchone()
        if row is None:
            return 0
        stored = int(row["value"] if isinstance(row, dict) else row[0])
        return stored

    def _set_schema_version(self, version: int) -> None:
        self._ensure_schema_meta()
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

    def _apply_pragmas(self, cur: sqlite3.Cursor) -> None:
        cur.execute("PRAGMA foreign_keys=ON")
        # WAL é mais rápido em disco local, mas NÃO-confiável em shares de
        # rede: a coordenação via -shm quebra, causando hangs e risco de
        # corrupção em acesso multi-processo. DELETE usa locking simples,
        # robusto em SMB/CIFS/NFS.
        requested = "DELETE" if _is_network_path(self.db_path) else "WAL"
        row = cur.execute(f"PRAGMA journal_mode={requested}").fetchone()
        actual = str(row[0]).upper() if row else requested
        if actual != requested:
            # Não foi possível trocar (ex.: outra conexão mantém WAL aberto).
            ErrorHandler.log(
                f"journal_mode solicitado={requested} mas efetivo={actual} "
                f"para {self.db_path}. Se o DB está em share de rede, feche "
                f"outras instâncias e reabra para converter para {requested}.",
                level=ErrorLevel.WARNING,
                context="Database",
            )
        cur.execute("PRAGMA synchronous=NORMAL")
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
                with self._cursor() as cur:
                    self._apply_pragmas(cur)
                self._create_schema()

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
                self._apply_pragmas(cur)

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
        assert last_id is not None, "INSERT did not produce a row id"
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

    def _insert_row(self, table: str, **kwargs: Any) -> int:
        cols = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
        return self._execute_insert(sql, tuple(kwargs.values()))

    def _update_row(self, table: str, row_id: int, **kwargs: Any) -> bool:
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE {table} SET {sets} WHERE id = ?"
        return self._execute_write(sql, tuple(kwargs.values()) + (row_id,))

    def _delete_row(
        self, table: str, row_id: int, guards: list[tuple[str, str]] | None = None
    ) -> bool:
        for guard_table, fk_col in guards or []:
            if self._fetch_count(guard_table, f"{fk_col} = ?", (row_id,)) > 0:
                return False
        return self._execute_write(f"DELETE FROM {table} WHERE id = ?", (row_id,))

    def _commit(self) -> None:
        with self._lock:
            assert self.conn is not None, "Database connection not initialized"
            if not self._in_transaction:
                self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group operations into a single commit.

        Calls to ``_commit()`` inside the block are deferred; the outermost
        block commits once on success or rolls back on error. Nesting is
        safe — only the outermost block commits.
        """
        with self._lock:
            already = self._in_transaction
            if not already:
                self._in_transaction = True
        try:
            yield
            if not already:
                with self._lock:
                    assert self.conn is not None, "Database connection not initialized"
                    self.conn.commit()
        except Exception:
            if not already:
                with self._lock:
                    assert self.conn is not None, "Database connection not initialized"
                    with suppress(Exception):
                        self.conn.rollback()
            raise
        finally:
            with self._lock:
                if not already:
                    self._in_transaction = False

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
            for old_backup in backups[: -self._backup_retention]:
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
