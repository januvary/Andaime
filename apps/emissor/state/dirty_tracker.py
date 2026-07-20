#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dirty Tracker — rastreia mudanças não salvas na aplicação."""

from __future__ import annotations

import re

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

from .state_events import StateEvent, StateEventType, StateObserver


class DirtyTracker:
    """
    Rastreia campos com mudanças não salvas. Cada campo é identificado por
    uma tupla como ("patient", "cpf") ou ("item", "123", "quantidade").
    """

    def __init__(self) -> None:
        self._unsaved_changes: set[tuple] = set()
        self._observers: list[StateObserver] = []
        self._originals: dict[tuple, str] = {}
        self._masked_fields: set[tuple] = set()
        self._last_notified_count: int = 0

    def add_observer(self, observer: StateObserver) -> None:
        """Registra observador para receber notificações de mudança."""
        self._observers.append(observer)

    def set_original(self, field_id: tuple, value: str, masked: bool = False) -> None:
        """Registra o valor original (limpo) de um campo, permitindo desmarcar
        campos que voltaram ao valor salvo. ``masked`` ignora máscara na
        comparação (telefone, CRM, processo)."""
        self._originals[field_id] = value or ""
        if masked:
            self._masked_fields.add(field_id)
        else:
            self._masked_fields.discard(field_id)

    def mark_dirty(
        self,
        field_id: tuple,
        is_dirty: bool = True,
        new_value: str | None = None,
    ) -> None:
        """Marca campo como sujo ou limpo. Se ``new_value`` é informado e há
        original registrado, só fica sujo se o valor realmente mudou."""
        if is_dirty:
            if new_value is not None and field_id in self._originals:
                if field_id in self._masked_fields:
                    changed = self.is_value_changed(
                        new_value, self._originals[field_id]
                    )
                else:
                    changed = new_value != self._originals[field_id]
                if changed:
                    self._unsaved_changes.add(field_id)
                else:
                    self._unsaved_changes.discard(field_id)
            else:
                self._unsaved_changes.add(field_id)
        else:
            self._unsaved_changes.discard(field_id)
        self._notify()

    def mark_clean(self) -> None:
        """Marca todos os campos como limpos, preservando os valores originais
        para futuras comparações após salvar."""
        self._unsaved_changes.clear()
        self._notify()

    def reset(self) -> None:
        """Limpa completamente o estado (troca de paciente, sem baseline)."""
        self._unsaved_changes.clear()
        self._originals.clear()
        self._masked_fields.clear()
        self._notify()

    @property
    def is_dirty(self) -> bool:
        """Retorna True se há mudanças não salvas."""
        return len(self._unsaved_changes) > 0

    @property
    def dirty_count(self) -> int:
        """Retorna quantidade de campos com mudanças não salvas."""
        return len(self._unsaved_changes)

    @staticmethod
    def strip_mask(value: str) -> str:
        """Remove caracteres não numéricos (comparação de valores mascarados)."""
        return re.sub(r"[^0-9]", "", value)

    def is_value_changed(self, new_value: str, original_value: str) -> bool:
        """Compara valores após remover máscaras; True se diferentes."""
        return self.strip_mask(new_value) != self.strip_mask(original_value)

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
