"""Barra inferior genérica (andaime.qt).

Espelha a ``TopBar``: mesmo visual (``panel-footer``), 52px, e quatro
colunas horizontais ponderadas por ``col_weights``:

- col1 (esquerda): ``left_widget``
- col2 (status): ``status_widget``
- col3 (centro): ``center_widget`` + ``actions``
- col4 (direita): ``right_widget`` + ``right_actions``

Usada pelo SS-54 com o ``RemessaLabel`` à esquerda, o ``StatusLabel``
em seguida, e o botão "Salvar" à direita.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QFrame, QPushButton, QWidget

from andaime.qt.top_bar import coerce_actions

_COL_LEFT = 2
_COL_STATUS = 2
_COL_CENTER = 8
_COL_RIGHT = 2


class BottomBar(QFrame):
    """Barra inferior: quatro colunas (esquerda / status / centro / direita)."""

    def __init__(
        self,
        parent: QFrame | None = None,
        actions: Optional[list] = None,
        left_widget: Optional[QWidget] = None,
        status_widget: Optional[QWidget] = None,
        center_widget: Optional[QWidget] = None,
        right_widget: Optional[QWidget] = None,
        right_actions: Optional[list] = None,
        col_weights: tuple[int, int, int, int] = (
            _COL_LEFT,
            _COL_STATUS,
            _COL_CENTER,
            _COL_RIGHT,
        ),
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "panel-footer")
        self.setFixedHeight(52)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        # ---- Coluna 1: esquerda ----
        col1 = QWidget(self)
        lay1 = QHBoxLayout(col1)
        lay1.setContentsMargins(0, 0, 0, 0)
        lay1.setSpacing(8)
        if left_widget is not None:
            lay1.addWidget(left_widget)
        layout.addWidget(col1, stretch=col_weights[0])

        # ---- Coluna 2: status ----
        col2 = QWidget(self)
        lay2 = QHBoxLayout(col2)
        lay2.setContentsMargins(0, 0, 0, 0)
        lay2.setSpacing(8)
        if status_widget is not None:
            lay2.addWidget(status_widget)
        layout.addWidget(col2, stretch=col_weights[1])

        # ---- Coluna 3: centro (ações) ----
        col3 = QWidget(self)
        lay3 = QHBoxLayout(col3)
        lay3.setContentsMargins(0, 0, 0, 0)
        lay3.setSpacing(8)
        if center_widget is not None:
            lay3.addWidget(center_widget)
        for btn in coerce_actions(actions or []):
            lay3.addWidget(btn)
        self._action_layout = lay3
        layout.addWidget(col3, stretch=col_weights[2])

        # ---- Coluna 4: direita ----
        col4 = QWidget(self)
        lay4 = QHBoxLayout(col4)
        lay4.setContentsMargins(0, 0, 0, 0)
        lay4.setSpacing(8)
        if right_widget is not None:
            lay4.addWidget(right_widget)
        for btn in coerce_actions(right_actions or []):
            lay4.addWidget(btn)
        self._right_layout = lay4
        layout.addWidget(col4, stretch=col_weights[3])

    def add_action(self, action) -> None:
        """Adiciona um botão de ação à coluna central.

        ``action`` pode ser um ``QWidget`` ou uma tupla
        ``(texto, role, callback?)``.
        """
        for btn in coerce_actions([action]):
            self._action_layout.addWidget(btn)

    def action_button(self, text: str) -> QPushButton | None:
        """Retorna o botão de ação cujo texto exato é ``text``.

        Busca nas colunas central (``actions``) e direita (``right_actions``).

        Args:
            text: Texto exato do botão

        Returns:
            QPushButton encontrado ou None se não houver correspondência
        """
        for layout in (self._action_layout, self._right_layout):
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()
                if isinstance(widget, QPushButton) and widget.text() == text:
                    return widget
        return None

    def add_right_widget(self, widget: QWidget) -> None:
        """Adiciona um widget à coluna direita."""
        self._right_layout.addWidget(widget)
