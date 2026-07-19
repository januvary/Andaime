#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilitários de arquivo
Funções UI-agnósticas para abertura de arquivos e operações comuns.
"""

from __future__ import annotations

import os
import subprocess
import sys

from andaime.error_handler import ErrorHandler


def open_file(file_path: str) -> None:
    """
    Abre arquivo com aplicativo padrão (cross-platform).

    Valida o caminho antes de abrir para evitar problemas de segurança.
    Levanta FileNotFoundError se o arquivo não existir.

    Args:
        file_path: Caminho do arquivo a abrir.

    Raises:
        FileNotFoundError: Se o caminho for inválido ou o arquivo não existir.
        OSError: Se a abertura falhar.
    """
    from emissor.utils.security import validate_file_path

    try:
        safe_path = validate_file_path(file_path)
    except ValueError as e:
        ErrorHandler.handle_file_error(
            FileNotFoundError(f"Arquivo inválido ou não encontrado: {e}"),
            file_path=file_path,
            operation="validate",
        )
        raise FileNotFoundError(f"Arquivo inválido ou não encontrado: {e}")

    try:
        if sys.platform == "win32":
            os.startfile(str(safe_path))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(safe_path)])
        else:
            subprocess.Popen(["xdg-open", str(safe_path)])
    except Exception as e:
        ErrorHandler.handle_file_error(e, file_path=file_path, operation="open")
        raise OSError(f"Falha ao abrir arquivo: {e}")
