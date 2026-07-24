#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dirty Tracker — rastreia mudanças não salvas via diff de payload."""

from __future__ import annotations

from typing import Any

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

from .state_events import StateEvent, StateEventType, StateObserver


def _snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Copia o payload normalizando valores (None → "", listas de dicts
    copiadas) para que mutações posteriores não alterem o baseline."""
    snap: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, list):
            snap[key] = [dict(row) for row in value]
        else:
            snap[key] = "" if value is None else str(value)
    return snap


def _diff_rows(key: str, base_rows: list, curr_rows: list) -> set[str]:
    """Diff por linha+campo entre duas listas de dicts."""
    dirty: set[str] = set()
    for i in range(max(len(base_rows), len(curr_rows))):
        base_row = base_rows[i] if i < len(base_rows) else {}
        curr_row = curr_rows[i] if i < len(curr_rows) else {}
        for field in base_row.keys() | curr_row.keys():
            base_val = base_row.get(field, "")
            curr_val = curr_row.get(field, "")
            base_str = "" if base_val is None else str(base_val)
            curr_str = "" if curr_val is None else str(curr_val)
            if base_str != curr_str:
                dirty.add(f"{key}[{i}].{field}")
    return dirty


class DirtyTracker:
    """
    Rastreia mudanças não salvas comparando o payload atual (o mesmo dict
    que seria persistido) com o baseline registrado na carga/salvamento.

    Campos escalares são comparados por chave; campos lista (ex.: itens)
    são comparados por linha+campo, gerando chaves como "itens[0].dias".
    """

    def __init__(self) -> None:
        self._baseline: dict[str, Any] = {}
        self._dirty_keys: set[str] = set()
        self._observers: list[StateObserver] = []
        self._last_notified_count: int = 0

    def add_observer(self, observer: StateObserver) -> None:
        """Registra observador para receber notificações de mudança."""
        self._observers.append(observer)

    def set_baseline(self, payload: dict[str, Any]) -> None:
        """Registra o estado limpo (após carga ou salvamento)."""
        self._baseline = _snapshot(payload)
        self._dirty_keys.clear()
        self._notify()

    def update(self, payload: dict[str, Any]) -> None:
        """Recomputa o estado dirty comparando o payload ao baseline."""
        self._dirty_keys = self._diff(self._baseline, _snapshot(payload))
        self._notify()

    def reset(self) -> None:
        """Limpa completamente o estado (troca de paciente, sem baseline)."""
        self._baseline = {}
        self._dirty_keys.clear()
        self._notify()

    @property
    def is_dirty(self) -> bool:
        """Retorna True se há mudanças não salvas."""
        return len(self._dirty_keys) > 0

    @property
    def dirty_count(self) -> int:
        """Retorna quantidade de campos com mudanças não salvas."""
        return len(self._dirty_keys)

    @property
    def dirty_keys(self) -> set[str]:
        """Retorna as chaves sujas (escalares ou "lista[linha].campo")."""
        return set(self._dirty_keys)

    @staticmethod
    def _diff(baseline: dict[str, Any], current: dict[str, Any]) -> set[str]:
        dirty: set[str] = set()
        for key in baseline.keys() | current.keys():
            base_val = baseline.get(key, "")
            curr_val = current.get(key, "")
            if isinstance(base_val, list) or isinstance(curr_val, list):
                base_rows = base_val if isinstance(base_val, list) else []
                curr_rows = curr_val if isinstance(curr_val, list) else []
                dirty |= _diff_rows(key, base_rows, curr_rows)
            elif str(base_val) != str(curr_val):
                dirty.add(key)
        return dirty

    def _notify(self) -> None:
        """Notifica observadores sobre mudança no estado dirty."""
        count = self.dirty_count
        if count == self._last_notified_count:
            return
        self._last_notified_count = count
        event = StateEvent(
            event_type=StateEventType.DIRTY_STATE_CHANGED,
            data={"dirty_count": count},
        )
        for observer in self._observers:
            try:
                observer.on_state_changed(event)
            except Exception as e:
                ErrorHandler.log(
                    f"Erro ao notificar observador dirty: {e}",
                    level=ErrorLevel.ERROR,
                    context=ErrorContext.UI,
                )
