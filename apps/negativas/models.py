"""Medicamentos e modelos de texto para Sistema de Negativas"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Medicamento:
    id: int
    nome: str
    categoria: str  # CEAF, USAFA, CAPS II
    cids: List[str]
    disponivel: bool = True  # False se estiver em falta

    @classmethod
    def from_row(cls, row: dict) -> "Medicamento":
        """Cria Medicamento a partir de uma linha do banco."""
        cids = row.get("cids", "[]")
        if isinstance(cids, str):
            import json
            cids = json.loads(cids)

        disponivel = row.get("disponivel", 1)
        if isinstance(disponivel, int):
            disponivel = bool(disponivel)

        return cls(
            id=row["id"],
            nome=row["nome"],
            categoria=row["categoria"],
            cids=cids if isinstance(cids, list) else [],
            disponivel=disponivel
        )


@dataclass
class ModeloTexto:
    id: int
    tipo: str
    texto: str

    @classmethod
    def from_row(cls, row: dict) -> "ModeloTexto":
        return cls(
            id=row["id"],
            tipo=row["tipo"],
            texto=row["texto"]
        )


@dataclass
class ItemSelecionado:
    """Item selecionado para gerar documento."""
    id: int
    nome: str
    categoria: str
    em_falta: bool = False
    is_medicamento: bool = True


@dataclass
class NegativaData:
    """Snapshot imutável do estado do formulário para gerar o documento."""
    destinatario: str = "autoridade competente"
    usos_daf: bool = True
    usos_dgmi: bool = False
    nome_daf: str = ""
    nome_dgmi: str = ""
    itens: List[ItemSelecionado] = field(default_factory=list)