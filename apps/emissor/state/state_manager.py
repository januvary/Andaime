"""Gerenciamento de estado centralizado da aplicação."""

import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from pathlib import Path
from threading import RLock

from .state_events import StateEvent, StateEventType, StateObserver
from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from emissor.database.models import Patient, PatientItem

if TYPE_CHECKING:
    from emissor.database import Patient

_PATIENT_WRITABLE_FIELDS = frozenset(
    {
        "nome",
        "processo_n",
        "extra_processos",
        "profissional_id",
        "matricula",
        "telefone",
        "tipo",
        "periodicidade",
        "receitas",
        "bloquear_balanco",
        "observacoes",
        "atendido_por",
        "itens",
    }
)


class StateManager:
    """Gerencia estado centralizado com notificações thread-safe."""

    def __init__(self) -> None:
        """Inicializa gerenciador de estado"""
        # Estado do paciente
        self._selected_patient: "Patient | None" = None

        # Configuração
        self._save_root_path: Optional[Path] = None
        self._print_copies: int = 1
        self._dark_mode: bool = True

        # Estado da UI
        self._last_generated_pdf: Optional[str] = None
        self._last_generated_pdf_patient_id: Optional[int] = None
        self._calculated_dates: Dict[str, Any] = {}

        # Options state (para cálculo de datas)
        self._periodicidade: str = ""
        self._receitas: List[Dict[str, str]] = []
        self._bloquear_balanco: bool = False

        # Observadores
        self._observers: List[StateObserver] = []

        # Lock para thread safety (usa RLock re-entrante para evitar deadlock)
        self._lock: RLock = RLock()

    # ========== Observer Pattern ==========

    def register_observer(self, observer: StateObserver) -> None:
        """Registra um observador de mudanças de estado."""
        with self._lock:
            if observer not in self._observers:
                self._observers.append(observer)
                ErrorHandler.log(
                    f"Observador registrado: {observer.__class__.__name__}",
                    level=ErrorLevel.DEBUG,
                    context=ErrorContext.UI,
                )

    def unregister_observer(self, observer: StateObserver) -> None:
        """Remove um observador."""
        with self._lock:
            if observer in self._observers:
                self._observers.remove(observer)

    def notify_observers(self, event: StateEvent) -> None:
        """Notifica todos os observadores sobre mudança de estado."""
        # Create a copy of observers list to avoid modification during iteration
        with self._lock:
            observers_to_notify = self._observers.copy()

        # Log errors immediately and continue notifying other observers
        for observer in observers_to_notify:
            try:
                observer.on_state_changed(event)
            except Exception as e:
                # Log immediately and continue
                ErrorHandler.log(
                    f"Observador {observer.__class__.__name__} falhou: {e}",
                    level=ErrorLevel.ERROR,
                    context=ErrorContext.UI,
                )

    def emit(self, event_type: StateEventType, **data: Any) -> None:
        """shorthand for notify_observers(StateEvent(...))"""
        self.notify_observers(StateEvent(event_type=event_type, data=data))

    # ========== Patient State ==========

    def get_selected_patient(self) -> Any:
        """Retorna o paciente selecionado (cópia rasa)."""
        with self._lock:
            return copy.copy(self._selected_patient) if self._selected_patient else None

    def set_selected_patient(self, patient_data: Any) -> None:
        """Define o paciente selecionado e notifica observadores."""
        if not patient_data:
            raise ValueError("patient_data não pode ser None ou vazio")

        if not isinstance(patient_data, Patient):
            patient_data = Patient.from_row(patient_data)

        with self._lock:
            self._selected_patient = copy.deepcopy(patient_data)

        self.emit(StateEventType.PATIENT_SELECTED, patient=patient_data)

        ErrorHandler.log(
            f"Paciente selecionado: {patient_data.nome}",
            level=ErrorLevel.INFO,
            context=ErrorContext.UI,
        )

    def clear_selected_patient(self) -> None:
        """Limpa o paciente selecionado (modo novo paciente)"""
        # Thread-safe state update
        with self._lock:
            self._selected_patient = None

        # Single notification call - error handling centralized
        self.emit(StateEventType.PATIENT_CLEARED)

        ErrorHandler.log(
            "Paciente selecionado limpo (modo novo paciente)",
            level=ErrorLevel.INFO,
            context=ErrorContext.UI,
        )

    def update_selected_patient(self, updates: Dict) -> None:
        """Atualiza dados do paciente selecionado."""
        normalized = updates.copy()
        if normalized.get("itens"):
            normalized["itens"] = [
                item if isinstance(item, PatientItem) else PatientItem.from_row(item)
                for item in normalized["itens"]
            ]

        with self._lock:
            if not self._selected_patient:
                raise ValueError("Nenhum paciente selecionado")
            for key, value in normalized.items():
                if key in _PATIENT_WRITABLE_FIELDS:
                    setattr(self._selected_patient, key, value)

        self.emit(StateEventType.PATIENT_UPDATED, updates=normalized)

    # ========== Configuration State ==========

    def get_save_root_path(self) -> Optional[Path]:
        """Retorna o caminho raiz para salvar arquivos."""
        with self._lock:
            return self._save_root_path

    def set_save_root_path(self, path: Path) -> None:
        """Define caminho raiz para salvar arquivos."""
        with self._lock:
            self._save_root_path = path

    def get_print_copies(self) -> int:
        """Retorna número de cópias para impressão."""
        with self._lock:
            return self._print_copies

    def set_print_copies(self, copies: int) -> None:
        """Define número de cópias (1 a 4)."""
        with self._lock:
            if copies < 1 or copies > 4:
                raise ValueError("print_copies deve estar entre 1 e 4")
            self._print_copies = copies

    def get_dark_mode(self) -> bool:
        """Retorna se dark mode está ativo."""
        with self._lock:
            return self._dark_mode

    def set_dark_mode(self, dark_mode: bool) -> None:
        """Define dark mode."""
        with self._lock:
            self._dark_mode = dark_mode

    # ========== PDF State ==========

    def get_last_generated_pdf(self) -> Optional[str]:
        """Retorna caminho do último PDF gerado (qualquer paciente)."""
        with self._lock:
            return self._last_generated_pdf

    def get_last_generated_pdf_for_patient(self, patient_id: int) -> Optional[str]:
        """Retorna o último PDF gerado apenas se pertencer ao paciente."""
        with self._lock:
            if (
                self._last_generated_pdf is not None
                and self._last_generated_pdf_patient_id == patient_id
            ):
                return self._last_generated_pdf
            return None

    def set_last_generated_pdf(
        self, pdf_path: str, patient_id: Optional[int] = None
    ) -> None:
        """Define o último PDF gerado, associado a um paciente."""
        # Thread-safe state update
        with self._lock:
            self._last_generated_pdf = pdf_path
            self._last_generated_pdf_patient_id = patient_id

        # Single notification call - error handling centralized
        self.emit(StateEventType.PDF_GENERATED, pdf_path=pdf_path)

    # ========== Options State (para Date Calculations) ==========

    def get_periodicidade(self) -> str:
        """Retorna a periodicidade atual."""
        with self._lock:
            return self._periodicidade

    def set_periodicidade(self, value: str) -> None:
        """Define periodicidade e notifica observadores."""
        # Thread-safe state update
        with self._lock:
            self._periodicidade = value

        # Single notification call - error handling centralized
        self.emit(StateEventType.DATE_RECALCULATION_NEEDED)

    def get_receitas(self) -> list[dict[str, str]]:
        """Retorna a lista ordenada de receitas (data + tipo)."""
        with self._lock:
            return [dict(r) for r in self._receitas]

    def set_receitas(self, receitas: List[Dict[str, str]]) -> None:
        """Define a lista de receitas e notifica observadores.

        Receitas são compactas (sem buracos); cada item tem "data" e "tipo".
        """
        normalized = []
        for r in receitas:
            data = (r.get("data") or "").strip()
            tipo = (r.get("tipo") or "").strip().lower()
            if data or tipo:
                normalized.append({"data": data, "tipo": tipo})

        # Thread-safe state update
        with self._lock:
            self._receitas = normalized

        self.emit(StateEventType.DATE_RECALCULATION_NEEDED)

    def get_bloquear_balanco(self) -> bool:
        """Retorna se o bloqueio de balanço está ativo."""
        with self._lock:
            return self._bloquear_balanco

    def set_bloquear_balanco(self, value: bool) -> None:
        """Define bloqueio de balanço e notifica observadores."""
        # Thread-safe state update
        with self._lock:
            self._bloquear_balanco = bool(value)

        self.emit(StateEventType.DATE_RECALCULATION_NEEDED)

    def update_date_field(self, field_name: str, value: Any) -> None:
        """Atualiza um campo de data (normaliza None para "") e notifica.

        Args:
            field_name: 'periodicidade'
            value: Valor (None vira "")
        """
        self.update_date_fields(**{field_name: value})

    def request_date_recalculation(self) -> None:
        """Solicita recálculo de datas sem alterar campos."""
        self.emit(StateEventType.DATE_RECALCULATION_NEEDED)

    def update_date_fields(self, **fields: Any) -> None:
        """Atualiza múltiplos campos de data com única notificação.

        Args:
            **fields: pares para periodicidade
        """
        valid_fields = {"periodicidade"}
        invalid = [f for f in fields.keys() if f not in valid_fields]
        if invalid:
            raise ValueError(
                f"Unknown date fields: {invalid}. Must be one of: periodicidade"
            )

        ErrorHandler.log(
            f"Batch update de {len(fields)} campos de data: {list(fields.keys())}",
            level=ErrorLevel.DEBUG,
            context=ErrorContext.STATE,
        )

        with self._lock:
            for field_name, value in fields.items():
                normalized_value = (
                    str(value) if value is not None and value != "" else ""
                )
                if field_name == "periodicidade":
                    self._periodicidade = normalized_value

        self.emit(StateEventType.DATE_RECALCULATION_NEEDED)

    # ========== Calculated Dates State ==========

    def calculate_dates(
        self,
        data_retirada_str: str,
        periodicidade_str: str,
        enable_distribution: bool = False,
        distribution_window_days: int = 3,
        retirada_count_fn: Any = None,
        bloquear_balanco: bool = False,
    ) -> Dict[str, Any]:
        """Calcula a próxima retirada e armazena no estado.

        Args:
            enable_distribution: habilita distribuição inteligente
            distribution_window_days: dias para trás na janela (1-7)
            retirada_count_fn: callable(start, end) → dict data→contagem
            bloquear_balanco: evita últimos 5 dias úteis do mês
        """
        from emissor.utils.date_utils import DateCalculator

        if not periodicidade_str:
            self.set_calculated_dates({})
            return {}

        result: Dict[str, Any] = {}

        proxima_result = DateCalculator.calculate_proxima_vez(
            data_retirada_str,
            periodicidade_str,
            enable_distribution=enable_distribution,
            distribution_window_days=distribution_window_days,
            retirada_count_fn=retirada_count_fn,
            bloquear_balanco=bloquear_balanco,
        )
        result.update(proxima_result)

        self.set_calculated_dates(result)
        return result

    def set_calculated_dates(self, dates: Dict[str, Any]) -> None:
        """Armazena datas calculadas."""
        with self._lock:
            self._calculated_dates = dates.copy()

    def get_calculated_dates(self) -> Dict[str, Any]:
        """Retorna cópia das datas calculadas."""
        with self._lock:
            return self._calculated_dates.copy()

    # ========== Convenience Methods ==========

    def has_selected_patient(self) -> bool:
        """Retorna True se há paciente selecionado."""
        with self._lock:
            return self._selected_patient is not None

    def get_patient_id(self) -> Optional[int]:
        """Retorna o ID do paciente selecionado ou None."""
        with self._lock:
            if not self._selected_patient:
                return None
            raw_id = self._selected_patient.id
            if isinstance(raw_id, int):
                return raw_id
            if isinstance(raw_id, str) and raw_id.isdigit():
                return int(raw_id)
            return None

    def get_patient_name(self) -> Optional[str]:
        """Retorna o nome do paciente selecionado ou None."""
        with self._lock:
            if not self._selected_patient:
                return None
            return self._selected_patient.nome
