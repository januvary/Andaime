"""Bootstrap para ferramentas CLI: garante andaime + ConfigManager prontos."""
from __future__ import annotations

from pathlib import Path

import andaime
from andaime.config import ConfigManager

from src.utils.config import SS54Config


def ensure_initialized() -> None:
    """Garante que o andaime e o ConfigManager estão inicializados.

    Idempotente: no-op quando já inicializado (ex.: dentro do app em execução).
    Usado pelos entry points CLI standalone (import_remessas, export_to_xlsx).
    """
    if getattr(andaime, "_app_root", None) is None:
        andaime.init("BAP", "BAP", Path(".").resolve())
    ConfigManager.init(SS54Config)
