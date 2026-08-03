#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilidades do Emissor - módulo de utilitários compartilhados.

NOTA: mantém try/except para imports porque pode ser importado tanto como
pacote (``from emissor.utils import ...``) quanto com src em sys.path
(``from utils import ...``). Esta é uma EXCEPTION à regra de imports
absolutos; todos os outros módulos usam imports absolutos.
"""

try:
    from .paths import (
        resolve_app_exe,
    )
    from .config import AppConfig
    from andaime.config import ConfigManager
    from andaime.paths import get_root_directory, resolve_db_path, get_config_path
    from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
    from andaime.database import BaseDatabase
    from .security import validate_file_path, validate_directory_path, sanitize_filename
    from .date_utils import DateCalculator
    from .validators import PatientDataValidator
    from .patient_fields_config import (
        get_all_patient_data_fields,
        get_fields_for_section,
        get_field_config,
    )
except ImportError:
    from utils.paths import resolve_app_exe  # type: ignore[import-not-found, no-redef]
    from utils.config import AppConfig  # type: ignore[import-not-found, no-redef]
    from andaime.config import ConfigManager
    from andaime.paths import get_root_directory, resolve_db_path, get_config_path
    from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel
    from andaime.database import BaseDatabase
    from utils.security import (  # type: ignore[import-not-found, no-redef]
        validate_file_path,
        validate_directory_path,
        sanitize_filename,
    )
    from utils.date_utils import DateCalculator  # type: ignore[import-not-found, no-redef]
    from utils.validators import PatientDataValidator  # type: ignore[import-not-found, no-redef]
    from utils.patient_fields_config import get_all_patient_data_fields, get_fields_for_section, get_field_config  # type: ignore[import-not-found, no-redef]

__all__ = [
    "get_root_directory",
    "resolve_db_path",
    "get_config_path",
    "resolve_app_exe",
    "AppConfig",
    "ConfigManager",
    "ErrorHandler",
    "ErrorLevel",
    "ErrorContext",
    "BaseDatabase",
    "validate_file_path",
    "validate_directory_path",
    "sanitize_filename",
    "DateCalculator",
    "PatientDataValidator",
    "get_all_patient_data_fields",
    "get_fields_for_section",
    "get_field_config",
]
