"""Serviço de remessas (lotes) do SS-54.

Mantém o agendamento automático de remessas, espelhando o padrão
histórico da planilha: envios **quinzenais** (a cada 14 dias), com
a data alvo ajustada para o dia útil mais próximo quando cai em
fim de semana ou feriado (regra espelhada do RAC via ``DateCalculator``).

Na inicialização, cria as remessas vencidas (a partir da última existente,
de 14 em 14 dias) até hoje.
"""

from __future__ import annotations

from datetime import date, timedelta

from andaime.dates import DateCalculator, parse_date

from src.database.ss54_database import SS54Database


def _parse(date_str: str) -> date:
    d = parse_date(date_str)
    return d if d else date.today()


def next_remessa_date(last: date) -> date:
    """Próxima data de remessa: ``last + 14 dias`` ajustada ao dia útil mais próximo."""
    target = last + timedelta(days=14)
    if DateCalculator.is_business_day(target):
        return target
    prev = DateCalculator.skip_to_previous_business_day(target)
    nxt = DateCalculator.skip_to_next_business_day(target)
    return prev if (target - prev) <= (nxt - target) else nxt


def _create_lote_moving_incompletos(db: SS54Database, date_iso: str) -> None:
    """Cria um lote em ``date_iso`` e move processos incompletos para ele."""
    lote = db.create_lote(date_iso)
    db.move_incompletos_to_lote(lote.id)


def _ensure_lote_at_next_or_today(db: SS54Database, lotes) -> int:
    """Cria a próxima remessa quinzenal (ou âncora em hoje se vazio).

    ``lotes`` já vem ordenada DESC por data (``get_all_lotes``). Retorna 0
    se a próxima data já existe, 1 se criou.
    """
    if not lotes:
        _create_lote_moving_incompletos(db, date.today().isoformat())
        return 1

    last = _parse(lotes[0].date)
    nxt = next_remessa_date(last)
    if nxt.isoformat() in {lot.date for lot in lotes}:
        return 0
    _create_lote_moving_incompletos(db, nxt.isoformat())
    return 1


def ensure_remessas(db: SS54Database) -> int:
    """Garante a próxima remessa quinzenal.

    Dispara quando ao menos um dia se passou desde a última remessa:
    cria a próxima (last + 14d, ajustada ao dia útil mais próximo),
    se ainda não existir. Se não houver nenhuma remessa, cria uma
    âncora em hoje. Retorna o número de remessas criadas (0 ou 1).
    """
    lotes = db.get_all_lotes()
    if lotes and (date.today() - _parse(lotes[0].date)).days < 1:
        return 0
    return _ensure_lote_at_next_or_today(db, lotes)


def ensure_next_open_lote(db: SS54Database) -> int:
    """Garante que exista uma remessa aberta (não enviada) para novos processos.

    Chamado após uma remessa ser marcada como enviada. Se já houver uma
    remessa aberta, não faz nada. Caso contrário, cria a próxima remessa
    (última data + 14 dias, ajustada ao dia útil). Retorna 0 ou 1.
    """
    if db.get_active_lote() is not None:
        return 0
    return _ensure_lote_at_next_or_today(db, db.get_all_lotes())
