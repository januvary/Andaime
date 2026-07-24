#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QSizePolicy,
    QHeaderView,
    QTreeWidgetItem,
    QLineEdit,
)
from datetime import datetime

from PySide6.QtCore import Qt

from rac.gui.widgets import (
    make_button,
    BasePage,
    make_dialog_button_row,
    export_with_fallback,
)
from rac.gui.widgets.dialogs import scaffold_dialog
from rac.gui.widgets._malote_tree import (
    make_malote_tree,
    populate_malote_tree,
    wire_tree_keyboard,
)
from rac.gui.constants import TIPO_LABELS, TIPO_HEX
from rac.gui.styles import colors, filter_table_rows, data_view_style_qss, faded_tipo_color
from rac.export.excel_exporter import ExcelExporter
from andaime.qt.table import table_batch_populate

_CANCELLED = object()


class _TipoCard(QWidget):
    def __init__(self, tipo_key: str, value: str, label: str | None = None, label_color: str | None = None):
        super().__init__()
        c = colors()
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            f"QWidget {{ background: transparent; border: 1px solid {c['border_light']}; "
            f"border-radius: 6px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._value_label = QLabel(value)
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_label.setStyleSheet(
            f"font-size: 20px; font-weight: 700; color: {c['text_primary']}; border: none;"
        )
        layout.addWidget(self._value_label)

        display_label = label or TIPO_LABELS.get(tipo_key, tipo_key)
        display_color = label_color or c["text_secondary"]
        lbl = QLabel(display_label)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {display_color}; border: none;"
        )
        layout.addWidget(lbl)

    def set_value(self, value: str):
        self._value_label.setText(value)


class StatsPage(BasePage):
    def __init__(self, main_window):
        super().__init__(main_window)
        self._date_from: str | None = None
        self._date_to: str | None = None
        self._build_ui()
        self._load_stats()

    def _build_ui(self):
        layout = self._scaffold(expand_vertical=True)
        self._build_header(layout)
        layout.addSpacing(12)

        self._build_tipo_cards(layout)

        self._build_medications_table(layout)
        layout.addSpacing(12)

        export_btn = make_button("Exportar Estatisticas", "positive")
        export_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        export_btn.setFixedHeight(44)
        export_btn.clicked.connect(self._on_export)
        layout.addWidget(export_btn)

    def _build_header(self, layout: QVBoxLayout):
        back_btn = make_button("Voltar", "flat")
        back_btn.clicked.connect(lambda: self._mw.navigate_to("start"))
        self._shortcut_widgets["back"] = back_btn

        c = colors()
        row = QHBoxLayout()
        row.setSpacing(0)

        row.addWidget(back_btn)
        row.addStretch(1)

        self._from_btn = make_button("Inicio", "flat")
        self._from_btn.setFixedWidth(115)
        self._from_btn.clicked.connect(lambda: self._pick_date("from"))
        row.addWidget(self._from_btn)

        row.addSpacing(20)

        sep = QLabel("\u2192")
        sep.setStyleSheet(f"color: {c['text_secondary']}; border: none;")
        row.addWidget(sep)

        row.addSpacing(20)

        self._to_btn = make_button("Fim", "flat")
        self._to_btn.setFixedWidth(115)
        self._to_btn.clicked.connect(lambda: self._pick_date("to"))
        row.addWidget(self._to_btn)

        row.addStretch(1)

        spacer = QWidget()
        spacer.setFixedWidth(back_btn.sizeHint().width())
        row.addWidget(spacer)

        layout.addLayout(row)

    def _pick_date(self, side: str):
        result = _show_date_picker(self, side)
        if result is _CANCELLED:
            return
        if side == "from":
            self._date_from = result
            if self._date_to and self._date_from and self._date_from > self._date_to:
                self._date_to = self._date_from
        else:
            self._date_to = result
            if self._date_from and self._date_to and self._date_from > self._date_to:
                self._date_from = self._date_to
        self._update_date_buttons()
        self._load_stats()

    def _update_date_buttons(self):
        self._from_btn.setText(
            datetime.fromisoformat(self._date_from).strftime("%d/%m/%Y")
            if self._date_from
            else "Inicio"
        )
        self._to_btn.setText(
            datetime.fromisoformat(self._date_to).strftime("%d/%m/%Y")
            if self._date_to
            else "Fim"
        )

    def _build_tipo_cards(self, layout: QVBoxLayout):
        tipo_row = QHBoxLayout()
        tipo_row.setSpacing(10)
        tipo_row.addStretch(1)
        self._tipo_cards: dict[str, _TipoCard] = {}
        for tipo_key in TIPO_LABELS:
            card = _TipoCard(tipo_key, "0", label_color=faded_tipo_color(TIPO_HEX[tipo_key]))
            self._tipo_cards[tipo_key] = card
            tipo_row.addWidget(card)
        tipo_row.addStretch(1)
        layout.addLayout(tipo_row)

        layout.addSpacing(8)

        totals_row = QHBoxLayout()
        totals_row.setSpacing(10)
        totals_row.addStretch(1)
        self._total_registros_card = _TipoCard("__total_reg", "0", label="Total Registros")
        totals_row.addWidget(self._total_registros_card)
        self._total_pacientes_card = _TipoCard("__total_pac", "0", label="Total Pacientes")
        totals_row.addWidget(self._total_pacientes_card)
        totals_row.addStretch(1)
        layout.addLayout(totals_row)

    def _build_medications_table(self, layout: QVBoxLayout):
        layout.addSpacing(2)

        self._meds_search = QLineEdit()
        self._meds_search.setPlaceholderText("Buscar medicamento...")
        self._meds_search.setFixedHeight(20)
        layout.addWidget(self._meds_search)
        layout.addSpacing(18)

        self._meds_table = QTableWidget(0, 3)
        self._meds_table.setHorizontalHeaderLabels(["Medicamento", "Registros", "%"])
        self._meds_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._meds_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed
        )
        self._meds_table.horizontalHeader().resizeSection(1, 90)
        self._meds_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self._meds_table.horizontalHeader().resizeSection(2, 90)
        self._meds_table.horizontalHeader().setFixedHeight(28)
        self._meds_table.verticalHeader().setVisible(False)
        self._meds_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._meds_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._meds_table.setAlternatingRowColors(True)
        self._meds_table.verticalHeader().setDefaultSectionSize(32)
        self._meds_table.setMinimumHeight(28 + 32 * 8)
        self._meds_table.setStyleSheet(data_view_style_qss(include_selected=False, include_hover=True))
        layout.addWidget(self._meds_table, 1)

        self._meds_search.textChanged.connect(self._filter_meds_table)
        self._shortcut_searches.append(("Buscar medicamento", self._meds_search))

    def _load_stats(self):
        db = self._mw.db

        tipo_rows = db.get_stats_by_tipo(
            date_from=self._date_from, date_to=self._date_to
        )
        tipo_map = {r["tipo"]: r for r in tipo_rows}
        for tipo_key in TIPO_LABELS:
            r = tipo_map.get(tipo_key)
            self._tipo_cards[tipo_key].set_value(str(r["registros"]) if r else "0")

        totals = db.get_stats_totals(date_from=self._date_from, date_to=self._date_to)
        self._total_registros_card.set_value(str(totals["registros"]))
        self._total_pacientes_card.set_value(str(totals["pacientes"]))

        meds = db.get_stats_top_itens(
            date_from=self._date_from, date_to=self._date_to
        )
        self._fill_meds_table(meds)

    def _fill_meds_table(self, rows: list[dict]):
        total = sum(r["registros"] for r in rows) or 1
        with table_batch_populate(self._meds_table):
            self._meds_table.setRowCount(len(rows))
            for row, r in enumerate(rows):
                self._meds_table.setItem(row, 0, self._cell(r["medicamento"]))
                self._meds_table.setItem(
                    row, 1, self._cell(str(r["registros"]), center=True)
                )
                pct = r["registros"] / total * 100
                self._meds_table.setItem(row, 2, self._cell(f"{pct:.1f}%", center=True))

    def _filter_meds_table(self, text: str):
        filter_table_rows(self._meds_table, text)

    def _on_export(self):
        exporter = ExcelExporter(self._mw.db)
        export_with_fallback(
            self,
            lambda: exporter.export_stats(
                date_from=self._date_from, date_to=self._date_to
            ),
        )

    @staticmethod
    def _cell(text: str, center: bool = False) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if center:
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        return item






_RESET_SENTINEL = object()


def _show_date_picker(parent_page: StatsPage, side: str):
    mw = parent_page._mw
    parent = parent_page.window()

    reset_label = "Início" if side == "from" else "Fim"

    dlg, layout = scaffold_dialog(parent, "Selecionar Data", min_width=320)
    dlg.setMinimumHeight(300)

    tree = make_malote_tree()

    reset_item = QTreeWidgetItem()
    reset_item.setText(0, reset_label)
    reset_item.setData(0, Qt.ItemDataRole.UserRole, _RESET_SENTINEL)

    malotes = mw.services.malote.all()
    populate_malote_tree(
        tree,
        malotes,
        get_user_data=lambda m, _dt: m.date,
        prepend_items=[reset_item],
    )

    selected_date: list[str | None | object] = [None]

    def on_item_clicked(item, _column):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is _RESET_SENTINEL:
            selected_date[0] = None
            dlg.accept()
        elif data is not None:
            selected_date[0] = data
            dlg.accept()
        else:
            item.setExpanded(not item.isExpanded())

    tree.itemClicked.connect(on_item_clicked)
    wire_tree_keyboard(tree, lambda item: on_item_clicked(item, 0))

    layout.addWidget(tree)

    btn_row, [close_btn] = make_dialog_button_row([("Cancelar", "flat")])
    close_btn.setAutoDefault(False)
    close_btn.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    dlg.rejected.connect(lambda: selected_date.__setitem__(0, _CANCELLED))
    dlg.exec()
    return selected_date[0]
