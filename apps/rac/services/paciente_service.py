#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from rac.database.rac_database import RACDatabase
from rac.models import Paciente
from rac.services.exceptions import ValidationError


class PacienteService:
    def __init__(self, db: RACDatabase) -> None:
        self._db = db

    def create(self, name: str) -> Paciente:
        return self._db.create_paciente(name)

    def get(self, paciente_id: int) -> Paciente | None:
        return self._db.get_paciente_by_id(paciente_id)

    def find_by_name(self, name: str) -> Paciente | None:
        return self._db.find_paciente_by_name(name)

    def search(self, query: str, limit: int = 10) -> list[Paciente]:
        return self._db.search_pacientes(query, limit)

    def all(self) -> list[Paciente]:
        return self._db.get_all_pacientes()

    def all_with_last_registro(self) -> list[Paciente]:
        return self._db.get_all_pacientes_with_last_registro()

    def update(
        self, paciente_id: int, *, name: str | None = None
    ) -> None:
        paciente = self._db.get_paciente_by_id(paciente_id)
        if not paciente:
            raise ValidationError("Paciente não encontrado")
        new_name = name.strip() if name is not None else paciente.name
        if not new_name:
            raise ValidationError("Nome do paciente é obrigatório")
        self._db.update_paciente(paciente_id, new_name)

    def delete(self, paciente_id: int) -> bool:
        return self._db.delete_paciente(paciente_id)
