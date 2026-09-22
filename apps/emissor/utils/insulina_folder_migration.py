#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migração de pastas insulina (anterior -> novo). Idempotente; sufixo -> 05, duplicatas removidas."""

from __future__ import annotations

from pathlib import Path

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from andaime.paths import find_parent_dir
from andaime.text import to_upper_normalized

from emissor.utils.paths import (
    INSULINA_PARENT_FOLDER,
    INSULINA_SUFFIX,
    RECIBOS_PARENT_FOLDER,
    find_matching_dir,
)


def _is_empty(directory: Path) -> bool:
    return not any(directory.iterdir())


def _log(level: ErrorLevel, msg: str) -> None:
    ErrorHandler.log(
        f"[insulina-migração] {msg}",
        level=level,
        context=ErrorContext.DATABASE,
    )


def _drop_empty_duplicate(parent: Path, original_name: str) -> None:
    """Remove duplicata vazia ou avisa se não vazia (match case/acento-insensível)."""
    duplicate = find_matching_dir(parent, original_name)
    if duplicate is None:
        return
    if _is_empty(duplicate):
        _log(ErrorLevel.INFO, f"duplicata vazia removida: {duplicate}")
        duplicate.rmdir()
    else:
        _log(
            ErrorLevel.WARNING,
            f"duplicata não vazia mantida: {duplicate} "
            f"(criada '{original_name}{INSULINA_SUFFIX}' separada)",
        )


def _move_to_insulina(
    src: Path,
    parent: Path,
    insulina_dir: Path,
    original_name: str,
) -> None:
    """Move src para insulina_dir com sufixo - INSULINA."""
    dest = insulina_dir / f"{original_name}{INSULINA_SUFFIX}"

    _drop_empty_duplicate(parent, original_name)

    if dest.exists() or find_matching_dir(insulina_dir, dest.name) is not None:
        _log(ErrorLevel.WARNING, f"destino já existe, pulando: {dest}")
        return

    _log(ErrorLevel.INFO, f"{src} -> {dest}")
    src.rename(dest)


def migrate_insulina_folders(save_root: Path | None) -> None:
    """Migra pastas insulina. Idempotente (ignora já em 05 - INSULINA)."""
    if save_root is None:
        return

    migration_root = find_parent_dir(save_root, RECIBOS_PARENT_FOLDER)
    if migration_root is None:
        _log(ErrorLevel.INFO, f"MANDADOS JUDICIAIS não encontrado a partir de {save_root}")
        return

    parent = migration_root / RECIBOS_PARENT_FOLDER

    insulina_dir = parent / INSULINA_PARENT_FOLDER

    try:
        sources: list[tuple[Path, str]] = []
        parent_key = to_upper_normalized(INSULINA_PARENT_FOLDER)
        suffix_key = to_upper_normalized(INSULINA_SUFFIX)
        for entry in sorted(parent.iterdir()):
            if not entry.is_dir() or to_upper_normalized(entry.name) == parent_key:
                continue
            if to_upper_normalized(entry.name).endswith(suffix_key):
                original_name = entry.name[: -len(INSULINA_SUFFIX)]
                sources.append((entry, original_name))

        if not sources:
            return

        insulina_dir.mkdir(parents=True, exist_ok=True)

        for src, original_name in sources:
            _move_to_insulina(src, parent, insulina_dir, original_name)
    except Exception as e:  # noqa: BLE001
        _log(ErrorLevel.ERROR, f"erro durante migração: {e}")