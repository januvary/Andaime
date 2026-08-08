#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pacote Olostech — automação de dispensação integrada ao Emissor."""

from emissor.olostech.auth import OlostechAuth, build_machine_auth_params
from emissor.olostech.dispensing import Dispensing
from emissor.olostech.exceptions import OlostechError, OlostechAuthError
from emissor.olostech.item_mapping import load_mapping
from emissor.olostech.patient_attendance import PatientAttendance

__all__ = [
    "OlostechAuth",
    "build_machine_auth_params",
    "Dispensing",
    "OlostechError",
    "OlostechAuthError",
    "load_mapping",
    "PatientAttendance",
]
