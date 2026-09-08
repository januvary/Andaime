#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrações de banco de dados do Emissor."""

from typing import Any

from andaime.text import to_upper_normalized


class DatabaseMigrator:
    """Gerencia migrações de banco de dados do Emissor."""

    @staticmethod
    def run_all(cursor: Any, conn: Any, db_path: str) -> None:
        """Executa migrações pendentes (idempotente via PRAGMA user_version).

        Versão atual: 9. Bancos novos já criam o schema completo.
        """
        if db_path == ":memory:":
            return

        version = cursor.execute("PRAGMA user_version").fetchone()[0]

        if version < 9:
            conn.create_function(
                "to_upper_normalized", 1, to_upper_normalized, deterministic=True
            )
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_pacientes_nome_norm
                ON pacientes(to_upper_normalized(nome))
            """)
            cursor.execute("PRAGMA user_version = 9")
