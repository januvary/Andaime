#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preview Page — tabbed table view of malote registros
"""

from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QLineEdit,
    QHeaderView,
    QMenu,
)
from PySide6.QtCore import Qt

from rac.gui.widgets import (
    MaloteLabel,
    BasePage,
    make_button,
    open_input_dialog,
    delete_registro_with_undo,
    confirm_delete_dialog,
    make_tab,
)
from rac.gui.constants import TIPO_HEX, TIPO_LABELS
from rac.gui.styles import faded_tipo_color, tab_style_qss, filter_table_rows, data_view_style_qss

from rac.utils.text_utils import format_malote_date, format_item
from rac.services.exceptions import DuplicateRecordError
from rac.services.registro_service import DeleteSnapshot
from andaime.qt.table import table_batch_populate


class PreviewPage(BasePage):
    def __init__(self, main_window):
        super().__init__(main_window)
        self._build_ui()

    def _build_ui(self):
        layout = self._scaffold(expand_vertical=True)
        self._build_header(layout)
        layout.addSpacing(20)
        self._build_tabs(layout)
        layout.addSpacing(12)
        self._add_export_button(layout, self._export_active_malote)

    def _build_header(self, layout: QVBoxLayout):
        h = self._add_back_button(layout)

        self._malote_label = MaloteLabel(self._mw)
        self._malote_label.malote_changed.connect(self.refresh)
        h.addWidget(self._malote_label, 0, Qt.AlignmentFlag.AlignTop)

    def _build_tabs(self, layout: QVBoxLayout, insert_index: int | None = None):
        self.clear_keyboard_nav()
        malote = self._mw.state.get_active_malote()
        if not malote:
            return

        registros = self._mw.services.registro.get_with_items_by_malote(malote.id)

        self._tabs = QTabWidget()
        self._tabs.setMinimumHeight(500)
        self._tab_tipo_keys: list[str] = []
        self._tabs.setStyleSheet(tab_style_qss())
        self._tab_searches: dict[int, QLineEdit] = {}
        self._shortcut_searches: list[tuple[str, QLineEdit]] = []

        for tipo in TIPO_LABELS:
            tipo_registros = [r for r in registros if r.tipo == tipo]
            tipo_registros.sort(key=lambda r: r.paciente_name or "")

            tab, tab_layout = make_tab()

            search = QLineEdit()
            search.setPlaceholderText("Buscar paciente ou medicamento...")

            add_btn = make_button("Novo Registro", "primary")
            add_btn.setToolTip(f"Novo registro — {TIPO_LABELS.get(tipo, tipo)}")
            add_btn.clicked.connect(
                lambda _checked=False, t=tipo: self._mw.navigate_to(
                    "entry", tipo=t, return_to="preview"
                )
            )

            search_row = QHBoxLayout()
            search_row.setSpacing(8)
            search_row.addWidget(search)
            search_row.addWidget(add_btn)
            tab_layout.addLayout(search_row)

            table = QTableWidget(0, 2)
            table.setHorizontalHeaderLabels(["Nome", "Medicamentos"])
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(
                0, QHeaderView.ResizeMode.ResizeToContents
            )
            table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            if hdr := table.horizontalHeaderItem(1):
                hdr.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
            table.setAlternatingRowColors(True)
            table.setCursor(Qt.CursorShape.PointingHandCursor)
            table.setStyleSheet(data_view_style_qss(extra_header_hover=f"\n            QHeaderView::section:hover {{ color: {TIPO_HEX.get(tipo, '#3B82F6')}; }}"))
            tab_layout.addWidget(table)

            search.textChanged.connect(
                lambda text, t=table: filter_table_rows(t, text)
            )

            rows_data = [
                (reg, proc)
                for reg in tipo_registros
                for proc in reg.processes
            ]

            table.setRowCount(len(rows_data))
            with table_batch_populate(table):
                for row, (reg, proc) in enumerate(rows_data):
                    name_item = QTableWidgetItem(reg.paciente_name or "")
                    name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                    name_item.setData(Qt.ItemDataRole.UserRole, reg.id)
                    table.setItem(row, 0, name_item)

                    formatted = [
                        format_item(name)
                        for name in proc.items
                    ]
                    items_str = " / ".join(formatted)
                    meds_item = QTableWidgetItem(items_str)
                    meds_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    table.setItem(row, 1, meds_item)

            table.resizeRowsToContents()
            table.setSortingEnabled(True)
            table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

            table.cellDoubleClicked.connect(
                lambda r, c, t=table: self._on_row_double_clicked(t, r)
            )
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            table.customContextMenuRequested.connect(
                lambda pos, t=table, tp=tipo: self._show_row_menu(t, tp, pos)
            )
            self.register_keyboard_nav(table, search, lambda t=table: self._on_enter(t))

            tab_label = f"{TIPO_LABELS.get(tipo, tipo)} ({len(tipo_registros)})"
            idx = self._tabs.addTab(tab, tab_label)
            self._tab_tipo_keys.append(tipo)
            self._tab_searches[idx] = search
            self._shortcut_searches.append(("_search_placeholder", search))

        self._tabs.currentChanged.connect(self._on_tab_changed)
        saved = self._mw._last_preview_tipo
        target_idx = self._tab_tipo_keys.index(saved) if saved in self._tab_tipo_keys else 0
        if target_idx == self._tabs.currentIndex():
            self._on_tab_changed(target_idx)
        else:
            self._tabs.setCurrentIndex(target_idx)
        if insert_index is not None:
            layout.insertWidget(insert_index, self._tabs, 1)
        else:
            layout.addWidget(self._tabs, 1)

    def _on_tab_changed(self, idx):
        if 0 <= idx < len(self._tab_tipo_keys):
            tipo_key = self._tab_tipo_keys[idx]
            self._tabs.setStyleSheet(tab_style_qss(faded_tipo_color(TIPO_HEX.get(tipo_key, ""))))
            self._mw._last_preview_tipo = tipo_key

    def refresh(self):
        self._malote_label.refresh()

        main_layout = self.layout()
        if main_layout is None:
            return
        item = main_layout.itemAt(0)
        if item is None:
            return
        container = item.widget()
        if container is None:
            return
        container_layout = container.layout()
        if not isinstance(container_layout, QVBoxLayout):
            return

        old = self.findChild(QTabWidget)
        insert_index = None
        if old:
            idx = container_layout.indexOf(old)
            if idx >= 0:
                insert_index = idx
            old.setParent(None)
            old.deleteLater()

        self._build_tabs(container_layout, insert_index)

    def _on_row_double_clicked(self, table: QTableWidget, row: int):
        item = table.item(row, 0)
        if not item:
            return
        reg_id = item.data(Qt.ItemDataRole.UserRole)
        if reg_id is None:
            return
        reg = self._mw.services.registro.get(reg_id)
        if reg:
            self._mw.navigate_to(
                "entry", tipo=reg.tipo, edit_id=reg_id, return_to="preview"
            )

    def _on_enter(self, table: QTableWidget):
        row = table.currentRow()
        if row >= 0:
            self._on_row_double_clicked(table, row)

    def _get_selected_ids(self, table: QTableWidget) -> list[int]:
        ids = []
        for row in table.selectionModel().selectedRows():
            item = table.item(row.row(), 0)
            if item:
                reg_id = item.data(Qt.ItemDataRole.UserRole)
                if reg_id is not None:
                    ids.append(reg_id)
        return ids

    def _show_row_menu(self, table: QTableWidget, current_tipo: str, pos):
        row = table.rowAt(pos.y())
        if row < 0:
            return
        item = table.item(row, 0)
        if not item:
            return
        reg_id = item.data(Qt.ItemDataRole.UserRole)
        if reg_id is None:
            return

        if not table.selectionModel().isRowSelected(row, table.rootIndex()):
            selected_ids = [reg_id]
            is_multi = False
        else:
            selected_ids = self._get_selected_ids(table)
            is_multi = len(selected_ids) > 1

        menu = QMenu(self)
        editar_menu = menu.addMenu("Editar")

        tipo_menu = editar_menu.addMenu("Tipo")
        for tipo in TIPO_LABELS:
            if tipo == current_tipo:
                continue
            action = tipo_menu.addAction(TIPO_LABELS.get(tipo, tipo))
            action.triggered.connect(
                lambda _checked=False, ids=selected_ids, t=tipo: self._change_tipo(
                    ids, t
                )
            )

        active = self._mw.state.get_active_malote()
        malotes = self._mw.services.malote.all()
        other_malotes = [m for m in malotes if not active or m.id != active.id]
        if other_malotes:
            malote_menu = editar_menu.addMenu("Malote")
            for m in other_malotes:
                display = format_malote_date(m)
                action = malote_menu.addAction(display)
                action.triggered.connect(
                    lambda _checked=False, ids=selected_ids, mid=m.id: self._move_to_malote(
                        ids, mid
                    )
                )

        if not is_multi:
            nome_action = editar_menu.addAction("Nome do paciente")
            nome_action.triggered.connect(
                lambda _checked=False, rid=reg_id: self._edit_paciente_name(rid)
            )

        editar_menu.addSeparator()
        label = f"Excluir ({len(selected_ids)})" if is_multi else "Excluir"
        excluir_action = editar_menu.addAction(label)
        excluir_action.triggered.connect(
            lambda _checked=False, ids=selected_ids: self._confirm_delete(ids)
        )

        if not is_multi:
            menu.addSeparator()
            paciente_action = menu.addAction("Ver paciente")
            paciente_action.triggered.connect(
                lambda _checked=False, rid=reg_id: self._view_patient(rid)
            )

        menu.exec(table.viewport().mapToGlobal(pos))

    def _change_tipo(self, reg_ids: list[int], new_tipo: str):
        service = self._mw.services.registro
        errors = 0
        for rid in reg_ids:
            try:
                service.change_tipo(rid, new_tipo)
            except DuplicateRecordError:
                errors += 1
        self.refresh()
        if errors:
            self._toast(f"{errors} registro(s) duplicado(s) ignorado(s)", "warning")
        else:
            count = len(reg_ids)
            self._toast(
                f"{count} registro(s) alterado(s)" if count > 1 else "Tipo alterado",
                "positive",
            )

    def _move_to_malote(self, reg_ids: list[int], new_malote_id: int):
        service = self._mw.services.registro
        errors = service.move_to_malote(reg_ids, new_malote_id)
        self.refresh()
        if errors:
            self._toast(f"{errors} registro(s) duplicado(s) ignorado(s)", "warning")
        else:
            count = len(reg_ids)
            self._toast(
                f"{count} registro(s) movido(s)" if count > 1 else "Registro movido",
                "positive",
            )

    def _edit_paciente_name(self, reg_id: int):
        reg = self._mw.services.registro.get(reg_id)
        if not reg or not reg.paciente_id:
            return
        new_name = open_input_dialog(
            self,
            "Editar Nome do Paciente",
            "Nome do paciente",
            initial=reg.paciente_name or "",
        )
        if not new_name or new_name == reg.paciente_name:
            return
        try:
            self._mw.services.paciente.update(reg.paciente_id, name=new_name)
            self.refresh()
            self._toast("Nome do paciente atualizado", "positive")
        except Exception as e:
            self._handle_error(e)

    def _confirm_delete(self, reg_ids: list[int]):
        if len(reg_ids) == 1:
            delete_registro_with_undo(self, self._mw.db, reg_ids[0], self.refresh)
        else:
            if not confirm_delete_dialog(
                self,
                "Excluir Registros",
                f"Excluir {len(reg_ids)} registros selecionados?",
            ):
                return
            try:
                from andaime.error_handler import ErrorContext, ErrorHandler

                service = self._mw.services.registro
                snapshots: list[DeleteSnapshot] = []
                errors = 0
                for rid in reg_ids:
                    try:
                        snap = service.delete_with_snapshot(rid)
                        if snap:
                            snapshots.append(snap)
                    except Exception as e:
                        ErrorHandler.handle_error(
                            e, context=ErrorContext.REGISTRY, show_dialog=False
                        )
                        errors += 1
                self.refresh()

                if snapshots:
                    import weakref
                    weak_self = weakref.ref(self)

                    def undo():
                        try:
                            for snap in snapshots:
                                service.restore_from_snapshot(snap)
                            p = weak_self()
                            if p is None:
                                return
                            p.refresh()
                            show_toast(
                                f"{len(snapshots)} registro(s) restaurado(s)",
                                "positive",
                                p,
                            )
                        except Exception as e:
                            ErrorHandler.handle_error(
                                e, context=ErrorContext.REGISTRY, show_dialog=False
                            )

                    from rac.gui.widgets.toast import show_toast

                    msg = f"{len(snapshots)} registros excluidos"
                    if errors:
                        msg += f" ({errors} erro(s))"
                    show_toast(
                        msg,
                        "info",
                        self,
                        action_label="Desfazer",
                        action_callback=undo,
                        timeout_ms=5000,
                    )
                else:
                    self._toast(f"{errors} erro(s) ao excluir", "negative")
            except Exception as e:
                self._handle_error(e)

    def _view_patient(self, reg_id: int):
        reg = self._mw.services.registro.get(reg_id)
        if reg and reg.paciente_id:
            self._mw.navigate_to("patient", paciente_id=reg.paciente_id, highlight_registro=reg_id, return_to="preview")

    def set_shortcuts_visible(self, show: bool):
        super().set_shortcuts_visible(show)
        self._malote_label.set_shortcut_hint_visible(show)
