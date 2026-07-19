"""Importação das remessas da planilha REMESSAS ENVIADAS.xlsx.

Fluxo em duas etapas:
  1. ``extract_xlsx_to_temp`` lê a planilha inteira e a espelha num banco
     SQLite temporário (data/remessas_import.db) com as tabelas ``remessas``
     e ``solicitacoes``.
  2. ``transfer_patients`` copia os pacientes únicos (por nome normalizado)
     para o banco principal (ss54.db), sem duplicar os já existentes.

O banco temporário permanece disponível para futuras transferências
(lotes/processos) conforme necessário.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

import openpyxl
from andaime.text import to_upper_normalized
from bap.utils.text_utils import fold_diacritics
from andaime.dates import parse_date

from bap.database.ss54_database import SS54Database
from bap.constants import Status

def _default_xlsx_path() -> str:
    from bap.utils.config import bap_data_dir
    return str(bap_data_dir() / "REMESSAS ENVIADAS.xlsx")


def _default_temp_db_path() -> str:
    from bap.utils.config import bap_data_dir
    return str(bap_data_dir() / "remessas_import.db")

_SECTION_PRIMEIRA = "PRIMEIRA SOLICITAÇÃO"
_SECTION_RENOVACAO = "RENOVAÇÃO"
_HEADER_MARKERS = {"NOME PACIENTE", "NOME PACIENTE "}


def _norm(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def extract_xlsx_to_temp(
    xlsx_path: str = None,
    temp_db_path: str = None,
) -> dict[str, int]:
    """Lê a planilha e popula o banco temporário.

    Returns:
        Dicionário com ``remessas`` e ``solicitacoes`` (contagens).
    """
    if xlsx_path is None:
        xlsx_path = _default_xlsx_path()
    if temp_db_path is None:
        temp_db_path = _default_temp_db_path()
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)

    conn = sqlite3.connect(temp_db_path)
    conn.executescript(
        """
        CREATE TABLE remessas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aba TEXT NOT NULL,
            data TEXT
        );
        CREATE TABLE solicitacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remessa_id INTEGER NOT NULL,
            tipo_solicitacao TEXT NOT NULL,
            nome TEXT NOT NULL,
            tipo TEXT DEFAULT '',
            descricao TEXT DEFAULT '',
            retorno_drs TEXT DEFAULT '',
            telefone TEXT DEFAULT ''
        );
        """
    )

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)

    for ws in wb.worksheets:
        remessa_id: int | None = None
        current_section = "primeira"

    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [None if c is None else c for c in row]
            first = _norm(cells[0]) if cells else ""
            fu = first.upper()

            if fu.startswith("REMESSA"):
                dt = cells[1] if len(cells) > 1 else None
                data = dt.date().isoformat() if isinstance(dt, datetime) else None
                cur = conn.execute(
                    "INSERT INTO remessas (aba, data) VALUES (?, ?)",
                    (str(ws.title), data),
                )
                remessa_id = cur.lastrowid
                current_section = "primeira"
                continue

            if fu == _SECTION_PRIMEIRA:
                current_section = "primeira"
                continue
            if fu == _SECTION_RENOVACAO:
                current_section = "renovacao"
                continue
            if fu in _HEADER_MARKERS:
                continue

            if remessa_id is None:
                continue

            nome = _norm(cells[0]) if cells else ""
            if not nome:
                continue

            tipo = _norm(cells[1]) if len(cells) > 1 else ""
            descricao = _norm(cells[2]) if len(cells) > 2 else ""
            retorno = _norm(cells[3]) if len(cells) > 3 else ""
            telefone = _norm(cells[4]) if len(cells) > 4 else ""

            conn.execute(
                "INSERT INTO solicitacoes "
                "(remessa_id, tipo_solicitacao, nome, tipo, descricao, retorno_drs, telefone) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (remessa_id, current_section, nome, tipo, descricao, retorno, telefone),
            )

    conn.commit()
    counts = {
        "remessas": conn.execute("SELECT COUNT(*) FROM remessas").fetchone()[0],
        "solicitacoes": conn.execute("SELECT COUNT(*) FROM solicitacoes").fetchone()[0],
    }
    conn.close()
    return counts


def _unique_patients(temp_db_path: str = None) -> dict[str, str]:
    """Retorna {nome_normalizado: telefone} sem duplicatas."""
    if temp_db_path is None:
        temp_db_path = _default_temp_db_path()
    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT nome, telefone FROM solicitacoes").fetchall()
    conn.close()

    seen: dict[str, str] = {}
    for r in rows:
        nome = to_upper_normalized(r["nome"])
        # Ignora linhas que não são nomes de pacientes:
        # sem letras, sem espaço (rótulos únicos como "ABRIL/2026"),
        # ou contendo "/".
        if not nome or not any(c.isalpha() for c in nome):
            continue
        if "/" in nome or " " not in nome:
            continue
        if nome not in seen:
            seen[nome] = r["telefone"] or ""
        elif not seen[nome] and r["telefone"]:
            seen[nome] = r["telefone"]
    return seen


def transfer_patients(
    db: SS54Database,
    temp_db_path: str = None,
) -> int:
    """Insere pacientes únicos do banco temporário no banco principal.

    Retorna o número de pacientes adicionados.
    """
    if temp_db_path is None:
        temp_db_path = _default_temp_db_path()
    patients = _unique_patients(temp_db_path)
    added = 0
    for nome, telefone in patients.items():
        if db.find_paciente_by_name(nome):
            continue
        db.create_paciente(nome, telefone)
        added += 1
    return added


def transfer_remessas(
    db: SS54Database,
    temp_db_path: str = None,
) -> int:
    """Insere lotes (remessas) do banco temporário no banco principal.

    Cada linha "REMESSA:" vira um Lote com sua data. Ignora remessas
    sem data e não duplica lotes já existentes (por data).

    Retorna o número de lotes adicionados.
    """
    if temp_db_path is None:
        temp_db_path = _default_temp_db_path()
    if not os.path.exists(temp_db_path):
        return 0

    conn = sqlite3.connect(temp_db_path)
    rows = conn.execute("SELECT DISTINCT data FROM remessas").fetchall()
    conn.close()

    existing = {l.date for l in db.get_all_lotes()}
    added = 0
    for (data,) in rows:
        if not data or data in existing:
            continue
        # Toda remessa importada é histórica: marca como enviada usando a
        # própria data da remessa como ``sent_at``.
        db.create_lote(data, sent_at=data)
        added += 1
    return added


def _normalize_tipo(raw: Any) -> str | None:
    """Mapeia o ``tipo`` livre da planilha para uma das 3 categorias do app.

    Retorna ``None`` para valores não mapeáveis (vazios ou números puros),
    que devem ser ignorados na importação.
    """
    t = _norm(raw).upper()
    if not t or t.isdigit():
        return None
    if "NUTRI" in t:
        return "nutricao"
    if "BOMBA" in t or "SENSOR" in t or "INSUMO" in t:
        return "bomba"
    return "medicamento"


def _status_norm(value: Any) -> str:
    """Normaliza texto para matching: sem acentos, MAIÚSCULO, espaços simples."""
    s = fold_diacritics(str(value or "")).upper()
    return " ".join(s.split())


_STATUS_PROTO = re.compile(r"\d{8,}")
_STATUS_NOTIF = [r"ENCAMINHAD", r"AVISAD", r"NAO ATENDE", r"SEM SUCESSO",
                 r"NOTIFICAD", r"NOTIFICAR"]


def _infer_status(retorno: Any) -> Status | None:
    """Infere o status do processo a partir do texto de ``retorno_drs``.

    Retorna a chave canônica do status ou ``None`` quando há texto mas
    nenhum sinal reconhecido (deve ser tratado manualmente). Campo vazio
    vira ``"enviado"`` (a solicitação consta na planilha, logo foi enviada).

    Ordem de prioridade (primeira que casar vence):
      1. encerrado  - óbito/falecimento/judicialização
      2. negado     - indeferido/negativa/"não autorizado"/"não deferido"
      3. autorizado - deferido/autorizado/aprovado
      4. correcao   - relatório solicitado, exceto se reenviado
      5. autorizado - disponível/ligar/compra/em atendimento
      6. correcao   - questionamento do DRS
      7. enviado    - reenviado
      8. correcao   - pendência/correção/corrigir
      9. enviado    - enviado/recebido/cobrado/ver e-mail
     10. enviado    - protocolo DRS
     11. encerrado  - apenas notificação (avisado/encaminhado/etc.)
    """
    t = _status_norm(retorno)
    if not t:
        return Status.ENVIADO

    # 1. Terminal states
    if any(re.search(p, t) for p in (
        r"OBITO", r"FALECID", r"FALECIMENTO", r"FALECEU",
        r"JUDICIALIZ", r"JUDICIAL", r"CANCELAMENTO", r"SOLICITOU CANCEL",
    )):
        return Status.ENCERRADO

    # 2. Definitive denials
    if any(re.search(p, t) for p in (
        r"INDEFERID", r"INDEFERIMENTO", r"NEGAD", r"NEGATIVA",
        r"NAO AUTORIZA", r"NAO DEFERID", r"NAO FOI AUTORIZA",
        r"NAO FOI DEFERID",
    )):
        return Status.NEGADO

    # 3. Definitive approvals
    if any(re.search(p, t) for p in (
        r"DEFERID", r"DEFERIMENTO", r"AUTORIZA", r"APROVAD",
    )):
        return Status.AUTORIZADO

    # 4. Document/report requested -> correction (unless re-submitted)
    if any(k in t for k in ("RELATORIO", "ENVIAR DOCUMENTO")) and not re.search(r"REENVIAD|REEENVIAD|REENVI", t):
        return Status.CORRECAO

    # 5. Weak administrative positive signals
    if any(re.search(p, t) for p in (
        r"DISPONIVEL", r"\bLIGAR\b", r"COMPRA", r"ATENDIMENTO",
    )):
        return Status.AUTORIZADO

    # 6. DRS question -> correction
    if "QUESTIONAMENTO" in t:
        return Status.CORRECAO

    # 7. Re-submitted -> enviado
    if re.search(r"REENVIAD|REEENVIAD|REENVI", t):
        return Status.ENVIADO

    # 8. Other pending / correction
    if any(re.search(p, t) for p in (r"PENDENCIA", r"CORREC", r"CORRIGIR", r"DIVERGENTE")):
        return Status.CORRECAO

    # 9. Generic sent / communication
    if any(re.search(p, t) for p in (
        r"ENVIAD", r"RECEBID", r"COBRAD", r"VER EMAIL", r"VER O EMAIL",
    )):
        return Status.ENVIADO

    # 10. Protocol number fallback
    if _STATUS_PROTO.search(t) or "PROTOCOLO" in t:
        return Status.ENVIADO

    # 11. Notification-only fallback
    if any(re.search(p, t) for p in _STATUS_NOTIF):
        return Status.ENCERRADO

    return None


# Tipos livres que são nomes de medicamentos específicos. Para esses,
# o nome do medicamento vira a descricao do processo e o conteúdo original
# da descricao (normalmente protocolo/data) é prefixado à observacoes.
_DRUG_TIPOS: set[str] = {
    "ALFAEPOETINA 10000UI",
    "ARIPIPRAZOL 15 MG  / FLUVOXAMINA 50 MG",
    "CANABIDIOL 20MG/ML",
    "INSULINA GLARGINA",
}


def _cleanup_tipo_descricao(
    nome: str,
    tipo_raw: str,
    tipo_norm: str,
    descricao: str,
) -> tuple[str, str]:
    """Limpa tipo/descrição para casos específicos da planilha.

    Regras:
      1. Paciente MARGARETE MALTA BASSO com descricao ``BOMBA DE INSULINA``
         vira tipo ``bomba`` e descricao vazia.
      2. Tipos sensor (``SENSOR``, ``SENSOR DE GLICEMIA``) mantêm ``bomba``
         e recebem descricao ``SENSOR DE GLICEMIA``.
      3. Tipos já mapeados para ``bomba`` cuja descrição só repete
         ``bomba``/``insulina`` (ex: "BOMBA DE INSULINA") têm descricao
         removida para evitar redundância.
    """
    desc_up = descricao.upper()

    # Regra 1: Margarete Malta Basso é bomba, mas veio como MEDICAÇÃO
    if nome == "MARGARETE MALTA BASSO" and "BOMBA DE INSULINA" in desc_up:
        return "bomba", ""

    # Regra 2: sensor -> descricao padronizada
    if tipo_raw.upper() in ("SENSOR", "SENSOR DE GLICEMIA"):
        return tipo_norm, "SENSOR DE GLICEMIA"

    # Regra 3: descricao redundante para bomba
    if tipo_norm == "bomba" and ("BOMBA" in desc_up or "INSULINA" in desc_up):
        return tipo_norm, ""

    return tipo_norm, descricao


def _format_drug_entry(
    tipo_raw: str,
    descricao: str,
    retorno: str,
) -> tuple[str, str]:
    """Para medicamentos de nome específico, usa o nome como descricao e
    prefixa o texto original da descricao às observacoes.

    Retorna (descricao, observacoes).
    """
    if tipo_raw not in _DRUG_TIPOS:
        return descricao, retorno
    novo_retorno = f"{descricao} {retorno}".strip() if descricao else retorno
    return tipo_raw, novo_retorno


def transfer_solicitacoes(
    db: SS54Database,
    temp_db_path: str = None,
) -> int:
    """Cria processos a partir das solicitações da planilha.

    Cada linha vira um ``Processo`` no grupo (paciente, lote, tipo,
    solicitacao); o ciclo é o ordinal natural pela ordem de inserção. É
    idempotente: só cria os processos que faltam no grupo, evitando
    duplicar em re-execuções do import.

    ``retorno_drs`` (coluna D) vai para ``observacoes``; o ``status`` é
    inferido do próprio ``retorno_drs`` via ``_infer_status`` (ou fica
    ``NULL`` quando o texto não tem sinal reconhecido).

    Retorna o número de processos adicionados.
    """
    if temp_db_path is None:
        temp_db_path = _default_temp_db_path()
    if not os.path.exists(temp_db_path):
        return 0

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT s.nome, s.tipo_solicitacao, s.tipo, s.descricao, "
        "s.retorno_drs, r.data AS remessa_data "
        "FROM solicitacoes s "
        "JOIN remessas r ON r.id = s.remessa_id "
        "ORDER BY s.id ASC"
    ).fetchall()
    conn.close()

    lotes_por_data = {l.date: l for l in db.get_all_lotes()}

    resolved: list[tuple] = []
    for r in rows:
        tipo = _normalize_tipo(r["tipo"])
        if tipo is None:
            continue
        data = r["remessa_data"]
        if not data:
            continue
        solicitacao = r["tipo_solicitacao"]
        if solicitacao not in ("primeira", "renovacao"):
            continue
        nome = to_upper_normalized(r["nome"])
        if not nome:
            continue
        paciente = db.find_paciente_by_name(nome)
        if paciente is None:
            continue
        lote = lotes_por_data.get(data)
        if lote is None:
            continue
        descricao = _norm(r["descricao"])
        retorno = _norm(r["retorno_drs"])
        tipo, descricao = _cleanup_tipo_descricao(
            nome, r["tipo"], tipo, descricao
        )
        descricao, retorno = _format_drug_entry(r["tipo"], descricao, retorno)
        resolved.append(
            (
                (paciente.id, lote.id, tipo, solicitacao),
                paciente.id,
                lote.id,
                tipo,
                solicitacao,
                descricao,
                retorno,
            )
        )

    grupos: dict[tuple, list[tuple]] = {}
    for item in resolved:
        grupos.setdefault(item[0], []).append(item)

    added = 0
    for key, items in grupos.items():
        paciente_id, lote_id, tipo, solicitacao = key
        lote = db.get_lote_by_id(lote_id)
        existentes = db.get_processos_by_context(
            paciente_id, lote_id, tipo, solicitacao
        )
        for item in items[len(existentes):]:
            _, _, _, _, _, descricao, retorno = item
            lote_year = parse_date(lote.date).year if lote else datetime.now().year
            obs_text = normalize_dates(retorno, lote_year)
            dates = _parse_dates_from_text(obs_text, lote_year)
            log_ts = dates[0].isoformat() if dates else ""
            if dates:
                obs_text = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", "", obs_text).strip()
            db.create_processo(
                paciente_id=paciente_id,
                lote_id=lote_id,
                tipo=tipo,
                solicitacao=solicitacao,
                descricao=descricao,
                observacoes=obs_text,
                status=_infer_status(retorno),
                created_at=lote.date if lote else None,
                log_created_at=log_ts,
            )
            added += 1
    return added


def _parse_dates_from_text(text: str, default_year: int) -> list[datetime]:
    """Extrai datas no formato D/M[/YY] ou DD/MM[/YYYY] de um texto livre.

    Datas sem ano recebem ``default_year`` (normalmente o ano da remessa).
    Retorna uma lista ordenada de ``datetime.date`` únicos.
    """
    dates: list[datetime] = []
    seen: set[tuple[int, int, int]] = set()
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", text):
        try:
            day = int(m.group(1))
            month = int(m.group(2))
            year_str = m.group(3)
            year = default_year if year_str is None else int(year_str)
            if year < 100:
                year += 2000
            dt = datetime(year, month, day).date()
            key = (year, month, day)
            if key not in seen:
                seen.add(key)
                dates.append(dt)
        except ValueError:
            continue
    return sorted(dates)


_DATE_RE = re.compile(
    r"(?P<yy>(?:\b|(?<=/))\d{4})[ -]*\d{1,2}[ /]{1,2}\d{1,2}"
    r"|(?P<h>(?:\b|(?<=/))\d{1,2}[ -]\d{1,2}(?![\d/]))"
    r"|(?P<s>(?:\b|(?<=/))\d{1,2}[ /]{1,2}\d{1,2}(?:/\d{2,4})?)"
)


def _norm_date_token(token: str) -> tuple[int, int, int | None]:
    """Split a D[ /]M[ /][YY] token into (day, month, year_or_None)."""
    parts = re.split(r"[ /-]+", token.strip())
    d, mo = int(parts[0]), int(parts[1])
    year = None
    if len(parts) > 2:
        y = parts[2]
        if y:
            year = int(y)
            if year < 100:
                year += 2000
    return d, mo, year


def normalize_dates(text: str, default_year: int) -> str:
    """Normaliza todas as datas livres de ``text`` para ``DD/MM/YYYY``.

    Aceita formatos separados por barra (``D/M``, ``D/M/AA``, ``D/M/AAAA``,
    incluindo barras duplas ``D//M``) e por hífen (``D-M``, ``AAAA- D/M``).
    Datas sem ano recebem ``default_year`` (normalmente o ano da remessa).
    Não altera o restante do texto (ex.: números de protocolo). Usado na
    importação para deixar o histórico de ``observacoes`` consistente.
    """
    if not text:
        return text

    def _replace(m: "re.Match") -> str:
        if m.group("yy"):
            prefix = m.group("yy")
            rest = m.string[m.end() : m.end() + 10]
            inner = re.search(r"\d{1,2}[ /]{1,2}\d{1,2}", rest)
            if not inner:
                return m.group(0)
            d, mo, _yr = _norm_date_token(inner.group(0))
            try:
                dt = datetime(int(prefix), mo, d).date()
            except ValueError:
                return m.group(0)
            return dt.strftime("%d/%m/%Y")
        if m.group("h"):
            d, mo, _yr = _norm_date_token(m.group("h"))
            try:
                dt = datetime(default_year, mo, d).date()
            except ValueError:
                return m.group("h")
            return dt.strftime("%d/%m/%Y")
        d, mo, year = _norm_date_token(m.group("s"))
        if year is None:
            year = default_year
        try:
            dt = datetime(year, mo, d).date()
        except ValueError:
            return m.group("s")
        return dt.strftime("%d/%m/%Y")

    return _DATE_RE.sub(_replace, text)


def expire_old_autorizados(
    db: SS54Database,
    dias_limite: int = 180,
    dias_limite_sem_data: int = 210,
) -> int:
    """Marca como ``expirado`` os processos ``autorizado`` antigos.

    Regra:
      - Se houver datas parseáveis em ``observacoes`` e alguma for anterior
        a ``hoje - dias_limite``, expira.
      - Se não houver datas parseáveis em ``observacoes``, expira se a data
        da remessa + ``dias_limite_sem_data`` já tiver passado.

    Retorna o número de processos expirados.
    """
    hoje = datetime.now().date()
    cutoff_com_data = hoje - timedelta(days=dias_limite)
    processos = db.get_processos_by_status(Status.AUTORIZADO)

    expirados = 0
    for p in processos:
        observacoes = p.observacoes or ""
        lote_date = parse_date(p.lote_date or "")
        lote_year = lote_date.year

        dates = _parse_dates_from_text(observacoes, lote_year)
        if dates:
            if any(d < cutoff_com_data for d in dates):
                db.update_processo_status(p.id, Status.EXPIRADO)
                expirados += 1
        else:
            cutoff_sem_data = lote_date + timedelta(days=dias_limite_sem_data)
            if hoje > cutoff_sem_data:
                db.update_processo_status(p.id, Status.EXPIRADO)
                expirados += 1
    return expirados


def run_import(
    xlsx_path: str = None,
    temp_db_path: str = None,
) -> dict[str, Any]:
    """Executa extração + transferência de pacientes. Retorna estatísticas."""
    from bap.utils.bootstrap import ensure_initialized

    ensure_initialized()

    if xlsx_path is None:
        xlsx_path = _default_xlsx_path()
    if temp_db_path is None:
        temp_db_path = _default_temp_db_path()

    counts = extract_xlsx_to_temp(xlsx_path, temp_db_path)
    db = SS54Database()
    added = transfer_patients(db, temp_db_path)
    lotes = transfer_remessas(db, temp_db_path)
    processos = transfer_solicitacoes(db, temp_db_path)
    expirados = expire_old_autorizados(db)
    total = db.get_all_pacientes()
    db.close()

    return {
        "remessas": counts["remessas"],
        "solicitacoes": counts["solicitacoes"],
        "pacientes_adicionados": added,
        "lotes_adicionados": lotes,
        "processos_adicionados": processos,
        "processos_expirados": expirados,
        "pacientes_total": len(total),
    }


if __name__ == "__main__":
    stats = run_import()
    print("Import concluído:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
