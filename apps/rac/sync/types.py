#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snapshot type definitions — pure TypedDicts with no runtime dependencies.

Kept separate from ``snapshot.py`` (which imports the database) so that
``merger.py`` and the GitHub Action can consume snapshots without pulling in
PySide6, andaime, or the database layer.
"""

from __future__ import annotations

from typing import Any, TypedDict


class TipoSummaryRow(TypedDict):
    registros: int
    pacientes: int
    items: int


class SnapshotSummary(TypedDict):
    by_tipo: dict[str, TipoSummaryRow]
    totals: dict[str, int]
    top_items: list[dict[str, Any]]


class Snapshot(TypedDict):
    usafa_id: str
    usafa_name: str
    exported_at: str
    schema_version: int
    tables: dict[str, list[dict[str, Any]]]
    summary: SnapshotSummary
