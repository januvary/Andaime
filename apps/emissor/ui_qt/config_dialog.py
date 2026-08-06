#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QtConfigDialog — diálogo de configuração (Qt).

Espelha o ConfigDialog CTk (visual fixo, sem stretch):
- Linha 1: Local de salvamento
- Janela de distribuição (dias) + toggle "Distribuir retiradas" na mesma linha
- print_copies e dark_mode não são editáveis na UI (repassam o valor corrente)
- Botões: Resetar Padrão (esq.) | Banco de Dados (centro) | Salvar (dir.)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from emissor.ui_qt.theme import make_button


class QtConfigDialog(QDialog):
    """Diálogo de configuração usando widgets Qt nativos."""

    def __init__(
        self,
        parent: QWidget,
        config: dict[str, Any],
        launch_dashboard_callback: Callable | None = None,
    ) -> None:
        """
        Inicializa o diálogo.

        Args:
            parent: Janela pai
            config: Configuração atual (passa por print_copies e dark_mode)
            launch_dashboard_callback: Callback do botão Banco de Dados
        """
        super().__init__(parent)
        self.setWindowTitle("Configurações")

        self.result_data: dict[str, Any] | None = None
        self._config = config
        self._launch_dashboard = launch_dashboard_callback

        self._location_edit: QLineEdit | None = None
        self._distribute_check: QCheckBox | None = None
        self._window_spin: QSpinBox | None = None

        self._build_ui()

    # ========== UI ==========

    def _build_ui(self) -> None:
        """Constrói a interface do diálogo."""
        layout = QVBoxLayout(self)
        # Fixa o tamanho ao conteúdo (não redimensionável) — espelha o CTk
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
        self._location_edit = QLineEdit(str(self._config.get("save_location", "")))
        self._location_edit.setMinimumWidth(280)
        loc_row.addWidget(self._location_edit, stretch=1)
        browse_btn = make_button("Procurar...", "flat-fill", loc_container)
        browse_btn.clicked.connect(self._browse_location)
        loc_row.addWidget(browse_btn)
        row.addWidget(loc_container, 1, 1)

        layout.addLayout(row)

        # === Janela (dias) + toggle | Gerenciar feriados ===
        dist_box = QFrame()
        dist_box.setProperty("class", "box")
        dist_row = QHBoxLayout(dist_box)
        dist_row.setContentsMargins(12, 10, 12, 10)
        dist_row.setSpacing(8)

        dist_row.addWidget(QLabel("Distribuição de retiradas"))
        self._window_spin = QSpinBox()
        self._window_spin.setRange(1, 7)
        self._window_spin.setFixedWidth(50)
        self._window_spin.setValue(
            self._config.get("distribution_window_days", 3)
        )
        dist_row.addWidget(self._window_spin)
        dist_row.addWidget(QLabel("(dias)"))

        dist_row.addSpacing(8)
        self._distribute_check = QCheckBox("")
        self._distribute_check.setChecked(
            self._config.get("distribute_retiradas", True)
        )
        self._distribute_check.toggled.connect(self._on_distribute_toggled)
        dist_row.addWidget(self._distribute_check)

        dist_row.addStretch()

        holidays_btn = make_button("Gerenciar feriados", "flat-fill", self)
        holidays_btn.setStyleSheet("font-size: 11px;")
        holidays_btn.clicked.connect(self._open_holidays)
        dist_row.addWidget(holidays_btn)

        layout.addWidget(dist_box)
        self._on_distribute_toggled(self._distribute_check.isChecked())

        # === Botões ===
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        reset_btn = make_button("Resetar Padrão", "flat-fill", self)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch(1)

        dashboard_btn = make_button("Banco de Dados", "flat-fill", self)
        if self._launch_dashboard is not None:
            dashboard_btn.clicked.connect(self._open_dashboard)
        btn_row.addWidget(dashboard_btn)

        btn_row.addStretch(1)

        save_btn = make_button("Salvar", "primary", self)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

    # ========== Handlers ==========

    def _open_dashboard(self) -> None:
        """Fecha este diálogo modal e abre o Dashboard (evita bloqueio de cliques)."""
        callback = self._launch_dashboard
        self.reject()
        if callback is not None:
            QTimer.singleShot(0, callback)

    def _on_distribute_toggled(self, checked: bool) -> None:
        """Habilita/desabilita a janela conforme o toggle de distribuição."""
        if self._window_spin is not None:
            self._window_spin.setEnabled(checked)

    def _open_holidays(self) -> None:
        """Abre o diálogo de gerenciamento de feriados facultativos."""
        from emissor.ui_qt.holidays_dialog import show_holidays_dialog

        show_holidays_dialog(self)

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
        from andaime.paths import get_root_directory

        assert self._location_edit is not None
        assert self._distribute_check is not None
        assert self._window_spin is not None

        self._location_edit.setText(str(get_root_directory()))
        self._distribute_check.setChecked(True)
        self._window_spin.setValue(3)

    def _save(self) -> None:
        """Valida e fecha o diálogo com o resultado (ou mostra erro)."""
        assert self._location_edit is not None
        assert self._distribute_check is not None
        assert self._window_spin is not None

        location_str = self._location_edit.text().strip()
        if not location_str:
            QMessageBox.warning(self, "Inválido", "O local de salvamento é obrigatório.")
            return
        location_path = Path(location_str)
        if not location_path.exists():
            QMessageBox.warning(
                self, "Inválido", "O local de salvamento não existe."
            )
            return

        self.result_data = {
            "save_location": location_path,
            # Não editáveis na UI — repassam o valor corrente
            "print_copies": self._config.get("print_copies", 2),
            "dark_mode": self._config.get("dark_mode", True),
            "distribute_retiradas": self._distribute_check.isChecked(),
            "distribution_window_days": self._window_spin.value(),
        }
        self.accept()
