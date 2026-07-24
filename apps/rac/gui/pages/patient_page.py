#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMenu,
)
from PySide6.QtCore import Qt

from rac.gui.widgets import (
    TipoButton,
    BasePage,
    delete_registro_with_undo,
    open_input_dialog,
    make_button,
    make_hbox,
)
from rac.gui.constants import TIPO_LABELS, TIPO_HEX
from rac.gui.styles import (
    colors,
    data_view_style_qss,
    faded_tipo_color,
)
from rac.utils.text_utils import format_malote_date, format_item
from rac.models import Malote
from andaime.qt.table import table_batch_populate


def _remove_layout_item(item):
    widget = item.widget()
    if widget:
        widget.setParent(None)
        widget.deleteLater()
    elif item.layout():
        while item.layout().count():
            _remove_layout_item(item.layout().takeAt(0))
        item.layout().setParent(None)
        item.layout().deleteLater()


class PatientPage(BasePage):
    def __init__(self, main_window, paciente_id: int, highlight_registro: int | None = None, return_to: str = "start"):
        super().__init__(main_window)
        self._paciente_id = paciente_id
        self._highlight_registro = highlight_registro
        self._return_to = return_to
        self._build_ui()

    def _build_ui(self):
        layout = self._scaffold()
        self._build_header(layout)
        layout.addSpacing(12)
        self._build_table(layout)
        layout.addSpacing(16)
        self._build_tipo_buttons(layout)

    def _build_header(self, layout: QVBoxLayout):
        h = self._add_back_button(layout, target=self._return_to)

        paciente = self._mw.services.paciente.get(self._paciente_id)
        name = paciente.name if paciente else "?"
        c = colors()

        header_h = make_hbox(spacing=12)
        header_h.addStretch()

        name_btn = make_button(name, "flat")
        name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        name_btn.setStyleSheet(
            f'QPushButton {{ background: transparent; border: none; '
            f"color: {c['text_primary']}; font-size: 18px; font-weight: 700; padding: 0; }}"
            f'QPushButton:hover {{ color: {c["text_secondary"]}; }}'
        )
        name_btn.clicked.connect(self._edit_name)
        header_h.addWidget(name_btn)

        h.addLayout(header_h)

    def _build_table(self, layout: QVBoxLayout):
        registros = self._mw.services.registro.get_by_paciente(self._paciente_id)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Malote", "Tipo", "Medicamentos", "CIDs"])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setCursor(Qt.CursorShape.PointingHandCursor)
        self._table.setMinimumHeight(300)
        self._table.setStyleSheet(data_view_style_qss(include_selected=True))
        layout.addWidget(self._table)

        self._table.setRowCount(len(registros))
        with table_batch_populate(self._table):
            for row, reg in enumerate(registros):
                items = self._mw.services.registro.get_items(reg.id)
                meds_by_group: dict[int, list[str]] = {}
                for item in items:
                    meds_by_group.setdefault(item.process_group, []).append(
                        item.item_name or ""
                    )

                meds_parts = []
                for pg in sorted(meds_by_group):
                    names = sorted(set(meds_by_group[pg]))
                    formatted = [format_item(n) for n in names if n]
                    if formatted:
                        prefix = f"G{pg}: " if len(meds_by_group) > 1 else ""
                        meds_parts.append(f"{prefix}{', '.join(formatted)}")

                meds_str = " | ".join(meds_parts) if meds_parts else "—"

                cids = sorted(set(item.cid for item in items if item.cid))
                if not cids:
                    cids_str = "—"
                elif len(cids) <= 2:
                    cids_str = ", ".join(cids)
                else:
                    cids_str = ", ".join(cids[:2]) + "…"

                tipo_key = reg.tipo
                tipo_label = TIPO_LABELS.get(tipo_key, tipo_key)

                malote_date = reg.malote_date or ""
                malote_display = format_malote_date(Malote(date=malote_date))
                date_item = QTableWidgetItem(malote_display)
                date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                date_item.setData(Qt.ItemDataRole.UserRole, reg.id)
                self._table.setItem(row, 0, date_item)

                tipo_item = QTableWidgetItem(tipo_label)
                tipo_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                tipo_item.setData(Qt.ItemDataRole.UserRole, reg.id)
                tipo_item.setData(Qt.ItemDataRole.UserRole + 1, tipo_key)
                self._table.setItem(row, 1, tipo_item)

                meds_item = QTableWidgetItem(meds_str)
                meds_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, 2, meds_item)

                cids_item = QTableWidgetItem(cids_str)
                cids_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, 3, cids_item)

        self._table.resizeRowsToContents()

        if self._highlight_registro is not None:
            for r in range(self._table.rowCount()):
                item = self._table.item(r, 0)
                if item and item.data(Qt.ItemDataRole.UserRole) == self._highlight_registro:
                    self._table.selectRow(r)
                    self._table.scrollToItem(item)
                    break

        self._table.cellDoubleClicked.connect(self._on_row_double_clicked)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_row_menu)

    def _build_tipo_buttons(self, layout: QVBoxLayout):
        from rac.gui.widgets.labels import SectionLabel

        title = SectionLabel("Novo registro")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(title.styleSheet() + "font-size: 13px;")
        layout.addWidget(title)
        layout.addSpacing(8)

        c = colors()
        h = QHBoxLayout()
        h.setSpacing(8)
        self._tipo_btns: list[TipoButton] = []
        for tipo_key in TIPO_LABELS:
            btn = TipoButton(tipo_key)
            btn.clicked_tipo.connect(self._on_new_registro)
            btn.setFixedHeight(40)
            faded = faded_tipo_color(TIPO_HEX[tipo_key])
            btn.setStyleSheet(
                f'QPushButton {{ background: transparent; border: 1px solid {c["border"]}; '
                f"border-radius: 6px; padding: 8px 12px; text-align: center; "
                f"color: {faded}; font-size: 13px; }}"
                f'QPushButton:hover {{ background: {c["bg_hover"]}; color: {c["text_primary"]}; }}'
                f'QPushButton:pressed {{ background: {c["bg_pressed"]}; }}'
            )
            self._tipo_btns.append(btn)
            h.addWidget(btn)
        layout.addLayout(h)

    def refresh(self):
        container_layout = self._container_layout()
        if not container_layout:
            return

        while container_layout.count() > 0:
            child = container_layout.takeAt(container_layout.count() - 1)
            _remove_layout_item(child)

        self._highlight_registro = None
        self._build_header(container_layout)
        container_layout.addSpacing(12)
        self._build_table(container_layout)
        container_layout.addSpacing(16)
        self._build_tipo_buttons(container_layout)

    def _container_layout(self) -> QVBoxLayout | None:
        main_layout = self.layout()
        if main_layout is None:
            return None
        item = main_layout.itemAt(0)
        if item is None:
            return None
        container = item.widget()
        if container is None:
            return None
        layout = container.layout()
        if isinstance(layout, QVBoxLayout):
            return layout
        return None

    def _get_reg_id(self, row: int) -> int | None:
        item = self._table.item(row, 1)
        if not item:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_row_double_clicked(self, row: int, _col: int):
        reg_id = self._get_reg_id(row)
        if reg_id is None:
            return
        reg = self._mw.services.registro.get(reg_id)
        if reg:
            self._mw.navigate_to(
                "entry", tipo=reg.tipo, edit_id=reg_id, return_to="patient",
                paciente_id=self._paciente_id, patient_return_to=self._return_to,
            )

    def _show_row_menu(self, pos):
        row = self._table.rowAt(pos.y())
        if row < 0:
            return
        reg_id = self._get_reg_id(row)
        if reg_id is None:
            return

        self._table.selectRow(row)

        menu = QMenu(self)
        edit_action = menu.addAction("Editar")
        edit_action.triggered.connect(
            lambda _checked=False, rid=reg_id: self._edit_registro(rid)
        )
        delete_action = menu.addAction("Excluir")
        delete_action.triggered.connect(
            lambda _checked=False, rid=reg_id: self._delete_registro(rid)
        )
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _edit_registro(self, reg_id: int):
        reg = self._mw.services.registro.get(reg_id)
        if reg:
            self._mw.navigate_to(
                "entry", tipo=reg.tipo, edit_id=reg_id, return_to="patient",
                paciente_id=self._paciente_id, patient_return_to=self._return_to,
            )

    def _delete_registro(self, reg_id: int):
        delete_registro_with_undo(self, self._mw.db, reg_id, self.refresh)

    def _on_new_registro(self, tipo: str):
        if not self._mw.state.has_active_malote():
            self._toast("Selecione um malote primeiro!", "warning")
            return
        self._mw.navigate_to(
            "entry", tipo=tipo, return_to="patient",
            paciente_id=self._paciente_id, patient_return_to=self._return_to,
        )

    def _edit_name(self):
        paciente = self._mw.services.paciente.get(self._paciente_id)
        if not paciente:
            return
        new_name = open_input_dialog(
            self, "Editar Nome", "Nome do paciente", initial=paciente.name,
        )
        if not new_name or new_name == paciente.name:
            return
        try:
            self._mw.services.paciente.update(self._paciente_id, name=new_name)
            self.refresh()
            self._toast("Nome atualizado", "positive")
        except Exception as e:
            self._handle_error(e)

    def set_shortcuts_visible(self, show: bool):
        super().set_shortcuts_visible(show)
