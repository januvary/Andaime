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
        """Retorna retornos agrupados por data_proxima_retirada. Status pendente/retirado conforme retirada posterior do mesmo paciente (regras derivadas: M.data_retirada > R.data_proxima_retirada OU R.data_retirada < M.data_retirada <= R.data_proxima_retirada com item em comum; usa M mais cedo). Caminhos PDF relativos à pasta de salvamento."""
        all_retiradas = self._db.get_all_retiradas()
        item_sets = self._db.get_retirada_item_sets(
            [r.id for r in all_retiradas if r.id is not None]
        )

        patient_retiradas: dict[int | None, list[Retirada]] = {}
        for retirada in all_retiradas:
            patient_retiradas.setdefault(retirada.patient_id, []).append(retirada)

        for retiradas in patient_retiradas.values():
            retiradas.sort(key=lambda r: r.data_retirada)

        date_map: dict[str, list[dict[str, Any]]] = {}
        for retirada in all_retiradas:
            status, data_retirada_real = self._resolve_retirada_status(
                retirada, patient_retiradas[retirada.patient_id], item_sets
            )
            patient_name = retirada.patient_name
            patient_tipo = retirada.tipo or ""
            data_retirada = retirada.data_retirada
            proxima_data = retirada.data_proxima_retirada

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

            date_map.setdefault(proxima_data, []).append(
                {
                    "nome": patient_name,
                    "pdf_path": pdf_path,
                    "status": status,
                    "data_retirada": data_retirada_real,
                    "retirada_pdf_path": (
                        f"{archive_folder}/{data_retirada_real}.pdf"
                        if status == "retirado" and data_retirada_real
                        else None
                    ),
                }
            )

        return date_map

    def _resolve_retirada_status(
        self,
        retirada: Retirada,
        ordered: list[Retirada],
        item_sets: Dict[int, set[str]],
    ) -> tuple[str, str | None]:
        """Resolve (status, data_retirada_real) para uma retirada, derivando
        sob demanda a condição de "retirado" sem usar coluna substituida."""
        own_items = item_sets.get(retirada.id or 0, set())
        for r in ordered:
            if r.data_retirada <= retirada.data_retirada:
                continue
            after = r.data_retirada > retirada.data_proxima_retirada
            in_window = r.data_retirada <= retirada.data_proxima_retirada
            shared = bool(own_items & item_sets.get(r.id or 0, set()))
            if after or (in_window and shared):
                return "retirado", r.data_retirada
        return "pendente", None

