#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared dialog primitives for andaime-based apps.

Provides a consistent dialog scaffold, button rows, and common dialog patterns
(confirm, prompt) built on the shared ``make_button`` and theme. App-specific
dialogs (those touching models/services) stay in the app and import these.

Roles used: ``flat`` (secondary/cancel), ``primary`` (confirm), ``negative``
(destructive). These map to ``QPushButton[class="..."]`` rules in the shared
theme, so buttons are styled consistently across RAC, Emissor and SS-54.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from andaime.qt.theme import colors, make_button

#: Sent to a prompt_dialog ``on_confirm`` to keep the dialog open on invalid input.
KEEP_OPEN = object()


def scaffold_dialog(
    parent: QWidget,
    title: str,
    *,
    spacing: int = 12,
    min_width: int = 340,
) -> tuple[QDialog, QVBoxLayout]:
    """Create a titled ``QDialog`` with a ``QVBoxLayout``.

    No heading label is added — the window title bar already shows ``title``,
    so an in-dialog heading would be redundant.
    """
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(min_width)
    layout = QVBoxLayout(dlg)
    layout.setSpacing(spacing)
    return dlg, layout


def make_dialog_button_row(
    actions: list[tuple[str, str]],
) -> tuple[QHBoxLayout, list[QPushButton]]:
    """Right-aligned dialog button row.

    ``actions`` is a list of ``(label, role)`` tuples, e.g.
    ``[("Cancelar", "flat"), ("Salvar", "primary")]``.
    """
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    buttons = []
    for label, role in actions:
        btn = make_button(label, role)
        btn_row.addWidget(btn)
        buttons.append(btn)
    return btn_row, buttons


def make_dialog_toolbar(
    left: list[tuple[str, str]] | None = None,
    right: list[tuple[str, str]] | None = None,
) -> tuple[QHBoxLayout, list[QPushButton]]:
    """Dialog button row with left-anchored and right-anchored actions split by
    a stretch — for dialogs with tool buttons."""
    bar = QHBoxLayout()
    buttons = []
    for label, role in (left or []):
        btn = make_button(label, role)
        bar.addWidget(btn)
        buttons.append(btn)
    bar.addStretch()
    for label, role in (right or []):
        btn = make_button(label, role)
        bar.addWidget(btn)
        buttons.append(btn)
    return bar, buttons


def make_message_label(text: str) -> QLabel:
    """Muted, word-wrapped body label used inside dialogs."""
    msg = QLabel(text)
    msg.setWordWrap(True)
    c = colors()
    msg.setStyleSheet(f"color: {c['text_secondary']}; font-size: 13px;")
    return msg


def confirm_dialog(
    parent: QWidget,
    title: str,
    message: str,
    confirm_label: str = "Confirmar",
    cancel_label: str = "Cancelar",
    *,
    danger: bool = False,
    cancel_role: str = "flat",
    min_width: int = 380,
) -> bool:
    """Two-button confirmation. Returns ``True`` if accepted.

    ``danger`` styles the confirm button with the ``negative`` (destructive)
    role instead of ``primary``.
    """
    dlg, layout = scaffold_dialog(parent, title, min_width=min_width)
    layout.addWidget(make_message_label(message))

    confirm_role = "negative" if danger else "primary"
    btn_row, [cancel, confirm] = make_dialog_button_row([
        (cancel_label, cancel_role),
        (confirm_label, confirm_role),
    ])
    cancel.clicked.connect(dlg.reject)
    confirm.clicked.connect(dlg.accept)
    layout.addLayout(btn_row)

    return dlg.exec() == QDialog.DialogCode.Accepted


def prompt_dialog(
    parent: QWidget,
    title: str,
    message: str = "",
    widget: QWidget | None = None,
    confirm_label: str = "Confirmar",
    on_confirm: Callable[[QWidget | None], Any] | None = None,
) -> Any:
    """Generic modal prompt: heading, optional message, one optional input
    widget, and right-aligned Cancel/Confirm.

    ``on_confirm(widget)`` runs on Confirm. Return ``KEEP_OPEN`` (after showing
    feedback) to keep the dialog open on invalid input; return anything else
    (including ``None``) to close — that value becomes the dialog's result.
    Cancelling returns ``None``. A ``QLineEdit`` inside ``widget`` is wired so
    Enter confirms.
    """
    dlg, layout = scaffold_dialog(parent, title, spacing=16)
    layout.addSpacing(4)

    if message:
        layout.addWidget(make_message_label(message))
        layout.addSpacing(4)
    if widget is not None:
        layout.addWidget(widget)

    btn_row, [cancel, confirm] = make_dialog_button_row([
        ("Cancelar", "flat"),
        (confirm_label, "primary"),
    ])
    cancel.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    result: list[Any] = []

    def on_confirm_clicked():
        value = on_confirm(widget) if on_confirm else None
        if value is KEEP_OPEN:
            return
        result.append(value)
        dlg.accept()

    confirm.clicked.connect(on_confirm_clicked)
    if widget is not None:
        enter_widget = widget if isinstance(widget, QLineEdit) else widget.findChild(QLineEdit)
        if enter_widget is not None:
            enter_widget.returnPressed.connect(on_confirm_clicked)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return result[0] if result else None
