"""Gerenciamento unificado de fontes para apps Qt.

Cada app define uma ``FontSpec`` que vive em ``andaime.App``. No momento de
inicializar a UI o main.py chama ``apply_font(qapp, app.font)``, que:

1. Carrega fontes empacotadas em ``<root>/fonts/`` (se ``bundled=True``).
2. Aplica a fonte padrão no ``QApplication``.
3. Configura a família usada pelo QSS global de ``andaime.qt.theme``.

Também expõe helpers de desenvolvedor para baixar fontes do Fontsource
(Google Fonts) e colocá-las no projeto.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import URLError

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from andaime import get_root_directory
from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel


@dataclass
class FontSpec:
    """Especificação de fonte para um app.

    Attributes:
        family: nome da família (ex: "IBM Plex Mono", "Geist").
        size: tamanho base em pontos.
        style_hint: hint usado pelo Qt quando a fonte não está disponível.
        bundled: se True, ``apply_font`` carrega arquivos de ``<root>/fonts/``
            antes de aplicar a família.
        fontsource_id: id opcional no Fontsource (ex: "ibm-plex-mono"). Se
            None, o download normaliza ``family`` (minúsculas, espaços -> '-').
    """

    family: str
    size: int = 11
    style_hint: QFont.StyleHint = QFont.StyleHint.SansSerif
    bundled: bool = True
    fontsource_id: str | None = None


def _fonts_dir() -> Path:
    """Retorna ``<andaime_root>/fonts``; cria se necessário."""
    return get_root_directory() / "fonts"


def load_bundled_fonts(fonts_dir: Path | None = None) -> list[str]:
    """Carrega todos os arquivos ``.ttf``/``.otf`` do diretório no Qt.

    Retorna a lista de família(s) efetivamente registradas.
    """
    target = fonts_dir or _fonts_dir()
    loaded_families: list[str] = []
    if not target.is_dir():
        return loaded_families

    for f in target.iterdir():
        if f.suffix.lower() not in (".ttf", ".otf"):
            continue
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid == -1:
            ErrorHandler.log(
                f"Failed to load bundled font: {f}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.UI,
            )
            continue
        loaded_families.extend(QFontDatabase.applicationFontFamilies(fid))
    return loaded_families


def apply_font(qapp: QApplication, font: FontSpec | None) -> None:
    """Aplica uma ``FontSpec`` no app Qt e no tema compartilhado."""
    if font is None:
        return

    if font.bundled:
        load_bundled_fonts()

    qfont = QFont(font.family, font.size)
    qfont.setStyleHint(font.style_hint)
    qapp.setFont(qfont)

    # Também configura a família no QSS global.
    from andaime.qt.theme import set_font_family

    set_font_family(font.family)


# -----------------------------------------------------------------------------
# Helpers de desenvolvimento (download de fontes)
# -----------------------------------------------------------------------------


FONTSOURCE_API = "https://api.fontsource.org/v1/fonts"
FONTSOURCE_CDN = "https://cdn.jsdelivr.net/fontsource/fonts"


def _fontsource_id(family: str) -> str:
    """Normaliza nome de família para id do Fontsource."""
    return family.lower().replace(" ", "-")


def download_font(
    family_id: str,
    output_dir: Path,
    subsets: Iterable[str] = ("latin",),
    weights: Iterable[str] = ("400", "700"),
    styles: Iterable[str] = ("normal", "italic"),
) -> None:
    """Baixa arquivos TTF de uma família do Fontsource.

    O ``family_id`` deve ser o id usado na URL (ex: ``ibm-plex-mono``).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    url = f"{FONTSOURCE_API}/{family_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "andaime-fonts/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (URLError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not fetch font metadata from {url}: {exc}") from exc

    family_name = data.get("family", family_id)
    variants = data.get("variants", {})

    for weight, styles_data in variants.items():
        if str(weight) not in weights:
            continue
        for style, subsets_data in styles_data.items():
            if style not in styles:
                continue
            for subset, urls in subsets_data.items():
                if subset not in subsets:
                    continue
                ttf_url = urls.get("url", {}).get("ttf")
                if not ttf_url:
                    continue
                filename = f"{family_name.replace(' ', '')}-{weight}-{style}-{subset}.ttf"
                dest = output_dir / filename
                try:
                    req = urllib.request.Request(ttf_url, headers={"User-Agent": "andaime-fonts/1.0"})
                    with urllib.request.urlopen(req, timeout=60) as response:
                        dest.write_bytes(response.read())
                except URLError as exc:
                    raise RuntimeError(f"Could not download {ttf_url}: {exc}") from exc


def download_bundled_font(
    font: FontSpec,
    output_dir: Path | None = None,
    subsets: Iterable[str] = ("latin",),
    weights: Iterable[str] = ("400", "700"),
    styles: Iterable[str] = ("normal", "italic"),
) -> None:
    """Baixa os arquivos TTF de uma ``FontSpec`` para ``<root>/fonts``."""
    target = output_dir or _fonts_dir()
    family_id = font.fontsource_id or _fontsource_id(font.family)
    download_font(family_id, target, subsets, weights, styles)


def download_font_by_name(
    family: str,
    output_dir: Path,
    subsets: Iterable[str] = ("latin",),
    weights: Iterable[str] = ("400", "700"),
    styles: Iterable[str] = ("normal", "italic"),
    fontsource_id: str | None = None,
) -> None:
    """Conveniência: baixa fonte pelo nome de família."""
    family_id = fontsource_id or _fontsource_id(family)
    download_font(family_id, output_dir, subsets, weights, styles)
