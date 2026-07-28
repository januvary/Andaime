#!/usr/bin/env python3
"""Pré-renderiza os ícones SVG dos botões da tile em PNG.

Evita dependência do plugin ``iconengines/qsvgicon.dll`` em runtime: a UI
carrega PNGs estáticos, garantindo que os botões da grade de documentos
apareçam corretamente no build empacotado.

Uso:
    python tools/generate_tile_icons.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "src" / "ui_qt" / "img"

# Tamanho de exibição dos botões (16x16) com superamostragem para HiDPI.
DISPLAY_SIZE = 16
SUPERSAMPLE = 4


_ICONS = [
    "copy-icon",
    "copy-icon-white",
    "preview-icon",
    "preview-icon-white",
    "rotate-icon",
    "rotate-icon-white",
    "X-icon",
    "X-icon-white",
]


def _render(svg_path: Path, size: int, supersample: int) -> QPixmap:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"SVG inválido: {svg_path}")

    target = QSize(size * supersample, size * supersample)
    pm = QPixmap(target)
    pm.fill(Qt.GlobalColor.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p, QRect(0, 0, target.width(), target.height()))
    p.end()
    return pm


def main() -> None:
    if not ICON_DIR.exists():
        raise SystemExit(f"Diretório não encontrado: {ICON_DIR}")

    QApplication([])
    total = 0
    for base in _ICONS:
        svg_path = ICON_DIR / f"{base}.svg"
        png_path = ICON_DIR / f"{base}.png"
        if not svg_path.exists():
            print(f"[SKIP] SVG não encontrado: {svg_path}")
            continue

        pm = _render(svg_path, DISPLAY_SIZE, SUPERSAMPLE)
        if not pm.save(str(png_path)):
            raise RuntimeError(f"Falha ao salvar: {png_path}")
        print(f"[OK] {png_path} ({pm.width()}x{pm.height()})")
        total += 1

    print(f"[OK] {total} ícone(s) gerado(s)")


if __name__ == "__main__":
    main()
