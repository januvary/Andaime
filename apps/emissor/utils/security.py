#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Security Utilities — validação de caminhos e sanitização de nomes."""

import re
from pathlib import Path


def validate_file_path(file_path: str, allow_nonexistent: bool = False) -> Path:
    """Valida caminho de arquivo (não vazio, existe a menos que permitido, é
    arquivo). Levanta ValueError se falhar."""
    if not file_path or not isinstance(file_path, str):
        raise ValueError("File path must be a non-empty string")

    try:
        path = Path(file_path)
    except (OSError, ValueError) as e:
        raise ValueError(f"Invalid file path: {e}")

    if not allow_nonexistent and not path.exists():
        raise ValueError(f"File path does not exist: {path}")

    if path.exists() and not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    return path


def validate_directory_path(dir_path: str, create_if_missing: bool = False) -> Path:
    """Valida diretório (não vazio, existe e é diretório; cria se solicitado).
    Levanta ValueError se falhar."""
    if not dir_path or not isinstance(dir_path, str):
        raise ValueError("Directory path must be a non-empty string")

    try:
        path = Path(dir_path)
    except (OSError, ValueError) as e:
        raise ValueError(f"Invalid directory path: {e}")

    if not path.exists():
        if create_if_missing:
            try:
                path.mkdir(parents=True, exist_ok=True)
                return path
            except OSError as e:
                raise ValueError(f"Failed to create directory: {e}")
        else:
            raise ValueError(f"Directory path does not exist: {path}")

    if not path.is_dir():
        raise ValueError(f"Path is not a directory: {path}")

    return path


def sanitize_filename(filename: str) -> str:
    """Sanitiza nome de arquivo: remove caracteres inválidos (Windows:
    < > : " / \\ | ? * e controles). Levanta ValueError se ficar vazio."""
    if not filename or not isinstance(filename, str):
        raise ValueError("Filename must be a non-empty string")

    sanitized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(". ")
    sanitized = re.sub(r"_+", "_", sanitized)

    if not sanitized:
        raise ValueError(f"Filename '{filename}' became empty after sanitization")

    return sanitized
