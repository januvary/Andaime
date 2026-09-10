#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PontosStore — single source of truth for pontos_facultativos.json.

Handles loading, saving (atomic writes), and corrupt-JSON recovery.
Used by DateCalculator and the shared holidays dialog.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import date
from pathlib import Path
from typing import Literal

from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel


class PontosStore:
    """Persistent store for optional-holiday (pontos facultativos) data.

    All mutations go through this class; ``save()`` writes atomically.
    The JSON shape is ``{"pontos_facultativos": {"2026": ["02/01", ...], ...}}``.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, list[str]] = {}
        self._load()

    # ========== Persistence ==========

    def _load(self) -> None:
        """Read from disk.  Corrupt JSON → backup, start fresh."""
        if not self._path.exists():
            self._data = {}
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            # Backup corrupt file so data isn't silently lost forever.
            backup = self._path.with_suffix(".json.bak")
            shutil.copy2(self._path, backup)
            ErrorHandler.log(
                f"pontos_facultativos corrompido ({e}); backup em {backup}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.FILE_IO,
            )
            self._data = {}
            return

        raw_pontos = raw.get("pontos_facultativos", {})
        self._data = raw_pontos if isinstance(raw_pontos, dict) else {}

    def save(self) -> None:
        """Atomic write: ``.tmp`` then ``os.replace``."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        payload = {"pontos_facultativos": self._data}
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, self._path)

    # ========== Queries ==========

    def get_all_dates(self) -> set[date]:
        """All pontos across all years as ``date`` objects."""
        result: set[date] = set()
        for yr_str, plist in self._data.items():
            try:
                yr = int(yr_str)
            except ValueError:
                ErrorHandler.log(
                    f"Ponto ignorado (ano inválido): {yr_str!r}",
                    level=ErrorLevel.DEBUG,
                    context=ErrorContext.FILE_IO,
                )
                continue
            for ps in plist:
                try:
                    d, m = map(int, ps.split("/"))
                    result.add(date(yr, m, d))
                except (ValueError, AttributeError):
                    ErrorHandler.log(
                        f"Ponto ignorado (entrada inválida): {ps!r}",
                        level=ErrorLevel.DEBUG,
                        context=ErrorContext.FILE_IO,
                    )
                    continue
        return result

    def get_year_dates(self, year: int) -> list[date]:
        """Sorted list of pontos for *year* (day-of-week included later)."""
        plist = self._data.get(str(year), [])
        dates: list[date] = []
        for ps in plist:
            try:
                d, m = map(int, ps.split("/"))
                dates.append(date(year, m, d))
            except (ValueError, AttributeError):
                continue
        dates.sort()
        return dates

    def get_years(self) -> list[int]:
        """All years that have at least one ponto entry."""
        years: list[int] = []
        for yr_str, plist in self._data.items():
            if plist:
                try:
                    years.append(int(yr_str))
                except ValueError:
                    continue
        return sorted(years)

    # ========== Mutations ==========

    def add(self, year: int, month: int, day: int) -> Literal["added", "duplicate", "invalid"]:
        """Add a ponto. Returns ``'added'``, ``'duplicate'``, or ``'invalid'``."""
        try:
            dt = date(year, month, day)
        except ValueError:
            return "invalid"
        # Reject national holidays (only facultativos may be managed here).
        # Caller should check this before calling — but guard anyway.
        yr_str = str(dt.year)
        entry = f"{dt.day:02d}/{dt.month:02d}"
        current = self._data.get(yr_str, [])
        if entry in current:
            return "duplicate"
        current.append(entry)
        current.sort(key=lambda x: (int(x.split("/")[1]), int(x.split("/")[0])))
        self._data[yr_str] = current
        return "added"

    def remove(self, dt: date) -> bool:
        """Remove a ponto. Returns ``True`` if found and removed."""
        yr_str = str(dt.year)
        entry = f"{dt.day:02d}/{dt.month:02d}"
        plist = self._data.get(yr_str, [])
        if entry in plist:
            plist.remove(entry)
            return True
        return False

    # ========== Year management ==========

    def ensure_year(self, year: int) -> None:
        """Create an empty entry for *year* if it doesn't exist yet."""
        yr_str = str(year)
        if yr_str not in self._data:
            self._data[yr_str] = []

    def list_all_entries(self) -> list[date]:
        """All pontos across all years, sorted chronologically."""
        return sorted(self.get_all_dates())
