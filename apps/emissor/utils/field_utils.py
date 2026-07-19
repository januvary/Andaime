#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilitários de extração de campos (dict, Mapping, dataclass ou objeto)."""

from __future__ import annotations

from typing import Any


def get_field_str(source: Any, key: str, default: str = "") -> str:
    """Extrai um campo como string de ``source`` (dict/Mapping/objeto/None).

    Aceita dict, qualquer objeto Mapping (ex.: dataclass ``Patient``),
    objetos com atributos, ou ``None``. ``None`` é normalizado para
    ``default``; valores não-None são convertidos via ``str()``.
    """
    if source is None:
        return default
    if hasattr(source, "__getitem__"):
        try:
            value = source[key]
        except (KeyError, TypeError, IndexError):
            value = None
        return "" if value is None else str(value)
    value = getattr(source, key, default)
    return "" if value is None else str(value)
