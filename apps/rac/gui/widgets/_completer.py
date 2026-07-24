#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QComboBox,
    QWidget,
    QStyledItemDelegate,
)
from PySide6.QtGui import QPainter, QFontMetrics, QColor
from PySide6.QtWidgets import QStyleOptionViewItem, QStyle
from PySide6.QtCore import Qt

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
        fm = QFontMetrics(self.font())
        text_width = fm.horizontalAdvance(text)
        text_height = fm.height()

        x = (self.width() - text_width) / 2
        y = (self.height() - text_height) / 2 + fm.ascent()

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
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            fill, pen = self._selected_fill_and_pen(option)
            painter.fillRect(option.rect, fill)
            painter.setPen(pen)
        else:
            painter.setPen(self._pen_color_unselected(option, index))
        painter.setFont(option.font)
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()


class _ThemedComboDelegate(_BaseComboDelegate):
    def _pen_color_unselected(self, option, index):
        return QColor(colors()["text_primary"])
