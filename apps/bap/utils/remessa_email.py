"""Preparação de remessas para o DRS (montagem dos rascunhos de e-mail).

Coleta os processos ``completo`` da remessa ativa, separa por tipo de
solicitação (renovação × primeira solicitação), garante que o PDF combinado
de cada processo esteja atualizado e monta o corpo (HTML) e os anexos de cada
grupo. O envio em si (criação do rascunho no Gmail) é responsabilidade do
``gmail_client`` + da camada de UI.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.constants import TIPO_LABELS, SOLICITACAO_LABELS, Status
from src.database.ss54_database import SS54Database
from src.models import Lote, Processo
from src.utils.arquivo_storage import (
    _safe_filename,
    build_processo_dir,
    compute_processo_sig,
    merge_conteudos_to_pdf,
    remessa_folder_relpath,
    resolve_arquivos_root,
)
from src.utils.config import SS54Config


@dataclass
class RemessaItem:
    """Uma linha da remessa (um processo)."""

    processo_id: int
    protocolo: str
    paciente_nome: str
    tipo_label: str
    descricao: str
    pdf_path: str | None
    attachment_name: str | None
    has_docs: bool


@dataclass
class RemessaGroup:
    """Um grupo de envio (renovação ou primeira solicitação)."""

    grupo: str
    label: str
    to_email: str
    subject: str
    html_body: str
    drive_folder: str = ""
    items: list[RemessaItem] = field(default_factory=list)
    attachments: list[tuple[str, str]] = field(default_factory=list)  # (path, nome)
    included_ids: list[int] = field(default_factory=list)
    skipped_ids: list[int] = field(default_factory=list)


def _attachment_name(paciente_nome: str, tipo_label: str) -> str:
    return _safe_filename(f"{paciente_nome} - {tipo_label.upper()}") + ".pdf"


def ensure_processo_pdf(
    db: SS54Database,
    root: Path,
    processo: Processo,
) -> tuple[str | None, bool]:
    """Garante o PDF combinado do processo, regenerando apenas se necessário.

    Retorna ``(caminho_pdf, tem_documentos)``. Quando o processo não tem
    documentos, retorna ``(None, False)``.

    A assinatura deriva só de metadados (``compute_processo_sig``): decidir se
    o PDF combinado está atualizado **não lê nenhum BLOB**. Só ao regenerar os
    BLOBs são lidos, uma vez, um por vez (pico de memória de um BLOB).
    """
    arqs = db.get_arquivos_by_processo(processo.id)
    if not arqs:
        return None, False

    sig = compute_processo_sig(arqs)

    folder = build_processo_dir(
        root,
        processo.lote_date or "",
        processo.solicitacao,
        processo.paciente_nome or "",
        processo.tipo,
    )
    tipo_label = TIPO_LABELS.get(processo.tipo, processo.tipo or "")
    dest = folder / _attachment_name(processo.paciente_nome or "", tipo_label)
    if dest.exists() and processo.pdf_sig == sig:
        return str(dest), True

    dest.parent.mkdir(parents=True, exist_ok=True)
    conteudos = (db.get_arquivo_conteudo(a.id) or b"" for a in arqs)
    merge_conteudos_to_pdf(conteudos, str(dest))
    db.set_processo_pdf_sig(processo.id, sig)
    return str(dest), True


def _build_html_body(label: str, sent_date: str, items: list[RemessaItem]) -> str:
    """Monta o corpo HTML do e-mail (tabela Nome / Tipo / Descrição)."""
    rows = []
    for i, item in enumerate(items):
        bg = "#ffffff" if i % 2 == 0 else "#f7fafc"
        rows.append(
            f'<tr style="background-color: {bg};">'
            f'<td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">'
            f"{html.escape(item.paciente_nome or 'Não informado')}</td>"
            f'<td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">'
            f"{html.escape(item.tipo_label)}</td>"
            f'<td style="padding: 10px; border-bottom: 1px solid #e2e8f0;">'
            f"{html.escape(item.descricao or '')}</td>"
            f"</tr>"
        )
    rows_html = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head><meta charset="UTF-8"></head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px;">
  <div style="background-color: #f9f9f9; border-radius: 2px; padding: 20px;">
    <div style="background-color: #fff; border: 1px solid #e2e8f0; border-radius: 2px; overflow-x: auto;">
      <table style="width: 100%; min-width: 600px; border-collapse: collapse; font-size: 14px;">
        <thead>
          <tr style="background-color: #2c5282; color: white;">
            <th style="padding: 12px 10px; text-align: left; border-bottom: 2px solid #1a365d;">Nome do Paciente</th>
            <th style="padding: 12px 10px; text-align: left; border-bottom: 2px solid #1a365d;">Tipo</th>
            <th style="padding: 12px 10px; text-align: left; border-bottom: 2px solid #1a365d;">Descrição</th>
          </tr>
        </thead>
        <tbody>
{rows_html}
        </tbody>
      </table>
    </div>
    <p style="font-size: 14px; color: #666; margin-top: 20px;">
      <strong>Total de processos:</strong> {len(items)}
    </p>
  </div>
</body>
</html>"""


def build_remessa_group(
    db: SS54Database,
    root: Path,
    lote: Lote,
    grupo: str,
    to_email: str,
    processos: list[Processo],
) -> RemessaGroup | None:
    """Monta um grupo de envio a partir de uma lista de processos ``completo``.

    Retorna ``None`` se não houver processos no grupo.
    """
    if not processos:
        return None

    label = SOLICITACAO_LABELS.get(grupo, grupo.upper())
    today = datetime.now().strftime("%d/%m")
    subject = f"REMESSA {today} - {label.upper()}"

    items: list[RemessaItem] = []
    attachments: list[tuple[str, str]] = []
    included_ids: list[int] = []
    skipped_ids: list[int] = []

    for processo in processos:
        pdf_path, has_docs = ensure_processo_pdf(db, root, processo)
        tipo_label = TIPO_LABELS.get(processo.tipo, processo.tipo or "")
        attach_name = (
            _attachment_name(processo.paciente_nome or "", tipo_label)
            if has_docs
            else None
        )
        item = RemessaItem(
            processo_id=processo.id,
            protocolo=processo.protocolo,
            paciente_nome=processo.paciente_nome or "",
            tipo_label=tipo_label,
            descricao=processo.descricao or "",
            pdf_path=pdf_path,
            attachment_name=attach_name,
            has_docs=has_docs,
        )
        items.append(item)
        if has_docs and pdf_path:
            attachments.append((pdf_path, attach_name))
            included_ids.append(processo.id)
        else:
            skipped_ids.append(processo.id)

    # Somente processos com documentos entram no corpo do e-mail.
    body_items = [it for it in items if it.has_docs]
    sent_date = datetime.now().strftime("%d/%m/%Y às %H:%M")
    html_body = _build_html_body(label, sent_date, body_items)

    return RemessaGroup(
        grupo=grupo,
        label=label,
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        drive_folder=remessa_folder_relpath(lote.date, grupo),
        items=items,
        attachments=attachments,
        included_ids=included_ids,
        skipped_ids=skipped_ids,
    )


def build_remessa_groups(
    db: SS54Database,
    config: SS54Config,
    lote: Lote,
) -> list[RemessaGroup]:
    """Monta os grupos de envio (apenas os que têm processos ``completo``).

    Retorna uma lista com 0, 1 ou 2 grupos (renovação e/ou primeira
    solicitação), na ordem: renovação, primeira.
    """
    root = resolve_arquivos_root(config)
    completos = db.get_processos_by_lote_and_status(lote.id, Status.COMPLETO)

    renovacoes = [p for p in completos if p.solicitacao == "renovacao"]
    primeiras = [p for p in completos if p.solicitacao == "primeira"]

    groups: list[RemessaGroup] = []
    renovacao_group = build_remessa_group(
        db, root, lote, "renovacao", config.drs_renovacao_email, renovacoes
    )
    if renovacao_group:
        groups.append(renovacao_group)

    primeira_group = build_remessa_group(
        db, root, lote, "primeira", config.drs_solicitacao_email, primeiras
    )
    if primeira_group:
        groups.append(primeira_group)

    return groups


_DRS_EMAIL_KEYS = {
    "renovacao": "drs_renovacao_email",
    "primeira": "drs_solicitacao_email",
}


def missing_drs_emails(
    db: SS54Database, config: SS54Config, lote: Lote
) -> list[tuple[str, str]]:
    """Grupos (renovação/primeira) com processos ``completo`` e e-mail DRS vazio.

    Retorna ``[(grupo, config_key), ...]`` — usado para solicitar os e-mails
    antes de montar os grupos, evitando reconstruir os PDFs combinados só para
    descobrir quais e-mails faltam.
    """
    completos = db.get_processos_by_lote_and_status(lote.id, Status.COMPLETO)
    faltando: list[tuple[str, str]] = []
    for grupo, key in _DRS_EMAIL_KEYS.items():
        tem_processos = any(p.solicitacao == grupo for p in completos)
        if tem_processos and not (getattr(config, key, "") or ""):
            faltando.append((grupo, key))
    return faltando
