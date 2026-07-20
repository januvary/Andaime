"""Orquestra o workflow de retirada: validar → gerar PDF → salvar."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from emissor.database.emissor_db import EmissorDatabase
from emissor.services.exceptions import RetiradaSaveError, ValidationError
from emissor.services.retirada_service import RetiradaService
from emissor.state.state_manager import StateManager


@dataclass(frozen=True)
class RetiradaRequest:
    """Dados coletados da UI para gerar uma retirada (stateless).

    ``data`` é a fonte única e completa dos campos do formulário (inclui
    chaves vazias); ``selected_patient`` é o registro salvo (fora de ``data``).
    ``data_retirada_for_pdf`` usa formato AAAA-MM-DD para o nome do arquivo e
    difere de ``data["datas"]["hoje"]`` (DD/MM/AAAA, para exibição/validação).
    """

    selected_patient: Any
    data: dict[str, Any]
    save_root: Path
    proxima_vez: date | None
    data_retirada_for_pdf: str
    ignorar_itens: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedRetirada:
    """Resultado de prepare(): PDF gerado e args prontos para commit()."""

    pdf_path: Path
    patient_id: int | None
    patient_name: str
    data_retirada_str: str
    proxima_vez: date | None
    items: list[Any]
    ignorar_itens: list[tuple[str, str]] = field(default_factory=list)


class RetiradaWorkflowService:
    """Orquestra o pipeline de retirada (prepare em worker thread, commit)."""

    def __init__(
        self,
        retirada_service: RetiradaService,
        state_manager: StateManager,
        config_manager: Any,
        db: EmissorDatabase,
    ) -> None:
        """Inicializa o serviço de workflow."""
        self._retirada_service = retirada_service
        self._state = state_manager
        self._config = config_manager
        self._db = db

    def ensure_dates_computed(self, data_retirada_str: str) -> None:
        """Pré-calcula ``proxima_vez`` se ainda não foi calculado (thread da UI)."""
        calculated = self._state.get_calculated_dates()
        proxima_vez = calculated.get("proxima_vez")

        periodicidade = self._state.get_periodicidade()
        if proxima_vez is not None or not periodicidade:
            return

        config = self._config.get_all()
        self._state.calculate_dates(
            data_retirada_str=data_retirada_str,
            periodicidade_str=periodicidade,
            ultima_receita_str=self._state.get_ultima_receita(),
            tipo_receita=self._state.get_tipo_receita(),
            enable_distribution=config.distribute_retiradas,
            distribution_window_days=config.distribution_window_days,
            retirada_count_fn=self._db.count_retiradas_by_proxima_date,
        )

    def prepare(self, request: RetiradaRequest, pdf_generator: Any) -> PreparedRetirada:
        """Valida e gera o PDF no disco — sem escrever no banco (stateless)."""
        # 1. Validar campos obrigatórios
        self._retirada_service.validate_for_pdf(
            request.selected_patient, request.data
        )

        # 2. Resolver caminho + gerar PDF
        path_result = self._retirada_service.resolve_pdf_path(
            patient_name=request.data["patient_name"],
            patient_tipo=request.data.get("tipo", ""),
            date_str=request.data_retirada_for_pdf,
            save_root=request.save_root,
        )
        self._retirada_service.set_pdf_generator(pdf_generator)
        pdf_path = self._retirada_service.generate_pdf(
            request.data, path_result.pdf_path
        )

        return PreparedRetirada(
            pdf_path=pdf_path,
            patient_id=request.data.get("patient_id"),
            patient_name=request.data["patient_name"],
            data_retirada_str=request.data.get("datas", {}).get("hoje", ""),
            proxima_vez=request.proxima_vez,
            items=request.data.get("itens", []),
            ignorar_itens=request.ignorar_itens,
        )

    def commit(self, prepared: PreparedRetirada) -> int:
        """Persiste a retirada no banco; remove PDF órfão em caso de falha."""
        if prepared.patient_id is None:
            raise ValidationError("patient_id ausente — paciente não selecionado")
        try:
            result = self._retirada_service.save_retirada(
                patient_id=prepared.patient_id,
                patient_name=prepared.patient_name,
                data_retirada_str=prepared.data_retirada_str,
                proxima_vez=prepared.proxima_vez,
                items=prepared.items,
                ignorar_itens=prepared.ignorar_itens,
            )
        except (ValidationError, RetiradaSaveError, OSError):
            with suppress(OSError):
                Path(prepared.pdf_path).unlink(missing_ok=True)
            raise
        return result.retirada_id
