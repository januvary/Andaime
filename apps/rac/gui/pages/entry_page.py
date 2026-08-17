#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry Page — record creation and editing
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QCheckBox,
    QSizePolicy,
    QLineEdit,
)
from PySide6.QtCore import Qt, QTimer

if TYPE_CHECKING:
    from rac.gui.main_window import MainWindow

from andaime.qt.widgets import SearchableComboBox, CycleButton, static_search_fn
from andaime.error_handler import ErrorContext
from rac.gui.widgets import (
    SectionLabel,
    TipoCombo,
    MaloteLabel,
    make_button,
    make_hbox,
    BasePage,
    delete_registro_with_undo,
    confirm_past_malote,
    MaloteDecision,
)
from rac.gui.widgets.buttons import make_icon_button
from rac.models import Registro
from rac.services.registro_service import EditContext
from rac.services.exceptions import ValidationError, DuplicateRecordError
from rac.utils.text_utils import is_malote_past
from andaime.text import to_upper_normalized

from rac.gui.styles import colors


@dataclass
class _RowData:
    group_btn: CycleButton
    row_widget: QWidget
    combo: SearchableComboBox | None = None
    quantidade_input: QLineEdit | None = None
    cid_combo: SearchableComboBox | None = None
    pg: int = 1


class EntryPage(BasePage):
    def __init__(
        self,
        main_window: MainWindow,
        tipo: str,
        edit_id: int | None = None,
        return_to: str = "start",
        paciente_id: int | None = None,
        patient_return_to: str = "start",
    ):
        super().__init__(main_window)
        self._tipo = tipo
        self._edit_id: int | None = edit_id
        self._edit_ctx: EditContext | None = None
        self._focus_index: int = -1
        self._return_to = return_to
        self._patient_return_to = patient_return_to
        self._pre_paciente_id: int | None = paciente_id
        self._rows: list[_RowData] = []
        self._focusable_combos: list[SearchableComboBox] = []
        self._group_cids: dict[int, str] = {}
        self._syncing: bool = False
        self._shortcut_widgets: dict[str, QPushButton | QLabel | QCheckBox] = {}
        self._delete_btn: QPushButton | None = None

        if edit_id:
            self._edit_ctx = self._mw.services.registro.load_for_edit(edit_id)

        self._state().set_current_tipo(tipo)
        self._build_ui()

    @property
    def _is_editing(self) -> bool:
        return self._edit_id is not None

    @property
    def _edit_registro(self) -> Registro | None:
        return self._edit_ctx.registro if self._edit_ctx else None

    def _build_ui(self):
        layout = self._scaffold()
        self._build_header(layout)
        layout.addSpacing(20)

        layout.addWidget(SectionLabel("Paciente"))
        layout.addSpacing(8)
        self._build_patient_section(layout)
        layout.addSpacing(20)

        layout.addWidget(SectionLabel("Itens"))
        layout.addSpacing(8)
        self._build_items_section(layout)
        layout.addSpacing(28)

        self._build_action_bar(layout)

        QTimer.singleShot(0, self._paciente_combo.focus_search)
        if self._pre_paciente_id and not self._edit_id:
            QTimer.singleShot(
                0, lambda: self._on_paciente_selected(str(self._pre_paciente_id))
            )

    def _build_header(self, layout: QVBoxLayout):
        self._tipo_combo = TipoCombo(self._tipo)

        if self._edit_registro:
            malote = self._mw.services.malote.get(self._edit_registro.malote_id)
            if malote:
                self._state().set_active_malote(malote)

        self._malote_label = MaloteLabel(self._mw)

        self._tipo_combo.tipo_changed.connect(self._on_context_changed)
        self._malote_label.malote_changed.connect(self._on_malote_changed)

        h = self._add_back_button(layout, target=self._return_to)
        h.addWidget(self._tipo_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        h.addStretch()
        h.addWidget(self._malote_label, 0, Qt.AlignmentFlag.AlignTop)

    def _build_patient_section(self, layout: QVBoxLayout):
        h = make_hbox()

        self._paciente_combo = SearchableComboBox(
            self._search_pacientes, "Nome do Paciente"
        )

        prefill_id = self._edit_registro.paciente_id if self._edit_registro else self._pre_paciente_id
        if prefill_id:
            paciente = self._mw.services.paciente.get(prefill_id)
            if paciente:
                self._paciente_combo.set_current(str(paciente.id), paciente.name)

        self._paciente_combo.selection_changed.connect(self._on_paciente_selected)
        h.addWidget(self._paciente_combo)

        self._focusable_combos = [self._paciente_combo]
        self._rebuild_focusable_combos()

        self._shortcut_searches = [
            ("Nome do Paciente", self._paciente_combo._line_edit),
        ]

        layout.addLayout(h)

    def _search_pacientes(self, query: str) -> dict[str, str]:
        pacientes = self._mw.services.paciente.search(query, limit=30)
        return {str(p.id): p.name for p in pacientes}

    def _search_items(self, query: str) -> dict[str, str]:
        normalized = to_upper_normalized(query)
        return {k: v for k, v in self._catalog_options.items() if normalized in v}

    def _build_items_section(self, layout: QVBoxLayout):
        all_items = self._mw.services.item_catalog.all()
        self._catalog_options = {str(i.id): i.name for i in all_items}
        self._item_cids: dict[int, list[str]] = {}
        for i in all_items:
            if i.id is not None and i.cids:
                try:
                    self._item_cids[i.id] = json.loads(i.cids)
                except (json.JSONDecodeError, TypeError):
                    self._item_cids[i.id] = []

        self._items_container = QVBoxLayout()
        self._items_container.setSpacing(4)
        layout.addLayout(self._items_container)

        layout.addSpacing(4)
        add_btn = make_button("+ Adicionar Item", "flat")
        add_btn.clicked.connect(self._add_item_row)
        self._shortcut_widgets["add_item"] = add_btn
        layout.addWidget(add_btn)

        if self._edit_ctx:
            for item_id, process_group, cid, quantidade in self._edit_ctx.items:
                self._add_item_row(
                    item_id=item_id,
                    process_group=process_group,
                    cid=cid,
                    quantidade=quantidade,
                )
        else:
            self._add_item_row()

    def _build_action_bar(self, layout: QVBoxLayout):
        h = QHBoxLayout()
        h.setSpacing(8)

        self._docs_check = QCheckBox("Esperando documentos")
        self._docs_check.setToolTip("Exclui este registro da planilha exportada.")
        if self._edit_registro and self._edit_registro.waiting_docs:
            self._docs_check.setChecked(True)
        self._docs_check.toggled.connect(self._on_waiting_docs_toggled)
        h.addWidget(self._docs_check)
        self._shortcut_widgets["toggle_docs"] = self._docs_check

        h.addStretch()

        self._status_label = QLabel()
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        h.addWidget(self._status_label)

        h.addStretch()

        stay_label = QLabel("Ficar nesta tela")
        c = colors()
        stay_label.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 12px; border: none;"
        )
        h.addWidget(stay_label)
        self._shortcut_widgets["toggle_stay"] = stay_label

        self._auto_switch = QCheckBox()
        self._auto_switch.setChecked(self._state().get_stay_on_page())
        self._auto_switch.stateChanged.connect(
            lambda: self._state().set_stay_on_page(self._auto_switch.isChecked())
        )
        h.addWidget(self._auto_switch)

        if self._is_editing:
            self._delete_btn = make_button("Excluir", "negative")
            self._delete_btn.clicked.connect(self._confirm_delete)
            h.addWidget(self._delete_btn)
        else:
            self._delete_btn = None

        save_btn = make_button("Salvar", "positive")
        save_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        save_btn.clicked.connect(self._on_save)
        h.addWidget(save_btn)
        self._shortcut_widgets["save"] = save_btn

        layout.addLayout(h)
        self._update_registro_status(self._is_editing)

    def set_shortcuts_visible(self, show: bool):
        super().set_shortcuts_visible(show)
        self._malote_label.set_shortcut_hint_visible(show)

    def _update_registro_status(self, editing: bool):
        c = colors()
        self._status_label.setText("Editando registro" if editing else "Novo registro")
        self._status_label.setStyleSheet(
            f"color: {c['text_secondary']}; font-size: 12px; font-style: italic;"
        )

    def _add_item_row(self, item_id: int | None = None, process_group: int = 1, cid: str = "", quantidade: int = 0):
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row_h = make_hbox(spacing=2)
        row.setLayout(row_h)

        rd: _RowData
        rd = _RowData(
            group_btn=CycleButton(
                str(process_group), "positive",
                modulus=5, base=1, initial=process_group, font_size=14,
                on_change=lambda v: self._on_group_changed(rd, v),
            ),
            row_widget=row, pg=process_group,
        )
        rd.group_btn.setToolTip("Grupo do item (clique p/ alterar)")
        row_h.addWidget(rd.group_btn)

        combo = SearchableComboBox(self._search_items, "Buscar item...")
        if item_id is not None:
            combo.set_current_by_data(str(item_id))
        rd.combo = combo
        row_h.addWidget(combo)

        # quantidade_input = None
        # if self._tipo == "retirada":
        #     quantidade_input = QLineEdit()
        #     quantidade_input.setFixedWidth(80)
        #     quantidade_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        #     quantidade_input.setPlaceholderText("Qnt")
        #     rd.quantidade_input = quantidade_input
        #     row_h.addWidget(quantidade_input)

        cid_combo = SearchableComboBox(static_search_fn({}), "CID")
        cid_combo.setFixedWidth(80)
        rd.cid_combo = cid_combo
        row_h.addWidget(cid_combo)

        cid_combo.selection_changed.connect(
            lambda data, r=rd: self._on_cid_changed_in_row(r, data)
        )

        if item_id is not None:
            self._populate_cid_combo(rd, item_id, cid)

        combo.selection_changed.connect(
            lambda data, r=rd: self._on_item_selected_in_row(r, data)
        )

        self._rows.append(rd)

        remove_btn = make_icon_button("\u00d7", "positive", font_size=16)
        remove_btn.setToolTip("Remover item")
        remove_btn.clicked.connect(lambda _checked=False, w=row: self._remove_item(w))
        row_h.addWidget(remove_btn)

        self._items_container.addWidget(row)
        self._rebuild_focusable_combos()
        return combo

    def _on_item_selected_in_row(self, rd: _RowData, data: str | None):
        if not data:
            if rd.cid_combo:
                rd.cid_combo.clear()
                rd.cid_combo.set_search_fn(static_search_fn({}))
            return
        try:
            item_id = int(data)
        except (ValueError, TypeError):
            return
        self._populate_cid_combo(rd, item_id, "")

    def _populate_cid_combo(self, rd: _RowData, item_id: int, selected_cid: str):
        if not rd.cid_combo:
            return
        cids = self._item_cids.get(item_id, [])
        if not cids:
            rd.cid_combo.clear()
            rd.cid_combo.set_search_fn(static_search_fn({}))
            return
        options = {cid: cid for cid in cids}
        rd.cid_combo.set_search_fn(static_search_fn(options))
        group_cid = self._group_cids.get(rd.pg, "")
        chosen = selected_cid or group_cid
        if chosen and chosen in options:
            rd.cid_combo.set_current_by_data(chosen)
            if selected_cid:
                self._register_and_propagate_cid(rd, selected_cid)
        elif len(cids) == 1:
            rd.cid_combo.set_current_by_data(cids[0])
            self._register_and_propagate_cid(rd, cids[0])

    def _on_cid_changed_in_row(self, rd: _RowData, data: str | None):
        if self._syncing or not data:
            return
        self._register_and_propagate_cid(rd, data)

    def _register_and_propagate_cid(self, rd: _RowData, cid: str):
        pg = rd.pg
        if self._group_cids.get(pg) == cid:
            return
        self._group_cids[pg] = cid
        self._syncing = True
        try:
            for other in self._rows:
                if other is rd or other.pg != pg:
                    continue
                self._apply_cid_to_row_if_allowed(other, cid)
        finally:
            self._syncing = False

    def _apply_cid_to_row_if_allowed(self, rd: _RowData, cid: str):
        if not rd.cid_combo:
            return
        data = rd.combo.current_data() if rd.combo else None
        if not data:
            return
        try:
            item_id = int(data)
        except (ValueError, TypeError):
            return
        allowed = self._item_cids.get(item_id, [])
        if cid in allowed:
            rd.cid_combo.set_current_by_data(cid)

    def _on_group_changed(self, rd: _RowData, new_pg: int):
        rd.pg = new_pg
        group_cid = self._group_cids.get(new_pg, "")
        if group_cid:
            self._apply_cid_to_row_if_allowed(rd, group_cid)
        else:
            current = rd.cid_combo.current_data() if rd.cid_combo else None
            if current:
                self._register_and_propagate_cid(rd, current)

    def _remove_item(self, widget: QWidget):
        self._rows = [rd for rd in self._rows if rd.row_widget is not widget]
        widget.setParent(None)
        widget.deleteLater()
        self._rebuild_focusable_combos()

    def _rebuild_focusable_combos(self):
        self._focusable_combos = [self._paciente_combo] + [
            rd.combo for rd in self._rows if rd.combo
        ]
        if self._focus_index >= len(self._focusable_combos):
            self._focus_index = -1

    def _on_paciente_selected(self, data):
        if not data:
            return
        try:
            paciente_id = int(data)
        except (ValueError, TypeError):
            return
        self._load_items_for_context(paciente_id)

    def _on_context_changed(self, *_):
        self._tipo = self._tipo_combo.current_tipo()
        paciente_id = self._resolve_current_patient()
        if paciente_id is None:
            return
        self._load_items_for_context(paciente_id)

    def _on_waiting_docs_toggled(self, _checked: bool):
        pass

    def _on_malote_changed(self):
        malote = self._state().get_active_malote()
        if malote and is_malote_past(malote):
            decision = confirm_past_malote(self.window(), malote)
            if decision is MaloteDecision.CHANGE:
                self._malote_label.open_dialog()

    def _resolve_current_patient(self) -> int | None:
        pid = self._paciente_combo.current_data()
        if not pid:
            name = self._paciente_combo.current_text().strip()
            if name:
                existing = self._mw.services.paciente.find_by_name(name)
                if existing:
                    pid = str(existing.id)
        if not pid:
            return None
        try:
            return int(pid)
        except (ValueError, TypeError):
            return None

    def _clear_item_rows(self):
        self._rows.clear()
        self._group_cids.clear()
        while self._items_container.count():
            item = self._items_container.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.setParent(None)
                w.deleteLater()
        self._rebuild_focusable_combos()

    def _collect_items(self) -> list[tuple[int, int, str, int]]:
        items = []
        for rd in self._rows:
            data = rd.combo.current_data() if rd.combo else None
            if not data:
                continue
            cid = rd.cid_combo.current_data() or "" if rd.cid_combo else ""
            quantidade = 0
            if self._tipo == "retirada" and rd.quantidade_input:
                try:
                    quantidade = int(rd.quantidade_input.text() or "0")
                except ValueError:
                    quantidade = 0
            items.append((int(data), rd.pg, cid, quantidade))
        return items

    def _load_items_for_context(self, paciente_id: int):
        malote = self._state().get_active_malote()
        tipo = self._tipo_combo.current_tipo()

        ctx = self._mw.services.registro.load_for_context(
            tipo, paciente_id, malote.id if malote else None
        )

        self._clear_item_rows()
        if ctx.registro:
            self._update_registro_status(True)
            if ctx.items:
                for item_id, process_group, cid, quantidade in ctx.items:
                    self._add_item_row(
                        item_id=item_id,
                        process_group=process_group,
                        cid=cid,
                        quantidade=quantidade,
                    )
            else:
                self._add_item_row()
        else:
            self._update_registro_status(False)
            if ctx.suggested_items:
                for item_id, process_group, cid, quantidade in ctx.suggested_items:
                    self._add_item_row(
                        item_id=item_id,
                        process_group=process_group,
                        cid=cid,
                        quantidade=quantidade,
                    )
            else:
                self._add_item_row()

    def focus_next_field(self):
        if not self._focusable_combos:
            return
        for _ in range(len(self._focusable_combos)):
            self._focus_index = (self._focus_index + 1) % len(self._focusable_combos)
            combo = self._focusable_combos[self._focus_index]
            if combo._line_edit.hasFocus():
                continue
            combo.focus_search()
            return

    def _combo_at(self, index: int) -> SearchableComboBox | None:
        if 0 <= index < len(self._focusable_combos):
            return self._focusable_combos[index]
        return None

    def _on_save(self):
        items = self._collect_items()
        if not items:
            self._toast("Adicione pelo menos um item", "warning")
            return
        tipo = self._tipo_combo.current_tipo()
        waiting_docs = self._docs_check.isChecked()

        malote = self._state().get_active_malote()
        if not malote:
            self._toast("Selecione um malote", "warning")
            return

        paciente_name = self._paciente_combo.current_text().strip()
        paciente_id = self._resolve_current_patient()

        service = self._mw.services.registro

        try:
            result = service.save(
                tipo=tipo,
                paciente_name=paciente_name,
                malote_id=malote.id,
                items=items,
                edit_id=self._edit_id,
                waiting_docs=waiting_docs,
                paciente_id=paciente_id,
            )
        except ValidationError as e:
            self._toast(str(e), "warning")
            return
        except DuplicateRecordError:
            self._toast(
                "Já existe um registro com esse tipo/paciente/malote", "warning"
            )
            return
        except Exception as e:
            self._handle_error(e, context=ErrorContext.REGISTRY)
            return

        msg = "Registro editado!" if result.is_update else "Registro salvo!"
        self._toast(msg, "positive")

        if self._auto_switch.isChecked():
            QTimer.singleShot(350, self._reset_form)
        else:
            QTimer.singleShot(350, self._navigate_back)

    def _reset_form(self):
        self._edit_id = None
        self._edit_ctx = None
        self._paciente_combo.clear()
        self._clear_item_rows()
        self._add_item_row()
        self._docs_check.blockSignals(True)
        self._docs_check.setChecked(False)
        self._docs_check.blockSignals(False)
        self._update_registro_status(False)
        if self._delete_btn:
            self._delete_btn.hide()
        self._paciente_combo.focus_search()

    def _confirm_delete(self):
        if not self._edit_id:
            return

        delete_registro_with_undo(
            self,
            self._require_db(),
            self._edit_id,
            on_refresh=lambda: QTimer.singleShot(800, self._navigate_back),
        )

    def _navigate_back(self):
        if self._return_to == "patient":
            self._mw.navigate_to(
                "patient", return_to=self._patient_return_to
            )
        else:
            self._mw.navigate_to(self._return_to)
