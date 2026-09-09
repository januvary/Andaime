#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrações de banco de dados do Emissor."""

from typing import Any


class DatabaseMigrator:
    """Gerencia migrações de banco de dados do Emissor."""

    @staticmethod
    def run_all(cursor: Any, conn: Any, db_path: str) -> None:
        """Executa migrações pendentes (idempotente via PRAGMA user_version).

        Versão atual: 8. Bancos novos já criam o schema completo.
        """
        if db_path == ":memory:":
            return
        # Future migrations go here
