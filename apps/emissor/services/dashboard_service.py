#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camada de serviço CRUD/introspecção para o Dashboard de bancos."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from andaime.paths import resolve_db_path


class DashboardService:
    """Serviço de leitura e escrita para o Dashboard."""

    DATABASE_PATHS: dict[str, Callable[[], Path]] = {
        "emissor": lambda: Path(resolve_db_path("emissor.db", create_dir=True)),
        "medications": lambda: Path(resolve_db_path("medications.db", create_dir=True)),
    }

    DATABASE_TABLES: dict[str, list[str]] = {
        "emissor": [
            "pacientes",
            "items_catalog",
            "patient_items",
            "retiradas",
            "retirada_items",
        ],
        "medications": [
            "medications",
            "medications_itanhaem",
            "cartilhas",
            "dispensation_locations",
            "dispensation_locations_itanhaem",
        ],
    }

    NON_EDITABLE_COLUMNS: dict[str, list[str]] = {
        "pacientes": ["id"],
        "items_catalog": ["created_at"],
        "retiradas": ["id", "created_at", "updated_at"],
        "retirada_items": ["id"],
        "patient_items": [],
        "medications": ["id", "code", "created_at"],
        "cartilhas": ["id", "downloaded_at"],
        "dispensation_locations": ["id"],
        "medications_itanhaem": ["id", "code", "created_at"],
        "dispensation_locations_itanhaem": ["id"],
    }

    def __init__(
        self,
        database_paths: dict[str, Callable[[], Path]] | None = None,
        database_tables: dict[str, list[str]] | None = None,
        non_editable_columns: dict[str, list[str]] | None = None,
    ) -> None:
        """Inicializa o serviço do Dashboard."""
        self._database_paths = database_paths or self.DATABASE_PATHS
        self._database_tables = database_tables or self.DATABASE_TABLES
        self._non_editable_columns = (
            non_editable_columns or self.NON_EDITABLE_COLUMNS
        )
        self._db_paths: dict[str, Path] = {}

    def connect_databases(self) -> dict[str, Path]:
        """Resolve e armazena os caminhos dos bancos disponíveis."""
        self._db_paths = {}
        for db_name, path_fn in self._database_paths.items():
            try:
                db_path = path_fn()
                if db_path.exists():
                    self._db_paths[db_name] = db_path
                    print(f"[INFO] Database path registered: {db_name}: {db_path}")
                else:
                    print(f"[WARN] Database not found: {db_path}")
            except Exception as e:
                print(f"[ERROR] Failed to register {db_name}: {e}")
        return self._db_paths

    def get_available_databases(self) -> list[str]:
        """Retorna os nomes dos bancos disponíveis."""
        return list(self._db_paths.keys())

    def _get_connection(self, db_name: str) -> sqlite3.Connection:
        """Obtém conexão SQLite de curta duração (row_factory + busy_timeout)."""
        db_path = self._db_paths.get(db_name)
        if not db_path:
            raise ValueError(f"Banco de dados não encontrado: {db_name}")

        conn = sqlite3.connect(str(db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()
        return conn

    def _validate_table(self, db_name: str, table_name: str) -> None:
        """Valida se a tabela está na whitelist do banco."""
        allowed_tables = self._database_tables.get(db_name, [])
        if table_name not in allowed_tables:
            raise ValueError(
                f"Tabela '{table_name}' não permitida no banco '{db_name}'"
            )

    def get_tables(self, db_name: str) -> list[tuple[str, int]]:
        """Retorna tabelas permitidas e suas contagens de registros."""
        conn = self._get_connection(db_name)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            allowed_tables = self._database_tables.get(db_name, [])
            result: list[tuple[str, int]] = []
            for row in cursor.fetchall():
                table_name = row[0]
                if table_name not in allowed_tables:
                    continue
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                result.append((table_name, int(count)))
            return result
        finally:
            conn.close()

    def _get_table_info(self, db_name: str, table_name: str) -> list[tuple]:
        """Retorna as linhas de PRAGMA table_info (colunas completas)."""
        conn = self._get_connection(db_name)
        try:
            cursor = conn.cursor()
            cursor.execute(f"PRAGMA table_info({table_name})")
            return cursor.fetchall()
        finally:
            conn.close()

    def get_table_schema(self, db_name: str, table_name: str) -> dict[str, Any]:
        """Retorna schema (column_names, pk_columns, columns_info) da tabela."""
        self._validate_table(db_name, table_name)
        columns_info = self._get_table_info(db_name, table_name)
        column_names = [col[1] for col in columns_info]
        pk_columns = [col[1] for col in columns_info if col[5] > 0]
        return {
            "column_names": column_names,
            "pk_columns": pk_columns,
            "columns_info": columns_info,
        }

    def get_table_rows(
        self, db_name: str, table_name: str, filter_text: str = ""
    ) -> list[sqlite3.Row]:
        """Retorna registros da tabela (filtro opcional em todas as colunas)."""
        self._validate_table(db_name, table_name)
        conn = self._get_connection(db_name)
        try:
            column_names = [col[1] for col in self._get_table_info(db_name, table_name)]
            cursor = conn.cursor()

            if filter_text:
                where_clauses = " OR ".join(
                    [f"CAST({col} AS TEXT) LIKE ?" for col in column_names]
                )
                query = f"SELECT * FROM {table_name} WHERE {where_clauses}"
                params = [f"%{filter_text}%"] * len(column_names)
                cursor.execute(query, params)
            else:
                cursor.execute(f"SELECT * FROM {table_name}")

            return cursor.fetchall()
        finally:
            conn.close()

    def update_record(
        self,
        db_name: str,
        table_name: str,
        pk_columns: list[str],
        pk_values: dict[str, Any],
        column_name: str,
        value: Any,
    ) -> None:
        """Atualiza uma célula de um registro pela chave primária."""
        self._validate_table(db_name, table_name)
        conn = self._get_connection(db_name)
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            db_value = None if value == "" else value
            where_clauses = " AND ".join([f"{pk} = ?" for pk in pk_columns])
            params = [db_value] + [pk_values.get(pk) for pk in pk_columns]
            query = f"""
                UPDATE {table_name}
                SET {column_name} = ?
                WHERE {where_clauses}
            """
            cursor.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    def insert_record(
        self, db_name: str, table_name: str, values: dict[str, Any]
    ) -> None:
        """Insere um novo registro na tabela."""
        self._validate_table(db_name, table_name)
        conn = self._get_connection(db_name)
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            cols = list(values.keys())
            placeholders = ", ".join(["?" for _ in cols])
            cols_str = ", ".join(cols)
            query = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
            params = [values[col] for col in cols]
            cursor.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    def delete_record(
        self,
        db_name: str,
        table_name: str,
        pk_columns: list[str],
        pk_values: dict[str, Any],
    ) -> None:
        """Remove um registro pela chave primária."""
        self._validate_table(db_name, table_name)
        conn = self._get_connection(db_name)
        try:
            cursor = conn.cursor()
            cursor.execute("BEGIN IMMEDIATE")
            where_clauses = " AND ".join([f"{pk} = ?" for pk in pk_columns])
            params = [pk_values.get(pk) for pk in pk_columns]
            query = f"DELETE FROM {table_name} WHERE {where_clauses}"
            cursor.execute(query, params)
            conn.commit()
        finally:
            conn.close()

    def parse_integrity_error(
        self,
        error: sqlite3.IntegrityError,
        table: str,
        column: str,
        value: str,
    ) -> str:
        """Converte erro de integridade SQLite em mensagem amigável."""
        msg = str(error)

        if "UNIQUE constraint failed" in msg:
            return f"Valor '{value}' já existe na tabela '{table}'"
        if "NOT NULL constraint failed" in msg:
            return f"Campo '{column}' não pode ser vazio"
        if "FOREIGN KEY constraint failed" in msg:
            return f"Referência inválida para '{value}'"
        return f"Erro no banco: {msg}"

    def get_non_editable_columns(self, table_name: str) -> list[str]:
        """Retorna colunas não editáveis de uma tabela."""
        return self._non_editable_columns.get(table_name, [])
