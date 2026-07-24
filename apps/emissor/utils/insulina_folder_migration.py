#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migração de pastas de pacientes insulina (esquemas antigos -> novo).

Esquemas antigos suportados:
- ``MANDADOS JUDICIAIS/0-INSULINAS/<nome>`` (subpasta dedicada)
- ``MANDADOS JUDICIAIS/INSULINA - <nome>`` (prefixo)

Esquema novo: sufixo ``MANDADOS JUDICIAIS/<nome> - INSULINA``.

A migração é idempotente e segura para rodar a cada lançamento.

Regras:
1. Pastas em 0-INSULINAS são movidas para o nível superior com sufixo
   `` - INSULINA``.
2. Pastas com prefixo ``INSULINA - `` no nível superior são renomeadas para
   o sufixo.
3. Se houver duplicata de nome (pasta sem sufixo) e ela estiver VAZIA,
   é removida; se não estiver vazia, é mantida e ambas coexistem.
4. Ao final, a pasta 0-INSULINAS é removida se vazia.
"""

from __future__ import annotations

from pathlib import Path

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

from emissor.utils.paths import RECIBOS_PARENT_FOLDER

INSULINA_PREFIX = "INSULINA - "
INSULINA_SUFFIX = " - INSULINA"
INSULINA_ARCHIVE_FOLDER = "0-INSULINAS"


def _is_empty(directory: Path) -> bool:
    return not any(directory.iterdir())


def _log(level: ErrorLevel, msg: str) -> None:
    ErrorHandler.log(
        f"[insulina-migração] {msg}",
        level=level,
        context=ErrorContext.DATABASE,
    )


def _drop_empty_duplicate(parent: Path, original_name: str) -> None:
    """Remove duplicata sem sufixo se estiver vazia; avisa se não estiver."""
    duplicate = parent / original_name
    if not (duplicate.exists() and duplicate.is_dir()):
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


def _move_to_suffix(src: Path, parent: Path, original_name: str) -> None:
    """Move/renomeia ``src`` para ``parent/<nome> - INSULINA`` com segurança."""
    dest = parent / f"{original_name}{INSULINA_SUFFIX}"

    _drop_empty_duplicate(parent, original_name)

    if dest.exists():
        _log(ErrorLevel.WARNING, f"destino já existe, pulando: {dest}")
        return

    _log(ErrorLevel.INFO, f"{src} -> {dest}")
    src.rename(dest)


def migrate_insulina_folders(save_root: Path | None) -> None:
    """Migra as pastas de insulina dos esquemas antigos para o novo.

    Idempotente: pastas já no formato ``<nome> - INSULINA`` são ignoradas.
    """
    if save_root is None:
        return

    parent = Path(save_root) / RECIBOS_PARENT_FOLDER
    if not parent.is_dir():
        return

    try:
        old_archive = parent / INSULINA_ARCHIVE_FOLDER
        if old_archive.is_dir():
            for src in sorted(old_archive.iterdir()):
                if src.is_dir():
                    _move_to_suffix(src, parent, src.name)
            if _is_empty(old_archive):
                old_archive.rmdir()
                _log(ErrorLevel.INFO, f"pasta antiga removida: {old_archive}")
            else:
                _log(
                    ErrorLevel.WARNING,
                    f"{old_archive} não está vazia, mantida.",
                )

        for entry in sorted(parent.iterdir()):
            if (
                entry.is_dir()
                and entry.name.startswith(INSULINA_PREFIX)
                and not entry.name.endswith(INSULINA_SUFFIX)
            ):
                original_name = entry.name[len(INSULINA_PREFIX) :]
                _move_to_suffix(entry, parent, original_name)
    except Exception as e:  # noqa: BLE001
        _log(ErrorLevel.ERROR, f"erro durante migração: {e}")
