#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Malote import — persists extracted malote tabs into the database.

Given a matcher + set of MaloteTab extractions, it creates/reuses malotes,
finds-or-creates pacientes, skips existing registros and links items.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from rac.database.rac_database import RACDatabase
from rac.importers.excel_importer import MaloteRow, MaloteTab
from rac.importers.matcher import MedMatcher
from rac.models import Malote


@dataclass
class MaloteImportSummary:
    malotes: int = 0
    registros_new: int = 0
    registros_skipped: int = 0
    pacientes_new: int = 0
    items_linked: int = 0
    unmatched: list[str] = field(default_factory=list)


class MaloteImportService:
    def __init__(self, db: RACDatabase, matcher: MedMatcher) -> None:
        self._db = db
        self._matcher = matcher

    def import_tabs(self, tabs: list[MaloteTab]) -> MaloteImportSummary:
        summary = MaloteImportSummary(
            malotes=len({t.date for t in tabs if t.date})
        )
        for tab in tabs:
            self._import_tab(tab, summary)
        return summary

    def _import_tab(self, tab: MaloteTab, summary: MaloteImportSummary) -> None:
        if not tab.tipo or not tab.rows or tab.date is None:
            return
        malote = self._ensure_malote(tab.date)
        if malote.id is None:
            return
        malote_id = malote.id

        paciente_cache: dict[str, int] = {}
        # group the sheet rows (each = one process group) by patient
        by_paciente: dict[str, list[MaloteRow]] = {}
        for row in tab.rows:
            by_paciente.setdefault(row.patient, []).append(row)

        for patient, rows in by_paciente.items():
            items: list[tuple[int, int, str, int]] = []
            for pg, row in enumerate(rows, start=1):
                for med in row.meds:
                    cid, _ = self._matcher.match(med)
                    if cid is None:
                        if med not in summary.unmatched:
                            summary.unmatched.append(med)
                        continue
                    summary.items_linked += 1
                    items.append((cid, pg, "", 0))

            if not items:
                continue

            paciente_id = self._ensure_paciente(
                paciente_cache, patient, summary
            )
            if paciente_id is None:
                continue

            if self._db.find_registro(tab.tipo, paciente_id, malote_id):
                summary.registros_skipped += 1
                continue

            reg = self._db.create_registro(tab.tipo, paciente_id, malote_id)
            if reg.id is None:
                continue
            self._db.set_registro_items(reg.id, items)
            summary.registros_new += 1

    def _ensure_malote(self, malote_date: date) -> Malote:
        if malote_date is None:
            raise ValueError("Malote date missing")
        iso = malote_date.isoformat()
        from rac.utils.date_calculator import calculate_arrival_date

        arrival_iso = None
        try:
            arrival_iso = calculate_arrival_date(malote_date).isoformat()
        except (ValueError, TypeError):
            arrival_iso = None
        return self._db.create_malote(iso, arrival_date=arrival_iso)

    def _ensure_paciente(
        self, cache: dict[str, int], name: str, summary: MaloteImportSummary
    ) -> int | None:
        pid = cache.get(name)
        if pid is not None:
            return pid
        found = self._db.find_paciente_by_name(name)
        if found and found.id is not None:
            cache[name] = found.id
            return found.id
        created = self._db.create_paciente(name)
        if created.id is None:
            return None
        summary.pacientes_new += 1
        cache[name] = created.id
        return created.id