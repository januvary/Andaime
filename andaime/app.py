"""Application bootstrap for PySide6 desktop apps."""

import shutil
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
                self._root = root_path / app_folder
            else:
                _warn_network_unavailable(root_path)
                self._root = self._detect_root()
        else:
            self._root = self._detect_root()

        # CRITICAL: Migrate legacy data BEFORE andaime.init() to avoid conflicts
        if getattr(sys, "frozen", False):
            self._migrate_legacy_data(app_folder)

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

    def _migrate_legacy_data(self, app_folder: str) -> None:
        """Migrate data from buggy layout to correct layout.

        Legacy bug: _detect_root() returned exe_dir.parent when exe_dir.name == app_folder
        This caused data to be created at <dist>/data/ instead of <dist>/<app>/data/

        This method detects and safely migrates data to the correct location.
        """
        import threading
        import time

        exe_dir = Path(sys.executable).parent

        # Only relevant for frozen builds where exe is in a subdirectory
        if exe_dir.name != app_folder:
            return

        # The buggy behavior would have used parent as root
        old_buggy_root = exe_dir.parent
        # The fixed behavior uses exe_dir as root (which is now self._root)
        new_correct_root = exe_dir

        old_data = old_buggy_root / "data"
        new_data = new_correct_root / "data"

        # Skip if no legacy data exists
        if not old_data.exists():
            return

        # Skip if data already exists at correct location (user might have manually moved it)
        if new_data.exists():
            ErrorHandler.log(
                f"Skipping migration: target {new_data} already exists",
                level=ErrorLevel.WARNING,
                context="Migration",
            )
            return

        try:
            ErrorHandler.log(
                f"Starting migration: {old_data} -> {new_data}",
                level=ErrorLevel.INFO,
                context="Migration",
            )

            # 1. Create backup with timestamp
            timestamp = int(time.time())
            backup = old_data.with_suffix(f".backup_{timestamp}")
            shutil.copytree(old_data, backup)

            # 2. Copy to temp location first for verification
            temp = new_data.with_suffix(".temp")
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)
            shutil.copytree(old_data, temp)

            # 3. Verify critical files exist in temp (be flexible with filenames)
            found_db = False
            found_config = False
            for item in temp.iterdir():
                if item.is_file():
                    if item.suffix == ".db":
                        found_db = True
                    if item.name == "config.json":
                        found_config = True

            if not found_db and not found_config:
                raise FileNotFoundError("No critical data files found after copy")

            # 4. Atomic move to final location
            temp.rename(new_data)

            # 5. Clean up old location completely after successful migration
            try:
                shutil.rmtree(old_data, ignore_errors=True)
            except Exception as cleanup_error:
                ErrorHandler.log(
                    f"Could not remove old data directory {old_data}: {cleanup_error}",
                    level=ErrorLevel.WARNING,
                    context="Migration",
                )

            # 6. Schedule backup cleanup after 24 hours
            def cleanup_backup():
                time.sleep(86400)  # 24 hours
                try:
                    if backup.exists():
                        shutil.rmtree(backup, ignore_errors=True)
                except Exception:
                    pass

            threading.Thread(target=cleanup_backup, daemon=True).start()

            ErrorHandler.log(
                f"Dados migrados com sucesso de {old_data} para {new_data}",
                level=ErrorLevel.INFO,
                context="Migration",
            )

        except Exception as e:
            # Rollback: restore from backup if something went wrong
            try:
                if backup.exists():
                    if temp.exists():
                        shutil.rmtree(temp, ignore_errors=True)
                    if old_data.exists():
                        shutil.rmtree(old_data, ignore_errors=True)
                    shutil.copytree(backup, old_data)
            except Exception as rollback_error:
                ErrorHandler.log(
                    f"Migration rollback failed: {rollback_error}",
                    level=ErrorLevel.ERROR,
                    context="Migration",
                )

            ErrorHandler.log(
                f"Falha na migração de dados: {e}. Backup mantido em {backup}",
                level=ErrorLevel.ERROR,
                context="Migration",
            )

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
