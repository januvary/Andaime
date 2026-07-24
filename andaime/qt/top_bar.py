"""Barra superior genérica (andaime.qt).

Reproduz o leiaute exato da barra do Emissor: uma linha ``QHBoxLayout``
dividida em colunas pesadas:

- coluna 1 (``_COL_PATIENT``=5): botão de tema + busca
  (``SearchableComboBox`` injetável, data-source agnóstica);
- coluna 1.5 (peso 0 por padrão): ``mid_widget`` opcional (vazio);
- coluna 2 (``_COL_OPTIONS``=6): botões de ação (vazia por padrão);
- coluna 3 (``_COL_RIGHT``=3): widget à direita (título ou brasão), centralizado.

``col_weights`` aceita tanto uma tupla de 3 quanto de 4 elementos; se
fornecida com 3, a coluna 1.5 recebe peso 0 (colapsada).

A linha de status é **separada** (ver ``MainWindow`` / app), espelhando
o Emissor: um ``QLabel`` centralizado abaixo da barra, atualizado via
``set_status``. Esta classe não acopla lógica de paciente: quem usa
in jeta um ``search_fn``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QSizePolicy,
    QFrame,
    QWidget,
)

from andaime.widgets import SearchableComboBox, static_search_fn
from andaime.qt.theme import ThemeToggleButton, make_button


# Pesos das colunas (espelham main.py do Emissor)
_COL_PATIENT = 5
_COL_OPTIONS = 6
_COL_RIGHT = 3


def coerce_actions(actions: list) -> list[QWidget]:
    """Converte uma lista de ações em ``QWidget``.

    Cada item pode ser um ``QWidget`` direto ou uma tupla
    ``(texto, role, callback?)``.
    """
    widgets: list[QWidget] = []
    for item in actions:
        if isinstance(item, QWidget):
            widgets.append(item)
        elif isinstance(item, tuple) and len(item) >= 2:
            text, role = item[0], item[1]
            btn = make_button(text, role)
            if len(item) >= 3 and callable(item[2]):
                btn.clicked.connect(item[2])
            widgets.append(btn)
    return widgets


class TopBar(QFrame):
    """Barra superior: tema + busca | ações | widget à direita."""

    selection_changed = Signal(object)  # key emitido pelo SearchableComboBox
    theme_toggled = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        search_fn: Optional[Callable[[str], dict[str, str]]] = None,
        title: str = "",
        placeholder: str = "Buscar...",
        actions: Optional[list] = None,
        right_widget: Optional[QWidget] = None,
        left_widget: Optional[QWidget] = None,
        mid_widget: Optional[QWidget] = None,
        show_theme: bool = True,
        show_search: bool = True,
        search_max_width: Optional[int] = 440,
        col_weights: tuple[int, ...] = (
            _COL_PATIENT,
            0,
            _COL_OPTIONS,
            _COL_RIGHT,
        ),
        right_stretch: bool = False,
        bottom_border: bool = True,
    ) -> None:
        super().__init__(parent)
        self._search_fn = search_fn
        self._placeholder = placeholder
        self._search: SearchableComboBox | None = None
        self._theme_btn: ThemeToggleButton | None = None
        self._search_max_width = search_max_width

        self.setProperty("class", "panel-header")
        if not bottom_border:
            self.setProperty("seamless", "true")
        self.setFixedHeight(52)

        if len(col_weights) == 3:
            col_weights = (col_weights[0], 0, col_weights[1], col_weights[2])

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(8)

        # ---- Coluna 1: tema (+ left_widget) ----
        col1 = QWidget(self)
        lay1 = QHBoxLayout(col1)
        lay1.setContentsMargins(0, 0, 0, 0)
        lay1.setSpacing(8)

        if show_theme:
            self._theme_btn = ThemeToggleButton(self)
            self._theme_btn.theme_toggled.connect(
                lambda d: self.theme_toggled.emit(d)
            )
            lay1.addWidget(self._theme_btn)

        if left_widget is not None:
            lay1.addWidget(left_widget)

        row.addWidget(col1, stretch=col_weights[0])

        # ---- Coluna 1.5: busca + widget do meio (opcional) ----
        col_mid = QWidget(self)
        self._mid_layout = QHBoxLayout(col_mid)
        self._mid_layout.setContentsMargins(0, 0, 0, 0)
        self._mid_layout.setSpacing(8)

        if show_search:
            self._search_slot = QWidget(self)
            self._search_slot.setLayout(QHBoxLayout())
            self._search_slot.layout().setContentsMargins(0, 0, 0, 0)
            self._search_slot.layout().setSpacing(0)
            self._search_slot.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
            self._mid_layout.addWidget(self._search_slot, stretch=1)
            self._build_search(search_fn, placeholder)
        else:
            self._search = None
            self._search_slot = None

        if mid_widget is not None:
            self._mid_layout.addWidget(mid_widget)
        row.addWidget(col_mid, stretch=col_weights[1])

        # ---- Coluna 2: ações ----
        col2 = QWidget(self)
        self._action_layout = QHBoxLayout(col2)
        self._action_layout.setContentsMargins(0, 0, 0, 0)
        self._action_layout.setSpacing(8)
        for btn in self._coerce_actions(actions or []):
            self._action_layout.addWidget(btn)

        row.addWidget(col2, stretch=col_weights[2])

        # ---- Coluna 3: widget à direita (título / brasão) ----
        col3 = QWidget(self)
        lay3 = QHBoxLayout(col3)
        lay3.setContentsMargins(0, 0, 0, 0)
        lay3.setSpacing(8)
        if not right_stretch:
            lay3.addStretch()

        if right_widget is not None:
            self._right_widget = right_widget
        else:
            self._right_widget = QLabel(title)
            self._right_widget.setProperty("heading", "true")
            self._right_widget.setStyleSheet("font-weight: 600;")
        lay3.addWidget(self._right_widget, stretch=1 if right_stretch else 0)
        if not right_stretch:
            lay3.addStretch()

        row.addWidget(col3, stretch=col_weights[3])

    # ========== Construção ==========

    def _build_search(
        self,
        search_fn: Optional[Callable[[str], dict[str, str]]],
        placeholder: str,
    ) -> None:
        self._clear_search_slot()
        self._search_fn = search_fn
        if search_fn is None:
            self._search = None
            return
        combo = SearchableComboBox(
            search_fn=search_fn, placeholder=placeholder, parent=self
        )
        if self._search_max_width is not None:
            combo.setMaximumWidth(self._search_max_width)
        else:
            combo.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
            )
        combo.setFixedHeight(34)
        combo.selection_changed.connect(self.selection_changed.emit)
        self._search_slot.layout().addWidget(combo)
        self._search = combo

    def _clear_search_slot(self) -> None:
        if self._search is not None:
            self._search.setParent(None)
            self._search.deleteLater()
            self._search = None

    @staticmethod
    def _coerce_actions(actions: list) -> list[QWidget]:
        return coerce_actions(actions)

    # ========== API ==========

    def add_action(self, action) -> None:
        """Adiciona um botão de ação à coluna 2.

        ``action`` pode ser um ``QWidget`` ou uma tupla
        ``(texto, role, callback?)``.
        """
        for btn in self._coerce_actions([action]):
            self._action_layout.addWidget(btn)

    def set_mid_widget(self, widget: QWidget) -> None:
        """Substitui o widget da coluna 1.5 (meio)."""
        lay = self._mid_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        lay.addWidget(widget)

    def set_search_fn(
        self, search_fn: Optional[Callable[[str], dict[str, str]]]
    ) -> None:
        self._build_search(search_fn, self._placeholder)

    def set_search_options(
        self, options: dict[str, str], placeholder: str = "Buscar..."
    ) -> None:
        self._placeholder = placeholder
        self._build_search(static_search_fn(options), placeholder)

    def set_current(self, key: str, label: str) -> None:
        if self._search is not None:
            self._search.set_current(key, label)
            self.selection_changed.emit(key)

    def set_current_by_key(self, key: str) -> None:
        if self._search is not None:
            self._search.set_current_by_data(key)

    def clear_search(self) -> None:
        if self._search is not None:
            self._search.clear()

    def current_text(self) -> str:
        if self._search is not None:
            return self._search.current_text()
        return ""

    def set_right_widget(self, widget: QWidget) -> None:
        """Substitui o widget à direita (coluna 3)."""
        self._right_widget.setParent(None)
        self._right_widget.deleteLater()
        self._right_widget = widget
        # Reinsere centralizado (stretch dos dois lados)
        col3 = self._right_widget.parent()
        if col3 is not None:
            lay = col3.layout()
            lay.insertStretch(0, 1)
            lay.addWidget(self._right_widget)
            lay.addStretch()

    def set_title(self, title: str) -> None:
        from PySide6.QtWidgets import QLabel as _QLabel

        new = _QLabel(title)
        new.setProperty("heading", "true")
        new.setStyleSheet("font-weight: 600;")
        self.set_right_widget(new)
