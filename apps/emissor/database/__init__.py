#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Database module — acesso unificado e migração."""

from .emissor_db import EmissorDatabase
from .models import Patient

__all__ = [
    "EmissorDatabase",
    "Patient",
]
