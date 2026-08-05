#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Excel Importer — reads patient names from .xlsx files.

Scans all tabs, detects the patient column from headers (PACIENTE(S),
NOME(S), NAME(S), ...) and extracts unique normalized names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
from andaime.text import to_upper_normalized

_HEADER_SCAN_ROWS = 16
_CONTENT_SCAN_ROWS = 50
_HIGH_PRIORITY = {"PACIENTE", "PACIENTES", "PATIENT", "PATIENTS"}
_LOW_PRIORITY = {"NOME", "NOMES", "NAME", "NAMES"}
_HEADER_NOISE = frozenset(_HIGH_PRIORITY | _LOW_PRIORITY)
_TOKEN_RE = re.compile(r"[A-Z0-9]+")

_COL_SPEC_RE = re.compile(r"^(\d+)\s*-\s*([A-Za-z]+)$")


def _header_tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(to_upper_normalized(text)))


def _nonempty_cell_count(row: tuple) -> int:
    return sum(1 for v in row if v is not None and str(v).strip())


def parse_col_spec(text: str) -> dict[int, str]:
    """Parse '1-A; 2-B' into {1: 'A', 2: 'B'}.

    Each entry is ``<tab_index>-<column_letter>`` separated by ``;``.
    Malformed entries are ignored. Returns a dict keyed by 1-based tab index.
    """
    result: dict[int, str] = {}
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        m = _COL_SPEC_RE.match(part)
        if not m:
            continue
        idx = int(m.group(1))
        if idx >= 1:
            result[idx] = m.group(2).upper()
    return result


def format_col_spec(col_map: dict[int, str]) -> str:
    """Inverse of parse_col_spec: {1: 'A', 2: 'B'} -> '1-A; 2-B'."""
    return "; ".join(f"{idx}-{letter}" for idx, letter in sorted(col_map.items()))


def _ensure_openpyxl():
    try:
        import openpyxl

        return openpyxl
    except ImportError:
        ErrorHandler.log(
            "openpyxl não instalado",
            level=ErrorLevel.ERROR,
            context=ErrorContext.EXPORT,
        )
        return None


@dataclass
class SheetAnalysis:
    name: str
    content_columns: list[str]
    header_row: int | None
    patient_col: str | None


@dataclass
class ImportAnalysis:
    sheets: list[SheetAnalysis]

    @property
    def all_content_columns(self) -> list[str]:
        seen: list[str] = []
        for s in self.sheets:
            for c in s.content_columns:
                if c not in seen:
                    seen.append(c)
        return seen

    @property
    def detected_patient_col(self) -> str | None:
        for s in self.sheets:
            if s.patient_col:
                return s.patient_col
        return None

    @property
    def default_col_spec(self) -> str:
        """Pre-fill string from per-sheet detection, e.g. '1-A; 3-B'."""
        parts = []
        for i, s in enumerate(self.sheets, start=1):
            if s.patient_col:
                parts.append(f"{i}-{s.patient_col}")
        return "; ".join(parts)

    @property
    def sheet_names(self) -> list[str]:
        return [s.name for s in self.sheets]


class ExcelImporter:
    """Open a workbook once, analyze it, then extract names from a chosen column."""

    def __init__(self, path: str) -> None:
        openpyxl = _ensure_openpyxl()
        if openpyxl is None:
            raise ImportError("openpyxl não instalado")
        self._wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        self._analysis: ImportAnalysis | None = None

    def close(self) -> None:
        self._wb.close()

    def analyze(self) -> ImportAnalysis:
        sheets = [self._analyze_sheet(ws) for ws in self._wb.worksheets]
        self._analysis = ImportAnalysis(sheets=sheets)
        return self._analysis

    def _analyze_sheet(self, ws) -> SheetAnalysis:
        from openpyxl.utils import get_column_letter

        max_row = ws.max_row or 0
        if max_row == 0:
            return SheetAnalysis(
                name=ws.title, content_columns=[], header_row=None, patient_col=None
            )

        rows = list(
            ws.iter_rows(
                min_row=1,
                max_row=min(max_row, _CONTENT_SCAN_ROWS),
                values_only=True,
            )
        )
        if not rows:
            return SheetAnalysis(
                name=ws.title, content_columns=[], header_row=None, patient_col=None
            )

        n_cols = max(len(r) for r in rows)

        content_columns: list[str] = []
        for col_idx in range(1, n_cols + 1):
            for r in rows:
                if col_idx <= len(r):
                    v = r[col_idx - 1]
                    if v is not None and str(v).strip():
                        content_columns.append(get_column_letter(col_idx))
                        break

        header_row: int | None = None
        patient_col: str | None = None
        best_score = 0
        for row_idx, r in enumerate(rows[:_HEADER_SCAN_ROWS], start=1):
            if _nonempty_cell_count(r) < 2:
                continue
            row_has_match = False
            for col_idx in range(1, len(r) + 1):
                tokens = _header_tokens(str(r[col_idx - 1] or ""))
                if tokens & _HIGH_PRIORITY:
                    score = 2
                elif tokens & _LOW_PRIORITY:
                    score = 1
                else:
                    continue
                row_has_match = True
                if score > best_score:
                    best_score = score
                    patient_col = get_column_letter(col_idx)
                    header_row = row_idx
            if row_has_match:
                break

        if patient_col is None and 2 <= len(content_columns) <= 3:
            patient_col = content_columns[0]

        return SheetAnalysis(
            name=ws.title,
            content_columns=content_columns,
            header_row=header_row,
            patient_col=patient_col,
        )

    def extract_names(self, col_map: dict[int, str]) -> list[str]:
        """Extract unique normalized patient names.

        col_map maps a 1-based tab index to a column letter. Tabs absent from
        the map are skipped.
        """
        from openpyxl.utils import column_index_from_string

        if self._analysis is None:
            self.analyze()

        assert self._analysis is not None
        analysis_by_idx = {
            i: s for i, s in enumerate(self._analysis.sheets, start=1)
        }

        worksheets = self._wb.worksheets
        names: list[str] = []
        seen: set[str] = set()
        for tab_idx, col_letter in col_map.items():
            if tab_idx < 1 or tab_idx > len(worksheets):
                continue
            ws = worksheets[tab_idx - 1]
            col_idx = column_index_from_string(col_letter)
            sa = analysis_by_idx.get(tab_idx)
            start_row = (sa.header_row + 1) if sa and sa.header_row else 1
            for row in ws.iter_rows(min_row=start_row, values_only=True):
                if col_idx - 1 >= len(row):
                    continue
                v = row[col_idx - 1]
                if v is None:
                    continue
                text = str(v).strip()
                if not text:
                    continue
                normalized = to_upper_normalized(text)
                if not normalized or normalized in _HEADER_NOISE:
                    continue
                if normalized not in seen:
                    seen.add(normalized)
                    names.append(normalized)
        return names
