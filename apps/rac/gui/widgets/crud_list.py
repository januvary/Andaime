#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CrudList — reusable search + table widget for managing a simple named entity
(pacientes, medicamentos, etc.) via injected DB callbacks. Optionally renders
a secondary column (e.g. "Último registro") via a value accessor.
"""

import sqlite3
from typing import Callable

from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLineEdit,
    QLabel,
    QMenu,
)
from PySide6.QtCore import Qt, QTimer

from rac.gui.widgets.buttons import make_button
from rac.gui.widgets.dialogs import confirm_delete_dialog, open_input_dialog
from rac.gui.widgets.base_page import make_tab
from rac.gui.styles import data_view_style_qss, filter_table_rows
from andaime.qt.table import table_batch_populate


class SortableTableWidgetItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by an explicit sort_key when provided,
    falling back to text comparison otherwise. Lets a column display a
    human-readable value (e.g. '01/06/2026 · Retirada') while sorting by an
    underlying value (e.g. the ISO date '2026-06-01')."""

    def __init__(self, text: str = "", sort_key: object = None) -> None:
        super().__init__(text)
        self._sort_key = sort_key

    def __lt__(self, other) -> bool:
        other_key = getattr(other, "_sort_key", None)
        if self._sort_key is not None and other_key is not None:
            return self._sort_key < other_key
        return self.text() < other.text()


class CrudList:
    def __init__(self, page, title, search_placeholder,
                 entity_label, entity_label_lower,
                 db_get_all, db_create, db_update, db_delete,
                 delete_in_use_msg, count_label: QLabel | None = None,
                 secondary_header: str | None = None,
                 secondary_value: Callable[[object], str] | None = None,
                 secondary_sort_key: Callable[[object], object] | None = None,
                 sortable: bool = True,
                 on_activate: Callable[[object], None] | None = None,
                 extra_context_items: list[tuple[str, Callable[[int], None]]] | None = None,
                 secondary_tooltip: Callable[[object], str] | None = None):
        self._page = page
        self._title = title
        self._entity_label = entity_label
        self._entity_label_lower = entity_label_lower
        self._db_get_all = db_get_all
        self._db_create = db_create
        self._db_update = db_update
        self._db_delete = db_delete
        self._delete_in_use_msg = delete_in_use_msg
        self._count_label = count_label
        self._secondary_header = secondary_header
        self._secondary_value = secondary_value
        self._secondary_sort_key = secondary_sort_key
        self._sortable = sortable
        self._on_activate = on_activate
        self._extra_context_items = extra_context_items or []
        self._secondary_tooltip = secondary_tooltip
        self._all_items: list = []
        self.list_widget: QTableWidget
        self.search: QLineEdit
        self.widget: QWidget
        self._build(search_placeholder)

    def _build(self, search_placeholder):
        tab, tab_layout = make_tab(margins=(0, 0, 0, 0))

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(search_placeholder)
        self.search.textChanged.connect(self.filter)
        search_row.addWidget(self.search)
        edit_btn = make_button("Editar", "primary")
        edit_btn.clicked.connect(self.edit_selected)
        search_row.addWidget(edit_btn)
        add_btn = make_button("Adicionar", "primary")
        add_btn.clicked.connect(self.add)
        search_row.addWidget(add_btn)
        del_btn = make_button("Excluir", "negative")
        del_btn.clicked.connect(self.delete_selected)
        search_row.addWidget(del_btn)
        tab_layout.addLayout(search_row)

        has_secondary = self._secondary_value is not None
        n_cols = 2 if has_secondary else 1
        self.list_widget = QTableWidget(0, n_cols)
        self.list_widget.setHorizontalHeaderLabels(
            ["Nome", self._secondary_header] if has_secondary else ["Nome"]
        )
        header = self.list_widget.horizontalHeader()
        self.list_widget.verticalHeader().setVisible(False)
        self.list_widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.list_widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.list_widget.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self.list_widget.setMinimumHeight(410)
        self.list_widget.setStyleSheet(
            data_view_style_qss(include_selected=True, include_hover=True)
        )
        if has_secondary:
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            header.setVisible(True)
            if name_hdr := self.list_widget.horizontalHeaderItem(0):
                name_hdr.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if sec_hdr := self.list_widget.horizontalHeaderItem(1):
                sec_hdr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        else:
            header.setVisible(False)
            header.setStretchLastSection(True)

        self.list_widget.cellDoubleClicked.connect(
            lambda row, _col: self._activate_row(row)
        )
        self._page.register_keyboard_nav(
            self.list_widget, self.search, lambda _: self._activate_current()
        )
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        tab_layout.addWidget(self.list_widget)

        self.load()
        self.widget = tab
        QTimer.singleShot(0, self.search.setFocus)

    def load(self):
        self._all_items = self._db_get_all()
        self._populate(self._all_items)
        self._update_count()

    def _update_count(self):
        if self._count_label is not None:
            self._count_label.setText(f"{self._title} ({len(self._all_items)})")

    def _populate(self, items):
        table = self.list_widget
        with table_batch_populate(table):
            table.setRowCount(len(items))
            for row, item in enumerate(items):
                name_item = SortableTableWidgetItem(item.name)
                name_item.setData(Qt.ItemDataRole.UserRole, item.id)
                table.setItem(row, 0, name_item)

                if self._secondary_value is not None:
                    display = self._secondary_value(item)
                    sort_key = (
                        self._secondary_sort_key(item)
                        if self._secondary_sort_key is not None
                        else display
                    )
                    sec_item = SortableTableWidgetItem(display, sort_key)
                    sec_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    sec_item.setFlags(
                        sec_item.flags() & ~Qt.ItemFlag.ItemIsEditable & ~Qt.ItemFlag.ItemIsSelectable
                    )
                    if self._secondary_tooltip is not None:
                        sec_item.setToolTip(self._secondary_tooltip(item))
                    table.setItem(row, 1, sec_item)

        if self._sortable and not table.isSortingEnabled():
            table.setSortingEnabled(True)
            table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    def filter(self, text: str):
        filter_table_rows(self.list_widget, text)

    def add(self):
        name = open_input_dialog(
            self._page, f"Adicionar {self._entity_label}",
            f"Nome do {self._entity_label_lower}",
        )
        if not name:
            return
        try:
            self._db_create(name)
            self.load()
            self.search.clear()
            self._page._toast(f"{self._entity_label} adicionado", "positive")
        except sqlite3.IntegrityError:
            self._page._toast("Erro: nome já existe ou inválido", "negative")
        except Exception as e:
            self._page._handle_error(e)

    def _edit_row(self, row: int):
        item = self.list_widget.item(row, 0)
        if item is not None:
            self._edit_item(item)

    def _activate_row(self, row: int):
        item = self.list_widget.item(row, 0)
        if item is None:
            return
        if self._on_activate is not None:
            item_id = item.data(Qt.ItemDataRole.UserRole)
            on_activate = self._on_activate
            # Defer navigation so the trailing mouse events of a double-click
            # are consumed by this list before the new page is shown — otherwise
            # they can land on the destination page (e.g. its history table,
            # which would re-fire its own double-click handler).
            QTimer.singleShot(0, lambda: on_activate(item_id))
        else:
            self._edit_item(item)

    def _activate_current(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self._activate_row(row)

    def _show_context_menu(self, pos):
        row = self.list_widget.rowAt(pos.y())
        if row < 0:
            return
        item = self.list_widget.item(row, 0)
        if item is None:
            return
        self.list_widget.selectRow(row)
        menu = QMenu(self._page)
        edit_action = menu.addAction(f"Editar {self._entity_label_lower}")
        edit_action.triggered.connect(
            lambda _checked=False, it=item: self._edit_item(it)
        )
        item_id = item.data(Qt.ItemDataRole.UserRole)
        for label, callback in self._extra_context_items:
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, cb=callback, iid=item_id: cb(iid)
            )
        delete_action = menu.addAction("Excluir")
        delete_action.triggered.connect(
            lambda _checked=False: self.delete_selected()
        )
        menu.exec(self.list_widget.viewport().mapToGlobal(pos))

    def _edit_item(self, item: QTableWidgetItem):
        item_id = item.data(Qt.ItemDataRole.UserRole)
        old_name = item.text()
        new_name = open_input_dialog(
            self._page, f"Editar {self._entity_label}",
            f"Nome do {self._entity_label_lower}", initial=old_name,
        )
        if not new_name or new_name == old_name:
            return
        try:
            self._db_update(item_id, new_name)
            self.load()
            self.search.clear()
            self._page._toast(f"{self._entity_label} atualizado", "positive")
        except sqlite3.IntegrityError:
            self._page._toast("Erro: nome já existe ou inválido", "negative")
        except Exception as e:
            self._page._handle_error(e)

    def edit_selected(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self._edit_row(row)

    def delete_selected(self):
        row = self.list_widget.currentRow()
        if row < 0:
            return
        item = self.list_widget.item(row, 0)
        if item is None:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()
        if not confirm_delete_dialog(
            self._page, f"Excluir {self._entity_label}", f'Excluir "{name}"?',
        ):
            return
        if self._db_delete(item_id):
            self.load()
            self.search.clear()
            self._page._toast(f"{self._entity_label} excluído", "positive")
        else:
            self._page._toast(self._delete_in_use_msg, "warning")
