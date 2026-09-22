#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DatesSection — datas (retirada, próxima, validade); reage a eventos."""

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

from emissor.state.state_events import StateEventType
from emissor.ui_qt.base import QtSection, on
from emissor.ui_qt.theme import PX_LARGE
from emissor.utils.field_utils import get_field_str

# Largura máxima do QDateEdit de retirada (formato dd/MM/yyyy).
_HOJE_EDIT_MAX_WIDTH = 165


class DatesSection(QtSection):
    """Painel de datas: retirada editável + próximas calculadas."""

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        """Inicializa datas (retirada, próxima, validade); args: parent, app."""
        super().__init__(parent, app)
        # Contêiner transparente — os boxes de data são os elementos visuais
        self.setProperty("class", "")

        self._hoje_edit: QDateEdit | None = None
        self._retirada_segment_index: int = 0  # day → month → year cycle
        self._retirada_registered_label: QLabel | None = None
        self._proxima_label: QLabel | None = None
        self._proxima_countdown: QLabel | None = None
        self._proxima_distribution: QLabel | None = None
        self._ultima_retirada_label: QLabel | None = None
        self._proxima_marcada_label: QLabel | None = None

        self._build_ui()
        self.update_today_date()

        # Debounce da recalculação (substitui self.after do CTk)
        self._recalc_timer = QTimer(self)
        self._recalc_timer.setSingleShot(True)
        self._recalc_timer.setInterval(50)
        self._recalc_timer.timeout.connect(self.recalculate_dates)

        # Geração anti-obsoleto: só o recálculo mais recente atualiza os labels.
        self._recalc_seq = 0

    # UI

    def _build_ui(self) -> None:
        """Constrói os três boxes de data (graded neutral)."""
        content = self.content_layout()
        content.setSpacing(6)

        # Última Retirada
        box4, lay4 = self._date_box("date-box-4")
        self._ultima_retirada_label = QLabel("—")
        self._ultima_retirada_label.setStyleSheet(f"font-size: {PX_LARGE + 1}px;")
        self._ultima_retirada_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._proxima_marcada_label = QLabel("")
        self._proxima_marcada_label.setProperty("class", "dim")
        self._proxima_marcada_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        titulo4 = self._title_label("Última Retirada:")
        titulo4.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay4.addWidget(titulo4)
        lay4.addWidget(self._ultima_retirada_label)
        lay4.addWidget(self._proxima_marcada_label)
        content.addWidget(box4)

        # Data da Retirada
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

        # Próxima Retirada
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

    @staticmethod
    def _date_box(class_name: str) -> tuple[QFrame, QVBoxLayout]:
        """Contêiner de data (class_name QSS); retorna (QFrame, QVBoxLayout)."""
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

    # Eventos

    def _on_date_changed(self, _new_date: QDate) -> None:
        """Data da retirada mudou → checa retirada existente e pede recálculo."""
        self.check_existing_retirada()
        self.state.request_date_recalculation()

    def focus_retirada(self) -> None:
        """Foca campo retirada (Ctrl+T); repetido avança DD→MM→AA."""
        if self._hoje_edit is None:
            return

        edit = self._hoje_edit
        if not edit.hasFocus():
            edit.setFocus()
            self._retirada_segment_index = 0
        else:
            self._retirada_segment_index = (self._retirada_segment_index + 1) % 3

        sections = [
            QDateEdit.Section.DaySection,
            QDateEdit.Section.MonthSection,
            QDateEdit.Section.YearSection,
        ]
        edit.setCurrentSection(sections[self._retirada_segment_index])

    def update_today_date(self) -> None:
        """Define a data da retirada para hoje (sem disparar recálculo)."""
        if self._hoje_edit is None:
            return
        self._hoje_edit.blockSignals(True)
        self._hoje_edit.setDate(QDate.currentDate())
        self._hoje_edit.blockSignals(False)

    # Cálculo

    def recalculate_dates(self) -> None:
        """Recalcula datas via worker; labels atualizados em ``_apply_recalculated`."""
        if self._hoje_edit is None:
            return

        params = {
            "data_retirada_str": self._hoje_edit.date().toString("dd/MM/yyyy"),
            "periodicidade_str": self.state.get_periodicidade(),
            "enable_distribution": self.app.config_manager.get(
                "distribute_retiradas", True
            ),
            "distribution_window_days": self.app.config_manager.get(
                "distribution_window_days", 3
            ),
            "bloquear_balanco": self.state.get_bloquear_balanco(),
        }
        if not params["periodicidade_str"]:
            self.state.set_calculated_dates({})
            self._set_label(self._proxima_label, "—")
            self._set_label(self._proxima_countdown, "")
            self._set_label(self._proxima_distribution, "")
            return

        self._recalc_seq += 1
        seq = self._recalc_seq
        db = self.db

        def _calc() -> dict:
            from emissor.utils.date_utils import DateCalculator

            return DateCalculator.calculate_proxima_vez(
                params["data_retirada_str"],
                periodicidade_str=params["periodicidade_str"],
                enable_distribution=params["enable_distribution"],
                distribution_window_days=params["distribution_window_days"],
                retirada_count_fn=db.count_retiradas_by_proxima_date,
                bloquear_balanco=params["bloquear_balanco"],
            )

        self.run_db(
            _calc,
            on_done=lambda result: self._apply_recalculated(seq, result),
            on_error=lambda exc: self._on_recalc_error(seq, exc, params),
        )

    def _apply_recalculated(self, seq: int, result: Any) -> None:
        """Aplica o resultado do recálculo e atualiza os labels (thread principal)."""
        if seq != self._recalc_seq:
            return  # obsoleto — um recálculo mais novo já foi pedido
        self.state.set_calculated_dates(result or {})
        self._update_proxima_labels(result or {})

    def _on_recalc_error(self, seq: int, exc: BaseException, params: dict) -> None:
        """Falha no recálculo (ex.: rede) — usa cálculo puro sem distribuição."""
        if seq != self._recalc_seq:
            return
        from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
        from emissor.utils.date_utils import DateCalculator

        ErrorHandler.log(
            f"Erro ao recalcular datas (usando cálculo sem distribuição): {exc}",
            level=ErrorLevel.WARNING,
            context=ErrorContext.DATABASE,
        )
        result = DateCalculator.calculate_proxima_vez(
            params["data_retirada_str"],
            periodicidade_str=params["periodicidade_str"],
            enable_distribution=False,
            distribution_window_days=params["distribution_window_days"],
            retirada_count_fn=None,
            bloquear_balanco=params["bloquear_balanco"],
        )
        self.state.set_calculated_dates(result or {})
        self._update_proxima_labels(result or {})

    def _update_proxima_labels(self, result: dict) -> None:
        """Atualiza os labels da próxima retirada a partir do resultado."""
        if not result:
            self._set_label(self._proxima_label, "—")
            self._set_label(self._proxima_countdown, "")
            self._set_label(self._proxima_distribution, "")
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

    def check_existing_retirada(self) -> None:
        """Verifica se já existe retirada para o paciente + data atual."""
        if self._retirada_registered_label is None or self._hoje_edit is None:
            return
        if not self.state.has_selected_patient():
            self._retirada_registered_label.setText("")
            return

        qd = self._hoje_edit.date()
        if not qd.isValid():
            self._retirada_registered_label.setText("")
            return

        patient_id = self.patient_id
        if patient_id is None:
            self._retirada_registered_label.setText("")
            return

        self.run_db(
            self.db.get_retirada_by_date,
            patient_id,
            qd.toString("yyyy-MM-dd"),
            on_done=self._apply_existing_retirada,
        )

    def _apply_existing_retirada(self, retirada: Any) -> None:
        """Atualiza aviso de retirada existente (thread principal); retirada pode ser None."""
        if self._retirada_registered_label is None:
            return
        if retirada:
            rid = getattr(retirada, "id", "?")
            self._retirada_registered_label.setText(f"⚠ Retirada registrada. ID: {rid}")
        else:
            self._retirada_registered_label.setText("")

    def refresh_ultima_retirada(self) -> None:
        """Carrega a última retirada ativa do paciente selecionado."""
        if self._ultima_retirada_label is None or self._proxima_marcada_label is None:
            return
        if not self.state.has_selected_patient():
            self._set_label(self._ultima_retirada_label, "—")
            self._set_label(self._proxima_marcada_label, "")
            return
        patient_id = self.patient_id
        if patient_id is None:
            self._set_label(self._ultima_retirada_label, "—")
            self._set_label(self._proxima_marcada_label, "")
            return
        self.run_db(
            self.db.get_ultima_retirada_ativa,
            patient_id,
            on_done=self._apply_ultima_retirada,
        )

    def _apply_ultima_retirada(self, ultima: Any) -> None:
        """Popula labels da última retirada ativa; ultima pode ser None."""
        if self._ultima_retirada_label is None or self._proxima_marcada_label is None:
            return
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

    # Leitura pública

    def get_data_retirada_for_pdf(self) -> tuple[str, str]:
        """Data da retirada validada para PDF (DD/MM/AAAA, AAAA-MM-DD)."""
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
        """Valores dos campos de data; retorna dict (hoje, proxima_vez)."""
        hoje = (
            self._hoje_edit.date().toString("dd/MM/yyyy")
            if self._hoje_edit is not None
            else ""
        )
        return {
            "hoje": hoje,
            "proxima_vez": self._proxima_label.text() if self._proxima_label else "",
        }

    # StateObserver

    @on(StateEventType.PATIENT_SELECTED)
    def _on_patient_selected(self, data: dict) -> None:
        patient_data = data.get("patient", {})
        self.state.update_date_fields(
            periodicidade=get_field_str(patient_data, "periodicidade"),
        )
        self.update_today_date()
        self.check_existing_retirada()
        self.refresh_ultima_retirada()

    @on(StateEventType.PATIENT_CLEARED)
    def _on_patient_cleared(self, data: dict) -> None:
        self.update_today_date()
        self._set_label(self._proxima_label, "—")
        self._set_label(self._proxima_countdown, "")
        self._set_label(self._proxima_distribution, "")
        self._set_label(self._retirada_registered_label, "")
        self._set_label(self._ultima_retirada_label, "—")
        self._set_label(self._proxima_marcada_label, "")

    @on(StateEventType.PATIENT_UPDATED)
    def _on_patient_updated(self, data: dict) -> None:
        updates = data.get("updates", {})
        if "periodicidade" in updates:
            self.state.update_date_fields(
                periodicidade=updates.get("periodicidade", ""),
            )
        self.refresh_ultima_retirada()

    @on(StateEventType.DATE_RECALCULATION_NEEDED)
    def _on_date_recalc_needed(self, data: dict) -> None:
        self._recalc_timer.start()

    # Helpers

    @staticmethod
    def _format_date(value: str) -> str:
        """Converte YYYY-MM-DD para dd/MM/yyyy; retorna vazio se inválido."""
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
