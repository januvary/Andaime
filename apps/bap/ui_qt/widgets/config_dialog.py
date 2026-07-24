#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QtConfigDialog (BAP) — diálogo de configuração (Qt).

Espelha o ConfigDialog do Emissor (visual fixo, sem stretch):
- Linha 1: Local de salvamento
- Botões: Resetar Padrão (esq.) | Exportar Planilha (centro) | Salvar (dir.)

Diferenças em relação ao Emissor:
- não há a seção intermediária de distribuição/feriados (datas);
- o botão central é "Exportar Planilha" (em vez de "Banco de Dados").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from bap.ui_qt.widgets.buttons import make_button


class QtConfigDialog(QDialog):
    """Diálogo de configuração usando widgets Qt nativos."""

    def __init__(
        self,
        parent: QWidget,
        config: dict[str, Any],
        export_callback: Callable | None = None,
        revert_callback: Callable | None = None,
    ) -> None:
        """
        Inicializa o diálogo.

        Args:
            parent: Janela pai
            config: Configuração atual (``arquivos_root`` e ``default_root``)
            export_callback: Callback do botão Exportar Planilha
            revert_callback: Callback do botão Reverter Migração
        """
        super().__init__(parent)
        self.setWindowTitle("Configurações")

        self.result_data: dict[str, Any] | None = None
        self._config = config
        self._export = export_callback
        self._revert = revert_callback

        self._location_edit: QLineEdit | None = None

        self._build_ui()

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói a interface do diálogo."""
        layout = QVBoxLayout(self)
        # Fixa o tamanho ao conteúdo (não redimensionável) — espelha o Emissor.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(22)

        # === Linha 1: Local de salvamento ===
        row = QGridLayout()
        row.setHorizontalSpacing(20)
        row.setVerticalSpacing(5)
        row.setColumnStretch(1, 3)

        row.addWidget(QLabel("Local de salvamento:"), 0, 1)

        loc_container = QWidget()
        loc_row = QHBoxLayout(loc_container)
        loc_row.setContentsMargins(0, 0, 0, 0)
        loc_row.setSpacing(6)
        self._location_edit = QLineEdit(str(self._config.get("arquivos_root", "")))
        self._location_edit.setMinimumWidth(280)
        loc_row.addWidget(self._location_edit, stretch=1)
        browse_btn = make_button("Procurar...", "flat-fill", loc_container)
        browse_btn.clicked.connect(self._browse_location)
        loc_row.addWidget(browse_btn)
        row.addWidget(loc_container, 1, 1)

        layout.addLayout(row)

        # === Botões ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        reset_btn = make_button("Resetar Padrão", "flat-fill", self)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch(1)

        export_btn = make_button("Exportar Planilha", "flat-fill", self)
        if self._export is not None:
            export_btn.clicked.connect(self._export_planilha)
        btn_row.addWidget(export_btn)

        if self._revert is not None:
            revert_btn = make_button("Reverter Migração", "flat-fill", self)
            revert_btn.clicked.connect(self._revert_archive)
            btn_row.addWidget(revert_btn)

        btn_row.addStretch(1)

        save_btn = make_button("Salvar", "primary", self)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    # ========== Handlers ==========

    def _revert_archive(self) -> None:
        """Delega a reversão da migração ao callback fornecido."""
        if self._revert is not None:
            self._revert(self)

    def _export_planilha(self) -> None:
        """Delega a exportação da planilha ao callback fornecido."""
        if self._export is not None:
            self._export(self)

    def _browse_location(self) -> None:
        """Abre seletor de diretório para o local de salvamento."""
        assert self._location_edit is not None
        current = self._location_edit.text()
        path = QFileDialog.getExistingDirectory(
            self, "Selecionar local de salvamento", current
        )
        if path:
            self._location_edit.setText(path)

    def _reset_defaults(self) -> None:
        """Restaura os campos do diálogo para os valores padrão."""
        assert self._location_edit is not None
        self._location_edit.setText(str(self._config.get("default_root", "")))

    def _save(self) -> None:
        """Valida e fecha o diálogo com o resultado (ou mostra erro)."""
        assert self._location_edit is not None

        location_str = self._location_edit.text().strip()
        if not location_str:
            QMessageBox.warning(
                self, "Inválido", "O local de salvamento é obrigatório."
            )
            return
        location_path = Path(location_str)
        if not location_path.exists():
            try:
                location_path.mkdir(parents=True, exist_ok=True)
            except OSError:
                QMessageBox.warning(
                    self,
                    "Inválido",
                    "Não foi possível criar o local de salvamento.",
                )
                return

        self.result_data = {"arquivos_root": str(location_path)}
        self.accept()
