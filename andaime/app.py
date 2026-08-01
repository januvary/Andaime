"""Application bootstrap for PySide6 desktop apps."""

import sys
from pathlib import Path
from typing import Generic, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from andaime.qt.fonts import FontSpec

import andaime
from andaime.config import ConfigManager
from andaime.database import BaseDatabase
from andaime.error_handler import ErrorHandler, ErrorLevel

_D = TypeVar("_D", bound=BaseDatabase)


def _is_path_reachable(path: Path) -> bool:
    """Quick reachability test: can we stat and list the directory?"""
    try:
        list(path.iterdir())
        return True
    except (OSError, PermissionError):
        return False


def _warn_network_unavailable(path: Path) -> None:
    """Show a warning when the network data root is unreachable."""
    msg = (
        f"Dados de rede indisponíveis: {path}\n\n"
        f"Usando dados locais. As alterações não serão sincronizadas "
        f"até que a conexão seja restaurada."
    )
    ErrorHandler.log(
        f"Network data root unreachable: {path}",
        level=ErrorLevel.WARNING,
        context="App",
    )
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0, msg, "SISTEMAS — Aviso", 0x30
            )
            return
        except Exception:
            pass
    print(f"[WARNING] {msg}", file=sys.stderr)


class App(Generic[_D]):
    def __init__(
        self,
        app_name: str,
        app_folder: str,
        config_cls: type,
        db_cls: type[_D],
        root: Path | None = None,
        font: "FontSpec | None" = None,
    ) -> None:
        self._app_name = app_name
        self._app_folder = app_folder
        self._font = font

        if root is not None:
            root_path = Path(root)
            if _is_path_reachable(root_path):
                self._root = root_path
            else:
                _warn_network_unavailable(root_path)
                self._root = self._detect_root()
        else:
            self._root = self._detect_root()

        andaime.init(app_name, app_folder, root=self._root)

        ConfigManager.init(config_cls)
        self._db: _D = db_cls()
        self._config = ConfigManager()

        # Signal successful init for post-update rollback monitoring.
        from andaime.updater import signal_post_update_success

        signal_post_update_success()

    @property
    def font(self) -> "FontSpec | None":
        return self._font

    def _detect_root(self) -> Path:
        exe = Path(sys.executable).resolve()

        # SISTEMAS Python-style: <install_root>/python/pythonw.exe
        if exe.parent.name == "python":
            candidate = exe.parent.parent
            if (candidate / "apps").is_dir() or (
                candidate / "VERSION"
            ).exists():
                return candidate

        # Frozen (legacy PyInstaller): exe directory IS the root
        if getattr(sys, "frozen", False):
            return Path(sys.executable).parent

        # Dev mode
        try:
            import __main__

            main_file = getattr(__main__, "__file__", None)
            if main_file is not None:
                p = Path(main_file).resolve()
                # apps/<module>/__main__.py → install root
                if p.parent.parent.name == "apps":
                    return p.parent.parent.parent
                return p.parent
        except (ImportError, AttributeError):
            pass

        return Path.cwd()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def db(self) -> _D:
        return self._db

    @property
    def config(self) -> ConfigManager:
        return self._config

    @property
    def app_name(self) -> str:
        return self._app_name

    @property
    def app_folder(self) -> str:
        return self._app_folder

    def get_data_root(self) -> Path:
        return self._root

    def shutdown(self) -> None:
        close = getattr(self._db, "close", None)
        if close is not None:
            close()

    @staticmethod
    def reset() -> None:
        from andaime.error_handler import ErrorHandler

        ConfigManager._reset()
        ErrorHandler._initialized = False
        ErrorHandler._logger = None
        ErrorHandler._show_dialog_callback = None
