#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lógica de negócio para validação, PDF e salvamento de retiradas."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from emissor.database.emissor_db import EmissorDatabase
from emissor.services.exceptions import (
    PDFGenerationError,
    RetiradaSaveError,
    ValidationError,
)
from andaime.dates import parse_date
from emissor.utils.paths import resolve_archive_dir
from emissor.utils.security import sanitize_filename
from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel


@dataclass
class PDFPathResult:
    """Resultado da resolução de caminho de PDF."""

    pdf_path: Path
    archive_dir: Path


@dataclass
class SaveRetiradaResult:
    """Resultado do salvamento de retirada."""

    retirada_id: int


class RetiradaService:
    """Serviço de domínio para operações com retiradas (sem UI/state)."""

    def __init__(self, db: EmissorDatabase, pdf_generator: Any = None) -> None:
        self._db = db
        self._pdf_generator = pdf_generator

    def set_pdf_generator(self, pdf_generator: Any) -> None:
        """Define o gerador de PDF (lazy-load)."""
        self._pdf_generator = pdf_generator

    def validate_for_pdf(self, selected_patient: Any, data: dict[str, Any]) -> None:
        """Valida campos obrigatórios para geração de PDF.

        Lê os campos do formulário diretamente de ``data`` (fonte única,
        completa e não-perdida), evitando encadeamento de parâmetros.
        """
        from emissor.utils.validators import PatientDataValidator

        is_valid, error_msg = PatientDataValidator.validate_for_pdf_generation(
            selected_patient=selected_patient,
            processo_n=(data.get("processos") or [""])[0] or "",
            item_rows=data.get("itens", []),
            periodicidade=data.get("periodicidade", ""),
            data_retirada_str=data.get("datas", {}).get("hoje", ""),
            tipo=data.get("tipo", ""),
        )
        if not is_valid:
            raise ValidationError(error_msg)

    def resolve_pdf_path(
        self,
        patient_name: str,
        patient_tipo: str,
        date_str: str,
        save_root: Path,
    ) -> PDFPathResult:
        """Resolve o caminho completo do PDF (sanitiza nome, cria pasta)."""
        if save_root is None:
            raise ValidationError(
                "Diretório de salvamento não configurado. "
                "Abra Configurações e defina um local de salvamento."
            )

        safe_patient_name = sanitize_filename(patient_name)

        archive_dir = resolve_archive_dir(
            save_root,
            patient_tipo,
            safe_patient_name,
            create=True,
        )
        pdf_path = archive_dir / f"{date_str}.pdf"

        return PDFPathResult(pdf_path=pdf_path, archive_dir=archive_dir)

    def generate_pdf(self, data: dict[str, Any], pdf_path: Path) -> Path:
        """Gera o PDF no disco e retorna o caminho."""
        if self._pdf_generator is None:
            raise PDFGenerationError("Gerador de PDF não configurado")

        success = self._pdf_generator.generate(data, str(pdf_path))
        if not success:
            raise PDFGenerationError(f"Falha ao gerar PDF: {pdf_path.name}")

        return pdf_path

    def save_retirada(
        self,
        patient_id: int,
        patient_name: str,
        data_retirada_str: str,
        proxima_vez: date | None,
        items: list[dict[str, str]],
        ignorar_itens: list[tuple[str, str]] | None = None,
    ) -> SaveRetiradaResult:
        """Salva a retirada no banco de dados."""
        data_retirada = parse_date(data_retirada_str)
        if not data_retirada:
            raise ValidationError(f"Data de retirada inválida: {data_retirada_str}")

        if not proxima_vez:
            raise ValidationError(
                "Data próxima vez não calculada. "
                "Verifique se a periodicidade está definida."
            )

        data_retirada_db = data_retirada.strftime("%Y-%m-%d")
        data_proxima_retirada = proxima_vez.strftime("%Y-%m-%d")

        items_list = [
            {
                "item_id": item.get("item_id", ""),
                "descricao": item.get("descricao", ""),
                "unidade": item.get("unidade", ""),
                "quantidade": item.get("quantidade", ""),
                "dias": item.get("dias", ""),
            }
            for item in items
        ]

        retirada_id = self._db.save_retirada(
            patient_id=patient_id,
            patient_name=patient_name,
            data_retirada=data_retirada_db,
            data_proxima_retirada=data_proxima_retirada,
            items=items_list,
            ignorar_itens=ignorar_itens,
        )

        if not retirada_id:
            raise RetiradaSaveError("Falha ao salvar retirada no banco de dados")

        ErrorHandler.log(
            f"Retirada salva via serviço: ID {retirada_id}",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )

        return SaveRetiradaResult(retirada_id=retirada_id)
