#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAC Database
SQLite database layer for Registros Alto Custo
"""

import sqlite3
import operator
import contextlib
from typing import Optional
from datetime import date, datetime

from andaime.database import BaseDatabase, db_op
from andaime.paths import resolve_db_path
from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel
from andaime.text import to_upper_normalized

from rac.database.definitive_catalog import DEFINITIVE_CATALOG
from rac.services.exceptions import DuplicateRecordError
from rac.models import (
    Malote,
    Paciente,
    ItemCatalog,
    Registro,
    RegistroItem,
    RegistroExport,
    Process,
)


class RACDatabase(BaseDatabase):
    SCHEMA_VERSION = 6

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = resolve_db_path("registros.db", create_dir=True)
        super().__init__(db_path=db_path, entity_name="registros")

    def _search_by_name(
        self, table: str, name_column: str, query: str, limit: int
    ) -> list[dict]:
        normalized = to_upper_normalized(query)
        return self._fetch_all(
            f"SELECT * FROM {table} WHERE {name_column} LIKE ? "
            f"ORDER BY {name_column} COLLATE NOCASE LIMIT ?",
            (f"%{normalized}%", limit),
        )

    def _create_schema(self) -> None:
        self._create_fresh_schema()
        self._set_schema_version(self.SCHEMA_VERSION)
        self._seed_catalog_if_empty()

    def _create_fresh_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript("""
                CREATE TABLE IF NOT EXISTS malotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    arrival_date TEXT
                );

                CREATE TABLE IF NOT EXISTS pacientes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS items_catalog (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    unidade TEXT NOT NULL DEFAULT 'un',
                    cids TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS registros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tipo TEXT NOT NULL,
                    paciente_id INTEGER NOT NULL REFERENCES pacientes(id),
                    malote_id INTEGER NOT NULL REFERENCES malotes(id),
                    created_at TEXT NOT NULL,
                    waiting_docs INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS processes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    registro_id INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
                    group_number INTEGER NOT NULL DEFAULT 1,
                    months_supply INTEGER NOT NULL DEFAULT 0,
                    expected_return_date TEXT
                );

                CREATE TABLE IF NOT EXISTS registro_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    registro_id INTEGER NOT NULL REFERENCES registros(id) ON DELETE CASCADE,
                    process_id INTEGER REFERENCES processes(id),
                    item_id INTEGER NOT NULL REFERENCES items_catalog(id),
                    process_group INTEGER NOT NULL DEFAULT 1,
                    cid TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_registros_malote ON registros(malote_id);
                CREATE INDEX IF NOT EXISTS idx_registros_paciente ON registros(paciente_id);
                CREATE INDEX IF NOT EXISTS idx_registros_tipo ON registros(tipo);
                CREATE INDEX IF NOT EXISTS idx_pacientes_nome ON pacientes(name COLLATE NOCASE);
                CREATE INDEX IF NOT EXISTS idx_registro_items_registro ON registro_items(registro_id);
                CREATE INDEX IF NOT EXISTS idx_registro_items_item ON registro_items(item_id);
                CREATE INDEX IF NOT EXISTS idx_registro_items_process ON registro_items(process_id);
                CREATE INDEX IF NOT EXISTS idx_processes_registro ON processes(registro_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_registros_unique ON registros(tipo, paciente_id, malote_id);
                """)
            self._commit()

    def _log_initialization_success(self) -> None:
        count = self._get_catalog_count()
        ErrorHandler.log(
            f"RACDatabase inicializado - {count} itens no catálogo",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

    def _seed_catalog_if_empty(self) -> None:
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM items_catalog")
            count = cur.fetchone()[0]

            if count == 0:
                for name, unidade, cids_json in DEFINITIVE_CATALOG:
                    cur.execute(
                        "INSERT INTO items_catalog (name, unidade, cids) VALUES (?, ?, ?)",
                        (to_upper_normalized(name), unidade, cids_json),
                    )
                self._commit()
                ErrorHandler.log(
                    f"Catálogo inicializado com {len(DEFINITIVE_CATALOG)} itens",
                    level=ErrorLevel.INFO,
                    context=ErrorContext.DATABASE,
                )

    def _get_catalog_count(self) -> int:
        return self._fetch_count("items_catalog")

    # ========== MALOTE ==========

    @db_op("write")
    def create_malote(self, date: str, arrival_date: str | None = None) -> Malote:
        with self._cursor() as cur:
            cur.execute("SELECT id, arrival_date FROM malotes WHERE date = ?", (date,))
            existing = cur.fetchone()
            if existing:
                return Malote(
                    id=existing["id"], date=date, arrival_date=existing["arrival_date"]
                )
            cur.execute(
                "INSERT INTO malotes (date, arrival_date) VALUES (?, ?)",
                (date, arrival_date),
            )
            self._commit()
            return Malote(id=cur.lastrowid, date=date, arrival_date=arrival_date)

    @db_op("read")
    def get_malote_by_id(self, malote_id: int) -> Optional[Malote]:
        row = self._fetch_by_id("malotes", malote_id)
        return Malote.from_row(row) if row else None

    @db_op("read")
    def get_recent_malotes(self, limit: int = 5) -> list[Malote]:
        return [Malote.from_row(r) for r in self._fetch_all(
            "SELECT * FROM malotes ORDER BY date DESC, id DESC LIMIT ?",
            (limit,),
        )]

    @db_op("read")
    def get_all_malotes(self) -> list[Malote]:
        return [Malote.from_row(r) for r in self._fetch_all_table(
            "malotes", "date DESC, id DESC"
        )]

    @db_op("read")
    def get_malote_dates(self) -> set:
        dates = set()
        for r in self._fetch_all("SELECT date FROM malotes"):
            with contextlib.suppress(ValueError, TypeError):
                dates.add(datetime.fromisoformat(r["date"]).date())
        return dates

    @db_op("write")
    def update_malote(
        self, malote_id: int, date: str | None = None, arrival_date: str | None = None
    ) -> bool:
        updates = {}
        if date is not None:
            updates["date"] = date
        if arrival_date is not None:
            updates["arrival_date"] = arrival_date
        if not updates:
            return False
        return self._update_row("malotes", malote_id, **updates)

    @db_op("write")
    def delete_malote(self, malote_id: int) -> bool:
        return self._delete_row("malotes", malote_id, guards=[("registros", "malote_id")])

    # ========== PACIENTE ==========

    @db_op("write")
    def create_paciente(self, name: str) -> Paciente:
        normalized = to_upper_normalized(name.strip())
        pid = self._insert_row("pacientes", name=normalized)
        return Paciente(id=pid, name=normalized)

    @db_op("read")
    def get_paciente_by_id(self, paciente_id: int) -> Optional[Paciente]:
        row = self._fetch_by_id("pacientes", paciente_id)
        return Paciente.from_row(row) if row else None

    @db_op("read")
    def find_paciente_by_name(self, name: str) -> Optional[Paciente]:
        row = self._fetch_one(
            "SELECT * FROM pacientes WHERE name = ? LIMIT 1",
            (to_upper_normalized(name),),
        )
        return Paciente.from_row(row) if row else None

    @db_op("read")
    def search_pacientes(self, query: str, limit: int = 10) -> list[Paciente]:
        return [Paciente.from_row(r) for r in self._search_by_name(
            "pacientes", "name", query, limit,
        )]

    @db_op("write")
    def update_paciente(self, paciente_id: int, name: str) -> bool:
        return self._update_row(
            "pacientes", paciente_id, name=to_upper_normalized(name.strip())
        )

    @db_op("write")
    def delete_paciente(self, paciente_id: int) -> bool:
        return self._delete_row("pacientes", paciente_id, guards=[("registros", "paciente_id")])

    # ========== REGISTRO ==========

    @db_op("write")
    def create_registro(
        self,
        tipo: str,
        paciente_id: int,
        malote_id: int,
        waiting_docs: bool = False,
    ) -> Registro:
        now = datetime.now().isoformat()
        wd = 1 if waiting_docs else 0
        rid = self._insert_row(
            "registros",
            tipo=tipo,
            paciente_id=paciente_id,
            malote_id=malote_id,
            created_at=now,
            waiting_docs=wd,
        )
        return Registro(
            id=rid,
            tipo=tipo,
            paciente_id=paciente_id,
            malote_id=malote_id,
            created_at=now,
            waiting_docs=waiting_docs,
        )

    @db_op("read")
    def get_registro_by_id(self, registro_id: int) -> Optional[Registro]:
        row = self._fetch_one(
            "SELECT r.*, p.name as paciente_name, m.date as malote_date "
            "FROM registros r "
            "JOIN pacientes p ON r.paciente_id = p.id "
            "JOIN malotes m ON r.malote_id = m.id "
            "WHERE r.id = ?",
            (registro_id,),
        )
        return Registro.from_row(row) if row else None

    @db_op("read")
    def find_registro(
        self, tipo: str, paciente_id: int, malote_id: int
    ) -> Optional[Registro]:
        row = self._fetch_one(
            "SELECT r.*, p.name as paciente_name, m.date as malote_date "
            "FROM registros r "
            "JOIN pacientes p ON r.paciente_id = p.id "
            "JOIN malotes m ON r.malote_id = m.id "
            "WHERE r.tipo = ? AND r.paciente_id = ? AND r.malote_id = ? "
            "LIMIT 1",
            (tipo, paciente_id, malote_id),
        )
        return Registro.from_row(row) if row else None

    @db_op("read")
    def get_registros_by_malote(self, malote_id: int) -> list[Registro]:
        return [Registro.from_row(r) for r in self._fetch_all(
            "SELECT r.*, p.name as paciente_name "
            "FROM registros r "
            "JOIN pacientes p ON r.paciente_id = p.id "
            "WHERE r.malote_id = ? "
            "ORDER BY p.name COLLATE NOCASE",
            (malote_id,),
        )]

    @db_op("read")
    def get_registros_by_malote_and_tipo(
        self, malote_id: int, tipo: str
    ) -> list[Registro]:
        return [Registro.from_row(r) for r in self._fetch_all(
            "SELECT r.*, p.name as paciente_name "
            "FROM registros r "
            "JOIN pacientes p ON r.paciente_id = p.id "
            "WHERE r.malote_id = ? AND r.tipo = ? "
            "ORDER BY p.name COLLATE NOCASE",
            (malote_id, tipo),
        )]

    @db_op("write")
    def update_registro(self, registro_id: int, **fields) -> bool:
        allowed = {"tipo", "paciente_id", "malote_id", "waiting_docs"}
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "waiting_docs":
                updates[k] = 1 if v else 0
            else:
                updates[k] = v

        if not updates:
            return False

        with self._cursor() as cur:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [registro_id]
            try:
                cur.execute(
                    f"UPDATE registros SET {set_clause} WHERE id = ?",
                    values,
                )
                self._commit()
                return cur.rowcount > 0
            except sqlite3.IntegrityError:
                raise DuplicateRecordError(
                    f"Duplicate: tipo={updates.get('tipo')}, "
                    f"paciente_id={updates.get('paciente_id')}, "
                    f"malote_id={updates.get('malote_id')}"
                )

    @db_op("write")
    def delete_registro(self, registro_id: int) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM registros WHERE id = ?", (registro_id,))
            self._commit()
            return cur.rowcount > 0

    @db_op("read")
    def search_registros_by_paciente(
        self, query: str, active_malote_id: int | None = None, limit: int = 20
    ) -> list[Registro]:
        normalized = to_upper_normalized(query)
        return [Registro.from_row(r) for r in self._fetch_all(
            "SELECT r.*, p.name as paciente_name, m.date as malote_date "
            "FROM registros r "
            "JOIN pacientes p ON r.paciente_id = p.id "
            "JOIN malotes m ON r.malote_id = m.id "
            "WHERE p.name LIKE ? "
            "ORDER BY "
            "CASE WHEN r.malote_id = ? THEN 0 ELSE 1 END, "
            "m.date DESC, "
            "p.name COLLATE NOCASE "
            "LIMIT ?",
            (f"%{normalized}%", active_malote_id or 0, limit),
        )]

    @db_op("read")
    def get_registros_by_paciente(self, paciente_id: int) -> list[Registro]:
        return [Registro.from_row(r) for r in self._fetch_all(
            "SELECT r.*, p.name as paciente_name, m.date as malote_date "
            "FROM registros r "
            "JOIN pacientes p ON r.paciente_id = p.id "
            "JOIN malotes m ON r.malote_id = m.id "
            "WHERE r.paciente_id = ? "
            "ORDER BY m.date DESC, r.created_at DESC",
            (paciente_id,),
        )]

    # ========== REGISTRO ITEMS ==========

    @db_op("write")
    def set_registro_items(
        self, registro_id: int, items: list[tuple[int, int, str]]
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM registro_items WHERE registro_id = ?",
                (registro_id,),
            )
            if items:
                cur.executemany(
                    "INSERT INTO registro_items (registro_id, item_id, process_group, cid) VALUES (?, ?, ?, ?)",
                    [(registro_id, iid, pg, cid) for iid, pg, cid in items],
                )
            self._commit()

    @db_op("write")
    def set_registro_items_with_process(
        self, registro_id: int, items: list[tuple[int, int, int | None, str]]
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM registro_items WHERE registro_id = ?",
                (registro_id,),
            )
            if items:
                cur.executemany(
                    "INSERT INTO registro_items (registro_id, item_id, process_group, process_id, cid) VALUES (?, ?, ?, ?, ?)",
                    [
                        (registro_id, iid, pg, pid, cid)
                        for iid, pg, pid, cid in items
                    ],
                )
            self._commit()

    @db_op("read")
    def get_items_by_registro(self, registro_id: int) -> list[RegistroItem]:
        return [RegistroItem.from_row(r) for r in self._fetch_all(
            "SELECT ri.*, ic.name as item_name, ic.unidade "
            "FROM registro_items ri "
            "JOIN items_catalog ic ON ri.item_id = ic.id "
            "WHERE ri.registro_id = ? "
            "ORDER BY ri.process_group, ic.name COLLATE NOCASE",
            (registro_id,),
        )]

    @db_op("read")
    def get_items_by_paciente(self, paciente_id: int) -> list[ItemCatalog]:
        return [ItemCatalog.from_row(r) for r in self._fetch_all(
            "SELECT DISTINCT ri.item_id as id, ic.name, ic.unidade, ic.cids "
            "FROM registro_items ri "
            "JOIN registros r ON ri.registro_id = r.id "
            "JOIN items_catalog ic ON ri.item_id = ic.id "
            "WHERE r.paciente_id = ? "
            "ORDER BY ic.name COLLATE NOCASE",
            (paciente_id,),
        )]

    @db_op("read")
    def get_last_usage_by_paciente(self, paciente_id: int) -> list[tuple[int, str]]:
        rows = self._fetch_all(
            "SELECT ri.item_id, ri.cid "
            "FROM registro_items ri "
            "JOIN registros r ON ri.registro_id = r.id "
            "WHERE r.paciente_id = ? "
            "ORDER BY r.created_at DESC, r.id DESC",
            (paciente_id,),
        )
        seen: set[int] = set()
        result: list[tuple[int, str]] = []
        for row in rows:
            iid = row["item_id"]
            if iid in seen:
                continue
            seen.add(iid)
            result.append((iid, row["cid"] or ""))
        return result

    # ========== PROCESSES ==========

    @db_op("write")
    def set_processes(
        self,
        registro_id: int,
        processes: list[tuple[int, int, str | None]],
    ) -> list[Process]:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE registro_items SET process_id = NULL WHERE registro_id = ?",
                (registro_id,),
            )
            cur.execute(
                "DELETE FROM processes WHERE registro_id = ?",
                (registro_id,),
            )
            result = []
            for group_number, months_supply, expected_return_date in processes:
                cur.execute(
                    "INSERT INTO processes (registro_id, group_number, months_supply, expected_return_date) VALUES (?, ?, ?, ?)",
                    (registro_id, group_number, months_supply, expected_return_date),
                )
                result.append(Process(
                    id=cur.lastrowid,
                    registro_id=registro_id,
                    group_number=group_number,
                    months_supply=months_supply,
                    expected_return_date=expected_return_date,
                ))
            self._commit()
            return result

    @db_op("read")
    def get_processes_by_registro(self, registro_id: int) -> list[Process]:
        return [Process.from_row(r) for r in self._fetch_all(
            "SELECT * FROM processes WHERE registro_id = ? ORDER BY group_number",
            (registro_id,),
        )]

    @db_op("read")
    def get_malote_arrivals_between(self, start_iso: str, end_iso: str) -> list[str]:
        from rac.utils.date_calculator import calculate_arrival_date

        rows = self._fetch_all(
            "SELECT arrival_date, date FROM malotes ORDER BY date ASC",
        )
        result = []
        for r in rows:
            arrival = r["arrival_date"]
            if not arrival and r["date"]:
                try:
                    arrival = calculate_arrival_date(
                        date.fromisoformat(r["date"])
                    ).isoformat()
                except (ValueError, TypeError):
                    continue
            if arrival and start_iso <= arrival <= end_iso:
                result.append(arrival)
        return result

    @db_op("read")
    def count_return_dates_between(self, start_iso: str, end_iso: str) -> dict[str, int]:
        rows = self._fetch_all(
            "SELECT p.expected_return_date, COUNT(*) as cnt "
            "FROM processes p "
            "WHERE p.expected_return_date IS NOT NULL "
            "AND p.expected_return_date >= ? AND p.expected_return_date <= ? "
            "GROUP BY p.expected_return_date",
            (start_iso, end_iso),
        )
        return {r["expected_return_date"]: r["cnt"] for r in rows}

    @db_op("read")
    def get_earlier_malote(self, current_malote_id: int) -> Optional[Malote]:
        current = self.get_malote_by_id(current_malote_id)
        if not current:
            return None
        row = self._fetch_one(
            "SELECT * FROM malotes WHERE date < ? ORDER BY date DESC LIMIT 1",
            (current.date,),
        )
        return Malote.from_row(row) if row else None

    # ========== ITEMS CATALOG ==========

    @db_op("read")
    def get_all_items(self) -> list[ItemCatalog]:
        return [ItemCatalog.from_row(r) for r in self._fetch_all_table(
            "items_catalog", "name COLLATE NOCASE"
        )]

    @db_op("read")
    def search_items(self, query: str, limit: int = 10) -> list[ItemCatalog]:
        return [ItemCatalog.from_row(r) for r in self._search_by_name(
            "items_catalog", "name", query, limit,
        )]

    @db_op("write")
    def create_item(self, name: str, unidade: str = "un", cids: str = "") -> ItemCatalog:
        normalized = to_upper_normalized(name.strip())
        iid = self._insert_row("items_catalog", name=normalized, unidade=unidade, cids=cids)
        return ItemCatalog(id=iid, name=normalized, unidade=unidade, cids=cids)

    @db_op("write")
    def update_item(self, item_id: int, name: str) -> bool:
        return self._update_row(
            "items_catalog", item_id, name=to_upper_normalized(name.strip())
        )

    @db_op("write")
    def update_item_cids(self, item_id: int, cids: str) -> bool:
        return self._update_row("items_catalog", item_id, cids=cids)

    @db_op("write")
    def delete_item(self, item_id: int) -> bool:
        return self._delete_row(
            "items_catalog", item_id, guards=[("registro_items", "item_id")]
        )

    # ========== PACIENTE (listagem) ==========

    @db_op("read")
    def get_all_pacientes(self) -> list[Paciente]:
        return [Paciente.from_row(r) for r in self._fetch_all_table(
            "pacientes", "name COLLATE NOCASE"
        )]

    @db_op("read")
    def get_all_pacientes_with_last_registro(self) -> list[Paciente]:
        return [Paciente.from_row(r) for r in self._fetch_all(
            "SELECT p.id, p.name, "
            "lr.tipo AS last_registro_tipo, "
            "lm.date AS last_registro_date "
            "FROM pacientes p "
            "LEFT JOIN registros lr ON lr.id = ("
            "  SELECT r.id FROM registros r "
            "  JOIN malotes m ON r.malote_id = m.id "
            "  WHERE r.paciente_id = p.id "
            "  ORDER BY m.date DESC, r.created_at DESC "
            "  LIMIT 1"
            ") "
            "LEFT JOIN malotes lm ON lm.id = lr.malote_id "
            "ORDER BY p.name COLLATE NOCASE"
        )]

    # ========== EXPORT HELPERS ==========

    @db_op("read")
    def dump_all_tables(self) -> dict[str, list[dict]]:
        return {
            name: self._fetch_all_table(name)
            for name in (
                "malotes",
                "pacientes",
                "items_catalog",
                "registros",
                "processes",
                "registro_items",
            )
        }

    @db_op("read")
    def get_registros_with_items_by_malote(
        self, malote_id: int
    ) -> list[RegistroExport]:
        from rac.models import ProcessExport

        rows = self._fetch_all(
            "SELECT r.id, r.tipo, r.paciente_id, p.name as paciente_name, "
            "ic.name as item_name, ri.process_group, "
            "pr.expected_return_date, pr.group_number as process_group_number "
            "FROM registros r "
            "JOIN pacientes p ON r.paciente_id = p.id "
            "LEFT JOIN registro_items ri ON ri.registro_id = r.id "
            "LEFT JOIN items_catalog ic ON ri.item_id = ic.id "
            "LEFT JOIN processes pr ON pr.id = ri.process_id "
            "WHERE r.malote_id = ? AND r.waiting_docs = 0 "
            "ORDER BY r.tipo, p.name COLLATE NOCASE, ri.process_group, ic.name",
            (malote_id,),
        )

        registros_map: dict[int, RegistroExport] = {}
        groups_map: dict[int, dict[int, list[str]]] = {}
        return_dates_map: dict[int, dict[int, str | None]] = {}
        for r in rows:
            reg_id = r["id"]
            if reg_id not in registros_map:
                registros_map[reg_id] = RegistroExport.from_row(r)
                groups_map[reg_id] = {}
                return_dates_map[reg_id] = {}
            item_name = r.get("item_name")
            if item_name:
                pg = r.get("process_group", 1) or 1
                groups_map[reg_id].setdefault(pg, []).append(item_name)
                if pg not in return_dates_map[reg_id]:
                    return_dates_map[reg_id][pg] = r.get("expected_return_date")

        for reg_id, groups in groups_map.items():
            sorted_groups = sorted(groups.items(), key=operator.itemgetter(0))
            registros_map[reg_id].processes = [
                ProcessExport(
                    group_number=pg,
                    items=items,
                    expected_return_date=return_dates_map.get(reg_id, {}).get(pg),
                )
                for pg, items in sorted_groups if items
            ]

        return list(registros_map.values())

    # ========== STATISTICS ==========

    def _stats_where(
        self,
        tipo: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> tuple[str, list]:
        clauses: list[str] = []
        params: list = []
        if tipo:
            clauses.append("r.tipo = ?")
            params.append(tipo)
        if date_from:
            clauses.append("m.date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("m.date <= ?")
            params.append(date_to)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, params

    @db_op("read")
    def get_stats_by_tipo(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        with self._cursor() as cur:
            where, params = self._stats_where( date_from=date_from, date_to=date_to)
            cur.execute(
                f"SELECT r.tipo, "
                f"COUNT(*) AS registros, "
                f"COUNT(DISTINCT r.paciente_id) AS pacientes "
                f"FROM registros r JOIN malotes m ON r.malote_id = m.id{where} "
                f"GROUP BY r.tipo ORDER BY r.tipo",
                params,
            )
            tipo_rows = [dict(r) for r in cur.fetchall()]
            cur.execute(
                f"SELECT r.tipo, COUNT(DISTINCT ri.item_id) AS items "
                f"FROM registro_items ri "
                f"JOIN registros r ON ri.registro_id = r.id "
                f"JOIN malotes m ON r.malote_id = m.id{where} "
                f"GROUP BY r.tipo",
                params,
            )
            item_map = {dict(r)["tipo"]: dict(r)["items"] for r in cur.fetchall()}
            for row in tipo_rows:
                row["items"] = item_map.get(row["tipo"], 0)
            return tipo_rows

    @db_op("read")
    def get_stats_totals(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict:
        with self._cursor() as cur:
            where, params = self._stats_where( date_from=date_from, date_to=date_to)
            cur.execute(
                f"SELECT COUNT(*) AS registros, "
                f"COUNT(DISTINCT paciente_id) AS pacientes "
                f"FROM registros r JOIN malotes m ON r.malote_id = m.id{where}",
                params,
            )
            return dict(cur.fetchone())

    @db_op("read")
    def get_malote_date_range(self) -> tuple[str | None, str | None]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT MIN(date) AS dmin, MAX(date) AS dmax FROM malotes"
            )
            row = cur.fetchone()
            if row and row["dmin"]:
                return row["dmin"], row["dmax"]
            return None, None

    @db_op("read")
    def get_stats_top_itens(
        self,
        tipo: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict]:
        with self._cursor() as cur:
            where, params = self._stats_where( tipo, date_from, date_to)
            cur.execute(
                f"SELECT ic.name AS medicamento, COUNT(*) AS registros "
                f"FROM registro_items ri "
                f"JOIN items_catalog ic ON ri.item_id = ic.id "
                f"JOIN registros r ON ri.registro_id = r.id "
                f"JOIN malotes m ON r.malote_id = m.id{where} "
                f"GROUP BY ri.item_id ORDER BY registros DESC",
                params,
            )
            return [dict(r) for r in cur.fetchall()]
