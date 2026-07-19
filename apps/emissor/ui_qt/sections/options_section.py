#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OptionsSection — seção de opções (Qt).

Espelha OptionsSectionV3 (CTk): Tipo, Periodicidade, Última receita,
Atendido por, Tipo de Receita e Observações. É um StateObserver que reage
a PATIENT_SELECTED/CLEARED/UPDATED e PROCESSO_COUNT_CHANGED.

Radios são desselecionáveis (clicar no ativo desliga o grupo). Os campos
periodicidade/última receita/tipo_receita alimentam o cálculo de datas via
state_manager.update_date_field() — logo, editá-los aqui recalcula a
DatesSection em tempo real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from emissor.state.state_events import StateEvent, StateEventType
from emissor.ui_qt.base import QtSection
from emissor.utils.field_utils import get_field_str
from andaime.widgets import DateLineEdit

# Larguras de campos (espelham constantes da app CTk)
_PERIODICIDADE_WIDTH = 50
_ULTIMA_RECEITA_WIDTH = 110


class OptionsSection(QtSection):
    """Painel de opções do recibo."""

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        """
        Inicializa a seção de opções.

        Args:
            parent: Widget pai
            app: Referência à aplicação principal (QtApp)
        """
        super().__init__(parent, app)

        self._tipo_radios: dict[str, QRadioButton] = {}
        self._tipo_receita_radios: dict[str, QRadioButton] = {}
        self._last_tipo: str = ""
        self._last_tipo_receita: str = ""

        self._periodicidade_edit: QLineEdit | None = None
        self._ultima_receita_edit: QLineEdit | None = None
        self._atendido_por_edit: QLineEdit | None = None
        self._observacoes_edit: QPlainTextEdit | None = None
        self._radio_municipal_e_revezado: QRadioButton | None = None

        self._build_ui()

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói os campos de opções."""
        content = self.content_layout()
        content.setSpacing(10)
        content.setContentsMargins(15, 15, 12, 12)

        # === Tipo (radios horizontais) ===
        tipo_row = QHBoxLayout()
        tipo_row.addWidget(QLabel("Tipo:"))
        for label, value in (
            ("Revezado", "revezado"),
            ("Municipal", "municipal"),
            ("Municipal e Revezado", "municipal_e_revezado"),
            ("Insulina", "insulina"),
        ):
            rb = self._make_radio(label, value, self._on_tipo_clicked)
            tipo_row.addWidget(rb)
            self._tipo_radios[value] = rb
            if value == "municipal_e_revezado":
                self._radio_municipal_e_revezado = rb
                rb.setEnabled(False)  # habilitado só com 2+ processos
        tipo_row.addStretch()
        content.addLayout(tipo_row)

        # === Periodicidade ===
        period_row = QHBoxLayout()
        period_row.addWidget(QLabel("Periodicidade:"))
        self._periodicidade_edit = QLineEdit()
        self._periodicidade_edit.setPlaceholderText("30")
        self._periodicidade_edit.setFixedWidth(_PERIODICIDADE_WIDTH)
        self._periodicidade_edit.setValidator(QIntValidator(1, 999))
        self._periodicidade_edit.textChanged.connect(self._on_periodicidade_changed)
        period_row.addWidget(self._periodicidade_edit)
        period_row.addWidget(QLabel("dias"))
        period_row.addStretch()
        content.addLayout(period_row)

        # === Última receita + Atendido por (lado a lado) ===
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Última receita:"))
        self._ultima_receita_edit = DateLineEdit()
        self._ultima_receita_edit.setFixedWidth(_ULTIMA_RECEITA_WIDTH)
        self._ultima_receita_edit.textChanged.connect(self._on_ultima_receita_changed)
        row3.addWidget(self._ultima_receita_edit)
        row3.addSpacing(20)
        row3.addWidget(QLabel("Atendido por:"))
        self._atendido_por_edit = QLineEdit()
        row3.addWidget(self._atendido_por_edit, stretch=1)
        content.addLayout(row3)

        # === Tipo de Receita + Observações (lado a lado) ===
        bottom = QHBoxLayout()

        receita_box = QGroupBox("Tipo de Receita")
        receita_lay = QVBoxLayout(receita_box)
        receita_lay.setSpacing(4)
        for label, value in (
            ("Tipo A (180 dias)", "tipo_a"),
            ("Tipo B (90 dias)", "tipo_b"),
            ("Tipo C (30 dias)", "tipo_c"),
        ):
            rb = self._make_radio(label, value, self._on_tipo_receita_clicked)
            receita_lay.addWidget(rb)
            self._tipo_receita_radios[value] = rb
        bottom.addWidget(receita_box)

        obs_box = QGroupBox("Observações")
        obs_lay = QVBoxLayout(obs_box)
        self._observacoes_edit = QPlainTextEdit()
        self._observacoes_edit.setFixedHeight(90)
        self._observacoes_edit.textChanged.connect(self._on_observacoes_changed)
        obs_lay.addWidget(self._observacoes_edit)
        bottom.addWidget(obs_box, stretch=1)

        content.addLayout(bottom)

    @staticmethod
    def _make_radio(text: str, value: str, on_change: Any) -> QRadioButton:
        """
        Cria um QRadioButton desselecionável (autoExclusive False).

        Args:
            text: Texto do radio
            value: Valor associado
            on_change: Handler (recebe o value)

        Returns:
            QRadioButton configurado
        """
        rb = QRadioButton(text)
        rb.setAutoExclusive(False)
        rb.setProperty("value", value)
        rb.clicked.connect(lambda _checked=False, v=value: on_change(v))
        return rb

    # ========== Handlers de Tipo / Tipo Receita ==========

    def _on_tipo_clicked(self, value: str) -> None:
        """Toggle do grupo Tipo (clicar no ativo desliga)."""
        if self._last_tipo == value:
            self._uncheck_all(self._tipo_radios)
            self._last_tipo = ""
        else:
            self._uncheck_all_except(self._tipo_radios, value)
            self._last_tipo = value
        self.app.dirty_tracker.mark_dirty(
            ("options", "tipo"), new_value=self._last_tipo
        )
        self.app.state_manager.notify_tipo_changed(self._last_tipo)

    def _on_tipo_receita_clicked(self, value: str) -> None:
        """Toggle do grupo Tipo de Receita; afeta apenas validade."""
        if self._last_tipo_receita == value:
            self._uncheck_all(self._tipo_receita_radios)
            self._last_tipo_receita = ""
            new_value = ""
        else:
            self._uncheck_all_except(self._tipo_receita_radios, value)
            self._last_tipo_receita = value
            new_value = value
        self.app.state_manager.update_date_field(
            "tipo_receita", new_value, calculation_mode="validade_only"
        )
        self.app.dirty_tracker.mark_dirty(
            ("options", "tipo_receita"), new_value=new_value
        )

    # ========== Handlers de campos ==========

    def _on_periodicidade_changed(self) -> None:
        """Periodicidade mudou → afeta próxima retirada (com distribuição)."""
        if self._periodicidade_edit is None:
            return
        self.app.state_manager.update_date_field(
            "periodicidade",
            self._periodicidade_edit.text().strip(),
            calculation_mode="proxima_vez_only",
        )
        self.app.dirty_tracker.mark_dirty(
            ("options", "periodicidade"),
            new_value=self._periodicidade_edit.text().strip(),
        )

    def _on_ultima_receita_changed(self) -> None:
        """Última receita mudou → recalcula validade."""
        if self._ultima_receita_edit is None:
            return
        self.app.state_manager.update_date_field(
            "ultima_receita",
            self._ultima_receita_edit.text().strip(),
            calculation_mode="validade_only",
        )
        self.app.dirty_tracker.mark_dirty(
            ("options", "ultima_receita"),
            new_value=self._ultima_receita_edit.text().strip(),
        )

    def _on_observacoes_changed(self) -> None:
        """Observações mudou."""
        if self._observacoes_edit is None:
            return
        self.app.dirty_tracker.mark_dirty(
            ("options", "observacoes"),
            new_value=self._observacoes_edit.toPlainText(),
        )

    # ========== Setters públicos ==========

    def set_municipal_e_revezado_enabled(self, enabled: bool) -> None:
        """
        Habilita/desabilita a opção Municipal e Revezado.

        Args:
            enabled: True se há 2+ processos
        """
        if self._radio_municipal_e_revezado is not None:
            self._radio_municipal_e_revezado.setEnabled(enabled)

    def set_tipo_values(self, tipo: str, tipo_receita: str) -> None:
        """
        Define valores de tipo e tipo_receita (sem marcar dirty).

        Args:
            tipo: Valor do tipo (ou "")
            tipo_receita: Valor do tipo_receita (ou "")
        """
        self._select_radio(self._tipo_radios, tipo)
        self._last_tipo = tipo
        self._select_radio(self._tipo_receita_radios, tipo_receita)
        self._last_tipo_receita = tipo_receita

    # ========== Getters ==========

    def get_tipo(self) -> str:
        """Retorna o tipo selecionado."""
        return self._last_tipo

    def get_tipo_receita(self) -> str:
        """Retorna o tipo de receita selecionado."""
        return self._last_tipo_receita

    def get_periodicidade(self) -> str:
        """Retorna a periodicidade digitada."""
        if self._periodicidade_edit is None:
            return ""
        return self._periodicidade_edit.text().strip()

    def get_ultima_receita(self) -> str:
        """Retorna a última receita (vazio se em branco)."""
        if self._ultima_receita_edit is None:
            return ""
        return self._ultima_receita_edit.text().strip()

    def get_atendido_por(self) -> str:
        """Retorna o campo atendido por."""
        if self._atendido_por_edit is None:
            return ""
        return self._atendido_por_edit.text().strip()

    def get_observacoes(self) -> str:
        """Retorna o conteúdo das observações."""
        if self._observacoes_edit is None:
            return ""
        return self._observacoes_edit.toPlainText().strip()

    def get_options_data(self) -> dict[str, str]:
        """
        Extrai todos os valores como dicionário (sempre inclui as chaves,
        mesmo em branco) — fonte não-perdida para validação e PDF.

        Returns:
            Dicionário com tipo/periodicidade/ultima_receita/tipo_receita/
            observacoes/atendido_por
        """
        return {
            "tipo": self.get_tipo(),
            "periodicidade": self.get_periodicidade(),
            "ultima_receita": self.get_ultima_receita(),
            "tipo_receita": self.get_tipo_receita(),
            "observacoes": self.get_observacoes(),
            "atendido_por": self.get_atendido_por(),
        }

    def clear_fields(self) -> None:
        """Limpa todos os campos de opções."""
        self._uncheck_all(self._tipo_radios)
        self._last_tipo = ""
        self._uncheck_all(self._tipo_receita_radios)
        self._last_tipo_receita = ""
        if self._periodicidade_edit is not None:
            self._periodicidade_edit.clear()
        if self._ultima_receita_edit is not None:
            self._ultima_receita_edit.clear()
        if self._atendido_por_edit is not None:
            self._atendido_por_edit.clear()
        if self._observacoes_edit is not None:
            self._observacoes_edit.clear()
        for field in ("periodicidade", "ultima_receita", "tipo_receita"):
            self.app.state_manager.update_date_field(field, "")

    # ========== StateObserver ==========

    def on_state_changed(self, event: StateEvent) -> None:
        """Reage a mudanças de estado do StateManager."""
        try:
            if event.event_type == StateEventType.PATIENT_SELECTED:
                self._load_from_patient(event.data.get("patient", {}))
            elif event.event_type == StateEventType.PATIENT_CLEARED:
                self.clear_fields()
            elif event.event_type == StateEventType.PATIENT_UPDATED:
                updates = event.data.get("updates", {})
                if "tipo" in updates or "tipo_receita" in updates:
                    self.set_tipo_values(
                        updates.get("tipo", ""), updates.get("tipo_receita", "")
                    )
                if "periodicidade" in updates:
                    self._set_edit_text(
                        self._periodicidade_edit, updates.get("periodicidade", "")
                    )
                if "ultima_receita" in updates:
                    self._set_edit_text(
                        self._ultima_receita_edit, updates.get("ultima_receita", "")
                    )
                if "observacoes" in updates:
                    if self._observacoes_edit is not None:
                        self._observacoes_edit.blockSignals(True)
                        self._observacoes_edit.setPlainText(
                            updates.get("observacoes", "")
                        )
                        self._observacoes_edit.blockSignals(False)
            elif event.event_type == StateEventType.PROCESSO_COUNT_CHANGED:
                count = event.data.get("count", 0)
                self.set_municipal_e_revezado_enabled(count >= 2)
        except Exception as e:
            self._handle_state_change_error(e, self.__class__.__name__)

    # ========== Helpers ==========

    def _load_from_patient(self, patient_data: Any) -> None:
        """Carrega campos a partir dos dados do paciente (sem marcar dirty)."""
        tipo = get_field_str(patient_data, "tipo")
        tipo_receita = get_field_str(patient_data, "tipo_receita")
        self.set_tipo_values(tipo, tipo_receita)

        self._set_edit_text(
            self._periodicidade_edit, get_field_str(patient_data, "periodicidade")
        )
        self._set_edit_text(
            self._ultima_receita_edit, get_field_str(patient_data, "ultima_receita")
        )
        self._set_edit_text(
            self._atendido_por_edit, get_field_str(patient_data, "atendido_por")
        )

        if self._observacoes_edit is not None:
            self._observacoes_edit.blockSignals(True)
            self._observacoes_edit.setPlainText(
                get_field_str(patient_data, "observacoes")
            )
            self._observacoes_edit.blockSignals(False)

        # Registra valores originais para detectar mudança real
        tracker = self.app.dirty_tracker
        tracker.set_original(("options", "tipo"), tipo)
        tracker.set_original(("options", "tipo_receita"), tipo_receita)
        tracker.set_original(
            ("options", "periodicidade"),
            get_field_str(patient_data, "periodicidade"),
        )
        tracker.set_original(
            ("options", "ultima_receita"),
            get_field_str(patient_data, "ultima_receita"),
        )
        tracker.set_original(
            ("options", "atendido_por"),
            get_field_str(patient_data, "atendido_por"),
        )
        tracker.set_original(
            ("options", "observacoes"),
            get_field_str(patient_data, "observacoes"),
        )

    @staticmethod
    def _set_edit_text(edit: QLineEdit | None, text: str) -> None:
        """Define texto de um QLineEdit sem disparar handlers (blockSignals)."""
        if edit is None:
            return
        edit.blockSignals(True)
        edit.setText(text)
        edit.blockSignals(False)

    @staticmethod
    def _select_radio(radios: dict[str, QRadioButton], value: str) -> None:
        """Seleciona o radio com o valor dado; desliga os demais."""
        for v, rb in radios.items():
            rb.setChecked(v == value)

    @staticmethod
    def _uncheck_all(radios: dict[str, QRadioButton]) -> None:
        """Desmarca todos os radios do grupo."""
        for rb in radios.values():
            rb.setChecked(False)

    @staticmethod
    def _uncheck_all_except(radios: dict[str, QRadioButton], value: str) -> None:
        """Marca só o radio do valor dado; desliga os demais."""
        for v, rb in radios.items():
            rb.setChecked(v == value)


