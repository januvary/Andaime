"""Utility functions for Sistema de Negativas"""

import re
import base64
from datetime import datetime
from typing import List
from pathlib import Path

from negativas.constants import MESES_PT, BRASAO_SVG_PATH

_CID_PATTERN = re.compile(r"[A-Z]\d{2}\.\d{1,2}")


def parse_cids(cids_text: str) -> List[str]:
    """Extrai códigos CID de texto

    Args:
        cids_text: Texto contendo códigos CID

    Returns:
        Lista ordenada de códigos CID únicos encontrados
    """
    if not cids_text:
        return []

    matches = _CID_PATTERN.findall(cids_text)

    return sorted(set(matches))


def data_por_extenso() -> str:
    """Retorna data atual por extenso em português."""
    now = datetime.now()
    return f"{now.day} de {MESES_PT[now.month - 1]} de {now.year}"


_svg_cache: str | None = None


def svg_base64() -> str:
    """Retorna o SVG do brasão em base64 (com cache)."""
    global _svg_cache
    if _svg_cache is None:
        try:
            _svg_cache = base64.b64encode(BRASAO_SVG_PATH.read_bytes()).decode()
        except Exception:
            _svg_cache = ""
    return _svg_cache
