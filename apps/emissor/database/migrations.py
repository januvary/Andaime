#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrações de banco de dados do Emissor."""

from typing import Any


class DatabaseMigrator:
    """Gerencia migrações de banco de dados do Emissor."""

    @staticmethod
    def run_all(cursor: Any, conn: Any, db_path: str) -> None:
        """Executa migrações pendentes (idempotente via PRAGMA user_version).

        Versão atual: 11. Bancos novos já criam o schema completo.
        """
        if db_path == ":memory:":
            return

        version = cursor.execute("PRAGMA user_version").fetchone()[0]

        if version < 10:
            cursor.execute("DROP INDEX IF EXISTS idx_pacientes_nome_norm")
            cursor.execute("PRAGMA user_version = 10")

        if version < 11:
            DatabaseMigrator._migrate_retirada_items_fk(cursor)
            cursor.execute("PRAGMA user_version = 11")

    @staticmethod
    def _migrate_retirada_items_fk(cursor: Any) -> None:
        """Reconstrói retirada_items com FK item_id → items_catalog (cascade).

        SQLite não permite ADD FOREIGN KEY via ALTER TABLE; a tabela é
        recriada e os dados copiados (lista de colunas dinâmica para
        suportar bancos antigos sem ignorar_suficiencia).
        """
        cols = [row[1] for row in cursor.execute("PRAGMA table_info(retirada_items)").fetchall()]
        if not cols:
            return
        fk = [row for row in cursor.execute("PRAGMA foreign_key_list(retirada_items)").fetchall()]
        if any(r[2] == "items_catalog" for r in fk):
            return

        col_list = ", ".join(cols)
        cursor.execute("PRAGMA foreign_keys=OFF")
        try:
            cursor.execute("""
                CREATE TABLE retirada_items_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    retirada_id INTEGER NOT NULL,
                    item_id TEXT NOT NULL,
                    descricao TEXT NOT NULL,
                    unidade TEXT,
                    quantidade TEXT,
                    dias TEXT,
                    ignorar_suficiencia INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (retirada_id) REFERENCES retiradas(id) ON DELETE CASCADE,
                    FOREIGN KEY (item_id) REFERENCES items_catalog(item_id) ON UPDATE CASCADE
                )
            """)
            cursor.execute(
                f"INSERT INTO retirada_items_new ({col_list}) SELECT {col_list} FROM retirada_items"
            )
            cursor.execute("DROP TABLE retirada_items")
            cursor.execute("ALTER TABLE retirada_items_new RENAME TO retirada_items")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_retirada_items_retirada ON retirada_items(retirada_id)"
            )
        finally:
            cursor.execute("PRAGMA foreign_keys=ON")
