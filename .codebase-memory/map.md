# CODEBASE MAP (passive context)
# Skeleton bodies mean: signatures kept, implementations stripped to '...'.

## andaime/database.py
_symbols: 41_ 
```python
"""
Base SQLite database class with connection management, retries, and backups.
"""

import os
import re
import sqlite3
import sys
import threading
import time
import shutil
from abc import ABC, abstractmethod
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, ParamSpec, TypeVar, cast

from andaime.paths import resolve_db_path
from andaime.error_handler import ErrorHandler, ErrorLevel

_P = ParamSpec("_P")
_R = TypeVar("_R")


# Tipos de filesystem de rede conhecidos (coluna fstype do /proc/mounts).
# WAL do SQLite é não-confiável nestes filesystems (riscos de hang e
# corrupção documentados), então usamos rollback-journal (DELETE) neles.
_NETWORK_FS_TYPES = frozenset(
    {
        "cifs",
        "smbfs",
        "smb2",
        "smb3",
        "nfs",
        "nfs4",
        "ncpfs",
        "fuse.sshfs",
        "fuse.curlftpfs",
        "fuse.gvfs-fuse-daemon",
        "davfs",
        "lustre",
        "gpfs",
        "ocfs2",
    }
)

# DRIVE_REMOTE do GetDriveTypeW (Windows).
_DRIVE_REMOTE = 4


def _decode_mount_point(raw: str) -> str:
    ...


def _read_proc_mounts() -> list[tuple[str, str, str]]:
    ...


def _is_network_path(path: str) -> bool:
    ...


def db_op(op_type: str = "read") -> Callable[[Callable[_P, _R]], Callable[_P, _R]]:
    ...


class BaseDatabase(ABC):
    def __init__(
        self, db_path: str | None = None, entity_name: str = "registros"
    ) -> None:
        ...

    @abstractmethod
    def _create_schema(self) -> None:
        ...

    def _ensure_schema_meta(self) -> None:
        ...

    def _ensure_schema_version(self) -> int:
        ...

    def _set_schema_version(self, version: int) -> None:
        ...

    def _resolve_default_db_path(self) -> str:
        ...

    def __enter__(self) -> "BaseDatabase":
        ...

    def __exit__(self, _exc_type: Any, _exc_val: Any, _exc_tb: Any) -> Literal[False]:
        ...

    def __del__(self) -> None:
        ...

    def _apply_pragmas(self, cur: sqlite3.Cursor) -> None:
        ...

    def _initialize(self) -> None:
        ...

    def _log_initialization_success(self) -> None:
        ...

    def _is_connection_healthy(self) -> bool:
        ...

    def _reconnect_unlocked(self) -> None:
        ...

    def _refresh_connection(self) -> None:
        ...

    def _ensure_connection(self) -> None:
        ...

    def _get_cursor(self) -> sqlite3.Cursor:
        ...

    def _get_connection(self) -> sqlite3.Connection:
        ...

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        ...

    def _fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        ...

    def _fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        ...

    def _fetch_value(self, sql: str, params: tuple = ()) -> Any:
        ...

    def _execute_write(self, sql: str, params: tuple = ()) -> bool:
        ...

    def _execute_insert(self, sql: str, params: tuple = ()) -> int:
        ...

    def _fetch_by_id(self, table: str, row_id: int) -> dict | None:
        ...

    def _fetch_all_table(self, table: str, order_by: str = "") -> list[dict]:
        ...

    def _fetch_count(self, table: str, where: str = "", params: tuple = ()) -> int:
        ...

    def _insert_row(self, table: str, **kwargs: Any) -> int:
        ...

    def _update_row(self, table: str, row_id: int, **kwargs: Any) -> bool:
        ...

    def _delete_row(
        self, table: str, row_id: int, guards: list[tuple[str, str]] | None = None
    ) -> bool:
        ...

    def _commit(self) -> None:
        ...

    @contextmanager
    def transaction(self) -> Iterator[None]:
        ...

    def _rollback(self) -> None:
        ...

    def _retry_on_transient_error(
        self,
        operation: Callable,
        max_retries: int = 3,
        operation_type: str = "operation",
    ) -> Any:
        ...

    def _backup_database(self) -> None:
        ...

    def close(self, skip_backup: bool = False) -> None:
        ...
```

## andaime/error_handler.py
_symbols: 15_ 
```python
"""
Centralized error handling with logging and UI dialogs.
"""

from __future__ import annotations

import logging
import sys
import traceback
from contextlib import suppress
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class ErrorLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class ErrorContext(str, Enum):
    DATABASE = "Database"
    FILE_IO = "File I/O"
    PDF_GENERATION = "PDF Generation"
    VALIDATION = "Validation"
    CONFIGURATION = "Configuration"
    UI = "User Interface"
    SECURITY = "Security"
    SHUTDOWN = "Shutdown"
    NETWORK = "Network"
    AUTOCOMPLETE = "Autocomplete"
    STATE = "State Management"
    EXPORT = "Export"
    REGISTRY = "Registry"
    UPDATER = "Updater"
    BATCH = "Batch"
    APP = "App"
    UNKNOWN = "Unknown"


class ErrorHandler:
    _logger: logging.Logger | None = None
    _show_dialog_callback: Callable[[str, str, ErrorLevel], None] | None = None
    _initialized: bool = False

    @staticmethod
    def _ctx(context: Any) -> str:
        ...

    def __init__(self) -> None:
        ...

    @classmethod
    def init(cls, app_name: str, root: Path | None = None) -> None:
        ...

    @staticmethod
    def handle_error(
        error: Exception,
        context: str | ErrorContext = ErrorContext.UNKNOWN,
        level: ErrorLevel = ErrorLevel.ERROR,
        show_dialog: bool = True,
        recovery_hint: str | None = None,
    ) -> str:
        ...

    @staticmethod
    def log(
        message: str,
        level: ErrorLevel = ErrorLevel.INFO,
        context: str | ErrorContext = ErrorContext.UNKNOWN,
    ) -> None:
        ...

    @staticmethod
    def handle_file_error(
        error: Exception,
        file_path: str,
        operation: str = "access",
        show_dialog: bool = True,
    ) -> str:
        ...

    @staticmethod
    def handle_validation_error(
        error: Exception,
        field: str,
        recovery_hint: str | None = None,
        show_dialog: bool = True,
    ) -> str:
        ...

    @staticmethod
    def handle_database_error(
        error: Exception,
        operation: str = "database operation",
        recovery_hint: str | None = None,
        show_dialog: bool = True,
    ) -> str:
        ...

    @staticmethod
    def safe_execute(
        func: Callable[..., Any],
        *args: Any,
        operation_name: str = "operation",
        on_error: Callable[[Exception], None] | None = None,
        context: str | ErrorContext = ErrorContext.UNKNOWN,
        **kwargs: Any,
    ) -> Any:
        ...

    @staticmethod
    def suppress_and_log(
        func: Callable,
        *args: Any,
        operation_name: str = "operation",
        context: str | ErrorContext = ErrorContext.UNKNOWN,
        **kwargs: Any,
    ) -> Any:
        ...

    @staticmethod
    def _setup_logging() -> None:
        ...

    @staticmethod
    def get_logger() -> logging.Logger:
        ...
```

## andaime/updater.py
_symbols: 29_ 
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
andaime.updater — Auto-update for Python-style SISTEMAS deployments.

Layout::

    <install_root>/
    ├── python/                          ← embedded CPython + deps
    │   └── Lib/site-packages/andaime/   ← shared chassis
    ├── apps/<module>/                   ← app code (e.g. apps/rac/)
    ├── data/                            ← user data (NEVER touched by updates)
    └── VERSION                          ← "1.2.3\\nruntime: <hash>"

Update flow::

    1. UpdateCheckWorker (background thread) queries GitHub Releases API.
    2. Compares app version + runtime hash.
    3. Downloads ``update.zip`` (small) or ``payload.zip`` (full python/).
    4. Extracts to ``_update_staging/``.
    5. User clicks Restart → ``restart_app()``.
    6. New process calls ``apply_pending_update()``.
    7. Directories swapped atomically (``.old`` suffix for rollback).
    8. New version launched with ``--post-update`` monitoring.
    9. On success signature → cleanup ``.old`` dirs.
   10. On failure/timeout → rollback ``.old`` dirs, relaunch old version.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

from andaime.error_handler import ErrorHandler, ErrorLevel

# ============================================================================
# Constants
# ============================================================================

STAGING_DIR = "_update_staging"
VERSION_FILE = "VERSION"
UPDATE_TAG = ".update_tag"
POST_UPDATE_ENV = "ANDAIME_POST_UPDATE"
SUCCESS_FILE = "success"
ROLLOUT_TIMEOUT = 30  # seconds to wait for launch signature

ANDAIME_REPO = "januvary/andaime"

# ============================================================================
# Install-root detection
# ============================================================================


def get_install_root() -> Path:
    ...


def get_shared_root() -> Path:
    ...


def staging_path() -> Path:
    ...


def _get_app_module() -> str:
    ...


# ============================================================================
# VERSION file I/O (hash-based manifest)
# ============================================================================


def parse_manifest_text(text: str) -> dict[str, str]:
    ...


def read_version_manifest(path: Path | None = None) -> dict[str, str]:
    ...


def get_local_manifest() -> dict[str, str]:
    ...


def get_local_hash(module: str) -> str:
    ...


def get_local_runtime_hash() -> str:
    ...


# ============================================================================
# Zip safety + checksums
# ============================================================================


def _verify_zip_paths(zf: zipfile.ZipFile) -> None:
    ...


def _sha256_file(path: Path) -> str:
    ...

# ============================================================================
# Directory swap primitives
# ============================================================================


def _swap_directory(current: Path, new: Path) -> list[tuple[Path, Path]]:
    ...


def _rollback(swaps: list[tuple[Path, Path]]) -> None:
    ...


def _cleanup_old_dirs(root: Path) -> None:
    ...


# ============================================================================
# Install format detection
# ============================================================================


def _detect_install_format(root: Path) -> str:
    ...


def _format_error_message(current_format: str, staged_format: str) -> str:
    ...


# ============================================================================
# Update application
# ============================================================================


def _acquire_lock(lock_path: Path) -> object | None:
    ...


def _release_lock(lock_path: Path, lock_handle: object | None) -> None:
    ...


def apply_pending_update() -> bool:
    ...


def _apply_pending_update_locked() -> bool:
    ...


def _get_python_exe() -> Path:
    ...


def _launch_with_monitoring(
    app_module: str, swaps: list[tuple[Path, Path]]
) -> None:
    ...


def signal_post_update_success() -> None:
    ...


# ============================================================================
# Restart
# ============================================================================


def restart_app() -> None:
    ...


# ============================================================================
# Error UI
# ============================================================================


def _show_update_error(error: Exception) -> None:
    ...


# ============================================================================
# Background update checker
# ============================================================================


class UpdateCheckWorker(QThread):
    """Background thread that checks januvary/andaime for updates.

    Uses hash-based comparison: downloads payload.zip when the runtime
    hash differs, and app-update.zip when the local app hash differs.

    Signals
    -------
    update_available(str, str) : ``(tag, release_notes)``
    update_ready(str)          : ``(tag,)`` — download complete, awaiting restart
    update_failed(str)         : ``(error_message,)``
    no_update()                — all hashes match, already up to date
    """

    update_available = Signal(str, str)
    update_ready = Signal(str)
    update_failed = Signal(str)
    no_update = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        ...

    def run(self) -> None:
        ...

    def _download_and_stage(
        self, url: str, tmp: str, filename: str, headers: dict, context: ssl.SSLContext
    ) -> None:
        ...
```

## andaime/widgets.py
_symbols: 29_ 
```python
"""PySide6 search-enabled combo box widget with accent-insensitive matching."""

from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal, QStringListModel
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from andaime.dates import parse_date
from andaime.text import scored_search_dict

SearchFn = Callable[[str], dict[str, str]]


def static_search_fn(options: dict[str, str]) -> SearchFn:
    ...


class SearchableComboBox(QWidget):
    """
    Campo de busca com autocomplete.

    Recebe uma função `search_fn(query) -> dict[key, label]`. A busca é
    síncrona: o chamador decide se filtra um dict local ou consulta o banco.
    """

    selection_changed = Signal(object)
    text_edited = Signal(str)

    def __init__(
        self,
        search_fn: SearchFn,
        placeholder: str = "Buscar...",
        parent: QWidget | None = None,
    ):
        ...

    @property
    def line_edit(self) -> QLineEdit:
        ...

    def set_search_fn(self, search_fn: SearchFn) -> None:
        ...

    def current_data(self) -> str | None:
        ...

    def set_current(self, data: str, label: str) -> None:
        ...

    def set_current_by_data(self, data: str) -> None:
        ...

    def set_text(self, text: str) -> None:
        ...

    def current_text(self) -> str:
        ...

    def focus_search(self) -> None:
        ...

    def clear(self) -> None:
        ...

    def _on_text_edited(self, text: str) -> None:
        ...

    def _update_model(self, query: str, show_popup: bool = False) -> None:
        # A search_fn é a fonte da verdade sobre o que casa e em que ordem.
        # O widget NÃO refiltra pelo label (senão buscas por um campo que não
        # aparece no label — ex.: telefone — seriam descartadas).
        ...

    def _on_text_changed(self, text: str) -> None:
        ...

    def _on_activated(self, text: str) -> None:
        ...


import calendar
from datetime import date, timedelta


def _add_months(d: date, n: int) -> date:
    ...


class DateLineEdit(QLineEdit):
    """Date entry that combines free typing with QDateEdit-style arrow stepping.

    Typed input is auto-formatted to ``DD/MM/YYYY`` (slashes inserted as digits
    are entered, with a ``DD/MM/YYYY`` placeholder when empty). Pressing
    Up/Down steps the day/month/year under the cursor -- like QDateEdit's
    section editing -- without giving up the text-field typing experience.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        ...

    @staticmethod
    def _format(text: str) -> str:
        ...

    def _on_text_edited(self, text: str) -> None:
        ...

    def keyPressEvent(self, event: Any) -> None:
        ...

    def _step(self, up: bool) -> bool:
        ...


class CycleButton(QPushButton):
    def __init__(
        self,
        label: str,
        role: str,
        *,
        modulus: int,
        base: int,
        initial: int,
        width: int = 40,
        font_size: int = 14,
        format_fn=None,
        on_change=None,
    ):
        ...

    def mousePressEvent(self, event):
        ...

    def _apply_label(self):
        ...

    @property
    def value(self) -> int:
        ...

    @value.setter
    def value(self, v: int):
        ...
```

## andaime/qt/theme.py
_symbols: 17_ 
```python
"""Tema Qt neutro compartilhado (andaime.qt).

Paleta light/dark em tons de cinza (sem azul/verde/vermelho) + QPalette
nativa + QSS global, além de ``ThemeToggleButton`` e ``make_button``.

As chaves da paleta seguem o esquema do Emissor (``window_bg``,
``panel_bg``, ``panel_header_bg``, ``panel_border``, ``box_bg``, ``text``,
``text_dim``, ``input_bg``, ``input_border``, ``btn_*``, ``action_*``,
``status_*``, ``date_*``). Chaves extras usadas pelo SS-54 (``bg_hover``,
``bg_pressed``, ``border_light``, ``text_secondary``, ``selection_*``,
``separador``, ``gridline``, ``scrollbar*``, ``toast_*``) foram agregadas
com nomes consistentes. O foreground dos toasts positive/warning/negative
é deduplicado em ``status_success``/``status_warning``/``status_error``
(apenas ``toast_info_fg`` permanece próprio); ver ``_build_qss``.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton

# ============================================================================
# Fonte base por plataforma
# ============================================================================


def _platform_font() -> str:
    ...


FONT_FAMILY = _platform_font()


def set_font_family(family: str) -> None:
    ...


PX = 13
PX_SMALL = 12
PX_HEADER = 14
PX_LARGE = 16


# ============================================================================
# Paletas (light / dark) — tons de cinza, sem cores de destaque
# ============================================================================

# ---- Chaves neutras e semânticas (fonte única para o modelo de rampa) ----
SURFACE_KEYS: tuple[str, ...] = (
    "window_bg",
    "panel_bg",
    "panel_header_bg",
    "box_bg",
    "panel_border",
    "border_light",
    "input_bg",
    "input_border",
    "text",
    "text_dim",
    "text_secondary",
    "bg_hover",
    "bg_pressed",
    "selection_bg",
    "selection_text",
    "separador",
    "gridline",
    "scrollbar",
    "scrollbar_hover",
    "date_editable",
    "date_calc_1",
    "date_calc_2",
    "btn_flat_hover",
    "btn_flat_fill",
    "btn_flat_fill_hover",
    "btn_primary",
    "btn_primary_hover",
    "action_1",
    "action_2",
    "action_3",
    "action_4",
    "action_5",
)

SEMANTIC_KEYS: tuple[str, ...] = (
    "status_success",
    "status_warning",
    "status_error",
    "toast_positive_bg",
    "toast_warning_bg",
    "toast_negative_bg",
    "toast_info_fg",
    "toast_info_bg",
    "brasao_ink",
)

# Comentários inline preservados por nível ao gravar _LEVELS.
LEVEL_COMMENTS: dict[int, str] = {
    1: "preto profundo",
    2: "tinta quase-preta",
    3: "tinta (ink)",
    4: "tinta esmaecida",
    5: "linhas / bordas",
    6: "preenchimentos",
    7: "hover",
    8: "superfície baixa",
    9: "superfície média",
    10: "superfície alta",
    11: "branco quase-puro",
    12: "branco puro",
}


# ---- Rampa neutra (fonte da verdade das superfícies) ----
# Cada modo tem 2 extremos (escuro, claro). As superfícies não guardam cor
# própria: cada papel (role) aponta para um NÍVEL numerado (1..12), e cada
# nível é uma posição t na rampa (0=papel escuro, 1=papel claro). DARK usa
# (1 - t), i.e. o modo escuro é o negativo fotográfico da rampa.
#
# Ajustar um nível remaneja todos os papéis nele; trocar o nível de um papel
# realoca só aquele papel. É só isso que define toda a paleta neutra.
_RAMP: dict[str, tuple[str, str]] = {
    "LIGHT": ("#0c2a2c", "#faffff"),
    "DARK": ("#252b37", "#fcfff0"),
}

# Nível -> posição t na rampa (do mais escuro ao mais claro).
_LEVELS: dict[int, float] = {
    1: -0.4,  # preto profundo
    2: -0.15,  # tinta quase-preta
    3: 0.0023,  # tinta (ink)
    4: 0.2609,  # tinta esmaecida
    5: 0.7245,  # linhas / bordas
    6: 0.8023,  # preenchimentos
    7: 0.9004,  # hover
    8: 0.9322,  # superfície baixa
    9: 0.9625,  # superfície média
    10: 1.0,  # superfície alta
    11: 1.11,  # branco quase-puro
    12: 1.2,  # branco puro
}

# Papel (role) -> nível, por modo (Light/Dark).
_ROLE_LEVEL: dict[str, dict[str, int]] = {
    "LIGHT": {
        "text": 1,
        "text_secondary": 3,
        "selection_text": 3,
        "text_dim": 4,
        "panel_border": 5,
        "input_border": 5,
        "bg_pressed": 5,
        "selection_bg": 5,
        "separador": 5,
        "scrollbar_hover": 5,
        "border_light": 6,
        "gridline": 6,
        "scrollbar": 6,
        "panel_header_bg": 7,
        "bg_hover": 7,
        "btn_flat_hover": 7,
        "panel_bg": 8,
        "date_calc_1": 8,
        "btn_flat_fill_hover": 8,
        "btn_primary_hover": 8,
        "action_2": 8,
        "date_calc_2": 9,
        "btn_primary": 9,
        "action_1": 9,
        "action_3": 9,
        "window_bg": 10,
        "date_editable": 10,
        "btn_flat_fill": 10,
        "action_4": 10,
        "action_5": 10,
        "box_bg": 12,
        "input_bg": 12,
    },
    "DARK": {
        "text": 1,
        "text_secondary": 3,
        "selection_text": 3,
        "text_dim": 4,
        "panel_border": 5,
        "input_border": 5,
        "bg_pressed": 5,
        "selection_bg": 5,
        "separador": 5,
        "scrollbar_hover": 5,
        "border_light": 6,
        "gridline": 6,
        "scrollbar": 6,
        "bg_hover": 7,
        "btn_flat_hover": 7,
        "panel_bg": 8,
        "panel_header_bg": 8,
        "date_calc_1": 8,
        "btn_flat_fill_hover": 8,
        "btn_primary_hover": 8,
        "action_2": 8,
        "date_calc_2": 9,
        "btn_primary": 9,
        "action_1": 9,
        "action_3": 9,
        "window_bg": 10,
        "box_bg": 10,
        "input_bg": 10,
        "date_editable": 10,
        "btn_flat_fill": 10,
        "action_4": 10,
        "action_5": 10,
    },
}

_SEMANTIC: dict[str, dict[str, str]] = {
    "LIGHT": {
        "status_success": "#14d57c",
        "status_warning": "#c29b35",
        "status_error": "#cb3c48",
        "toast_positive_bg": "#f0fff0",
        "toast_warning_bg": "#fffff0",
        "toast_negative_bg": "#fde1d7",
        "toast_info_fg": "#7662af",
        "toast_info_bg": "#f3f3ff",
        "brasao_ink": "#342a2c",
    },
    "DARK": {
        "status_success": "#6bca86",
        "status_warning": "#f0b580",
        "status_error": "#ff5376",
        "toast_positive_bg": "#005a3c",
        "toast_warning_bg": "#5a3c28",
        "toast_negative_bg": "#503200",
        "toast_info_fg": "#bbd6ff",
        "toast_info_bg": "#2b2b49",
        "brasao_ink": "#ddf5e4",
    },
}


def _lerp_hex(lo: str, hi: str, t: float) -> str:
    ...


def _build_palette(mode: str) -> dict[str, str]:
    ...


LIGHT: dict[str, str] = _build_palette("LIGHT")
DARK: dict[str, str] = _build_palette("DARK")


# ============================================================================
# Estado de tema (nível de módulo; persistência é responsabilidade do app)
# ============================================================================

_current_theme: str = "dark"


def set_theme(theme: str) -> None:
    ...


def get_theme() -> str:
    ...


def toggle_theme() -> str:
    ...


def colors() -> dict[str, str]:
    ...


def get_palette(dark_mode: bool = True) -> dict[str, str]:
    ...


def qpalette(palette: dict[str, str]) -> QPalette:
    ...


# ============================================================================
# QSS global (gerado a partir da paleta)
# ============================================================================


def get_stylesheet(theme: Optional[str] = None) -> str:
    ...


# Alias (Emissor usa stylesheet())
stylesheet = get_stylesheet


def _build_qss(c: dict) -> str:
    ...


# ============================================================================
# Helpers de botão
# ============================================================================


def make_button(
    text: str,
    role: str = "flat",
    parent=None,
) -> QPushButton:
    ...


class ThemeToggleButton(QPushButton):
    """Botão de alternância de tema (claro/escuro).

    Mostra ☾ no modo escuro e ☀ no modo claro (reflete o estado atual).
    Emite ``theme_toggled(bool dark_mode)`` — a aplicação conecta esse sinal
    para persistir a preferência e reaplicar palette/QSS.
    """

    theme_toggled = Signal(bool)

    def __init__(self, parent=None):
        ...

    def _toggle(self):
        ...

    def _update_icon(self):
        ...
```

## andaime/qt/top_bar.py
_symbols: 16_ 
```python
"""Barra superior genérica (andaime.qt).

Reproduz o leiaute exato da barra do Emissor: uma linha ``QHBoxLayout``
dividida em colunas pesadas:

- coluna 1 (``_COL_PATIENT``=5): botão de tema + busca
  (``SearchableComboBox`` injetável, data-source agnóstica);
- coluna 1.5 (peso 0 por padrão): ``mid_widget`` opcional (vazio);
- coluna 2 (``_COL_OPTIONS``=6): botões de ação (vazia por padrão);
- coluna 3 (``_COL_RIGHT``=3): widget à direita (título ou brasão), centralizado.

``col_weights`` aceita tanto uma tupla de 3 quanto de 4 elementos; se
fornecida com 3, a coluna 1.5 recebe peso 0 (colapsada).

A linha de status é **separada** (ver ``MainWindow`` / app), espelhando
o Emissor: um ``QLabel`` centralizado abaixo da barra, atualizado via
``set_status``. Esta classe não acopla lógica de paciente: quem usa
in jeta um ``search_fn``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QHBoxLayout,
    QSizePolicy,
    QFrame,
    QWidget,
)

from andaime.widgets import SearchableComboBox, static_search_fn
from andaime.qt.theme import ThemeToggleButton, make_button


# Pesos das colunas (espelham main.py do Emissor)
_COL_PATIENT = 5
_COL_OPTIONS = 6
_COL_RIGHT = 3


def coerce_actions(actions: list) -> list[QWidget]:
    ...


class TopBar(QFrame):
    """Barra superior: tema + busca | ações | widget à direita."""

    selection_changed = Signal(object)  # key emitido pelo SearchableComboBox
    theme_toggled = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        search_fn: Optional[Callable[[str], dict[str, str]]] = None,
        title: str = "",
        placeholder: str = "Buscar...",
        actions: Optional[list] = None,
        right_widget: Optional[QWidget] = None,
        left_widget: Optional[QWidget] = None,
        mid_widget: Optional[QWidget] = None,
        show_theme: bool = True,
        show_search: bool = True,
        search_max_width: Optional[int] = 440,
        col_weights: tuple[int, ...] = (
            _COL_PATIENT,
            0,
            _COL_OPTIONS,
            _COL_RIGHT,
        ),
        right_stretch: bool = False,
        bottom_border: bool = True,
    ) -> None:
        ...

    # ========== Construção ==========

    def _build_search(
        self,
        search_fn: Optional[Callable[[str], dict[str, str]]],
        placeholder: str,
    ) -> None:
        ...

    def _clear_search_slot(self) -> None:
        ...

    @staticmethod
    def _coerce_actions(actions: list) -> list[QWidget]:
        ...

    # ========== API ==========

    def add_action(self, action) -> None:
        ...

    def set_mid_widget(self, widget: QWidget) -> None:
        ...

    def set_search_fn(
        self, search_fn: Optional[Callable[[str], dict[str, str]]]
    ) -> None:
        ...

    def set_search_options(
        self, options: dict[str, str], placeholder: str = "Buscar..."
    ) -> None:
        ...

    def set_current(self, key: str, label: str) -> None:
        ...

    def set_current_by_key(self, key: str) -> None:
        ...

    def clear_search(self) -> None:
        ...

    def current_text(self) -> str:
        ...

    def set_right_widget(self, widget: QWidget) -> None:
        ...

    def set_title(self, title: str) -> None:
        ...
```

## andaime/config.py
_symbols: 13_ 
```python
"""
Generic configuration manager.

The app provides a dataclass with:
  - to_dict() -> dict
  - get_defaults() -> <dataclass>
  - __post_init__ validation
  - Optional: migrate_data(data: dict) -> dict for JSON migrations
"""

from __future__ import annotations

import json
from dataclasses import fields, replace
from typing import Any, Protocol, cast

from andaime.paths import get_config_path
from andaime.error_handler import ErrorHandler, ErrorLevel


class _ConfigSchema(Protocol):
    @classmethod
    ...

    ...


class ConfigManager:
    _instance: ConfigManager | None = None
    _config: Any = None
    _config_cls: type[_ConfigSchema] | None = None

    def __new__(cls) -> ConfigManager:
        ...

    @classmethod
    def init(cls, config_cls: type[_ConfigSchema]) -> None:
        ...

    def __init__(self) -> None:
        ...

    @classmethod
    def _load(cls) -> Any:
        ...

    @classmethod
    def _save_to_file(cls, config: Any) -> None:
        ...

    def get(self, key: str, default: Any = None) -> Any:
        ...

    def set(self, key: str, value: Any) -> bool:
        ...

    def get_all(self) -> Any:
        ...

    def reload(self) -> None:
        ...

    def reset_to_defaults(self) -> None:
        ...

    @classmethod
    def _reset(cls) -> None:
        ...
```

## andaime/qt/table.py
_symbols: 16_ 
```python
"""Table helpers for Qt — two approaches, same module.

**QTableWidget path** (simplest): use ``table_batch_populate`` to freeze
``ResizeToContents`` columns during batch ``setItem``, avoiding the
quadratic re-measure that occurs when inserting rows one at a time.

**QTableView + model path** (fastest, scales): use ``TableViewModel`` with
``ColumnSpec`` definitions. The model holds plain data objects (no per-cell
widget allocation); the view only paints visible rows. ``beginResetModel``
/``endResetModel`` batches updates atomically — no manual signal blocking.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
)


@contextmanager
def table_batch_populate(table: QTableWidget) -> Iterator[None]:
    ...


class NoElideDelegate(QStyledItemDelegate):
    """Draws cell text without ellipsis ("...") and adds a bottom separator.

    By default, Qt elides text that doesn't fit a cell. This delegate draws
    the text directly via ``painter.drawText``, which clips at the cell
    boundary without inserting "...". A thin separator line is drawn at the
    bottom of each row for visual separation when grid lines are hidden.
    """

    _TEXT_HMARGIN = 8

    def paint(self, painter, option, index):
        ...

    def sizeHint(self, option, index):
        ...


# ============================================================
# QTableView + model path
# ============================================================

_DEFAULT_ALIGN = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
_PADDING_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True)
class ColumnSpec:
    """Declarative column definition for ``TableViewModel``.

    Attributes:
        header: Header label text.
        getter: ``(row_data) -> display_text`` called per cell.
        alignment: Cell text alignment (default: centered).
        header_alignment: Header text alignment (default: centered).
        resize_mode: How the column resizes (default: Interactive).
        width: Fixed pixel width (used when ``resize_mode=Fixed``).
        foreground: Optional ``(row_data) -> QColor | None`` for per-row
            foreground color (e.g. status colors).
        padding: Extra horizontal padding (px per side) added to the cell's
            size hint. Useful for ``ResizeToContents`` columns that look
            too tight. Default: 0.
    """

    header: str
    getter: Callable[[Any], str]
    alignment: Qt.AlignmentFlag = _DEFAULT_ALIGN
    header_alignment: Qt.AlignmentFlag = _DEFAULT_ALIGN
    resize_mode: QHeaderView.ResizeMode = QHeaderView.ResizeMode.Interactive
    width: int | None = None
    foreground: Callable[[Any], QColor | None] | None = None
    padding: int = 0


class TableViewModel(QAbstractTableModel):
    """Generic table model backed by a list of plain data objects.

    Each row is a data object (dataclass, namedtuple, dict, etc.).
    ``ColumnSpec.getter`` extracts display text; ``ColumnSpec.foreground``
    optionally returns a per-row ``QColor``. The row's ID (for lookups
    via ``row_id`` / ``find_row_by_id``) comes from ``id_getter``.

    Call ``set_rows(rows)`` to replace all data atomically — the view
    updates in one pass via ``beginResetModel``/``endResetModel``, so no
    manual signal blocking or resize freezing is needed.
    """

    def __init__(
        self,
        columns: list[ColumnSpec],
        id_getter: Callable[[Any], Any] | None = None,
    ) -> None:
        ...

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        ...

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        ...

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        ...

    def data(
        self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        ...

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        ...

    def set_rows(self, rows: list[Any]) -> None:
        ...

    def row_id(self, row: int) -> Any:
        ...

    def find_row_by_id(self, id_value: Any) -> int | None:
        ...


def configure_table_view(
    view: QTableView, columns: list[ColumnSpec]
) -> None:
    ...
```

## andaime/qt/theme_model.py
_symbols: 10_ 
```python
"""Modelo de tema baseado em rampa + níveis (andaime).

Este módulo é a fonte lógica do tema independente da UI: deriva paletas a
partir da rampa (_RAMP), dos níveis (_LEVELS) e do mapeamento papel→nível
(_ROLE_LEVEL), e serializa/grava o bloco de tema em ``andaime.qt.theme``.

Não depende de widgets — só de ``andaime.qt.theme`` (dados) e de helpers de cor.

Ver também ``tools/theme_studio.py`` (editor) e ``tools/generate_brasao.py``.
"""

from __future__ import annotations

from pathlib import Path

from andaime.qt.theme import (
    LEVEL_COMMENTS,
    SEMANTIC_KEYS,
    SURFACE_KEYS,
)

# ---- Helpers de cor ----


def clamp(v: int) -> int:
    ...


def shift(hex_color: str, channel: int, delta: int) -> str:
    ...


def to_rgb(hex_color: str) -> list[int]:
    ...


def to_hex(rgb: list[float]) -> str:
    ...


def lerp(lo: str, hi: str, t: float) -> str:
    ...


def luminance(hex_color: str) -> float:
    ...


def contrast(a: str, b: str) -> float:
    ...


# ---- Modelo de rampa ----


def derive_palette(
    ramp: dict[str, list[str]],
    levels: dict[int, float],
    roles: dict[str, dict[str, int]],
    sem: dict[str, dict[str, str]],
    mode: str,
) -> dict[str, str]:
    ...


def theme_block(
    ramp: dict[str, list[str]],
    levels: dict[int, float],
    roles: dict[str, int],
    sem: dict[str, dict[str, str]],
) -> list[str]:
    ...


def write_theme(
    theme_file: Path,
    ramp: dict[str, list[str]],
    levels: dict[int, float],
    roles: dict[str, int],
    sem: dict[str, dict[str, str]],
) -> None:
    ...
```

## andaime/qt/dev_inspector.py
_symbols: 11_ 
```python
"""Inspetor de widgets para desenvolvimento (andaime.qt).

Permite apontar um widget e descobrir onde sua classe (de código da
aplicação) está definida — útil para "clicar no componente e ir ao código".

Gatilhos (apenas quando a var. de ambiente ``DEV`` está setada):

- ``F12`` (atalho de teclado), ou
- ``Ctrl+Shift+Click`` sobre um widget (fallback quando o window manager
  intercepta teclas de função).

O resultado aparece em um diálogo persistente, rolável e copiável com
``arquivo:linha`` da classe correspondente. **Não abre editor
automaticamente** — apenas mostra o caminho, evitando asociar/rodar o
arquivo por engano.

Uso::

    from andaime.qt.dev_inspector import enable_if_env
    enable_if_env(app)  # ativa com a var. de ambiente DEV=1
"""

from __future__ import annotations

import inspect
import os
import time
import traceback
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QObject
from PySide6.QtGui import QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

_QT_PACKAGES = ("PySide6", "PyQt6", "PyQt5")
_DEFAULT_SHORTCUT = "F12"
_CLICK_MODS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
_ENV_VAR = "DEV"
_DEBOUNCE_S = 0.2
_ATTR_KEEPALIVE = "_dev_inspector"


def _is_qt_class(cls: type) -> bool:
    ...


def _build_chain(
    widget: object,
) -> list[tuple[str, Optional[str], Optional[int], bool]]:
    ...


def _source_location(obj: object) -> tuple[Optional[str], Optional[int]]:
    ...


def _show_dialog(titulo: str, corpo: str, copiar: Optional[str] = None) -> None:
    ...


def _show_chain_dialog(
    widget: object,
    cadeia: list[tuple[str, Optional[str], Optional[int], bool]],
) -> None:
    ...


class _DevInspector(QObject):
    """Observa todos os eventos da QApplication para disparar a inspeção.

    Instala o filtro de eventos na própria QApplication: assim o gatilho
    funciona independentemente de qual widget (ou nenhum) tem o foco.
    """

    def __init__(self, app: QApplication, atalho: str = _DEFAULT_SHORTCUT) -> None:
        ...

    def eventFilter(self, _obj, event) -> bool:  # noqa: D401 - assinatura Qt
        ...

    def _inspecionar(self) -> None:
        ...


def install_dev_inspector(
    app: Optional[QApplication] = None, atalho: str = _DEFAULT_SHORTCUT
) -> _DevInspector:
    ...


def enable_if_env(
    app: Optional[QApplication] = None,
    var: str = _ENV_VAR,
    atalho: str = _DEFAULT_SHORTCUT,
) -> Optional[_DevInspector]:
    ...
```

## andaime/dates.py
_symbols: 10_ 
```python
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
        ...

    @staticmethod
    def _convert_pontos_to_dates(year: int, pontos_list: list[str]) -> set[date]:
        ...

    @staticmethod
    def get_holidays() -> set[date]:
        ...

    @classmethod
    def clear_holidays_cache(cls) -> None:
        ...

    @staticmethod
    def is_business_day(dt: date | datetime) -> bool:
        ...

    @staticmethod
    def skip_to_previous_business_day(dt: datetime | date) -> date:
        ...

    @staticmethod
    def skip_to_next_business_day(dt: datetime | date) -> date:
        ...


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
    ...


def format_date(dt: date, include_weekday: bool = False) -> str:
    ...
```

## andaime/app.py
_symbols: 14_ 
```python
"""Application bootstrap for PySide6 desktop apps."""

import sys
from pathlib import Path
from typing import Generic, TypeVar, TYPE_CHECKING

if TYPE_CHECKING:
    from andaime.qt.fonts import FontSpec

import andaime
from andaime.config import ConfigManager
from andaime.database import BaseDatabase
from andaime.error_handler import ErrorHandler, ErrorLevel

_D = TypeVar("_D", bound=BaseDatabase)


def _is_path_reachable(path: Path) -> bool:
    ...


def _warn_network_unavailable(path: Path) -> None:
    ...


class App(Generic[_D]):
    def __init__(
        self,
        app_name: str,
        app_folder: str,
        config_cls: type,
        db_cls: type[_D],
        root: Path | None = None,
        font: "FontSpec | None" = None,
    ) -> None:
        ...

    @property
    def font(self) -> "FontSpec | None":
        ...

    def _detect_root(self) -> Path:
        ...

    @property
    def root(self) -> Path:
        ...

    @property
    def db(self) -> _D:
        ...

    @property
    def config(self) -> ConfigManager:
        ...

    @property
    def app_name(self) -> str:
        ...

    @property
    def app_folder(self) -> str:
        ...

    def get_data_root(self) -> Path:
        ...

    def shutdown(self) -> None:
        ...

    @staticmethod
    def reset() -> None:
        ...
```

## andaime/pdf.py
_symbols: 10_ 
```python
"""Operações de PDF compartilhadas entre os apps (BAP, Emissor, ...).

Facade sobre as melhores bibliotecas por tarefa:

- estrutura (abrir, contar, dividir, mesclar, extrair página): ``pypdf``
- imagem -> PDF: ``img2pdf``
- rasterização: ``pypdfium2``
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Iterable, Union

from PySide6.QtGui import QImage

# PDFium não é thread-safe; chamadas concorrentes corrompem o bitmap.
_PDFIUM_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Estrutura (pypdf)
# ---------------------------------------------------------------------------


def open_pdf(src: Union[bytes, str, Path]):
    ...


def page_count(src: Union[bytes, str, Path]) -> int:
    ...


def split_pages(src: Union[bytes, str, Path]) -> list[bytes]:
    ...


def extract_page(src: Union[bytes, str, Path], page: int) -> bytes:
    ...


def merge_pdfs(conteudos: Iterable[Union[bytes, str, Path]], output_path: str) -> str:
    ...


# ---------------------------------------------------------------------------
# Imagem -> PDF (img2pdf)
# ---------------------------------------------------------------------------


def _clamped_layout_fun(imgwidthpx, imgheightpx, ndpi):
    ...


def image_to_pdf(source: Union[bytes, str, Path], filetype: str = "") -> bytes:
    ...


# ---------------------------------------------------------------------------
# Rasterização (pypdfium2)
# ---------------------------------------------------------------------------


def render_page_pil(
    src: Union[bytes, str, Path], page: int, scale: float = 2.0
):
    ...


def render_pages_pil(
    src: Union[bytes, str, Path], scale: float = 2.0
):
    ...


def render_page(
    src: Union[bytes, str, Path], page: int, scale: float = 2.0
) -> QImage:
    ...
```

## andaime/paths.py
_symbols: 3_ 
```python
"""
Path management utilities.
"""

from pathlib import Path

import andaime
from andaime.error_handler import ErrorHandler, ErrorLevel


def get_root_directory() -> Path:
    ...


def resolve_db_path(db_filename: str, create_dir: bool = True) -> str:
    ...


def get_config_path() -> Path:
    ...
```

## andaime/qt/fonts.py
_symbols: 8_ 
```python
"""Gerenciamento unificado de fontes para apps Qt.

Cada app define uma ``FontSpec`` que vive em ``andaime.App``. No momento de
inicializar a UI o main.py chama ``apply_font(qapp, app.font)``, que:

1. Carrega fontes empacotadas em ``<root>/fonts/`` (se ``bundled=True``).
2. Aplica a fonte padrão no ``QApplication``.
3. Configura a família usada pelo QSS global de ``andaime.qt.theme``.

Também expõe helpers de desenvolvedor para baixar fontes do Fontsource
(Google Fonts) e colocá-las no projeto.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import URLError

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from andaime import get_root_directory
from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel


@dataclass
class FontSpec:
    """Especificação de fonte para um app.

    Attributes:
        family: nome da família (ex: "IBM Plex Mono", "Geist").
        size: tamanho base em pontos.
        style_hint: hint usado pelo Qt quando a fonte não está disponível.
        bundled: se True, ``apply_font`` carrega arquivos de ``<root>/fonts/``
            antes de aplicar a família.
        fontsource_id: id opcional no Fontsource (ex: "ibm-plex-mono"). Se
            None, o download normaliza ``family`` (minúsculas, espaços -> '-').
    """

    family: str
    size: int = 11
    style_hint: QFont.StyleHint = QFont.StyleHint.SansSerif
    bundled: bool = True
    fontsource_id: str | None = None


def _fonts_dir() -> Path:
    ...


def load_bundled_fonts(fonts_dir: Path | None = None) -> list[str]:
    ...


def apply_font(qapp: QApplication, font: FontSpec | None) -> None:
    ...


# -----------------------------------------------------------------------------
# Helpers de desenvolvimento (download de fontes)
# -----------------------------------------------------------------------------


FONTSOURCE_API = "https://api.fontsource.org/v1/fonts"
FONTSOURCE_CDN = "https://cdn.jsdelivr.net/fontsource/fonts"


def _fontsource_id(family: str) -> str:
    ...


def download_font(
    family_id: str,
    output_dir: Path,
    subsets: Iterable[str] = ("latin",),
    weights: Iterable[str] = ("400", "700"),
    styles: Iterable[str] = ("normal", "italic"),
) -> None:
    ...


def download_bundled_font(
    font: FontSpec,
    output_dir: Path | None = None,
    subsets: Iterable[str] = ("latin",),
    weights: Iterable[str] = ("400", "700"),
    styles: Iterable[str] = ("normal", "italic"),
) -> None:
    ...


def download_font_by_name(
    family: str,
    output_dir: Path,
    subsets: Iterable[str] = ("latin",),
    weights: Iterable[str] = ("400", "700"),
    styles: Iterable[str] = ("normal", "italic"),
    fontsource_id: str | None = None,
) -> None:
    ...
```

## andaime/qt/shortcuts.py
_symbols: 8_ 
```python
"""Gerenciador de atalhos de teclado — andaime.qt.

Registra QShortcuts com variantes Ctrl+Shift e revela dicas nos widgets
ao segurar Ctrl+Shift (peek). Reutilizável entre apps (Emissor, RAC, BAP).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLineEdit, QPushButton, QWidget


class ShortcutManager(QObject):
    """
    Registro de atalhos com dicas visuais (peek via Ctrl+Shift).

    Cada atalho registrado com ``bind`` cria automaticamente uma variante
    Ctrl+Shift+<tecla>. Segurar Ctrl+Shift revela a dica ``(Ctrl+<tecla>)``
    ao lado do texto do widget associado.

    Attributes:
        _window: Janela que recebe os atalhos e o event filter
        _hints: Lista de (widget, sufixo) para exibir/ocultar dicas
        _peek_active: Estado atual do peek
        _peek_callbacks: Callbacks notificados quando o peek muda de estado
    """

    def __init__(self, window: QWidget) -> None:
        ...

    def bind(
        self,
        key: str,
        handler: Callable[[], None],
        hint_widget: QWidget | None = None,
    ) -> None:
        ...

    def register_hint(self, widget: QWidget, key: str) -> None:
        ...

    def on_peek(self, callback: Callable[[bool], None]) -> None:
        ...

    def reset_peek(self) -> None:
        ...

    def eventFilter(self, obj, event):
        ...

    def _set_peek(self, show: bool) -> None:
        ...
```

## andaime/text.py
_symbols: 5_ 
```python
"""
Text normalization utilities.
"""

import unicodedata


def _strip_accents(text: str) -> str:
    ...


def normalize_text(text: str) -> str:
    ...


def to_upper_normalized(text: str) -> str:
    ...


def scored_search_dict(
    results: dict[str, str],
    query: str,
    limit: int = 0,
) -> dict[str, str]:
    ...


def scored_search(
    results: list[dict],
    query: str,
    field: str,
    limit: int = 0,
) -> list[dict]:
    ...
```

## andaime/qt/toggle_group.py
_symbols: 6_ 
```python
"""Grupo de botões tipo "toggle" (controle segmentado) — andaime.qt.

Conjunto de botões onde exatamente um está ativo (comportamento de
"radio"). O botão ativo usa o papel ``flat-fill`` (preenchido); os
demais usam o estilo plano (``flat``). Os segmentos são dispostos em
uma única linha, colados (espaçamento 0) e com divisores, formando um
controle segmentado —— ( | | ). O visual de borda/divisores vem do QSS
global (``ToggleGroup``), então reage ao tema automaticamente.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from andaime.qt.theme import make_button


class ToggleGroup(QWidget):
    """Controle segmentado: uma opção ativa por vez."""

    selection_changed = Signal(str)  # chave da opção ativa

    def __init__(
        self,
        parent: QWidget | None = None,
        options: Optional[list[tuple[str, str]]] = None,
        default: Optional[str] = None,
        allow_deselect: bool = False,
    ) -> None:
        ...

    def _on_click(self, key: str) -> None:
        ...

    def _apply(self) -> None:
        ...

    def set_selected(self, key: Optional[str], emit: bool = False) -> None:
        ...

    def selected(self) -> Optional[str]:
        ...
```

## andaime/qt/splash.py
_symbols: 6_ 
```python
"""Splash screen shown during app startup."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

_BG = QColor("#1e1e2e")
_FG = QColor("#cdd6f4")
_SUB = QColor("#7f849c")
_ACCENT = QColor("#89b4fa")

_W, _H = 480, 280


class SplashScreen:
    """Branded splash screen shown while the app initializes.

    Usage::

        qapp = QApplication(sys.argv)
        splash = SplashScreen("RAC", icon_path)
        splash.show()
        # ... heavy initialization ...
        window.show()
        splash.finish(window)
    """

    def __init__(
        self,
        app_name: str,
        icon_path: Path | None = None,
    ) -> None:
        ...

    def show(self) -> None:
        ...

    def finish(self, window: "QWidget") -> None:
        ...

    def close(self) -> None:
        ...

    # ------------------------------------------------------------------
    def _make_pixmap(self) -> QPixmap:
        ...
```

## andaime/qt/db_runner.py
_symbols: 5_ 
```python
"""
DbAsyncRunner — executa ops num worker e devolve o resultado na thread Qt principal.

A UI chama ``runner.run(worker.submit_fn, args..., on_done=...)``: a operação
roda na thread dedicada do DatabaseWorker, e ``on_done(result)`` é invocada na
thread principal do Qt (segura para tocar widgets). O marshal cross-thread é
feito por um Signal Qt (emitir um signal de outra thread é seguro — o Qt
enfileira a chamada para a thread do receptor).
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from andaime.db_worker import DatabaseWorker


class DbAsyncRunner(QObject):
    """
    Ponte entre o DatabaseWorker (stdlib) e a thread principal do Qt.

    Fluxo: worker executa fn -> add_done_callback emite _dispatch (signal) ->
    Qt entrega na main thread -> slot roda o thunk que chama on_done/on_error.
    """

    # Carrega um thunk () -> None para ser executado na thread principal.
    _dispatch = Signal(object)

    def __init__(self, worker: DatabaseWorker, parent: QObject | None = None) -> None:
        ...

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_done: Callable[[Any], None],
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        ...

    @staticmethod
    def _run_thunk(thunk: Callable[[], None]) -> None:
        ...


def run_or_sync(
    runner: DbAsyncRunner | None,
    fn: Callable[..., Any],
    *,
    on_done: Callable[[Any], None],
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    ...
```

## andaime/db_worker.py
_symbols: 5_ 
```python
"""
Database worker — executa operações de banco numa única thread dedicada.

O ``BaseDatabase`` já é thread-safe (``RLock`` + ``check_same_thread=False``),
então este worker chama os métodos do db diretamente. As operações são
serializadas em ordem FIFO (``ThreadPoolExecutor`` com 1 worker), garantindo
que duas chamadas nunca concorram na conexão. Os resultados chegam via
``concurrent.futures.Future``; a camada de UI faz o marshal de volta para a
sua própria thread (Qt: signal; Tk: ``after``).

Princípio: uma única thread de DB → sem locking extra, sem corrupção de
conexão, e a UI nunca bloqueia numa chamada demorada.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

_R = TypeVar("_R")


class DatabaseWorker:
    """
    Executa operações de banco numa thread dedicada e serializada.

    Attributes:
        db: A instância do banco (tipicamente um BaseDatabase).
    """

    def __init__(self, db: Any) -> None:
        ...

    @property
    def db(self) -> Any:
        ...

    def submit(self, fn: Callable[..., _R], *args: Any, **kwargs: Any) -> Future[_R]:
        ...

    def shutdown(self, wait: bool = True) -> None:
        ...
```

## andaime/qt/bottom_bar.py
_symbols: 5_ 
```python
"""Barra inferior genérica (andaime.qt).

Espelha a ``TopBar``: mesmo visual (``panel-footer``), 52px, e quatro
colunas horizontais ponderadas por ``col_weights``:

- col1 (esquerda): ``left_widget``
- col2 (status): ``status_widget``
- col3 (centro): ``center_widget`` + ``actions``
- col4 (direita): ``right_widget`` + ``right_actions``

Usada pelo SS-54 com o ``RemessaLabel`` à esquerda, o ``StatusLabel``
em seguida, e o botão "Salvar" à direita.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QFrame, QPushButton, QWidget

from andaime.qt.top_bar import coerce_actions

_COL_LEFT = 2
_COL_STATUS = 2
_COL_CENTER = 8
_COL_RIGHT = 2


class BottomBar(QFrame):
    """Barra inferior: quatro colunas (esquerda / status / centro / direita)."""

    def __init__(
        self,
        parent: QFrame | None = None,
        actions: Optional[list] = None,
        left_widget: Optional[QWidget] = None,
        status_widget: Optional[QWidget] = None,
        center_widget: Optional[QWidget] = None,
        right_widget: Optional[QWidget] = None,
        right_actions: Optional[list] = None,
        col_weights: tuple[int, int, int, int] = (
            _COL_LEFT,
            _COL_STATUS,
            _COL_CENTER,
            _COL_RIGHT,
        ),
    ) -> None:
        ...

    def add_action(self, action) -> None:
        ...

    def action_button(self, text: str) -> QPushButton | None:
        ...

    def add_right_widget(self, widget: QWidget) -> None:
        ...
```

## andaime/__init__.py
_symbols: 4_ 
```python
"""
andaime — shared toolkit for PySide6 desktop apps
"""

import sys
from pathlib import Path

_app_name: str = ""
_app_folder: str = ""
_app_root: Path | None = None


def init(app_name: str, app_folder: str, root: Path) -> None:
    ...


def get_app_name() -> str:
    ...


def get_app_folder() -> str:
    ...


def get_root_directory() -> Path:
    ...


from andaime.app import App
from andaime.qt.splash import SplashScreen
```

## andaime/qt/status_line.py
_symbols: 4_ 
```python
"""Linha de status transiente (andaime.qt).

``StatusLine`` é um ``QLabel`` centralizado, com cor opcional e — quando um
caminho é informado — sublinhado e clicável, abrindo o explorador de
arquivos no caminho ao ser clicado.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from andaime.qt.fs import reveal_path
from andaime.qt.theme import colors


class StatusLine(QLabel):
    """Linha de status transiente (texto centralizado, cor/acao opcional).

    Quando ``set_status`` recebe ``path``, o texto fica sublinhado e o cursor
    vira "mão"; um clique emite ``reveal_path(path)``.
    """

    def __init__(self, parent=None):
        ...

    def set_status(
        self,
        text: str,
        color: str | None = None,
        path: str | None = None,
    ) -> None:
        ...

    def mouseReleaseEvent(self, event):
        ...
```

## andaime/shutdown.py
_symbols: 4_ 
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application Shutdown Manager — registra e executa handlers de limpeza no exit.

Registra callbacks (ex.: ``db.close``) via :func:`register_cleanup` e os
conecta a ``atexit`` + SIGINT/SIGTERM via :func:`setup_shutdown_handlers`.
Os handlers rodam após o loop de eventos, fora da thread de UI.
"""

import atexit
import signal
import sys
from contextlib import suppress
from typing import Any, Callable, List, Tuple, Optional

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

# Type alias for cleanup handlers
Handler = Callable[[], None]

# Global registry of cleanup handlers
_cleanup_handlers: List[Tuple[Handler, str]] = []


def register_cleanup(handler: Handler, name: Optional[str] = None) -> None:
    ...


def _run_cleanup_handlers() -> None:
    ...


def setup_shutdown_handlers() -> None:
    ...


def _signal_handler(signum: int, _frame: Any) -> None:
    ...
```

## andaime/qt/fs.py
_symbols: 2_ 
```python
"""Utilitários de sistema de arquivos para a interface Qt (andaime)."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def reveal_path(path: str) -> None:
    ...


def relative_path(root: str | Path | None, path: str | Path) -> str:
    ...

```

## andaime/brasao.py
_symbols: 2_ 
```python
"""Helpers de renderização do brasão (andaime).

Renderiza a silhueta do SVG do brasão e a recolorida conforme a tinta do tema,
preservando o alpha. Compartilhado entre ``tools/generate_brasao.py`` (gera os
PNG estáticos) e o editor de tema (pré-visualização ao vivo).

Usage:
    from andaime.brasao import render_brasao_silhouette, recolor_brasao
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


def render_brasao_silhouette(
    svg_path: str | Path,
    height: int,
    supersample: int = 1,
) -> QPixmap:
    ...


def recolor_brasao(silhouette: QPixmap, ink: str) -> QPixmap:
    ...
```

## andaime/win32.py
_symbols: 1_ 
```python
"""Windows taskbar identity helpers."""

from __future__ import annotations

import sys
from pathlib import Path


def register_taskbar_identity(
    app_id: str, display_name: str, icon_path: Path | str | None = None
) -> None:
    ...
```

<!-- 28/28 files, ~15051 tokens -->