#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from contextlib import suppress
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

# Shared primitives (from andaime.qt.dialogs) — re-exported so existing
# intra-project importers keep working. App-specific dialogs below build on them.
from andaime.qt.dialogs import (  # noqa: F401
    KEEP_OPEN,
    confirm_dialog,
    make_dialog_button_row,
    make_dialog_toolbar,
    make_message_label,
    prompt_dialog,
    scaffold_dialog,
)
from andaime.error_handler import ErrorContext, ErrorHandler
from rac.gui.widgets._completer import themed_combo
from rac.gui.widgets.toast import show_toast
from rac.services.registro_service import RegistroService
from rac.models import Malote
from rac.utils.text_utils import format_malote_date


def confirm_delete_dialog(
    parent: QWidget,
    title: str,
    message: str,
    destructive_label: str = "Excluir",
) -> bool:
    return confirm_dialog(
        parent, title, message, confirm_label=destructive_label, danger=True
    )


def open_select_dialog(
    parent: QWidget,
    title: str,
    placeholder: str,
    options: list[str],
    initial: str | None = None,
    confirm_label: str = "Confirmar",
) -> str | None:
    combo = themed_combo()
    combo.addItems(options)
    if initial:
        idx = combo.findText(initial)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def on_confirm(field) -> str | None:
        selected = field.currentText().strip()
        return selected.split(" - ")[0] if " - " in selected else selected

    return prompt_dialog(
        parent,
        title,
        widget=combo,
        confirm_label=confirm_label,
        on_confirm=on_confirm,
    )


def open_input_dialog(
    parent: QWidget,
    title: str,
    placeholder: str,
    initial: str = "",
    confirm_label: str = "Confirmar",
) -> str | None:
    input_field = QLineEdit()
    input_field.setPlaceholderText(placeholder)
    input_field.setText(initial)
    if initial:
        input_field.selectAll()

    def on_confirm(field: QLineEdit) -> str | None:
        return field.text().strip() or None

    return prompt_dialog(
        parent,
        title,
        widget=input_field,
        confirm_label=confirm_label,
        on_confirm=on_confirm,
    )


def open_estoque_dialog(
    parent: QWidget,
    title: str,
    initial_value: int,
) -> int | None:
    from andaime.qt.theme import make_button

    def step_field(field: QLineEdit, delta: int):
        with suppress(ValueError):
            current = int(field.text())
            field.setText(str(max(0, current + delta)))
            field.selectAll()

    input_field = QLineEdit()
    input_field.setFixedSize(100, 48)
    input_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
    input_field.setText(str(initial_value))
    input_field.selectAll()

    input_row = QHBoxLayout()
    input_row.setSpacing(4)
    input_row.addStretch()
    for delta in (-60, -30, -1):
        btn = make_button(f"{delta:+d}", "stepper")
        btn.setFixedSize(48, 48)
        btn.clicked.connect(lambda _, d=delta: step_field(input_field, d))
        input_row.addWidget(btn)
    input_row.addWidget(input_field)
    for delta in (1, 30, 60):
        btn = make_button(f"{delta:+d}", "stepper")
        btn.setFixedSize(48, 48)
        btn.clicked.connect(lambda _, d=delta: step_field(input_field, d))
        input_row.addWidget(btn)
    input_row.addStretch()

    holder = QWidget()
    holder.setLayout(input_row)

    def on_confirm(field: QWidget) -> int | None:
        line_edit = field.findChild(QLineEdit)
        if line_edit is None:
            return None
        try:
            return int(line_edit.text().strip())
        except ValueError:
            return None

    return prompt_dialog(parent, title, widget=holder, on_confirm=on_confirm)


class MaloteDecision(Enum):
    """Outcome of the 'malote already sent' confirmation."""

    CONTINUE = "continue"
    CHANGE = "change"
    CANCEL = "cancel"


def confirm_past_malote(
    parent: QWidget,
    malote: Malote,
) -> MaloteDecision:
    from andaime.qt.dialogs import scaffold_dialog

    dlg, layout = scaffold_dialog(parent, "Malote já enviado")
    layout.addSpacing(4)
    layout.addWidget(make_message_label(
        f"O malote {format_malote_date(malote)} já foi enviado. Continuar?"
    ))

    choice: list[MaloteDecision] = []

    def choose(value: MaloteDecision):
        choice.append(value)
        dlg.accept()

    btn_row, [continue_btn, change_btn] = make_dialog_button_row([
        ("Continuar", "flat"),
        ("Trocar malote", "primary"),
    ])
    continue_btn.clicked.connect(lambda: choose(MaloteDecision.CONTINUE))
    change_btn.clicked.connect(lambda: choose(MaloteDecision.CHANGE))
    layout.addLayout(btn_row)

    dlg.exec()
    return choice[0] if choice else MaloteDecision.CANCEL


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
