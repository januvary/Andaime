from __future__ import annotations

import re
from datetime import date as date_type
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from rac.models import Malote

from andaime.dates import parse_date, format_date


def format_malote_date(malote: Optional[Malote]) -> str:
    if not malote:
        return "?"
    try:
        dt = date_type.fromisoformat(malote.date)
        return format_date(dt)
    except ValueError:
        return malote.date or "?"


def is_malote_past(malote: Optional[Malote]) -> bool:
    if not malote or not malote.date:
        return False
    try:
        return date_type.fromisoformat(malote.date) < date_type.today()
    except ValueError:
        return False


def format_item(name: str) -> str:
    paren = re.search(r"\(([^)]+)\)\s*$", name)
    if not paren:
        result = name
    else:
        brand = paren.group(1).strip().upper()
        digit = re.search(r"\d", name)
        if not digit:
            result = brand
        else:
            dosage = name[digit.start() : paren.start()].strip()
            result = f"{brand} {dosage}"
    return result.replace(" ", "\u00a0")
