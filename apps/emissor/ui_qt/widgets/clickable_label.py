#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Clickable Label
QLabel que emite um sinal quando clicado.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget


class ClickableLabel(QLabel):
    """
    Label clicável para ações na interface Qt.

    Emite o sinal ``clicked`` ao receber um clique do mouse.
    """

    clicked = Signal()
    right_clicked = Signal()

    def __init__(
        self, text: str = "", parent: QWidget | None = None
    ) -> None:
        """
        Inicializa o label clicável.

        Args:
            text: Texto inicial do label.
            parent: Widget pai opcional.
        """
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """
        Emite o sinal clicked (botão esquerdo) ou right_clicked (botão direito)
        quando o label é pressionado.

        Args:
            event: Evento de pressionamento do mouse.
        """
        if event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit()
        else:
            self.clicked.emit()
        super().mousePressEvent(event)
