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
    "context_menu_stylesheet",
]


def context_menu_stylesheet() -> str:
    """QSS consistente para os menus de contexto da aplicação."""
    c = colors()
    return f"""
        QMenu {{
            background-color: {c['panel_bg']};
            border: 1px solid {c['panel_border']};
            border-radius: 4px;
            padding: 4px;
        }}
        QMenu::item {{
            background-color: transparent;
            padding: 6px 20px;
            border-radius: 3px;
            color: {c['text']};
        }}
        QMenu::item:selected {{
            background-color: {c['bg_hover']};
        }}
        QMenu::item:checked {{
            background-color: {c['selection_bg']};
            color: {c['selection_text']};
        }}
        QMenu::item:checked:selected {{
            background-color: {c['selection_bg']};
            color: {c['selection_text']};
        }}
        QMenu::indicator {{
            width: 0px;
            margin: 0px;
        }}
    """
