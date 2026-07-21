#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Path Management Utilities. Compartilhadas delegam ao andaime; específicas
do Emissor ficam aqui."""

from pathlib import Path

from andaime import paths as _andaime_paths

from emissor.utils.net_io import network_mkdir


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
INSULINA_SUFFIX = " - INSULINA"


def resolve_archive_dir(
    save_root: Path,
    patient_tipo: str,
    safe_patient_name: str,
    create: bool = True,
) -> Path:
    save_root = Path(save_root)

    parent = save_root / RECIBOS_PARENT_FOLDER
    if patient_tipo == "insulina":
        archive_dir = parent / f"{safe_patient_name}{INSULINA_SUFFIX}"
    else:
        archive_dir = parent / safe_patient_name

    if create:
        network_mkdir(archive_dir)

    return archive_dir
