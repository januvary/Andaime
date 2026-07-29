#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sistema de Negativas — entry point."""

from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap: permite rodar como script (python main.py) ou módulo
# (python -m main), garantindo que o pacote raiz esteja em sys.path.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import andaime  # noqa: E402
from andaime.shutdown import setup_shutdown_handlers  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from negativas.constants import APP_NAME, APP_DISPLAY_NAME, DB_PATH
from negativas.config import NegativasConfig
from negativas.database.negativas_database import NegativasDatabase
from negativas.ui_qt.main_window import MainWindow


def _get_app_icon_path() -> Path:
    """Retorna o caminho para o ícone do aplicativo."""
    return _PROJECT_ROOT / "icon.ico"


def main() -> None:
    """Ponto de entrada da UI Qt."""
    
    # Set AppUserModelID + register icon in registry BEFORE QApplication (Windows only).
    try:
        from andaime.win32 import register_taskbar_identity
        register_taskbar_identity(
            "SISTEMAS.Negativas", 
            "Negativas", 
            _get_app_icon_path()
        )
    except ImportError:
        # Not on Windows, skip
        pass

    # Inicializa o app Andaime
    andaime_instance = andaime.App(
        APP_NAME,
        APP_DISPLAY_NAME,
        config_cls=NegativasConfig,
        db_cls=NegativasDatabase,
    )
    
    setup_shutdown_handlers()

    # Configura o Qt
    qt_app = QApplication(sys.argv)
    
    # Ícone da aplicação (taskbar + alt-tab)
    icon_path = _get_app_icon_path()
    if icon_path.exists():
        qt_app.setWindowIcon(QIcon(str(icon_path)))
    
    # Fonte padrão
    font = QFont("Segoe UI", 11)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    qt_app.setFont(font)
    
    # Dev: Ctrl+Alt+I abre o código-fonte do widget sob o cursor (var. DEV_INSPECTOR).
    from andaime.qt.dev_inspector import enable_if_env
    enable_if_env(qt_app)
    
    # Cria a janela principal
    window = MainWindow(andaime_instance, andaime_instance.db, andaime_instance.config)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    
    window.show()
    
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()