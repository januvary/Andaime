#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QSizePolicy,
    QWidget,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette

from rac.gui.widgets._completer import (
    _CenteredComboBox,
    _BaseComboDelegate,
)
from rac.gui.widgets.base_page import make_hbox
from rac.gui.constants import TIPO_LABELS, TIPO_SYMBOLS, TIPO_HEX
from rac.gui.styles import colors, faded_tipo_color, combo_style_qss


class _TipoComboDelegate(_BaseComboDelegate):
    def _selected_fill_and_pen(self, option):
        return (
            option.palette.color(QPalette.ColorRole.Highlight),
            option.palette.color(QPalette.ColorRole.HighlightedText),
        )

    def _pen_color_unselected(self, option, index):
        tipo_key = index.data(Qt.ItemDataRole.UserRole)
        if tipo_key:
            hex_color = TIPO_HEX.get(tipo_key, "")
            if hex_color:
                return QColor(faded_tipo_color(hex_color))
        return option.palette.color(QPalette.ColorRole.Text)


class TipoCombo(QWidget):
    tipo_changed = Signal(str)

    def __init__(self, current_tipo: str, parent=None):
        super().__init__(parent)
        self._tipo = current_tipo

        self._layout = make_hbox(spacing=6)
        self.setLayout(self._layout)

        self.setFixedHeight(28)

        self._combo = _CenteredComboBox()
        self._combo.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._combo.setMinimumWidth(130)
        self._combo.setItemDelegate(_TipoComboDelegate(self._combo))
        self._combo._popup_bg = ""
        self._combo.setHideCurrentItem(True)
        self._layout.addWidget(self._combo)

        self._combo.currentIndexChanged.connect(self._on_index_changed)

        self._combo.blockSignals(True)
        for key in TIPO_LABELS:
            self._combo.addItem(f"{TIPO_SYMBOLS[key]}  {TIPO_LABELS[key]}", key)
        self._combo.blockSignals(False)

        self._update_display(current_tipo)
        idx = self._combo.findData(current_tipo)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)

    def current_tipo(self) -> str:
        return self._tipo

    def set_tipo(self, tipo_key: str):
        idx = self._combo.findData(tipo_key)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)

    def _on_index_changed(self, idx):
        data = self._combo.itemData(idx)
        if data and data != self._tipo:
            self._tipo = data
            self._update_display(data)
            self.tipo_changed.emit(data)

    def _update_display(self, tipo_key: str):
        c = colors()
        dropdown_bg = c["bg_input"]
        self._combo._popup_bg = dropdown_bg
        hex_color = TIPO_HEX.get(tipo_key, "")
        faded = faded_tipo_color(hex_color)
        self._combo.setStyleSheet(combo_style_qss(
            text_color=faded,
            bg="transparent",
            bg_hover=c["bg_hover"],
            dropdown_bg=dropdown_bg,
            selection_bg=c["selection_bg"],
            selection_text=c["selection_text"],
            font_size="16px",
            font_weight="600",
            padding="2px 6px",
            border="none",
            min_height="22px",
            max_height="28px",
        ))
