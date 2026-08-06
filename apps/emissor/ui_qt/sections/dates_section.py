#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DatesSection — seção de datas (Qt).

Espelha DatesSectionV3 (CTk): Data da Retirada editável (QDateEdit com
popup de calendário), Próxima Retirada e Validade da receita calculadas.
É um StateObserver: reage a PATIENT_SELECTED/CLEARED/UPDATED e a
DATE_RECALCULATION_NEEDED (com debounce via QTimer).

O cálculo em si é delegado a state_manager.calculate_dates() (backend
reutilizado da UI CTk). Apenas a camada de apresentação é nova.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from emissor.state.state_events import StateEvent, StateEventType
from emissor.ui_qt.base import QtSection
from emissor.ui_qt.theme import PX_LARGE
from emissor.utils.field_utils import get_field_str

# Largura máxima do QDateEdit de retirada (formato dd/MM/yyyy).
_HOJE_EDIT_MAX_WIDTH = 165


class DatesSection(QtSection):
    """Painel de datas: retirada editável + próximas calculadas."""

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        """
        Inicializa a seção de datas.

        Args:
            parent: Widget pai
            app: Referência à aplicação principal (QtApp)
        """
        super().__init__(parent, app)
        # Contêiner transparente — os boxes de data são os elementos visuais
        self.setProperty("class", "")

        self._hoje_edit: QDateEdit | None = None
        self._retirada_registered_label: QLabel | None = None
        self._proxima_label: QLabel | None = None
        self._proxima_countdown: QLabel | None = None
        self._proxima_distribution: QLabel | None = None
        self._validade_label: QLabel | None = None
        self._validade_countdown: QLabel | None = None
        self._ultima_retirada_label: QLabel | None = None
        self._proxima_marcada_label: QLabel | None = None

        self._calculation_mode: str = "full"

        self._build_ui()
        self.update_today_date()

        # Debounce da recalculação (substitui self.after do CTk)
        self._recalc_timer = QTimer(self)
        self._recalc_timer.setSingleShot(True)
        self._recalc_timer.setInterval(50)
        self._recalc_timer.timeout.connect(self.recalculate_dates)

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói os três boxes de data (graded neutral)."""
        content = self.content_layout()
        content.setSpacing(6)

        # === Última Retirada (histórico) ===
        box4, lay4 = self._date_box("date-box-4")
        self._ultima_retirada_label = QLabel("—")
        self._ultima_retirada_label.setStyleSheet(f"font-size: {PX_LARGE + 1}px;")
        self._ultima_retirada_label.setAlignment(Qt.AlignCenter)
        self._proxima_marcada_label = QLabel("")
        self._proxima_marcada_label.setProperty("class", "dim")
        self._proxima_marcada_label.setAlignment(Qt.AlignCenter)
        titulo4 = self._title_label("Última Retirada:")
        titulo4.setAlignment(Qt.AlignCenter)
        lay4.addWidget(titulo4)
        lay4.addWidget(self._ultima_retirada_label)
        lay4.addWidget(self._proxima_marcada_label)
        content.addWidget(box4)

        # === Data da Retirada (editável) ===
        box1, lay1 = self._date_box("date-box-1")
        self._hoje_edit = QDateEdit()
        self._hoje_edit.setDisplayFormat("dd/MM/yyyy")
        self._hoje_edit.setCalendarPopup(True)
        self._hoje_edit.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._hoje_edit.setDate(QDate.currentDate())
        self._hoje_edit.setStyleSheet(f"font-size: {PX_LARGE + 1}px;")
        self._hoje_edit.setMaximumWidth(_HOJE_EDIT_MAX_WIDTH)
        self._hoje_edit.dateChanged.connect(self._on_date_changed)
        lay1.addWidget(self._title_label("Data da Retirada:"))
        lay1.addWidget(self._hoje_edit)

        self._retirada_registered_label = QLabel("")
        self._retirada_registered_label.setProperty("class", "dim")
        lay1.addWidget(self._retirada_registered_label)
        content.addWidget(box1)

        # === Próxima Retirada (calculada) ===
        box2, lay2 = self._date_box("date-box-2")
        self._proxima_label = QLabel("—")
        self._proxima_label.setStyleSheet(f"font-size: {PX_LARGE + 1}px;")
        self._proxima_countdown = QLabel("")
        self._proxima_countdown.setProperty("class", "dim")
        self._proxima_distribution = QLabel("")
        lay2.addWidget(self._title_label("Próxima Retirada:"))
        lay2.addWidget(self._proxima_label)
        info2 = QHBoxLayout()
        info2.setContentsMargins(0, 0, 0, 0)
        info2.addWidget(self._proxima_countdown, stretch=1)
        info2.addWidget(self._proxima_distribution)
        lay2.addLayout(info2)
        content.addWidget(box2)

        # === Validade da receita (calculada) ===
        box3, lay3 = self._date_box("date-box-3")
        self._validade_label = QLabel("—")
        self._validade_label.setStyleSheet(f"font-size: {PX_LARGE + 1}px;")
        self._validade_countdown = QLabel("")
        self._validade_countdown.setProperty("class", "dim")
        lay3.addWidget(self._title_label("Validade da receita:"))
        lay3.addWidget(self._validade_label)
        lay3.addWidget(self._validade_countdown)
        content.addWidget(box3)

    @staticmethod
    def _date_box(class_name: str) -> tuple[QFrame, QVBoxLayout]:
        """
        Cria um contêiner de data com a classe de fundo indicada.

        Args:
            class_name: Classe QSS ("date-box-1/2/3") para a cor graded

        Returns:
            Tupla (QFrame, QVBoxLayout) pronto para receber widgets
        """
        frame = QFrame()
        frame.setProperty("class", class_name)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 6, 14, 8)
        lay.setSpacing(2)
        return frame, lay

    @staticmethod
    def _title_label(text: str) -> QLabel:
        """Cria o label de título de um box de data."""
        lbl = QLabel(text)
        lbl.setProperty("class", "dim")
        return lbl

    # ========== Eventos ==========

    def _on_date_changed(self, _new_date: QDate) -> None:
        """Data da retirada mudou → checa retirada existente e pede recálculo."""
        self.check_existing_retirada()
        self.app.state_manager.request_date_recalculation(
            calculation_mode="proxima_vez_only"
        )

    def update_today_date(self) -> None:
        """Define a data da retirada para hoje (sem disparar recálculo)."""
        if self._hoje_edit is None:
            return
        self._hoje_edit.blockSignals(True)
        self._hoje_edit.setDate(QDate.currentDate())
        self._hoje_edit.blockSignals(False)

    # ========== Cálculo ==========

    def recalculate_dates(self) -> None:
        """Recalcula as datas via StateManager e atualiza os labels."""
        if self._hoje_edit is None:
            return

        calculation_mode = self._calculation_mode
        self._calculation_mode = "full"

        data_retirada_str = self._hoje_edit.date().toString("dd/MM/yyyy")
        result = self.app.state_manager.calculate_dates(
            data_retirada_str=data_retirada_str,
            periodicidade_str=self.app.state_manager.get_periodicidade(),
            ultima_receita_str=self.app.state_manager.get_ultima_receita(),
            tipo_receita=self.app.state_manager.get_tipo_receita(),
            calculation_mode=calculation_mode,
            enable_distribution=self.app.config_manager.get(
                "distribute_retiradas", True
            ),
            distribution_window_days=self.app.config_manager.get(
                "distribution_window_days", 3
            ),
            retirada_count_fn=self.app.db.count_retiradas_by_proxima_date,
        )

        if not result:
            self._set_label(self._proxima_label, "—")
            self._set_label(self._proxima_countdown, "")
            self._set_label(self._proxima_distribution, "")
            self._set_label(self._validade_label, "—")
            self._set_label(self._validade_countdown, "")
            return

        if "proxima_vez_formatted" in result:
            self._set_label(
                self._proxima_label, result.get("proxima_vez_formatted") or "—"
            )
            self._set_label(
                self._proxima_countdown, result.get("proxima_vez_countdown", "")
            )
            if result.get("proxima_vez_foi_ajustada"):
                original = result.get("proxima_vez_data_original")
                texto = f"↩ {original.strftime('%d/%m')}" if original else ""
                self._set_label(self._proxima_distribution, texto)
            else:
                self._set_label(self._proxima_distribution, "")

        if "validade_receita_formatted" in result:
            self._set_label(
                self._validade_label,
                result.get("validade_receita_formatted") or "—",
            )
            self._set_label(
                self._validade_countdown,
                result.get("validade_receita_countdown", ""),
            )

    def check_existing_retirada(self) -> None:
        """Verifica se já existe retirada para o paciente + data atual."""
        if self._retirada_registered_label is None or self._hoje_edit is None:
            return
        if not self.app.state_manager.has_selected_patient():
            self._retirada_registered_label.setText("")
            return

        qd = self._hoje_edit.date()
        if not qd.isValid():
            self._retirada_registered_label.setText("")
            return

        patient_id = self.app.state_manager.get_patient_id()
        if patient_id is None:
            self._retirada_registered_label.setText("")
            return

        self.app.db_runner.run(
            self.app.db.get_retirada_by_date,
            patient_id,
            qd.toString("yyyy-MM-dd"),
            on_done=self._apply_existing_retirada,
        )

    def _apply_existing_retirada(self, retirada: Any) -> None:
        """
        Atualiza o aviso de retirada existente (thread principal).

        Args:
            retirada: Registro retornado por db.get_retirada_by_date, ou None.
        """
        if self._retirada_registered_label is None:
            return
        if retirada:
            rid = getattr(retirada, "id", "?")
            self._retirada_registered_label.setText(f"⚠ Retirada registrada. ID: {rid}")
        else:
            self._retirada_registered_label.setText("")

    def refresh_ultima_retirada(self) -> None:
        """Carrega a última retirada (ativa) do paciente selecionado."""
        if (
            self._ultima_retirada_label is None
            or self._proxima_marcada_label is None
        ):
            return
        if not self.app.state_manager.has_selected_patient():
            self._set_label(self._ultima_retirada_label, "—")
            self._set_label(self._proxima_marcada_label, "")
            return
        patient_id = self.app.state_manager.get_patient_id()
        if patient_id is None:
            self._set_label(self._ultima_retirada_label, "—")
            self._set_label(self._proxima_marcada_label, "")
            return
        self.app.db_runner.run(
            self.app.db.get_retiradas_by_patient,
            patient_id,
            on_done=self._apply_ultima_retirada,
        )

    def _apply_ultima_retirada(self, retiradas: Any) -> None:
        """
        Popula os labels com a última retirada ativa (thread principal).

        Args:
            retiradas: Lista de retiradas do paciente (mais recentes primeiro).
        """
        if (
            self._ultima_retirada_label is None
            or self._proxima_marcada_label is None
        ):
            return
        ultima = None
        if retiradas:
            for r in retiradas:
                if getattr(r, "substituida", 0) == 0:
                    ultima = r
                    break
        if ultima is None:
            self._set_label(self._ultima_retirada_label, "—")
            self._set_label(self._proxima_marcada_label, "")
            return
        self._set_label(
            self._ultima_retirada_label,
            self._format_date(getattr(ultima, "data_retirada", "")) or "—",
        )
        proxima = getattr(ultima, "data_proxima_retirada", "")
        if proxima:
            texto = f"prox. marcada: {self._format_date(proxima)}"
            try:
                if date.fromisoformat(proxima) > date.today() + timedelta(days=3):
                    texto = f"{texto} ⚠"
            except ValueError:
                pass
            self._set_label(self._proxima_marcada_label, texto)
        else:
            self._set_label(self._proxima_marcada_label, "")

    # ========== Leitura pública ==========

    def get_data_retirada_for_pdf(self) -> tuple[str, str]:
        """
        Retorna a data da retirada validada para uso no PDF.

        Returns:
            Tupla (data formatada DD/MM/AAAA, data para nome de arquivo AAAA-MM-DD)
        """
        if self._hoje_edit is None:
            d = date.today()
        else:
            qd = self._hoje_edit.date()
            iso = qd.toString("yyyy-MM-dd")
            try:
                d = date.fromisoformat(iso)
            except ValueError:
                d = date.today()
        return d.strftime("%d/%m/%Y"), d.strftime("%Y-%m-%d")

    def get_date_entries(self) -> dict[str, str]:
        """
        Retorna os valores dos campos de data.

        Returns:
            Dicionário com hoje/proxima_vez/validade_receita
        """
        hoje = (
            self._hoje_edit.date().toString("dd/MM/yyyy")
            if self._hoje_edit is not None
            else ""
        )
        return {
            "hoje": hoje,
            "proxima_vez": self._proxima_label.text() if self._proxima_label else "",
            "validade_receita": (
                self._validade_label.text() if self._validade_label else ""
            ),
        }

    # ========== StateObserver ==========

    def on_state_changed(self, event: StateEvent) -> None:
        """Reage a mudanças de estado do StateManager."""
        try:
            if event.event_type == StateEventType.PATIENT_SELECTED:
                patient_data = event.data.get("patient", {})
                self.app.state_manager.update_date_fields(
                    periodicidade=get_field_str(patient_data, "periodicidade"),
                    ultima_receita=get_field_str(patient_data, "ultima_receita"),
                    tipo_receita=get_field_str(patient_data, "tipo_receita"),
                )
                self.update_today_date()
                self.check_existing_retirada()
                self.refresh_ultima_retirada()
            elif event.event_type == StateEventType.PATIENT_CLEARED:
                self.update_today_date()
                self._set_label(self._proxima_label, "—")
                self._set_label(self._proxima_countdown, "")
                self._set_label(self._proxima_distribution, "")
                self._set_label(self._validade_label, "—")
                self._set_label(self._validade_countdown, "")
                self._set_label(self._retirada_registered_label, "")
                self._set_label(self._ultima_retirada_label, "—")
                self._set_label(self._proxima_marcada_label, "")
            elif event.event_type == StateEventType.PATIENT_UPDATED:
                updates = event.data.get("updates", {})
                if (
                    "periodicidade" in updates
                    or "ultima_receita" in updates
                    or "tipo_receita" in updates
                ):
                    self.app.state_manager.update_date_fields(
                        periodicidade=updates.get("periodicidade", ""),
                        ultima_receita=updates.get("ultima_receita", ""),
                        tipo_receita=updates.get("tipo_receita", ""),
                    )
                self.refresh_ultima_retirada()
            elif event.event_type == StateEventType.DATE_RECALCULATION_NEEDED:
                self._calculation_mode = event.data.get("calculation_mode", "full")
                self._recalc_timer.start()
        except Exception as e:
            self._handle_state_change_error(e, self.__class__.__name__)

    # ========== Helpers ==========

    @staticmethod
    def _format_date(value: str) -> str:
        """
        Converte data YYYY-MM-DD (banco) para dd/MM/yyyy.

        Args:
            value: Data no formato ISO (AAAA-MM-DD) ou vazia.

        Returns:
            Data formatada, ou string vazia se inválida/ausente.
        """
        if not value:
            return ""
        try:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        except ValueError:
            return ""

    @staticmethod
    def _set_label(label: QLabel | None, text: str) -> None:
        """Define texto de label de forma segura."""
        if label is not None:
            label.setText(text)

