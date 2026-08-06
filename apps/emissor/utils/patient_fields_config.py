#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Patient Fields Configuration Module

Central configuration for all patient data fields.
This allows adding new fields without modifying multiple files.
"""

import operator

from typing import Dict, List, Optional, Any

# Field type constants
TYPE_TEXT = "text"
TYPE_NUMBER = "number"
TYPE_DATE = "date"
TYPE_ENUM = "enum"

# GUI widget constants
WIDGET_ENTRY = "entry"
WIDGET_MASKED = "masked"
WIDGET_RADIO = "radio"
WIDGET_COMBOBOX = "combobox"
WIDGET_TEXTBOX = "textbox"
WIDGET_SPECIAL = "special"  # Custom handler


def validate_none(value: Any) -> tuple[bool, str]:
    """Default validator - accepts any non-empty value"""
    return True, ""


def transform_none(value: str) -> Any:
    """Default transformer - returns value as-is"""
    return value


def transform_uppercase(value: str) -> Any:
    """Transform value to uppercase"""
    return value.upper() if value else value


# Configuration for all patient data fields
# Keys are database column names
PATIENT_DATA_FIELDS: Dict[str, Dict[str, Any]] = {
    # Processo fields (handled specially - supports multiple instances)
    "processo_n": {
        "type": TYPE_TEXT,
        "label": "Processo Nº",
        "gui_widget": WIDGET_MASKED,
        "mask": "9999999-99.9999.9.99.9999",  # Processo number mask (use '9' for digits)
        "required": False,
        "pdf_display": True,
        "multiple": True,  # Can have multiple instances (processo_2_n, etc.)
        "max_instances": 10,
        "section": "patient",  # Seção PatientSection
        "validation": validate_none,
        "transform": transform_none,
        "ui_metadata": {
            "placeholder": "0000000-00.0000.0.00.0000",
            "order": 3,  # Inserted between nome (order 1) and profissional (order 4)
        },
    },
    # Matrícula field
    "matricula": {
        "type": TYPE_TEXT,
        "label": "Matrícula",
        "gui_widget": WIDGET_ENTRY,
        "required": False,
        "pdf_display": True,
        "section": "patient",  # Seção PatientSection
        "validation": validate_none,
        "transform": transform_none,
        "ui_metadata": {
            "placeholder": "",
            "order": 2,
        },
    },
    # Telefone field (phone number)
    "telefone": {
        "type": TYPE_TEXT,
        "label": "Telefone",
        "gui_widget": WIDGET_MASKED,
        "mask": "(99) 99999-9999",  # Brazilian phone format
        "required": False,
        "pdf_display": True,
        "section": "patient",  # Seção PatientSection
        "validation": validate_none,
        "transform": transform_none,
        "ui_metadata": {
            "placeholder": "(00) 00000-0000",
            "order": 2.5,  # Between matricula (2) and processo_n (3)
        },
    },
    # Tipo field (radio buttons)
    "tipo": {
        "type": TYPE_ENUM,
        "label": "Tipo",
        "gui_widget": WIDGET_RADIO,
        "options": ["revezado", "municipal", "municipal_e_revezado", "insulina"],
        "required": False,
        "pdf_display": True,
        "section": "options",  # Seção OptionsSection
        "validation": validate_none,
        "transform": transform_none,
    },
    # Periodicidade field (numeric)
    "periodicidade": {
        "type": TYPE_NUMBER,
        "label": "Periodicidade",
        "gui_widget": WIDGET_ENTRY,
        "required": False,
        "pdf_display": False,  # Not displayed in PDF
        "section": "options",  # Seção OptionsSection
        "validation": validate_none,
        "transform": lambda x: int(x) if x.isdigit() else None,
    },
    # Última receita field (date)
    "ultima_receita": {
        "type": TYPE_DATE,
        "label": "Última receita",
        "gui_widget": WIDGET_MASKED,
        "mask": "99/99/9999",  # Use '9' for optional digits
        "required": False,
        "pdf_display": False,  # Used for calculation, not display
        "section": "options",  # Seção OptionsSection
        "validation": validate_none,
        "transform": transform_none,
    },
    # Tipo de receita field (radio buttons)
    "tipo_receita": {
        "type": TYPE_ENUM,
        "label": "Tipo de receita",
        "gui_widget": WIDGET_RADIO,
        "options": ["tipo_a", "tipo_b", "tipo_c"],
        "required": False,
        "pdf_display": False,  # Used for validity calculation
        "section": "options",  # Seção OptionsSection
        "validation": validate_none,
        "transform": transform_none,
    },
    # Observações field (multiline textbox)
    "observacoes": {
        "type": TYPE_TEXT,
        "label": "Observações",
        "gui_widget": WIDGET_TEXTBOX,
        "textbox_lines": 5,
        "required": False,
        "pdf_display": True,
        "section": "options",  # Seção OptionsSection
        "validation": validate_none,
        "transform": transform_none,
    },
}

# Fields in the base pacientes table (not dynamically generated)
BASE_PATIENT_FIELDS = ["id", "nome"]

# Fields that require special handling (not auto-generated)
SPECIAL_FIELDS = {
    "atendido_por": {
        "type": TYPE_TEXT,
        "label": "Atendido por",
        "gui_widget": WIDGET_ENTRY,
        "required": False,
        "pdf_display": True,
        "validation": validate_none,
        "transform": transform_none,
    },
    "profissional_id": {
        "type": TYPE_TEXT,
        "label": "Profissional",
        "gui_widget": WIDGET_SPECIAL,
        "required": False,
        "pdf_display": True,
        "validation": validate_none,
        "transform": transform_none,
    },
}


def get_field_config(field_name: str) -> Optional[Dict[str, Any]]:
    """
    Get configuration for a specific field.

    Args:
        field_name: Name of the field

    Returns:
        Field configuration dict or None if not found
    """
    # Check main patient data fields
    if field_name in PATIENT_DATA_FIELDS:
        return PATIENT_DATA_FIELDS[field_name]

    # Check special fields
    if field_name in SPECIAL_FIELDS:
        return SPECIAL_FIELDS[field_name]

    return None


def get_all_patient_data_fields() -> List[str]:
    """
    Get list of all patient data field names.

    Returns:
        List of field names that should be in the pacientes table
    """
    return list(PATIENT_DATA_FIELDS.keys())


def is_multiple_instance_field(field_name: str) -> bool:
    """
    Check if a field supports multiple instances (like processo_n).

    Args:
        field_name: Name of the field

    Returns:
        True if field supports multiple instances
    """
    config = get_field_config(field_name)
    return config.get("multiple", False) if config else False


def get_fields_for_section(section_name: str) -> List[str]:
    """
    Obtém lista de campos para uma seção específica, ordenados por ui_metadata.order.

    Args:
        section_name: 'patient', 'options', etc.

    Returns:
        Lista de nomes de campos ordenados por ordem de exibição
    """
    fields = [
        (field_name, config.get("ui_metadata", {}).get("order", 999))
        for field_name, config in PATIENT_DATA_FIELDS.items()
        if config.get("section") == section_name
    ]
    fields.sort(key=operator.itemgetter(1))
    return [field_name for field_name, _ in fields]
