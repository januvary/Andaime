#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QDialog,
    QPushButton,
    QComboBox,
)
from typing import Callable, Optional

from rac.gui.widgets.buttons import make_button
from rac.gui.widgets.labels import HeadingLabel
from rac.gui.styles import colors
from rac.gui.widgets.toast import show_toast
from rac.services.registro_service import RegistroService
from rac.models import Malote
from rac.utils.text_utils import format_malote_date
from andaime.error_handler import ErrorContext, ErrorHandler


def scaffold_dialog(parent, title, spacing=12, min_width=340):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(min_width)
    layout = QVBoxLayout(dlg)
    layout.setSpacing(spacing)
    layout.addWidget(HeadingLabel(title))
    return dlg, layout


def make_dialog_button_row(actions: list[tuple[str, str]]) -> tuple[QHBoxLayout, list[QPushButton]]:
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    buttons = []
    for label, role in actions:
        btn = make_button(label, role)
        btn_row.addWidget(btn)
        buttons.append(btn)
    return btn_row, buttons


def confirm_delete_dialog(
    parent: QWidget,
    title: str,
    message: str,
    destructive_label: str = "Excluir",
) -> bool:
    dlg, layout = scaffold_dialog(parent, title)
    layout.addSpacing(4)

    msg = QLabel(message)
    msg.setWordWrap(True)
    c = colors()
    msg.setStyleSheet(f"color: {c['text_secondary']}; font-size: 13px;")
    layout.addWidget(msg)

    btn_row, [cancel, delete_btn] = make_dialog_button_row([
        ("Cancelar", "flat"),
        (destructive_label, "negative"),
    ])
    cancel.clicked.connect(dlg.reject)
    delete_btn.clicked.connect(dlg.accept)
    layout.addLayout(btn_row)

    return dlg.exec() == QDialog.DialogCode.Accepted


def open_select_dialog(
    parent: QWidget,
    title: str,
    placeholder: str,
    options: list[str],
    initial: str | None = None,
    confirm_label: str = "Confirmar",
) -> str | None:
    dlg, layout = scaffold_dialog(parent, title, spacing=16)
    layout.addSpacing(4)

    input_field = QComboBox()
    input_field.addItems(options)
    if initial:
        idx = input_field.findText(initial)
        if idx >= 0:
            input_field.setCurrentIndex(idx)
    layout.addWidget(input_field)

    btn_row, [cancel, confirm] = make_dialog_button_row([
        ("Cancelar", "flat"),
        (confirm_label, "primary"),
    ])
    cancel.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    selected = input_field.currentText().strip()
    return selected.split(" - ")[0] if " - " in selected else selected


def open_input_dialog(
    parent: QWidget,
    title: str,
    placeholder: str,
    initial: str = "",
    confirm_label: str = "Confirmar",
) -> str | None:
    dlg, layout = scaffold_dialog(parent, title, spacing=16)
    layout.addSpacing(4)

    input_field = QLineEdit()
    input_field.setPlaceholderText(placeholder)
    input_field.setText(initial)
    if initial:
        input_field.selectAll()
    layout.addWidget(input_field)

    btn_row, [cancel, confirm] = make_dialog_button_row([
        ("Cancelar", "flat"),
        (confirm_label, "primary"),
    ])
    cancel.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    input_field.returnPressed.connect(dlg.accept)
    confirm.clicked.connect(dlg.accept)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return input_field.text().strip() or None


def open_estoque_dialog(
    parent: QWidget,
    title: str,
    initial_value: int,
) -> int | None:
    dlg, layout = scaffold_dialog(parent, title, spacing=16)
    layout.addSpacing(4)

    input_row = QHBoxLayout()
    input_row.setSpacing(4)
    input_row.addStretch()

    minus_60_btn = QPushButton("-60")
    minus_60_btn.setFixedSize(48, 48)
    minus_60_btn.setStyleSheet("padding: 0;")
    input_row.addWidget(minus_60_btn)

    minus_30_btn = QPushButton("-30")
    minus_30_btn.setFixedSize(48, 48)
    minus_30_btn.setStyleSheet("padding: 0;")
    input_row.addWidget(minus_30_btn)

    minus_btn = QPushButton("-1")
    minus_btn.setFixedSize(48, 48)
    minus_btn.setStyleSheet("padding: 0;")
    input_row.addWidget(minus_btn)

    input_field = QLineEdit()
    input_field.setFixedSize(100, 48)
    input_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
    input_field.setText(str(initial_value))
    input_field.selectAll()
    input_row.addWidget(input_field)

    plus_1_btn = QPushButton("+1")
    plus_1_btn.setFixedSize(48, 48)
    plus_1_btn.setStyleSheet("padding: 0;")
    input_row.addWidget(plus_1_btn)

    plus_30_btn = QPushButton("+30")
    plus_30_btn.setFixedSize(48, 48)
    plus_30_btn.setStyleSheet("padding: 0;")
    input_row.addWidget(plus_30_btn)

    plus_60_btn = QPushButton("+60")
    plus_60_btn.setFixedSize(48, 48)
    plus_60_btn.setStyleSheet("padding: 0;")
    input_row.addWidget(plus_60_btn)

    input_row.addStretch()
    layout.addLayout(input_row)

    btn_row, [cancel, confirm] = make_dialog_button_row([
        ("Cancelar", "flat"),
        ("Confirmar", "primary"),
    ])
    cancel.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    def update_delta(delta: int):
        try:
            current = int(input_field.text())
            new_val = max(0, current + delta)
            input_field.setText(str(new_val))
            input_field.selectAll()
        except ValueError:
            pass

    minus_60_btn.clicked.connect(lambda: update_delta(-60))
    minus_30_btn.clicked.connect(lambda: update_delta(-30))
    minus_btn.clicked.connect(lambda: update_delta(-1))
    plus_1_btn.clicked.connect(lambda: update_delta(1))
    plus_30_btn.clicked.connect(lambda: update_delta(30))
    plus_60_btn.clicked.connect(lambda: update_delta(60))

    input_field.returnPressed.connect(dlg.accept)
    confirm.clicked.connect(dlg.accept)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    try:
        return int(input_field.text().strip())
    except ValueError:
        return None


def confirm_past_malote(
    parent: QWidget,
    malote: Malote,
    on_change: Optional[Callable[[], None]] = None,
) -> bool:
    dlg, layout = scaffold_dialog(parent, "Malote já enviado")
    layout.addSpacing(4)

    msg = QLabel(
        f"O malote {format_malote_date(malote)} já foi enviado. Continuar?"
    )
    msg.setWordWrap(True)
    c = colors()
    msg.setStyleSheet(f"color: {c['text_secondary']}; font-size: 13px;")
    layout.addWidget(msg)

    change = False

    def on_change_clicked():
        nonlocal change
        change = True
        dlg.reject()

    btn_row, [continue_btn, change_btn] = make_dialog_button_row([
        ("Continuar", "flat"),
        ("Trocar malote", "primary"),
    ])
    continue_btn.clicked.connect(dlg.accept)
    change_btn.clicked.connect(on_change_clicked)
    layout.addLayout(btn_row)

    if dlg.exec() == QDialog.DialogCode.Accepted:
        return True
    if change and on_change:
        on_change()
    return False


def delete_registro_with_undo(page, db, reg_id: int, on_refresh, on_error=None):
    if not confirm_delete_dialog(
        page, "Excluir Registro", "Esta ação não pode ser desfeita."
    ):
        return

    try:
        service = RegistroService(db)
        service.delete(reg_id)
        on_refresh()
        show_toast("Registro excluido", "info", page)
    except Exception as e:
        ErrorHandler.handle_error(e, context=ErrorContext.REGISTRY, show_dialog=False)
        if on_error:
            on_error(e)
        else:
            show_toast(f"Erro: {e}", "negative", page)
