#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Medicamentos Page — manage the medication (item catalog) list
"""

import json

from rac.gui.widgets import (
    BasePage, CrudList, HeadingLabel, export_with_fallback, open_input_dialog,
)
from rac.export.excel_exporter import ExcelExporter


def _format_cids(item) -> str:
    if not item.cids:
        return "—"
    try:
        cids = json.loads(item.cids)
        return ", ".join(cids[:3]) + ("…" if len(cids) > 3 else "")
    except (json.JSONDecodeError, TypeError):
        return "—"


def _full_cids(item) -> str:
    if not item.cids:
        return ""
    try:
        return ", ".join(json.loads(item.cids))
    except (json.JSONDecodeError, TypeError):
        return ""


class MedicamentosPage(BasePage):
    def __init__(self, main_window):
        super().__init__(main_window)
        self._build_ui()

    def _build_ui(self):
        layout = self._scaffold(expand_vertical=True)
        self._add_back_button(layout)
        layout.addSpacing(20)

        self._heading = HeadingLabel("Medicamentos")
        layout.addWidget(self._heading)
        layout.addSpacing(12)

        self._crud = CrudList(
            self,
            title="Medicamentos",
            search_placeholder="Buscar medicamento...",
            entity_label="Medicamento",
            entity_label_lower="medicamento",
            db_get_all=self._mw.services.item_catalog.all,
            db_create=self._mw.services.item_catalog.create,
            db_update=self._mw.services.item_catalog.update,
            db_delete=self._mw.services.item_catalog.delete,
            delete_in_use_msg="Não é possível excluir: medicamento em uso",
            count_label=self._heading,
            secondary_header="CIDs",
            secondary_value=_format_cids,
            secondary_tooltip=_full_cids,
            extra_context_items=[
                ("Editar CIDs", self._edit_cids),
            ],
        )
        layout.addWidget(self._crud.widget, 1)
        layout.addSpacing(12)
        self._add_export_button(layout, self._on_export, label="Exportar Catálogo")

        self._shortcut_searches = [
            ("Buscar medicamento...", self._crud.search),
        ]

    def _edit_cids(self, item_id: int):
        items = self._mw.services.item_catalog.all()
        item = next((i for i in items if i.id == item_id), None)
        if not item:
            return
        try:
            cids = json.loads(item.cids) if item.cids else []
        except (json.JSONDecodeError, TypeError):
            cids = []
        initial = ", ".join(cids)
        result = open_input_dialog(
            self, "Editar CIDs",
            "CIDs separados por vírgula (ex: M05.0, K50.1)",
            initial=initial,
        )
        if result is None:
            return
        new_cids = [c.strip().upper() for c in result.split(",") if c.strip()]
        cids_json = json.dumps(new_cids)
        try:
            self._mw.services.item_catalog.update_cids(item_id, cids_json)
            self._crud.load()
            self._toast("CIDs atualizados", "positive")
        except Exception as e:
            self._handle_error(e)

    def _on_export(self):
        exporter = ExcelExporter(self._mw.db)
        export_with_fallback(
            self,
            lambda: exporter.export_catalog(),
            "Nenhum medicamento para exportar",
        )
