#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RAC State Manager
Centralized state management with observer pattern
"""

from __future__ import annotations

import threading
import copy
from typing import Optional

from rac.models import Malote


class RACStateManager:
    def __init__(self) -> None:
        self._active_malote: Optional[Malote] = None
        self._current_tipo: str = ""
        self._stay_on_page: bool = False
        self._lock = threading.RLock()

    # ========== MALOTE ==========

    def get_active_malote(self) -> Optional[Malote]:
        with self._lock:
            return copy.deepcopy(self._active_malote) if self._active_malote else None

    def set_active_malote(self, malote: Optional[Malote]) -> None:
        with self._lock:
            self._active_malote = copy.deepcopy(malote) if malote else None

    def has_active_malote(self) -> bool:
        with self._lock:
            return self._active_malote is not None

    # ========== TIPO ==========

    def get_current_tipo(self) -> str:
        with self._lock:
            return self._current_tipo

    def set_current_tipo(self, tipo: str) -> None:
        with self._lock:
            self._current_tipo = tipo

    # ========== CONFIG ==========

    def get_stay_on_page(self) -> bool:
        with self._lock:
            return self._stay_on_page

    def set_stay_on_page(self, value: bool) -> None:
        with self._lock:
            self._stay_on_page = value
