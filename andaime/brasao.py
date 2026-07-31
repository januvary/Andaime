"""Helpers de renderização do brasão (andaime).

Renderiza a silhueta do SVG do brasão e a recolorida conforme a tinta do tema,
preservando o alpha. Compartilhado entre ``tools/generate_brasao.py`` (gera os
PNG estáticos) e o editor de tema (pré-visualização ao vivo).

Usage:
    from andaime.brasao import render_brasao_silhouette, recolor_brasao
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def render_brasao_silhouette(
    svg_path: str | Path,
    height: int,
    supersample: int = 1,
) -> QPixmap:
    """Renderiza o SVG do brasão em um QPixmap transparente (tinta preta).

    Args:
        svg_path: Caminho do SVG do brasão.
        height: Altura de renderização em px (antes da superamostragem).
        supersample: Fator de superamostragem para nitidez em HiDPI.

    Returns:
        Silhueta em QPixmap (alpha = formato; cor = preta).
    """
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise RuntimeError(f"SVG do brasão inválido: {svg_path}")

    tamanho = renderer.defaultSize()
    if tamanho.width() <= 0 or tamanho.height() <= 0:
        proporcao = 1728.0 / 1867.0
    else:
        proporcao = tamanho.width() / tamanho.height()

    altura = height * supersample
    largura = max(1, int(round(altura * proporcao)))
    alvo = QSize(largura, altura)

    base = QPixmap(alvo)
    base.fill(Qt.GlobalColor.transparent)
    p = QPainter(base)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p, QRect(0, 0, largura, altura))
    p.end()
    return base


def recolor_brasao(silhouette: QPixmap, ink: str) -> QPixmap:
    """Recolor a silhueta (preta) para a tinta do tema, preservando o alpha.

    Args:
        silhouette: Pixmap transparente vindo de ``render_brasao_silhouette``.
        ink: Cor de tinta (#rrggbb) do brasão.

    Returns:
        Pixmap da silhueta recolorida (alpha preservado).
    """
    alvo = silhouette.size()
    colorido = QPixmap(alvo)
    colorido.fill(QColor(ink))
    p = QPainter(colorido)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawPixmap(0, 0, silhouette)
    p.end()
    return colorido
