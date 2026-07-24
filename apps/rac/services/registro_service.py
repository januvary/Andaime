#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from rac.database.rac_database import RACDatabase
from rac.models import Registro, RegistroItem, RegistroExport
from rac.services.exceptions import ValidationError, DuplicateRecordError
from rac.utils.date_calculator import calculate_return_dates

import sqlite3


@dataclass
class SaveResult:
    registro_id: int
    is_update: bool


@dataclass
class EditContext:
    registro: Registro
    items: list[tuple[int, int, str]]
    processes: list[tuple[int, int]]


@dataclass
class ContextResult:
    registro: Registro | None
    items: list[tuple[int, int, str]]
    processes: list[tuple[int, int]]
    suggested_items: list[tuple[int, int, str]]


@dataclass
class DeleteSnapshot:
    tipo: str
    paciente_id: int
    malote_id: int
    waiting_docs: bool
    items: list[tuple[int, int, str]]
    process_months: list[tuple[int, int]]


class RegistroService:
    def __init__(self, db: RACDatabase) -> None:
        self._db = db

    def get(self, registro_id: int) -> Registro | None:
        return self._db.get_registro_by_id(registro_id)

    def get_items(self, registro_id: int) -> list[RegistroItem]:
        return self._db.get_items_by_registro(registro_id)

    def get_by_paciente(self, paciente_id: int) -> list[Registro]:
        return self._db.get_registros_by_paciente(paciente_id)

    def search_by_paciente(
        self, query: str, malote_id: int | None = None, limit: int = 20
    ) -> list[Registro]:
        return self._db.search_registros_by_paciente(query, malote_id, limit)

    def get_with_items_by_malote(self, malote_id: int) -> list[RegistroExport]:
        return self._db.get_registros_with_items_by_malote(malote_id)

    def get_by_malote(self, malote_id: int) -> list[Registro]:
        return self._db.get_registros_by_malote(malote_id)

    def update(
        self,
        id: int,
        tipo: str,
        paciente_id: int,
        malote_id: int,
        items: list[tuple[int, int, str]],
        waiting_docs: bool,
        process_months: list[tuple[int, int]] | None = None,
    ) -> SaveResult:
        updated = self._db.update_registro(
            id,
            tipo=tipo,
            paciente_id=paciente_id,
            malote_id=malote_id,
            waiting_docs=waiting_docs,
        )
        if not updated:
            raise ValidationError("Registro não encontrado")
        if process_months is not None:
            self._save_processes(id, tipo, malote_id, waiting_docs, process_months, items)
        else:
            self._db.set_registro_items(id, items)
        return SaveResult(registro_id=id, is_update=True)

    def _resolve_arrival_date(self, malote_id: int) -> date | None:
        from rac.utils.date_calculator import resolve_arrival_from_malote
        malote = self._db.get_malote_by_id(malote_id)
        return resolve_arrival_from_malote(malote) if malote else None

    def _save_processes(
        self,
        registro_id: int,
        tipo: str,
        malote_id: int,
        waiting_docs: bool,
        process_months: list[tuple[int, int]],
        items: list[tuple[int, int, str]] | None = None,
    ) -> None:
        arrival_date = self._resolve_arrival_date(malote_id)
        returns = calculate_return_dates(
            tipo=tipo,
            arrival_date=arrival_date,
            process_groups=process_months,
            db=self._db,
            current_malote_id=malote_id,
            waiting_docs=waiting_docs,
        )
        processes_data = [
            (r.group_number, r.months_supply, r.expected_return_date.isoformat() if r.expected_return_date else None)
            for r in returns
        ]
        new_processes = self._db.set_processes(registro_id, processes_data)
        process_by_group = {p.group_number: p.id for p in new_processes}
        if items is None:
            items = [
                (i.item_id, i.process_group, i.cid)
                for i in self._db.get_items_by_registro(registro_id)
                if i.item_id is not None
            ]
        items_with_process: list[tuple[int, int, int | None, str]] = [
            (iid, pg, process_by_group.get(pg), cid) for iid, pg, cid in items
        ]
        self._db.set_registro_items_with_process(registro_id, items_with_process)

    def save(
        self,
        tipo: str,
        paciente_name: str,
        malote_id: int,
        items: list[tuple[int, int, str]],
        edit_id: int | None = None,
        waiting_docs: bool = False,
        paciente_id: int | None = None,
        process_months: list[tuple[int, int]] | None = None,
    ) -> SaveResult:
        """Save a registro. paciente_id takes priority if provided;
        otherwise paciente_name is used to find-or-create a patient."""
        if not tipo:
            raise ValidationError("Selecione um tipo")
        paciente_name = paciente_name.strip()
        if not paciente_name and paciente_id is None:
            raise ValidationError("Informe o nome do paciente")

        resolved_id = paciente_id
        if resolved_id is None:
            found = self._db.find_paciente_by_name(paciente_name)
            if found:
                resolved_id = found.id
            else:
                created = self._db.create_paciente(paciente_name)
                resolved_id = created.id

        if resolved_id is None:
            raise RuntimeError("Failed to resolve patient")

        if edit_id is not None:
            return self.update(
                edit_id, tipo, resolved_id, malote_id, items, waiting_docs, process_months
            )

        existing = self._db.find_registro(tipo, resolved_id, malote_id)
        if existing and existing.id is not None:
            return self.update(
                existing.id, tipo, resolved_id, malote_id, items, waiting_docs, process_months
            )

        try:
            new_reg = self._db.create_registro(
                tipo, resolved_id, malote_id, waiting_docs=waiting_docs
            )
        except sqlite3.IntegrityError:
            existing = self._db.find_registro(tipo, resolved_id, malote_id)
            if existing and existing.id is not None:
                return self.update(
                    existing.id, tipo, resolved_id, malote_id, items, waiting_docs, process_months
                )
            raise DuplicateRecordError(
                f"Duplicate: tipo={tipo}, paciente_id={resolved_id}, malote_id={malote_id}"
            )
        if new_reg.id is None:
            raise RuntimeError("Failed to create registro")
        if process_months is not None:
            self._save_processes(
                new_reg.id, tipo, malote_id, waiting_docs, process_months, items
            )
        else:
            self._db.set_registro_items(new_reg.id, items)
        return SaveResult(registro_id=new_reg.id, is_update=False)

    def delete(self, registro_id: int) -> None:
        if registro_id is None or registro_id <= 0:
            raise ValidationError("ID do registro é obrigatório")
        deleted = self._db.delete_registro(registro_id)
        if not deleted:
            raise ValidationError("Registro não encontrado")

    def load_for_edit(self, registro_id: int) -> EditContext | None:
        reg = self._db.get_registro_by_id(registro_id)
        if not reg:
            return None
        items = self._db.get_items_by_registro(registro_id)
        processes = self._db.get_processes_by_registro(registro_id)
        return EditContext(
            registro=reg,
            items=[
                (item.item_id, item.process_group, item.cid)
                for item in items
                if item.item_id is not None
            ],
            processes=[
                (p.group_number, p.months_supply)
                for p in processes
            ],
        )

    def load_for_context(
        self, tipo: str, paciente_id: int, malote_id: int | None
    ) -> ContextResult:
        existing = (
            self._db.find_registro(tipo, paciente_id, malote_id)
            if malote_id else None
        )
        if existing and existing.id is not None:
            items = self._db.get_items_by_registro(existing.id)
            processes = self._db.get_processes_by_registro(existing.id)
            return ContextResult(
                registro=existing,
                items=[
                    (item.item_id, item.process_group, item.cid)
                    for item in items
                    if item.item_id is not None
                ],
                processes=[
                    (p.group_number, p.months_supply)
                    for p in processes
                ],
                suggested_items=[],
            )
        usage = self._db.get_last_usage_by_paciente(paciente_id)
        cid_to_group: dict[str, int] = {}
        next_group = 1
        suggested: list[tuple[int, int, str]] = []
        for item_id, cid in usage:
            if cid not in cid_to_group:
                cid_to_group[cid] = next_group
                next_group += 1
            suggested.append((item_id, cid_to_group[cid], cid))
        return ContextResult(
            registro=None,
            items=[],
            processes=[],
            suggested_items=suggested,
        )

    def change_tipo(self, registro_id: int, new_tipo: str) -> None:
        reg = self._db.get_registro_by_id(registro_id)
        if not reg:
            raise ValidationError("Registro não encontrado")
        if reg.paciente_id is None or reg.malote_id is None:
            raise ValidationError("Registro inválido")
        items = self._db.get_items_by_registro(registro_id)
        item_tuples = [
            (i.item_id, i.process_group, i.cid) for i in items if i.item_id is not None
        ]
        processes = self._db.get_processes_by_registro(registro_id)
        process_months = [(p.group_number, p.months_supply) for p in processes]
        self.update(
            registro_id, new_tipo, reg.paciente_id, reg.malote_id,
            item_tuples, reg.waiting_docs, process_months,
        )

    def change_tipos(self, reg_ids: list[int], new_tipo: str) -> int:
        """Bulk ``change_tipo``: batches all updates into a single commit.

        Returns the count of registros skipped due to duplicates.
        """
        errors = 0
        with self._db.transaction():
            for rid in reg_ids:
                try:
                    self.change_tipo(rid, new_tipo)
                except DuplicateRecordError:
                    errors += 1
        return errors

    def move_to_malote(
        self, registro_ids: list[int], new_malote_id: int
    ) -> int:
        errors = 0
        with self._db.transaction():
            for rid in registro_ids:
                reg = self._db.get_registro_by_id(rid)
                if not reg or reg.paciente_id is None:
                    continue
                items = self._db.get_items_by_registro(rid)
                item_tuples = [
                    (i.item_id, i.process_group, i.cid) for i in items if i.item_id is not None
                ]
                processes = self._db.get_processes_by_registro(rid)
                process_months = [(p.group_number, p.months_supply) for p in processes]
                try:
                    self.update(
                        rid, reg.tipo, reg.paciente_id, new_malote_id,
                        item_tuples, reg.waiting_docs, process_months,
                    )
                except DuplicateRecordError:
                    errors += 1
        return errors

    def delete_with_snapshot(self, registro_id: int) -> DeleteSnapshot | None:
        reg = self._db.get_registro_by_id(registro_id)
        if not reg:
            return None
        if reg.paciente_id is None or reg.malote_id is None:
            return None
        items = self._db.get_items_by_registro(registro_id)
        processes = self._db.get_processes_by_registro(registro_id)
        snapshot = DeleteSnapshot(
            tipo=reg.tipo,
            paciente_id=reg.paciente_id,
            malote_id=reg.malote_id,
            waiting_docs=reg.waiting_docs,
            items=[(i.item_id, i.process_group, i.cid) for i in items if i.item_id is not None],
            process_months=[(p.group_number, p.months_supply) for p in processes],
        )
        self.delete(registro_id)
        return snapshot

    def restore_from_snapshot(self, snapshot: DeleteSnapshot) -> int:
        result = self.save(
            tipo=snapshot.tipo,
            paciente_name="",
            malote_id=snapshot.malote_id,
            items=snapshot.items,
            waiting_docs=snapshot.waiting_docs,
            paciente_id=snapshot.paciente_id,
            process_months=snapshot.process_months,
        )
        return result.registro_id
