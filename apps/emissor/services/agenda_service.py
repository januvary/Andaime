#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agenda Service — camada de leitura para o calendário de retornos.

Espelha a lógica do antigo AgendaDatabase (standalone/agenda.py), sem UI e
sem instância global de app: recebe banco e pasta de arquivamento por injeção,
sendo reutilizável entre Tk, Qt e testes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from emissor.database.emissor_db import EmissorDatabase
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
        """Retorna retornos agrupados por data_proxima_retirada. O status é
        "pendente"/"retirado" conforme existência de retirada posterior do
        mesmo paciente; caminhos de PDF relativos à pasta de salvamento."""
        all_retiradas = self._db.get_all_retiradas()

        patient_retiradas: dict[int | None, list[Any]] = {}
        for retirada in all_retiradas:
            pid = retirada.patient_id
            patient_retiradas.setdefault(pid, []).append(retirada)

        for retiradas in patient_retiradas.values():
            retiradas.sort(key=lambda r: r.data_retirada)

        date_map: dict[str, list[dict[str, Any]]] = {}
        for retirada in all_retiradas:
            proxima_data = retirada.data_proxima_retirada
            patient_id = retirada.patient_id
            patient_name = retirada.patient_name
            data_retirada = retirada.data_retirada
            patient_tipo = retirada.tipo or ""

            status = "pendente"
            data_retirada_real = None
            for r in patient_retiradas[patient_id]:
                if r.data_retirada > proxima_data:
                    status = "retirado"
                    data_retirada_real = r.data_retirada
                    break

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
