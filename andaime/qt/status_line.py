"""Linha de status transiente (andaime.qt)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel, QWidget

from andaime.qt.fs import reveal_path
from andaime.qt.theme import colors


class StatusLine(QLabel):
    """Linha de status transiente (texto centralizado, cor/acao opcional).

    Quando ``set_status`` recebe ``path``, o texto fica sublinhado e o cursor
    vira "mão"; um clique emite ``reveal_path(path)``.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__("", parent)
        self.setProperty("class", "dim")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._path: str | None = None

    def set_status(
        self,
        text: str,
        color: str | None = None,
        path: str | None = None,
    ) -> None:
        """Define o texto e a aparência da linha de status."""
        self.setText(text)
        self._path = path
        style = ""
        if color:
            resolved = colors().get(color, color)
            style = f"color: {resolved};"
        if path:
            style += " text-decoration: underline;"
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setStyleSheet(style)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._path:
            reveal_path(self._path)
        super().mouseReleaseEvent(event)
