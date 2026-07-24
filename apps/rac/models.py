from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Malote:
    id: int | None = None
    date: str = ""
    arrival_date: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Malote:
        return cls(
            id=row.get("id"),
            date=row.get("date", ""),
            arrival_date=row.get("arrival_date"),
        )


@dataclass
class Paciente:
    id: int | None = None
    name: str = ""
    last_registro_date: str | None = None
    last_registro_tipo: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Paciente:
        return cls(
            id=row.get("id"),
            name=row.get("name", ""),
            last_registro_date=row.get("last_registro_date"),
            last_registro_tipo=row.get("last_registro_tipo"),
        )


@dataclass
class ItemCatalog:
    id: int | None = None
    name: str = ""
    unidade: str = "un"
    cids: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ItemCatalog:
        return cls(
            id=row.get("id"),
            name=row.get("name", ""),
            unidade=row.get("unidade", "un"),
            cids=row.get("cids", ""),
        )


@dataclass
class Registro:
    id: int | None = None
    tipo: str = ""
    paciente_id: int | None = None
    malote_id: int | None = None
    created_at: str = ""
    paciente_name: str | None = None
    malote_date: str | None = None
    waiting_docs: bool = False

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Registro:
        return cls(
            id=row.get("id"),
            tipo=row.get("tipo", ""),
            paciente_id=row.get("paciente_id"),
            malote_id=row.get("malote_id"),
            created_at=row.get("created_at", ""),
            paciente_name=row.get("paciente_name"),
            malote_date=row.get("malote_date"),
            waiting_docs=bool(row.get("waiting_docs", 0)),
        )


@dataclass
class Process:
    id: int | None = None
    registro_id: int | None = None
    group_number: int = 1
    months_supply: int = 0
    expected_return_date: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Process:
        return cls(
            id=row.get("id"),
            registro_id=row.get("registro_id"),
            group_number=row.get("group_number", 1),
            months_supply=row.get("months_supply", 0),
            expected_return_date=row.get("expected_return_date"),
        )


@dataclass
class RegistroItem:
    id: int | None = None
    registro_id: int | None = None
    process_id: int | None = None
    item_id: int | None = None
    item_name: str | None = None
    unidade: str | None = None
    process_group: int = 1
    cid: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RegistroItem:
        return cls(
            id=row.get("id"),
            registro_id=row.get("registro_id"),
            process_id=row.get("process_id"),
            item_id=row.get("item_id"),
            item_name=row.get("item_name"),
            unidade=row.get("unidade"),
            process_group=row.get("process_group", 1),
            cid=row.get("cid", ""),
        )


@dataclass
class ProcessExport:
    group_number: int = 1
    items: list[str] = field(default_factory=list)
    expected_return_date: str | None = None


@dataclass
class RegistroExport:
    id: int | None = None
    tipo: str = ""
    paciente_id: int | None = None
    paciente_name: str | None = None
    processes: list[ProcessExport] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RegistroExport:
        return cls(
            id=row.get("id"),
            tipo=row.get("tipo", ""),
            paciente_id=row.get("paciente_id"),
            paciente_name=row.get("paciente_name"),
        )
