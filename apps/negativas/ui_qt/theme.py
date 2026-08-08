"""Tema compartilhado Andaime para Sistema de Negativas."""

from andaime.qt.theme import (
    DARK,
    LIGHT,
    set_theme as _set_theme,
    get_theme as _get_theme,
    toggle_theme as _toggle_theme,
    colors as _colors,
    get_stylesheet as _get_stylesheet,
    qpalette as _qpalette,
    make_button as _make_button,
    ThemeToggleButton as _ThemeToggleButton,
)


def get_palette(dark_mode: bool = True) -> dict:
    """Retorna paleta apropriada para o modo especificado."""
    return DARK if dark_mode else LIGHT


def set_theme(theme: str) -> None:
    """Define o tema global."""
    _set_theme(theme)


def get_theme() -> str:
    """Retorna o tema atual."""
    return _get_theme()


def toggle_theme() -> str:
    """Alterna entre temas light/dark."""
    return _toggle_theme()


def colors() -> dict:
    """Retorna paleta de cores do tema atual."""
    return _colors()


def get_stylesheet(theme: str | None = None) -> str:
    """Retorna stylesheet do tema especificado (ou atual)."""
    resolved = theme or _get_theme()
    return _get_stylesheet(resolved)


def qpalette(palette: dict):
    """Cria QPalette a partir de paleta de cores."""
    return _qpalette(palette)


def make_button(text: str, role: str = "flat", parent=None):
    """Cria QPushButton com papel visual padronizado."""
    return _make_button(text, role, parent)


# Re-export ThemeToggleButton
ThemeToggleButton = _ThemeToggleButton


__all__ = [
    "DARK",
    "LIGHT",
    "set_theme",
    "get_theme",
    "toggle_theme",
    "colors",
    "get_stylesheet",
    "qpalette",
    "get_palette",
    "make_button",
    "ThemeToggleButton",
]