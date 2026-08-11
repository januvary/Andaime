#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PdfPickerDialog (Qt) — lista os PDFs da pasta do paciente.

Exibe em um grupo os recibos assinados (digitalizações) e em outro os
recibos gerados, ordenados do mais recente para o mais antigo. O usuário
abre um PDF com duplo clique ou selecionando e clicando em "Abrir".
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from andaime.qt.dialogs import (
    make_dialog_toolbar,
    scaffold_dialog,
)

from emissor.utils.file_utils import open_file

SCAN_SUBFOLDER = "RECIBOS ASSINADOS"
SCAN_GROUP = "Recibos assinados"
MAIN_GROUP = "Recibos"


def _sort_key(path: Path) -> tuple[str, Path]:
    """Ordena por data (nome) e, em empate, pelo nome completo."""
    return (path.stem[:10], path)


def _display_name(path: Path) -> str:
    """Converte o nome do arquivo em um rótulo legível (dd/mm/aaaa)."""
    stem = path.stem
    try:
        dt = datetime.strptime(stem[:10], "%Y-%m-%d")
        return f"{dt.strftime('%d/%m/%Y')}{stem[10:]}"
    except ValueError:
        return stem


def collect_patient_pdfs(archive_dir: Path) -> dict[str, list[Path]]:
    """Coleta os PDFs do paciente agrupados, mais recentes primeiro.

    O grupo de recibos assinados (subpasta) aparece à frente dos recibos
    gerados na pasta principal. Grupos vazios são omitidos.
    """
    grupos: dict[str, list[Path]] = {}

    scan_dir = archive_dir / SCAN_SUBFOLDER
    if scan_dir.is_dir():
        scanned = sorted(scan_dir.glob("*.pdf"), key=_sort_key, reverse=True)
        if scanned:
            grupos[SCAN_GROUP] = scanned

    main = sorted(archive_dir.glob("*.pdf"), key=_sort_key, reverse=True)
    if main:
        grupos[MAIN_GROUP] = main

    return grupos


def show_pdf_picker_dialog(
    parent: QWidget,
    patient_name: str,
    grupos: dict[str, list[Path]],
    palette: dict[str, str],
    highlight_date: str | None = None,
) -> None:
    """Abre o diálogo com a lista de PDFs do paciente selecionado."""
    dlg, layout = scaffold_dialog(parent, "PDFs Salvos", spacing=12, min_width=280)
    dlg.setMinimumHeight(420)

    name_title = QLabel(patient_name)
    name_title.setWordWrap(True)
    name_title.setStyleSheet(
        f"font-size: 15px; font-weight: 600; color: {palette['text']};"
    )
    layout.addWidget(name_title)

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(True)
    tree.setIndentation(14)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    tree.setStyleSheet(
        f"QTreeWidget {{ font-size: 15px; color: {palette['text']}; }}"
    )
    layout.addWidget(tree)

    match = _populate_tree(tree, grupos, highlight_date)
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if top.text(0) == SCAN_GROUP:
            tree.collapseItem(top)
        else:
            top.setExpanded(True)
    if match is not None:
        parent_item = match.parent()
        if parent_item is not None:
            parent_item.setExpanded(True)
        tree.setCurrentItem(match)
        tree.scrollToItem(match)

    btn_row, [open_btn, close_btn] = make_dialog_toolbar(
        left=[("Abrir", "primary")],
        right=[("Fechar", "flat")],
    )
    tree.itemDoubleClicked.connect(lambda _item=None: _open_selected(tree))
    open_btn.clicked.connect(lambda: _open_selected(tree))
    close_btn.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    dlg.exec()


def _populate_tree(
    tree: QTreeWidget,
    grupos: dict[str, list[Path]],
    highlight_date: str | None = None,
) -> QTreeWidgetItem | None:
    """Preenche a árvore e retorna o item cujo PDF casa com a data."""
    match: QTreeWidgetItem | None = None
    for group_name, pdfs in grupos.items():
        group = QTreeWidgetItem([group_name])
        group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        tree.addTopLevelItem(group)
        for pdf in pdfs:
            item = QTreeWidgetItem([_display_name(pdf)])
            item.setData(0, Qt.ItemDataRole.UserRole, str(pdf))
            if highlight_date and pdf.stem[:10] == highlight_date:
                match = item
            group.addChild(item)
    return match


def _open_selected(tree: QTreeWidget) -> None:
    """Abre o PDF do item selecionado (ignora itens de grupo)."""
    item: QTreeWidgetItem | None = tree.currentItem()
    if item is None:
        return
    pdf_path: Any = item.data(0, Qt.ItemDataRole.UserRole)
    if not pdf_path:
        return
    try:
        open_file(str(pdf_path))
    except (FileNotFoundError, OSError) as e:
        print(f"[ERRO] Falha ao abrir PDF: {e}")