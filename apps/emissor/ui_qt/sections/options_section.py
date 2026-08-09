#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OptionsSection — seção de opções (Qt).

Espelha OptionsSectionV3 (CTk): Tipo, Periodicidade, Última receita,
Atendido por, Tipo de Receita e Observações. É um StateObserver que reage
a PATIENT_SELECTED/CLEARED/UPDATED e PROCESSO_COUNT_CHANGED.

Radios são desselecionáveis (clicar no ativo desliga o grupo). O grid de
receitas (data + validade/tipo + vencimento automático) e a periodicidade
alimentam o cálculo de datas via state_manager — logo, editá-los aqui
recalcula a DatesSection em tempo real.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QStyle,
    QStyleOptionComboBox,
    QStyleOptionViewItem,
    QStylePainter,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from emissor.state.state_events import StateEvent, StateEventType
from emissor.ui_qt.base import QtSection
from emissor.utils.field_utils import get_field_str
from emissor.utils.date_utils import TIPO_RECEITA_INFO, DateCalculator
from emissor.ui_qt.theme import make_button
from andaime.widgets import DateLineEdit

# Larguras de campos (espelham constantes da app CTk)
_PERIODICIDADE_WIDTH = 50
_ULTIMA_RECEITA_WIDTH = 65
_MAX_RECEITAS = 3
_RECEITA_DATA_WIDTH = 105


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

        self._tipo_combo: QComboBox | None = None
        self._tipo_model: QStandardItemModel | None = None
        self._last_tipo: str = ""

        self._periodicidade_edit: QLineEdit | None = None
        self._atendido_por_edit: QLineEdit | None = None
        self._observacoes_edit: QPlainTextEdit | None = None
        self._bloquear_balanco_radio: QRadioButton | None = None
        self._bloquear_balanco_radio: QRadioButton | None = None
        self._bloquear_balanco_active: bool = False

        # Widget de receitas (até 3 linhas de data/tipo/vencimento)
        self._receitas_grid: QGridLayout | None = None
        self._receita_rows: list[dict[str, Any]] = []
        self._receitas_box: QWidget | None = None

        self._build_ui()

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói os campos de opções."""
        content = self.content_layout()
        content.setSpacing(10)
        content.setContentsMargins(15, 15, 12, 12)

        # === Periodicidade (esquerda) + Tipo (direita) ===
        tipo_row = QHBoxLayout()
        tipo_row.addWidget(QLabel("Periodicidade:"))
        self._periodicidade_edit = QLineEdit()
        self._periodicidade_edit.setPlaceholderText("30")
        self._periodicidade_edit.setFixedWidth(_PERIODICIDADE_WIDTH)
        self._periodicidade_edit.setValidator(QIntValidator(1, 999))
        self._periodicidade_edit.textChanged.connect(self._on_periodicidade_changed)
        tipo_row.addWidget(self._periodicidade_edit)
        tipo_row.addWidget(QLabel("dias"))
        tipo_row.addStretch()
        tipo_row.addWidget(QLabel("Tipo:"))
        self._tipo_combo = _make_centered_combo()
        self._tipo_model = QStandardItemModel(self._tipo_combo)
        self._tipo_combo.setModel(self._tipo_model)
        for label, value in (
            ("", ""),
            ("Revezado", "revezado"),
            ("Municipal", "municipal"),
            ("Municipal e Revezado", "municipal_e_revezado"),
            ("Insulina", "insulina"),
        ):
            item = QStandardItem(label)
            item.setData(value, Qt.ItemDataRole.UserRole)
            self._tipo_model.appendRow(item)
        self._tipo_combo.setFixedWidth(180)
        self._tipo_combo.currentIndexChanged.connect(self._on_tipo_changed)
        tipo_row.addWidget(self._tipo_combo)
        content.addLayout(tipo_row)
        content.addSpacing(8)

        # === Evitar dias de balanço + Atendido por (alinhado à direita) ===
        period_row = QHBoxLayout()
        period_row.addWidget(QLabel("Evitar dias de balanço:"))
        self._bloquear_balanco_radio = QRadioButton("")
        self._bloquear_balanco_radio.setAutoExclusive(False)
        self._bloquear_balanco_radio.setProperty("value", "bloquear_balanco")
        self._bloquear_balanco_radio.clicked.connect(
            self._on_bloquear_balanco_clicked
        )
        period_row.addWidget(self._bloquear_balanco_radio)
        period_row.addStretch()
        atend_col = QVBoxLayout()
        atend_col.setContentsMargins(0, 0, 0, 0)
        self._atendido_por_edit = QLineEdit()
        self._atendido_por_edit.setPlaceholderText("Atendido por...")
        atend_col.addWidget(self._atendido_por_edit)
        period_row.addLayout(atend_col)
        content.addLayout(period_row)

        # === Receitas + Observações (mesma linha) ===
        rec_atend_obs = QHBoxLayout()
        rec_atend_obs.setSpacing(8)
        rec_atend_obs.addWidget(self._build_receitas_widget())
        obs_box = QGroupBox()
        obs_lay = QVBoxLayout(obs_box)
        self._observacoes_edit = QPlainTextEdit()
        self._observacoes_edit.setFixedHeight(90)
        self._observacoes_edit.setPlaceholderText("Observações...")
        self._observacoes_edit.textChanged.connect(self._on_observacoes_changed)
        obs_lay.addWidget(self._observacoes_edit)
        rec_atend_obs.addWidget(obs_box, 1)
        content.addLayout(rec_atend_obs)

    def _build_receitas_widget(self) -> QWidget:
        """Constrói o grid de receitas (data/tipo/vencimento + add/remove).

        Colunas: Data da receita | Validade da receita | Data de vencimento
        | (+/-). Rows são compactas (1..3) e o vencimento é automático.
        """
        box = QGroupBox()
        self._receitas_box = box
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._receitas_grid = grid

        headers = (
            "Data da receita",
            "Validade",
            "Vencimento",
            "",
        )
        for col, text in enumerate(headers):
            if text:
                header = QLabel(text)
                header.setProperty("class", "dim")
                grid.addWidget(header, 0, col)

        # Primeira linha com botão "+" (mesmo padrão do Processo N).
        self._add_receita_row()
        return box

    def _add_receita_row(self, data: str = "", tipo: str = "") -> None:
        """Adiciona uma linha de receita (se houver espaço)."""
        if self._receitas_grid is None:
            return
        if len(self._receita_rows) >= _MAX_RECEITAS:
            return

        row = len(self._receita_rows) + 1

        date_edit = DateLineEdit()
        date_edit.setFixedWidth(_RECEITA_DATA_WIDTH)
        date_edit.setText(data)

        tipo_combo = _make_centered_combo()
        tipo_combo.addItem("")
        for value, info in TIPO_RECEITA_INFO.items():
            tipo_combo.addItem(info["label"], userData=value)
        if tipo in TIPO_RECEITA_INFO:
            tipo_combo.setCurrentIndex(tipo_combo.findData(tipo))
        tipo_combo.setFixedWidth(_ULTIMA_RECEITA_WIDTH)

        venc_label = QLabel("—")

        # Botão "+" na primeira linha; "−" nas demais.
        if len(self._receita_rows) == 0:
            button = make_button("+", "icon", self._receitas_box)
        else:
            button = make_button("\u2212", "icon", self._receitas_box)
        button.setFixedSize(24, 24)

        entry = {
            "date": date_edit,
            "tipo": tipo_combo,
            "venc": venc_label,
            "button": button,
        }
        self._receita_rows.append(entry)

        if len(self._receita_rows) == 1:
            button.clicked.connect(self._on_add_receita_clicked)
        else:
            button.clicked.connect(
                lambda _=False, e=entry: self._on_remove_receita_clicked(e)
            )

        date_edit.textChanged.connect(self._on_receita_changed)
        tipo_combo.currentIndexChanged.connect(self._on_receita_changed)

        self._receitas_grid.addWidget(date_edit, row, 0)
        self._receitas_grid.addWidget(tipo_combo, row, 1)
        self._receitas_grid.addWidget(venc_label, row, 2)
        self._receitas_grid.addWidget(button, row, 3)

        self._update_vencimento(entry)

    def _remove_receita_row(self, entry: dict[str, Any]) -> None:
        """Remove uma linha de receita e compacta (shift up)."""
        if self._receitas_grid is None:
            return
        if len(self._receita_rows) <= 1:
            return

        try:
            idx = self._receita_rows.index(entry)
        except ValueError:
            return

        # Capturar valores restantes e reconstruir compacto (1..3).
        remaining = [
            {"data": e["date"].text().strip(), "tipo": e["tipo"].currentData() or ""}
            for i, e in enumerate(self._receita_rows)
            if i != idx
        ]
        self._clear_receitas()
        for entry in remaining:
            self._add_receita_row(entry["data"], entry.get("tipo", ""))
        self._on_receita_changed()

    def _on_add_receita_clicked(self) -> None:
        """Handler do botão adicionar receita."""
        if len(self._receita_rows) >= _MAX_RECEITAS:
            return
        self._add_receita_row()
        self._on_receita_changed()

    def _on_remove_receita_clicked(self, entry: dict[str, Any]) -> None:
        """Handler do botão remover receita."""
        self._remove_receita_row(entry)

    def _on_receita_changed(self, *_args: Any) -> None:
        """Qualquer mudança numa linha recalcula vencimentos e sincroniza."""
        for entry in self._receita_rows:
            self._update_vencimento(entry)
        self.app.state_manager.set_receitas(self.get_receitas())
        self.app.refresh_dirty_state()

    def _update_vencimento(self, entry: dict[str, Any]) -> None:
        """Atualiza o rótulo de vencimento da linha (data + tipo)."""
        data = entry["date"].text().strip()
        tipo = entry["tipo"].currentData() or ""
        if not data or not tipo:
            entry["venc"].setText("—")
            return
        resultado = DateCalculator.calculate_validade_receita(data, tipo)
        formatted = resultado.get("validade_receita_formatted", "-")
        entry["venc"].setText(formatted if formatted != "-" else "—")

    # ========== Handlers de Tipo ==========

    def _on_tipo_changed(self, *_args: Any) -> None:
        """Mudou o tipo selecionado no dropdown → notifica StateManager."""
        if self._tipo_combo is None:
            return
        value = self._tipo_combo.currentData() or ""
        self._last_tipo = value
        self.app.refresh_dirty_state()
        self.app.state_manager.notify_tipo_changed(self._last_tipo)

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
        self.app.refresh_dirty_state()

    def _on_bloquear_balanco_clicked(self) -> None:
        """Toggle do bloqueio de balanço (clicar no ativo desliga)."""
        if self._bloquear_balanco_radio is None:
            return
        self._bloquear_balanco_active = self._bloquear_balanco_radio.isChecked()
        self.app.state_manager.set_bloquear_balanco(self._bloquear_balanco_active)
        self.app.refresh_dirty_state()

    def _on_observacoes_changed(self) -> None:
        """Observações mudou."""
        if self._observacoes_edit is None:
            return
        self.app.refresh_dirty_state()

    # ========== Setters públicos ==========

    def set_municipal_e_revezado_enabled(self, enabled: bool) -> None:
        """
        Habilita/desabilita a opção Municipal e Revezado.

        Args:
            enabled: True se há 2+ processos
        """
        if self._tipo_model is not None:
            for row in range(self._tipo_model.rowCount()):
                item = self._tipo_model.item(row)
                if (
                    item is not None
                    and item.data(Qt.ItemDataRole.UserRole) == "municipal_e_revezado"
                ):
                    item.setEnabled(enabled)

    def set_tipo_values(self, tipo: str) -> None:
        """
        Define valor de tipo no dropdown (sem notificar/semas marcar dirty).

        Args:
            tipo: Valor do tipo (ou "")
        """
        if self._tipo_combo is None:
            return
        idx = self._tipo_combo.findData(tipo)
        if idx < 0:
            idx = 0
        self._tipo_combo.blockSignals(True)
        self._tipo_combo.setCurrentIndex(idx)
        self._tipo_combo.blockSignals(False)
        self._last_tipo = tipo

    # ========== Getters ==========

    def get_tipo(self) -> str:
        """Retorna o tipo selecionado."""
        return self._last_tipo

    def get_receitas(self) -> list[dict[str, str]]:
        """Retorna as receitas preenchidas (compactas, data + tipo)."""
        receitas = []
        for e in self._receita_rows:
            data = e["date"].text().strip()
            tipo = e["tipo"].currentData() or ""
            if data or tipo:
                receitas.append({"data": data, "tipo": tipo})
        return receitas

    def get_periodicidade(self) -> str:
        """Retorna a periodicidade digitada."""
        if self._periodicidade_edit is None:
            return ""
        return self._periodicidade_edit.text().strip()

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

    def get_bloquear_balanco(self) -> bool:
        """Retorna se o bloqueio de balanço está ativo."""
        return self._bloquear_balanco_active

    def get_options_data(self) -> dict[str, Any]:
        """
        Extrai todos os valores como dicionário (sempre inclui as chaves,
        mesmo em branco) — fonte não-perdida para validação e PDF.

        Returns:
            Dicionário com tipo/periodicidade/receita_*_data|_tipo/
            observacoes/atendido_por
        """
        receitas = self.get_receitas()
        options: dict[str, Any] = {
            "tipo": self.get_tipo(),
            "periodicidade": self.get_periodicidade(),
            "receitas": receitas,
            "observacoes": self.get_observacoes(),
            "atendido_por": self.get_atendido_por(),
            "bloquear_balanco": self.get_bloquear_balanco(),
        }
        # Colunas de persistência (1..3), sempre presentes p/ limpar no banco.
        for i in range(1, _MAX_RECEITAS + 1):
            entry = receitas[i - 1] if i <= len(receitas) else {}
            options[f"receita_{i}_data"] = entry.get("data", "")
            options[f"receita_{i}_tipo"] = entry.get("tipo", "")
        return options

    def clear_fields(self) -> None:
        """Limpa todos os campos de opções."""
        self.set_tipo_values("")
        self._load_receitas([])
        if self._periodicidade_edit is not None:
            self._periodicidade_edit.clear()
        if self._atendido_por_edit is not None:
            self._atendido_por_edit.clear()
        if self._observacoes_edit is not None:
            self._observacoes_edit.clear()
        if self._bloquear_balanco_radio is not None:
            self._bloquear_balanco_radio.setChecked(False)
        self._bloquear_balanco_active = False
        self.app.state_manager.set_bloquear_balanco(False)
        self.app.state_manager.set_receitas([])
        self.app.state_manager.update_date_field("periodicidade", "")

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
                if "tipo" in updates:
                    self.set_tipo_values(updates.get("tipo", ""))
                if "periodicidade" in updates:
                    self._set_edit_text(
                        self._periodicidade_edit, updates.get("periodicidade", "")
                    )
                if "receitas" in updates:
                    self._load_receitas(updates.get("receitas") or [])
                if "bloquear_balanco" in updates:
                    self._apply_bloquear_balanco(
                        bool(updates.get("bloquear_balanco", False))
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
        self.set_tipo_values(tipo)

        self._set_edit_text(
            self._periodicidade_edit, get_field_str(patient_data, "periodicidade")
        )
        if self._receitas_box is None:
            self._build_receitas_widget()
        receitas = []
        for i in range(1, _MAX_RECEITAS + 1):
            data = get_field_str(patient_data, f"receita_{i}_data")
            tipo = get_field_str(patient_data, f"receita_{i}_tipo")
            if data or tipo:
                receitas.append({"data": data, "tipo": tipo})
        self._load_receitas(receitas)
        bloquear = get_field_str(patient_data, "bloquear_balanco")
        self._apply_bloquear_balanco(
            bloquear.strip().lower() in ("1", "true", "on", "yes")
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

    def _load_receitas(self, receitas: list[dict[str, str]]) -> None:
        """Reconstrói as linhas de receita a partir de uma lista compacta."""
        self._clear_receitas()
        for r in receitas[: _MAX_RECEITAS]:
            self._add_receita_row(
                data=r.get("data", ""), tipo=r.get("tipo", "") or ""
            )
        if not self._receita_rows:
            self._add_receita_row()
        self._on_receita_changed()

    def _clear_receitas(self) -> None:
        """Remove todas as linhas de receita (grid fica vazio)."""
        if self._receitas_grid is None:
            return
        for entry in list(self._receita_rows):
            for widget in (entry["date"], entry["tipo"], entry["venc"], entry["button"]):
                self._receitas_grid.removeWidget(widget)
                widget.deleteLater()
        self._receita_rows.clear()

    @staticmethod
    def _set_edit_text(edit: QLineEdit | None, text: str) -> None:
        """Define texto de um QLineEdit sem disparar handlers (blockSignals)."""
        if edit is None:
            return
        edit.blockSignals(True)
        edit.setText(text)
        edit.blockSignals(False)

    def _apply_bloquear_balanco(self, active: bool) -> None:
        """Define o estado do toggle e sincroniza o StateManager."""
        if self._bloquear_balanco_radio is not None:
            self._bloquear_balanco_radio.setChecked(active)
        self._bloquear_balanco_active = active
        self.app.state_manager.set_bloquear_balanco(active)


class _CenteredCombo(QComboBox):
    """QComboBox não-editable com o texto do campo centralizado.

    Não usa line edit (que travaria o clique/popup); apenas pinta o texto
    do item atual centralizado mantendo o comportamento nativo do dropdown.
    """

    def paintEvent(self, event: Any) -> None:
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        if self.currentText():
            rect = self.rect().adjusted(4, 0, -26, 0)
            painter.drawItemText(
                rect,
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                self.palette(),
                self.isEnabled(),
                self.currentText(),
            )


class _CenteredItemDelegate(QStyledItemDelegate):
    """Delegate que centraliza os itens do dropdown (popup)."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: Any,
    ) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.displayAlignment = (
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        super().paint(painter, opt, index)


def _make_centered_combo() -> QComboBox:
    """Cria um QComboBox com o texto dos itens centralizado."""
    combo = _CenteredCombo()
    combo.setItemDelegate(_CenteredItemDelegate(combo))
    return combo
