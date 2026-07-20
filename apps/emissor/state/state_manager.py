"""Gerenciamento de estado centralizado da aplicação."""

import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast
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
        "ultima_receita",
        "tipo_receita",
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
        self._search_results: List[Dict[str, Any]] = []

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
        self._ultima_receita: str = ""
        self._tipo_receita: str = ""

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

    def _notify_observers(self, event: StateEvent) -> None:
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

    # ========== Public Event Notification Methods ==========

    def notify_processo_count_changed(self, count: int) -> None:
        """Notifica observadores sobre mudança na contagem de processos."""
        # Single notification call - error handling centralized
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.PROCESSO_COUNT_CHANGED, data={"count": count}
            )
        )

    def notify_tipo_changed(self, tipo: str) -> None:
        """Notifica observadores sobre mudança no tipo do paciente."""
        self._notify_observers(
            StateEvent(StateEventType.TIPO_CHANGED, data={"tipo": tipo})
        )

    # ========== Patient State ==========

    def get_selected_patient(self) -> Any:
        """Retorna o paciente selecionado (cópia rasa)."""
        with self._lock:
            return (
                copy.copy(self._selected_patient)
                if self._selected_patient
                else None
            )

    def set_selected_patient(self, patient_data: Any) -> None:
        """Define o paciente selecionado e notifica observadores."""
        if not patient_data:
            raise ValueError("patient_data não pode ser None ou vazio")

        if not isinstance(patient_data, Patient):
            patient_data = Patient.from_row(patient_data)

        with self._lock:
            self._selected_patient = copy.deepcopy(patient_data)

        self._notify_observers(
            StateEvent(
                event_type=StateEventType.PATIENT_SELECTED,
                data={"patient": patient_data, "batch_mode": True},
            )
        )

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
        self._notify_observers(
            StateEvent(event_type=StateEventType.PATIENT_CLEARED, data={})
        )

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

        self._notify_observers(
            StateEvent(
                event_type=StateEventType.PATIENT_UPDATED, data={"updates": normalized}
            )
        )

    # ========== Search State ==========

    def get_search_results(self) -> List[Dict[str, Any]]:
        """Retorna resultados da busca atual (cópia)."""
        with self._lock:
            # Return a shallow copy to avoid external modifications
            return self._search_results.copy()

    def set_search_results(self, results: List[Dict[str, Any]]) -> None:
        """Define resultados da busca e notifica observadores."""
        with self._lock:
            self._search_results = results.copy()

        self._notify_observers(
            StateEvent(
                event_type=StateEventType.SEARCH_RESULTS_UPDATED,
                data={"results": results, "count": len(results)},
            )
        )

    # ========== Configuration State ==========

    def get_save_root_path(self) -> Optional[Path]:
        """Retorna o caminho raiz para salvar arquivos."""
        with self._lock:
            return self._save_root_path

    def set_save_root_path(self, path: Path) -> None:
        """Define caminho raiz para salvar arquivos."""
        # Thread-safe state update
        with self._lock:
            self._save_root_path = path

        # Single notification call - error handling centralized
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.CONFIG_CHANGED,
                data={"key": "save_location", "value": str(path)},
            )
        )

    def get_print_copies(self) -> int:
        """Retorna número de cópias para impressão."""
        with self._lock:
            return self._print_copies

    def set_print_copies(self, copies: int) -> None:
        """Define número de cópias (1 a 4)."""
        # Thread-safe state update
        with self._lock:
            if copies < 1 or copies > 4:
                raise ValueError("print_copies deve estar entre 1 e 4")
            self._print_copies = copies

        # Single notification call - error handling centralized
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.CONFIG_CHANGED,
                data={"key": "print_copies", "value": copies},
            )
        )

    def get_dark_mode(self) -> bool:
        """Retorna se dark mode está ativo."""
        with self._lock:
            return self._dark_mode

    def set_dark_mode(self, dark_mode: bool) -> None:
        """Define dark mode."""
        # Thread-safe state update
        with self._lock:
            self._dark_mode = dark_mode

        # Single notification call - error handling centralized
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.CONFIG_CHANGED,
                data={"key": "dark_mode", "value": dark_mode},
            )
        )

    # ========== PDF State ==========

    def get_last_generated_pdf(self) -> Optional[str]:
        """Retorna caminho do último PDF gerado (qualquer paciente)."""
        with self._lock:
            return self._last_generated_pdf

    def get_last_generated_pdf_for_patient(
        self, patient_id: int
    ) -> Optional[str]:
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
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.PDF_GENERATED, data={"pdf_path": pdf_path}
            )
        )

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
        self._notify_observers(
            StateEvent(event_type=StateEventType.DATE_RECALCULATION_NEEDED, data={})
        )

    def get_ultima_receita(self) -> str:
        """Retorna a última receita atual."""
        with self._lock:
            return self._ultima_receita

    def set_ultima_receita(self, value: str) -> None:
        """Define última receita e notifica observadores."""
        # Thread-safe state update
        with self._lock:
            self._ultima_receita = value

        # Single notification call - error handling centralized
        self._notify_observers(
            StateEvent(event_type=StateEventType.DATE_RECALCULATION_NEEDED, data={})
        )

    def get_tipo_receita(self) -> str:
        """Retorna o tipo de receita atual."""
        with self._lock:
            return self._tipo_receita

    def set_tipo_receita(self, value: str) -> None:
        """Define tipo de receita e notifica observadores."""
        # Thread-safe state update
        with self._lock:
            self._tipo_receita = value

        # Single notification call - error handling centralized
        self._notify_observers(
            StateEvent(event_type=StateEventType.DATE_RECALCULATION_NEEDED, data={})
        )

    def update_date_field(
        self, field_name: str, value: Any, calculation_mode: str = "full"
    ) -> None:
        """Atualiza um campo de data (normaliza None para "") e notifica.

        Args:
            field_name: 'periodicidade', 'ultima_receita' ou 'tipo_receita'
            value: Valor (None vira "")
            calculation_mode: 'full', 'proxima_vez_only' ou 'validade_only'
        """
        self.update_date_fields(
            _calculation_mode=calculation_mode, **{field_name: value}
        )

    def request_date_recalculation(self, calculation_mode: str = "full") -> None:
        """Solicita recálculo de datas sem alterar campos.

        Args:
            calculation_mode: 'full', 'proxima_vez_only' ou 'validade_only'
        """
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.DATE_RECALCULATION_NEEDED,
                data={"calculation_mode": calculation_mode},
            )
        )

    def update_date_fields(
        self, _calculation_mode: str = "full", **fields: Any
    ) -> None:
        """Atualiza múltiplos campos de data com única notificação.

        Args:
            _calculation_mode: 'full', 'proxima_vez_only' ou 'validade_only'
            **fields: pares para periodicidade, ultima_receita, tipo_receita
        """
        valid_fields = {"periodicidade", "ultima_receita", "tipo_receita"}
        invalid = [f for f in fields.keys() if f not in valid_fields]
        if invalid:
            raise ValueError(
                f"Unknown date fields: {invalid}. "
                f"Must be one of: periodicidade, ultima_receita, tipo_receita"
            )

        # Log batch update operation
        ErrorHandler.log(
            f"Batch update de {len(fields)} campos de data: {list(fields.keys())}",
            level=ErrorLevel.DEBUG,
            context=ErrorContext.STATE,
        )

        # Batch update state (single lock acquisition)
        with self._lock:
            for field_name, value in fields.items():
                normalized_value = (
                    str(value) if value is not None and value != "" else ""
                )
                if field_name == "periodicidade":
                    self._periodicidade = normalized_value
                elif field_name == "ultima_receita":
                    self._ultima_receita = normalized_value
                elif field_name == "tipo_receita":
                    self._tipo_receita = normalized_value

        # Log notification emission
        ErrorHandler.log(
            f"Emitindo único notification DATE_RECALCULATION_NEEDED para "
            f"{len(fields)} campos (mode={_calculation_mode})",
            level=ErrorLevel.DEBUG,
            context=ErrorContext.STATE,
        )

        # Single notification for all fields, carrying the calculation mode
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.DATE_RECALCULATION_NEEDED,
                data={"calculation_mode": _calculation_mode},
            )
        )

    # ========== Calculated Dates State ==========

    def calculate_dates(
        self,
        data_retirada_str: str,
        periodicidade_str: str,
        ultima_receita_str: str,
        tipo_receita: str,
        calculation_mode: str = "full",
        enable_distribution: bool = False,
        distribution_window_days: int = 3,
        retirada_count_fn: Any = None,
    ) -> Dict[str, Any]:
        """Calcula datas (próxima vez e validade) e armazena no estado.

        Args:
            calculation_mode: 'full', 'proxima_vez_only' ou 'validade_only'
            enable_distribution: habilita distribuição inteligente
            distribution_window_days: janela em dias
            retirada_count_fn: callable para contar retiradas por data
        """
        from emissor.utils.date_utils import DateCalculator

        if not periodicidade_str and not ultima_receita_str:
            self.set_calculated_dates({})
            return {}

        result: Dict[str, Any] = {}

        if calculation_mode in ("full", "proxima_vez_only"):
            proxima_result = DateCalculator.calculate_proxima_vez(
                data_retirada_str,
                periodicidade_str,
                enable_distribution=enable_distribution,
                distribution_window_days=distribution_window_days,
                retirada_count_fn=retirada_count_fn,
            )
            result.update(proxima_result)

        if calculation_mode in ("full", "validade_only"):
            validade_result = DateCalculator.calculate_validade_receita(
                ultima_receita_str, tipo_receita
            )
            result.update(validade_result)

        self.set_calculated_dates(result)
        return result

    def set_calculated_dates(self, dates: Dict[str, Any]) -> None:
        """Armazena datas calculadas e emite RETIRADA_DATE_CALCULATED."""
        # Thread-safe state update
        with self._lock:
            self._calculated_dates = dates.copy()

        # Single notification call - error handling centralized
        self._notify_observers(
            StateEvent(
                event_type=StateEventType.RETIRADA_DATE_CALCULATED,
                data={"dates": dates},
            )
        )

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
            return cast(int, self._selected_patient.id)

    def get_patient_name(self) -> Optional[str]:
        """Retorna o nome do paciente selecionado ou None."""
        with self._lock:
            if not self._selected_patient:
                return None
            return self._selected_patient.nome
