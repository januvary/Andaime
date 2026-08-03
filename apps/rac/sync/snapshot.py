#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snapshot export — serialize a RAC database into a JSON-serializable dict,
tagged with the originating USAFA identity.

The snapshot is the unit of data exchanged with the management panel. It is
self-describing: it carries the raw table rows (for drill-down /
reconstruction) and a precomputed summary that the panel renders directly.
"""

from __future__ import annotations

from datetime import datetime

from rac.database.rac_database import RACDatabase
from rac.sync.types import Snapshot, SnapshotSummary, TipoSummaryRow


def build_summary(db: RACDatabase) -> SnapshotSummary:
    by_tipo: dict[str, TipoSummaryRow] = {}
    for row in db.get_stats_by_tipo():
        by_tipo[row["tipo"]] = {
            "registros": int(row["registros"]),
            "pacientes": int(row["pacientes"]),
            "items": int(row["items"]),
        }

    totals = db.get_stats_totals()
    return {
        "by_tipo": by_tipo,
        "totals": {
            "registros": int(totals.get("registros", 0)),
            "pacientes": int(totals.get("pacientes", 0)),
        },
        "top_items": [
            {"medicamento": r["medicamento"], "registros": int(r["registros"])}
            for r in db.get_stats_top_itens()
        ],
    }


def export_snapshot(db: RACDatabase, usafa_id: str, usafa_name: str) -> Snapshot:
    return {
        "usafa_id": usafa_id,
        "usafa_name": usafa_name,
        "exported_at": datetime.now().isoformat(),
        "schema_version": db.SCHEMA_VERSION,
        "tables": db.dump_all_tables(),
        "summary": build_summary(db),
    }
