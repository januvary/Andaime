from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable, ClassVar

from typing_extensions import Self

from src.constants import Status


def _identity(value: Any) -> Any:
    return value


@dataclass
class RowModel:
    CONVERTERS: ClassVar[dict[str, Callable[[Any], Any]]] = {}
    EXCLUDE: ClassVar[set[str]] = set()

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Self:
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            raw = row.get(f.name, f.default)
            kwargs[f.name] = cls.CONVERTERS.get(f.name, _identity)(raw)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            f.name: getattr(self, f.name)
            for f in fields(self)
            if f.name not in self.EXCLUDE
        }


@dataclass
class Paciente(RowModel):
    id: int | None = None
    nome: str = ""
    telefone: str = ""
    created_at: str = ""


@dataclass
class Lote(RowModel):
    id: int | None = None
    date: str = ""
    sent_at: str | None = None


@dataclass
class Processo(RowModel):
    id: int | None = None
    protocolo: str = ""
    paciente_id: int | None = None
    lote_id: int | None = None
    tipo: str = ""
    solicitacao: str = ""
    status: str = Status.EM_ANALISE
    descricao: str = ""
    protocolo_drs: str = ""
    observacoes: str = ""
    pdf_sig: str | None = None
    created_at: str = ""
    sent_at: str | None = None
    result_at: str | None = None
    paciente_nome: str | None = None
    paciente_telefone: str | None = None
    lote_date: str | None = None
    last_obs: str = ""
    last_obs_at: str = ""


@dataclass
class Arquivo(RowModel):
    EXCLUDE = {"conteudo"}
    CONVERTERS = {"validado": bool}

    id: int | None = None
    processo_id: int | None = None
    tipo_documento: str = ""
    arquivo_original: str = ""
    caminho: str | None = None
    conteudo: bytes | None = None
    ordem: int = 0
    validado: bool = False
    content_sha256: str = ""
    created_at: str = ""


def image_to_pdf_bytes(source: str | bytes, filetype: str = "") -> bytes:
    """Converte uma imagem (caminho ou bytes) em um PDF de página única."""
    from andaime.pdf import image_to_pdf

    return image_to_pdf(source, filetype)


@dataclass
class GridItem:
    page: int | None = 0
    arquivo_id: int | None = None
    arquivo_original: str = ""
    tipo_documento: str = "outro"
    path: str | None = None
    data: bytes | None = None

    @property
    def display_name(self) -> str:
        return (
            self.arquivo_original
            or (Path(self.path).name if self.path else "documento.pdf")
        )

    def raw_bytes(
        self, loader: "Callable[[GridItem], bytes | None] | None" = None
    ) -> bytes | None:
        """Resolve o conteúdo do item como bytes de PDF."""
        if self.data is not None:
            return bytes(self.data)
        if self.path is not None:
            if Path(self.path).suffix.lower() == ".pdf":
                with open(self.path, "rb") as f:
                    return f.read()
            return image_to_pdf_bytes(self.path)
        if loader is not None and self.arquivo_id is not None:
            return loader(self)
        return None

    def open_document(self, loader: Callable[[GridItem], bytes | None] | None = None):
        """Abre o conteúdo como ``pypdf.PdfReader``."""
        from andaime.pdf import open_pdf

        raw = self.raw_bytes(loader)
        return open_pdf(raw) if raw else None

    def to_pdf_bytes(
        self, loader: Callable[[GridItem], bytes | None] | None = None
    ) -> bytes | None:
        """Extrai a página do item como PDF de página única (bytes)."""
        from andaime.pdf import extract_page

        if self.data is not None and self.path is None:
            return bytes(self.data)

        raw = self.raw_bytes(loader)
        if not raw:
            return None
        return extract_page(raw, self.page or 0)
