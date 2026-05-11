"""
Path management utilities.
"""

from pathlib import Path

import andaime
from andaime.error_handler import ErrorHandler, ErrorLevel


def get_root_directory() -> Path:
    return andaime.get_root_directory()


def resolve_db_path(db_filename: str, create_dir: bool = True) -> str:
    root_dir = get_root_directory()

    db_in_data_dir = root_dir / "data" / db_filename
    db_in_root = root_dir / db_filename

    if db_in_data_dir.exists():
        return str(db_in_data_dir)

    if db_in_root.exists():
        return str(db_in_root)

    chosen_path = db_in_data_dir

    if create_dir:
        chosen_path.parent.mkdir(parents=True, exist_ok=True)
        ErrorHandler.log(
            f"Criando diretório: {chosen_path.parent}",
            level=ErrorLevel.INFO,
            context="File I/O",
        )

    return str(chosen_path)


def get_config_path() -> Path:
    root_dir = get_root_directory()

    data_config = root_dir / "data" / "config.json"
    if data_config.exists():
        return data_config

    root_config = root_dir / "config.json"
    if root_config.exists():
        return root_config

    return data_config
