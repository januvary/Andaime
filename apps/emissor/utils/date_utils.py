#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cálculo de dias úteis e formatação de datas (feriados BR)."""

from datetime import timedelta, date
from typing import Any, Callable, Dict, List

from andaime.dates import DateCalculator as _BaseDateCalculator, parse_date, format_date

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel


# Cache de dias úteis por (ano, mês): get_business_days_of_month é puro e
# reconstruído várias vezes por adjust_for_balanco / find_optimal_next_date.
_business_days_cache: Dict[tuple[int, int], List[date]] = {}


class DateCalculator(_BaseDateCalculator):
    """Utilitários de cálculo de datas com feriados e finais de semana."""

    @staticmethod
    def calculate_next_date(base_date: date, days: int) -> date:
        """Calcula próxima data: base_date + days, ajustando para dia útil anterior."""
        next_date = base_date + timedelta(days=days)
        return DateCalculator.skip_to_previous_business_day(next_date)

    @staticmethod
    def days_until(target_date: date) -> int:
        """Calcula quantos dias faltam até a data alvo (a partir de hoje)."""
        delta = target_date - date.today()
        return delta.days

    @staticmethod
    def _format_countdown(days: int, past_prefix: str = "") -> str:
        """Formata delta em dias como texto PT-BR.

        Ex.: 5 → "em 5 dias", 0 → "hoje", -3 → "3 dias atrás"
        (com past_prefix="expirou há " → "expirou há 3 dias atrás").
        """
        if days > 0:
            return f"em {days} dia{'s' if days != 1 else ''}"
        if days == 0:
            return "hoje"
        n = abs(days)
        return f"{past_prefix}{n} dia{'s' if n != 1 else ''} atrás"

    @staticmethod
    def calculate_proxima_vez(
        data_retirada_str: str,
        periodicidade_str: str,
        enable_distribution: bool = False,
        distribution_window_days: int = 3,
        retirada_count_fn: Callable[[str, str], Dict[str, int]] | None = None,
        bloquear_balanco: bool = False,
    ) -> Dict[str, Any]:
        """Calcula a próxima retirada (com distribuição opcional).

        Args:
            enable_distribution: habilita distribuição inteligente
            distribution_window_days: dias para trás na janela (1-7)
            retirada_count_fn: callable(start, end) → dict data→contagem
            bloquear_balanco: evita últimos 5 dias úteis do mês
        """
        result: dict[str, Any] = {
            "proxima_vez": None,
            "proxima_vez_formatted": "-",
            "proxima_vez_countdown": "",
            "proxima_vez_foi_ajustada": False,
            "proxima_vez_data_original": None,
        }

        if not periodicidade_str or not periodicidade_str.isdigit():
            return result

        try:
            periodicidade = int(periodicidade_str)
            data_retirada = parse_date(data_retirada_str)

            if not data_retirada:
                data_retirada = date.today()

            proxima_vez = DateCalculator.calculate_next_date(
                data_retirada, periodicidade
            )

            data_original = proxima_vez
            foi_ajustada = False

            # Distribuição inteligente se habilitada
            if enable_distribution and retirada_count_fn:
                try:
                    proxima_vez_ajustada, foi_ajustada = (
                        RetiradaDateDistributor.find_optimal_next_date(
                            data_original,
                            retirada_count_fn=retirada_count_fn,
                            max_days_back=distribution_window_days,
                            bloquear_balanco=bloquear_balanco,
                        )
                    )
                    if foi_ajustada:
                        proxima_vez = proxima_vez_ajustada
                except Exception as e:
                    # Falha gracefully em caso de erro na distribuição
                    ErrorHandler.log(
                        f"Erro na distribuição de datas: {e}",
                        level=ErrorLevel.WARNING,
                        context=ErrorContext.STATE,
                    )

            result["proxima_vez"] = proxima_vez
            result["proxima_vez_formatted"] = format_date(
                proxima_vez, include_weekday=True
            )
            result["proxima_vez_foi_ajustada"] = foi_ajustada
            result["proxima_vez_data_original"] = data_original

            # Bloqueio de balanço: deslocar para fora dos últimos 5 dias úteis
            if bloquear_balanco:
                proxima_vez_ajustada = DateCalculator.adjust_for_balanco(proxima_vez)
                if proxima_vez_ajustada != proxima_vez:
                    proxima_vez = proxima_vez_ajustada
                    foi_ajustada = True
                    result["proxima_vez_foi_ajustada"] = True
                    result["proxima_vez_data_original"] = data_original
                    ErrorHandler.log(
                        f"Data ajustada para balanço: "
                        f"{result.get('proxima_vez')} -> {proxima_vez}",
                        level=ErrorLevel.INFO,
                        context=ErrorContext.STATE,
                    )

            result["proxima_vez"] = proxima_vez
            result["proxima_vez_formatted"] = format_date(
                proxima_vez, include_weekday=True
            )

            # Countdown
            result["proxima_vez_countdown"] = DateCalculator._format_countdown(
                DateCalculator.days_until(proxima_vez)
            )

        except Exception as e:
            ErrorHandler.log(
                f"Erro ao calcular próxima vez: {e}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.STATE,
            )

        return result

    @staticmethod
    def calculate_validade_receita(
        ultima_receita_str: str, tipo_receita: str
    ) -> Dict[str, Any]:
        """Calcula a validade da receita (sem distribuição).

        Args:
            tipo_receita: 'tipo_a' (180d), 'tipo_b' (90d) ou 'tipo_c' (30d)
        """
        result: dict[str, Any] = {
            "validade_receita": None,
            "validade_receita_formatted": "-",
            "validade_receita_countdown": "",
        }

        validade_map = {"tipo_a": 180, "tipo_b": 90, "tipo_c": 30}

        if not ultima_receita_str or not tipo_receita:
            return result

        try:
            ultima_receita = parse_date(ultima_receita_str)

            if ultima_receita and tipo_receita in validade_map:
                validade_dias = validade_map[tipo_receita]
                validade_date = DateCalculator.calculate_next_date(
                    ultima_receita, validade_dias
                )

                result["validade_receita"] = validade_date
                result["validade_receita_formatted"] = format_date(
                    validade_date, include_weekday=False
                )

                # Countdown
                result["validade_receita_countdown"] = (
                    DateCalculator._format_countdown(
                        DateCalculator.days_until(validade_date),
                        past_prefix="expirou há ",
                    )
                )

        except Exception as e:
            ErrorHandler.log(
                f"Erro ao calcular validade da receita: {e}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.STATE,
            )

        return result

    # ========== Bloqueio de balanço do almoxarifado ==========

    BALANCO_BLOCK_DAYS: int = 5

    @staticmethod
    def _is_business_day(check_date: date) -> bool:
        """Verifica se a data é dia útil (não fim de semana, não feriado)."""
        br_holidays = DateCalculator.get_holidays()
        return check_date.weekday() < 5 and check_date not in br_holidays

    @staticmethod
    def get_business_days_of_month(month_reference: date) -> List[date]:
        """Retorna os dias úteis do mês (memoizado por ano/mês)."""
        key = (month_reference.year, month_reference.month)
        cached = _business_days_cache.get(key)
        if cached is not None:
            return cached

        first_day = month_reference.replace(day=1)
        if first_day.month == 12:
            next_month = first_day.replace(year=first_day.year + 1, month=1)
        else:
            next_month = first_day.replace(month=first_day.month + 1)
        last_day = next_month - timedelta(days=1)

        business_days: List[date] = []
        current = first_day
        while current <= last_day:
            if DateCalculator._is_business_day(current):
                business_days.append(current)
            current = current + timedelta(days=1)

        _business_days_cache[key] = business_days
        return business_days

    @staticmethod
    def get_balanco_block_dates(
        month_reference: date, n: int = BALANCO_BLOCK_DAYS
    ) -> List[date]:
        """Retorna os últimos ``n`` dias úteis do mês (período de balanço)."""
        business_days = DateCalculator.get_business_days_of_month(month_reference)
        return business_days[-n:] if len(business_days) >= n else business_days

    @staticmethod
    def is_in_balanco_block(check_date: date, n: int = BALANCO_BLOCK_DAYS) -> bool:
        """Verifica se a data cai no período de balanço do mês."""
        return check_date in set(
            DateCalculator.get_balanco_block_dates(check_date, n)
        )

    @staticmethod
    def adjust_for_balanco(
        proxima_vez: date, n: int = BALANCO_BLOCK_DAYS
    ) -> date:
        """Ajusta a data para fora do período de balanço do mês."""
        if not DateCalculator.is_in_balanco_block(proxima_vez, n):
            return proxima_vez

        business_days = DateCalculator.get_business_days_of_month(proxima_vez)
        # Índice do último dia útil anterior ao bloqueio
        pre_block_index = len(business_days) - n - 1
        if pre_block_index >= 0:
            return business_days[pre_block_index]

        # Mês com poucos dias úteis: recua para o último útil do mês anterior
        previous_month = proxima_vez.replace(day=1) - timedelta(days=1)
        prev_business_days = DateCalculator.get_business_days_of_month(previous_month)
        return prev_business_days[-1] if prev_business_days else proxima_vez


class RetiradaDateDistributor:
    """Distribuição inteligente de retiradas em dias úteis."""

    @staticmethod
    def find_optimal_next_date(
        base_date: date,
        max_days_back: int = 3,
        retirada_count_fn: Callable[[str, str], Dict[str, int]] | None = None,
        bloquear_balanco: bool = False,
    ) -> tuple[date, bool]:
        """Encontra dia útil com menos retiradas em [base-max_days_back, base].

        Args:
            max_days_back: janela para trás (padrão 3)
            retirada_count_fn: callable(start, end) → dict data→contagem
            bloquear_balanco: exclui últimos 5 dias úteis do mês
        """
        if retirada_count_fn is None:
            raise ValueError("retirada_count_fn deve ser fornecido")

        # Gerar candidatos
        candidates = [base_date - timedelta(days=i) for i in range(max_days_back + 1)]

        # Filtrar apenas dias úteis
        business_day_candidates = []
        br_holidays = DateCalculator.get_holidays()

        for candidate in candidates:
            # Verificar se é dia útil (não fim de semana, não feriado)
            if candidate.weekday() < 5 and candidate not in br_holidays:
                business_day_candidates.append(candidate)

        # Excluir dias do bloqueio de balanço (últimos 5 dias úteis do mês)
        if bloquear_balanco:
            blocked = {
                d
                for c in business_day_candidates
                for d in DateCalculator.get_balanco_block_dates(c)
            }
            business_day_candidates = [
                c for c in business_day_candidates if c not in blocked
            ]

        # Se nenhum dia útil encontrado, retornar base_date original
        if not business_day_candidates:
            ErrorHandler.log(
                f"Nenhum dia útil encontrado na janela de {max_days_back} dias",
                level=ErrorLevel.WARNING,
                context=ErrorContext.STATE,
            )
            return base_date, False

        # Filtrar candidatos que não são no passado
        today = date.today()
        future_candidates = [c for c in business_day_candidates if c >= today]

        if not future_candidates:
            # Todos os candidatos são no passado, retornar base_date original
            ErrorHandler.log(
                "Todos os dias úteis na janela são no passado, mantendo data original",
                level=ErrorLevel.INFO,
                context=ErrorContext.STATE,
            )
            return base_date, False

        # Consultar contagem de retiradas para cada candidato
        start_date = min(future_candidates).strftime("%Y-%m-%d")
        end_date = max(future_candidates).strftime("%Y-%m-%d")

        try:
            date_counts = retirada_count_fn(start_date, end_date)
        except Exception as e:
            ErrorHandler.log(
                f"Erro ao consultar contagem de retiradas: {e}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.DATABASE,
            )
            # Em caso de erro, retornar primeiro dia útil futuro
            return future_candidates[0], False

        # Encontrar dia com menor contagem
        optimal_date = base_date
        min_count = float("inf")

        # Preservar ordem de preferência: base_date primeiro, então base_date-1, etc
        for candidate in future_candidates:
            candidate_str = candidate.strftime("%Y-%m-%d")
            count = date_counts.get(candidate_str, 0)

            if count < min_count:
                min_count = count
                optimal_date = candidate

                # Se encontrou dia vazio, não precisa procurar mais
                if min_count == 0:
                    break

        foi_ajustada = optimal_date != base_date

        if foi_ajustada:
            ErrorHandler.log(
                f"Data ajustada para distribuir retiradas: "
                f"{base_date.strftime('%d/%m/%Y')} -> {optimal_date.strftime('%d/%m/%Y')} "
                f"(janela: {max_days_back} dias, contagem: {min_count})",
                level=ErrorLevel.INFO,
                context=ErrorContext.STATE,
            )

        return optimal_date, foi_ajustada
