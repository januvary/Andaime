#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brasão da Prefeitura e RAC logo (Qt). Os PNGs claro/escuro são pré-renderizados
por ``tools/generate_brasao.py`` evitando QtSvg em runtime e garantindo visual 
idêntico entre fonte e build empacotado. O resultado é cacheado por (altura, modo_escuro)."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


def _resolver_caminho(nome: str, pasta: str = "img") -> Path:
    """Resolve caminho de PNG (funciona em fonte e empacotado via _MEIPASS)."""
    base = Path(__file__).resolve().parent / pasta
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidato = Path(meipass) / "src" / "gui" / pasta / nome
            if candidato.exists():
                return candidato
    return base / nome


def _get_pixmap_cached(
    cache: dict, height: int, dark_mode: bool, nome: str
) -> QPixmap | None:
    """Retorna QPixmap cacheado ou None silencioso se não disponível."""
    chave = (height, dark_mode)
    if chave in cache:
        return cache[chave]

    tema = "dark" if dark_mode else "light"
    caminho = _resolver_caminho(f"{nome}_{tema}.png")
    if not caminho.exists():
        print(f"[AVISO] PNG não encontrado: {caminho}")
        cache[chave] = None
        return None

    pixmap = QPixmap(str(caminho))
    if pixmap.isNull():
        print(f"[AVISO] Falha ao carregar PNG: {caminho}")
        cache[chave] = None
        return None

    resultado = pixmap.scaledToHeight(
        height, Qt.TransformationMode.SmoothTransformation
    )
    cache[chave] = resultado
    return resultado


_pixmap_cache: dict[tuple[int, bool], QPixmap | None] = {}
_rac_cache: dict[tuple[int, bool], QPixmap | None] = {}


def get_brasao_pixmap(height: int = 41, dark_mode: bool = True) -> QPixmap | None:
    """Retorna QPixmap do brasão dimensionado à altura e cacheado."""
    return _get_pixmap_cached(_pixmap_cache, height, dark_mode, "brasao")


def get_rac_pixmap(height: int = 30, dark_mode: bool = True) -> QPixmap | None:
    """Retorna QPixmap do RAC logo dimensionado à altura e cacheado."""
    return _get_pixmap_cached(_rac_cache, height, dark_mode, "rac")