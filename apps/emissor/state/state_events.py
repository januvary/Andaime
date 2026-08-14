"""State change event definitions — tipos de eventos e interface de observadores."""

from enum import Enum
from typing import Dict, Any
from dataclasses import dataclass


class StateEventType(Enum):
    """Tipos de eventos de mudança de estado"""

    PATIENT_SELECTED = "patient_selected"
    PATIENT_CLEARED = "patient_cleared"
    PATIENT_UPDATED = "patient_updated"
    PDF_GENERATED = "pdf_generated"

    # Process management events
    PROCESSO_COUNT_CHANGED = "processo_count_changed"

    # Tipo (revezado/municipal/insulina) changed
    TIPO_CHANGED = "tipo_changed"

    # Date calculation triggers
    DATE_RECALCULATION_NEEDED = "date_recalculation_needed"

    # Dirty tracking
    DIRTY_STATE_CHANGED = "dirty_state_changed"


@dataclass
class StateEvent:
    """Evento de mudança de estado: tipo + dicionário de dados."""

    event_type: StateEventType
    data: Dict[str, Any]


class StateObserver:
    """Interface para observadores de mudança de estado (registrados no
    StateManager para receber notificações)."""

    def on_state_changed(self, event: StateEvent) -> None:
        """Chamado quando o estado observado muda."""
        raise NotImplementedError(
            f"{self.__class__.__name__} deve implementar on_state_changed()"
        )
