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


def scored_search(
    results: list[dict],
    query: str,
    field: str,
    limit: int = 0,
) -> list[dict]:
    if not query:
        return []
    query_normalized = normalize_text(query)
    scored: list[tuple[int, dict]] = []
    for result in results:
        value = result.get(field, "")
        if not value:
            continue
        value_normalized = normalize_text(str(value))
        pos = value_normalized.find(query_normalized)
        if pos >= 0:
            scored.append((pos, result))
    scored.sort(key=lambda x: (x[0], str(x[1].get(field, ""))))
    out = [item[1] for item in scored]
    if limit > 0:
        out = out[:limit]
    return out
