#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Banco de dados unificado do Emissor (pacientes, itens, retiradas)."""

import sqlite3

from typing import Any, Dict, List, Optional, Tuple, cast

from andaime.database import BaseDatabase, db_op
from andaime.paths import resolve_db_path
from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from andaime.dates import parse_date
from emissor.utils.patient_fields_config import (
    TYPE_ENUM,
    get_all_patient_data_fields,
    get_field_config,
)
from emissor.database.migrations import DatabaseMigrator
from emissor.database.models import Patient, PatientItem, Retirada, RetiradaItem


def _is_enum_field(field_name: str) -> bool:
    """Verifica se um campo é enum (não deve ser uppercased ao salvar)."""
    config = get_field_config(field_name)
    return config is not None and config.get("type") == TYPE_ENUM


class EmissorDatabase(BaseDatabase):
    """Banco unificado: pacientes, itens, catálogo e retiradas em SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        """Inicializa o banco unificado."""
        if db_path is None:
            db_path = resolve_db_path("emissor.db", create_dir=True)

        super().__init__(db_path=str(db_path), entity_name="emissor")

    def _resolve_default_db_path(self) -> str:
        """Resolve caminho padrão para emissor.db"""
        return resolve_db_path("emissor.db", create_dir=True)

    def _log_initialization_success(self) -> None:
        """Log mensagem de sucesso com estatísticas"""
        try:
            pacientes_count = self._fetch_count("pacientes")
            items_count = self._fetch_count("items_catalog")
            retiradas_count = self._fetch_count("retiradas")

            ErrorHandler.log(
                f"EmissorDatabase inicializado: {pacientes_count} pacientes, "
                f"{items_count} itens no catálogo, {retiradas_count} retiradas",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )
        except Exception:
            super()._log_initialization_success()

    # ========================================================================
    # SCHEMA
    # ========================================================================

    def _create_schema(self) -> None:
        """Cria o schema completo do banco unificado."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")

        pacientes_columns = [
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            "nome TEXT NOT NULL UNIQUE",
            "processo_n TEXT",
            "profissional_id INTEGER REFERENCES profissionais(id) ON DELETE SET NULL",
        ]
        for i in range(2, 11):
            pacientes_columns.append(f"processo_{i}_n TEXT")
        for field_name in get_all_patient_data_fields():
            if field_name != "processo_n":
                pacientes_columns.append(f"{field_name} TEXT")

        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS pacientes (
                {', '.join(pacientes_columns)}
            )
        """)

        # Tabela mestre de profissionais (normalização v5).
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS profissionais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT UNIQUE NOT NULL,
                crm TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items_catalog (
                item_id TEXT PRIMARY KEY,
                descricao TEXT NOT NULL UNIQUE,
                unidade TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS patient_items (
                patient_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                quantidade TEXT,
                dias TEXT,
                PRIMARY KEY (patient_id, item_id),
                FOREIGN KEY (patient_id) REFERENCES pacientes(id) ON DELETE RESTRICT,
                FOREIGN KEY (item_id) REFERENCES items_catalog(item_id) ON UPDATE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retiradas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL,
                patient_name TEXT NOT NULL,
                data_retirada TEXT NOT NULL,
                data_proxima_retirada TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                substituida INTEGER NOT NULL DEFAULT 0,
                UNIQUE(patient_id, data_retirada),
                FOREIGN KEY (patient_id) REFERENCES pacientes(id) ON DELETE RESTRICT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retirada_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                retirada_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                descricao TEXT NOT NULL,
                unidade TEXT,
                quantidade TEXT,
                dias TEXT,
                ignorar_suficiencia INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (retirada_id) REFERENCES retiradas(id) ON DELETE CASCADE
            )
        """)

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_pacientes_nome ON pacientes(nome)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_profissionais_nome ON profissionais(nome)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_catalog_desc ON items_catalog(descricao)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_patient_items_patient ON patient_items(patient_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_retiradas_patient ON retiradas(patient_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_retiradas_proxima ON retiradas(data_proxima_retirada)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_retirada_items_retirada ON retirada_items(retirada_id)"
        )

        # Garantir coluna substituida em bancos existentes
        cursor.execute("PRAGMA table_info(retiradas)")
        retirada_cols = {row[1] for row in cursor.fetchall()}
        if "substituida" not in retirada_cols:
            cursor.execute(
                "ALTER TABLE retiradas ADD COLUMN substituida INTEGER NOT NULL DEFAULT 0"
            )

        # Garantir coluna ignorar_suficiencia em bancos existentes
        cursor.execute("PRAGMA table_info(retirada_items)")
        item_cols = {row[1] for row in cursor.fetchall()}
        if "ignorar_suficiencia" not in item_cols:
            cursor.execute(
                "ALTER TABLE retirada_items ADD COLUMN ignorar_suficiencia INTEGER NOT NULL DEFAULT 0"
            )

        self._commit()

        if self.db_path != ":memory:":
            DatabaseMigrator.sync_definitive_catalog(cursor, self.conn, self.db_path)
            DatabaseMigrator.flatten_patient_data(cursor, self.conn, self.db_path)
            DatabaseMigrator.mark_superseded_retiradas(cursor, self.conn, self.db_path)
            DatabaseMigrator.normalize_ultima_receita(cursor, self.conn, self.db_path)
            DatabaseMigrator.normalize_profissionais(cursor, self.conn, self.db_path)

    # ========================================================================
    # HELPERS
    # ========================================================================

    def _fetch_retirada_items(
        self, cursor: Any, retirada_id: int
    ) -> list[RetiradaItem]:
        """Busca itens de uma retirada."""
        cursor.execute(
            "SELECT item_id, descricao, unidade, quantidade, dias "
            "FROM retirada_items WHERE retirada_id = ? ORDER BY id",
            (retirada_id,),
        )
        return [RetiradaItem.from_row(r) for r in cursor.fetchall()]

    # ========================================================================
    # PACIENTES
    # ========================================================================

    @db_op("read")
    def get_all_patient_names(self) -> List[Dict[str, Any]]:
        """Retorna ID e nome de todos os pacientes."""
        return self._fetch_all_table("pacientes")

    @db_op("read")
    def get_patient_by_id(self, patient_id: int) -> Optional[Patient]:
        """Retorna paciente completo por ID."""
        self._ensure_connection()

        with self._cursor() as cur:
            cur.execute(
                "SELECT p.*, pr.nome AS profissional_nome, pr.crm AS profissional_crm "
                "FROM pacientes p "
                "LEFT JOIN profissionais pr ON p.profissional_id = pr.id "
                "WHERE p.id = ?",
                (patient_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            patient = Patient.from_row(row)

            cur.execute(
                "SELECT pi.item_id, ic.descricao, ic.unidade, pi.quantidade, pi.dias "
                "FROM patient_items pi LEFT JOIN items_catalog ic ON pi.item_id = ic.item_id "
                "WHERE pi.patient_id = ? ORDER BY pi.item_id",
                (patient_id,),
            )
            patient.itens = [PatientItem.from_row(r) for r in cur.fetchall()]

            # Flag leve p/ habilitar "Abrir PDF" sem consulta extra em seguida.
            cur.execute(
                "SELECT 1 FROM retiradas WHERE patient_id = ? LIMIT 1",
                (patient_id,),
            )
            patient.tem_retirada = cur.fetchone() is not None

        return patient

    @db_op("write")
    def add_patient(self, nome: str) -> Dict:
        """Adiciona novo paciente."""
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO pacientes (nome) VALUES (?)", (nome.strip().upper(),)
            )
            new_id = cur.lastrowid
            self._commit()

        ErrorHandler.log(
            f"Novo paciente criado: {nome.strip().upper()} (ID: {new_id})",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )
        return {"id": new_id, "nome": nome.strip().upper()}

    @db_op("write")
    def update_patient(self, patient_id: int, data: Dict) -> bool:
        """Atualiza dados de um paciente (metadata + itens)."""
        with self._cursor() as cur:
            data = data.copy()
            items = data.pop("itens", None)
            self._update_metadata(cur, patient_id, data)
            if items is not None:
                self._sync_patient_items(cur, patient_id, items)
            self._commit()
        return True

    def _update_metadata(self, cur: Any, patient_id: int, data: Dict) -> None:
        data.pop("id", None)
        data.pop("nome", None)

        allowed = set(get_all_patient_data_fields())
        allowed.add("processo_n")
        allowed.add("profissional_id")
        for i in range(2, 11):
            allowed.add(f"processo_{i}_n")

        filtered = {k: v for k, v in data.items() if k in allowed}
        if not filtered:
            return

        set_clauses: list[str] = []
        values: list[Any] = []
        for key, v in filtered.items():
            if key == "ultima_receita" and isinstance(v, str) and v.strip():
                parsed = parse_date(v.strip())
                values.append(parsed.strftime("%Y-%m-%d") if parsed else "")
            elif isinstance(v, str) and not _is_enum_field(key):
                values.append(v.strip().upper())
            else:
                values.append(v)
            set_clauses.append(f"{key} = ?")
        values.append(patient_id)
        cur.execute(
            f"UPDATE pacientes SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )

    def _sync_patient_items(self, cur: Any, patient_id: int, items: list) -> None:
        cur.execute("DELETE FROM patient_items WHERE patient_id = ?", (patient_id,))
        for item in items:
            item_id = (
                item.get("item_id", "").strip()
                if isinstance(item, dict)
                else item.item_id.strip()
            )
            if not item_id:
                continue

            cur.execute(
                "SELECT descricao, unidade FROM items_catalog WHERE item_id = ?",
                (item_id,),
            )
            existing_by_id = cur.fetchone()

            if not existing_by_id:
                descricao = (
                    item.get("descricao", "").strip()
                    if isinstance(item, dict)
                    else item.descricao.strip()
                )
                cur.execute(
                    "SELECT item_id, unidade FROM items_catalog WHERE descricao = ?",
                    (descricao,),
                )
                existing_by_desc = cur.fetchone()

                if existing_by_desc and descricao:
                    ErrorHandler.log(
                        f"Item ID '{item_id}' não encontrado no catálogo. "
                        f"Descrição '{descricao}' existe com ID '{existing_by_desc['item_id']}'. Item ignorado.",
                        level=ErrorLevel.WARNING,
                        context=ErrorContext.DATABASE,
                    )
                    continue
                else:
                    unidade = (
                        item.get("unidade", "")
                        if isinstance(item, dict)
                        else item.unidade
                    )
                    cur.execute(
                        "INSERT INTO items_catalog (item_id, descricao, unidade) VALUES (?, ?, ?)",
                        (item_id, descricao, unidade),
                    )
                    ErrorHandler.log(
                        f"Novo item adicionado ao catálogo: {item_id} - {descricao}",
                        level=ErrorLevel.INFO,
                        context=ErrorContext.DATABASE,
                    )

            quantidade = (
                item.get("quantidade") if isinstance(item, dict) else item.quantidade
            )
            dias = item.get("dias") if isinstance(item, dict) else item.dias
            cur.execute(
                "INSERT OR REPLACE INTO patient_items (patient_id, item_id, quantidade, dias) VALUES (?, ?, ?, ?)",
                (patient_id, item_id, quantidade, dias),
            )

    @db_op("write")
    def delete_patient(self, patient_id: int) -> bool:
        """Deleta paciente mantendo registros históricos intactos."""
        try:
            self._ensure_connection()
            with self._cursor() as cur:
                cur.execute("PRAGMA foreign_keys = OFF")
                try:
                    cur.execute(
                        "SELECT nome FROM pacientes WHERE id = ?", (patient_id,)
                    )
                    patient = cur.fetchone()
                    if not patient:
                        self._rollback()
                        return False

                    cur.execute("DELETE FROM pacientes WHERE id = ?", (patient_id,))
                    self._commit()
                finally:
                    cur.execute("PRAGMA foreign_keys = ON")

            ErrorHandler.log(
                f"Paciente '{patient['nome']}' (ID: {patient_id}) deletado. Dados históricos mantidos.",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )
            return True
        except sqlite3.OperationalError:
            raise
        except Exception as e:
            ErrorHandler.handle_database_error(e, operation="deletar paciente")
            return False

    # ========================================================================
    # ITEMS CATALOG
    # ========================================================================

    @db_op("read")
    def get_all_catalog_items(self) -> List[Dict]:
        """Retorna todos os itens do catálogo."""
        return self._fetch_all(
            "SELECT item_id, descricao, unidade FROM items_catalog ORDER BY descricao"
        )

    @db_op("read")
    def get_all_profissionais(self) -> List[Dict[str, Any]]:
        """Retorna todos os profissionais da tabela mestre (para autocomplete)."""
        return self._fetch_all(
            "SELECT id, nome, crm FROM profissionais ORDER BY nome"
        )

    @db_op("read")
    def get_profissional(self, profissional_id: int) -> Optional[Dict[str, Any]]:
        """Retorna a linha mestre do profissional pelo id."""
        return self._fetch_one(
            "SELECT id, nome, crm FROM profissionais WHERE id = ?",
            (profissional_id,),
        )

    @db_op("write")
    def upsert_profissional(self, nome: str, crm: str = "") -> Optional[int]:
        """Cria ou atualiza um profissional mestre, retorna seu id.

        Nomes são armazenados em maiúsculas; CRM vazio preserva o existente.
        """
        nome = (nome or "").strip().upper()
        if not nome:
            return None
        crm = (crm or "").strip().upper()

        with self._cursor() as cur:
            cur.execute(
                "SELECT id, crm FROM profissionais WHERE nome = ?", (nome,)
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "INSERT INTO profissionais (nome, crm) VALUES (?, ?)",
                    (nome, crm),
                )
                prof_id = cur.lastrowid
                ErrorHandler.log(
                    f"Novo profissional criado: {nome} (ID: {prof_id})",
                    level=ErrorLevel.INFO,
                    context=ErrorContext.DATABASE,
                )
            else:
                prof_id = row["id"]
                existing_crm = row["crm"] or ""
                if crm and crm != existing_crm:
                    cur.execute(
                        "UPDATE profissionais SET crm = ? WHERE id = ?",
                        (crm, prof_id),
                    )
            self._commit()
        return cast(int, prof_id)

    # ========================================================================
    # RETIRADAS
    # ========================================================================

    def _mark_superseded_retiradas(
        self,
        cur: Any,
        patient_id: int,
        new_retirada_id: int,
        data_retirada: str,
        items: List[Dict],
    ) -> None:
        """Marca retiradas anteriores do paciente (mesmo item) como substituídas."""
        new_item_ids = {
            item.get("item_id", "") for item in items if item.get("item_id")
        }
        if not new_item_ids:
            return

        cur.execute(
            "SELECT id FROM retiradas "
            "WHERE patient_id = ? AND id != ? AND substituida = 0 "
            "AND data_proxima_retirada >= ?",
            (patient_id, new_retirada_id, data_retirada),
        )
        candidate_ids = [row["id"] for row in cur.fetchall()]

        for cid in candidate_ids:
            cur.execute(
                "SELECT item_id FROM retirada_items WHERE retirada_id = ?",
                (cid,),
            )
            prev_item_ids = {row["item_id"] for row in cur.fetchall()}
            if new_item_ids & prev_item_ids:
                cur.execute(
                    "UPDATE retiradas SET substituida = 1 WHERE id = ?",
                    (cid,),
                )
                ErrorHandler.log(
                    f"Retirada ID {cid} marcada como substituída por "
                    f"ID {new_retirada_id}",
                    level=ErrorLevel.INFO,
                    context=ErrorContext.DATABASE,
                )

    @db_op("write")
    def save_retirada(
        self,
        patient_id: int,
        patient_name: str,
        data_retirada: str,
        data_proxima_retirada: str,
        items: List[Dict],
        ignorar_itens: Optional[List[Tuple[str, str]]] = None,
    ) -> Optional[int]:
        """Salva ou atualiza retirada com itens (snapshot).

        Se ``ignorar_itens`` for informado, marca os itens correspondentes
        de retiradas ANTERIORES como ignorados para suficiência (a nova
        retirada passa a ser a linha de base).
        """
        try:
            self._ensure_connection()
            with self._cursor() as cur:
                cur.execute(
                    "SELECT id FROM retiradas WHERE patient_id = ? AND data_retirada = ?",
                    (patient_id, data_retirada),
                )
                existing = cur.fetchone()

                if existing:
                    retirada_id = existing["id"]
                    cur.execute(
                        "UPDATE retiradas SET patient_name = ?, data_proxima_retirada = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (patient_name, data_proxima_retirada, retirada_id),
                    )
                    cur.execute(
                        "DELETE FROM retirada_items WHERE retirada_id = ?",
                        (retirada_id,),
                    )
                    ErrorHandler.log(
                        f"Retirada atualizada: ID {retirada_id}",
                        level=ErrorLevel.INFO,
                        context=ErrorContext.DATABASE,
                    )
                else:
                    cur.execute(
                        "INSERT INTO retiradas (patient_id, patient_name, data_retirada, data_proxima_retirada) VALUES (?, ?, ?, ?)",
                        (
                            patient_id,
                            patient_name,
                            data_retirada,
                            data_proxima_retirada,
                        ),
                    )
                    retirada_id = cur.lastrowid
                    ErrorHandler.log(
                        f"Nova retirada: ID {retirada_id}",
                        level=ErrorLevel.INFO,
                        context=ErrorContext.DATABASE,
                    )

                # Marca itens de retiradas anteriores como ignorados (reset).
                if ignorar_itens:
                    self._mark_items_ignored(
                        cur, patient_id, data_retirada, ignorar_itens
                    )

                for item in items:
                    cur.execute(
                        "INSERT INTO retirada_items (retirada_id, item_id, descricao, unidade, quantidade, dias, ignorar_suficiencia) VALUES (?, ?, ?, ?, ?, ?, 0)",
                        (
                            retirada_id,
                            item.get("item_id", ""),
                            item.get("descricao", ""),
                            item.get("unidade", ""),
                            item.get("quantidade", ""),
                            item.get("dias", ""),
                        ),
                    )

                self._mark_superseded_retiradas(
                    cur, patient_id, retirada_id, data_retirada, items
                )

                self._commit()
            return cast(int | None, retirada_id)
        except sqlite3.OperationalError:
            raise
        except Exception as e:
            self._rollback()
            ErrorHandler.handle_database_error(
                e,
                operation="salvar retirada",
                recovery_hint="Verifique se todos os dados são válidos.",
            )
            return None

    @staticmethod
    def _mark_items_ignored(
        cur: Any,
        patient_id: int,
        data_retirada: str,
        ignorar_itens: List[Tuple[str, str]],
    ) -> None:
        """Marca itens de retiradas anteriores como ignorados para suficiência.

        Para cada (item_id, descricao), marca retirada_items correspondentes
        de retiradas anteriores à data_retirada informada.
        """
        for item_id, descricao in ignorar_itens:
            if item_id:
                cur.execute(
                    "UPDATE retirada_items SET ignorar_suficiencia = 1 "
                    "WHERE ignorar_suficiencia = 0 "
                    "AND retirada_id IN ("
                    "  SELECT r.id FROM retiradas r "
                    "  WHERE r.patient_id = ? AND r.data_retirada < ?"
                    ") AND item_id = ?",
                    (patient_id, data_retirada, item_id),
                )
            norm_desc = " ".join(descricao.lower().split())
            if norm_desc:
                cur.execute(
                    "UPDATE retirada_items SET ignorar_suficiencia = 1 "
                    "WHERE ignorar_suficiencia = 0 "
                    "AND retirada_id IN ("
                    "  SELECT r.id FROM retiradas r "
                    "  WHERE r.patient_id = ? AND r.data_retirada < ?"
                    ") AND lower(trim(descricao)) = ?",
                    (patient_id, data_retirada, norm_desc),
                )

    @db_op("read")
    def get_retirada_by_date(
        self, patient_id: int, data_retirada: str
    ) -> Optional[Retirada]:
        """Retorna retirada por paciente e data."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM retiradas WHERE patient_id = ? AND data_retirada = ?",
                (patient_id, data_retirada),
            )
            row = cur.fetchone()
            if not row:
                return None

            retirada = Retirada.from_row(
                row, items=self._fetch_retirada_items(cur, row["id"])
            )
        return retirada

    @db_op("read")
    def get_retiradas_by_patient(self, patient_id: int) -> list[Retirada]:
        """Retorna todas as retiradas de um paciente (sem itens)."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT id, patient_id, patient_name, data_retirada, data_proxima_retirada, substituida, created_at, updated_at "
                "FROM retiradas WHERE patient_id = ? ORDER BY data_retirada DESC",
                (patient_id,),
            )
            return [Retirada.from_row(r) for r in cur.fetchall()]

    @db_op("read")
    def get_all_retiradas(self) -> list[Retirada]:
        """Retorna todas as retiradas (para agenda), incluindo tipo do paciente."""
        with self._cursor() as cur:
            cur.execute(
                "SELECT r.id, r.patient_id, r.patient_name, r.data_retirada, "
                "r.data_proxima_retirada, r.created_at, r.updated_at, p.tipo "
                "FROM retiradas r LEFT JOIN pacientes p ON r.patient_id = p.id "
                "WHERE r.substituida = 0 "
                "ORDER BY r.data_retirada DESC"
            )
            return [Retirada.from_row(r) for r in cur.fetchall()]

    @db_op("read")
    def count_retiradas_by_proxima_date(
        self, start_date: str, end_date: str
    ) -> Dict[str, int]:
        """Conta retiradas agrupadas por data_proxima_retirada."""
        rows = self._fetch_all(
            "SELECT data_proxima_retirada, COUNT(*) as count FROM retiradas "
            "WHERE data_proxima_retirada BETWEEN ? AND ? "
            "GROUP BY data_proxima_retirada ORDER BY data_proxima_retirada",
            (start_date, end_date),
        )
        return {row["data_proxima_retirada"]: row["count"] for row in rows}

    @db_op("read")
    def get_patient_item_dispensation_history(
        self, patient_id: int
    ) -> List[Dict[str, str]]:
        """Retorna histórico de dispensações por item (exclui itens resetados)."""
        self._ensure_connection()
        with self._cursor():
            rows = self._fetch_all(
                "SELECT ri.item_id, ri.descricao, r.data_retirada, ri.dias "
                "FROM retiradas r "
                "JOIN retirada_items ri ON ri.retirada_id = r.id "
                "WHERE r.patient_id = ? AND ri.ignorar_suficiencia = 0 "
                "ORDER BY r.data_retirada ASC, r.id ASC",
                (patient_id,),
            )
        return [dict(r) for r in rows]

    @db_op("write")
    def delete_retirada(self, retirada_id: int) -> bool:
        """Deleta uma retirada (FK CASCADE deleta itens)."""
        try:
            self._ensure_connection()
            with self._cursor() as cur:
                cur.execute("DELETE FROM retiradas WHERE id = ?", (retirada_id,))
                self._commit()
                if cur.rowcount > 0:
                    ErrorHandler.log(
                        f"Retirada ID {retirada_id} deletada",
                        level=ErrorLevel.INFO,
                        context=ErrorContext.DATABASE,
                    )
                    return True
                ErrorHandler.log(
                    f"Retirada ID {retirada_id} não encontrada",
                    level=ErrorLevel.WARNING,
                    context=ErrorContext.DATABASE,
                )
                return False
        except sqlite3.OperationalError:
            raise
        except Exception as e:
            ErrorHandler.handle_database_error(e, operation="deletar retirada")
            return False
