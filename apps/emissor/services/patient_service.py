#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patient Service — criação e atualização de pacientes."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from emissor.database.emissor_db import EmissorDatabase
from emissor.database.models import Patient
from emissor.services.exceptions import DuplicatePatientError, ValidationError
from emissor.utils.patient_fields_config import (
    get_all_patient_data_fields,
    get_field_config,
    is_multiple_instance_field,
)
from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel


@dataclass
class CreatePatientResult:
    """Resultado da criação de um novo paciente."""

    patient_id: int
    patient_name: str


@dataclass
class SavePatientResult:
    """Resultado do salvamento de dados do paciente."""

    patient_id: int
    patient_name: str
    is_new: bool


class PatientService:
    """Serviço de domínio para pacientes. Recebe dados + db, retorna
    resultados ou levanta exceções; nunca toca UI, StateManager ou seções."""

    def __init__(self, db: EmissorDatabase) -> None:
        self._db = db

    def create_patient(self, nome: str) -> CreatePatientResult:
        """Cria paciente (nome obrigatório, em maiúsculas). Levanta
        ValidationError se vazio ou DuplicatePatientError se já existir."""
        nome = nome.strip()
        if not nome:
            raise ValidationError("Nome do paciente é obrigatório")

        try:
            result = self._db.add_patient(nome)
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                raise DuplicatePatientError(nome) from e
            raise

        ErrorHandler.log(
            f"Novo paciente criado via serviço: {result['nome']} (ID: {result['id']})",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        return CreatePatientResult(
            patient_id=result["id"],
            patient_name=result["nome"],
        )

    def save_patient_data(
        self,
        patient_id: int,
        data: dict[str, Any],
        current_patient: Patient | None = None,
    ) -> SavePatientResult:
        """Salva dados combinados (pessoais + opções + itens), expandindo
        campos multi-instância e preenchendo vazios do paciente atual.
        Levanta ValidationError se ID inválido ou dados vazios."""
        if patient_id is None or patient_id <= 0:
            raise ValidationError("ID do paciente é obrigatório para salvar dados")

        data = data.copy()

        self._expand_multi_instance_fields(data, current_patient)

        data.pop("atendido_por", None)

        # Resolver profissional (nome + crm) para profissional_id mestre.
        prof_nome = data.pop("profissional_nome", None)
        prof_crm = data.pop("profissional_crm", None)
        if prof_nome:
            prof_id = self._db.upsert_profissional(prof_nome, prof_crm or "")
            data["profissional_id"] = prof_id
        elif "profissional_id" not in data:
            data["profissional_id"] = None

        if not data:
            raise ValidationError("Nenhum dado para salvar")

        self._db.update_patient(patient_id, data.copy())

        patient_name = data.get("nome", "")
        ErrorHandler.log(
            f"Dados salvos via serviço para paciente ID {patient_id}",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        return SavePatientResult(
            patient_id=patient_id,
            patient_name=patient_name,
            is_new=False,
        )

    def _expand_multi_instance_fields(
        self, data: dict[str, Any], current_patient: Patient | None
    ) -> None:
        """Expande campos multi-instância (ex.: processo_n → processo_2_n…)
        e preenche campos ausentes do paciente atual com string vazia para
        limpeza no banco."""
        fields_to_check = get_all_patient_data_fields()

        for field_name in fields_to_check.copy():
            if is_multiple_instance_field(field_name):
                config = get_field_config(field_name)
                max_instances = config.get("max_instances", 10) if config else 10
                base_name = (
                    field_name.rsplit("_n", 1)[0]
                    if field_name.endswith("_n")
                    else field_name
                )
                for i in range(2, max_instances + 1):
                    fields_to_check.append(f"{base_name}_{i}_n")

        fields_to_check.append("atendido_por")

        for field in fields_to_check:
            if (
                field not in data
                and current_patient is not None
                and field in current_patient
            ):
                data[field] = ""
