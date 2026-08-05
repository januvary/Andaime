"""
State Management Package
Gerenciamento centralizado de estado da aplicação
"""

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
