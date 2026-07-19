#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migração de pastas de pacientes insulina (esquema antigo -> novo).

O esquema antigo guardava pacientes de insulina numa subpasta
``MANDADOS JUDICIAIS/0-INSULINAS/<nome>``. O novo esquema usa prefixo
``INSULINA - `` direto em ``MANDADOS JUDICIAIS/<INSULINA - nome>``.

A migração é idempotente: se a pasta ``0-INSULINAS`` já não existir, não faz
nada. Por isso é seguro dispará-la a cada lançamento (first-launch friendly).

Regras:
1. Para cada pasta em 0-INSULINAS, procura duplicata de nome no nível superior
   de MANDADOS JUDICIAIS.
2. Se houver duplicata e ela estiver VAZIA, é removida.
3. A pasta de insulina é renomeada para 'INSULINA - <nome>' e movida para o
   nível superior de MANDADOS JUDICIAIS.
4. Ao final, a pasta 0-INSULINAS é removida se vazia.
"""

from __future__ import annotations

from pathlib import Path

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

from emissor.utils.paths import RECIBOS_PARENT_FOLDER

INSULINA_PREFIX = "INSULINA - "
INSULINA_ARCHIVE_FOLDER = "0-INSULINAS"


def _is_empty(directory: Path) -> bool:
    return not any(directory.iterdir())


def migrate_insulina_folders(save_root: Path | None) -> None:
    """Migra as pastas de insulina do esquema antigo para o novo.

    Roda de forma idempotente: se não houver ``0-INSULINAS``, retorna cedo.
    """
    if save_root is None:
        return

    parent = Path(save_root) / RECIBOS_PARENT_FOLDER
    old_archive = parent / INSULINA_ARCHIVE_FOLDER

    if not old_archive.is_dir():
        return

    try:
        for src in sorted(old_archive.iterdir()):
            if not src.is_dir():
                continue

            original_name = src.name
            new_name = f"{INSULINA_PREFIX}{original_name}"
            dest = parent / new_name

            duplicate = parent / original_name
            if duplicate.exists() and duplicate.is_dir():
                if _is_empty(duplicate):
                    ErrorHandler.log(
                        f"[insulina-migração] duplicata vazia removida: {duplicate}",
                        level=ErrorLevel.INFO,
                        context=ErrorContext.DATABASE,
                    )
                    duplicate.rmdir()
                else:
                    ErrorHandler.log(
                        f"[insulina-migração] duplicata não vazia mantida: "
                        f"{duplicate} (criada '{new_name}' separada)",
                        level=ErrorLevel.WARNING,
                        context=ErrorContext.DATABASE,
                    )

            if dest.exists():
                ErrorHandler.log(
                    f"[insulina-migração] destino já existe, pulando: {dest}",
                    level=ErrorLevel.WARNING,
                    context=ErrorContext.DATABASE,
                )
                continue

            ErrorHandler.log(
                f"[insulina-migração] {src} -> {dest}",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )
            src.rename(dest)

        if _is_empty(old_archive):
            old_archive.rmdir()
            ErrorHandler.log(
                f"[insulina-migração] pasta antiga removida: {old_archive}",
                level=ErrorLevel.INFO,
                context=ErrorContext.DATABASE,
            )
        else:
            ErrorHandler.log(
                f"[insulina-migração] {old_archive} não está vazia, mantida.",
                level=ErrorLevel.WARNING,
                context=ErrorContext.DATABASE,
            )
    except Exception as e:  # noqa: BLE001
        ErrorHandler.log(
            f"[insulina-migração] erro durante migração: {e}",
            level=ErrorLevel.ERROR,
            context=ErrorContext.DATABASE,
        )
