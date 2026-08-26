from __future__ import annotations

from typing import Callable
from pathlib import Path
from contextlib import contextmanager

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPixmap, QIcon
from PySide6.QtWidgets import QPushButton

from bap.models import GridItem
from bap.ui_qt.styles import colors, get_theme
from andaime.pdf import render_page

_ICON_DIR = Path(__file__).resolve().parent / "img"

BTN_STYLE = (
    "QPushButton {"
    " background: transparent;"
    f" border: 1px solid {colors()['panel_border']};"
    " border-radius: 4px; padding: 0px;"
    f" color: {colors()['text']}; }}"
    " QPushButton:hover {"
    f" background: {colors()['bg_hover']};"
    f" border: 1px solid {colors()['text_dim']}; }}"
)


def icon_path(base: str) -> str:
    suffix = "-white" if get_theme() == "dark" else ""
    png_path = _ICON_DIR / f"{base}{suffix}.png"
    if png_path.exists():
        return str(png_path)
    return str(_ICON_DIR / f"{base}{suffix}.svg")


def make_icon_button(
    icon: str,
    tooltip: str,
    handler: Callable,
    parent: object = None,
) -> QPushButton:
    btn = QPushButton(parent)
    btn.setIcon(QIcon(icon_path(icon)))
    btn.setIconSize(QSize(16, 16))
    btn.setFixedSize(26, 22)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(BTN_STYLE)
    btn.clicked.connect(handler)
    return btn


@contextmanager
def _resolve_item_page(
    item: GridItem,
    loader: "Callable[[GridItem], bytes | None] | None" = None,
    scale: float = 2.0,
):
    """Resolve um item em ``(qimage, image_path)`` para renderização.

    Para PDFs, renderiza a página via ``andaime.pdf``. Para imagens em disco,
    devolve o caminho para carga direta via ``QImage(path)``.
    """
    page_no = item.page or 0

    if (
        item.data is None
        and item.path is not None
        and Path(item.path).suffix.lower() != ".pdf"
    ):
        yield None, item.path
        return

    raw = item.raw_bytes(loader)
    if not raw:
        yield None, None
        return

    try:
        yield render_page(raw, page_no, scale), None
    except Exception:
        yield None, None


def resolve_item_image(
    item: GridItem,
    loader: "Callable[[GridItem], bytes | None] | None" = None,
    scale: float = 2.0,
) -> QImage | None:
    """Resolve um GridItem a um QImage, ou None se indisponível."""
    with _resolve_item_page(item, loader, scale) as (qimage, image_path):
        if qimage is not None:
            return qimage
        if image_path is not None:
            img = QImage(image_path)
            return None if img.isNull() else img
        return None
