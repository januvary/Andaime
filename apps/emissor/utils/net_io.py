#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Utilitários de I/O resiliente: escrita atômica e retry em rede."""

from __future__ import annotations

import errno
import functools
import logging
import os
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

T = TypeVar("T")

_logger = logging.getLogger("Emissor")

# Errnos that typically indicate transient network issues worth retrying.
_TRANSIENT_ERRNOS = frozenset(
    {
        errno.ECONNRESET,
        errno.ETIMEDOUT,
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPIPE,
        errno.EAGAIN,
        errno.EINTR,
    }
)

# Windows network error codes (WinError) that are transient.
_TRANSIENT_WIN_ERRORS = frozenset({53, 67, 121, 64, 1232, 1233, 1234, 1236})


def is_transient_error(exc: BaseException) -> bool:
    """Classifica a exceção como transitória (vale a pena retry)."""
    if not isinstance(exc, OSError):
        return False

    # PermissionError is never transient.
    if isinstance(exc, PermissionError):
        return False

    # Check standard errno.
    if exc.errno in _TRANSIENT_ERRNOS:
        return True

    # Check Windows-specific error codes via winerror attribute.
    winerror = getattr(exc, "winerror", None)
    if winerror is not None and winerror in _TRANSIENT_WIN_ERRORS:
        return True

    # OSError with errno=None on Windows often wraps a WinError.
    if exc.errno is None and winerror is None:
        msg = str(exc).lower()
        if any(
            keyword in msg
            for keyword in (
                "timeout",
                "timed out",
                "unreachable",
                "broken pipe",
                "reset",
            )
        ):
            return True

    return False


def retry_on_network_error(
    max_retries: int = 2, base_delay: float = 1.0
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorador que retenta a função em erros de rede transitórios.

    Args:
        max_retries: tentativas de retry (padrão 2)
        base_delay: atraso base em segundos, multiplicado pelo nº da tentativa
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OSError as exc:
                    last_exc = exc
                    if not is_transient_error(exc) or attempt == max_retries:
                        raise
                    delay = base_delay * (attempt + 1)
                    _logger.warning(
                        "I/O transient error in %s (attempt %d/%d): %s — "
                        "retrying in %.1fs",
                        func.__qualname__,
                        attempt + 1,
                        max_retries,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


@retry_on_network_error(max_retries=2, base_delay=1.0)
def network_mkdir(path: Path) -> Path:
    """Cria diretório (com parents) com retry em rede."""
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def atomic_write_path(target: Path) -> Iterator[Path]:
    """Context manager para escrita atômica em shares de rede.

    Substitui o destino no fim limpo; deleta o temporário em exceção.
    """
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        yield tmp
        os.replace(tmp, target)
    except BaseException:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
