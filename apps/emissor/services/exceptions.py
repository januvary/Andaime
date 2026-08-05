#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Exceções de Domínio
Hierarquia de exceções específicas do Emissor.
"""


class EmissorError(Exception):
    """Exceção base para todas as erros de domínio do Emissor."""

    pass


class ValidationError(EmissorError):
    """
    Erro de validação de dados.

    Levantado quando campos obrigatórios estão faltando ou inválidos.
    """

    pass


class DuplicatePatientError(EmissorError):
    """
    Paciente duplicado.

    Levantado ao tentar criar paciente com nome já existente.
    """

    def __init__(self, nome: str) -> None:
        self.nome = nome
        super().__init__(f"Paciente já existe: {nome}")


class PDFGenerationError(EmissorError):
    """Erro durante geração de PDF."""

    pass


class RetiradaSaveError(EmissorError):
    """Erro ao salvar retirada no banco de dados."""

    pass
