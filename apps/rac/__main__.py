#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
from pathlib import Path

from PySide6.QtCore import Qt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import andaime
from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel
from andaime.qt.fonts import FontSpec, apply_font
from rac.utils.config import RACConfig
from rac.database.rac_database import RACDatabase


def _get_app_icon_path():
    return Path(__file__).parent / "icon.ico"


def _apply_pending_update():
    from andaime.updater import apply_pending_update

    apply_pending_update()


def _show_usafa_dialog(config, parent=None):
    """Show dialog to configure USAFA name."""
    from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QHBoxLayout
    from rac.gui.widgets.buttons import make_button
    from rac.gui.widgets.labels import HeadingLabel
    from rac.gui.styles import colors

    current_name = config.get("usafa_name", "")
    display_name = current_name.replace("USAFA ", "") if current_name else ""

    dlg = QDialog(parent)
    dlg.setWindowTitle("Configuração da USAFA")
    dlg.setMinimumWidth(400)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)

    c = colors()
    title = HeadingLabel("Nome da USAFA")
    layout.addWidget(title)

    msg = QLabel("Digite o nome da sua unidade de saúde:")
    msg.setWordWrap(True)
    msg.setStyleSheet(f"color: {c['text_secondary']}; font-size: 13px;")
    layout.addWidget(msg)

    input_layout = QHBoxLayout()
    prefix_label = QLabel("USAFA ")
    prefix_label.setStyleSheet(f"color: {c['text_primary']}; font-size: 14px;")
    input_layout.addWidget(prefix_label)

    input_field = QLineEdit(display_name)
    input_field.setPlaceholderText("Nome da unidade")
    input_field.setStyleSheet(f"color: {c['text_primary']}; font-size: 14px; padding: 6px;")
    input_field.setMinimumWidth(250)
    input_layout.addWidget(input_field)

    layout.addLayout(input_layout)
    layout.addSpacing(8)

    btn_row = QHBoxLayout()
    btn_row.addStretch()

    cancel = make_button("Cancelar", "flat")
    cancel.clicked.connect(dlg.reject)
    btn_row.addWidget(cancel)

    confirm = make_button("Confirmar", "primary")
    confirm.clicked.connect(dlg.accept)
    btn_row.addWidget(confirm)

    input_field.returnPressed.connect(confirm.click)

    layout.addLayout(btn_row)

    if dlg.exec() == QDialog.DialogCode.Accepted:
        usafa_input = input_field.text().strip().upper()
        if usafa_input:
            config.set("usafa_name", f"USAFA {usafa_input}")
            return f"USAFA {usafa_input}"
    return None


def _prompt_usafa_name(config):
    """Prompt user to input USAFA name if not set."""
    usafa_name = config.get("usafa_name")
    if usafa_name and usafa_name.strip():
        return

    result = _show_usafa_dialog(config)
    if not result:
        sys.exit(0)


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
    # Set AppUserModelID + register icon in registry BEFORE QApplication.
    from pathlib import Path

    from andaime.win32 import register_taskbar_identity

    register_taskbar_identity(
        "SISTEMAS.RAC", "RAC", Path(__file__).resolve().parent / "icon.ico"
    )

    _apply_pending_update()

    from andaime.updater import get_shared_root

    app = andaime.App("RAC", "RAC", config_cls=RACConfig, db_cls=RACDatabase, root=get_shared_root(),
                      font=FontSpec("Geist", 11, bundled=True))

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

    apply_font(qapp, app.font)

    config = app.config
    _prompt_usafa_name(config)
    theme = config.get("theme", "dark")
    set_theme(theme)
    qapp.setStyleSheet(get_stylesheet())

    from rac.gui.main_window import MainWindow

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.init_backend()
    window.navigate_to("start")
    window.show()

    _start_update_check(window)

    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()