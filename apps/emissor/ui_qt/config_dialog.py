#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QtConfigDialog — diálogo de configuração (Qt).

Constrói sobre o ``QtConfigDialog`` compartilhado de ``andaime.qt.dialogs``,
fornecendo o conteúdo intermediário (distribuição de retiradas + feriados),
a ação central (Banco de Dados) e o ``on_save`` específico.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from andaime.paths import get_root_directory
from andaime.qt.dialogs import QtConfigDialog as _QtConfigDialog
from andaime.qt.theme import make_button


class QtConfigDialog(_QtConfigDialog):
    """Diálogo de configuração do Emissor (visual fixo, sem stretch)."""

    def __init__(
        self,
        parent: QWidget,
        config: dict[str, Any],
        launch_dashboard_callback: Callable | None = None,
    ) -> None:
        """
        Args:
            parent: Janela pai
            config: Configuração atual (passa por print_copies e dark_mode)
            launch_dashboard_callback: Callback do botão Banco de Dados
        """
        self._config = config
        self._launch_dashboard = launch_dashboard_callback

        self._distribute_check = QCheckBox("")
        self._distribute_check.setChecked(
            config.get("distribute_retiradas", True)
        )
        self._window_spin = QSpinBox()
        self._window_spin.setRange(1, 7)
        self._window_spin.setFixedWidth(50)
        self._window_spin.setValue(config.get("distribution_window_days", 3))

        middle = self._build_middle()
        self._distribute_check.toggled.connect(self._on_distribute_toggled)
        self._on_distribute_toggled(self._distribute_check.isChecked())

        super().__init__(
            parent,
            initial_location=str(config.get("save_location", "")),
            reset_location=str(get_root_directory()),
            on_save=self._on_save,
            center_label="Banco de Dados",
            center_callback=lambda: self._open_dashboard(),
            middle=middle,
            on_reset=self._on_reset,
        )

    # ========== Conteúdo intermediário ==========

    def _build_middle(self) -> QWidget:
        """Linha: janela (dias) + toggle | Gerenciar feriados."""
        dist_box = QFrame()
        dist_box.setProperty("class", "box")
        dist_row = QHBoxLayout(dist_box)
        dist_row.setContentsMargins(12, 10, 12, 10)
        dist_row.setSpacing(8)

        dist_row.addWidget(QLabel("Distribuição de retiradas"))
        dist_row.addWidget(self._window_spin)
        dist_row.addWidget(QLabel("(dias)"))

        dist_row.addSpacing(8)
        dist_row.addWidget(self._distribute_check)
        dist_row.addStretch()

        holidays_btn = make_button("Gerenciar feriados", "flat")
        holidays_btn.setStyleSheet("font-size: 11px;")
        holidays_btn.clicked.connect(self._open_holidays)
        dist_row.addWidget(holidays_btn)

        return dist_box

    # ========== Handlers ==========

    def _on_distribute_toggled(self, checked: bool) -> None:
        """Habilita/desabilita a janela conforme o toggle de distribuição."""
        self._window_spin.setEnabled(checked)

    def _open_holidays(self) -> None:
        """Abre o diálogo de gerenciamento de feriados facultativos."""
        from emissor.ui_qt.holidays_dialog import show_holidays_dialog

        show_holidays_dialog(self)

    def _open_dashboard(self) -> None:
        """Fecha este diálogo modal e abre o Dashboard (evita bloqueio de cliques)."""
        callback = self._launch_dashboard
        self.reject()
        if callback is not None:
            QTimer.singleShot(0, callback)

    def _on_reset(self) -> None:
        """Restaura a distribuição para os valores padrão."""
        self._distribute_check.setChecked(True)
        self._window_spin.setValue(3)

    def _on_save(self, location_str: str) -> dict[str, Any] | None:
        """Valida e devolve o resultado (ou mostra erro e mantém aberto)."""
        location_path = Path(location_str)
        if not location_path.exists():
            QMessageBox.warning(self, "Inválido", "O local de salvamento não existe.")
            return None

        return {
            "save_location": location_path,
            # Não editáveis na UI — repassam o valor corrente
            "print_copies": self._config.get("print_copies", 2),
            "dark_mode": self._config.get("dark_mode", True),
            "distribute_retiradas": self._distribute_check.isChecked(),
            "distribution_window_days": self._window_spin.value(),
        }