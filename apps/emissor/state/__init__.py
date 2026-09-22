"""State package — gerenciamento centralizado de estado."""

from .dirty_tracker import DirtyTracker
from .state_events import StateEvent, StateEventType, StateObserver
from .state_manager import StateManager

__all__ = [
    "DirtyTracker",
    "StateEvent",
    "StateEventType",
    "StateObserver",
    "StateManager",
]
