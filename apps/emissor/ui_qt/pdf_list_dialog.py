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
    QDialog,
    QHBoxLayout,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emissor.utils.file_utils import open_file
from emissor.ui_qt.theme import make_button

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


class PdfPickerDialog(QDialog):
    """Diálogo com a lista de PDFs do paciente selecionado."""

    def __init__(
        self,
        parent: QWidget,
        patient_name: str,
        grupos: dict[str, list[Path]],
        palette: dict[str, str],
        highlight_date: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._palette = palette

        self.setWindowTitle("PDFs Salvos")
        self.setMinimumSize(240, 420)
        self.setStyleSheet(f"background-color: {palette['window_bg']};")

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        self.setLayout(layout)

        name_title = QLabel(patient_name)
        name_title.setWordWrap(True)
        name_title.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {palette['text']};"
        )
        layout.addWidget(name_title)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(14)
        self._tree.setAlternatingRowColors(True)
        self._tree.setColumnCount(1)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # QSS local vence o "font-size: 13px" global; +2px sobre a base.
        self._tree.setStyleSheet(
            f"QTreeWidget {{ font-size: 15px; color: {palette['text']}; }}"
        )
        layout.addWidget(self._tree)

        match = self._populate(grupos, highlight_date)
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top.text(0) == SCAN_GROUP:
                self._tree.collapseItem(top)
            else:
                top.setExpanded(True)
        if match is not None:
            parent = match.parent()
            if parent is not None:
                parent.setExpanded(True)
            self._tree.setCurrentItem(match)
            self._tree.scrollToItem(match)
        self._tree.itemDoubleClicked.connect(self._open_selected)

        btn_row = QHBoxLayout()
        close_btn = make_button("Fechar", "primary", self)
        close_btn.clicked.connect(self.reject)
        open_btn = make_button("Abrir", "flat-fill", self)
        open_btn.clicked.connect(self._open_selected)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        btn_row.addWidget(open_btn)
        layout.addLayout(btn_row)

    def _populate(
        self, grupos: dict[str, list[Path]], highlight_date: str | None = None
    ) -> QTreeWidgetItem | None:
        """Preenche a árvore e retorna o item cujo PDF casa com a data.

        ``highlight_date`` é a data da retirada atual (AAAA-MM-DD); o item do
        PDF com esse nome recebe destaque na abertura do diálogo.
        """
        match: QTreeWidgetItem | None = None
        for group_name, pdfs in grupos.items():
            group = QTreeWidgetItem([group_name])
            group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._tree.addTopLevelItem(group)
            for pdf in pdfs:
                item = QTreeWidgetItem([_display_name(pdf)])
                item.setData(0, Qt.ItemDataRole.UserRole, str(pdf))
                if highlight_date and pdf.stem[:10] == highlight_date:
                    match = item
                group.addChild(item)
        return match

    def _open_selected(self) -> None:
        """Abre o PDF do item selecionado (ignora itens de grupo)."""
        item: QTreeWidgetItem | None = self._tree.currentItem()
        if item is None:
            return
        pdf_path: Any = item.data(0, Qt.ItemDataRole.UserRole)
        if not pdf_path:
            return
        try:
            open_file(str(pdf_path))
        except (FileNotFoundError, OSError) as e:
            print(f"[ERRO] Falha ao abrir PDF: {e}")