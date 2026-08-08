#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Exceções específicas do módulo Olostech."""


class OlostechError(Exception):
    """Erro genérico durante operação Olostech."""


class OlostechAuthError(OlostechError):
    """Falha na autenticação/login Olostech."""


class OlostechDispensingError(OlostechError):
    """Falha durante dispensação no Olostech."""


class OlostechConfigError(OlostechError):
    """Configuração Olostech incompleta ou inválida."""
