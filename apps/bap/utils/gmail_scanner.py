"""Escaneia e-mails do Gmail em busca de menções a pacientes.

Lê as mensagens recentes da caixa de entrada, extrai o corpo do texto e
compara com os nomes dos pacientes via *fuzzy matching* (``rapidfuzz``).
Quando há correspondência (≥ 90), infere o status provável a partir do
conteúdo e registra no banco (``drs_messages``).
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timezone

from rapidfuzz import fuzz
from rapidfuzz.process import extractOne

from bap.utils.import_remessas import _infer_status, _status_norm


# Limite inferior (exclusivo) para o escaneamento de e-mails DRS.
# "after:AAAA/MM/DD" considera mensagens posteriores a essa data; usar o
# dia seguinte a junho (30/06) cobre 01/07/2026 em diante.
SCAN_AFTER_DATE = "2026/06/30"


def _decode_body_data(data: str) -> str:
    padded = data + "=" * (4 - len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _strip_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


def _extract_body(payload: dict) -> str:
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    if body.get("data"):
        text = _decode_body_data(body["data"])
        if mime == "text/html":
            return _strip_html(text)
        return text

    parts = payload.get("parts", [])
    for part in parts:
        pmime = part.get("mimeType", "")
        if pmime == "text/plain":
            pbody = part.get("body", {})
            if pbody.get("data"):
                return _decode_body_data(pbody["data"])

    for part in parts:
        pmime = part.get("mimeType", "")
        if pmime == "text/html":
            pbody = part.get("body", {})
            if pbody.get("data"):
                return _strip_html(_decode_body_data(pbody["data"]))

    for part in parts:
        nested = part.get("parts", [])
        if nested:
            result = _extract_body(part)
            if result:
                return result

    return ""


def _extract_headers(msg: dict) -> dict[str, str]:
    headers = {}
    for h in msg.get("payload", {}).get("headers", []):
        headers[h["name"]] = h["value"]
    return headers


def _internal_date_to_iso(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts) / 1000, tz=timezone.utc)
        return dt.isoformat()
    except (ValueError, OSError):
        return ""


def _find_name_pos(body_norm: str, nome_norm: str) -> int | None:
    """Localiza o início da menção do paciente no texto normalizado.

    Retorna a posição do *primeiro* token do nome que aparece no corpo
    (geralmente o prenome, que marca o início real da menção). Assim os
    segmentos por paciente terminam antes do nome seguinte começar,
    evitando contaminação do status inferido.
    """
    tokens = [t for t in nome_norm.split() if len(t) >= 3]
    positions = [body_norm.find(t) for t in tokens]
    positions = [p for p in positions if p != -1]
    return min(positions) if positions else None


def scan_drs_messages(db, service, max_results: int = 100) -> int:
    """Escaneia e-mails recentes e registra menções a pacientes.

    Retorna o número de novas menções encontradas.
    """
    pacientes = db.get_all_pacientes()
    name_map = [
        (p.id, _status_norm(p.nome))
        for p in pacientes
        if p.nome and len(p.nome.strip()) >= 5
    ]
    if not name_map:
        return 0

    scanned_ids = db.get_scanned_message_ids()

    try:
        results = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=["INBOX"],
                q=f"after:{SCAN_AFTER_DATE}",
                maxResults=max_results,
            )
            .execute()
        )
    except Exception:
        return 0

    new_count = 0
    for m in results.get("messages", []):
        msg_id = m["id"]
        if msg_id in scanned_ids:
            continue

        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
        except Exception:
            continue

        body = _extract_body(msg.get("payload", {}))
        body_norm = _status_norm(body)
        if not body_norm:
            continue

        headers = _extract_headers(msg)
        subject = headers.get("Subject", "")
        from_email = headers.get("From", "")
        msg_date = _internal_date_to_iso(msg.get("internalDate", ""))
        snippet = body.strip()[:300]

        # Coleta as menções e suas posições no corpo para inferir o status
        # de forma isolada por paciente (um e-mail pode conter vários).
        matches: list[tuple[int, int | None]] = []  # (paciente_id, pos)
        for pid, nome_norm in name_map:
            res = extractOne(
                nome_norm, [body_norm], scorer=fuzz.partial_ratio, score_cutoff=90
            )
            if res is None:
                continue
            if fuzz.token_set_ratio(nome_norm, res[0]) < 90:
                continue
            matches.append((pid, _find_name_pos(body_norm, nome_norm)))

        if not matches:
            continue

        # Supressão de subconjunto: se o nome de um paciente detectado é
        # subconjunto estrito do de outro no mesmo e-mail, mantém o mais
        # específico (evita que um nome curto "sequestre" a menção do longo).
        _name_tokens = {pid: set(nome.split()) for pid, nome in name_map}
        drop: set[int] = set()
        for pid_a, _ in matches:
            for pid_b, _ in matches:
                if pid_a != pid_b and _name_tokens[pid_a] < _name_tokens[pid_b]:
                    drop.add(pid_a)
        matches = [(pid, pos) for pid, pos in matches if pid not in drop]

        # Ordena por posição para dividir o corpo em segmentos por paciente.
        matches.sort(key=lambda x: x[1] if x[1] is not None else -1)
        n = len(matches)

        for i, (pid, pos) in enumerate(matches):
            if pos is None:
                segment = body_norm
            else:
                start = pos
                nxt = matches[i + 1][1] if i + 1 < n else None
                end = nxt if nxt is not None else len(body_norm)
                segment = body_norm[start:end]

            inferred = _infer_status(segment)
            created = db.create_drs_message(
                paciente_id=pid,
                message_id=msg_id,
                thread_id=msg.get("threadId", ""),
                from_email=from_email,
                subject=subject,
                snippet=snippet,
                body=body,
                message_date=msg_date,
                inferred_status=inferred or "",
            )
            if created:
                new_count += 1

    return new_count
