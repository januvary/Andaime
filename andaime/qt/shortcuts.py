"""Gerenciador de atalhos de teclado — andaime.qt."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from typing import cast
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLineEdit, QPushButton, QWidget


class ShortcutManager(QObject):
    """Registro de atalhos com dicas visuais (peek via Ctrl+Shift)."""

    def __init__(self, window: QWidget) -> None:
        """Inicializa o gerenciador.

        Args:
            window: Widget raiz que receberá os atalhos e o event filter
        """
        self._window = window
        self._hints: list[tuple[QWidget, str]] = []
        self._peek_callbacks: list[Callable[[bool], None]] = []
        self._peek_active = False
        super().__init__(window)
        window.installEventFilter(self)

    def bind(
        self,
        key: str,
        handler: Callable[[], None],
        hint_widget: QWidget | None = None,
    ) -> None:
        """Registra um atalho com variante Ctrl+Shift."""
        QShortcut(QKeySequence(key), self._window, handler)
        if isinstance(key, str) and key.startswith("Ctrl+"):
            shifted = QKeySequence(key.replace("Ctrl+", "Ctrl+Shift+", 1))
            QShortcut(shifted, self._window, handler)
        if hint_widget is not None:
            self._hints.append((hint_widget, f" ({key})"))

    def register_hint(self, widget: QWidget, key: str) -> None:
        """Registra um widget de dica para uma tecla já vinculada."""
        self._hints.append((widget, f" ({key})"))

    def on_peek(self, callback: Callable[[bool], None]) -> None:
        """Registra callback notificado quando o peek muda de estado."""
        self._peek_callbacks.append(callback)

    def reset_peek(self) -> None:
        """Força o peek para oculto (chamar em navegação/reset de página)."""
        self._set_peek(False)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Detecta Ctrl+Shift segurados para ativar/desativar o peek."""
        try:
            key_event = cast(QKeyEvent, event)
            etype = key_event.type()
            if etype == QEvent.Type.KeyPress:
                if (
                    key_event.key() == Qt.Key.Key_Shift
                    and key_event.modifiers() & Qt.KeyboardModifier.ControlModifier
                ):
                    self._set_peek(True)
                elif (
                    key_event.key() == Qt.Key.Key_Control
                    and key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                ):
                    self._set_peek(True)
            elif etype == QEvent.Type.KeyRelease:
                if key_event.key() in (Qt.Key.Key_Shift, Qt.Key.Key_Control):
                    mods = key_event.modifiers()
                    has_ctrl = mods & Qt.KeyboardModifier.ControlModifier
                    has_shift = mods & Qt.KeyboardModifier.ShiftModifier
                    if not (has_ctrl and has_shift):
                        self._set_peek(False)
        except RuntimeError:
            pass
        return super().eventFilter(obj, event)

    def _set_peek(self, show: bool) -> None:
        """Exibe ou oculta as dicas de atalho nos widgets registrados."""
        if show == self._peek_active:
            return
        self._peek_active = show
        for widget, suffix in self._hints:
            if show and not widget.isVisible():
                continue
            if isinstance(widget, QPushButton):
                if show:
                    widget.setText(widget.text() + suffix)
                elif widget.text().endswith(suffix):
                    widget.setText(widget.text()[: -len(suffix)])
            elif isinstance(widget, QLineEdit):
                if show:
                    widget.setPlaceholderText(widget.placeholderText() + suffix)
                elif widget.placeholderText().endswith(suffix):
                    widget.setPlaceholderText(
                        widget.placeholderText()[: -len(suffix)]
                    )
        for cb in self._peek_callbacks:
            cb(show)
