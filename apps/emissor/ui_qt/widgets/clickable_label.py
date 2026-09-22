#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ClickableLabel — QLabel que emite sinal ao ser clicado."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget


class ClickableLabel(QLabel):
    """Label clicável; emite clicked / right_clicked."""

    clicked = Signal()
    right_clicked = Signal()

    def __init__(
        self, text: str = "", parent: QWidget | None = None
    ) -> None:
        """text, parent opcional; cursor pointing-hand."""
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Emite clicked (esquerdo) ou right_clicked (direito)."""
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit()
        else:
            self.clicked.emit()
        super().mousePressEvent(event)
