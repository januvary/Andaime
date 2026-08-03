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
from andaime.updater import get_shared_root  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from negativas.constants import APP_NAME, APP_DISPLAY_NAME
from negativas.config import NegativasConfig
from negativas.database.negativas_database import NegativasDatabase
from negativas.ui_qt.main_window import MainWindow


def _get_app_icon_path() -> Path:
    """Retorna o caminho para o ícone do aplicativo."""
    return _PROJECT_ROOT / "icon.ico"


def _apply_pending_update() -> None:
    from andaime.updater import apply_pending_update

    apply_pending_update()


def _start_update_check(window) -> None:
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QHBoxLayout, QPushButton

    from andaime.updater import UpdateCheckWorker, restart_app

    worker = UpdateCheckWorker(parent=window)

    def _on_downloaded(tag: str) -> None:
        dlg = QDialog(window)
        dlg.setWindowTitle("Atualização disponível")
        dlg.setMinimumWidth(360)

        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"Atualização {tag} disponível."))
        layout.addWidget(QLabel("Reinicie o aplicativo para aplicar."))

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        later = QPushButton("Mais tarde")
        later.clicked.connect(dlg.reject)
        btn_row.addWidget(later)
        restart = QPushButton("Reiniciar")
        restart.clicked.connect(dlg.accept)
        btn_row.addWidget(restart)
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            restart_app()

    worker.update_ready.connect(_on_downloaded)
    worker.start()


def main() -> None:
    """Ponto de entrada da UI Qt."""

    # Set AppUserModelID + register icon in registry BEFORE QApplication (Windows only).
    try:
        from andaime.win32 import register_taskbar_identity

        register_taskbar_identity(
            "SISTEMAS.Negativas", "Negativas", _get_app_icon_path()
        )
    except ImportError:
        # Not on Windows, skip
        pass

    _apply_pending_update()

    # Inicializa o app Andaime
    andaime_instance = andaime.App(
        APP_NAME,
        APP_DISPLAY_NAME,
        config_cls=NegativasConfig,
        db_cls=NegativasDatabase,
        root=get_shared_root(),
    )

    setup_shutdown_handlers()

    # Configura o Qt
    qt_app = QApplication(sys.argv)

    icon_path = _get_app_icon_path()
    splash = andaime.SplashScreen("Negativas", icon_path)
    splash.show()

    # Apply andaime theme
    from negativas.ui_qt.theme import set_theme, get_stylesheet, qpalette, get_palette
    theme = andaime_instance.config.get("theme", "dark")
    set_theme(theme)
    palette = get_palette(theme == "dark")
    qt_app.setStyleSheet(get_stylesheet(theme))
    qt_app.setPalette(qpalette(palette))

    if icon_path.exists():
        qt_app.setWindowIcon(QIcon(str(icon_path)))

    # Dev: Ctrl+Alt+I abre o código-fonte do widget sob o cursor (var. DEV_INSPECTOR).
    from andaime.qt.dev_inspector import enable_if_env

    enable_if_env(qt_app)

    # Cria a janela principal
    window = MainWindow(andaime_instance)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))

    window.show()
    splash.finish(window)

    _start_update_check(window)

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
