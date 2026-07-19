"""Detecção de pacientes duplicados (mesma pessoa com nomes distintos).

O cadastro veio com nomes pouco confiáveis (sobrenomes faltando, erros de
digitação, variações fonéticas), então a mesma pessoa costuma aparecer em
mais de um registro. Esta rotina acha pares de pacientes cujos nomes são
suficientemente semelhantes para serem o mesmo indivíduo.
"""

from __future__ import annotations


from rapidfuzz import fuzz

from bap.utils.import_remessas import _status_norm


def find_duplicate_patients(
    db, threshold: float = 90.0
) -> list[dict]:
    """Retorna pares de pacientes que provavelmente são a mesma pessoa.

    Cada item traz os dois ids, os nomes originais, a pontuação de
    similaridade (``token_set_ratio``) e a quantidade de processos de cada
    um, para ajudar na decisão de mesclagem.
    """
    pacientes = db.get_all_pacientes()
    rows = [
        (p.id, p.nome, _status_norm(p.nome))
        for p in pacientes
        if p.nome and len(p.nome.strip()) >= 5
    ]
    counts = {pid: db.count_processos_by_paciente(pid) for pid, _, _ in rows}

    results: list[dict] = []
    n = len(rows)
    for i in range(n):
        pid_i, nome_i, norm_i = rows[i]
        for j in range(i + 1, n):
            pid_j, nome_j, norm_j = rows[j]
            score = fuzz.token_set_ratio(norm_i, norm_j)
            if score >= threshold:
                results.append({
                    "pid_a": pid_i,
                    "nome_a": nome_i,
                    "pid_b": pid_j,
                    "nome_b": nome_j,
                    "score": score,
                    "count_a": counts.get(pid_i, 0),
                    "count_b": counts.get(pid_j, 0),
                })

    results.sort(key=lambda r: r["score"], reverse=True)
    return results
