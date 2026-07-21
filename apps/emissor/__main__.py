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
from emissor.database.emissor_db import EmissorDatabase  # noqa: E402
from emissor.utils.config import AppConfig  # noqa: E402
from emissor.utils.updater import get_shared_root  # noqa: E402
from emissor.main_window import QtApp  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

from emissor.ui_qt.theme import get_palette, qpalette, stylesheet  # noqa: E402


def main() -> None:
    """Ponto de entrada da UI Qt."""
    from pathlib import Path

    # Set AppUserModelID + register icon in registry BEFORE QApplication.
    from andaime.win32 import register_taskbar_identity

    register_taskbar_identity(
        "SISTEMAS.Emissor", "Emissor", Path(__file__).resolve().parent / "icon.ico"
    )

    andaime_instance = andaime.App(
        "Emissor",
        "Emissor",
        config_cls=AppConfig,
        db_cls=EmissorDatabase,
        root=get_shared_root(),
    )
    setup_shutdown_handlers()

    # Migração de pastas de insulina (idempotente): roda a cada lançamento,
    # mas só atua enquanto existir a pasta antiga 0-INSULINAS.
    from emissor.utils.insulina_folder_migration import migrate_insulina_folders

    _migration_root = andaime_instance.root
    migrate_insulina_folders(_migration_root)

    app = QApplication(sys.argv)

    # Window icon (taskbar + alt-tab)
    from PySide6.QtGui import QIcon

    icon_path = Path(__file__).resolve().parent / "icon.ico"
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

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
