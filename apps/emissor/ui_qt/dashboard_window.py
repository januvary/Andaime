#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DashboardWindow — Visualizador de banco de dados (Qt).

Janela interna do Emissor. Usa DashboardService com conexões de curta
duração (não fecha o banco principal da aplicação).
"""

from __future__ import annotations

import sqlite3
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from emissor.services.dashboard_service import DashboardService
from emissor.ui_qt.theme import get_palette, make_button
from emissor.utils.masks import apply_mask_for_field
from andaime.qt.table import table_batch_populate


class _AddRecordDialog(QDialog):
    """Diálogo para inserir um novo registro."""

    def __init__(
        self,
        parent: QWidget,
        table_name: str,
        editable_columns: list[tuple],
        palette: dict[str, str],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Adicionar em {table_name}")
        self.setMinimumWidth(420)
        self._inputs: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        form = QFormLayout()
        form.setSpacing(8)
        for col_info in editable_columns:
            col_name = col_info[1]
            entry = QLineEdit()
            entry.setPlaceholderText(col_name)
            form.addRow(f"{col_name}:", entry)
            self._inputs[col_name] = entry
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = make_button("Cancelar", "flat-fill", self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = make_button("Adicionar", "primary", self)
        ok_btn.clicked.connect(self.accept)
        ok_btn.setDefault(True)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        if self._inputs:
            next(iter(self._inputs.values())).setFocus()

    def values(self) -> dict[str, Any]:
        """Retorna {coluna: valor} (None se vazio)."""
        result: dict[str, Any] = {}
        for col_name, entry in self._inputs.items():
            text = entry.text().strip()
            result[col_name] = text if text else None
        return result


class DashboardWindow(QMainWindow):
    """Janela principal do Dashboard interno."""

    def __init__(
        self,
        parent: QWidget | None,
        config_manager: Any,
    ) -> None:
        super().__init__(parent)
        self._config_manager = config_manager
        self.setWindowTitle("Dashboard - Banco de Dados")
        self.setMinimumSize(1000, 700)
        # Janela independente (não fica presa atrás de diálogos modais)
        self.setWindowFlag(Qt.WindowType.Window, True)

        dark_mode = bool(self._config_manager.get("dark_mode", True))
        self._palette = get_palette(dark_mode)

        self._service = DashboardService()
        self._db_paths: dict[str, Any] = {}
        self._current_db = "emissor"
        self._current_table: str | None = None
        self._sort_column: int | None = None
        self._sort_order = Qt.SortOrder.AscendingOrder

        self._column_names: list[str] = []
        self._pk_columns: list[str] = []
        # row_key (str) -> {pk_col: value}
        self._pk_values: dict[str, dict[str, Any]] = {}
        # row_key -> {col_name: original_value}
        self._original_values: dict[str, dict[str, Any]] = {}
        # row_key -> {col_name: new_value}
        self._unsaved_changes: dict[str, dict[str, Any]] = {}

        self._db_buttons: dict[str, QPushButton] = {}
        self._table_buttons: dict[str, QPushButton] = {}
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._execute_search)

        self._setup_ui()
        self._connect_databases()

    # ------------------------------------------------------------------ UI

    def _setup_ui(self) -> None:
        """Monta a interface: sidebar + área principal."""
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main(), stretch=1)

    def _build_sidebar(self) -> QWidget:
        """Constrói a barra lateral (bancos + tabelas)."""
        sidebar = QFrame()
        sidebar.setProperty("class", "panel")
        sidebar.setFixedWidth(240)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(8)

        db_label = QLabel("Database")
        db_label.setProperty("class", "panel-title")
        layout.addWidget(db_label)

        for db_name in ("emissor", "medications"):
            btn = make_button(db_name.capitalize(), "flat-fill", sidebar)
            btn.clicked.connect(
                lambda checked=False, d=db_name: self._switch_database(d)
            )
            layout.addWidget(btn)
            self._db_buttons[db_name] = btn

        tables_label = QLabel("Tabelas")
        tables_label.setProperty("class", "panel-title")
        layout.addWidget(tables_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._tables_container = QWidget()
        self._tables_layout = QVBoxLayout(self._tables_container)
        self._tables_layout.setContentsMargins(0, 0, 0, 0)
        self._tables_layout.setSpacing(4)
        self._tables_layout.addStretch()
        scroll.setWidget(self._tables_container)
        layout.addWidget(scroll, stretch=1)

        return sidebar

    def _build_main(self) -> QWidget:
        """Constrói a área principal (busca + tabela)."""
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)

        search_label = QLabel("Buscar:")
        search_row.addWidget(search_label)

        self._search_entry = QLineEdit()
        self._search_entry.setPlaceholderText("Digite para filtrar...")
        self._search_entry.textChanged.connect(self._on_search)
        search_row.addWidget(self._search_entry, stretch=1)

        self._add_button = make_button("Adicionar", "flat-fill", main)
        self._add_button.setEnabled(False)
        self._add_button.clicked.connect(self._add_record)
        search_row.addWidget(self._add_button)

        self._delete_button = make_button("Excluir", "flat-fill", main)
        self._delete_button.setEnabled(False)
        self._delete_button.clicked.connect(self._delete_record)
        search_row.addWidget(self._delete_button)

        self._save_button = make_button("Salvar (0)", "primary", main)
        self._save_button.clicked.connect(self._save_changes)
        search_row.addWidget(self._save_button)

        layout.addLayout(search_row)

        self._table = QTableWidget()
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self._table.setAlternatingRowColors(True)
        self._table.setSortingEnabled(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.verticalHeader().setVisible(False)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, stretch=1)

        return main

    # ----------------------------------------------------------- data/load

    def _connect_databases(self) -> None:
        """Registra caminhos dos bancos e popula a sidebar."""
        self._db_paths = self._service.connect_databases()
        if self._current_db not in self._db_paths and self._db_paths:
            self._current_db = next(iter(self._db_paths))
        self._update_db_buttons()
        self._populate_table_list()

    def _update_db_buttons(self) -> None:
        """Destaca o banco ativo."""
        for db_name, btn in self._db_buttons.items():
            available = db_name in self._db_paths
            btn.setEnabled(available)
            if db_name == self._current_db and available:
                btn.setProperty("class", "primary")
            else:
                btn.setProperty("class", "flat-fill")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _switch_database(self, db_name: str) -> None:
        """Troca o banco ativo."""
        if db_name not in self._db_paths:
            QMessageBox.critical(
                self, "Erro", f"Banco de dados '{db_name}' não disponível."
            )
            return
        if self._unsaved_changes:
            reply = QMessageBox.question(
                self,
                "Alterações não salvas",
                "Há alterações não salvas. Trocar de banco mesmo assim?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._current_db = db_name
        self._current_table = None
        self._unsaved_changes.clear()
        self._update_save_button()
        self._update_db_buttons()
        self._table.clear()
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._add_button.setEnabled(False)
        self._delete_button.setEnabled(False)
        self._populate_table_list()

    def _update_table_buttons(self) -> None:
        """Destaca o botão da tabela selecionada."""
        for table_name, btn in self._table_buttons.items():
            btn.setProperty(
                "class", "primary" if table_name == self._current_table else ""
            )
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _populate_table_list(self) -> None:
        """Preenche a lista de tabelas na sidebar."""
        while self._tables_layout.count() > 1:
            item = self._tables_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._table_buttons.clear()

        if self._current_db not in self._db_paths:
            return

        for table_name, count in self._service.get_tables(self._current_db):
            btn = make_button(f"{table_name}\n({count} rows)", "flat-fill", self)
            btn.setMinimumHeight(44)
            btn.clicked.connect(
                lambda checked=False, t=table_name: self._select_table(t)
            )
            self._tables_layout.insertWidget(self._tables_layout.count() - 1, btn)
            self._table_buttons[table_name] = btn

        self._update_table_buttons()

    def _select_table(self, table_name: str) -> None:
        """Seleciona e carrega uma tabela."""
        if self._current_table == table_name:
            return
        if self._unsaved_changes:
            reply = QMessageBox.question(
                self,
                "Alterações não salvas",
                "Há alterações não salvas. Trocar de tabela mesmo assim?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._current_table = table_name
        self._update_table_buttons()
        self._search_entry.clear()
        self._add_button.setEnabled(True)
        self._delete_button.setEnabled(True)
        self._unsaved_changes.clear()
        self._update_save_button()
        self._populate_table(table_name)

    def _populate_table(self, table_name: str, filter_text: str = "") -> None:
        """Carrega dados da tabela no QTableWidget."""
        if self._current_db not in self._db_paths:
            return

        schema = self._service.get_table_schema(self._current_db, table_name)
        self._column_names = schema["column_names"]
        self._pk_columns = schema["pk_columns"]
        non_editable = set(self._service.get_non_editable_columns(table_name))

        rows = self._service.get_table_rows(
            self._current_db, table_name, filter_text
        )

        with table_batch_populate(self._table):
            self._table.clear()
            self._table.setColumnCount(len(self._column_names))
            self._table.setHorizontalHeaderLabels(self._column_names)
            self._table.setRowCount(len(rows))

            self._pk_values.clear()
            self._original_values.clear()

            for row_idx, row in enumerate(rows):
                row_key = str(row_idx)
                pk_vals: dict[str, Any] = {}
                originals: dict[str, Any] = {}

                for col_idx, col_name in enumerate(self._column_names):
                    raw = row[col_idx]
                    originals[col_name] = raw
                    if col_name in self._pk_columns:
                        pk_vals[col_name] = raw

                    display = "-" if raw is None else str(raw)
                    if raw is not None and col_name not in non_editable:
                        masked = apply_mask_for_field(col_name, str(raw))
                        if masked:
                            display = masked

                    item = QTableWidgetItem(display)
                    item.setData(Qt.ItemDataRole.UserRole, row_key)
                    if col_name in non_editable:
                        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                        item.setForeground(QColor(self._palette["text_dim"]))
                    self._table.setItem(row_idx, col_idx, item)

                self._pk_values[row_key] = pk_vals
                self._original_values[row_key] = originals

        self._table.resizeColumnsToContents()

    # ----------------------------------------------------------- search

    def _on_search(self, _text: str = "") -> None:
        """Debounce da busca."""
        self._search_timer.start()

    def _execute_search(self) -> None:
        """Executa filtro após debounce."""
        if self._current_table:
            self._populate_table(self._current_table, self._search_entry.text())

    # ----------------------------------------------------------- editing

    def _row_key_for_item(self, item: QTableWidgetItem) -> str | None:
        """Obtém a chave de linha armazenada no item."""
        key = item.data(Qt.ItemDataRole.UserRole)
        return str(key) if key is not None else None

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Rastreia edições in-line como mudanças não salvas."""
        if self._current_table is None:
            return

        col = item.column()
        if col < 0 or col >= len(self._column_names):
            return

        col_name = self._column_names[col]
        non_editable = self._service.get_non_editable_columns(self._current_table)
        if col_name in non_editable:
            return

        row_key = self._row_key_for_item(item)
        if row_key is None:
            return

        new_text = item.text()
        if new_text == "-":
            new_text = ""

        original = self._original_values.get(row_key, {}).get(col_name)
        original_str = "" if original is None else str(original)

        # Comparar sem máscara
        if new_text == original_str or (
            original is None and new_text in ("", "-")
        ):
            if row_key in self._unsaved_changes:
                self._unsaved_changes[row_key].pop(col_name, None)
                if not self._unsaved_changes[row_key]:
                    del self._unsaved_changes[row_key]
            self._update_save_button()
            return

        masked = apply_mask_for_field(col_name, new_text) or "-"
        if masked != item.text():
            self._table.blockSignals(True)
            item.setText(masked)
            self._table.blockSignals(False)

        self._unsaved_changes.setdefault(row_key, {})[col_name] = new_text
        self._update_save_button()

    def _update_save_button(self) -> None:
        """Atualiza contador de alterações no botão Salvar."""
        total = sum(len(c) for c in self._unsaved_changes.values())
        self._save_button.setText(f"Salvar ({total})")

    def _save_changes(self) -> None:
        """Persiste alterações pendentes no banco."""
        if not self._unsaved_changes or not self._current_table:
            return

        saved = 0
        changes_copy = {
            rk: dict(cols) for rk, cols in self._unsaved_changes.items()
        }

        for row_key, changes in changes_copy.items():
            pk_vals = self._pk_values.get(row_key, {})
            for col_name, new_value in list(changes.items()):
                value = new_value
                if self._current_table == "items_catalog" and col_name in (
                    "descricao",
                    "item_id",
                ):
                    value = value.strip().upper() if isinstance(value, str) and value else value
                try:
                    self._service.update_record(
                        self._current_db,
                        self._current_table,
                        self._pk_columns or ["id"],
                        pk_vals,
                        col_name,
                        value,
                    )
                    saved += 1
                    self._original_values.setdefault(row_key, {})[col_name] = (
                        new_value if new_value != "" else None
                    )
                    del self._unsaved_changes[row_key][col_name]
                    if not self._unsaved_changes[row_key]:
                        del self._unsaved_changes[row_key]
                except sqlite3.IntegrityError as e:
                    original = self._original_values.get(row_key, {}).get(
                        col_name
                    )
                    display = "-" if original is None else str(original)
                    # Reverter célula
                    col_idx = self._column_names.index(col_name)
                    for r in range(self._table.rowCount()):
                        it = self._table.item(r, col_idx)
                        if it and self._row_key_for_item(it) == row_key:
                            self._table.blockSignals(True)
                            it.setText(display)
                            self._table.blockSignals(False)
                            break
                    msg = self._service.parse_integrity_error(
                        e, self._current_table, col_name, str(new_value)
                    )
                    QMessageBox.critical(self, "Erro ao salvar", msg)
                    del self._unsaved_changes[row_key][col_name]
                    if not self._unsaved_changes[row_key]:
                        del self._unsaved_changes[row_key]

        self._update_save_button()
        if saved > 0:
            QMessageBox.information(
                self, "Sucesso", f"{saved} alteração(ões) salva(s) no banco."
            )

    # ----------------------------------------------------------- CRUD

    def _add_record(self) -> None:
        """Abre diálogo para inserir registro."""
        if not self._current_table:
            return

        schema = self._service.get_table_schema(
            self._current_db, self._current_table
        )
        columns_info = schema["columns_info"]
        non_editable = set(
            self._service.get_non_editable_columns(self._current_table)
        )
        editable = [
            col
            for col in columns_info
            if col[1] not in non_editable
            and not (col[5] > 0 and str(col[2]).upper() == "INTEGER")
        ]
        if not editable:
            QMessageBox.warning(
                self,
                "Sem colunas editáveis",
                f"A tabela '{self._current_table}' não possui colunas editáveis.",
            )
            return

        dialog = _AddRecordDialog(
            self, self._current_table, editable, self._palette
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        values = dialog.values()
        if self._current_table == "items_catalog":
            values = self._normalize_catalog_values(values)

        try:
            self._service.insert_record(
                self._current_db, self._current_table, values
            )
            self._populate_table(self._current_table)
            self._populate_table_list()
            QMessageBox.information(
                self, "Sucesso", "Registro adicionado com sucesso!"
            )
        except sqlite3.IntegrityError as e:
            msg = self._service.parse_integrity_error(
                e, self._current_table, "", ""
            )
            QMessageBox.critical(self, "Erro ao adicionar", msg)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro inesperado: {e}")

    def _normalize_catalog_values(self, values: dict[str, Any]) -> dict[str, Any]:
        """
        Normaliza campos do catálogo de itens.

        Aplica strip + upper (mantém acentos) em descrição e código.
        Campos vazios (None) são preservados.

        Args:
            values: Valores brutos do diálogo de inserção.

        Returns:
            Valores normalizados para items_catalog.
        """
        normalized = dict(values)
        for field in ("descricao", "item_id"):
            value = normalized.get(field)
            if value:
                normalized[field] = value.strip().upper()
        return normalized
    def _delete_record(self) -> None:
        """Exclui o registro selecionado."""
        if not self._current_table:
            return

        selected = self._table.selectedItems()
        if not selected:
            QMessageBox.warning(
                self,
                "Nenhum registro selecionado",
                "Selecione um registro para excluir.",
            )
            return

        row = selected[0].row()
        first_item = self._table.item(row, 0)
        if first_item is None:
            return
        row_key = self._row_key_for_item(first_item)
        if row_key is None:
            return

        pk_vals = self._pk_values.get(row_key, {})
        pk_cols = self._pk_columns or ["id"]
        pk_str = ", ".join(f"{k}={v}" for k, v in pk_vals.items() if k in pk_cols)

        reply = QMessageBox.question(
            self,
            "Confirmar exclusão",
            f"Tem certeza que deseja excluir o registro:\n"
            f"{self._current_table}[{pk_str}]?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._service.delete_record(
                self._current_db, self._current_table, pk_cols, pk_vals
            )
            self._unsaved_changes.pop(row_key, None)
            self._update_save_button()
            self._populate_table(self._current_table)
            self._populate_table_list()
            QMessageBox.information(
                self, "Sucesso", "Registro excluído com sucesso!"
            )
        except sqlite3.IntegrityError as e:
            msg = self._service.parse_integrity_error(
                e, self._current_table, "", ""
            )
            QMessageBox.critical(self, "Erro ao excluir", msg)
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Erro inesperado: {e}")


def open_dashboard(parent: QWidget, config_manager: Any) -> DashboardWindow:
    """
    Abre a janela do Dashboard.

    Args:
        parent: Widget pai.
        config_manager: Gerenciador de configuração.

    Returns:
        A janela do Dashboard já exibida.
    """
    window = DashboardWindow(parent, config_manager)
    window.show()
    return window
