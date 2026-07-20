"""Compatibilidade: re-exporta o tema neutro compartilhado de ``andaime.qt.theme``
(a paleta/QSS canônica vive lá; ``brasao_ink`` e seleção vêm do tema)."""

from __future__ import annotations

from pathlib import Path

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
    get_stylesheet,
    get_theme,
    make_button,
    qpalette,
    set_theme,
    toggle_theme,
)


def get_palette(dark_mode: bool = True) -> dict[str, str]:
    """Paleta do Emissor (paleta compartilhada + ``brasao_ink``)."""
    return DARK if dark_mode else LIGHT


def _checkbox_overlay(palette: dict[str, str]) -> str:
    """QSS que preserva o glifo de checkmark do Emissor sobre o tema base."""
    assets_dir = Path(__file__).resolve().parent / "assets"
    check_svg = assets_dir / (
        "check-dark.svg" if palette is DARK else "check-light.svg"
    )
    check_url = str(check_svg).replace("\\", "/")
    c = palette
    return f"""
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 1px solid {c['input_border']};
        border-radius: 3px;
        background: {c['input_bg']};
    }}
    QCheckBox::indicator:checked {{
        background: {c['btn_primary']};
        border-color: {c['btn_primary']};
        image: url({check_url});
    }}
    """


def _radio_overlay(palette: dict[str, str]) -> str:
    """QSS que aplica cor de alto contraste ao radio selecionado."""
    accent = palette["text_dim"]
    return f"""
    QRadioButton::indicator:checked {{
        background: {accent};
        border-color: {accent};
    }}
    """


def stylesheet(palette: dict[str, str]) -> str:
    """QSS global (tema compartilhado + overlays de checkbox/radio do Emissor).

    Aceita o dict retornado por ``get_palette`` para manter compatibilidade
    com os chamadores existentes.
    """
    theme = "dark" if palette is DARK else "light"
    return (
        get_stylesheet(theme)
        + _checkbox_overlay(palette)
        + _radio_overlay(palette)
    )


__all__ = [
    "FONT_FAMILY",
    "PX",
    "PX_SMALL",
    "PX_HEADER",
    "PX_LARGE",
    "LIGHT",
    "DARK",
    "colors",
    "get_palette",
    "get_stylesheet",
    "get_theme",
    "make_button",
    "qpalette",
    "set_theme",
    "toggle_theme",
    "stylesheet",
    "ThemeToggleButton",
]
