#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from contextlib import suppress

from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QWidget,
    QTreeWidget,
    QTreeWidgetItem,
)
from PySide6.QtCore import Qt, Signal

from rac.gui.widgets.base_page import make_hbox
from rac.gui.widgets.toast import show_toast
from rac.gui.widgets.dialogs import (
    confirm_delete_dialog,
    open_input_dialog,
    scaffold_dialog,
    prompt_dialog,
    make_dialog_toolbar,
    KEEP_OPEN,
)
from rac.gui.styles import colors
from andaime.qt import styled_menu
from andaime.qt.holidays import show_holidays_dialog

def _activate_malote_if_changed(mw, malote):
    current = mw.state.get_active_malote()
    if not current or current.id != malote.id or current.date != malote.date:
        mw.state.set_active_malote(malote)


class MaloteLabel(QWidget):
    malote_changed = Signal()

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self._mw = main_window

        layout = make_hbox(spacing=6)
        self.setLayout(layout)

        self._shortcut_hint = QLabel("")
        self._shortcut_hint.setFixedHeight(28)
        self._shortcut_hint.setFixedWidth(52)
        self._shortcut_hint.setStyleSheet(
            "color: #9CA3AF; font-size: 14px; border: none;"
        )
        layout.addWidget(self._shortcut_hint)

        self._prefix_label = QLabel("Malote:")
        self._prefix_label.setFixedHeight(28)
        self._prefix_label.setStyleSheet(
            "color: #9CA3AF; font-size: 14px; border: none;"
        )
        layout.addWidget(self._prefix_label)

        layout.addSpacing(6)

        self._date_label = QLabel()
        self._date_label.setProperty("malotelabel", "true")
        self._date_label.setFixedHeight(28)
        self._date_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._date_label.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )
        layout.addWidget(self._date_label)

        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.refresh()

    def mousePressEvent(self, event):
        _show_malote_dialog(self)

    def open_dialog(self):
        _show_malote_dialog(self)

    def refresh(self):
        from rac.utils.text_utils import format_malote_date

        malote = self._mw.state.get_active_malote()
        display = format_malote_date(malote) if malote else "Nenhum malote ativo"
        self._date_label.setText(display)

    def set_shortcut_hint_visible(self, show: bool):
        self._shortcut_hint.setText("(Ctrl+D)" if show else "")


def _show_malote_dialog(label: MaloteLabel):
    from datetime import datetime
    from rac.utils.text_utils import format_malote_date
    from rac.gui.widgets._malote_tree import (
        make_malote_tree as _make_tree,
        populate_malote_tree as _populate,
        wire_tree_keyboard as _wire_kb,
    )
    from PySide6.QtWidgets import QHeaderView

    parent = label.window()
    mw = label._mw

    dlg, layout = scaffold_dialog(parent, "Malotes", spacing=12, min_width=340)
    dlg.setMinimumHeight(350)

    tree = _make_tree()
    tree.setColumnCount(2)
    hdr = tree.header()
    hdr.setStretchLastSection(False)
    hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

    def _decorate(child, m, dt):
        active = mw.state.get_active_malote()
        is_active = active and active.id == m.id
        display = format_malote_date(m)
        prefix = "\u2713 " if is_active else "    "
        child.setText(0, f"{prefix}{display}")
        if is_active:
            font = child.font(0)
            font.setBold(True)
            child.setFont(0, font)

        arrival_str = m.arrival_date
        if not arrival_str:
            try:
                from rac.utils.date_calculator import calculate_arrival_date

                send_dt = datetime.fromisoformat(m.date).date()
                arrival_str = calculate_arrival_date(send_dt).isoformat()
            except (ValueError, TypeError):
                arrival_str = None
        if arrival_str:
            with suppress(ValueError, TypeError):
                arrival = datetime.fromisoformat(arrival_str).date()
                child.setText(1, f"\u279c {arrival.strftime('%d/%m/%Y')}")
                child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
                font = child.font(1)
                font.setPointSize(font.pointSize() - 1)
                child.setFont(1, font)

    def _populate_tree():
        malotes = mw.services.malote.all()
        _populate(
            tree,
            malotes,
            format_display=lambda _m, _dt: "",
            decorate_item=_decorate,
        )

    _populate_tree()

    def on_item_clicked(item, _column):
        malote = item.data(0, Qt.ItemDataRole.UserRole)
        if malote:
            _activate_malote_if_changed(mw, malote)
            dlg.accept()
            label.refresh()
        else:
            item.setExpanded(not item.isExpanded())

    tree.itemClicked.connect(on_item_clicked)
    _wire_kb(tree, lambda item: on_item_clicked(item, 0))
    tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def _show_tree_menu(pos):
        item = tree.itemAt(pos)
        if not item:
            return
        malote = item.data(0, Qt.ItemDataRole.UserRole)
        if not malote:
            return

        menu = styled_menu(tree)
        edit_menu = menu.addMenu("Editar")
        envio_action = edit_menu.addAction("Data de envio")
        retorno_action = edit_menu.addAction("Data de retorno")
        has_registros = mw.services.registro.get_by_malote(malote.id)
        if not has_registros:
            delete_action = menu.addAction("Excluir")
        else:
            delete_action = None

        action = menu.exec(tree.viewport().mapToGlobal(pos))
        if action == envio_action:
            _show_date_dialog(label, malote, "send", _populate_tree, dlg)
        elif action == retorno_action:
            _show_date_dialog(label, malote, "arrival", _populate_tree, dlg)
        elif action == delete_action and delete_action is not None:
            if not confirm_delete_dialog(
                parent,
                "Excluir Malote",
                f'Excluir malote "{format_malote_date(malote)}"?',
            ):
                return

            deleted = mw.services.malote.delete(malote.id)
            if deleted:
                current_active = mw.state.get_active_malote()
                if current_active and current_active.id == malote.id:
                    remaining = [
                        m for m in mw.services.malote.all() if m.id != malote.id
                    ]
                    mw.state.set_active_malote(remaining[0] if remaining else None)
                label.refresh()
                _populate_tree()
                show_toast("Malote excluído", "positive", label)
            else:
                show_toast(
                    "Malote possui registros e não pode ser excluído", "negative", label
                )

    tree.customContextMenuRequested.connect(_show_tree_menu)
    layout.addWidget(tree)

    btn_row, [new_m, holidays_btn, close_m] = make_dialog_toolbar(
        left=[("Novo Malote", "flat")],
        right=[("Gerenciar feriados", "flat"), ("Fechar", "flat")],
    )

    def _on_new_malote(_):
        _show_new_malote_dialog(label, dlg)
        _populate_tree()

    new_m.clicked.connect(_on_new_malote)

    holidays_btn.setStyleSheet("font-size: 11px;")
    holidays_btn.clicked.connect(lambda: show_holidays_dialog(parent))

    close_m.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    def _malote_key(m):
        return (m.id, m.date, m.arrival_date) if m else None

    initial = _malote_key(mw.state.get_active_malote())
    dlg.exec()
    if _malote_key(mw.state.get_active_malote()) != initial:
        label.malote_changed.emit()



def _show_new_malote_dialog(label: MaloteLabel, dlg):
    from andaime.dates import parse_date
    from rac.utils.text_utils import format_malote_date
    from rac.utils.date_calculator import next_send_date, calculate_arrival_date
    from andaime.error_handler import ErrorContext, ErrorHandler
    from andaime.qt.widgets import DateLineEdit

    mw = label._mw

    date_input = DateLineEdit()
    date_input.setPlaceholderText("dd/mm ou dd/mm/aa")
    with suppress(ValueError, TypeError):
        existing = set(mw.services.malote.get_dates())
        suggested = next_send_date(existing)
        date_input.setText(suggested.strftime("%d/%m/%Y"))
    date_input.selectAll()

    def on_confirm(input_field: DateLineEdit):
        parsed = parse_date(input_field.text())
        if not parsed:
            show_toast("Data inválida", "negative", label)
            return KEEP_OPEN
        iso = parsed.isoformat()
        try:
            arrival_iso = None
            with suppress(ValueError, TypeError):
                arrival = calculate_arrival_date(parsed)
                arrival_iso = arrival.isoformat()
            malote = mw.services.malote.create(iso, arrival_date=arrival_iso)
            _activate_malote_if_changed(mw, malote)
            label.refresh()
            show_toast(
                f"Malote criado: {format_malote_date(malote)}", "positive", label
            )
        except Exception as e:
            ErrorHandler.handle_error(e, context=ErrorContext.BATCH, show_dialog=False)
            show_toast(f"Erro: {e}", "negative", label)
            return KEEP_OPEN

    prompt_dialog(
        dlg, "Novo Malote",
        widget=date_input, confirm_label="Criar", on_confirm=on_confirm,
    )


def _show_date_dialog(label: MaloteLabel, malote, field: str, on_done, dlg):
    from andaime.dates import parse_date
    from andaime.error_handler import ErrorContext, ErrorHandler
    from andaime.qt.widgets import DateLineEdit

    mw = label._mw

    if field == "send":
        title = "Data de Envio"
        current_iso = malote.date
    else:
        title = "Data de Retorno"
        current_iso = malote.arrival_date or ""
        if not current_iso:
            with suppress(ValueError, TypeError):
                from rac.utils.date_calculator import calculate_arrival_date
                from datetime import date as date_cls

                send_dt = date_cls.fromisoformat(malote.date)
                current_iso = calculate_arrival_date(send_dt).isoformat()

    date_input = DateLineEdit()
    date_input.setPlaceholderText("dd/mm ou dd/mm/aa")
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(current_iso)
        date_input.setText(dt.strftime("%d/%m/%Y"))
    except (ValueError, TypeError):
        date_input.setText(current_iso or "")
    if date_input.text():
        date_input.selectAll()

    def on_confirm(input_field: DateLineEdit):
        parsed = parse_date(input_field.text())
        if not parsed:
            show_toast("Data inválida", "negative", label)
            return KEEP_OPEN
        iso = parsed.isoformat()
        if iso == current_iso:
            return None
        try:
            svc = mw.services.malote
            if field == "send":
                svc.update(malote.id, date=iso)
                refreshed = mw.services.malote.get(malote.id)
                if refreshed:
                    malote.date = refreshed.date
                    malote.arrival_date = refreshed.arrival_date
            else:
                svc.update(malote.id, arrival_date=iso)
                malote.arrival_date = iso
            if (
                mw.state.get_active_malote()
                and mw.state.get_active_malote().id == malote.id
            ):
                mw.state.set_active_malote(malote)
            label.refresh()
            on_done()
            show_toast("Malote atualizado", "positive", label)
        except Exception as e:
            ErrorHandler.handle_error(e, context=ErrorContext.BATCH, show_dialog=False)
            show_toast(f"Erro: {e}", "negative", label)
            return KEEP_OPEN

    prompt_dialog(
        dlg, title,
        widget=date_input, confirm_label="Salvar", on_confirm=on_confirm,
    )
