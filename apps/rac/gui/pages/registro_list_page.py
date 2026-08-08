#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registro List Page — read-only list of registros reached from the stats page,
filtered by tipo, by medication, or unfiltered. Double-clicking a row opens
the patient page for that registro's patient.
"""

from PySide6.QtWidgets import QHeaderView
from PySide6.QtCore import Qt

from rac.gui.widgets import ListPage, ListColumn, ListRow
from rac.gui.constants import TIPO_LABELS
from rac.models import Malote, Registro
from rac.utils.text_utils import format_malote_date, format_registro_meds
from rac.export.excel_exporter import ExcelExporter
from rac.gui.widgets import export_with_fallback

_CENTER = Qt.AlignmentFlag.AlignCenter
_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter


class RegistroListPage(ListPage):
    def __init__(
        self,
        main_window,
        kind: str,
        tipo: str | None = None,
        item_id: int | None = None,
        item_name: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ):
        db = main_window.db
        self._db = db
        self._date_from = date_from
        self._date_to = date_to
        registros = db.get_stats_registros(
            tipo=tipo, item_id=item_id, date_from=date_from, date_to=date_to
        )
        pacientes = len({r.paciente_id for r in registros})

        if kind == "item":
            assert item_id is not None
            totals = db.get_stats_item_totals(item_id, date_from, date_to)
            total = totals["total"] or 1
            total_pac = totals["total_pacientes"] or 1
            pct_reg = totals["registros"] / total * 100
            pct_pac = totals["pacientes"] / total_pac * 100
            title = (
                f"{item_name} ({totals['registros']} registros - "
                f"{pct_reg:.1f}% do total - {pacientes} pacientes únicos)"
            )
            title_parts = [
                (item_name or "", Qt.AlignmentFlag.AlignLeft),
                (
                    f"{totals['registros']} registros ({pct_reg:.1f}% do total)",
                    Qt.AlignmentFlag.AlignRight,
                ),
                (
                    f"{pacientes} pacientes únicos ({pct_pac:.1f}% do total)",
                    Qt.AlignmentFlag.AlignRight,
                ),
            ]
            columns = [
                ListColumn("Data", QHeaderView.ResizeMode.ResizeToContents, _CENTER),
                ListColumn("Paciente", QHeaderView.ResizeMode.Stretch, _LEFT),
                ListColumn("CID", QHeaderView.ResizeMode.ResizeToContents, _CENTER),
            ]
            rows = self._item_rows(db, registros, item_id, date_from, date_to)
        else:
            if kind == "tipo":
                label = TIPO_LABELS.get(tipo, tipo) if tipo else "Registros"
                title = (
                    f"{label} ({len(registros)} registros - "
                    f"{pacientes} pacientes únicos)"
                )
            else:
                title = f"Registros ({len(registros)})"
            columns = [
                ListColumn("Data", QHeaderView.ResizeMode.ResizeToContents, _CENTER),
                ListColumn("Paciente", QHeaderView.ResizeMode.ResizeToContents, _LEFT),
                ListColumn("Medicamentos", QHeaderView.ResizeMode.Stretch, _LEFT),
            ]
            rows = self._registro_rows(db, registros)

        super().__init__(
            main_window,
            title=title,
            search_placeholder="Buscar paciente...",
            columns=columns,
            rows=rows,
            on_activate=self._open_patient,
            back_target="stats",
            default_sort=(0, Qt.SortOrder.DescendingOrder),
            on_export=self._on_export,
            title_parts=title_parts if kind == "item" else None,
        )

    def _on_export(self):
        headers = [c.header for c in self._columns]
        rows = [r.cells for r in self._rows]
        export_title = self._title.split("\n")[0]
        exporter = ExcelExporter(self._db)
        export_with_fallback(
            self,
            lambda: exporter.export_registro_list(
                export_title, headers, rows, self._date_from, self._date_to
            ),
            "Nenhum registro para exportar",
        )

    @staticmethod
    def _registro_rows(db, registros: list[Registro]) -> list[ListRow]:
        items_map = db.get_items_by_registros([r.id for r in registros])
        rows = []
        for reg in registros:
            rows.append(ListRow(
                cells=[
                    format_malote_date(Malote(date=reg.malote_date or "")),
                    reg.paciente_name or "",
                    format_registro_meds(items_map.get(reg.id, [])),
                ],
                data=(reg.paciente_id, reg.id),
                sort_keys=[reg.malote_date or "", None, None],
            ))
        return rows

    @staticmethod
    def _item_rows(
        db,
        registros: list[Registro],
        item_id: int,
        date_from: str | None,
        date_to: str | None,
    ) -> list[ListRow]:
        cids_map = db.get_item_cids_by_registro(item_id, date_from, date_to)
        rows = []
        for reg in registros:
            cids = cids_map.get(reg.id, [])
            rows.append(ListRow(
                cells=[
                    format_malote_date(Malote(date=reg.malote_date or "")),
                    reg.paciente_name or "",
                    ", ".join(cids) if cids else "—",
                ],
                data=(reg.paciente_id, reg.id),
                sort_keys=[reg.malote_date or "", None, None],
            ))
        return rows

    def _open_patient(self, data):
        paciente_id, registro_id = data
        self._mw.navigate_to(
            "patient",
            paciente_id=paciente_id,
            highlight_registro=registro_id,
            return_to="registro_list",
        )
