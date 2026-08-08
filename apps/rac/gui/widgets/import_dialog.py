#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importar Planilha dialog — drop an .xlsx, pick the patient column, import names.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from rac.gui.widgets.buttons import make_button
from rac.gui.styles import colors
from rac.importers.excel_importer import ExcelImporter, ImportAnalysis, parse_col_spec


class ImportPlanilhaDialog(QDialog):
    def __init__(self, parent, importer: ExcelImporter, existing_names: set[str], on_import):
        super().__init__(parent)
        self.setWindowTitle("Importar planilha")
        self.setMinimumWidth(440)
        self.setWindowModality(self.windowModality())

        self._importer = importer
        self._existing_names = existing_names
        self._on_import = on_import
        self._names: list[str] = []
        self._analysis: ImportAnalysis | None = None

        try:
            self._analysis = importer.analyze()
        except Exception as e:
            from andaime.error_handler import ErrorHandler, ErrorContext

            ErrorHandler.handle_error(
                e, context=ErrorContext.EXPORT, show_dialog=False
            )
            self._analysis = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        c = colors()
        muted = f"color: {c['text_secondary']}; font-size: 13px;"

        if self._analysis is None:
            msg = QLabel("Não foi possível ler a planilha.")
            msg.setWordWrap(True)
            msg.setStyleSheet(muted)
            layout.addWidget(msg)
            btn_row, [close_btn] = _button_row([("Fechar", "flat")])
            close_btn.clicked.connect(self.reject)
            layout.addLayout(btn_row)
            return

        sheets_lbl = QLabel(
            f"{len(self._analysis.sheets)} aba(s): "
            f"{', '.join(self._analysis.sheet_names)}"
        )
        sheets_lbl.setWordWrap(True)
        sheets_lbl.setStyleSheet(muted)
        layout.addWidget(sheets_lbl)

        per_tab = "\n".join(
            f"  · {i}-{s.name}: "
            f"{', '.join(s.content_columns) if s.content_columns else '—'}"
            for i, s in enumerate(self._analysis.sheets, start=1)
        )
        cols_lbl = QLabel(f"Colunas com conteúdo detectadas:\n{per_tab}")
        cols_lbl.setWordWrap(True)
        cols_lbl.setStyleSheet(muted)
        layout.addWidget(cols_lbl)

        label = QLabel("Coluna pacientes:")
        label.setStyleSheet(f"color: {c['text_primary']}; font-size: 14px;")
        layout.addWidget(label)

        self._col_edit = QLineEdit()
        self._col_edit.setText(self._analysis.default_col_spec)
        self._col_edit.setPlaceholderText("formato: aba-coluna, ex: 1-A; 2-B")
        self._col_edit.textChanged.connect(self._update_preview)
        layout.addWidget(self._col_edit)

        hint = QLabel("Cada entrada é <aba>-<coluna>; abas não listadas são ignoradas.")
        hint.setWordWrap(True)
        hint.setStyleSheet(muted)
        layout.addWidget(hint)

        self._preview_label = QLabel("")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(muted)
        layout.addWidget(self._preview_label)

        layout.addSpacing(4)

        self._btn_row, [self._cancel_btn, self._import_btn] = _button_row(
            [("Cancelar", "flat"), ("Importar", "primary")]
        )
        self._cancel_btn.clicked.connect(self.reject)
        self._import_btn.clicked.connect(self._do_import)
        layout.addLayout(self._btn_row)

        self._update_preview()

    def _update_preview(self) -> None:
        col_map = parse_col_spec(self._col_edit.text())
        if not col_map:
            self._names = []
            self._preview_label.setText(
                "Nenhuma coluna válida (use o formato 1-A; 2-B)."
            )
            self._import_btn.setEnabled(False)
            return

        self._names = self._importer.extract_names(col_map)
        new = sum(1 for n in self._names if n not in self._existing_names)
        existing = len(self._names) - new
        self._preview_label.setText(
            f"{len(self._names)} nomes detectados · {new} novos · {existing} já existem"
        )
        self._import_btn.setEnabled(len(self._names) > 0)

    def _do_import(self) -> None:
        if self._names:
            self._on_import(list(self._names))
        self.accept()

    def closeEvent(self, event):
        self._importer.close()
        super().closeEvent(event)


def _button_row(actions: list[tuple[str, str]]):
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    buttons = [make_button(label, role) for label, role in actions]
    for btn in buttons:
        btn_row.addWidget(btn)
    return btn_row, buttons
