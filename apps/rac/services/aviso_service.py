#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aviso de última retirada (modo_medcasa).

Detects, at retirada-save time, whether the saved retirada is the LAST one
of its process — the one after which the patient must submit a new
renovação — and produces the data for the printed warning label.

Model
-----
A process is anchored at the patient's entrada/renovação registros (a
retirada sharing the malote with its anchor belongs to the PREVIOUS
process: the new one isn't authorized yet).
Per (process, med) a ledger accumulates the recibo months (N) of each
retirada. The retirada that brings the cumulative supply to >= 6
competências is the last one → one label per med in the triggering groups.

Deadline:
  D1 = month(anchor malote) + 6 months

The anchor malote date is when the renovação was sent; the auth window
closes 6 months after that. The label deadline is D1.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date

from rac.database.rac_database import RACDatabase
from rac.utils.date_calculator import add_months


@dataclass
class AvisoLabel:
    registro_id: int
    paciente_id: int
    paciente_name: str
    item_id: int
    med_name: str
    n: int              # recibo months of the triggering retirada
    deadline: date      # D1 — rendered as MÊS/ANO on the label
    d1: date


class AvisoService:
    CYCLE_MONTHS = 6

    def __init__(self, db: RACDatabase) -> None:
        self._db = db

    def detect_for_malote(self, malote_id: int) -> list[AvisoLabel]:
        """Labels for every last-of-process retirada in the given malote.

        One entry per triggering (retirada, med), sorted by patient then
        med so the printed sheet groups stickers per patient.
        """
        labels: list[AvisoLabel] = []
        for reg in self._db.get_registros_by_malote(malote_id):
            if reg.tipo != "retirada" or reg.id is None:
                continue
            labels.extend(self.detect_for_retirada(reg.id))
        labels.sort(key=lambda lab: (lab.paciente_name, lab.med_name))
        return labels

    def detect_for_retirada(self, registro_id: int) -> list[AvisoLabel]:
        """Labels to print after saving the given retirada registro.

        Returns [] for non-retirada registros and for retiradas that are
        not the last of their process.
        """
        registro = self._db.get_registro_by_id(registro_id)
        if not registro or registro.tipo != "retirada":
            return []
        if registro.paciente_id is None:
            return []

        paciente = self._db.get_paciente_by_id(registro.paciente_id)
        paciente_name = paciente.name if paciente else (registro.paciente_name or "?")

        rows = self._db.get_dispensation_history(registro.paciente_id)
        eventos: list[dict] = []
        months_by_reg: dict[int, dict[int, int]] = {}
        item_names: dict[int, str] = {}
        for r in rows:
            try:
                malote = date.fromisoformat(r["malote_date"])
            except (TypeError, ValueError):
                continue
            reg_id = r["reg_id"]
            pg = r["pg"] or 1
            eventos.append({
                "reg_id": reg_id,
                "tipo": r["tipo"],
                "malote": malote,
                "item_id": r["item_id"],
                "pg": pg,
            })
            months = r["months_supply"]
            months_by_reg.setdefault(reg_id, {})[pg] = int(months) if months is not None else 0
            if r["item_id"] is not None and r["item_name"]:
                item_names[r["item_id"]] = r["item_name"]

        anchors = [e for e in eventos if e["tipo"] in ("entrada", "renovacao")]
        anchor_dates = [a["malote"] for a in anchors]

        ledgers: dict[tuple[int, int], int] = {}
        triggered_keys: set[tuple[int, int]] = set()
        labels: list[AvisoLabel] = []

        for e in sorted(eventos, key=lambda x: (x["malote"], x["reg_id"])):
            if e["tipo"] != "retirada" or e["item_id"] is None:
                continue
            # last anchor strictly before this malote; a retirada sharing
            # the anchor's own malote therefore falls into the previous
            # process (the new one isn't authorized yet)
            i = bisect_left(anchor_dates, e["malote"]) - 1
            if i < 0:
                continue
            key = (i, e["item_id"])
            if key in triggered_keys:
                continue
            # retiradas without recibo months (pre-feature, imported)
            # contribute 0 to the ledger
            ledgers[key] = ledgers.get(key, 0) + months_by_reg.get(
                e["reg_id"], {}
            ).get(e["pg"], 0)
            if ledgers[key] < self.CYCLE_MONTHS:
                continue
            triggered_keys.add(key)

            if e["reg_id"] != registro_id:
                # an earlier retirada already exhausted this (process, med)
                continue

            anchor = anchors[i]
            d1 = add_months(anchor["malote"], self.CYCLE_MONTHS)
            labels.append(
                AvisoLabel(
                    registro_id=registro_id,
                    paciente_id=registro.paciente_id,
                    paciente_name=paciente_name,
                    item_id=e["item_id"],
                    med_name=item_names.get(e["item_id"], "?"),
                    n=months_by_reg.get(e["reg_id"], {}).get(e["pg"], 0),
                    deadline=d1,
                    d1=d1,
                )
            )

        return labels
