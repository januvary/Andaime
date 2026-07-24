#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Holidays Dialog (Qt) — gerenciamento de feriados facultativos.

Port do _show_holidays_dialog do RAC: lista feriados do ano corrente
(combinando feriados fixos/nacionais via DateCalculator + facultativos do
data/pontos_facultativos.json) e permite adicionar/remover facultativos.
"""

from __future__ import annotations

import json
from datetime import date as date_cls
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emissor.ui_qt.theme import make_button


_DAY_NAMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def show_holidays_dialog(parent: QWidget) -> None:
    """
    Abre o diálogo de gerenciamento de feriados facultativos.

    Args:
        parent: Janela pai
    """
    from andaime.dates import DateCalculator
    from andaime.paths import get_root_directory

    pontos_path = get_root_directory() / "data" / "pontos_facultativos.json"
    pontos_data = _load_pontos(pontos_path)

    all_holidays: set[date_cls] = set(DateCalculator.get_holidays())
    year = date_cls.today().year

    pontos_set = _extract_pontos_dates(pontos_data)

    dlg = QDialog(parent)
    dlg.setWindowTitle("Feriados")
    dlg.setMinimumWidth(310)
    dlg.setMinimumHeight(420)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(False)
    tree.setIndentation(0)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    layout.addWidget(tree)

    def _populate_tree() -> None:
        tree.clear()
        for h in sorted(d for d in all_holidays if d.year == year):
            is_ponto = h in pontos_set
            text = f"{h.strftime('%d/%m')}  ({_DAY_NAMES[h.weekday()]})"
            if is_ponto:
                text += "  • facultativo"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, h)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, is_ponto)
            tree.addTopLevelItem(item)

    _populate_tree()

    btn_row = QHBoxLayout()
    add_btn = make_button("Adicionar", "primary")
    del_btn = make_button("Remover", "flat-fill")
    close_btn = make_button("Fechar", "flat-fill")
    btn_row.addWidget(add_btn)
    btn_row.addWidget(del_btn)
    btn_row.addStretch()
    btn_row.addWidget(close_btn)
    layout.addLayout(btn_row)

    def _on_add() -> None:
        result, ok = QInputDialog.getText(
            dlg, "Adicionar facultativo", f"dd/mm (ano {year})"
        )
        if not ok or not result.strip():
            return
        try:
            parts = result.strip().split("/")
            d, m = int(parts[0]), int(parts[1])
            new_date = date_cls(year, m, d)
        except (ValueError, IndexError):
            QMessageBox.warning(dlg, "Inválido", "Data inválida (use dd/mm)")
            return

        yr_str = str(year)
        entry = f"{int(parts[0]):02d}/{int(parts[1]):02d}"
        current = pontos_data.get(yr_str, [])
        if entry in current:
            QMessageBox.warning(dlg, "Duplicado", "Feriado facultativo já existe")
            return

        current.append(entry)
        current.sort(key=lambda x: (int(x.split("/")[1]), int(x.split("/")[0])))
        pontos_data[yr_str] = current
        _save_pontos(pontos_path, pontos_data)
        DateCalculator.clear_holidays_cache()
        all_holidays.add(new_date)
        pontos_set.add(new_date)
        _populate_tree()

    def _on_remove() -> None:
        item: QTreeWidgetItem | None = tree.currentItem()
        if item is None:
            return
        is_ponto = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not is_ponto:
            QMessageBox.warning(
                dlg,
                "Não removível",
                "Apenas feriados facultativos podem ser removidos",
            )
            return

        h: date_cls = item.data(0, Qt.ItemDataRole.UserRole)
        confirm = QMessageBox.question(
            dlg,
            "Remover facultativo",
            f'Remover "{h.strftime("%d/%m")}" dos facultativos?',
        )
        if confirm == QMessageBox.StandardButton.Yes:
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

    add_btn.clicked.connect(_on_add)
    del_btn.clicked.connect(_on_remove)
    close_btn.clicked.connect(dlg.accept)

    dlg.exec()


# ============================================================================
# Helpers de persistência (port do RAC)
# ============================================================================


def _load_pontos(path: Path) -> dict[str, Any]:
    """
    Carrega o dict de pontos facultativos do JSON.

    Args:
        path: Caminho do arquivo pontos_facultativos.json

    Returns:
        Dicionário {ano_str: [lista de "dd/mm"]}; vazio se inexistente/inválido
    """
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    result = data.get("pontos_facultativos", {})
    return result if isinstance(result, dict) else {}


def _extract_pontos_dates(pontos_data: dict[str, Any]) -> set[date_cls]:
    """
    Converte o dict de pontos facultativos em um conjunto de dates.

    Args:
        pontos_data: Dicionário {ano_str: [lista de "dd/mm"]}

    Returns:
        Conjunto de objetos date para cada entrada válida
    """
    result: set[date_cls] = set()
    for yr_str, plist in pontos_data.items():
        try:
            yr = int(yr_str)
        except ValueError:
            continue
        for ps in plist:
            try:
                d, m = map(int, ps.split("/"))
                result.add(date_cls(yr, m, d))
            except (ValueError, AttributeError):
                continue
    return result


def _save_pontos(path: Path, pontos_data: dict[str, Any]) -> None:
    """
    Persiste o dict de pontos facultativos em JSON.

    Args:
        path: Caminho do arquivo
        pontos_data: Dicionário {ano_str: [lista de "dd/mm"]}
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump({"pontos_facultativos": pontos_data}, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _remove_ponto(dt: date_cls, path: Path) -> None:
    """
    Remove um ponto facultativo específico do JSON.

    Args:
        dt: Data a remover
        path: Caminho do arquivo
    """
    data: dict[str, Any] = {"pontos_facultativos": {}}
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
    pontos = data.get("pontos_facultativos", {})
    yr_str = str(dt.year)
    entry = f"{dt.day:02d}/{dt.month:02d}"
    if yr_str in pontos and entry in pontos[yr_str]:
        pontos[yr_str].remove(entry)
    _save_pontos(path, pontos)
