#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared constants for RAC PySide6 app
"""

from rac.constants import (  # noqa: F401
    TIPO_LABELS,
    TIPO_TITLES,
    TIPOS_WITH_MONTHS,
    TIPO_HEX,
)

TIPO_SYMBOLS: dict[str, str] = {
    "entrada": "arrow_upward",
    "renovacao": "autorenew",
    "retirada": "arrow_downward",
    "urgente": "frame_source",
    "medcasa": "home",
}

RIGHT_BUTTON_SYMBOLS: dict[str, str] = {
    "preview": "view_list",
    "export": "file_export",
    "medicamentos": "pill",
    "pacientes": "person",
    "stats": "leaderboard",
}

SHORTCUT_LABELS: dict[str, tuple[str, str]] = {
    "save": ("Ctrl+S", "Salvar"),
    "export": ("Ctrl+E", "Exportar Listas"),
    "back": ("Esc", "Voltar"),
    "preview": ("Ctrl+G", "Visualizar Malote"),
    "medicamentos": ("Ctrl+M", "Medicamentos"),
    "pacientes": ("Ctrl+P", "Pacientes"),
    "stats": ("Ctrl+Y", "Estatisticas"),
    "add_item": ("Ctrl+F", "+ Adicionar Item"),
    "toggle_docs": ("Ctrl+W", "Esperando documentos"),
    "toggle_stay": ("Ctrl+Q", "Ficar nesta tela"),
}

TIPO_SHORTCUT_KEYS: dict[str, str] = {
    "entrada": "Ctrl+1",
    "renovacao": "Ctrl+2",
    "retirada": "Ctrl+3",
    "urgente": "Ctrl+4",
    "medcasa": "Ctrl+5",
}
