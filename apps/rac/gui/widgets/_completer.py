#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QComboBox,
    QWidget,
    QStyledItemDelegate,
)
from PySide6.QtGui import QPainter, QFontMetrics, QColor
from PySide6.QtWidgets import QStyleOptionViewItem, QStyle
from PySide6.QtCore import Qt, QRect, QSize

from rac.gui.styles import colors


def themed_combo() -> "_ThemedPopupComboBox":
    """Return a QComboBox with a themed dropdown popup (no box styling).

    Popup rows are left-aligned (text), with the theme's colors. The closed
    box keeps the native look: regular text alignment, default border/hover.
    """
    combo = _ThemedPopupComboBox()
    combo._popup_bg = colors()["bg_input"]
    combo.setItemDelegate(_LeftComboDelegate(combo))
    return combo


class _NoScrollComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class _ThemedPopupComboBox(_NoScrollComboBox):
    """QComboBox whose popup gets the app's themed background/selection look."""

    _popup_bg: str = ""

    def showPopup(self):
        super().showPopup()
        popup = self.findChild(QWidget)
        if popup:
            bg = self._popup_bg or colors()["bg_card"]
            popup.setStyleSheet(f"background-color: {bg}; border: none;")


class _CenteredComboBox(_ThemedPopupComboBox):
    _hide_current: bool = False

    def setHideCurrentItem(self, hide: bool):
        self._hide_current = hide

    def showPopup(self):
        if self._hide_current:
            for i in range(self.count()):
                self.view().setRowHidden(i, i == self.currentIndex())
        super().showPopup()

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
    align = Qt.AlignmentFlag.AlignCenter
    padding_left: int = 0

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
        text_rect = option.rect.adjusted(self.padding_left, 0, 0, 0)
        if icon and not icon.isNull():
            icon_rect = QRect(
                option.rect.left() + 6,
                option.rect.top() + (option.rect.height() - icon_size) // 2,
                icon_size,
                icon_size,
            )
            icon.paint(painter, icon_rect)
            text_rect = option.rect.adjusted(self.padding_left + icon_size + 12, 0, 0, 0)

        painter.setFont(option.font)
        painter.drawText(text_rect, self.align, text)
        painter.restore()


class _ThemedComboDelegate(_BaseComboDelegate):
    def _pen_color_unselected(self, option, index):
        return QColor(colors()["text_primary"])


class _LeftComboDelegate(_ThemedComboDelegate):
    """Left-aligned themed rows, ~2px shorter for native popup feel."""

    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    padding_left = 10

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), max(hint.height() - 2, 0))
