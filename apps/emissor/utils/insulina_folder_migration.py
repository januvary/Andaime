#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migração de pastas de pacientes insulina (esquema anterior -> novo).

Esquema anterior: ``MANDADOS JUDICIAIS/<nome> - INSULINA`` (sufixo direto no
nível superior).

Esquema novo: ``MANDADOS JUDICIAIS/05 - INSULINA/<nome> - INSULINA``.

A migração é idempotente e segura para rodar a cada lançamento.

Regras:
1. Pastas com sufixo `` - INSULINA`` no nível superior são movidas para
   ``05 - INSULINA`` mantendo o nome.
2. Se houver duplicata de nome (pasta sem sufixo) no nível superior e ela
   estiver VAZIA, é removida; se não estiver vazia, é mantida e ambas coexistem.
3. Esquemas mais antigos (0-INSULINAS, prefixo ``INSULINA - ``) ficam de fora
   desta migração.
"""

from __future__ import annotations

from pathlib import Path

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

from emissor.utils.paths import (
    INSULINA_PARENT_FOLDER,
    INSULINA_SUFFIX,
    RECIBOS_PARENT_FOLDER,
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


def _move_to_insulina(
    src: Path,
    parent: Path,
    insulina_dir: Path,
    original_name: str,
) -> None:
    """Move/renomeia ``src`` para ``<insulina_dir>/<nome> - INSULINA``."""
    dest = insulina_dir / f"{original_name}{INSULINA_SUFFIX}"

    _drop_empty_duplicate(parent, original_name)

    if dest.exists():
        _log(ErrorLevel.WARNING, f"destino já existe, pulando: {dest}")
        return

    _log(ErrorLevel.INFO, f"{src} -> {dest}")
    src.rename(dest)


def migrate_insulina_folders(save_root: Path | None) -> None:
    """Migra as pastas de insulina do esquema anterior para o novo.

    Idempotente: pastas já dentro de ``05 - INSULINA`` são ignoradas.
    """
    if save_root is None:
        return

    parent = Path(save_root) / RECIBOS_PARENT_FOLDER
    if not parent.is_dir():
        return

    insulina_dir = parent / INSULINA_PARENT_FOLDER

    try:
        sources: list[tuple[Path, str]] = []
        for entry in sorted(parent.iterdir()):
            if not entry.is_dir() or entry.name == INSULINA_PARENT_FOLDER:
                continue
            if entry.name.endswith(INSULINA_SUFFIX):
                original_name = entry.name[: -len(INSULINA_SUFFIX)]
                sources.append((entry, original_name))

        if not sources:
            return

        insulina_dir.mkdir(parents=True, exist_ok=True)

        for src, original_name in sources:
            _move_to_insulina(src, parent, insulina_dir, original_name)
    except Exception as e:  # noqa: BLE001
        _log(ErrorLevel.ERROR, f"erro durante migração: {e}")