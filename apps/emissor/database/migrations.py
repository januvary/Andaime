#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrações de banco de dados do Emissor."""

from typing import Any


class DatabaseMigrator:
    """Gerencia migrações de banco de dados do Emissor."""

    @staticmethod
    def run_all(cursor: Any, conn: Any, db_path: str) -> None:
        """Executa migrações pendentes (idempotente via PRAGMA user_version).

        Versão atual: 10. Bancos novos já criam o schema completo.
        """
        if db_path == ":memory:":
            return

        version = cursor.execute("PRAGMA user_version").fetchone()[0]

        if version < 10:
            cursor.execute("DROP INDEX IF EXISTS idx_pacientes_nome_norm")
            cursor.execute("PRAGMA user_version = 10")
