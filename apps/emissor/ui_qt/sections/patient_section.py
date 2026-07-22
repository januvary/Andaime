#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PatientSection — dados do paciente (Qt).

Form layout com: Nome (readonly, editável em modo novo paciente),
Matrícula, Telefone (máscara), Processo Nº (múltiplas instâncias com
+/-), Profissional (autocomplete via SearchableComboBox, que também
preenche o CRM) e CRM (máscara).

StateObserver: PATIENT_SELECTED carrega os campos, PATIENT_CLEARED limpa
e habilita edição do Nome, PATIENT_UPDATED atualiza campos específicos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from andaime.widgets import SearchableComboBox, static_search_fn

from emissor.state.state_events import StateEvent, StateEventType
from emissor.ui_qt.base import QtSection
from emissor.ui_qt.theme import make_button
from emissor.utils.field_utils import get_field_str

# Placeholders dos campos formatados (mesmo estilo do campo última receita)
_TELEFONE_PLACEHOLDER = "(00) 00000-0000"
_PROCESSO_PLACEHOLDER = "0000000-00.0000.0.00.0000"
_CRM_PLACEHOLDER = "00000000"


class PatientSection(QtSection):
    """Painel de dados do paciente."""

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        """
        Inicializa a seção de paciente.

        Args:
            parent: Widget pai
            app: Referência à aplicação principal (QtApp)
        """
        super().__init__(parent, app)

        self._nome_edit: QLineEdit | None = None
        self._matricula_edit: QLineEdit | None = None
        self._telefone_edit: QLineEdit | None = None
        self._profissional_combo: SearchableComboBox | None = None
        self._crm_combo: SearchableComboBox | None = None
        self._selected_profissional_id: int | None = None
        self._syncing_combos: bool = False

        # Cache de profissionais para autocomplete local (carregado uma vez).
        self._prof_options: dict[str, str] = {}
        self._crm_options: dict[str, str] = {}

        # Processo dinâmico (paralelo: widgets de linha + line edits)
        self._processo_rows: list[QWidget] = []
        self._processo_edits: list[QLineEdit] = []
        self._processo_container: QWidget | None = None
        self._processo_label: Any = None
        self._stashed_processos: list[str] = []

        self._name_id_editable = False

        self._build_ui()

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói o formulário de paciente."""
        content = self.content_layout()
        content.setContentsMargins(0, 0, 0, 0)

        # Área rolável: quando o conteúdo (ex.: vários processos) excede a
        # altura da seção, aparece scrollbar vertical em vez de expandir.
        # Fundo transparente por objectName para preservar o input_bg dos campos.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        viewport = scroll.viewport()
        viewport.setObjectName("patient_viewport")
        viewport.setStyleSheet("QWidget#patient_viewport { background: transparent; }")
        inner = QWidget()
        inner.setObjectName("patient_inner")
        inner.setStyleSheet("QWidget#patient_inner { background: transparent; }")
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(12, 12, 12, 12)

        form = QFormLayout()
        form.setSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)

        # Nome (readonly por padrão)
        self._nome_edit = QLineEdit()
        self._nome_edit.setReadOnly(True)
        self._nome_edit.textChanged.connect(
            lambda _t="": self.app.refresh_dirty_state()
        )
        form.addRow("Nome:", self._nome_edit)

        # Matrícula
        self._matricula_edit = QLineEdit()
        self._matricula_edit.textChanged.connect(
            lambda _t="": self.app.refresh_dirty_state()
        )
        form.addRow("Matrícula:", self._matricula_edit)

        # Telefone (placeholder + auto-formata)
        self._telefone_edit = QLineEdit()
        self._telefone_edit.setPlaceholderText(_TELEFONE_PLACEHOLDER)
        self._telefone_edit.textChanged.connect(self._on_telefone_changed)
        form.addRow("Telefone:", self._telefone_edit)

        # Processo Nº (container dinâmico)
        processo_container = QWidget()
        self._processo_layout = QVBoxLayout(processo_container)
        self._processo_layout.setContentsMargins(0, 0, 0, 0)
        self._processo_layout.setSpacing(4)
        self._add_processo_row()  # primeira linha (com botão "+")
        form.addRow("Processo Nº:", processo_container)
        self._processo_container = processo_container
        self._processo_label = form.labelForField(processo_container)

        # Profissional (autocomplete por nome, cache local em memória)
        self._profissional_combo = SearchableComboBox(
            search_fn=static_search_fn(self._prof_options),
            placeholder="Nome do profissional...",
            parent=self,
        )
        self._profissional_combo.selection_changed.connect(self._on_profissional_key)
        self._profissional_combo.text_edited.connect(
            lambda _t="": self.app.refresh_dirty_state()
        )
        form.addRow("Profissional:", self._profissional_combo)

        # CRM (combo de busca espelhado, pesquisa por CRM em vez de nome)
        self._crm_combo = SearchableComboBox(
            search_fn=static_search_fn(self._crm_options),
            placeholder="CRM do profissional...",
            parent=self,
        )
        self._crm_combo.selection_changed.connect(self._on_profissional_key)
        self._crm_combo.text_edited.connect(
            lambda _t="": self.app.refresh_dirty_state()
        )
        form.addRow("CRM:", self._crm_combo)

        inner_layout.addLayout(form)
        inner_layout.addStretch()
        scroll.setWidget(inner)
        content.addWidget(scroll)

        self._load_profissionais()

    # ========== Profissionais (autocomplete local) ==========

    def _load_profissionais(self) -> None:
        """Carrega todos os profissionais para autocomplete local (cache)."""
        try:
            rows = self.app.db.get_all_profissionais()
        except Exception as e:
            from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

            ErrorHandler.log(
                f"Erro ao carregar profissionais: {e}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.DATABASE,
            )
            rows = []

        self._prof_options = {}
        self._crm_options = {}
        for r in rows:
            pid = str(r.get("id", ""))
            nome = r.get("nome", "")
            crm = r.get("crm", "") or ""
            if not pid or not nome:
                continue
            self._prof_options[pid] = nome
            self._crm_options[pid] = crm

        if self._profissional_combo is not None:
            self._profissional_combo.set_search_fn(static_search_fn(self._prof_options))
        if self._crm_combo is not None:
            self._crm_combo.set_search_fn(static_search_fn(self._crm_options))

    def _refresh_profissional_options(self) -> None:
        """Recarrega profissionais e atualiza as opções dos combos."""
        self._load_profissionais()

    # ========== Processo dinâmico ==========

    def _add_processo_row(self) -> QLineEdit:
        """
        Adiciona uma linha de processo (com botão remover, exceto a primeira).

        Returns:
            O QLineEdit da nova linha
        """
        row_widget = QWidget()
        row_lay = QHBoxLayout(row_widget)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(4)

        edit = QLineEdit()
        edit.setPlaceholderText(_PROCESSO_PLACEHOLDER)
        edit.textChanged.connect(lambda _t="", e=edit: self._on_processo_changed(e))
        row_lay.addWidget(edit)

        # Primeira linha: botão "+"; linhas adicionais: botão "−"
        if not self._processo_edits:
            add = make_button("+", "icon", row_widget)
            add.setFixedSize(24, 24)
            add.clicked.connect(self._on_add_processo_clicked)
            row_lay.addWidget(add)
        else:
            rm = make_button("\u2212", "icon", row_widget)
            rm.setFixedSize(24, 24)
            rm.clicked.connect(
                lambda _=False, w=row_widget: self._on_remove_processo(w)
            )
            row_lay.addWidget(rm)

        self._processo_edits.append(edit)
        self._processo_rows.append(row_widget)
        self._processo_layout.addWidget(row_widget)
        return edit

    def _on_add_processo_clicked(self) -> None:
        """Handler do botão Adicionar processo."""
        self._add_processo_row()
        self._notify_processo_count()
        self.app.refresh_dirty_state()

    def _on_remove_processo(self, row_widget: QWidget) -> None:
        """Remove uma linha de processo."""
        try:
            idx = self._processo_rows.index(row_widget)
        except ValueError:
            return
        self._processo_rows.pop(idx)
        self._processo_edits.pop(idx)
        self._processo_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        self._notify_processo_count()
        self.app.refresh_dirty_state()

    def _on_processo_changed(self, edit: QLineEdit) -> None:
        """Auto-formata o campo processo e recomputa o estado dirty."""
        self._format_field(edit, self._format_processo)
        self.app.refresh_dirty_state()

    def _on_telefone_changed(self) -> None:
        """Auto-formata o telefone e recomputa o estado dirty."""
        if self._telefone_edit is not None:
            self._format_field(self._telefone_edit, self._format_telefone)
        self.app.refresh_dirty_state()

    def _format_field(self, edit: QLineEdit | None, formatter: Any) -> None:
        """
        Aplica auto-formatação ao edit (setText com cursor no fim).

        Args:
            edit: QLineEdit a formatar
            formatter: Função str -> str
        """
        if edit is None:
            return
        raw = edit.text()
        formatted = formatter(raw)
        if formatted != raw:
            edit.blockSignals(True)
            edit.setText(formatted)
            edit.setCursorPosition(len(formatted))
            edit.blockSignals(False)

    @staticmethod
    def _format_telefone(text: str) -> str:
        """Formata entrada para (DD) DDDDD-DDDD."""
        digits = "".join(c for c in text if c.isdigit())[:11]
        if len(digits) <= 2:
            return digits
        if len(digits) <= 7:
            return f"({digits[:2]}) {digits[2:]}"
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"

    @staticmethod
    def _format_processo(text: str) -> str:
        """Formata entrada para XXXXXXX-XX.XXXX.X.XX.XXXX."""
        digits = "".join(c for c in text if c.isdigit())[:20]
        sizes = [7, 2, 4, 1, 2, 4]
        seps = ["", "-", ".", ".", ".", "."]
        result = ""
        pos = 0
        for i, size in enumerate(sizes):
            group = digits[pos : pos + size]
            if not group:
                break
            result += seps[i] + group
            pos += size
        return result

    @staticmethod
    def _format_crm(text: str) -> str:
        """Limita o CRM a 8 dígitos."""
        return "".join(c for c in text if c.isdigit())[:8]

    def _clear_processo_rows(self) -> None:
        """Remove linhas extras e limpa a primeira."""
        while len(self._processo_edits) > 1:
            self._on_remove_processo(self._processo_rows[-1])
        if self._processo_edits:
            self._processo_edits[0].blockSignals(True)
            self._processo_edits[0].clear()
            self._processo_edits[0].blockSignals(False)

    def _notify_processo_count(self) -> None:
        """Notifica o StateManager sobre a contagem de processos."""
        self.app.state_manager.notify_processo_count_changed(
            count=len(self._processo_edits)
        )

    def _set_processo_visible(self, visible: bool) -> None:
        """Mostra/esconde o campo Processo Nº (oculto para tipo insulina).

        Ao ocultar, os valores são preservados em memória e restaurados
        caso o tipo insulina seja desmarcado.
        """
        if self._processo_container is not None:
            self._processo_container.setVisible(visible)
        if self._processo_label is not None:
            self._processo_label.setVisible(visible)
        if visible:
            # Restaura valores previamente ocultados (se houver) — só quando
            # não há valores carregados (ex.: toggle de tipo, não carregamento
            # de paciente que já preenche as linhas via _load_processos).
            if not any(edit.text() for edit in self._processo_edits):
                values = self._stashed_processos
                self._stashed_processos = []
                self._clear_processo_rows()
                for i, val in enumerate(values):
                    edit = (
                        self._processo_edits[0] if i == 0 else self._add_processo_row()
                    )
                    if val:
                        edit.setText(val)
                self._notify_processo_count()
        else:
            # Guarda os valores atuais antes de ocultar e esvazia as linhas
            # (o widget fica limpo enquanto invisível).
            self._stashed_processos = [edit.text() for edit in self._processo_edits]
            self._clear_processo_rows()

    # ========== Profissional autocomplete ==========

    def _on_profissional_key(self, key: object) -> None:
        """Trata seleção nos combos de profissional/CRM (ambos apontam para a
        mesma linha mestre): carrega a linha e sincroniza os campos. ``None``
        indica texto digitado divergente da seleção — invalida o id."""
        if key is None:
            self._selected_profissional_id = None
            self.app.refresh_dirty_state()
            return
        if not isinstance(key, str):
            return
        try:
            prof_id = int(key)
        except (ValueError, TypeError):
            return
        row = self.app.db.get_profissional(prof_id)
        if row is not None:
            self._select_profissional(row)

    def _select_profissional(self, row: dict) -> None:
        """Seleciona um profissional a partir de uma linha mestre, preenchendo
        nome e CRM e registrando o id. Evita loop entre os dois combos."""
        prof_id = row.get("id")
        if prof_id is None:
            return
        self._selected_profissional_id = int(prof_id)
        if self._syncing_combos:
            return
        self._syncing_combos = True
        try:
            if self._profissional_combo is not None:
                self._profissional_combo.set_text(row.get("nome", ""))
            if self._crm_combo is not None:
                self._crm_combo.set_text(row.get("crm", "") or "")
        finally:
            self._syncing_combos = False
        self.app.refresh_dirty_state()

    # ========== Setters públicos ==========

    def set_name_id_editable(self, editable: bool) -> None:
        """
        Habilita/desabilita a edição do campo Nome.

        Args:
            editable: True para modo novo paciente (Nome editável)
        """
        self._name_id_editable = editable
        if self._nome_edit is not None:
            self._nome_edit.setReadOnly(not editable)

    # ========== Carregamento / limpeza ==========

    def populate_patient_fields(self, patient_data: Any) -> None:
        """
        Preenche todos os campos a partir dos dados do paciente.

        Args:
            patient_data: Patient (dataclass/Mapping) com dados do banco
        """
        self.clear_patient_fields()
        self.set_name_id_editable(False)

        self._set_text(self._nome_edit, get_field_str(patient_data, "nome"))
        self._set_text(self._matricula_edit, get_field_str(patient_data, "matricula"))
        self._set_text(self._telefone_edit, get_field_str(patient_data, "telefone"))
        self._set_profissional(get_field_str(patient_data, "profissional_nome"))
        self._set_crm(get_field_str(patient_data, "profissional_crm"))
        self._selected_profissional_id = self._field_to_int(
            patient_data, "profissional_id"
        )
        self._load_processos(patient_data)
        self._set_processo_visible(get_field_str(patient_data, "tipo") != "insulina")

    def clear_patient_fields(self) -> None:
        """Limpa todos os campos e habilita edição do Nome."""
        for edit in (
            self._nome_edit,
            self._matricula_edit,
            self._telefone_edit,
        ):
            if edit is not None:
                edit.blockSignals(True)
                edit.clear()
                edit.blockSignals(False)
        self._clear_processo_rows()
        self._stashed_processos = []
        self._selected_profissional_id = None
        if self._profissional_combo is not None:
            self._profissional_combo.clear()
        if self._crm_combo is not None:
            self._crm_combo.clear()
        self.set_name_id_editable(True)
        self._set_processo_visible(True)
        self._notify_processo_count()

    def _load_processos(self, patient_data: Any) -> None:
        """Carrega os processos do paciente (principal + adicionais)."""
        self._clear_processo_rows()
        p1 = get_field_str(patient_data, "processo_n")
        if p1 and self._processo_edits:
            self._set_text(self._processo_edits[0], p1)

        count = self._patient_processo_count(patient_data)
        for i in range(2, count + 1):
            edit = self._add_processo_row()
            val = self._patient_get_processo(patient_data, i)
            if val:
                self._set_text(edit, val)
        self._notify_processo_count()

    # ========== Getters ==========

    def get_patient_data(self) -> dict[str, str]:
        """
        Extrai os valores atuais como dicionário.

        Returns:
            Dicionário com campos não-vazios (processos como
            processo_n, processo_2_n, ...)
        """
        data: dict[str, str] = {}

        for key, edit in (
            ("nome", self._nome_edit),
            ("matricula", self._matricula_edit),
            ("telefone", self._telefone_edit),
        ):
            value = self._clean(edit)
            if value:
                data[key] = value

        for i, edit in enumerate(self._processo_edits):
            if (
                self._processo_container is not None
                and self._processo_container.isHidden()
            ):
                break
            value = self._clean(edit)
            if value:
                key = "processo_n" if i == 0 else f"processo_{i + 1}_n"
                data[key] = value

        if self._profissional_combo is not None:
            prof = self._profissional_combo.current_text().strip()
            if prof:
                data["profissional_nome"] = prof
                data["profissional_id"] = self._selected_profissional_id
            elif self._selected_profissional_id is not None:
                data["profissional_id"] = None

        if self._crm_combo is not None:
            crm = self._crm_combo.current_text().strip()
            if crm:
                data["profissional_crm"] = crm

        return data

    def get_all_processos(self) -> list[str]:
        """
        Retorna todos os processos preenchidos.

        Returns:
            Lista de strings com números de processo
        """
        if self._processo_container is not None and self._processo_container.isHidden():
            return []
        return [self._clean(edit) for edit in self._processo_edits if self._clean(edit)]

    # ========== StateObserver ==========

    def on_state_changed(self, event: StateEvent) -> None:
        """Reage a mudanças de estado do StateManager."""
        try:
            if event.event_type == StateEventType.PATIENT_SELECTED:
                self._refresh_profissional_options()
                self.populate_patient_fields(event.data.get("patient", {}))
            elif event.event_type == StateEventType.PATIENT_CLEARED:
                self._refresh_profissional_options()
                self.clear_patient_fields()
            elif event.event_type == StateEventType.TIPO_CHANGED:
                self._set_processo_visible(event.data.get("tipo") != "insulina")
            elif event.event_type == StateEventType.PATIENT_UPDATED:
                self._refresh_profissional_options()
                for field, value in event.data.get("updates", {}).items():
                    self._apply_update(field, str(value))
        except Exception as e:
            self._handle_state_change_error(e, self.__class__.__name__)

    # ========== Helpers ==========

    def _apply_update(self, field: str, value: str) -> None:
        """Aplica atualização de um campo específico (PATIENT_UPDATED)."""
        if field == "crm":
            self._set_crm(value)
        elif field == "profissional":
            self._set_profissional(value)
        elif field == "processo_n" and self._processo_edits:
            self._processo_edits[0].setText(value)
        elif field.startswith("processo_") and field.endswith("_n"):
            # processo_X_n → índice X
            try:
                idx = int(field.split("_")[1]) - 1
            except (IndexError, ValueError):
                return
            while len(self._processo_edits) <= idx:
                self._add_processo_row()
            self._processo_edits[idx].setText(value)

    def _set_profissional(self, name: str) -> None:
        """Define o texto do campo profissional."""
        if self._profissional_combo is None:
            return
        self._profissional_combo.set_text(name)

    def _set_crm(self, crm: str) -> None:
        """Define o texto do campo CRM (combo espelhado)."""
        if self._crm_combo is None:
            return
        self._crm_combo.set_text(crm)

    @staticmethod
    def _set_text(edit: QLineEdit | None, value: str) -> None:
        """Define texto de um QLineEdit sem disparar handlers."""
        if edit is None:
            return
        edit.blockSignals(True)
        edit.setText(value)
        edit.blockSignals(False)

    @staticmethod
    def _clean(edit: QLineEdit | None) -> str:
        """Retorna o valor do edit ("" se vazio/só máscara)."""
        if edit is None:
            return ""
        text = edit.text()
        return text.strip() if any(c.isalnum() for c in text) else ""

    @staticmethod
    @staticmethod
    def _field_to_int(patient_data: Any, key: str) -> int | None:
        """Extrai campo inteiro opcional de patient_data."""
        raw = get_field_str(patient_data, key)
        if not raw:
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _patient_processo_count(patient_data: Any) -> int:
        """Conta os processos do paciente via método ou campos."""
        fn = getattr(patient_data, "processo_count", None)
        if callable(fn):
            try:
                return int(fn())
            except Exception:
                pass
        return 1 if get_field_str(patient_data, "processo_n") else 0

    @staticmethod
    def _patient_get_processo(patient_data: Any, index: int) -> str:
        """Retorna o processo de índice (1-based) do paciente."""
        fn = getattr(patient_data, "get_processo", None)
        if callable(fn):
            try:
                return str(fn(index))
            except Exception:
                pass
        return get_field_str(patient_data, f"processo_{index}_n")
