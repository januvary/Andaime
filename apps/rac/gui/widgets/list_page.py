#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ListPage — reusable read-only list page: heading, search bar and a sortable
table. Parameterized by columns and row data; double-clicking (or pressing
Enter on) a row invokes on_activate with the row's user data. No CRUD buttons
and no context menu.
"""

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import (
    QTableWidget,
    QHeaderView,
    QLineEdit,
    QSizePolicy,
    QLabel,
)
from PySide6.QtCore import Qt, QTimer

from rac.gui.widgets.base_page import BasePage
from rac.gui.widgets.crud_list import SortableTableWidgetItem
from rac.gui.widgets.labels import HeadingLabel
from rac.gui.styles import (
    data_view_style_qss,
    filter_table_rows,
    colors,
)
from andaime.qt.table import table_batch_populate


@dataclass
class ListColumn:
    header: str
    resize_mode: QHeaderView.ResizeMode = QHeaderView.ResizeMode.Stretch
    align: Qt.AlignmentFlag = (
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    )


@dataclass
class ListRow:
    cells: list[str]
    data: object = None
    sort_keys: list | None = None


class ListPage(BasePage):
    def __init__(
        self,
        main_window,
        *,
        title: str,
        search_placeholder: str,
        columns: list[ListColumn],
        rows: list[ListRow],
        on_activate: Callable[[object], None],
        back_target: str = "start",
        default_sort: tuple[int, Qt.SortOrder] | None = None,
        on_export: Callable | None = None,
        export_label: str = "Exportar Registros",
        title_parts: list[tuple[str, Qt.AlignmentFlag]] | None = None,
    ):
        super().__init__(main_window)
        self._on_activate = on_activate
        self._title = title
        self._columns = columns
        self._rows = rows
        self.search: QLineEdit
        self.table: QTableWidget
        self._build_ui(
            title, search_placeholder, columns, rows, back_target, default_sort,
            on_export, export_label, title_parts,
        )

    def _build_ui(
        self,
        title: str,
        search_placeholder: str,
        columns: list[ListColumn],
        rows: list[ListRow],
        back_target: str,
        default_sort: tuple[int, Qt.SortOrder] | None,
        on_export: Callable | None,
        export_label: str,
        title_parts: list[tuple[str, Qt.AlignmentFlag]] | None,
    ):
        layout = self._scaffold(expand_vertical=True)
        self._add_back_button(layout, target=back_target)
        layout.addSpacing(20)

        if title_parts:
            c = colors()
            for text, align in title_parts:
                if align in (Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignCenter):
                    title_lbl = HeadingLabel(text)
                    title_lbl.setAlignment(align)
                    title_lbl.setWordWrap(True)
                    title_lbl.setSizePolicy(
                        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
                    )
                    title_lbl.setAlignment(align)
                    layout.addWidget(title_lbl)
                else:
                    detail_lbl = QLabel(text)
                    detail_lbl.setProperty("heading", "section")
                    detail_lbl.setSizePolicy(
                        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
                    )
                    detail_lbl.setStyleSheet(
                        f"font-size: 14px; font-weight: 600; color: {c['text_secondary']}; border: none;"
                    )
                    detail_lbl.setAlignment(align)
                    layout.addWidget(detail_lbl)
        else:
            self._heading = HeadingLabel(title)
            self._heading.setWordWrap(True)
            self._heading.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
            )
            layout.addWidget(self._heading)

        layout.addSpacing(12)

        self.search = QLineEdit()
        self.search.setPlaceholderText(search_placeholder)
        layout.addWidget(self.search)
        layout.addSpacing(12)

        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([c.header for c in columns])
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for idx, col in enumerate(columns):
            header.setSectionResizeMode(idx, col.resize_mode)
            if hdr := self.table.horizontalHeaderItem(idx):
                hdr.setTextAlignment(col.align)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setCursor(Qt.CursorShape.PointingHandCursor)
        self.table.setMinimumHeight(410)
        self.table.setStyleSheet(
            data_view_style_qss(include_selected=True, include_hover=True)
        )
        layout.addWidget(self.table, 1)

        self._populate(columns, rows)

        if default_sort is not None:
            sort_col, order = default_sort
            self.table.setSortingEnabled(True)
            self.table.sortByColumn(sort_col, order)

        self.search.textChanged.connect(self._on_search)
        self.table.cellDoubleClicked.connect(
            lambda row, _col: self._activate_row(row)
        )
        self.register_keyboard_nav(
            self.table, self.search, lambda _w: self._activate_current()
        )
        self._shortcut_searches.append((search_placeholder, self.search))
        QTimer.singleShot(0, self.search.setFocus)

        if on_export is not None:
            layout.addSpacing(12)
            self._add_export_button(layout, on_export, label=export_label)

    def _populate(self, columns: list[ListColumn], rows: list[ListRow]):
        with table_batch_populate(self.table):
            self.table.setRowCount(len(rows))
            for row_idx, list_row in enumerate(rows):
                for col_idx, text in enumerate(list_row.cells):
                    sort_key = (
                        list_row.sort_keys[col_idx]
                        if list_row.sort_keys is not None
                        else None
                    )
                    item = SortableTableWidgetItem(text, sort_key)
                    item.setTextAlignment(columns[col_idx].align)
                    if col_idx == 0:
                        item.setData(Qt.ItemDataRole.UserRole, list_row.data)
                    self.table.setItem(row_idx, col_idx, item)

    def _activate_row(self, row: int):
        item = self.table.item(row, 0)
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        on_activate = self._on_activate
        # Defer navigation so the trailing mouse events of a double-click are
        # consumed by this list before the new page is shown.
        QTimer.singleShot(0, lambda: on_activate(data))

    def _activate_current(self):
        row = self.table.currentRow()
        if row >= 0:
            self._activate_row(row)

    def _on_search(self, text: str):
        filter_table_rows(self.table, text)
