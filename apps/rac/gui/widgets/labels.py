#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QSizePolicy,
    QWidget,
)
from rac.gui.constants import TIPO_HEX, TIPO_SYMBOLS, TIPO_LABELS
from rac.gui.styles import colors
from rac.gui.widgets.base_page import make_hbox


class Separator(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("separator", True)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class SectionLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("heading", "section")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class HeadingLabel(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setProperty("heading", "true")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class TipoLabel(QWidget):
    def __init__(self, tipo_key: str, parent=None):
        super().__init__(parent)
        hex_color = TIPO_HEX[tipo_key]
        symbol = TIPO_SYMBOLS[tipo_key]
        label = TIPO_LABELS[tipo_key]

        h = make_hbox(spacing=6)
        self.setLayout(h)

        dot = QLabel("\u25cf")
        dot.setStyleSheet(f"color: {hex_color}; font-size: 14px; border: none;")
        dot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        h.addWidget(dot)

        c = colors()
        text = QLabel(f"{symbol} {label}")
        text.setStyleSheet(
            f"color: {c['text_primary']}; font-size: 14px; font-weight: 600; border: none;"
        )
        text.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        h.addWidget(text)
