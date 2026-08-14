#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QtSection — classe base para as seções da UI Qt.

Espelha o contrato de BaseSection (CTk): referência à app, registro como
StateObserver, cleanup de widgets e handler de erro. Cada seção é um QFrame
(painel) com header opcional e área de conteúdo. A comunicação entre seções é
sempre via StateManager (eventos), nunca por chamadas diretas."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QWidget, QVBoxLayout, QLabel, QFrame

if TYPE_CHECKING:
    from emissor.main_window import QtApp
    from emissor.database.emissor_db import EmissorDatabase
    from emissor.state.state_manager import StateManager

from emissor.state.state_events import StateEvent, StateEventType, StateObserver


def on(event_type: StateEventType):
    """Registra o método como handler para um tipo de evento."""
    def decorator(fn):
        fn._event_type = event_type
        return fn
    return decorator


class QtSection(QFrame, StateObserver):
    """Painel retangular base com header opcional e área de conteúdo."""

    #: Emitido quando um campo da seção muda (usado para recomputar dirty state).
    field_changed = Signal()

    #: Se True, a seção não se registra como observadora (ex.: busca, só output).
    _output_only: bool = False

    _on_handlers: dict[StateEventType, Any] = {}  # populated by __init_subclass__

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        handlers: dict[StateEventType, Any] = {}
        for attr in vars(cls).values():
            if callable(attr) and hasattr(attr, "_event_type"):
                handlers[attr._event_type] = attr
        cls._on_handlers = {**QtSection._on_handlers, **handlers}

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

    @property
    def patient_id(self) -> int | None:
        """ID do paciente selecionado (atalho para state_manager)."""
        return self._app.state_manager.get_patient_id()

    # ========== Acesso a dados ==========

    @property
    def state(self) -> StateManager:
        """StateManager da aplicação — estado compartilhado + eventos."""
        return self._app.state_manager

    @property
    def db(self) -> EmissorDatabase:
        """Banco da aplicação — leitura síncrona direta dos métodos."""
        return self._app.db

    def run_db(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_done: Callable[[Any], None],
    ) -> None:
        """Executa ``fn`` (método de ``self.db``) no worker thread; o
        resultado chega em ``on_done`` na thread principal."""
        self._app.db_runner.run(fn, *args, on_done=on_done)

    @staticmethod
    def set_edit_text(edit: QLineEdit | None, value: str) -> None:
        """Define texto de um QLineEdit sem disparar handlers (blockSignals)."""
        if edit is None:
            return
        edit.blockSignals(True)
        edit.setText(value)
        edit.setCursorPosition(0)
        edit.blockSignals(False)

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
        except Exception as e:
            from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
            ErrorHandler.log(
                f"Falha ao registrar observer: {e}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.UI,
            )
            self._is_registered = False

    def on_state_changed(self, event: StateEvent) -> None:
        """Despacha eventos para handlers registrados via @on."""
        handler = self._on_handlers.get(event.event_type)
        if handler is None:
            return
        try:
            handler(self, event.data)
        except Exception as e:
            self._handle_state_change_error(e, self.__class__.__name__)

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
