#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QComboBox,
    QWidget,
    QStyledItemDelegate,
)
from PySide6.QtGui import QPainter, QFontMetrics, QColor
from PySide6.QtWidgets import QStyleOptionViewItem, QStyle
from PySide6.QtCore import Qt, QRect

from rac.gui.styles import colors


class _NoScrollComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class _CenteredComboBox(_NoScrollComboBox):
    _popup_bg: str = ""
    _hide_current: bool = False

    def setHideCurrentItem(self, hide: bool):
        self._hide_current = hide

    def showPopup(self):
        if self._hide_current:
            for i in range(self.count()):
                self.view().setRowHidden(i, i == self.currentIndex())
        super().showPopup()
        popup = self.findChild(QWidget)
        if popup:
            bg = self._popup_bg or colors()["bg_card"]
            popup.setStyleSheet(f"background-color: {bg}; border: none;")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().text().color())
        painter.setFont(self.font())

        text = self.currentText()
        icon = self.itemIcon(self.currentIndex())
        fm = QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(text)
        text_height = fm.height()
        icon_size = 16
        spacing = 6
        total_width = text_width + (icon_size + spacing if icon and not icon.isNull() else 0)

        x = (self.width() - total_width) / 2
        y = (self.height() - text_height) / 2 + fm.ascent()

        if icon and not icon.isNull():
            icon_rect = QRect(int(x), (self.height() - icon_size) // 2, icon_size, icon_size)
            icon.paint(painter, icon_rect)
            x += icon_size + spacing

        painter.drawText(int(x), int(y), text)
        painter.end()


class _BaseComboDelegate(QStyledItemDelegate):
    def _pen_color_unselected(self, option: QStyleOptionViewItem, index) -> QColor:
        raise NotImplementedError

    def _selected_fill_and_pen(self, option: QStyleOptionViewItem):
        c = colors()
        return QColor(c["selection_bg"]), QColor(c["selection_text"])

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        text = index.data(Qt.ItemDataRole.DisplayRole)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        painter.save()

        if option.state & QStyle.StateFlag.State_Selected:
            fill, pen = self._selected_fill_and_pen(option)
            painter.fillRect(option.rect, fill)
            painter.setPen(pen)
        else:
            painter.setPen(self._pen_color_unselected(option, index))

        icon_size = 16
        text_rect = option.rect
        if icon and not icon.isNull():
            icon_rect = QRect(
                option.rect.left() + 6,
                option.rect.top() + (option.rect.height() - icon_size) // 2,
                icon_size,
                icon_size,
            )
            icon.paint(painter, icon_rect)
            text_rect = option.rect.adjusted(icon_size + 12, 0, 0, 0)

        painter.setFont(option.font)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class _ThemedComboDelegate(_BaseComboDelegate):
    def _pen_color_unselected(self, option, index):
        return QColor(colors()["text_primary"])
