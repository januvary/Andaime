"""Compatibilidade: re-exporta o tema compartilhado de ``andaime.qt.theme``.

A paleta/QSS canônica vive em ``andaime.qt``; este módulo apenas
re-exporta a API para não quebrar os imports existentes.
"""

from andaime.qt.theme import (
    DARK,
    FONT_FAMILY,
    LIGHT,
    PX,
    PX_HEADER,
    PX_LARGE,
    PX_SMALL,
    colors,
    get_palette,
    get_stylesheet,
    get_theme,
    make_button,
    qpalette,
    set_theme,
    toggle_theme,
)

__all__ = [
    "DARK",
    "LIGHT",
    "FONT_FAMILY",
    "PX",
    "PX_SMALL",
    "PX_HEADER",
    "PX_LARGE",
    "colors",
    "get_palette",
    "get_stylesheet",
    "get_theme",
    "make_button",
    "qpalette",
    "set_theme",
    "toggle_theme",
]
