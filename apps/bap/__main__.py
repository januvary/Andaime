import sys
from pathlib import Path
import os


# Repositório GitHub que hospeda os releases (zip) para o autoatualizador.
UPDATE_REPO = "januvary/BAP"


def _apply_pending_update():
    from andaime.updater import apply_pending_update

    apply_pending_update()


def _start_update_check(window):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QLabel

    from andaime.updater import UpdateCheckWorker, restart_app
    from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel
    from bap import __version__
    from bap.ui_qt.widgets.dialogs import confirm_dialog

    worker = UpdateCheckWorker(UPDATE_REPO, __version__, parent=window)

    def _on_downloaded(tag):
        if confirm_dialog(
            window,
            f"Atualização {tag}",
            "Uma nova versão foi baixada e está pronta para uso.\n"
            "Reinicie o aplicativo para aplicar a atualização.",
            confirm_label="Reiniciar",
            cancel_label="Mais tarde",
            cancel_role="flat",
            modal=True,
        ):
            restart_app()

    def _on_failed(msg):
        ErrorHandler.log(
            f"Update check failed: {msg}",
            level=ErrorLevel.WARNING,
            context=ErrorContext.UPDATER,
        )

    worker.update_ready.connect(_on_downloaded)
    worker.update_failed.connect(_on_failed)
    worker.no_update.connect(
        lambda: ErrorHandler.log("No update available", context=ErrorContext.UPDATER)
    )
    # Mantém referência para o worker não ser coletado pelo GC.
    window._update_worker = worker
    worker.start()


def main():
    from pathlib import Path

    # Set AppUserModelID + register icon in registry BEFORE QApplication.
    from andaime.win32 import register_taskbar_identity

    register_taskbar_identity(
        "SISTEMAS.BAP", "BAP", Path(__file__).resolve().parent / "icon.ico"
    )

    import andaime
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QIcon
    from bap.utils.config import SS54Config
    from bap.database.ss54_database import SS54Database

    # Config + error handler usam <root>/data por padrão (andaime).
    import andaime.config as _andaime_config
    from bap.utils.config import bap_data_dir

    _andaime_config.get_config_path = lambda: bap_data_dir() / "config.json"

    from andaime.updater import get_shared_root

    app = andaime.App("BAP", "BAP", config_cls=SS54Config, db_cls=SS54Database, root=get_shared_root())

    # Fecha o banco (backup síncrono) no atexit, fora da thread de UI.
    from andaime.shutdown import register_cleanup, setup_shutdown_handlers

    setup_shutdown_handlers()
    register_cleanup(app.db.close, "ss54_database")

    from bap.ui_qt.styles import set_theme, get_stylesheet, get_palette, qpalette

    qt_app = QApplication(sys.argv)

    # Window icon (taskbar + alt-tab)
    icon_path = Path(__file__).resolve().parent / "icon.ico"
    if icon_path.exists():
        qt_app.setWindowIcon(QIcon(str(icon_path)))

    from andaime.qt.dev_inspector import enable_if_env
    enable_if_env(qt_app)

    font = QFont("Segoe UI", 11)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    qt_app.setFont(font)

    theme = app.config.get("theme", "dark")
    set_theme(theme)
    qt_app.setPalette(qpalette(get_palette(theme == "dark")))
    qt_app.setStyleSheet(get_stylesheet())

    from bap.ui_qt.main_window import MainWindow
    from PySide6.QtCore import QTimer

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    QTimer.singleShot(0, window.init_backend)

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
