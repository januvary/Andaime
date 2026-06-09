"""
andaime — shared toolkit for PySide6 desktop apps
"""

import sys
from pathlib import Path

_app_name: str = ""
_app_folder: str = ""
_app_root: Path | None = None


def init(app_name: str, app_folder: str, root: Path) -> None:
    global _app_name, _app_folder, _app_root

    _app_name = app_name
    _app_folder = app_folder
    _app_root = root

    from andaime.error_handler import ErrorHandler

    ErrorHandler.init(app_name, _app_root)


def get_app_name() -> str:
    return _app_name


def get_app_folder() -> str:
    return _app_folder


def get_root_directory() -> Path:
    if _app_root is None:
        raise RuntimeError("andaime.init() must be called before using get_root_directory()")
    return _app_root


from andaime.app import App
