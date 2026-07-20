#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Database Module - Módulo de banco de dados do Emissor

Fornece acesso ao banco de dados unificado e funcionalidades de migração.
"""

from .emissor_db import EmissorDatabase
from .migrations import DatabaseMigrator
from .definitive_catalog import DEFINITIVE_CATALOG
from .models import Patient

__all__ = [
    "EmissorDatabase",
    "DatabaseMigrator",
    "DEFINITIVE_CATALOG",
    "Patient",
]
