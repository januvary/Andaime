"""
Text normalization utilities.
"""

import unicodedata


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if unicodedata.category(c) != "Mn"
    )


def normalize_text(text: str) -> str:
    if not text:
        return ""
    return _strip_accents(text).lower()


def to_upper_normalized(text: str) -> str:
    if not text:
        return ""
    return _strip_accents(text).upper()
