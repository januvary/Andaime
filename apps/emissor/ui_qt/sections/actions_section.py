#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ActionsSection — botões de ação (Qt): Salvar Dados, Imprimir,
Salvar Recibo, Abrir PDF e Digitalizar. Observa DIRTY_STATE_CHANGED,
PDF_GENERATED e PATIENT_SELECTED."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from emissor.state.state_events import StateEvent, StateEventType
from emissor.ui_qt.base import QtSection
from emissor.ui_qt.theme import make_button


class ActionsSection(QtSection):
    """Painel de ações: salvar dados, imprimir, salvar/abrir PDF."""

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        super().__init__(parent, app)
        # Painel transparente, igual DatesSection — os botões são os elementos visuais
        self.setProperty("class", "")

        self._save_data_btn = make_button("Salvar Dados", "action-1", self)
        self._print_btn = make_button("Imprimir", "action-2", self)
        self._save_pdf_btn = make_button("Salvar Recibo", "action-3", self)
        self._open_pdf_btn = make_button("Abrir PDF", "action-4", self)
        self._scan_btn = make_button("Digitalizar", "action-4", self)

        self._build_ui()

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói os botões de ação."""
        content = self.content_layout()
        content.setContentsMargins(6, 6, 6, 6)
        content.setSpacing(0)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        # Pesos verticais espelhando ActionsSectionV3 (CTk)
        grid.setRowStretch(0, 2)  # Salvar Dados
        grid.setRowStretch(1, 5)  # Imprimir
        grid.setRowStretch(2, 4)  # Salvar PDF
        grid.setRowStretch(3, 2)  # Abrir PDF + Digitalizar

        # Salvar Dados: mais estreito, centralizado horizontalmente
        self._save_data_btn.setMinimumWidth(150)
        self._save_data_btn.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding
        )
        self._save_data_btn.clicked.connect(self.app.save_patient_data)
        grid.addWidget(
            self._save_data_btn,
            0,
            0,
            1,
            2,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        self._print_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._print_btn.clicked.connect(self.app.handle_print)
        grid.addWidget(self._print_btn, 1, 0, 1, 2)

        self._save_pdf_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._save_pdf_btn.clicked.connect(self.app.handle_save_pdf)
        grid.addWidget(self._save_pdf_btn, 2, 0, 1, 2)

        self._open_pdf_btn.setEnabled(False)
        self._open_pdf_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._open_pdf_btn.clicked.connect(self.app.handle_open_pdf)
        grid.addWidget(self._open_pdf_btn, 3, 0)

        # Digitalizar: exige paciente + data selecionados (começa desabilitado)
        # Mesma linha e cor de "Abrir PDF"
        self._scan_btn.setEnabled(False)
        self._scan_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._scan_btn.clicked.connect(self.app.handle_scan)
        grid.addWidget(self._scan_btn, 3, 1)

        content.addLayout(grid, stretch=1)

    # ========== API pública ==========

    def enable_open_pdf_button(self) -> None:
        """Habilita o botão Abrir PDF."""
        if self._open_pdf_btn is not None:
            self._open_pdf_btn.setEnabled(True)

    def disable_open_pdf_button(self) -> None:
        """Desabilita o botão Abrir PDF."""
        if self._open_pdf_btn is not None:
            self._open_pdf_btn.setEnabled(False)

    def enable_scan_button(self) -> None:
        """Habilita o botão Digitalizar (paciente + data selecionados)."""
        if self._scan_btn is not None:
            self._scan_btn.setEnabled(True)

    def disable_scan_button(self) -> None:
        """Desabilita o botão Digitalizar."""
        if self._scan_btn is not None:
            self._scan_btn.setEnabled(False)

    def set_pdf_actions_busy(self, busy: bool) -> None:
        """Bloqueia/desbloqueia Imprimir + Salvar Recibo durante operações
        assíncronas (evita duplo-clique enquanto o worker thread executa)."""
        if self._print_btn is not None:
            self._print_btn.setEnabled(not busy)
        if self._save_pdf_btn is not None:
            self._save_pdf_btn.setEnabled(not busy)

    def update_save_button(self, unsaved_count: int) -> None:
        """Atualiza texto do botão Salvar Dados com o contador; 0 esconde."""
        if unsaved_count > 0:
            self._save_data_btn.setText(f"Salvar Dados ({unsaved_count})")
        else:
            self._save_data_btn.setText("Salvar Dados")

    # ========== StateObserver ==========

    def on_state_changed(self, event: StateEvent) -> None:
        """Reage a mudanças de estado do StateManager / DirtyTracker."""
        try:
            if event.event_type == StateEventType.PDF_GENERATED:
                self.enable_open_pdf_button()
            elif event.event_type == StateEventType.DIRTY_STATE_CHANGED:
                count = int(event.data.get("dirty_count", 0))
                self.update_save_button(count)
            elif event.event_type == StateEventType.PATIENT_SELECTED:
                # Abrir PDF fica disponível se o paciente já tiver recibos salvos.
                # O flag vem do paciente já carregado (get_patient_by_id), sem
                # consulta extra nem bloqueio da UI.
                patient = event.data.get("patient")
                if patient is not None and getattr(patient, "tem_retirada", False):
                    self.enable_open_pdf_button()
                else:
                    self.disable_open_pdf_button()
                self.enable_scan_button()
            elif event.event_type == StateEventType.PATIENT_CLEARED:
                self.disable_open_pdf_button()
                self.disable_scan_button()
        except Exception as e:
            self._handle_state_change_error(e, self.__class__.__name__)
