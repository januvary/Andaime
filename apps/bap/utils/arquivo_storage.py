from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from andaime.paths import get_root_directory
from andaime.dates import parse_date


def resolve_arquivos_root(config: Path | dict | None = None) -> Path:
    if config is not None:
        if isinstance(config, Path):
            return config
        if isinstance(config, dict) and config.get("arquivos_root"):
            return Path(config["arquivos_root"])
    return get_root_directory() / "REMESSAS"


def _safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "_").replace("/", "_")
    if not name:
        name = "arquivo"
    return name


def _tipo_folder(solicitacao: str) -> str:
    return "SOLICITAÇÕES" if solicitacao == "primeira" else "RENOVAÇÕES"


def remessa_folder_relpath(lote_date: str, solicitacao: str) -> str:
    """Caminho relativo (estilo POSIX) da pasta da remessa: ``REMESSAS/YYYY/MM-DD/TIPO``.

    Usado tanto no disco quanto como espelho de pastas no Google Drive, para
    manter a mesma estrutura nos dois lugares.
    """
    d = parse_date(lote_date)
    if d is None:
        year, mmdd = "0000", "00-00"
    else:
        year = f"{d.year:04d}"
        mmdd = f"{d.month:02d}-{d.day:02d}"
    return f"REMESSAS/{year}/{mmdd}/{_tipo_folder(solicitacao)}"


def build_processo_dir(
    root: Path,
    lote_date: str,
    solicitacao: str,
    paciente_nome: str,
    tipo: str,
    ciclo: int = 1,
) -> Path:
    d = parse_date(lote_date)
    if d is None:
        year, mmdd = "0000", "00-00"
    else:
        year = f"{d.year:04d}"
        mmdd = f"{d.month:02d}-{d.day:02d}"

    # PDFs ficam direto na pasta do tipo (sem subpasta por paciente).
    d = root / year / mmdd / _tipo_folder(solicitacao)
    d.mkdir(parents=True, exist_ok=True)
    return d


def merge_conteudos_to_pdf(conteudos: "Iterable[bytes]", output_path: str) -> str:
    """Une PDFs (bytes) em um único PDF salvo em ``output_path``.

    Aceita qualquer iterável de bytes — incluindo um gerador que resolve os
    BLOBs sob demanda — de modo que os conteúdos não precisam estar todos na
    memória ao mesmo tempo.
    """
    from andaime.pdf import merge_pdfs

    merge_pdfs(conteudos, output_path)
    return output_path


def compute_processo_sig(arqs: list) -> str:
    """Assinatura estável do conjunto de arquivos de um processo (só metadados).

    Deriva de ``(id, ordem, content_sha256)`` de cada arquivo — **sem ler nenhum
    BLOB** — de modo que a decisão de regenerar o PDF combinado é O(1) em disco.
    A assinatura muda se um arquivo é adicionado/removido, reordenado ou tem
    seu conteúdo alterado (o ``content_sha256`` é regravado a cada escrita, na
    mesma transação do BLOB). ``tipo_documento`` fica de fora: é classificação,
    não conteúdo da página — mudá-lo não deve forçar regenerar o PDF.
    """
    h = hashlib.sha256()
    for a in sorted(arqs, key=lambda x: (x.ordem, x.id)):
        h.update(f"{a.id}|{a.ordem}|{a.content_sha256}".encode())
        h.update(b";")
    return h.hexdigest()

