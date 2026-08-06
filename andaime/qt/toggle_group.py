"""Grupo de botões tipo "toggle" (controle segmentado) — andaime.qt.

Conjunto de botões onde exatamente um está ativo (comportamento de
"radio"). O botão ativo usa o papel ``flat-fill`` (preenchido); os
demais usam o estilo plano (``flat``). Os segmentos são dispostos em
uma única linha, colados (espaçamento 0) e com divisores, formando um
controle segmentado —— ( | | ). O visual de borda/divisores vem do QSS
global (``ToggleGroup``), então reage ao tema automaticamente.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from andaime.qt.theme import make_button


class ToggleGroup(QWidget):
    """Controle segmentado: uma opção ativa por vez."""

    selection_changed = Signal(str)  # chave da opção ativa

    def __init__(
        self,
        parent: QWidget | None = None,
        options: Optional[list[tuple[str, str]]] = None,
        default: Optional[str] = None,
        allow_deselect: bool = False,
    ) -> None:
        super().__init__(parent)
        self._buttons: dict[str, QPushButton] = {}
        self._selected: Optional[str] = default
        self._allow_deselect = allow_deselect

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for key, label in options or []:
            btn = make_button(label, "flat")
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda _checked=False, k=key: self._on_click(k)
            )
            self._buttons[key] = btn
            layout.addWidget(btn)

        keys = list(self._buttons)
        for i, k in enumerate(keys):
            edge = "first" if i == 0 else "last" if i == len(keys) - 1 else "middle"
            self._buttons[k].setProperty("edge", edge)

        self._apply()

    def _on_click(self, key: str) -> None:
        if self._allow_deselect and self._selected == key:
            self.set_selected(None, emit=True)
        else:
            self.set_selected(key, emit=True)

    def _apply(self) -> None:
        for key, btn in self._buttons.items():
            active = key == self._selected
            btn.setProperty("class", "flat-fill" if active else "flat")
            btn.setChecked(active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_selected(self, key: Optional[str], emit: bool = False) -> None:
        if key is not None and key not in self._buttons:
            return
        self._selected = key
        self._apply()
        if emit:
            self.selection_changed.emit(key or "")

    def selected(self) -> Optional[str]:
        return self._selected
