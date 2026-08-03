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
_current_svg_color: str | None = None


def svg_base64() -> str:
    """Retorna o SVG do brasão em base64 (com cache e cor de tema)."""
    global _svg_cache, _current_svg_color
    
    # Get current theme color
    try:
        from negativas.ui_qt.theme import colors
        theme_color = colors().get("text", "#000000")
    except ImportError:
        theme_color = "#000000"
    
    # Check if we need to regenerate the SVG
    if _svg_cache is None or _current_svg_color != theme_color:
        try:
            svg_content = BRASAO_SVG_PATH.read_text(encoding='utf-8')
            # Replace hardcoded fill color with theme color
            svg_colored = svg_content.replace('fill="#000000"', f'fill="{theme_color}"')
            _svg_cache = base64.b64encode(svg_colored.encode('utf-8')).decode()
            _current_svg_color = theme_color
        except Exception:
            _svg_cache = ""
            _current_svg_color = None
    
    return _svg_cache


def clear_svg_cache():
    """Limpa o cache do SVG para forçar regeneração com nova cor de tema."""
    global _svg_cache, _current_svg_color
    _svg_cache = None
    _current_svg_color = None
