#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SearchSection — barra superior de busca de pacientes (Qt).

Busca com autocomplete local usando andaime.widgets.SearchableComboBox
(match accent-insensitive). O catálogo de pacientes é carregado uma vez
em memória e atualizado quando pacientes são criados/selecionados.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from andaime.widgets import SearchableComboBox, static_search_fn

from emissor.state.state_events import StateEvent, StateEventType
from emissor.ui_qt.base import QtSection
from emissor.ui_qt.brasao import get_brasao_pixmap
from emissor.ui_qt.theme import ThemeToggleButton, make_button


class SearchSection(QtSection):
    """Barra superior com busca de pacientes e ações primárias."""

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        """
        Inicializa a seção de busca.

        Args:
            parent: Widget pai
            app: Referência à aplicação principal (QtApp)
        """
        super().__init__(parent, app)

        self._search_combo: SearchableComboBox | None = None
        self._theme_toggle: ThemeToggleButton | None = None
        self._brasao_label: QLabel | None = None
        self._current_patient: dict[str, Any] | None = None
        self._patient_options: dict[str, str] = {}

        self._load_patients()
        self._build_ui()

    # ========== Pacientes ==========

    def _load_patients(self) -> None:
        """Carrega todos os pacientes para autocomplete local."""
        try:
            rows = self.app.db.get_all_patient_names()
        except Exception as e:
            ErrorHandler.log(
                f"Erro ao carregar pacientes: {e}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.DATABASE,
            )
            rows = []

        self._patient_options = {}
        for p in rows:
            pid = str(p.get("id", ""))
            nome = p.get("nome", "")
            if not pid or not nome:
                continue
            label = f"{nome} (INSULINA)" if p.get("tipo") == "insulina" else nome
            self._patient_options[pid] = label

    def _refresh_patient_options(self) -> None:
        """Recarrega pacientes e atualiza as opções do combo."""
        self._load_patients()
        if self._search_combo is not None:
            self._search_combo.set_search_fn(static_search_fn(self._patient_options))

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói a barra: linha de controles."""
        content = self.content_layout()

        # Três colunas ocultas (sem borda) que correspondem às três
        # colunas do layout principal (Patient=5, Options=6, Right=3).
        from emissor.main_window import (  # noqa: E402
            _COL_PATIENT,
            _COL_OPTIONS,
            _COL_RIGHT,
        )

        self._theme_toggle = ThemeToggleButton(self)
        self._theme_toggle.theme_toggled.connect(self.app._on_theme_toggled)
        self._theme_toggle.theme_toggled.connect(self._update_brasao)

        # Busca com autocomplete (accent-insensitive, local)
        self._search_combo = SearchableComboBox(
            search_fn=static_search_fn(self._patient_options),
            placeholder="Digite o nome do paciente...",
            parent=self,
        )
        self._search_combo.setMaximumWidth(440)
        self._search_combo.setFixedHeight(34)
        self._search_combo.selection_changed.connect(self._on_selection_changed)

        # Coluna 1 (Patient): theme toggle + busca ocupam a coluna
        col1 = QWidget(self)
        lay1 = QHBoxLayout(col1)
        lay1.setContentsMargins(0, 0, 0, 0)
        lay1.setSpacing(8)
        lay1.addWidget(self._theme_toggle)
        lay1.addWidget(self._search_combo, stretch=1)

        # Botões (criados aqui, distribuídos nas colunas 2 e 3)
        new_patient_btn = make_button("Novo Paciente", "flat-fill", self)
        new_patient_btn.clicked.connect(self.on_new_patient_clicked)

        agenda_btn = make_button("Abrir Agenda", "flat-fill", self)
        agenda_btn.clicked.connect(self.on_agenda_clicked)

        config_btn = make_button("Configuração", "flat-fill", self)
        config_btn.clicked.connect(self.on_config_clicked)

        # Reiniciar: mesmo estilo do theme toggle (icon, 28x28)
        restart_btn = make_button("↺", "icon", self)
        restart_btn.setFixedSize(28, 28)
        restart_btn.clicked.connect(self.on_restart_clicked)

        # Coluna 2 (Options): Novo Paciente à esquerda,
        # Agenda/Config/Reiniciar à direita
        col2 = QWidget(self)
        lay2 = QHBoxLayout(col2)
        lay2.setContentsMargins(0, 0, 0, 0)
        lay2.setSpacing(8)
        lay2.addWidget(new_patient_btn)
        lay2.addStretch()
        lay2.addWidget(agenda_btn)
        lay2.addWidget(config_btn)
        lay2.addWidget(restart_btn)

        # Coluna 3 (Right): brasão centralizado
        self._brasao_label = QLabel(self)
        self._update_brasao(self.app.config_manager.get("dark_mode", True))

        col3 = QWidget(self)
        lay3 = QHBoxLayout(col3)
        lay3.setContentsMargins(0, 0, 0, 0)
        lay3.setSpacing(8)
        lay3.addStretch()
        lay3.addWidget(self._brasao_label)
        lay3.addStretch()

        # Linha principal: três colunas com os pesos do layout
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(col1, stretch=_COL_PATIENT)
        row.addWidget(col2, stretch=_COL_OPTIONS)
        row.addWidget(col3, stretch=_COL_RIGHT)

        content.addLayout(row)

    # ========== Busca / Autocomplete ==========

    def _on_selection_changed(self, key: object) -> None:
        """
        Trata seleção de paciente no autocomplete.

        Args:
            key: ID do paciente (str) emitido pelo SearchableComboBox
        """
        if not isinstance(key, str):
            return
        try:
            pid = int(key)
        except ValueError:
            return
        self.select_patient({"id": pid})

    # ========== Event Handlers ==========

    def on_new_patient_clicked(self) -> None:
        """Handler do botão Novo Paciente."""
        if self._search_combo is not None:
            self._search_combo.clear()

        self.app.state_manager.clear_selected_patient()
        self.app.dirty_tracker.reset()

        # Habilitar edição na seção de paciente (quando existir)
        patient_section = getattr(self.app, "patient_section", None)
        if patient_section is not None and hasattr(
            patient_section, "set_name_id_editable"
        ):
            patient_section.set_name_id_editable(True)

        self.set_status("Modo: Novo Paciente")

    def select_patient(self, patient: dict[str, Any]) -> None:
        """
        Seleciona um paciente e dispara a carga dos dados completos (assíncrono).

        A busca do paciente completo roda no DB worker; a propagação para o
        StateManager e a barra de status acontece em _apply_selected_patient,
        na thread principal. Não bloqueia a UI.

        Args:
            patient: Dicionário com dados do paciente (precisa ter "id")
        """
        self._current_patient = patient
        self.set_status("Carregando paciente...")
        self.app.db_runner.run(
            self.app.db.get_patient_by_id,
            patient["id"],
            on_done=lambda full: self._apply_selected_patient(patient, full),
        )

    def _apply_selected_patient(
        self, patient: dict[str, Any], full_patient: Any
    ) -> None:
        """
        Propaga o paciente selecionado ao StateManager (thread principal).

        Args:
            patient: Dicionário mínimo repassado como fallback.
            full_patient: Paciente completo retornado por db.get_patient_by_id.
        """
        patient_to_set = full_patient or patient
        self.app.state_manager.set_selected_patient(patient_to_set)
        self.app.set_dirty_baseline()

        nome = patient_to_set.get("nome") or patient.get("nome", "")
        self.set_status(f"Paciente selecionado: {nome}")

    # ========== StateObserver ==========

    def on_state_changed(self, event: StateEvent) -> None:
        """Reage a mudanças de estado do StateManager."""
        try:
            if event.event_type == StateEventType.PATIENT_SELECTED:
                self._sync_combo_to_patient(event.data.get("patient", {}))
            elif event.event_type == StateEventType.PATIENT_UPDATED:
                updates = event.data.get("updates", {})
                if "nome" in updates or "tipo" in updates:
                    self._refresh_patient_options()
            elif event.event_type == StateEventType.PATIENT_CLEARED:
                self.clear_search()
        except Exception as e:
            self._handle_state_change_error(e, self.__class__.__name__)

    def _sync_combo_to_patient(self, patient: dict[str, Any]) -> None:
        """Sincroniza o combo de busca com o paciente selecionado.

        Recarrega o índice de pacientes apenas quando o paciente selecionado
        não está presente (ex.: recém-criado), evitando uma leitura completa
        da tabela a cada seleção.

        Args:
            patient: Dicionário com dados do paciente selecionado.
        """
        if not patient or self._search_combo is None:
            return
        pid = str(patient.get("id", ""))
        if pid and pid not in self._patient_options:
            self._refresh_patient_options()
        nome = patient.get("nome", "")
        current = self._search_combo.current_text()
        if current != nome:
            self._search_combo.set_current_by_data(pid)

    # ========== Helpers ==========

    def _update_brasao(self, dark_mode: bool) -> None:
        """
        Atualiza o pixmap do brasão conforme o tema (claro/escuro).

        Args:
            dark_mode: True para modo escuro (tinta clara)
        """
        if self._brasao_label is None:
            return
        pixmap = get_brasao_pixmap(height=41, dark_mode=dark_mode)
        if pixmap is not None:
            self._brasao_label.setPixmap(pixmap)

    def clear_search(self) -> None:
        """Limpa campo de busca e estado."""
        if self._search_combo is not None:
            self._search_combo.clear()
        self.set_status("")
        self._current_patient = None

    def focus_search(self) -> None:
        """Foca o campo de busca (atalho Ctrl+R)."""
        if self._search_combo is not None:
            self._search_combo.focus_search()

    def set_search_text(self, text: str) -> None:
        """
        Limpa o campo de busca quando text é vazio.

        O SearchableComboBox gerencia seu próprio texto via seleção; não há
        setter público para texto arbitrário.

        Args:
            text: Texto (apenas "" tem efeito — limpa o campo)
        """
        if not text and self._search_combo is not None:
            self._search_combo.clear()

    def set_status(
        self,
        text: str,
        color: str | None = None,
        path: str | None = None,
    ) -> None:
        """
        Define texto do status (delegado ao label global da janela).

        Args:
            text: Texto do status
            color: Cor opcional para o texto (hex)
            path: Caminho opcional que torna o status clicável
        """
        self.app.set_status(text, color, path=path)

    # ========== Callbacks dos Botões ==========

    def on_restart_clicked(self) -> None:
        """Callback do botão Reiniciar."""
        self.app.restart_app()

    def on_config_clicked(self) -> None:
        """Callback do botão Configuração."""
        self.app.open_config_dialog()

    def on_agenda_clicked(self) -> None:
        """Callback do botão Agenda."""
        self.app.launch_agenda()
