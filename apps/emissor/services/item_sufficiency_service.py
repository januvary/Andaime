#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Item Sufficiency Service — datas de suficiência de itens dispensados."""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

from andaime.dates import format_date


class ItemSufficiencyService:
    """Calcula datas de suficiência de itens de uma receita, considerando
    retiradas anteriores do mesmo item."""

    @staticmethod
    def parse_dias(value: str) -> int | None:
        """Converte string de dias em inteiro não-negativo; None se inválido."""
        if not value or not value.strip():
            return None
        try:
            dias = int(value.strip())
            return dias if dias >= 0 else None
        except ValueError:
            return None

    @staticmethod
    def format_date(dt: date) -> str:
        """Formata data de suficiência como DD/MM/AAAA (sem dia da semana)."""
        return format_date(dt, include_weekday=False)

    @staticmethod
    def compute_plain_end(current_date: date, current_dias: int) -> date:
        """Data de término considerando apenas a dispensação atual."""
        return current_date + timedelta(days=current_dias)

    @staticmethod
    def compute_default_end(
        history: List[Tuple[date, int]],
    ) -> date | None:
        """Data de término acumulando o saldo remanescente de cada retirada
        anterior (sem a dispensação em digitação); None se sem histórico."""
        coverage_end: date | None = None

        for dispensation_date, dias in history:
            if coverage_end is None:
                coverage_end = dispensation_date
            if dispensation_date > coverage_end:
                coverage_end = dispensation_date
            coverage_end = coverage_end + timedelta(days=dias)

        return coverage_end

    @staticmethod
    def compute_combined_end(
        history: List[Tuple[date, int]],
        current_date: date,
        current_dias: int,
    ) -> date:
        """Data de término acumulando retiradas anteriores E a dispensação em
        digitação. O saldo remanescente das retiradas passadas é considerado
        antes de contar os dias da dispensação atual."""
        coverage_end = ItemSufficiencyService.compute_default_end(history)
        if coverage_end is None or coverage_end < current_date:
            coverage_end = current_date
        return coverage_end + timedelta(days=current_dias)
