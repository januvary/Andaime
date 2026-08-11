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
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
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
    no_close_button: bool = False,
) -> bool:
    """Two-button confirmation. Returns ``True`` if accepted.

    ``danger`` styles the confirm button with the ``negative`` (destructive)
    role instead of ``primary``. ``no_close_button`` hides the window's close
    (X) button and disables Esc, forcing an explicit choice — used for
    high-stakes confirmations.
    """
    dlg, layout = scaffold_dialog(parent, title, min_width=min_width)
    if no_close_button:
        dlg.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
        )
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


def open_input_dialog(
    parent: QWidget,
    title: str,
    placeholder: str = "",
    initial: str = "",
    confirm_label: str = "Confirmar",
    *,
    multiline: bool = False,
    min_height: int = 220,
) -> str | None:
    """Single-line (``QLineEdit``) or multi-line (``QTextEdit``) text prompt.

    Returns the trimmed text when accepted, or ``None`` on cancel. Multi-line
    mode grows the dialog and is meant for longer free-form text (observations).
    """
    dlg, layout = scaffold_dialog(parent, title, spacing=16)
    layout.addSpacing(4)

    if multiline:
        input_field = QTextEdit()
        input_field.setPlaceholderText(placeholder)
        input_field.setPlainText(initial)
        input_field.setAcceptRichText(False)
        dlg.setMinimumHeight(min_height)
        layout.addWidget(input_field, stretch=1)
    else:
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

    if not multiline:
        input_field.returnPressed.connect(dlg.accept)
    confirm.clicked.connect(dlg.accept)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    if multiline:
        text = input_field.toPlainText().strip()
    else:
        text = input_field.text().strip()
    return text or None


class QtConfigDialog(QDialog):
    """Shared settings dialog: a save-location row plus app-specific middle
    content and a ``Resetar Padrão | [center action] | Salvar`` button row.

    Ownership split: this class owns the scaffold, the location row (label,
    ``QLineEdit``, browse button) and the button row; the app supplies the
    middle content and the behaviours via hooks.

    ``on_save(location)`` returns the ``result_data`` dict on success, or
    ``None`` after showing its own error message (keeping the dialog open).
    ``on_reset()`` runs after the location field is reset to ``reset_location``
    (so the app can also reset its middle custom controls).
    """

    def __init__(
        self,
        parent: QWidget | None,
        *,
        initial_location: str,
        reset_location: str,
        on_save: Callable[[str], dict[str, Any] | None],
        location_label: str = "Local de salvamento:",
        center_label: str | None = None,
        center_callback: Callable | None = None,
        middle: QWidget | None = None,
        on_reset: Callable | None = None,
        title: str = "Configurações",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)

        self.result_data: dict[str, Any] | None = None
        self._on_save = on_save
        self._on_reset = on_reset

        self._location_edit = QLineEdit(initial_location)
        self._location_edit.setMinimumWidth(280)

        self._build_ui(
            location_label=location_label,
            center_label=center_label,
            center_callback=center_callback,
            middle=middle,
            reset_location=reset_location,
        )

    # ========== UI ==========

    def _build_ui(
        self,
        *,
        location_label: str,
        center_label: str | None,
        center_callback: Callable | None,
        middle: QWidget | None,
        reset_location: str,
    ) -> None:
        layout = QVBoxLayout(self)
        # Fixa o tamanho ao conteúdo (não redimensionável) — espelha os apps.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(22)

        # === Local de salvamento ===
        row = QGridLayout()
        row.setHorizontalSpacing(20)
        row.setVerticalSpacing(5)
        row.setColumnStretch(1, 3)

        row.addWidget(QLabel(location_label), 0, 1)

        loc_container = QWidget()
        loc_row = QHBoxLayout(loc_container)
        loc_row.setContentsMargins(0, 0, 0, 0)
        loc_row.setSpacing(6)
        loc_row.addWidget(self._location_edit, stretch=1)
        browse_btn = make_button("Procurar...", "flat", loc_container)
        browse_btn.clicked.connect(self._browse_location)
        loc_row.addWidget(browse_btn)
        row.addWidget(loc_container, 1, 1)

        layout.addLayout(row)

        # === Conteúdo intermediário específico do app ===
        if middle is not None:
            layout.addWidget(middle)

        # === Botões ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        reset_btn = make_button("Resetar Padrão", "flat", self)
        reset_btn.clicked.connect(lambda: self._reset(reset_location))
        btn_row.addWidget(reset_btn)

        btn_row.addStretch(1)

        if center_label is not None:
            center_btn = make_button(center_label, "flat", self)
            if center_callback is not None:
                center_btn.clicked.connect(center_callback)
            btn_row.addWidget(center_btn)
            btn_row.addStretch(1)

        save_btn = make_button("Salvar", "primary", self)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    # ========== Handlers ==========

    def _browse_location(self) -> None:
        """Abre seletor de diretório para o local de salvamento."""
        current = self._location_edit.text()
        path = QFileDialog.getExistingDirectory(
            self, "Selecionar local de salvamento", current
        )
        if path:
            self._location_edit.setText(path)

    def _reset(self, reset_location: str) -> None:
        """Restaura o local de salvamento (e o middle, via on_reset)."""
        self._location_edit.setText(reset_location)
        if self._on_reset is not None:
            self._on_reset()

    def _save(self) -> None:
        """Delega a construção do resultado ao app; aceita se retornar dict."""
        location_str = self._location_edit.text().strip()
        if not location_str:
            QMessageBox.warning(
                self, "Inválido", "O local de salvamento é obrigatório."
            )
            return
        result = self._on_save(location_str)
        if result is None:
            return
        self.result_data = result
        self.accept()
