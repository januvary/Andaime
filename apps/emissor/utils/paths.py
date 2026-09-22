#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Path Management Utilities. Compartilhadas delegam ao andaime; específicas
do Emissor ficam aqui."""

from pathlib import Path

from andaime import paths as _andaime_paths
from andaime.text import to_upper_normalized

from andaime.net_io import network_mkdir


def ensure_data_dir_exists() -> Path:
    data_dir = _andaime_paths.get_root_directory() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def resolve_app_exe(app_name: str) -> Path | None:
    """Resolve o executável standalone (pastas irmãs/filhas/raiz; .exe ou sem
    extensão, Windows/Linux/Mac); None se não encontrado."""
    root_dir = _andaime_paths.get_root_directory()

    candidates = [
        root_dir.parent / app_name / f"{app_name}",
        root_dir.parent / app_name / f"{app_name}.exe",
        root_dir / app_name / f"{app_name}",
        root_dir / app_name / f"{app_name}.exe",
        root_dir / f"{app_name}",
        root_dir / f"{app_name}.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


RECIBOS_PARENT_FOLDER = "MANDADOS JUDICIAIS"
INSULINA_PARENT_FOLDER = "05 - INSULINA"
INSULINA_SUFFIX = " - INSULINA"


def find_matching_dir(parent: Path, name: str) -> Path | None:
    """Pasta em ``parent`` cujo nome casa sem case/acento, ou None."""
    key = to_upper_normalized(name)
    if not key or not parent.is_dir():
        return None
    for entry in sorted(parent.iterdir()):
        if entry.is_dir() and to_upper_normalized(entry.name) == key:
            return entry
    return None


def resolve_archive_dir(
    save_root: Path,
    patient_tipo: str,
    safe_patient_name: str,
    create: bool = True,
) -> Path:
    """Resolve a pasta de arquivo do paciente; matching case/acento-insensível
    (reaproveita pasta existente com grafia diferente em vez de duplicar)."""
    save_root = Path(save_root)

    parent = save_root / RECIBOS_PARENT_FOLDER
    if patient_tipo == "insulina":
        parent = parent / INSULINA_PARENT_FOLDER
        target_name = f"{safe_patient_name}{INSULINA_SUFFIX}"
    else:
        target_name = safe_patient_name

    archive_dir = parent / target_name
    if archive_dir.is_dir():
        return archive_dir

    existing = find_matching_dir(parent, target_name)
    if existing is not None:
        return existing

    if create:
        network_mkdir(archive_dir)

    return archive_dir
