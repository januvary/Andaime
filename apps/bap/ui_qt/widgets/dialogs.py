#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diálogos no padrão compartilhado (andaime.qt.dialogs).

Primitivas compartilhadas (RAC/Emissor/SS-54) vêm de ``andaime.qt.dialogs``;
apenas o seletor de lista ``pick_from_list`` é específico da SS-54.
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QLabel,
    QListWidget,
    QListWidgetItem,
)

from andaime.qt.dialogs import (  # noqa: F401
    confirm_dialog,
    make_dialog_button_row,
    open_input_dialog,
    scaffold_dialog,
)


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
        ("Cancelar", "flat"),
        (confirm_label, "primary"),
    ])
    cancel.clicked.connect(dlg.reject)
    selecionar.clicked.connect(_on_sel)
    layout.addLayout(btn_row)

    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return selected["data"]