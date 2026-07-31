"""Serviço de remessas (lotes) do SS-54.

Mantém o agendamento automático de remessas, espelhando o padrão
histórico da planilha: envios **quinzenais** (a cada 14 dias), com
a data alvo ajustada para o dia útil mais próximo quando cai em
fim de semana ou feriado (regra espelhada do RAC via ``DateCalculator``).

Na inicialização, cria as remessas vencidas (a partir da última existente,
de 14 em 14 dias) até hoje. Quando uma nova remessa é criada, as remessas
anteriores são arquivadas: seus PDFs combinados passam a ser a fonte de
verdade e os BLOBs dos arquivos são removidos do banco.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from andaime.dates import DateCalculator, parse_date

from bap.database.ss54_database import SS54Database


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


def _create_lote_moving_incompletos(db: SS54Database, date_iso: str) -> object:
    """Cria um lote em ``date_iso`` e move processos incompletos para ele."""
    lote = db.create_lote(date_iso)
    db.move_incompletos_to_lote(lote.id)
    return lote


def _archive_processo(db: SS54Database, root: Path, processo: object) -> bool:
    """Arquiva um processo: garante PDF e remove BLOBs.

    Idempotente: se já estiver arquivado, retorna ``True`` sem alterar nada.
    Se o PDF não existir, cria a partir dos BLOBs atuais. Preserva os metadados
    na tabela ``arquivos`` (conteúdo fica ``NULL``).
    """
    if processo.is_archived:
        return True

    from bap.models import Processo
    from bap.utils.remessa_email import ensure_processo_pdf, processo_pdf_path

    if not isinstance(processo, Processo):
        processo = db.get_processo_by_id(processo.id)
        if processo is None:
            return False

    pdf_path = processo_pdf_path(root, processo)
    if not pdf_path.exists():
        pdf_path, has_docs = ensure_processo_pdf(db, root, processo)
        if not has_docs or pdf_path is None:
            return False
        pdf_path = Path(pdf_path)

    db.delete_conteudos_for_processo(processo.id)
    db.set_processo_archived(processo.id, True)
    return True


def archive_previous_lotes(
    db: SS54Database, root: Path, new_lote: object
) -> dict:
    """Arquiva todos os processos de remessas anteriores a ``new_lote``.

    Para cada lote com data anterior a ``new_lote.date``, garante o PDF de cada
    processo e remove seus BLOBs. Retorna relatório com contadores.
    """
    report = {"processos": 0, "arquivados": 0, "erros": 0, "error_detail": []}
    lotes = db.get_all_lotes()
    for lote in lotes:
        if lote.date >= new_lote.date:
            continue
        for processo in db.get_processos_by_lote(lote.id):
            report["processos"] += 1
            try:
                if _archive_processo(db, root, processo):
                    report["arquivados"] += 1
            except Exception as e:  # noqa: BLE001
                report["erros"] += 1
                report["error_detail"].append(str(e))
    return report


def _ensure_lote_at_next_or_today(db: SS54Database, root: Path | None, lotes) -> tuple[int, object | None]:
    """Cria a próxima remessa quinzenal (ou âncora em hoje se vazio).

    ``lotes`` já vem ordenada DESC por data (``get_all_lotes``). Retorna
    ``(0, None)`` se a próxima data já existe, ``(1, lote)`` se criou.
    """
    if not lotes:
        lote = _create_lote_moving_incompletos(db, date.today().isoformat())
        return 1, lote

    last = _parse(lotes[0].date)
    nxt = next_remessa_date(last)
    if nxt.isoformat() in {lot.date for lot in lotes}:
        return 0, None
    lote = _create_lote_moving_incompletos(db, nxt.isoformat())
    return 1, lote


def ensure_remessas(db: SS54Database, root: Path | None = None) -> dict:
    """Garante a próxima remessa quinzenal e arquiva remessas anteriores.

    Dispara quando ao menos um dia se passou desde a última remessa:
    cria a próxima (last + 14d, ajustada ao dia útil mais próximo),
    se ainda não existir. Se não houver nenhuma remessa, cria uma
    âncora em hoje. Quando uma nova remessa é criada, arquiva as anteriores.
    Retorna relatório da operação.
    """
    lotes = db.get_all_lotes()
    if lotes and (date.today() - _parse(lotes[0].date)).days < 1:
        return {"criados": 0, "archive": {"processos": 0, "arquivados": 0, "erros": 0}}
    created, lote = _ensure_lote_at_next_or_today(db, root, lotes)
    archive_report = {"processos": 0, "arquivados": 0, "erros": 0}
    if created and lote is not None and root is not None:
        archive_report = archive_previous_lotes(db, root, lote)
    return {"criados": created, "archive": archive_report}


def ensure_next_open_lote(db: SS54Database, root: Path | None = None) -> dict:
    """Garante que exista uma remessa aberta (não enviada) para novos processos.

    Chamado após uma remessa ser marcada como enviada. Se já houver uma
    remessa aberta, não faz nada. Caso contrário, cria a próxima remessa
    (última data + 14 dias, ajustada ao dia útil). Quando uma nova remessa é
    criada, arquiva as anteriores. Retorna relatório da operação.
    """
    if db.get_active_lote() is not None:
        return {"criados": 0, "archive": {"processos": 0, "arquivados": 0, "erros": 0}}
    created, lote = _ensure_lote_at_next_or_today(db, root, db.get_all_lotes())
    archive_report = {"processos": 0, "arquivados": 0, "erros": 0}
    if created and lote is not None and root is not None:
        archive_report = archive_previous_lotes(db, root, lote)
    return {"criados": created, "archive": archive_report}
