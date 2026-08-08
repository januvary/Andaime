#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Máscaras de campos centralizadas (sem dependência de framework)."""

from __future__ import annotations

import re

# Máscaras de campos por tipo/nome
FIELD_MASKS: dict[str, str] = {
    "processo": "9999999-99.9999.9.99.9999",
    "cpf": "000.000.000-00",
    "telefone": "(99) 99999-9999",
    "codigo": "999.99999.9999-99",
    "item_id": "999.99999.9999-99",
}


def get_mask_for_field(field_name: str) -> str | None:
    """Retorna a máscara para o campo (match exato ou por prefixo)."""
    if field_name in FIELD_MASKS:
        return FIELD_MASKS[field_name]

    for key, mask in FIELD_MASKS.items():
        if field_name.startswith(key):
            return mask

    return None


def apply_mask_format(value: str, mask: str) -> str:
    """Aplica a máscara ao valor, mantendo apenas dígitos."""
    if not value:
        return ""

    digits = re.sub(r"[^0-9]", "", value)
    result: list[str] = []
    digit_index = 0

    for char in mask:
        if digit_index >= len(digits):
            break
        if char == "9":
            result.append(digits[digit_index])
            digit_index += 1
        else:
            result.append(char)

    return "".join(result)


def apply_mask_for_field(field_name: str, value: str) -> str:
    """Aplica a máscara do campo; retorna valor original se não houver."""
    mask = get_mask_for_field(field_name)
    if not mask:
        return value
    return apply_mask_format(value, mask)
