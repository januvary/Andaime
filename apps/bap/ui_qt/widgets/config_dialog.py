#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QtConfigDialog (BAP) — diálogo de configuração (Qt).

Constrói sobre o ``QtConfigDialog`` compartilhado de ``andaime.qt.dialogs`` —
o mesmo base usado pelo Emissor. A SS-54 não tem seção intermediária; o botão
central é "Exportar Planilha" (em vez de "Banco de Dados" do Emissor).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import QMessageBox, QWidget

from andaime.qt.dialogs import QtConfigDialog as _QtConfigDialog


class QtConfigDialog(_QtConfigDialog):
    """Diálogo de configuração da SS-54 (visual fixo, sem stretch)."""

    def __init__(
        self,
        parent: QWidget,
        config: dict[str, Any],
        export_callback: Callable | None = None,
    ) -> None:
        """
        Args:
            parent: Janela pai
            config: Configuração atual (``arquivos_root`` e ``default_root``)
            export_callback: Callback do botão Exportar Planilha
        """
        self._config = config
        self._export = export_callback

        super().__init__(
            parent,
            initial_location=str(config.get("arquivos_root", "")),
            reset_location=str(config.get("default_root", "")),
            on_save=self._on_save,
            center_label="Exportar Planilha",
            center_callback=lambda: self._export_planilha(),
        )

    # ========== Handlers ==========

    def _export_planilha(self) -> None:
        """Delega a exportação da planilha ao callback fornecido."""
        if self._export is not None:
            self._export(self)

    def _on_save(self, location_str: str) -> dict[str, Any] | None:
        """Valida e devolve o resultado (ou cria o diretório e mantém aberto)."""
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
                return None

        return {"arquivos_root": str(location_path)}