#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from datetime import datetime
import operator
from typing import Callable, Any

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt, QObject
from PySide6.QtGui import QKeyEvent

from rac.gui.styles import colors


def populate_malote_tree(
    tree: QTreeWidget,
    malotes: list[Any],
    *,
    format_display: Callable[[Any, datetime], str] | None = None,
    decorate_item: Callable[[QTreeWidgetItem, Any, datetime], None] | None = None,
    get_user_data: Callable[[Any, datetime], Any] | None = None,
    prepend_items: list[QTreeWidgetItem] | None = None,
) -> None:
    if format_display is None:
        def format_display(_m, dt):
            return dt.strftime("%d/%m/%Y")
    if get_user_data is None:
        def get_user_data(m, _dt):
            return m

    tree.clear()

    if prepend_items:
        for item in prepend_items:
            tree.addTopLevelItem(item)

    current_year = datetime.now().year
    current_month = datetime.now().month
    year_items: dict[int, QTreeWidgetItem] = {}
    month_items: dict[tuple[int, int], QTreeWidgetItem] = {}

    sorted_malotes: list[tuple[Any, datetime]] = []
    for m in malotes:
        try:
            dt = datetime.fromisoformat(m.date)
        except (ValueError, TypeError):
            dt = datetime.now()
        sorted_malotes.append((m, dt))
    sorted_malotes.sort(key=operator.itemgetter(1), reverse=True)

    for m, dt in sorted_malotes:
        year = dt.year
        month = dt.month
        is_past_month = (year, month) < (current_year, current_month)
        is_past_year = year < current_year

        child = QTreeWidgetItem()
        child.setText(0, format_display(m, dt))
        child.setData(0, Qt.ItemDataRole.UserRole, get_user_data(m, dt))
        if decorate_item:
            decorate_item(child, m, dt)

        if not is_past_month:
            tree.addTopLevelItem(child)
        elif is_past_year:
            if year not in year_items:
                year_item = QTreeWidgetItem()
                year_item.setText(0, str(year))
                year_item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
                year_item.setExpanded(False)
                year_items[year] = year_item
                tree.addTopLevelItem(year_item)

            key = (year, month)
            if key not in month_items:
                month_item = QTreeWidgetItem()
                month_item.setText(0, f"{month:02d}/{year}")
                month_item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
                month_item.setExpanded(False)
                month_items[key] = month_item
                year_items[year].addChild(month_item)

            month_items[key].addChild(child)
        else:
            key = (year, month)
            if key not in month_items:
                month_item = QTreeWidgetItem()
                month_item.setText(0, f"{month:02d}/{year}")
                month_item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
                month_item.setExpanded(True)
                month_items[key] = month_item
                tree.addTopLevelItem(month_item)
            month_items[key].addChild(child)


def make_malote_tree() -> QTreeWidget:
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(True)
    tree.setAnimated(True)
    tree.setIndentation(0)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    c = colors()
    tree.setStyleSheet(
        f'QTreeWidget {{ alternate-background-color: {c["table_alt_bg"]}; }}'
    )
    return tree


def wire_tree_keyboard(tree: QTreeWidget, on_activate) -> None:
    class _KeyFilter(QObject):
        def eventFilter(self, obj, event):
            if isinstance(event, QKeyEvent) and event.type() == event.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    item = tree.currentItem()
                    if item:
                        on_activate(item)
                        return True
            return super().eventFilter(obj, event)

    tree.installEventFilter(_KeyFilter(tree))
