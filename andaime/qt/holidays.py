#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared holidays dialog — manage pontos facultativos across years."""

from __future__ import annotations

from datetime import date as date_cls
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from andaime.dates import DateCalculator, parse_date
from andaime.paths import get_root_directory
from andaime.pontos import PontosStore
from andaime.qt.dialogs import (
    KEEP_OPEN,
    confirm_dialog,
    make_dialog_toolbar,
    prompt_dialog,
    scaffold_dialog,
)
from andaime.qt.widgets import DateLineEdit

_DAY_NAMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

_NATIONAL_HOLIDAYS_WARNING = (
    "Este feriado é nacional/fixo e não pode ser removido.\n"
    "Apenas feriados facultativos gerenciados pelo sistema são removíveis."
)


def _pontos_path() -> Path:
    """Return the canonical path to ``pontos_facultativos.json``."""
    return get_root_directory() / "data" / "pontos_facultativos.json"


def show_holidays_dialog(
    parent: QWidget,
    *,
    year: int | None = None,
) -> None:
    """Open the shared holidays management dialog.

    Args:
        parent: Parent widget.
        year: Year to show initially.  Defaults to the current year.
    """
    from PySide6.QtWidgets import QSpinBox

    store = PontosStore(_pontos_path())
    pontos_set: set[date_cls] = store.get_all_dates()

    current_year = year or date_cls.today().year

    dlg, layout = scaffold_dialog(parent, "Feriados", spacing=12, min_width=340)
    dlg.setMinimumHeight(480)

    # === Year selector ===
    year_row = QHBoxLayout()
    year_row.setSpacing(8)
    year_row.addWidget(QLabel("Ano:"))
    year_spin = QSpinBox()
    year_spin.setRange(2020, 2099)
    year_spin.setValue(current_year)
    year_spin.setFixedWidth(80)
    year_row.addWidget(year_spin)
    year_row.addStretch()
    layout.addLayout(year_row)

    # === Tree ===
    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(True)
    tree.setAnimated(True)
    tree.setIndentation(0)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    layout.addWidget(tree)

    def _refresh_holidays() -> set[date_cls]:
        """Re-fetch the full holiday set (national + pontos) from cache."""
        return set(DateCalculator.get_holidays())

    all_holidays = _refresh_holidays()

    def _populate_tree() -> None:
        """Rebuild the tree for the currently selected year."""
        tree.clear()
        yr = year_spin.value()
        yr_holidays = sorted(h for h in all_holidays if h.year == yr)
        for h in yr_holidays:
            is_ponto = h in pontos_set
            dn = _DAY_NAMES[h.weekday()]
            text = f"    {h.strftime('%d/%m')}  ({dn})"
            if is_ponto:
                text += "  \u2022 facultativo"
            item = QTreeWidgetItem([text])
            item.setData(0, Qt.ItemDataRole.UserRole, h)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, is_ponto)
            tree.addTopLevelItem(item)

    _populate_tree()

    year_spin.valueChanged.connect(lambda _val: _populate_tree())

    # === Double-click to edit facultativo ===
    def _on_edit_ponto(old_date: date_cls) -> None:
        """Open a prompt dialog to edit a facultativo date."""
        date_input = DateLineEdit()
        date_input.setPlaceholderText("dd/mm")
        date_input.setText(old_date.strftime("%d/%m/%Y"))
        date_input.selectAll()

        def _on_confirm(input_field: DateLineEdit) -> str | None:
            parsed = parse_date(input_field.text())
            if not parsed:
                QMessageBox.warning(dlg, "Inválido", "Data inválida (use dd/mm)")
                return KEEP_OPEN
            new_date = parsed
            if new_date == old_date:
                return None

            # Can't move to a national holiday slot
            if new_date in all_holidays and new_date not in pontos_set:
                QMessageBox.warning(
                    dlg,
                    "Feriado nacional",
                    f"{new_date.strftime('%d/%m')} já é feriado nacional/fixo.",
                )
                return KEEP_OPEN

            # Check duplicate
            if new_date in pontos_set:
                QMessageBox.warning(
                    dlg,
                    "Duplicado",
                    "Já existe um facultativo nesta data",
                )
                return KEEP_OPEN

            # Swap: remove old, add new
            store.remove(old_date)
            pontos_set.discard(old_date)
            store.add(new_date.year, new_date.month, new_date.day)
            pontos_set.add(new_date)
            store.save()
            DateCalculator.clear_holidays_cache()
            all_holidays.clear()
            all_holidays.update(_refresh_holidays())
            _populate_tree()
            return None

        prompt_dialog(
            dlg,
            "Editar facultativo",
            widget=date_input,
            confirm_label="Salvar",
            on_confirm=_on_confirm,
        )

    def _on_tree_double_clicked(item: QTreeWidgetItem, column: int) -> None:
        is_ponto = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not is_ponto:
            return
        old_date: date_cls = item.data(0, Qt.ItemDataRole.UserRole)
        _on_edit_ponto(old_date)

    tree.itemDoubleClicked.connect(_on_tree_double_clicked)

    # === Buttons ===
    btn_row, [add_btn, del_btn, close_btn] = make_dialog_toolbar(
        left=[("Adicionar", "primary"), ("Remover", "negative")],
        right=[("Fechar", "flat")],
    )

    def _on_add() -> None:
        yr = year_spin.value()
        date_input = DateLineEdit()
        date_input.setPlaceholderText(f"dd/mm (ano {yr})")

        def _on_confirm_add(input_field: DateLineEdit) -> str | None:
            parsed = parse_date(input_field.text())
            if not parsed:
                QMessageBox.warning(dlg, "Inválido", "Data inválida (use dd/mm)")
                return KEEP_OPEN
            new_date = parsed

            # Block adding on national holidays
            if new_date in all_holidays and new_date not in pontos_set:
                QMessageBox.warning(
                    dlg,
                    "Feriado nacional",
                    f"{new_date.strftime('%d/%m')} é feriado nacional/fixo.\n"
                    "Não é possível adicioná-lo como facultativo.",
                )
                return KEEP_OPEN

            status = store.add(new_date.year, new_date.month, new_date.day)
            if status == "duplicate":
                QMessageBox.warning(
                    dlg, "Duplicado", "Feriado facultativo já existe"
                )
                return KEEP_OPEN
            if status == "invalid":
                QMessageBox.warning(dlg, "Inválido", "Data inválida")
                return KEEP_OPEN

            store.save()
            DateCalculator.clear_holidays_cache()
            pontos_set.add(new_date)
            all_holidays.clear()
            all_holidays.update(_refresh_holidays())
            _populate_tree()
            return None

        prompt_dialog(
            dlg,
            "Adicionar facultativo",
            widget=date_input,
            confirm_label="Adicionar",
            on_confirm=_on_confirm_add,
        )

    def _on_remove() -> None:
        item = tree.currentItem()
        if item is None:
            return
        is_ponto = item.data(0, Qt.ItemDataRole.UserRole + 1)
        if not is_ponto:
            QMessageBox.warning(dlg, "Não removível", _NATIONAL_HOLIDAYS_WARNING)
            return

        h: date_cls = item.data(0, Qt.ItemDataRole.UserRole)
        if not confirm_dialog(
            dlg,
            "Remover facultativo",
            f'Remover "{h.strftime("%d/%m")}" dos facultativos?',
            confirm_label="Remover",
            danger=True,
        ):
            return

        store.remove(h)
        store.save()
        DateCalculator.clear_holidays_cache()
        pontos_set.discard(h)
        all_holidays.clear()
        all_holidays.update(_refresh_holidays())
        _populate_tree()

    add_btn.clicked.connect(_on_add)
    del_btn.clicked.connect(_on_remove)
    close_btn.clicked.connect(dlg.accept)

    layout.addLayout(btn_row)
    dlg.exec()
