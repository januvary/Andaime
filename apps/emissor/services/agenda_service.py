#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agenda Service — leitura de calendário de retornos (espelha AgendaDatabase; recebe db/pasta por injeção, reutilizável Tk/Qt/testes)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from emissor.database.emissor_db import EmissorDatabase
from emissor.database.models import Retirada
from emissor.utils.paths import RECIBOS_PARENT_FOLDER, resolve_archive_dir
from emissor.utils.security import sanitize_filename


class AgendaService:
    """Serviço de leitura para o calendário de retornos."""

    def __init__(
        self,
        db: EmissorDatabase,
        save_root: Path | None = None,
    ) -> None:
        self._db = db
        self._save_root = Path(save_root) if save_root is not None else None

    def get_appointments_by_date(self) -> dict[str, list[dict[str, Any]]]:
        """Retorna retornos agrupados por data_proxima_retirada, com status pendente/retirado derivado da regra de itens compartilhados entre retiradas do mesmo paciente."""
        all_retiradas = self._db.get_all_retiradas()
        item_sets = self._db.get_retirada_item_sets(
            [r.id for r in all_retiradas if r.id is not None]
        )
        patient_groups = self._group_by_patient(all_retiradas)
        return self._build_date_map(all_retiradas, patient_groups, item_sets)

    def _group_by_patient(
        self, retiradas: list[Retirada]
    ) -> dict[int | None, list[Retirada]]:
        groups: dict[int | None, list[Retirada]] = {}
        for r in retiradas:
            groups.setdefault(r.patient_id, []).append(r)
        for group in groups.values():
            group.sort(key=lambda r: r.data_retirada)
        return groups

    def _build_date_map(
        self,
        all_retiradas: list[Retirada],
        patient_groups: dict[int | None, list[Retirada]],
        item_sets: Dict[int, set[str]],
    ) -> dict[str, list[dict[str, Any]]]:
        status_lookup: dict[int, dict[int, tuple[str, str | None]]] = {}
        for patient_id, ordered in patient_groups.items():
            status_lookup[patient_id] = self._resolve_statuses_for_patient(
                ordered, item_sets
            )

        date_map: dict[str, list[dict[str, Any]]] = {}
        for retirada in all_retiradas:
            status, data_retirada_real = status_lookup[
                retirada.patient_id
            ][retirada.id or 0]
            entry = self._build_date_entry(
                retirada, status, data_retirada_real
            )
            date_map.setdefault(retirada.data_proxima_retirada, []).append(
                entry
            )
        return date_map

    def get_patient_retiradas(self, patient_id: int) -> list[dict[str, Any]]:
        """Retorna todas as retiradas de um paciente com status e caminho PDF."""
        retiradas = self._db.get_retiradas_by_patient(patient_id)
        if not retiradas:
            return []
        item_sets = self._db.get_retirada_item_sets(
            [r.id for r in retiradas if r.id is not None]
        )
        sorted_retiradas = sorted(retiradas, key=lambda r: r.data_retirada)
        patient_groups = {patient_id: sorted_retiradas}
        statuses = self._resolve_statuses_for_patient(
            sorted_retiradas, item_sets
        )

        result = []
        for r in retiradas:
            status, data_retirada_real = statuses[r.id or 0]
            patient_tipo = r.tipo or ""
            safe_patient_name = sanitize_filename(r.patient_name)
            if self._save_root is None:
                archive_folder = RECIBOS_PARENT_FOLDER
            else:
                archive_dir = resolve_archive_dir(
                    self._save_root,
                    patient_tipo,
                    safe_patient_name,
                    create=False,
                )
                archive_folder = str(archive_dir.relative_to(self._save_root))
            pdf_path = f"{archive_folder}/{r.data_retirada}.pdf"
            result.append(
                {
                    "data_retirada": r.data_retirada,
                    "data_proxima_retirada": r.data_proxima_retirada,
                    "status": status,
                    "data_retirada_real": data_retirada_real,
                    "pdf_path": pdf_path,
                    "retirada_pdf_path": (
                        f"{archive_folder}/{data_retirada_real}.pdf"
                        if status == "retirado" and data_retirada_real
                        else None
                    ),
                    "retirada_id": r.id,
                    "patient_name": r.patient_name,
                }
            )
        return result

    def _build_date_entry(
        self,
        retirada: Retirada,
        status: str,
        data_retirada_real: str | None,
    ) -> dict[str, Any]:
        patient_name = retirada.patient_name
        patient_tipo = retirada.tipo or ""
        data_retirada = retirada.data_retirada
        safe_patient_name = sanitize_filename(patient_name)

        if self._save_root is None:
            archive_folder = RECIBOS_PARENT_FOLDER
        else:
            archive_dir = resolve_archive_dir(
                self._save_root,
                patient_tipo,
                safe_patient_name,
                create=False,
            )
            archive_folder = str(archive_dir.relative_to(self._save_root))

        pdf_path = f"{archive_folder}/{data_retirada}.pdf"

        return {
            "nome": patient_name,
            "pdf_path": pdf_path,
            "status": status,
            "data_retirada": data_retirada_real,
            "patient_id": retirada.patient_id,
            "retirada_id": retirada.id,
            "retirada_pdf_path": (
                f"{archive_folder}/{data_retirada_real}.pdf"
                if status == "retirado" and data_retirada_real
                else None
            ),
        }

    def _resolve_statuses_for_patient(
        self, ordered: list[Retirada], item_sets: Dict[int, set[str]]
    ) -> dict[int, tuple[str, str | None]]:
        """Pre-compute (status, data_retirada_real) for all retiradas of a patient in a single pass."""
        results: dict[int, tuple[str, str | None]] = {}
        for i, retirada in enumerate(ordered):
            own_items = item_sets.get(retirada.id or 0, set())
            status, data_retirada_real = "pendente", None
            for r in ordered[i + 1 :]:
                if r.data_retirada > retirada.data_proxima_retirada:
                    status, data_retirada_real = "retirado", r.data_retirada
                    break
                shared = bool(
                    own_items & item_sets.get(r.id or 0, set())
                )
                if shared:
                    status, data_retirada_real = "retirado", r.data_retirada
                    break
            results[retirada.id or 0] = (status, data_retirada_real)
        return results

