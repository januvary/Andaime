#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Importar Planilha dialog — drop one or more .xlsx files.

Two modes, as tabs:
  - Malote: detects tipo+date per tab and imports paciente/med rows as registros.
  - Pacientes: imports patient names only.
Malote mode is selected automatically when a malote structure is detected.
"""

from __future__ import annotations

from itertools import starmap

from PySide6.QtCore import QThread, QTimer, Signal, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rac.gui.styles import colors, tab_style_qss
from rac.gui.widgets.buttons import make_button
from rac.importers.excel_importer import (
    ExcelImporter,
    ImportAnalysis,
    MaloteExtraction,
    parse_malote_spec,
    parse_col_spec,
)
from rac.importers.matcher import MedMatcher
from rac.services.malote_import_service import MaloteImportService

_DEBOUNCE_MS = 250


class _ExtractWorker(QThread):
    result = Signal(object)

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self._job = job

    def run(self) -> None:
        try:
            out = self._job()
        except Exception:
            out = []
        self.result.emit(out)


class ImportPlanilhaDialog(QDialog):
    def __init__(self, parent, importers: list[ExcelImporter], db, on_import):
        super().__init__(parent)
        self.setWindowTitle("Importar planilha")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self.setWindowModality(self.windowModality())

        self._importers = importers
        self._db = db
        self._on_import = on_import

        self._names: list[str] = []
        self._malote: MaloteExtraction | None = None
        self._existing_names = {p.name for p in db.get_all_pacientes()}
        self._matcher = MedMatcher(
            [(item.name, item.id) for item in db.get_all_items()]
        )
        self._analyses: list[ImportAnalysis] = []
        self._worker: _ExtractWorker | None = None
        self._malote_generation = 0
        self._pac_generation = 0

        self._malote_debounce = QTimer(self)
        self._malote_debounce.setSingleShot(True)
        self._malote_debounce.setInterval(_DEBOUNCE_MS)
        self._malote_debounce.timeout.connect(self._run_malote_extract)

        self._pac_debounce = QTimer(self)
        self._pac_debounce.setSingleShot(True)
        self._pac_debounce.setInterval(_DEBOUNCE_MS)
        self._pac_debounce.timeout.connect(self._run_pac_extract)

        try:
            self._analyses = [imp.analyze() for imp in self._importers]
        except Exception as e:
            from andaime.error_handler import ErrorHandler, ErrorContext

            ErrorHandler.handle_error(
                e, context=ErrorContext.EXPORT, show_dialog=False
            )
            self._analyses = []

        self._build_ui()

    # ========== UI ==========

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        c = colors()
        muted = f"color: {c['text_secondary']}; font-size: 13px;"

        if not self._analyses:
            msg = QLabel("Não foi possível ler a planilha.")
            msg.setWordWrap(True)
            msg.setStyleSheet(muted)
            layout.addWidget(msg)
            btn_row, [close_btn] = _button_row([("Fechar", "flat")])
            close_btn.clicked.connect(self.reject)
            layout.addLayout(btn_row)
            return

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(tab_style_qss())
        layout.addWidget(self._tabs, 1)

        has_malote = any(a.has_malote for a in self._analyses)
        if has_malote:
            self._build_malote_tab(c, muted)
            self._tabs.setCurrentIndex(0)
        else:
            self._tabs.addTab(self._no_malote_widget(muted), "Malote")
        self._build_pacientes_tab(c, muted)
        if not has_malote:
            self._tabs.setCurrentIndex(1)

    def _no_malote_widget(self, muted: str):
        from PySide6.QtWidgets import QWidget

        w = QWidget()
        lay = QVBoxLayout(w)
        lbl = QLabel("Nenhum malote detectado nesta planilha.")
        lbl.setWordWrap(True)
        lbl.setStyleSheet(muted)
        lay.addWidget(lbl)
        lay.addStretch()
        return w

    def _file_selector_row(self, c: dict) -> tuple[QHBoxLayout, QComboBox]:
        """Build a file-selector row (dropdown + 'N arquivo(s)' counter)."""
        from pathlib import Path

        from rac.gui.widgets._completer import themed_combo

        combo = themed_combo()
        for importer in self._importers:
            combo.addItem(Path(importer.path).name)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(combo, 1)

        n = len(self._importers)
        counter = QLabel(f"{n} arquivo(s)")
        counter.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 13px;"
        )
        row.addWidget(counter)
        return row, combo

    def _make_file_aware_edit(
        self,
        combo: QComboBox,
        specs: list[str],
        edit: QLineEdit,
    ) -> None:
        """Wire a QLineEdit to show/save the spec of the combo's selected file."""

        def load() -> None:
            idx = combo.currentIndex()
            if 0 <= idx < len(specs):
                edit.setText(specs[idx])

        def edited(text: str) -> None:
            idx = combo.currentIndex()
            if 0 <= idx < len(specs):
                specs[idx] = text

        combo.currentIndexChanged.connect(lambda *_: load())
        edit.textChanged.connect(edited)
        load()

    def _scrollable_tab(self) -> tuple[QWidget, QVBoxLayout]:
        """Return (tab_widget, content_layout) where content is scrollable.

        The content layout holds the scrollable widgets; the caller is
        responsible for adding a button row below via ``_pin_buttons``.
        """
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            " QScrollArea > QWidget > QWidget { background: transparent; border: none; }"
        )
        area.viewport().setAutoFillBackground(False)

        inner = QWidget()
        inner.setAutoFillBackground(False)
        layout = QVBoxLayout(inner)
        layout.setSpacing(10)
        area.setWidget(inner)
        outer.addWidget(area, 1)
        return w, layout

    def _pin_buttons(self, tab: QWidget, actions) -> list:
        outer = tab.layout()
        assert isinstance(outer, QVBoxLayout)
        btn_row, buttons = _button_row(actions)
        outer.addLayout(btn_row)
        return buttons

    def _build_malote_tab(self, c: dict, muted: str) -> None:
        w, lay = self._scrollable_tab()

        self._malote_specs = [
            a.default_malote_spec for a in self._analyses if a
        ] or [""]

        file_row, self._malote_file_combo = self._file_selector_row(c)
        lay.addLayout(file_row)

        label = QLabel("Colunas (aba-paciente-medicamento):")
        label.setStyleSheet(f"color: {c['text_primary']}; font-size: 14px;")
        lay.addWidget(label)

        self._malote_edit = QLineEdit()
        self._malote_edit.setPlaceholderText("formato: 1-A-B; 2-A-C")
        lay.addWidget(self._malote_edit)

        self._make_file_aware_edit(
            self._malote_file_combo, self._malote_specs, self._malote_edit
        )
        self._malote_edit.textChanged.connect(self._schedule_malote_preview)

        self._malote_summary = QLabel("Analisando...")
        self._malote_summary.setWordWrap(True)
        self._malote_summary.setStyleSheet(muted)
        lay.addWidget(self._malote_summary)

        self._malote_preview_label = QLabel("")
        self._malote_preview_label.setWordWrap(True)
        self._malote_preview_label.setStyleSheet(muted)
        lay.addWidget(self._malote_preview_label)

        self._malote_warning = QLabel("")
        self._malote_warning.setWordWrap(True)
        self._malote_warning.setStyleSheet(
            f"color: {c['toast_warning_fg']}; font-size: 12px;"
        )
        lay.addWidget(self._malote_warning)

        lay.addStretch(1)

        self._cancel_btn, self._import_btn = self._pin_buttons(
            w, [("Cancelar", "flat"), ("Importar", "primary")]
        )
        self._cancel_btn.clicked.connect(self.reject)
        self._import_btn.clicked.connect(self._do_malote_import)

        self._tabs.addTab(w, "Malote")
        self._schedule_malote_preview()

    def _build_pacientes_tab(self, c: dict, muted: str) -> None:
        w, lay = self._scrollable_tab()

        self._col_specs = [a.default_col_spec for a in self._analyses if a] or [""]

        file_row, self._pac_file_combo = self._file_selector_row(c)
        lay.addLayout(file_row)

        label = QLabel("Coluna pacientes (aba-paciente):")
        label.setStyleSheet(f"color: {c['text_primary']}; font-size: 14px;")
        lay.addWidget(label)

        self._col_edit = QLineEdit()
        self._col_edit.setPlaceholderText("formato: aba-coluna, ex: 1-A; 2-B")
        lay.addWidget(self._col_edit)

        self._make_file_aware_edit(
            self._pac_file_combo, self._col_specs, self._col_edit
        )
        self._col_edit.textChanged.connect(self._schedule_pac_preview)

        self._preview_label = QLabel("")
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(muted)
        lay.addWidget(self._preview_label)

        lay.addStretch(1)

        self._pac_cancel_btn, self._pac_import_btn = self._pin_buttons(
            w, [("Cancelar", "flat"), ("Importar", "primary")]
        )
        self._pac_cancel_btn.clicked.connect(self.reject)
        self._pac_import_btn.clicked.connect(self._do_pac_import)

        self._tabs.addTab(w, "Pacientes")
        self._schedule_pac_preview()

    # ========== Malote mode ==========

    def _schedule_malote_preview(self) -> None:
        self._malote_debounce.start()

    def _run_malote_extract(self) -> None:
        if not any(self._parse_malote_specs()):
            self._malote = None
            self._malote_summary.setText(
                "Nenhuma coluna válida (use o formato 1-A-B; 2-A-C)."
            )
            self._import_btn.setEnabled(False)
            return

        self._malote_summary.setText("Analisando planilha...")
        self._import_btn.setEnabled(False)
        self._malote_generation += 1
        generation = self._malote_generation

        worker = _ExtractWorker(self._extract_all_malotes, self)
        worker.result.connect(
            lambda ext, g=generation: self._on_malote_done(ext, g)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self._worker = worker

    def _parse_malote_specs(self) -> list[dict]:
        """Parse per-file spec cache into {tab_idx: (pac, med)} per file."""
        return [parse_malote_spec(s) for s in self._malote_specs]

    def _extract_all_malotes(self) -> MaloteExtraction:
        from pathlib import Path

        from rac.importers.excel_importer import MaloteExtraction

        specs = self._parse_malote_specs()
        combined = MaloteExtraction()
        for importer, spec in zip(self._importers, specs):
            if not spec:
                continue
            file_label = Path(importer.path).name
            for tab in importer.extract_malote(spec).tabs:
                tab.sheet_name = f"{file_label} · {tab.sheet_name}"
                combined.tabs.append(tab)
        return combined

    def _on_malote_done(self, ext: MaloteExtraction, generation: int) -> None:
        if generation != self._malote_generation:
            return
        self._malote = ext
        tabs = ext.tabs
        if not tabs:
            self._malote_summary.setText("Nenhuma aba malote válida.")
            self._import_btn.setEnabled(False)
            return
        lines = []
        total = 0
        unmatched = []
        seen_unmatched: set[str] = set()
        for tab in tabs:
            if tab.rows:
                total += len(tab.rows)
                for row in tab.rows:
                    for med in row.meds:
                        cid, _ = self._matcher.match(med)
                        if cid is None and med not in seen_unmatched:
                            seen_unmatched.add(med)
                            unmatched.append(med)
            from rac.gui.constants import TIPO_LABELS

            tipo_label = TIPO_LABELS.get(tab.tipo, tab.tipo)
            d = tab.date.strftime("%d/%m/%Y") if tab.date else "?"
            total_pac = len({r.patient for r in tab.rows})
            lines.append(
                f"  · {tab.sheet_name}: {tipo_label} ({d}) — {total_pac} paciente(s)"
            )
        header = f"{len(tabs)} aba(s) de malote · {total} linha(s):"
        body = "\n".join(lines)
        self._malote_summary.setText(f"{header}\n{body}")
        self._import_btn.setEnabled(total > 0)
        self._malote_has_unmatched = bool(unmatched)

        patients = {r.patient for t in tabs for r in t.rows}
        new = sum(1 for p in patients if p not in self._existing_names)
        existing = len(patients) - new
        self._malote_preview_label.setText(
            f"{len(patients)} nomes detectados · {new} novos · {existing} já existem"
        )

        if unmatched:
            self._malote_warning.setText(
                "Medicamentos não encontrados no catálogo:\n  · "
                + "\n  · ".join(unmatched[:10])
                + ("\n  · ..." if len(unmatched) > 10 else "")
            )
        else:
            self._malote_warning.setText("")

    # ========== Pacientes mode ==========

    def _schedule_pac_preview(self) -> None:
        self._pac_debounce.start()

    def _run_pac_extract(self) -> None:
        if not any(parse_col_spec(s) for s in self._col_specs):
            self._names = []
            self._preview_label.setText(
                "Nenhuma coluna válida (use o formato 1-A; 2-B)."
            )
            self._pac_import_btn.setEnabled(False)
            return

        self._preview_label.setText("Analisando planilha...")
        self._pac_import_btn.setEnabled(False)
        self._pac_generation += 1
        generation = self._pac_generation

        worker = _ExtractWorker(self._extract_all_names, self)
        worker.result.connect(
            lambda names, g=generation: self._on_pac_done(names, g)
        )
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self._worker = worker

    def _extract_all_names(self) -> list[str]:
        names: list[str] = []
        seen: set[str] = set()
        for importer, spec_text in zip(self._importers, self._col_specs):
            col_map = parse_col_spec(spec_text)
            if not col_map:
                continue
            for n in importer.extract_names(col_map):
                if n not in seen:
                    seen.add(n)
                    names.append(n)
        return names

    def _on_pac_done(self, names: list[str], generation: int) -> None:
        if generation != self._pac_generation:
            return
        self._names = names
        new = sum(1 for n in names if n not in self._existing_names)
        existing = len(names) - new
        self._preview_label.setText(
            f"{len(names)} nomes detectados · {new} novos · {existing} já existem"
        )
        self._pac_import_btn.setEnabled(len(names) > 0)

    # ========== Actions ==========

    def _do_malote_import(self) -> None:
        if self._malote is None or not self._malote.tabs:
            return
        svc = MaloteImportService(self._db, self._matcher)
        summary = svc.import_tabs(self._malote.tabs)
        self._on_import(summary)
        self.accept()

    def _do_pac_import(self) -> None:
        if self._names:
            self._on_import(self._names.copy())
        self.accept()

    def closeEvent(self, event):
        for importer in self._importers:
            importer.close()
        super().closeEvent(event)


def _button_row(actions: list[tuple[str, str]]):
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    buttons = list(starmap(make_button, actions))
    for btn in buttons:
        btn_row.addWidget(btn)
    return btn_row, buttons