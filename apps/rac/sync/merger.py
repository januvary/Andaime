#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Snapshot merger — combine per-USAFA snapshots into aggregate stats for the
management panel. Pure logic: no I/O, no Qt, fully testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rac.sync.types import Snapshot


@dataclass
class UsafaStats:
    usafa_id: str
    usafa_name: str
    exported_at: str
    registros: int
    pacientes: int
    malotes: int
    by_tipo: dict[str, int] = field(default_factory=dict)


@dataclass
class AggregateStats:
    usafas: list[UsafaStats] = field(default_factory=list)
    total_registros: int = 0
    total_pacientes: int = 0
    total_usafas: int = 0
    by_tipo: dict[str, int] = field(default_factory=dict)
    top_items: list[dict[str, Any]] = field(default_factory=list)


def merge_snapshots(snapshots: list[Snapshot]) -> AggregateStats:
    usafa_stats: list[UsafaStats] = []
    by_tipo: dict[str, int] = {}
    item_counts: dict[str, int] = {}
    total_registros = 0
    total_pacientes = 0

    for snap in snapshots:
        summary = snap["summary"]
        totals = summary["totals"]
        reg = int(totals.get("registros", 0))
        pac = int(totals.get("pacientes", 0))
        total_registros += reg
        total_pacientes += pac

        tipo_counts: dict[str, int] = {}
        for tipo, row in summary["by_tipo"].items():
            cnt = int(row.get("registros", 0))
            tipo_counts[tipo] = cnt
            by_tipo[tipo] = by_tipo.get(tipo, 0) + cnt

        for item in summary["top_items"]:
            name = str(item.get("medicamento", ""))
            if not name:
                continue
            item_counts[name] = item_counts.get(name, 0) + int(item.get("registros", 0))

        malotes = len(snap.get("tables", {}).get("malotes", []))

        usafa_stats.append(
            UsafaStats(
                usafa_id=snap["usafa_id"],
                usafa_name=snap["usafa_name"],
                exported_at=snap["exported_at"],
                registros=reg,
                pacientes=pac,
                malotes=malotes,
                by_tipo=tipo_counts,
            )
        )

    top_items = [
        {"medicamento": name, "registros": count}
        for name, count in sorted(item_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    return AggregateStats(
        usafas=usafa_stats,
        total_registros=total_registros,
        total_pacientes=total_pacientes,
        total_usafas=len(usafa_stats),
        by_tipo=by_tipo,
        top_items=top_items,
    )
