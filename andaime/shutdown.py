#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application Shutdown Manager — registra e executa handlers de limpeza no exit.

Registra callbacks (ex.: ``db.close``) via :func:`register_cleanup` e os
conecta a ``atexit`` + SIGINT/SIGTERM via :func:`setup_shutdown_handlers`.
Os handlers rodam após o loop de eventos, fora da thread de UI.
"""

import atexit
import signal
import sys
from contextlib import suppress
from typing import Any, Callable, List, Tuple, Optional

from andaime.error_handler import ErrorContext, ErrorHandler, ErrorLevel

# Type alias for cleanup handlers
Handler = Callable[[], None]

# Global registry of cleanup handlers
_cleanup_handlers: List[Tuple[Handler, str]] = []


def register_cleanup(handler: Handler, name: Optional[str] = None) -> None:
    """Register a cleanup handler run on application exit.

    Example:
        register_cleanup(lambda: db.close(), "database")
    """
    handler_name = name or handler.__name__
    _cleanup_handlers.append((handler, handler_name))
    ErrorHandler.log(
        f"Cleanup handler registrado: {handler_name}",
        level=ErrorLevel.DEBUG,
        context=ErrorContext.SHUTDOWN,
    )


def _run_cleanup_handlers() -> None:
    """Run all registered cleanup handlers (called automatically on exit)."""
    import logging

    # Close log file handlers first to avoid "I/O on closed file" errors
    # when logging handlers are torn down during shutdown.
    for handler in logging.root.handlers.copy():
        with suppress(Exception):
            handler.close()
            logging.root.removeHandler(handler)

    for cleanup_func, name in reversed(_cleanup_handlers):  # reverse order
        try:
            cleanup_func()
        except Exception as e:
            # logging is already closed, print to console directly
            print(f"Erro durante limpeza ({name}): {e}", file=sys.stderr)


def setup_shutdown_handlers() -> None:
    """Register atexit + SIGINT/SIGTERM handlers for graceful shutdown."""
    atexit.register(_run_cleanup_handlers)

    try:
        signal.signal(signal.SIGINT, _signal_handler)  # Ctrl+C
        signal.signal(signal.SIGTERM, _signal_handler)  # termination
    except (ValueError, OSError) as e:
        # signal.signal() raises ValueError for invalid signals,
        # OSError on platforms lacking support
        ErrorHandler.log(
            f"Aviso: Não foi possível registrar signal handler: {e}",
            level=ErrorLevel.WARNING,
            context=ErrorContext.SHUTDOWN,
        )


def _signal_handler(signum: int, _frame: Any) -> None:
    """Handle signals (Ctrl+C, etc) with graceful shutdown."""
    ErrorHandler.log(
        f"Sinal recebido: {signum}",
        level=ErrorLevel.INFO,
        context=ErrorContext.SHUTDOWN,
    )
    sys.exit(0)  # triggers atexit handlers
