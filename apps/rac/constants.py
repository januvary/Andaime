#!/usr/bin/env python3
# -*- coding: utf-8 -*-

TIPO_LABELS = {
    "entrada": "Entrada",
    "renovacao": "Renovação",
    "retirada": "Retirada",
    "urgente": "Resolver na hora",
    "medcasa": "Remédio em Casa",
}

TIPO_TITLES = {
    "entrada": "ENTRADAS",
    "renovacao": "RENOVAÇÕES",
    "retirada": "RETIRADAS",
    "urgente": "RESOLVER NA HORA",
    "medcasa": "REMÉDIO EM CASA",
}

TIPOS_WITH_MONTHS = frozenset({"retirada", "renovacao"})

TIPO_HEX = {
    "entrada": "#10B981",
    "renovacao": "#3B82F6",
    "retirada": "#D97706",
    "urgente": "#EF4444",
    "medcasa": "#06B6D4",
}
