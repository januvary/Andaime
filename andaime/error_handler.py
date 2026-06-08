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


class ErrorHandler:
    _logger: logging.Logger | None = None
    _show_dialog_callback: Callable[[str, str, ErrorLevel], None] | None = None
    _initialized: bool = False

    @staticmethod
    def _ctx(context: Any) -> str:
        if isinstance(context, str):
            return context
        return getattr(context, "value", str(context))

    def __init__(self) -> None:
        if not self._initialized and self._logger is None:
            self._logger = logging.getLogger("andaime-fallback")
            self._logger.setLevel(logging.DEBUG)
            if not self._logger.handlers:
                handler = logging.StreamHandler(sys.stdout)
                handler.setLevel(logging.INFO)
                handler.setFormatter(logging.Formatter(
                    "[%(asctime)s] [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                ))
                self._logger.addHandler(handler)

    @classmethod
    def init(cls, app_name: str, root: Path | None = None) -> None:
        if cls._initialized:
            return
        cls._logger = logging.getLogger(app_name)
        cls._logger.setLevel(logging.DEBUG)

        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        cls._logger.addHandler(console_handler)

        if root is not None:
            with suppress(Exception):
                log_dir = root / "data"
                log_dir.mkdir(parents=True, exist_ok=True)
                log_file = log_dir / f"{app_name.lower()}.log"

                file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                cls._logger.addHandler(file_handler)

        cls._initialized = True

    @staticmethod
    def handle_error(
        error: Exception,
        context: str = "Unknown",
        level: ErrorLevel = ErrorLevel.ERROR,
        show_dialog: bool = True,
        recovery_hint: str | None = None,
    ) -> str:
        handler = ErrorHandler()

        error_msg = f"[{context}] {type(error).__name__}: {error}"

        if handler._logger:
            log_func = {
                ErrorLevel.INFO: handler._logger.info,
                ErrorLevel.WARNING: handler._logger.warning,
                ErrorLevel.ERROR: handler._logger.error,
                ErrorLevel.CRITICAL: handler._logger.critical,
            }.get(level, handler._logger.error)

            log_func(error_msg)

            if level in (ErrorLevel.ERROR, ErrorLevel.CRITICAL):
                handler._logger.debug(traceback.format_exc())

        if show_dialog and ErrorHandler._show_dialog_callback:
            dialog_msg = error_msg
            if recovery_hint:
                dialog_msg += f"\n\nSugestão: {recovery_hint}"

            with suppress(Exception):
                ErrorHandler._show_dialog_callback(
                    f"Erro de {context}", dialog_msg, level
                )

        return error_msg

    @staticmethod
    def log(
        message: str,
        level: ErrorLevel = ErrorLevel.INFO,
        context: str = "Unknown",
    ) -> None:
        handler = ErrorHandler()
        if handler._logger:
            with suppress(Exception):
                formatted_msg = f"[{context}] {message}"

                log_func = {
                    ErrorLevel.DEBUG: handler._logger.debug,
                    ErrorLevel.INFO: handler._logger.info,
                    ErrorLevel.WARNING: handler._logger.warning,
                    ErrorLevel.ERROR: handler._logger.error,
                    ErrorLevel.CRITICAL: handler._logger.critical,
                }.get(level, handler._logger.info)

                log_func(formatted_msg)

    @staticmethod
    def handle_file_error(
        error: Exception,
        file_path: str,
        operation: str = "access",
        show_dialog: bool = True,
    ) -> str:
        recovery_hints = {
            "read": "Verifique se o arquivo existe e você tem permissão de leitura.",
            "write": "Verifique se o diretório existe e você tem permissão de escrita.",
            "delete": "Verifique se o arquivo existe e você tem permissão de deleção.",
            "create": "Verifique se o diretório pai existe e você tem permissão.",
            "open": "Verifique se o arquivo existe e está acessível.",
            "move": "Verifique se origem e destino existem e são acessíveis.",
        }

        hint = recovery_hints.get(operation, "Verifique se o caminho está correto.")

        return ErrorHandler.handle_error(
            error,
            context="File I/O",
            level=ErrorLevel.ERROR,
            recovery_hint=hint + f"\n\nCaminho: {file_path}",
            show_dialog=show_dialog,
        )

    @staticmethod
    def handle_validation_error(
        error: Exception,
        field: str,
        recovery_hint: str | None = None,
        show_dialog: bool = True,
    ) -> str:
        if recovery_hint is None:
            recovery_hint = f"Verifique o campo: {field}"

        return ErrorHandler.handle_error(
            error,
            context="Validation",
            level=ErrorLevel.WARNING,
            recovery_hint=recovery_hint,
            show_dialog=show_dialog,
        )

    @staticmethod
    def handle_database_error(
        error: Exception,
        operation: str = "database operation",
        recovery_hint: str | None = None,
        show_dialog: bool = True,
    ) -> str:
        if recovery_hint is None:
            recovery_hint = (
                "Se o problema persistir, tente:\n"
                "1. Fechar e reabrir a aplicação\n"
                "2. Verificar espaço em disco\n"
                "3. Contatar suporte"
            )

        return ErrorHandler.handle_error(
            error,
            context="Database",
            level=ErrorLevel.ERROR,
            recovery_hint=recovery_hint,
            show_dialog=show_dialog,
        )

    @staticmethod
    def safe_execute(
        func: Callable[..., Any],
        *args: Any,
        operation_name: str = "operation",
        on_error: Callable[[Exception], None] | None = None,
        context: str = "Unknown",
        **kwargs: Any,
    ) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            ErrorHandler.handle_error(
                e,
                context=context,
                recovery_hint=f"Falha ao executar {operation_name}",
            )
            if on_error:
                with suppress(Exception):
                    on_error(e)
            return None

    @staticmethod
    def suppress_and_log(
        func: Callable,
        *args: Any,
        operation_name: str = "operation",
        context: str = "Unknown",
        **kwargs: Any,
    ) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            ErrorHandler.log(
                f"Suppressed error in {operation_name}: {e}",
                level=ErrorLevel.WARNING,
                context=context,
            )
            return None

    @staticmethod
    def _setup_logging() -> None:
        if ErrorHandler._logger is None:
            ErrorHandler._logger = logging.getLogger("andaime-fallback")
            ErrorHandler._logger.setLevel(logging.DEBUG)
            if not ErrorHandler._logger.handlers:
                handler = logging.StreamHandler(sys.stdout)
                handler.setLevel(logging.INFO)
                handler.setFormatter(logging.Formatter(
                    "[%(asctime)s] [%(levelname)s] %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                ))
                ErrorHandler._logger.addHandler(handler)

    @staticmethod
    def get_logger() -> logging.Logger:
        handler = ErrorHandler()
        if handler._logger is None:
            handler._setup_logging()
        return handler._logger  # type: ignore[return-value]
