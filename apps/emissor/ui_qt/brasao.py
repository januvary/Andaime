#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brasão da Prefeitura (Qt). Os PNGs claro/escuro são pré-renderizados por
``tools/generate_brasao.py`` já com fundo da barra e tinta recolorida, evitando
QtSvg em runtime e garantindo visual idêntico entre fonte e build empacotado.
O resultado é cacheado por (altura, modo_escuro)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


def _resolver_caminho(tema: str) -> Path:
    """Resolve o PNG do brasão (funciona em fonte e empacotado via _MEIPASS)."""
    nome = f"brasao_{tema}.png"
    base = Path(__file__).resolve().parent / "assets"
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidato = Path(meipass) / "src" / "ui_qt" / "assets" / nome
            if candidato.exists():
                return candidato
    return base / nome


# Cache por (altura, modo_escuro) -> QPixmap
_pixmap_cache: dict[tuple[int, bool], QPixmap | None] = {}


def get_brasao_pixmap(height: int = 41, dark_mode: bool = True) -> QPixmap | None:
    """Retorna QPixmap do brasão dimensionado à altura (largura proporcional) e
    cacheado; None silencioso se o PNG não estiver disponível."""
    chave = (height, dark_mode)
    if chave in _pixmap_cache:
        return _pixmap_cache[chave]

    tema = "dark" if dark_mode else "light"
    caminho = _resolver_caminho(tema)
    if not caminho.exists():
        print(f"[AVISO] Brasão PNG não encontrado: {caminho}")
        _pixmap_cache[chave] = None
        return None

    pixmap = QPixmap(str(caminho))
    if pixmap.isNull():
        print(f"[AVISO] Falha ao carregar brasão: {caminho}")
        _pixmap_cache[chave] = None
        return None

    resultado = pixmap.scaledToHeight(
        height, Qt.TransformationMode.SmoothTransformation
    )
    _pixmap_cache[chave] = resultado
    return resultado
