#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Date utilities for Brazilian business day calculations.

Provides holiday-aware date adjustments using Brazil/SP national holidays
and optional pontos facultativos (optional holidays) loaded from JSON.
"""

import json
import re
import shutil
from datetime import date, datetime, timedelta

import holidays as _holidays_lib

from typing import cast

from andaime.paths import get_root_directory


class DateCalculator:
    _holidays_cache: set[date] | None = None

    @staticmethod
    def _load_pontos_facultativos() -> dict[str, list[str]]:
        root_dir = get_root_directory()
        user_path = root_dir / "data" / "pontos_facultativos.json"
        bundled_path = root_dir / "_internal" / "data" / "pontos_facultativos.json"

        if not user_path.exists() and bundled_path.exists():
            user_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled_path, user_path)

        config_path = user_path if user_path.exists() else bundled_path

        if not config_path.exists():
            try:
                import andaime.data as _pkg_data
                from pathlib import Path

                pkg_path = Path(_pkg_data.__file__).parent / "pontos_facultativos.json"
                if pkg_path.exists():
                    user_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(pkg_path, user_path)
                    config_path = user_path
            except Exception:
                pass

        if not config_path.exists():
            return {}

        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return cast("dict[str, list[str]]", data.get("pontos_facultativos", {}))
        except (json.JSONDecodeError, Exception):
            return {}

    @staticmethod
    def _convert_pontos_to_dates(year: int, pontos_list: list[str]) -> set[date]:
        dates: set[date] = set()
        for date_str in pontos_list:
            try:
                day, month = map(int, date_str.split("/"))
                dates.add(date(year, month, day))
            except (ValueError, AttributeError):
                continue
        return dates

    @staticmethod
    def get_holidays() -> set[date]:
        if DateCalculator._holidays_cache is not None:
            return DateCalculator._holidays_cache

        holidays_set: set[date] = set()

        try:
            br_holidays = _holidays_lib.Brazil(state="SP", years=range(2020, 2031))  # type: ignore[attr-defined]
            holidays_set.update(br_holidays.keys())
        except (ImportError, AttributeError, TypeError):
            try:
                br_holidays = _holidays_lib.country_holidays("BR", subdiv="SP")
                holidays_set.update(br_holidays.keys())
            except Exception:
                pass

        pontos_data = DateCalculator._load_pontos_facultativos()
        for year_str, pontos_list in pontos_data.items():
            try:
                year = int(year_str)
                holidays_set.update(
                    DateCalculator._convert_pontos_to_dates(year, pontos_list)
                )
            except ValueError:
                continue

        DateCalculator._holidays_cache = holidays_set
        return holidays_set

    @classmethod
    def clear_holidays_cache(cls) -> None:
        cls._holidays_cache = None

    @staticmethod
    def is_business_day(dt: date | datetime) -> bool:
        if isinstance(dt, datetime):
            dt = dt.date()
        return dt.weekday() < 5 and dt not in DateCalculator.get_holidays()

    @staticmethod
    def skip_to_previous_business_day(dt: datetime | date) -> date:
        if isinstance(dt, datetime):
            dt = dt.date()
        h = DateCalculator.get_holidays()
        while dt.weekday() >= 5 or dt in h:
            dt -= timedelta(days=1)
        return dt

    @staticmethod
    def skip_to_next_business_day(dt: datetime | date) -> date:
        if isinstance(dt, datetime):
            dt = dt.date()
        h = DateCalculator.get_holidays()
        while dt.weekday() >= 5 or dt in h:
            dt += timedelta(days=1)
        return dt


_WEEKDAYS_PT = [
    "segunda",
    "terça",
    "quarta",
    "quinta",
    "sexta",
    "sábado",
    "domingo",
]


def parse_date(text: str | None) -> date | None:
    """Parse a date string into a ``date``.

    Accepts both Brazilian and ISO shapes:
    - ``DD/MM`` (assumes current year), ``DD/MM/AA`` (2-digit year maps to
      the 2000s) and ``DD/MM/AAAA`` with ``/``, ``-`` or ``.`` separators;
    - ``AAAA-MM-DD`` (ISO), e.g. values stored in the database.
    Returns ``None`` for empty or invalid input (including impossible
    calendar dates).
    """
    text = (text or "").strip()
    if not text:
        return None

    # ISO YYYY-MM-DD (4-digit year first)
    iso_match = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            return None

    parts: list[str] | None = None
    for sep in ("/", "-", "."):
        if sep in text:
            parts = text.split(sep)
            break
    if parts is None or not (2 <= len(parts) <= 3):
        return None
    try:
        day = int(parts[0])
        month = int(parts[1])
        if len(parts) == 2:
            year = date.today().year
        else:
            yp = int(parts[2])
            year = 2000 + yp if yp < 100 else yp
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def format_date(dt: date, include_weekday: bool = False) -> str:
    """Format a ``date`` as ``DD/MM/AAAA``.

    With ``include_weekday=True`` appends the Portuguese weekday in
    parentheses, e.g. ``13/03/2026 (sexta)``.
    """
    if include_weekday:
        return f"{dt.strftime('%d/%m/%Y')} ({_WEEKDAYS_PT[dt.weekday()]})"
    return dt.strftime("%d/%m/%Y")
