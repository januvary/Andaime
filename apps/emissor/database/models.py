#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Models
Dataclasses para entidades do banco de dados Emissor.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from andaime.dates import parse_date


def _normalize_date_display(value: str) -> str:
    """Convert a stored date (ISO or BR) to BR ``DD/MM/YYYY`` for display.

    Unparseable or empty values are returned unchanged.
    """
    if not value:
        return ""
    parsed = parse_date(value)
    return parsed.strftime("%d/%m/%Y") if parsed else value


@dataclass
class CatalogItem:
    """Item do catálogo de medicamentos/materiais."""

    item_id: str = ""
    descricao: str = ""
    unidade: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any] | Any) -> CatalogItem:
        d = dict(row) if not isinstance(row, dict) else row
        return cls(
            item_id=d.get("item_id", ""),
            descricao=d.get("descricao", ""),
            unidade=d.get("unidade", ""),
        )


@dataclass
class PatientItem:
    """Item vinculado a um paciente (com quantidade e dias)."""

    item_id: str = ""
    descricao: str = ""
    unidade: str = ""
    quantidade: str = ""
    dias: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any] | Any) -> PatientItem:
        d = dict(row) if not isinstance(row, dict) else row
        return cls(
            item_id=d.get("item_id", ""),
            descricao=d.get("descricao", "") or d.get("item_id", ""),
            unidade=d.get("unidade", "") or "",
            quantidade=d.get("quantidade", ""),
            dias=d.get("dias", ""),
        )


@dataclass
class Patient(Mapping):
    """Paciente com dados básicos, metadata e itens."""

    id: int | None = None
    nome: str = ""
    processo_n: str = ""
    extra_processos: list[str] = field(default_factory=list)
    profissional_id: int | None = None
    profissional_nome: str = ""
    profissional_crm: str = ""
    matricula: str = ""
    telefone: str = ""
    tipo: str = ""
    periodicidade: str = ""
    ultima_receita: str = ""
    tipo_receita: str = ""
    observacoes: str = ""
    atendido_por: str = ""
    tem_retirada: bool = False
    itens: list[PatientItem] = field(default_factory=list)

    def __getitem__(self, key: str) -> Any:
        # processo_n é o campo base (índice 1); processo_2_n, processo_3_n... extras.
        if key == "processo_n":
            return self.processo_n
        if key.startswith("processo_") and key.endswith("_n"):
            middle = key[len("processo_") : -2]
            if middle.isdigit():
                return self.get_processo(int(middle))
        if key in self.__dataclass_fields__:
            return getattr(self, key)
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        yield from self.__dataclass_fields__
        for i in range(len(self.extra_processos)):
            yield f"processo_{i + 2}_n"

    def __len__(self) -> int:
        return len(self.__dataclass_fields__) + len(self.extra_processos)

    def get_processos(self) -> list[str]:
        """Retorna lista de todos os processos (principal + extras)."""
        result = []
        if self.processo_n:
            result.append(self.processo_n)
        result.extend(p for p in self.extra_processos if p)
        return result

    def get_processo(self, index: int) -> str:
        """Retorna processo pelo índice (1-based). Index 1 = processo_n.

        Índices além dos processos preenchidos retornam "" (nunca levantam).
        """
        if index == 1:
            return self.processo_n
        if 2 <= index <= len(self.extra_processos) + 1:
            return self.extra_processos[index - 2]
        return ""

    def set_processo(self, index: int, value: str) -> None:
        """Define processo pelo índice (1-based). Index 1 = processo_n."""
        if index == 1:
            self.processo_n = value
        else:
            extra_idx = index - 2
            while len(self.extra_processos) <= extra_idx:
                self.extra_processos.append("")
            self.extra_processos[extra_idx] = value

    def processo_count(self) -> int:
        """Retorna quantidade de processos preenchidos."""
        count = 1 if self.processo_n else 0
        count += sum(1 for p in self.extra_processos if p)
        return count

    @classmethod
    def from_row(
        cls, row: dict[str, Any] | Any, items: list[PatientItem] | None = None
    ) -> Patient:
        d = dict(row) if not isinstance(row, dict) else row
        extra_processos = []
        for i in range(2, 11):
            key = f"processo_{i}_n"
            extra_processos.append(d.get(key, "") or "")
        return cls(
            id=d.get("id"),
            nome=d.get("nome", ""),
            processo_n=d.get("processo_n", "") or "",
            extra_processos=extra_processos,
            profissional_id=d.get("profissional_id"),
            profissional_nome=d.get("profissional_nome", "") or "",
            profissional_crm=d.get("profissional_crm", "") or "",
            matricula=d.get("matricula", "") or "",
            telefone=d.get("telefone", "") or "",
            tipo=d.get("tipo", "") or "",
            periodicidade=str(d.get("periodicidade", "") or ""),
            ultima_receita=_normalize_date_display(d.get("ultima_receita", "") or ""),
            tipo_receita=d.get("tipo_receita", "") or "",
            observacoes=d.get("observacoes", "") or "",
            atendido_por=d.get("atendido_por", "") or "",
            tem_retirada=bool(d.get("tem_retirada", 0)),
            itens=items or [],
        )


@dataclass
class RetiradaItem:
    """Snapshot de item em uma retirada."""

    item_id: str = ""
    descricao: str = ""
    unidade: str = ""
    quantidade: str = ""
    dias: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any] | Any) -> RetiradaItem:
        d = dict(row) if not isinstance(row, dict) else row
        return cls(
            item_id=d.get("item_id", ""),
            descricao=d.get("descricao", ""),
            unidade=d.get("unidade", ""),
            quantidade=d.get("quantidade", ""),
            dias=d.get("dias", ""),
        )


@dataclass
class Retirada:
    """Registro de retirada (cabeçalho)."""

    id: int | None = None
    patient_id: int | None = None
    patient_name: str = ""
    data_retirada: str = ""
    data_proxima_retirada: str = ""
    substituida: int = 0
    matricula: str = ""
    profissional: str = ""
    crm: str = ""
    tipo_receita: str = ""
    created_at: str = ""
    updated_at: str = ""
    tipo: str = ""
    itens: list[RetiradaItem] = field(default_factory=list)

    @classmethod
    def from_row(
        cls, row: dict[str, Any] | Any, items: list[RetiradaItem] | None = None
    ) -> Retirada:
        d = dict(row) if not isinstance(row, dict) else row
        return cls(
            id=d.get("id"),
            patient_id=d.get("patient_id"),
            patient_name=d.get("patient_name", ""),
            data_retirada=d.get("data_retirada", ""),
            data_proxima_retirada=d.get("data_proxima_retirada", ""),
            substituida=d.get("substituida", 0),
            matricula=d.get("matricula", "") or "",
            profissional=d.get("profissional", "") or "",
            crm=d.get("crm", "") or "",
            tipo_receita=d.get("tipo_receita", "") or "",
            created_at=d.get("created_at", "") or "",
            updated_at=d.get("updated_at", "") or "",
            tipo=d.get("tipo", "") or "",
            itens=items or [],
        )
