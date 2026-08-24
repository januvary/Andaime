#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Emissor de Recibos — entry point."""

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
from andaime.qt.fonts import FontSpec, apply_font  # noqa: E402
from emissor.database.emissor_db import EmissorDatabase  # noqa: E402
from emissor.utils.config import AppConfig  # noqa: E402
from andaime.updater import get_shared_root  # noqa: E402
from emissor.main_window import QtApp  # noqa: E402

from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from emissor.ui_qt.theme import get_palette, qpalette, stylesheet  # noqa: E402


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
    from pathlib import Path

    # Set AppUserModelID + register icon in registry BEFORE QApplication.
    from andaime.win32 import register_taskbar_identity

    register_taskbar_identity(
        "SISTEMAS.Emissor", "Emissor", Path(__file__).resolve().parent / "icon.ico"
    )

    _apply_pending_update()

    andaime_instance = andaime.App(
        "Emissor",
        "Emissor",
        config_cls=AppConfig,
        db_cls=EmissorDatabase,
        root=get_shared_root(),
        font=FontSpec(
            family="IBM Plex Sans",
            size=11,
            style_hint=QFont.StyleHint.SansSerif,
            bundled=True,
        ),
    )
    setup_shutdown_handlers()

    # Migração de pastas de insulina (idempotente): roda a cada lançamento,
    # movendo pastas com sufixo ' - INSULINA' do nível superior para
    # MANDADOS JUDICIAIS/05 - INSULINA.
    from emissor.utils.insulina_folder_migration import migrate_insulina_folders

    _migration_root = andaime_instance.config.get_all().save_location
    try:
        migrate_insulina_folders(_migration_root)
    except Exception:
        pass

    app = QApplication(sys.argv)

    icon_path = Path(__file__).resolve().parent / "icon.ico"
    splash = andaime.SplashScreen("Emissor", icon_path)
    splash.show()

    apply_font(app, andaime_instance.font)

    from PySide6.QtGui import QIcon
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Dev: Ctrl+Alt+I abre o código-fonte do widget sob o cursor (var. DEV_INSPECTOR).
    from andaime.qt.dev_inspector import enable_if_env

    enable_if_env(app)

    dark_mode = andaime_instance.config.get("dark_mode", True)
    palette = get_palette(dark_mode)
    app.setPalette(qpalette(palette))
    app.setStyleSheet(stylesheet(palette))

    window = QtApp(andaime_instance)
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    splash.finish(window)

    _start_update_check(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
