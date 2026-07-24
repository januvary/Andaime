"""Application bootstrap for PySide6 desktop apps."""

import sys
from pathlib import Path
from typing import Generic, TypeVar

import andaime
from andaime.config import ConfigManager
from andaime.database import BaseDatabase

_D = TypeVar("_D", bound=BaseDatabase)


class App(Generic[_D]):
    def __init__(
        self,
        app_name: str,
        app_folder: str,
        config_cls: type,
        db_cls: type[_D],
        root: Path | None = None,
    ) -> None:
        self._app_name = app_name
        self._app_folder = app_folder
        if root is not None:
            self._root = Path(root) / app_folder
        else:
            self._root = self._detect_root()

        andaime.init(app_name, app_folder, root=self._root)

        ConfigManager.init(config_cls)
        self._db: _D = db_cls()
        self._config = ConfigManager()

    def _detect_root(self) -> Path:
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).parent
            if exe_dir.name == self._app_folder:
                return exe_dir.parent
            return exe_dir

        try:
            import __main__

            main_file = getattr(__main__, "__file__", None)
            if main_file is not None:
                return Path(main_file).resolve().parent
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
