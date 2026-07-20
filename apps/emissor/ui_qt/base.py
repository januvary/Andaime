#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QtSection — classe base para as seções da UI Qt.

Espelha o contrato de BaseSection (CTk): referência à app, registro como
StateObserver, cleanup de widgets e handler de erro. Cada seção é um QFrame
(painel) com header opcional e área de conteúdo. A comunicação entre seções é
sempre via StateManager (eventos), nunca por chamadas diretas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from emissor.state.state_events import StateEvent, StateObserver


class QtSection(QFrame, StateObserver):
    """Painel retangular base com header opcional e área de conteúdo."""

    #: Se True, a seção não se registra como observadora (ex.: busca, só output).
    _output_only: bool = False

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        super().__init__(parent)
        self._app = app
        self._is_registered = False
        self._widgets_to_cleanup: list[tuple[str, QWidget | None]] = []
        self._section_header: QFrame | None = None

        self.setProperty("class", "panel")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        self._register_observer()

    @property
    def app(self) -> QtApp:
        """Retorna a referência à aplicação."""
        return self._app

    # ========== Observer ==========

    def _register_observer(self) -> None:
        """Registra a seção como observadora do StateManager."""
        if self._output_only:
            return
        state_manager = getattr(self._app, "state_manager", None)
        if state_manager is None:
            return
        try:
            state_manager.register_observer(self)
            self._is_registered = True
        except Exception:
            self._is_registered = False

    def on_state_changed(self, event: StateEvent) -> None:
        """Chamado quando o estado observado muda. Override nas subclasses."""

    def _handle_state_change_error(self, e: Exception, section_name: str) -> None:
        """Trata erro de on_state_changed de forma consistente."""
        from andaime.error_handler import (
            ErrorContext,
            ErrorHandler,
            ErrorLevel,
        )

        ErrorHandler.handle_error(
            e,
            context=ErrorContext.UI,
            level=ErrorLevel.ERROR,
            recovery_hint=f"Erro em {section_name}.on_state_changed(): {e}",
            show_dialog=True,
        )

    # ========== Construção de UI ==========

    def add_header(self, title: str) -> QFrame:
        """Adiciona barra de header com título; retorna o QFrame para estilo."""
        header = QFrame()
        header.setProperty("class", "panel-header")
        header.setFixedHeight(32)
        hl = QVBoxLayout(header)
        hl.setContentsMargins(10, 0, 10, 0)
        label = QLabel(title)
        label.setProperty("class", "panel-title")
        hl.addWidget(label)
        self._root.addWidget(header)
        self._section_header = header
        return header

    def content_layout(self) -> QVBoxLayout:
        """Cria e retorna o layout de conteúdo (padding padrão)."""
        content = QVBoxLayout()
        content.setContentsMargins(10, 8, 10, 8)
        content.setSpacing(6)
        self._root.addLayout(content)
        return content

    # ========== Helpers de widget ==========

    def register_widget(self, name: str, widget: QWidget | None) -> None:
        """Registra widget para tracking/cleanup."""
        setattr(self, name, widget)
        self._widgets_to_cleanup.append((name, widget))

    @staticmethod
    def is_widget_valid(widget: Any) -> bool:
        """True se o widget é utilizável (não nulo)."""
        return widget is not None

    # ========== Ciclo de vida ==========

    def finish_edit(self) -> None:
        """Hook chamado ao finalizar edição. Override nas subclasses."""

    def cleanup(self) -> None:
        """Desregistra do StateManager. Chamar no fechamento da janela."""
        if self._is_registered:
            state_manager = getattr(self._app, "state_manager", None)
            if state_manager is not None:
                try:
                    state_manager.unregister_observer(self)
                except Exception:
                    pass
            self._is_registered = False
