#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Carrega mapeamento Emissor item_id -> Olostech CSV code.

Por enquanto lê do arquivo Excel; futuramente será substituído por
consulta à coluna olostech_id da tabela items_catalog.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl


def load_mapping(mapping_file: str | Path) -> dict[str, str]:
    """Carrega mapeamento DB item_id -> Olostech CSV code.

    Args:
        mapping_file: caminho para o arquivo Excel de mapeamento.

    Returns:
        dict: {db_item_id: csv_code}
    """
    mapping: dict[str, str] = {}

    if not mapping_file:
        return mapping

    wb = openpyxl.load_workbook(str(mapping_file), read_only=True)
    ws = wb.active

    # Pares mapeados começam na linha 3
    # Colunas: A=Código CSV, B=Descrição CSV, C=vazio, D=ID DB, E=Descrição DB
    for row in ws.iter_rows(min_row=3, max_col=5, values_only=True):
        csv_code, _csv_desc, _empty, db_id, _db_desc = row[:5]

        # Para na seção "ONLY IN CSV"
        if csv_code and isinstance(csv_code, str) and "ONLY IN" in csv_code:
            break

        if csv_code and db_id:
            mapping[str(db_id).strip()] = str(csv_code).strip()

    wb.close()
    return mapping


def reverse_mapping(mapping: dict[str, str]) -> dict[str, str]:
    """CSV code -> DB item_id (para referência/debug)."""
    return {v: k for k, v in mapping.items()}


def load_mapping_from_db(db: Any) -> dict[str, str]:
    """Carrega mapeamento da coluna olostech_id do banco (futuro).

    Placeholder para quando a migration de mapeamento for implementada.
    """
    raise NotImplementedError("Mapeamento via banco ainda não implementado.")
