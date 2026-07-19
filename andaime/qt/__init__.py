"""andaime.qt — framework de UI Qt neutro e reutilizável.

Componentes compartilhados entre apps (Emissor, SS-54, ...):
tema/paleta, botões, e a barra superior genérica (``TopBar``).
"""

from __future__ import annotations

from andaime.qt.theme import (
    DARK,
    FONT_FAMILY,
    LIGHT,
    PX,
    PX_HEADER,
    PX_LARGE,
    PX_SMALL,
    ThemeToggleButton,
    colors,
    get_palette,
    get_stylesheet,
    make_button,
    qpalette,
    set_theme,
    stylesheet,
    toggle_theme,
)
from andaime.qt.top_bar import TopBar
from andaime.qt.bottom_bar import BottomBar
from andaime.qt.toggle_group import ToggleGroup
from andaime.qt.shortcuts import ShortcutManager
from andaime.qt.db_runner import DbAsyncRunner
from andaime.qt.fs import reveal_path, relative_path
from andaime.qt.status_line import StatusLine
from andaime.qt.table import (
    ColumnSpec,
    NoElideDelegate,
    TableViewModel,
    configure_table_view,
    table_batch_populate,
)

__all__ = [
    "DARK",
    "LIGHT",
    "FONT_FAMILY",
    "PX",
    "PX_SMALL",
    "PX_HEADER",
    "PX_LARGE",
    "ThemeToggleButton",
    "make_button",
    "colors",
    "get_palette",
    "get_stylesheet",
    "stylesheet",
    "qpalette",
    "set_theme",
    "toggle_theme",
    "TopBar",
    "BottomBar",
    "ToggleGroup",
    "ShortcutManager",
    "DbAsyncRunner",
    "reveal_path",
    "StatusLine",
    "relative_path",
    "NoElideDelegate",
    "table_batch_populate",
    "ColumnSpec",
    "TableViewModel",
    "configure_table_view",
]
