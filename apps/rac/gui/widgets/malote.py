#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from contextlib import suppress
import json
from pathlib import Path

from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QDialog,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
)
from PySide6.QtCore import Qt, Signal

from rac.gui.widgets.buttons import make_button
from rac.gui.widgets.labels import HeadingLabel
from rac.gui.widgets.base_page import make_hbox
from rac.gui.widgets.toast import show_toast
from rac.gui.widgets.dialogs import confirm_delete_dialog, make_dialog_button_row, open_input_dialog, scaffold_dialog
from rac.gui.styles import colors

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

    dlg = QDialog(parent)
    dlg.setWindowTitle("Malotes")
    dlg.setMinimumWidth(340)
    dlg.setMinimumHeight(350)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)

    layout.addWidget(HeadingLabel("Malotes"))

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

        menu = QMenu(tree)
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
            _show_date_dialog(label, malote, "send", _populate_tree)
        elif action == retorno_action:
            _show_date_dialog(label, malote, "arrival", _populate_tree)
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

    btn_row = QHBoxLayout()
    new_m = make_button("Novo Malote", "flat")
    new_m.setAutoDefault(False)

    def _on_new_malote(_):
        _show_new_malote_dialog(label)
        _populate_tree()

    new_m.clicked.connect(_on_new_malote)
    btn_row.addWidget(new_m)
    btn_row.addStretch()

    holidays_btn = make_button("Gerenciar feriados", "flat")
    holidays_btn.setAutoDefault(False)
    holidays_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    holidays_btn.setStyleSheet(holidays_btn.styleSheet() + "; font-size: 11px")
    holidays_btn.clicked.connect(lambda: _show_holidays_dialog(parent))
    btn_row.addWidget(holidays_btn)

    btn_row.addStretch()
    close_m = make_button("Fechar", "flat")
    close_m.setAutoDefault(False)
    close_m.clicked.connect(dlg.reject)
    btn_row.addWidget(close_m)
    layout.addLayout(btn_row)

    def _malote_key(m):
        return (m.id, m.date, m.arrival_date) if m else None

    initial = _malote_key(mw.state.get_active_malote())
    dlg.exec()
    if _malote_key(mw.state.get_active_malote()) != initial:
        label.malote_changed.emit()


def _show_holidays_dialog(parent):
    from datetime import date as date_cls
    from andaime.dates import DateCalculator
    from andaime.paths import get_root_directory

    dlg, layout = scaffold_dialog(parent, "Feriados", spacing=12, min_width=310)
    dlg.setMinimumHeight(420)

    pontos_path = get_root_directory() / "data" / "pontos_facultativos.json"
    pontos_data: dict[str, list[str]] = {}
    if pontos_path.exists():
        try:
            with pontos_path.open("r", encoding="utf-8") as f:
                pontos_data = json.load(f).get("pontos_facultativos", {})
        except (json.JSONDecodeError, OSError):
            pontos_data = {}

    all_holidays = DateCalculator.get_holidays()
    today = date_cls.today()
    year = today.year
    c = colors()
    day_names = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']

    pontos_set: set[date_cls] = set()
    for yr_str, plist in pontos_data.items():
        try:
            yr = int(yr_str)
        except ValueError:
            continue
        for ps in plist:
            try:
                d, m = map(int, ps.split("/"))
                pontos_set.add(date_cls(yr, m, d))
            except (ValueError, AttributeError):
                continue

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(True)
    tree.setAnimated(True)
    tree.setIndentation(0)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    tree.setStyleSheet(
        f'QTreeWidget {{ alternate-background-color: {c["table_alt_bg"]}; }}'
    )

    def _populate_tree():
        tree.clear()
        yr_holidays = sorted(h for h in all_holidays if h.year == year)
        for h in yr_holidays:
            is_ponto = h in pontos_set
            dn = day_names[h.weekday()]
            child = QTreeWidgetItem()
            child.setText(0, f"    {h.strftime('%d/%m')}  ({dn})")
            child.setData(0, Qt.ItemDataRole.UserRole, h)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, is_ponto)
            tree.addTopLevelItem(child)

    _populate_tree()
    layout.addWidget(tree)

    btn_row = QHBoxLayout()
    add_btn = make_button("Adicionar", "primary")
    add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    del_btn = make_button("Remover", "negative")
    del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    close_btn = make_button("Fechar", "flat")
    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_row.addWidget(add_btn)
    btn_row.addWidget(del_btn)
    btn_row.addStretch()
    btn_row.addWidget(close_btn)

    def _on_add():
        result = open_input_dialog(
            parent, "Adicionar facultativo",
            f"dd/mm (ano {year})",
        )
        if not result:
            return
        try:
            parts = result.strip().split("/")
            d, m = int(parts[0]), int(parts[1])
            new_date = date_cls(year, m, d)
        except (ValueError, IndexError):
            show_toast("Data inválida (use dd/mm)", "negative", parent)
            return
        yr_str = str(year)
        entry = f"{int(parts[0]):02d}/{int(parts[1]):02d}"
        current = pontos_data.get(yr_str, [])
        if entry in current:
            show_toast("Feriado facultativo já existe", "warning", parent)
            return
        current.append(entry)
        current.sort(key=lambda x: (int(x.split("/")[1]), int(x.split("/")[0])))
        pontos_data[yr_str] = current
        _save_pontos(pontos_path, pontos_data)
        DateCalculator.clear_holidays_cache()
        all_holidays.add(new_date)
        pontos_set.add(new_date)
        _populate_tree()

    add_btn.clicked.connect(_on_add)

    def _on_remove():
        item = tree.currentItem()
        if not item:
            return
        is_ponto = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not is_ponto:
            show_toast("Apenas feriados facultativos podem ser removidos", "warning", parent)
            return
        h = item.data(0, Qt.ItemDataRole.UserRole)
        if not confirm_delete_dialog(
            parent, "Remover facultativo",
            f'Remover "{h.strftime("%d/%m")}" dos facultativos?',
        ):
            return
        _remove_ponto(h, pontos_path)
        pontos_set.discard(h)
        all_holidays.discard(h)
        yr_str = str(h.year)
        if yr_str in pontos_data:
            entry = f"{h.day:02d}/{h.month:02d}"
            if entry in pontos_data[yr_str]:
                pontos_data[yr_str].remove(entry)
        DateCalculator.clear_holidays_cache()
        _populate_tree()

    del_btn.clicked.connect(_on_remove)
    close_btn.clicked.connect(dlg.accept)
    layout.addLayout(btn_row)

    dlg.exec()


def _remove_ponto(dt, pontos_path: Path):
    yr_str = str(dt.year)
    entry = f"{dt.day:02d}/{dt.month:02d}"
    data: dict = {"pontos_facultativos": {}}
    if pontos_path.exists():
        try:
            with pontos_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
    pontos = data.get("pontos_facultativos", {})
    if yr_str in pontos and entry in pontos[yr_str]:
        pontos[yr_str].remove(entry)
    _save_pontos(pontos_path, pontos)


def _save_pontos(pontos_path: Path, pontos_data: dict):
    data = {"pontos_facultativos": pontos_data}
    pontos_path.parent.mkdir(parents=True, exist_ok=True)
    with pontos_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _show_new_malote_dialog(label: MaloteLabel):
    from rac.utils.text_utils import parse_date, format_malote_date
    from rac.utils.date_calculator import next_send_date, calculate_arrival_date
    from andaime.error_handler import ErrorContext, ErrorHandler
    from andaime.widgets import DateLineEdit

    parent = label.window()
    mw = label._mw

    dlg, layout = scaffold_dialog(parent, "Novo Malote", spacing=16)

    date_input = DateLineEdit()
    date_input.setPlaceholderText("dd/mm ou dd/mm/aa")
    with suppress(ValueError, TypeError):
        existing = set(mw.services.malote.get_dates())
        suggested = next_send_date(existing)
        date_input.setText(suggested.strftime("%d/%m/%Y"))
    date_input.selectAll()
    layout.addWidget(date_input)

    btn_row, [cancel, create] = make_dialog_button_row([
        ("Cancelar", "flat"),
        ("Criar", "primary"),
    ])
    cancel.clicked.connect(dlg.reject)

    def do_create():
        parsed = parse_date(date_input.text())
        if not parsed:
            show_toast("Data inválida", "negative", label)
            return
        iso = parsed.isoformat()
        try:
            arrival_iso = None
            with suppress(ValueError, TypeError):
                arrival = calculate_arrival_date(parsed)
                arrival_iso = arrival.isoformat()
            malote = mw.services.malote.create(iso, arrival_date=arrival_iso)
            _activate_malote_if_changed(mw, malote)
            dlg.accept()
            label.refresh()
            show_toast(
                f"Malote criado: {format_malote_date(malote)}", "positive", label
            )
        except Exception as e:
            ErrorHandler.handle_error(e, context=ErrorContext.BATCH, show_dialog=False)
            show_toast(f"Erro: {e}", "negative", label)

    create.clicked.connect(do_create)
    layout.addLayout(btn_row)

    date_input.returnPressed.connect(do_create)
    dlg.exec()


def _show_date_dialog(label: MaloteLabel, malote, field: str, on_done):
    from rac.utils.text_utils import parse_date
    from andaime.error_handler import ErrorContext, ErrorHandler
    from andaime.widgets import DateLineEdit

    parent = label.window()
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

    dlg, layout = scaffold_dialog(parent, title, spacing=16)
    layout.addSpacing(4)

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
    layout.addWidget(date_input)

    btn_row, [cancel, save] = make_dialog_button_row([
        ("Cancelar", "flat"),
        ("Salvar", "primary"),
    ])
    cancel.clicked.connect(dlg.reject)

    def do_save():
        parsed = parse_date(date_input.text())
        if not parsed:
            show_toast("Data inválida", "negative", label)
            return
        iso = parsed.isoformat()
        if iso == current_iso:
            dlg.accept()
            return
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
            dlg.accept()
            on_done()
            show_toast("Malote atualizado", "positive", label)
        except Exception as e:
            ErrorHandler.handle_error(e, context=ErrorContext.BATCH, show_dialog=False)
            show_toast(f"Erro: {e}", "negative", label)

    save.clicked.connect(do_save)
    layout.addLayout(btn_row)

    date_input.returnPressed.connect(do_save)
    dlg.exec()
