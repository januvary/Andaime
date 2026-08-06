"""Linha de status transiente (andaime.qt).

``StatusLine`` é um ``QLabel`` centralizado, com cor opcional e — quando um
caminho é informado — sublinhado e clicável, abrindo o explorador de
arquivos no caminho ao ser clicado.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from andaime.qt.fs import reveal_path
from andaime.qt.theme import colors


class StatusLine(QLabel):
    """Linha de status transiente (texto centralizado, cor/acao opcional).

    Quando ``set_status`` recebe ``path``, o texto fica sublinhado e o cursor
    vira "mão"; um clique emite ``reveal_path(path)``.
    """

    def __init__(self, parent=None):
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
        """Define o texto e a aparência da linha de status.

        Args:
            text: texto exibido
            color: chave de paleta (ex.: "status_success") ou cor CSS literal
            path: caminho opcional; torna a linha clicável (abre o explorador)
        """
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

    def mouseReleaseEvent(self, event):
        if self._path:
            reveal_path(self._path)
        super().mouseReleaseEvent(event)
