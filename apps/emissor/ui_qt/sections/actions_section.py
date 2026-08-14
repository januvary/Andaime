#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ActionsSection — botões de ação (Qt): Salvar Dados, Imprimir,
Salvar Recibo, Registrar Olostech, Abrir PDF e Digitalizar. Observa
DIRTY_STATE_CHANGED, PDF_GENERATED e PATIENT_SELECTED."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QSizePolicy, QWidget

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from emissor.state.state_events import StateEventType
from emissor.ui_qt.base import QtSection, on
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
        self._olostech_btn = make_button("Olostech", "action-3", self)
        self._open_pdf_btn = make_button("Abrir PDF", "action-4", self)
        self._scan_btn = make_button("Digitalizar", "action-4", self)

        self._olostech_enabled = False
        self._current_retirada = None

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
        grid.setRowStretch(2, 4)  # Salvar PDF + Registrar Olostech
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

        # Salvar Recibo + Registrar Olostech na mesma linha
        self._save_pdf_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._save_pdf_btn.clicked.connect(self.app.handle_save_pdf)
        grid.addWidget(self._save_pdf_btn, 2, 0)

        self._olostech_btn.setEnabled(False)
        self._olostech_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._olostech_btn.clicked.connect(self.app.handle_olostech_registration)
        grid.addWidget(self._olostech_btn, 2, 1)

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

    def set_olostech_registered(self, registered: bool) -> None:
        """Atualiza estado do botão Olostech.

        Se True, mostra "Registrador" e desabilita.
        Se False, mostra "Olostech" e habilita (se retirada existir).
        """
        if self._olostech_btn is None:
            return
        if registered:
            self._olostech_btn.setText("Registrado")
            self._olostech_btn.setEnabled(False)
        else:
            self._olostech_btn.setText("Olostech")
            # Habilitação condicional: só habilita se houver retirada
            # O enable_olostech_button cuida disso
            self._olostech_btn.setEnabled(self._olostech_enabled)

    def enable_olostech_button(self) -> None:
        """Habilita o botão Registrar Olostech (retirada existente)."""
        self._olostech_enabled = True
        if self._olostech_btn is not None and self._olostech_btn.text() != "Registrado":
            self._olostech_btn.setEnabled(True)

    def disable_olostech_button(self) -> None:
        """Desabilita o botão Registrar Olostech."""
        self._olostech_enabled = False
        if self._olostech_btn is not None:
            self._olostech_btn.setEnabled(False)

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

    @on(StateEventType.PDF_GENERATED)
    def _on_pdf_generated(self, data: dict) -> None:
        self.enable_open_pdf_button()

    @on(StateEventType.DIRTY_STATE_CHANGED)
    def _on_dirty_changed(self, data: dict) -> None:
        count = int(data.get("dirty_count", 0))
        self.update_save_button(count)

    @on(StateEventType.PATIENT_SELECTED)
    def _on_patient_selected(self, data: dict) -> None:
        patient = data.get("patient")
        if patient is not None and getattr(patient, "tem_retirada", False):
            self.enable_open_pdf_button()
        else:
            self.disable_open_pdf_button()
        self.enable_scan_button()
        self._check_olostech_state()

    @on(StateEventType.PATIENT_CLEARED)
    def _on_patient_cleared(self, data: dict) -> None:
        self.disable_open_pdf_button()
        self.disable_scan_button()
        self.disable_olostech_button()
        self._olostech_btn.setText("Olostech")
        self._current_retirada = None

    @on(StateEventType.PATIENT_UPDATED)
    def _on_patient_updated(self, data: dict) -> None:
        self._check_olostech_state()

    @on(StateEventType.DATE_RECALCULATION_NEEDED)
    def _on_date_recalc_needed(self, data: dict) -> None:
        self._check_olostech_state()

    def _check_olostech_state(self) -> None:
        """Verifica se há retirada existente e atualiza botão Olostech."""
        patient_id = self.patient_id
        if patient_id is None:
            self.disable_olostech_button()
            return

        dates_section = getattr(self.app, "dates_section", None)
        if dates_section is None:
            self.disable_olostech_button()
            return

        try:
            _, date_str = dates_section.get_data_retirada_for_pdf()
        except Exception:
            self.disable_olostech_button()
            return

        if not date_str:
            self.disable_olostech_button()
            return

        self.run_db(
            self.db.get_retirada_by_date,
            patient_id,
            date_str,
            on_done=self._apply_olostech_state,
        )

    def _apply_olostech_state(self, retirada: Any) -> None:
        """Atualiza estado do botão Olostech conforme retirada."""
        self._current_retirada = retirada
        if retirada is None:
            self._olostech_btn.setText("Olostech")
            self.disable_olostech_button()
            return
        if getattr(retirada, "olostech_ok", 0):
            self.set_olostech_registered(True)
        else:
            self.set_olostech_registered(False)
            self.enable_olostech_button()
