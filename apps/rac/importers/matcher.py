#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Medication matching — maps free-text med names from imported sheets to the
app's items_catalog. Pure logic, no DB/Qt: fed by a list of (name, id) pairs.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable

_CANON_RE = re.compile(r"[^a-z0-9]+")
_PAREN_RE = re.compile(r"\(([^)]+)\)")
_DOSE_RE = re.compile(r"\d+(?:[.,]\d*)?")


def _canon(text: str) -> str:
    """Uppercase, strip accents, drop non-alphanumerics. '10MG' == '10 mg'."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _CANON_RE.sub("", text.lower())


def _letters(text: str) -> str:
    """Only the letters of the canonical form (dose numbers removed)."""
    return _CANON_RE.sub("", re.sub(r"[0-9.,]+", "", text.lower()))


def _dose_tokens(text: str) -> frozenset[str]:
    """Dose numbers as written, decimal-aware. '2,5' stays distinct from '25'."""
    return frozenset(_DOSE_RE.findall(text.upper().replace(" ", "")))


# Active-ingredient abbreviations / common typos seen in real sheets.
# Keys stored lowercase to match canonical sheet letters.
_INGREDIENT_ALIASES: dict[str, str] = {
    "ator": "ATORVASTATINA",
    "ciclosp": "CICLOSPORINA",
    "ciclocsp": "CICLOSPORINA",
    "micof": "MICOFENOLATO",
    "micofmofetila": "MICOFENOLATODEMOFETILA",
    "micofenolatomofetila": "MICOFENOLATODEMOFETILA",
"mesal": "MESALAZINA",
    "mes": "MESALAZINA",
    "shf": "sacarato de hidroxido ferrico 100 mg inj.",
    "ciclopsorina": "CICLOSPORINA",
    "azatiopriona": "AZATIOPRINA",
    "dapaglifloizina": "DAPAGLIFLOZINA",
    "dapgliflozina": "DAPAGLIFLOZINA",
    "etn": "ETANERCEPTE",
    "tac": "TACROLIMO",
    "micofenolatosodio": "MICOFENOLATODESODIO",
    "fludrocortisona": "FLUDROCORTISONA",
    "kit": "kit infusao infliximabe",
}

# Special whole-name phrases -> specific catalog items. Keys lowercase.
_PHRASE_ALIASES: dict[str, str] = {
    "insulinaglargina": "insulina analoga de acao prolongada 100 ui/ml",
    "insulinalispro": "insulina analoga de acao rapida 100 ui/ml",
}

# Form words that hint at a liquid/solution catalog form.
LIQUID_HINTS = ("ML", "SOL", "SOLUCAO", "GOTAS", "XAROPE", "SPRAY", "NASAL")
# Form words that hint at a solid form.
SOLID_HINTS = ("CAP", "COMP", "COMPRIMIDO", "POMADA", "CREME", "SACHE", "CPSULA")


class MedMatcher:
    """Match sheet med names to catalog items by id."""

    def __init__(self, catalog: Iterable[tuple[str, int]]) -> None:
        self._items: list[tuple[str, int]] = list(catalog)
        self._by_canon: dict[str, int] = {}
        self._by_brand: dict[str, list[int]] = {}
        self._by_letters: dict[str, list[int]] = {}

        for name, cid in self._items:
            canon = _canon(name)
            self._by_canon.setdefault(canon, cid)

            for brand in set(_PAREN_RE.findall(name)):
                brand_letters = _letters(brand) or _canon(brand)
                if brand_letters:
                    self._by_brand.setdefault(brand_letters, []).append(cid)

            letters = _letters(name)
            for start in range(0, len(letters), 6):
                key = letters[start : start + 14]
                self._by_letters.setdefault(key, []).append(cid)
            self._by_letters.setdefault(letters[:18], []).append(cid)

    def _candidates_by_letters(self, sheet_letters: str) -> list[int]:
        if not sheet_letters:
            return []
        seen: set[int] = set()
        out: list[int] = []
        for key in (sheet_letters[:18], sheet_letters[:12], sheet_letters[:6]):
            for cid in self._by_letters.get(key, []):
                if cid not in seen:
                    seen.add(cid)
                    out.append(cid)
        return out

    def match(self, sheet_name: str) -> tuple[int | None, str | None]:
        """Return (catalog_id, catalog_name) or (None, reason)."""
        canon = _canon(sheet_name)
        sheet_letters = _letters(sheet_name)
        sheet_doses = _dose_tokens(sheet_name)

        # 0. phrase alias (e.g. insulinas de marca)
        phrase = _PHRASE_ALIASES.get(sheet_letters)
        if phrase:
            pcanon = _canon(phrase)
            if pcanon in self._by_canon:
                return self._by_canon[pcanon], self._name_of(self._by_canon[pcanon])

        # 1. exact canonical
        if canon in self._by_canon:
            cid = self._by_canon[canon]
            return cid, self._name_of(cid)

        # 2. brand alias (exact, or brand token within a longer name) — dose aware
        if sheet_letters in self._by_brand:
            best = self._pick_brand_candidate(
                self._by_brand[sheet_letters], sheet_doses
            )
            if best is not None:
                return best, self._name_of(best)
        for brand, cids in self._by_brand.items():
            if len(brand) >= 4 and brand in sheet_letters:
                best = self._pick_brand_candidate(cids, sheet_doses)
                if best is not None:
                    return best, self._name_of(best)

        # 3. ingredient alias (abbreviations/typos). Run on canon to keep doses.
        aliased = _INGREDIENT_ALIASES.get(canon) or _INGREDIENT_ALIASES.get(
            sheet_letters
        )
        if aliased:
            cid2 = self._try_aliased(aliased, sheet_doses, sheet_name)
            if cid2 is not None:
                return cid2, self._name_of(cid2)

        # 3b. partial-word alias (prefix like 'ATOR', 'MICOF', 'MESAL'), dose aware
        for abbr, full in _INGREDIENT_ALIASES.items():
            if len(abbr) >= 4 and canon.startswith(abbr):
                rest = canon[len(abbr):]
                rebuilt = _canon(full + rest)
                if rebuilt in self._by_canon:
                    cid2 = self._by_canon[rebuilt]
                    return cid2, self._name_of(cid2)
                cid2 = self._fuzzy_best(rebuilt, sheet_doses=sheet_doses)
                if cid2 is not None:
                    return cid2, self._name_of(cid2)

        # 4. strip dose+form -> letters-overlap candidates, score by ingredient
        cleaned = self._strip_dose_form(sheet_name)
        cand = self._candidates_by_letters(_letters(cleaned) or sheet_letters)
        if cand:
            cid2 = self._pick_best_for_candidates(cand, sheet_name, sheet_doses)
            if cid2 is not None:
                return cid2, self._name_of(cid2)

        # 5. generic fuzzy, dose aware
        cid2 = self._fuzzy_best(canon, sheet_doses=sheet_doses)
        if cid2 is not None:
            return cid2, self._name_of(cid2)

        return None, None

    def _try_aliased(
        self,
        aliased: str,
        sheet_doses: frozenset[str],
        sheet_name: str,
    ) -> int | None:
        aliased_canon = _canon(aliased)
        if aliased_canon in self._by_canon:
            return self._by_canon[aliased_canon]
        cand = self._candidates_by_letters(_letters(aliased))
        return self._pick_best_for_candidates(cand[:8], aliased, sheet_doses)

    def _pick_brand_candidate(
        self,
        candidates: list[int],
        sheet_doses: frozenset[str],
    ) -> int | None:
        """Among brand-tagged candidates, pick by dose intersection.

        With no sheet dose, a single brand-tagged candidate is unambiguous;
        otherwise require an exact dose-set match (or single intersection).
        """
        if not candidates:
            return None
        if not sheet_doses:
            return candidates[0] if len(candidates) == 1 else None
        exact = [
            cid
            for cid in candidates
            if _dose_tokens(self._name_of(cid)) == sheet_doses
        ]
        if len(exact) == 1:
            return exact[0]
        inter = [cid for cid in candidates if _dose_tokens(self._name_of(cid)) & sheet_doses]
        return inter[0] if len(inter) == 1 else None

    def _pick_best_for_candidates(
        self,
        candidates: list[int],
        sheet_name: str,
        sheet_doses: frozenset[str],
        min_ratio: float = 0.5,
    ) -> int | None:
        if not candidates:
            return None
        q = _canon(sheet_name)
        q_letters = _letters(sheet_name)
        best_id: int | None = None
        best_score = min_ratio
        for cid in candidates:
            cname = self._name_of(cid)
            ccanon = _canon(cname)
            cdoses = _dose_tokens(cname)

            # dose compatibility gates hard mismatches when sheet specifies doses
            if sheet_doses and cdoses and not (sheet_doses & cdoses):
                continue

            ratio = SequenceMatcher(None, q, ccanon).ratio()
            letter_ratio = SequenceMatcher(None, q_letters, _letters(cname)).ratio()
            score = max(ratio, letter_ratio)

            # liquid/solid form hint
            if sheet_doses and cdoses and sheet_doses == cdoses:
                score += 0.15
            liquid = any(h in ccanon for h in LIQUID_HINTS)
            solid = any(h in ccanon for h in SOLID_HINTS)
            if any(h in q_letters for h in LIQUID_HINTS) and liquid:
                score += 0.05
            if any(h in q_letters for h in SOLID_HINTS) and solid:
                score += 0.05

            if score > best_score:
                best_score = score
                best_id = cid
        return best_id

    def _strip_dose_form(self, name: str) -> str:
        words = _canon(name).split()
        kept = []
        for w in words:
            if w in ("e", "de"):
                continue
            if any(ch.isdigit() for ch in w):
                continue
            kept.append(w)
        return " ".join(kept)

    def _fuzzy_best(
        self,
        query: str,
        candidates: list[int] | None = None,
        sheet_doses: frozenset[str] | None = None,
        min_ratio: float = 0.55,
    ) -> int | None:
        if candidates is None:
            candidates = [cid for _, cid in self._items]
        doses = frozenset() if sheet_doses is None else sheet_doses
        return self._pick_best_for_candidates(candidates, query, doses, min_ratio)

    def _name_of(self, cid: int) -> str:
        for name, c in self._items:
            if c == cid:
                return name
        return ""