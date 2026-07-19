#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diálogos no padrão do RAC (QDialog custom com HeadingLabel + botões flat/primary)."""

from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QTextEdit,
    QDialog,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
)

from src.ui_qt.widgets.buttons import make_button


def pick_from_list(
    parent: QWidget,
    title: str,
    items: Sequence,
    formatter: "Callable[[object], tuple[str, object]]",
    *,
    hint: str = "",
    confirm_label: str = "Selecionar",
    min_width: int = 420,
    max_height: int = 320,
) -> object | None:
    """Abre um diálogo "escolha um de uma lista".

    ``formatter(item)`` devolve ``(rótulo, dado)``; o ``dado`` é retornado
    quando o usuário confirma (duplo-clique ou botão). ``None`` se cancelar
    ou nada estiver selecionado. Compartilhado por seletores da RemessasPage
    (lote/processo) que eram quase idênticos.
    """
    dlg, layout = scaffold_dialog(parent, title, spacing=12, min_width=min_width)

    if hint:
        hint_lbl = QLabel(hint)
        hint_lbl.setWordWrap(True)
        layout.addWidget(hint_lbl)

    list_widget = QListWidget()
    list_widget.setProperty("class", "remessa-tree")
    list_widget.setAlternatingRowColors(True)
    list_widget.setMaximumHeight(max_height)
    for item in items:
        label, data = formatter(item)
        lw_item = QListWidgetItem(label)
        lw_item.setData(Qt.ItemDataRole.UserRole, data)
        list_widget.addItem(lw_item)
    layout.addWidget(list_widget)

    selected = {"data": None}

    def _on_dbl(lw_item):
        selected["data"] = lw_item.data(Qt.ItemDataRole.UserRole)
        dlg.accept()

    def _on_sel():
        cur = list_widget.currentItem()
        if cur is not None:
            selected["data"] = cur.data(Qt.ItemDataRole.UserRole)
        dlg.accept()

    list_widget.itemDoubleClicked.connect(_on_dbl)
    btn_row, [cancel, selecionar] = make_dialog_button_row([
        ("Cancelar", "flat-fill"),
        (confirm_label, "primary"),
    ])
    cancel.clicked.connect(dlg.reject)
    selecionar.clicked.connect(_on_sel)
    layout.addLayout(btn_row)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return selected["data"]


def confirm_dialog(
    parent: QWidget,
    title: str,
    message: str,
    confirm_label: str = "Confirmar",
    cancel_label: str = "Cancelar",
    *,
    danger: bool = False,
    cancel_role: str = "flat-fill",
    modal: bool = False,
    min_width: int = 380,
) -> bool:
    """Diálogo de confirmação de dois botões. Retorna ``True`` se aceito.

    ``danger`` usa o papel vermelho no botão de confirmação; ``cancel_role``
    define o papel do cancelar; ``modal=True`` bloqueia a aplicação.
    """
    dlg, layout = scaffold_dialog(parent, title, min_width=min_width)
    dlg.setMinimumHeight(160)
    if modal:
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)

    label = QLabel(message)
    label.setWordWrap(True)
    layout.addWidget(label)

    confirm_role = "danger" if danger else "primary"
    btn_row, [cancel, confirm] = make_dialog_button_row([
        (cancel_label, cancel_role),
        (confirm_label, confirm_role),
    ])
    cancel.clicked.connect(dlg.reject)
    confirm.clicked.connect(dlg.accept)
    layout.addLayout(btn_row)

    return dlg.exec() == QDialog.DialogCode.Accepted


def scaffold_dialog(parent, title, spacing=12, min_width=340):
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumWidth(min_width)
    layout = QVBoxLayout(dlg)
    layout.setSpacing(spacing)
    return dlg, layout


def make_dialog_button_row(
    actions: list[tuple[str, str]]
) -> tuple[QHBoxLayout, list[QPushButton]]:
    btn_row = QHBoxLayout()
    btn_row.addStretch()
    buttons = []
    for label, role in actions:
        btn = make_button(label, role)
        btn_row.addWidget(btn)
        buttons.append(btn)
    return btn_row, buttons


def open_input_dialog(
    parent: QWidget,
    title: str,
    placeholder: str = "",
    initial: str = "",
    confirm_label: str = "Confirmar",
    multiline: bool = False,
    min_height: int = 220,
) -> str | None:
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
        ("Cancelar", "flat-fill"),
        (confirm_label, "primary"),
    ])
    cancel.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    if not multiline:
        input_field.returnPressed.connect(dlg.accept)
    confirm.clicked.connect(dlg.accept)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    text = (
        input_field.toPlainText() if multiline else input_field.text()
    ).strip()
    return text or None
