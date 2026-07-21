#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
from pathlib import Path

from PySide6.QtCore import Qt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import andaime
from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel
from rac.utils.config import RACConfig
from rac.database.rac_database import RACDatabase


def _load_bundled_fonts():
    from PySide6.QtGui import QFontDatabase
    from andaime.paths import get_root_directory

    fonts_dir = get_root_directory() / "fonts"
    if fonts_dir.is_dir():
        db = QFontDatabase()
        for f in fonts_dir.iterdir():
            if f.suffix in (".ttf", ".otf"):
                db.addApplicationFont(str(f))


def _get_app_icon_path():
    return Path(__file__).parent / "src" / "gui" / "img" / "folder-1486.svg"


def _apply_pending_update():
    from andaime.updater import apply_pending_update

    apply_pending_update()


def _start_update_check(window):
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
    from andaime.updater import UpdateCheckWorker, restart_app
    from rac import __version__
    from rac.gui.widgets.buttons import make_button
    from rac.gui.widgets.labels import HeadingLabel
    from rac.gui.styles import colors

    worker = UpdateCheckWorker("januvary/RAC", __version__, parent=window)

    def _on_downloaded(tag):
        dlg = QDialog(window)
        dlg.setWindowTitle("Atualização disponível")
        dlg.setMinimumWidth(380)
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.addWidget(HeadingLabel(f"Atualização {tag}"))

        c = colors()
        msg = QLabel("Uma nova versão foi baixada e está pronta para uso.\nReinicie o aplicativo para aplicar a atualização.")
        msg.setWordWrap(True)
        msg.setStyleSheet(f"color: {c['text_secondary']}; font-size: 13px;")
        layout.addWidget(msg)
        layout.addSpacing(8)

        from PySide6.QtWidgets import QHBoxLayout
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        later = make_button("Mais tarde", "flat")
        later.clicked.connect(dlg.reject)
        btn_row.addWidget(later)
        restart = make_button("Reiniciar", "primary")
        restart.clicked.connect(dlg.accept)
        btn_row.addWidget(restart)
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            restart_app()

    def _on_failed(msg):
        ErrorHandler.log(f"Update check failed: {msg}", level=ErrorLevel.WARNING, context=ErrorContext.UPDATER)

    worker.update_ready.connect(_on_downloaded)
    worker.update_failed.connect(_on_failed)
    worker.no_update.connect(lambda: ErrorHandler.log("No update available", context=ErrorContext.UPDATER))
    worker.start()


def main():
    # Set AppUserModelID BEFORE any window/QApplication is created so the
    # taskbar groups the pythonw.exe child process under the app identity.
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "SISTEMAS.RAC"
        )

    _apply_pending_update()

    from andaime.updater import get_shared_root

    app = andaime.App("RAC", "RAC", config_cls=RACConfig, db_cls=RACDatabase, root=get_shared_root())

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QIcon

    from rac.gui.styles import set_theme, get_stylesheet

    qapp = QApplication(sys.argv)

    # Dev: Ctrl+Shift+I abre o código-fonte do widget sob o cursor (var. DEV_INSPECTOR).
    from andaime.qt.dev_inspector import enable_if_env
    enable_if_env(qapp)

    icon_path = _get_app_icon_path()
    if icon_path.exists():
        qapp.setWindowIcon(QIcon(str(icon_path)))

    _load_bundled_fonts()

    font = QFont("Geist", 11)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    qapp.setFont(font)

    config = app.config
    theme = config.get("theme", "dark")
    set_theme(theme)
    qapp.setStyleSheet(get_stylesheet())

    from rac.gui.main_window import MainWindow

    window = MainWindow()
    window.init_backend()
    window.navigate_to("start")
    window.show()

    _start_update_check(window)

    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
