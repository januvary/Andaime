from __future__ import annotations

from typing import Optional

IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".jp2"})


def delete_arquivos_before(db, cutoff: str) -> dict:
    """Remove todos os arquivos de processos em remessas anteriores a ``cutoff``.

    Deleta tanto os metadados (tabela ``arquivos``) quanto os BLOBs
    (``arqdb.arquivo_conteudos``) dos arquivos cujo processo pertence a um
    lote com data < ``cutoff`` (formato YYYY-MM-DD). Operação idempotente.
    """
    report = {"processos_afetados": 0, "arquivos_removidos": 0, "erros": 0}
    try:
        rows = db._fetch_all(
            "SELECT a.id, a.processo_id FROM arquivos a "
            "JOIN processos p ON a.processo_id = p.id "
            "JOIN lotes l ON p.lote_id = l.id "
            f"WHERE l.date < '{cutoff}'"
        )
    except Exception as e:  # noqa: BLE001
        report["erros"] += 1
        report["error_detail"] = [str(e)]
        return report

    pids = {r["processo_id"] for r in rows}
    report["processos_afetados"] = len(pids)
    report["arquivos_removidos"] = len(rows)
    for r in rows:
        try:
            db.delete_arquivo(r["id"])
        except Exception:  # noqa: BLE001
            report["erros"] += 1
    return report
