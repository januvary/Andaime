#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ItemsSection — itens da receita (Qt).

Lista rolável de itens, cada um com: Descrição (autocomplete do catálogo),
Código (autocomplete), Unidade, Quantidade e Dias. Selecionar Descrição ou
Código preenche os demais campos do item (cross-fill a partir do catálogo).

StateObserver: PATIENT_SELECTED carrega os itens, PATIENT_CLEARED limpa.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from emissor.main_window import QtApp

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from andaime.widgets import SearchableComboBox, static_search_fn

from emissor.services.item_sufficiency_service import ItemSufficiencyService
from emissor.state.state_events import StateEvent, StateEventType
from emissor.ui_qt.base import QtSection
from emissor.ui_qt.theme import make_button
from emissor.ui_qt.widgets.clickable_label import ClickableLabel
from emissor.utils.field_utils import get_field_str

# Larguras de coluna (compartilhadas entre cabeçalho e linhas p/ alinhar)
_W_NUM = 28
_W_COD = 135
_W_UNID = 70
_W_QTDE = 50
_W_DIAS = 50
_W_SUF = 90
_W_BTN = 28


class ItemsSection(QtSection):
    """Painel de itens da receita."""

    def __init__(self, parent: QWidget, app: QtApp) -> None:
        """
        Inicializa a seção de itens.

        Args:
            parent: Widget pai
            app: Referência à aplicação principal (QtApp)
        """
        super().__init__(parent, app)

        # Cada entrada: dict com widgets da linha
        self._item_rows: list[dict[str, Any]] = []
        self._items_list_layout: QVBoxLayout | None = None

        # Catálogo completo em memória para autocomplete local (accent/case insensitive)
        self._catalog: dict[str, dict[str, Any]] = {}
        self._desc_options: dict[str, str] = {}
        self._cod_options: dict[str, str] = {}
        self._load_catalog()

        # Histórico de dispensações por item/descrição para cálculo de suficiência
        self._history_by_item: dict[str, list[tuple[date, int]]] = {}
        self._history_by_descricao: dict[str, list[tuple[date, int]]] = {}
        self._history_patient_id: int | None = None
        self._suficiencia_modes: dict[QWidget, str] = {}
        self._suficiencia_reset: dict[QWidget, bool] = {}

        self._build_ui()

    # ========== Catálogo ==========

    def _load_catalog(self) -> None:
        """Carrega o catálogo completo uma vez para autocomplete local."""
        try:
            rows = self.app.db.get_all_catalog_items()
        except Exception as e:
            ErrorHandler.log(
                f"Erro ao carregar catálogo de itens: {e}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.DATABASE,
            )
            rows = []

        self._catalog = {}
        self._desc_options = {}
        self._cod_options = {}
        for row in rows:
            item_id = str(row.get("item_id", "")).strip()
            descricao = str(row.get("descricao", "")).strip()
            unidade = str(row.get("unidade", "")).strip()
            if not item_id or not descricao:
                continue
            self._catalog[item_id] = {
                "item_id": item_id,
                "descricao": descricao,
                "unidade": unidade,
            }
            self._desc_options[item_id] = descricao
            self._cod_options[item_id] = item_id

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói o cabeçalho de colunas + lista rolável de itens."""
        content = self.content_layout()
        content.setContentsMargins(12, 8, 12, 12)
        content.setSpacing(12)

        # Linha de cabeçalho de colunas + botão adicionar
        header = self._build_column_row(is_header=True)
        content.addLayout(header)

        # Área rolável com as linhas de itens
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Fundo transparente para herdar a cor do painel. Seletores por objectName
        # para NÃO cascatear e preservar o input_bg dos QLineEdits filhos.
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        viewport = scroll.viewport()
        viewport.setObjectName("items_viewport")
        viewport.setStyleSheet("QWidget#items_viewport { background: transparent; }")
        inner = QWidget()
        inner.setObjectName("items_inner")
        inner.setStyleSheet("QWidget#items_inner { background: transparent; }")
        self._items_list_layout = QVBoxLayout(inner)
        self._items_list_layout.setContentsMargins(0, 0, 0, 0)
        self._items_list_layout.setSpacing(4)
        self._items_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(inner)
        content.addWidget(scroll, stretch=1)

        # Uma linha vazia inicial
        self.add_item()

    def _build_column_row(self, is_header: bool = False) -> QHBoxLayout:
        """
        Constrói o cabeçalho de colunas (labels).

        Args:
            is_header: True para construir o cabeçalho de labels

        Returns:
            QHBoxLayout com os labels de coluna alinhados
        """
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)

        def _label(
            text: str,
            width: int | None = None,
            align: Qt.AlignmentFlag | None = None,
        ) -> QLabel:
            lbl = QLabel(text)
            if width is not None:
                lbl.setFixedWidth(width)
            if align is not None:
                lbl.setAlignment(align)
            return lbl

        row.addWidget(_label("#", _W_NUM))
        row.addWidget(_label("Descrição"))
        row.addWidget(_label("Código", _W_COD))
        row.addWidget(_label("Unid.", _W_UNID))
        row.addWidget(_label("Qtde.", _W_QTDE))
        row.addWidget(_label("Dias", _W_DIAS))
        row.addWidget(_label("Suficiência", _W_SUF, Qt.AlignmentFlag.AlignCenter))
        # Botão adicionar no lugar da coluna de delete
        add_btn = make_button("+", "icon")
        add_btn.setFixedSize(_W_BTN, _W_BTN)
        add_btn.clicked.connect(
            lambda _=False: (self.add_item(), self._mark_items_dirty())
        )
        row.addWidget(add_btn)
        return row

    # ========== Linhas de item ==========

    def add_item(
        self,
        descricao: str = "",
        codigo: str = "",
        unidade: str = "",
        quantidade: str = "",
        dias: str = "",
    ) -> None:
        """
        Adiciona uma linha de item com valores iniciais opcionais.

        Args:
            descricao: Descrição inicial
            codigo: Código (item_id) inicial
            unidade: Unidade inicial
            quantidade: Quantidade inicial
            dias: Dias inicial
        """
        if self._items_list_layout is None:
            return

        row_widget = QWidget()
        row_lay = QHBoxLayout(row_widget)
        row_lay.setSpacing(6)
        row_lay.setContentsMargins(0, 0, 0, 0)

        num_label = QLabel("")
        num_label.setFixedWidth(_W_NUM)
        row_lay.addWidget(num_label)

        desc_combo = SearchableComboBox(
            search_fn=static_search_fn(self._desc_options),
            placeholder="Descrição...",
            parent=row_widget,
        )
        row_lay.addWidget(desc_combo, stretch=1)

        cod_combo = SearchableComboBox(
            search_fn=static_search_fn(self._cod_options),
            placeholder="Código...",
            parent=row_widget,
        )
        cod_combo.setFixedWidth(_W_COD)
        row_lay.addWidget(cod_combo)

        unid_edit = QLineEdit()
        unid_edit.setFixedWidth(_W_UNID)
        row_lay.addWidget(unid_edit)

        qtde_edit = QLineEdit()
        qtde_edit.setFixedWidth(_W_QTDE)
        qtde_edit.setValidator(QIntValidator(0, 9999))
        row_lay.addWidget(qtde_edit)

        dias_edit = QLineEdit()
        dias_edit.setFixedWidth(_W_DIAS)
        dias_edit.setValidator(QIntValidator(0, 9999))
        row_lay.addWidget(dias_edit)

        suf_label = ClickableLabel("-/-/-", row_widget)
        suf_label.setFixedWidth(_W_SUF)
        suf_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        suf_label.setToolTip(
            "Suficiência baseada em retiradas salvas (clique para alternar)"
        )
        suf_label.clicked.connect(
            lambda _=False, w=row_widget: self._toggle_suficiencia_mode(w)
        )
        suf_label.right_clicked.connect(
            lambda _=False, w=row_widget: self._open_suficiencia_menu(w)
        )
        row_lay.addWidget(suf_label)

        rm = make_button("\u2715", "icon", row_widget)
        rm.setFixedSize(_W_BTN, _W_BTN)
        rm.clicked.connect(lambda _=False, w=row_widget: self._remove_item_row(w))
        row_lay.addWidget(rm)

        # Valores iniciais
        self._set_combo_text(desc_combo, descricao)
        self._set_combo_text(cod_combo, codigo)
        unid_edit.setText(unidade)
        qtde_edit.setText(quantidade)
        dias_edit.setText(dias)

        # Cross-fill: selecionar descrição/código preenche os demais
        desc_combo.selection_changed.connect(
            lambda key, c=cod_combo, u=unid_edit: self._on_desc_selected(key, c, u)
        )
        cod_combo.selection_changed.connect(
            lambda key, d=desc_combo, u=unid_edit: self._on_cod_selected(key, d, u)
        )

        # Dirty tracking
        for w in (unid_edit, qtde_edit, dias_edit):
            w.textChanged.connect(lambda _t="": self._mark_items_dirty())
        for combo in (desc_combo, cod_combo):
            combo.text_edited.connect(lambda _t="": self._mark_items_dirty())

        # Atualiza coluna de suficiência sempre que dias mudam
        dias_edit.textChanged.connect(self._update_suficiencia_labels)

        entry = {
            "widget": row_widget,
            "num": num_label,
            "desc": desc_combo,
            "cod": cod_combo,
            "unid": unid_edit,
            "qtde": qtde_edit,
            "dias": dias_edit,
            "suf": suf_label,
        }
        self._suficiencia_modes[row_widget] = "salvo"
        self._item_rows.append(entry)
        self._items_list_layout.addWidget(row_widget)
        self._renumber()

    def _remove_item_row(self, row_widget: QWidget) -> None:
        """Remove uma linha de item."""
        entry = next((e for e in self._item_rows if e["widget"] is row_widget), None)
        if entry is None:
            return
        self._item_rows.remove(entry)
        self._suficiencia_modes.pop(row_widget, None)
        if self._items_list_layout is not None:
            self._items_list_layout.removeWidget(row_widget)
        row_widget.deleteLater()
        # Garante ao menos uma linha vazia
        if not self._item_rows:
            self.add_item()
        else:
            self._renumber()
        self._mark_items_dirty()

    def _renumber(self) -> None:
        """Renumera as linhas (1, 2, 3, ...)."""
        for i, entry in enumerate(self._item_rows):
            entry["num"].setText(str(i + 1))

    # ========== Suficiência ==========

    def _load_history(self, patient_id: int | None) -> None:
        """
        Carrega histórico de dispensações do paciente de forma assíncrona.

        Args:
            patient_id: ID do paciente selecionado ou None.
        """
        self._history_by_item.clear()
        self._history_by_descricao.clear()
        self._history_patient_id = patient_id
        if patient_id is None:
            return
        self.app.db_runner.run(
            self.app.db.get_patient_item_dispensation_history,
            patient_id,
            on_done=self._on_history_loaded,
        )

    def _on_history_loaded(self, rows: Any) -> None:
        """
        Processa resultado do histórico e atualiza os labels de suficiência.

        Args:
            rows: Linhas retornadas pelo banco de dados.
        """
        current_patient_id = self.app.state_manager.get_patient_id()
        if current_patient_id != self._history_patient_id:
            return

        (
            self._history_by_item,
            self._history_by_descricao,
        ) = self._parse_history_rows(rows)
        self._update_suficiencia_labels()

    def _parse_history_rows(
        self, rows: Any
    ) -> tuple[dict[str, list[tuple[date, int]]], dict[str, list[tuple[date, int]]]]:
        """
        Converte linhas do banco em dicionários de histórico por item e descrição.

        Args:
            rows: Linhas do banco com item_id, descricao, data_retirada e dias.

        Returns:
            Tupla (historico_por_item_id, historico_por_descricao).
        """
        by_item: dict[str, list[tuple[date, int]]] = {}
        by_descricao: dict[str, list[tuple[date, int]]] = {}
        for row in rows:
            item_id = str(row.get("item_id", "")).strip()
            descricao = str(row.get("descricao", "")).strip()
            data_str = str(row.get("data_retirada", "")).strip()
            dias_str = str(row.get("dias", "")).strip()
            if not data_str:
                continue
            try:
                data_retirada = date.fromisoformat(data_str)
                dias = int(dias_str)
            except (ValueError, TypeError):
                continue
            if dias < 0:
                continue
            if item_id:
                by_item.setdefault(item_id, []).append((data_retirada, dias))
            if descricao:
                by_descricao.setdefault(
                    self._normalize_suficiencia_key(descricao), []
                ).append((data_retirada, dias))
        for item_history in by_item.values():
            item_history.sort(key=lambda x: x[0])
        for desc_history in by_descricao.values():
            desc_history.sort(key=lambda x: x[0])
        return by_item, by_descricao

    @staticmethod
    def _normalize_suficiencia_key(text: str) -> str:
        """
        Normaliza texto para comparação de suficiência.

        Args:
            text: Texto a ser normalizado.

        Returns:
            Texto em minúsculas e sem espaços extras.
        """
        return " ".join(text.lower().split())

    def _current_dispensation_date(self) -> date:
        """
        Retorna a data da retirada selecionada na DatesSection.

        Returns:
            Data da retirada ou data atual se não for possível parser.
        """
        try:
            _, data_filename = self.app.dates_section.get_data_retirada_for_pdf()
            return date.fromisoformat(data_filename)
        except (ValueError, AttributeError):
            return date.today()

    def _update_suficiencia_labels(self) -> None:
        """Atualiza os labels de suficiência de todas as linhas."""
        current_date = self._current_dispensation_date()
        for entry in self._item_rows:
            self._update_suficiencia_for_row(entry, current_date)

    def _update_suficiencia_for_row(
        self, entry: dict[str, Any], current_date: date
    ) -> None:
        """
        Calcula e exibe a suficiência de uma linha específica.

        Args:
            entry: Dicionário com widgets da linha.
            current_date: Data da dispensação atual.
        """
        suf_label = entry.get("suf")
        if suf_label is None:
            return

        item_id = entry["cod"].current_text().strip()
        descricao = entry["desc"].current_text().strip()
        mode = self._suficiencia_modes.get(entry["widget"], "salvo")

        # Busca histórico por item_id; se não encontrar, tenta pela descrição
        # (algumas retiradas antigas podem ter item_id vazio ou divergente).
        history: list[tuple[date, int]] = []
        if item_id:
            history = self._history_by_item.get(item_id, [])
        if not history and descricao:
            history = self._history_by_descricao.get(
                self._normalize_suficiencia_key(descricao), []
            )

        try:
            if mode == "salvo":
                result_date = ItemSufficiencyService.compute_default_end(history)
                if result_date is None:
                    suf_label.setText("-/-/-")
                    return
                tooltip = (
                    "Suficiência baseada em retiradas salvas "
                    "(clique para ver a partir da data de retirada)"
                )
            else:
                dias = ItemSufficiencyService.parse_dias(entry["dias"].text())
                if dias is None:
                    suf_label.setText("-/-/-")
                    return
                result_date = ItemSufficiencyService.compute_combined_end(
                    history, current_date, dias
                )
                tooltip = (
                    "Suficiência a partir da data de retirada "
                    "(clique para ver retiradas salvas)"
                )

            suf_label.setText(ItemSufficiencyService.format_date(result_date))
            suf_label.setToolTip(tooltip)
        except Exception:
            suf_label.setText("-/-/-")

    def _toggle_suficiencia_mode(self, row_widget: QWidget) -> None:
        """
        Alterna o modo de exibição da suficiência de uma linha.

        Args:
            row_widget: Widget da linha clicada.
        """
        current_mode = self._suficiencia_modes.get(row_widget, "salvo")
        new_mode = "hoje" if current_mode == "salvo" else "salvo"
        self._suficiencia_modes[row_widget] = new_mode
        entry = next((e for e in self._item_rows if e["widget"] is row_widget), None)
        if entry is not None:
            self._update_suficiencia_for_row(entry, self._current_dispensation_date())

    def _open_suficiencia_menu(self, row_widget: QWidget) -> None:
        """
        Abre o menu de contexto da suficiência (botão direito).

        O item "Resetar" é alternável (checkable): ligado, marca o item para
        ser ignorado no histórico de suficiência ao salvar a retirada.

        Args:
            row_widget: Widget da linha clicada.
        """
        entry = next((e for e in self._item_rows if e["widget"] is row_widget), None)
        if entry is None:
            return
        menu = QMenu(self)
        reset_action = menu.addAction("Resetar")
        reset_action.setCheckable(True)
        reset_action.setChecked(self._suficiencia_reset.get(row_widget, False))
        reset_action.triggered.connect(
            lambda _checked, w=row_widget: self._toggle_reset_suficiencia(w)
        )
        menu.exec(self.cursor().pos())

    def _toggle_reset_suficiencia(self, row_widget: QWidget) -> None:
        """
        Alterna o estado de reset (ignore histórico) de uma linha. Quando
        ligado, purga o histórico em memória daquele item para feedback
        imediato; a persistência ocorre ao salvar a retirada.

        Args:
            row_widget: Widget da linha a alternar.
        """
        entry = next((e for e in self._item_rows if e["widget"] is row_widget), None)
        if entry is None:
            return
        new_state = not self._suficiencia_reset.get(row_widget, False)
        self._suficiencia_reset[row_widget] = new_state
        if new_state:
            item_id = entry["cod"].current_text().strip()
            descricao = entry["desc"].current_text().strip()
            if item_id:
                self._history_by_item.pop(item_id, None)
            if descricao:
                self._history_by_descricao.pop(
                    self._normalize_suficiencia_key(descricao), None
                )
        else:
            self._load_history(self._history_patient_id)
        self._update_suficiencia_for_row(entry, self._current_dispensation_date())

    def get_reset_item_keys(self) -> list[tuple[str, str]]:
        """
        Retorna os pares (item_id, descricao) das linhas com reset ativo,
        para serem ignorados no histórico ao salvar a retirada.

        Returns:
            Lista de tuplas (item_id, descricao) normalizadas.
        """
        keys: list[tuple[str, str]] = []
        for entry in self._item_rows:
            if not self._suficiencia_reset.get(entry["widget"], False):
                continue
            item_id = entry["cod"].current_text().strip()
            descricao = entry["desc"].current_text().strip()
            keys.append((item_id, descricao))
        return keys

    def clear_reset_toggles(self) -> None:
        """Limpa o estado de reset de todas as linhas (após salvar)."""
        self._suficiencia_reset.clear()
        self._update_suficiencia_labels()

    def clear_items(self) -> None:
        """Remove todas as linhas e cria uma vazia."""
        for entry in self._item_rows:
            entry["widget"].deleteLater()
        self._item_rows.clear()
        self._suficiencia_modes.clear()
        self.add_item()

    def load_items(self, items: Any) -> None:
        """
        Carrega uma lista de itens (do paciente).

        Args:
            items: Lista de dicts/objetos com item_id, descricao, unidade,
                quantidade, dias
        """
        for entry in self._item_rows:
            entry["widget"].deleteLater()
        self._item_rows.clear()
        self._suficiencia_modes.clear()
        for item in items:
            self.add_item(
                descricao=get_field_str(item, "descricao"),
                codigo=get_field_str(item, "item_id"),
                unidade=get_field_str(item, "unidade"),
                quantidade=get_field_str(item, "quantidade"),
                dias=get_field_str(item, "dias"),
            )
        if not self._item_rows:
            self.add_item()

    def _mark_items_dirty(self) -> None:
        """Recomputa o estado dirty a partir dos valores atuais da UI."""
        self.app.refresh_dirty_state()

    def get_items_data(self) -> list[dict[str, str]]:
        """
        Extrai os itens preenchidos (apenas os com descrição).

        Returns:
            Lista de dicionários com num/descricao/item_id/unidade/
            quantidade/dias
        """
        items: list[dict[str, str]] = []
        for entry in self._item_rows:
            descricao = entry["desc"].current_text().strip()
            if not descricao:
                continue
            items.append(
                {
                    "num": entry["num"].text(),
                    "descricao": descricao,
                    "item_id": entry["cod"].current_text().strip(),
                    "unidade": entry["unid"].text().strip(),
                    "quantidade": entry["qtde"].text().strip(),
                    "dias": entry["dias"].text().strip(),
                }
            )
        return items

    def finish_edit(self) -> None:
        """Qt: edições são commitadas imediatamente (no-op)."""

    # ========== Autocomplete (catálogo) ==========

    def _on_desc_selected(
        self, key: object, cod_combo: SearchableComboBox, unid_edit: QLineEdit
    ) -> None:
        """
        Seleção de descrição: preenche código e unidade a partir do catálogo.

        Args:
            key: item_id selecionado
            cod_combo: Combo de código da mesma linha
            unid_edit: Campo unidade da mesma linha
        """
        if not isinstance(key, str):
            return

        rec = self._catalog.get(key)
        if rec is not None:
            self._set_combo_text(cod_combo, str(rec.get("item_id", "")))
            unid = rec.get("unidade", "")
            if unid:
                unid_edit.setText(unid)
        self._mark_items_dirty()
        self._update_suficiencia_labels()

    def _on_cod_selected(
        self, key: object, desc_combo: SearchableComboBox, unid_edit: QLineEdit
    ) -> None:
        """
        Seleção de código: preenche descrição e unidade a partir do catálogo.

        Args:
            key: item_id selecionado
            desc_combo: Combo de descrição da mesma linha
            unid_edit: Campo unidade da mesma linha
        """
        if not isinstance(key, str):
            return

        rec = self._catalog.get(key)
        if rec is not None:
            self._set_combo_text(desc_combo, str(rec.get("descricao", "")))
            unid = rec.get("unidade", "")
            if unid:
                unid_edit.setText(unid)
        self._mark_items_dirty()
        self._update_suficiencia_labels()

    def _refresh_catalog(self) -> None:
        """Recarrega o catálogo e atualiza opções de todos os combos existentes."""
        self._load_catalog()
        for entry in self._item_rows:
            entry["desc"].set_search_fn(static_search_fn(self._desc_options))
            entry["cod"].set_search_fn(static_search_fn(self._cod_options))

    # ========== StateObserver ==========

    def on_state_changed(self, event: StateEvent) -> None:
        """Reage a mudanças de estado do StateManager."""
        try:
            if event.event_type == StateEventType.PATIENT_SELECTED:
                items = event.data.get("patient", {}).get("itens", [])
                self.load_items(items)
                self._load_history(self.app.state_manager.get_patient_id())
            elif event.event_type == StateEventType.PATIENT_CLEARED:
                self.clear_items()
                self._load_history(None)
            elif event.event_type == StateEventType.PATIENT_UPDATED:
                self._refresh_catalog()
                updates = event.data.get("updates", {})
                if "itens" in updates:
                    self.load_items(updates.get("itens", []))
                    self._update_suficiencia_labels()
            elif event.event_type == StateEventType.DATE_RECALCULATION_NEEDED:
                self._update_suficiencia_labels()
            elif event.event_type == StateEventType.PDF_GENERATED:
                self._load_history(self.app.state_manager.get_patient_id())
        except Exception as e:
            self._handle_state_change_error(e, self.__class__.__name__)

    # ========== Helpers ==========

    @staticmethod
    def _set_combo_text(combo: SearchableComboBox, text: str) -> None:
        """Define texto de um SearchableComboBox sem disparar busca."""
        combo.set_text(text)
