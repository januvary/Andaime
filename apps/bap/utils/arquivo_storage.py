from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

from andaime.paths import find_parent_dir, get_root_directory
from andaime.dates import parse_date
from andaime.pdf import merge_pdfs


def _find_ss54_dir() -> Path | None:
    return find_parent_dir(Path.cwd(), "SS 54")


def resolve_arquivos_root(config: Path | dict | None = None) -> Path:
    if config is not None:
        if isinstance(config, Path):
            return config
        if isinstance(config, dict) and config.get("arquivos_root"):
            return Path(config["arquivos_root"])
        # Handle SS54Config objects (which have to_dict() method)
        if hasattr(config, "to_dict") and callable(getattr(config, "to_dict")):
            config_dict = config.to_dict()
            if config_dict.get("arquivos_root"):
                return Path(config_dict["arquivos_root"])
    ss54 = _find_ss54_dir()
    if ss54 is not None:
        return ss54 / "REMESSAS"
    return get_root_directory() / "SS 54" / "REMESSAS"


def _safe_filename(name: str) -> str:
    name = name.strip().replace("\\", "_").replace("/", "_")
    if not name:
        name = "arquivo"
    return name


def _tipo_folder(solicitacao: str) -> str:
    return "SOLICITAÇÕES" if solicitacao == "primeira" else "RENOVAÇÕES"


def remessa_folder_relpath(lote_date: str, solicitacao: str) -> str:
    """Caminho relativo da pasta da remessa: ``REMESSAS/YYYY/MM-DD/TIPO``."""
    d = parse_date(lote_date)
    if d is None:
        year, mmdd = "0000", "00-00"
    else:
        year = f"{d.year:04d}"
        mmdd = f"{d.month:02d}-{d.day:02d}"
    return f"REMESSAS/{year}/{mmdd}/{_tipo_folder(solicitacao)}"


def processo_dir_path(
    root: Path,
    lote_date: str,
    solicitacao: str,
    paciente_nome: str,
    tipo: str,
    ciclo: int = 1,
) -> Path:
    """Caminho da pasta do processo (não cria em disco)."""
    d = parse_date(lote_date)
    if d is None:
        year, mmdd = "0000", "00-00"
    else:
        year = f"{d.year:04d}"
        mmdd = f"{d.month:02d}-{d.day:02d}"

    # PDFs ficam direto na pasta do tipo (sem subpasta por paciente).
    return root / year / mmdd / _tipo_folder(solicitacao)


def merge_conteudos_to_pdf(conteudos: "Iterable[bytes]", output_path: str) -> str:
    """Une PDFs (bytes) em um único PDF salvo em ``output_path``."""
    merge_pdfs(conteudos, output_path)
    return output_path


def compute_processo_sig(arqs: list) -> str:
    """Assinatura estável do conjunto de arquivos (só metadados, sem ler BLOBs)."""
    h = hashlib.sha256()
    for a in sorted(arqs, key=lambda x: (x.ordem, x.id)):
        h.update(f"{a.id}|{a.ordem}|{a.content_sha256}".encode())
        h.update(b";")
    return h.hexdigest()

