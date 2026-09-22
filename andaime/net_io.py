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

from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel

_R = TypeVar("_R")

_logger = logging.getLogger("andaime")

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

# WinError 32/33 chega como PermissionError mas limpa sozinho.
_SHARING_WIN_ERRORS = frozenset({32, 33})


def is_transient_error(exc: BaseException) -> bool:
    """Classifica a exceção como transitória (vale a pena retry)."""
    if not isinstance(exc, OSError):
        return False

    winerror = getattr(exc, "winerror", None)
    if winerror is not None and winerror in _SHARING_WIN_ERRORS:
        return True

    # PermissionError is otherwise never transient.
    if isinstance(exc, PermissionError):
        return False

    # Check standard errno.
    if exc.errno in _TRANSIENT_ERRNOS:
        return True

    # Check Windows-specific error codes via winerror attribute.
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
) -> Callable[[Callable[..., _R]], Callable[..., _R]]:
    """Decorador que retenta a função em erros de rede transitórios."""

    def decorator(func: Callable[..., _R]) -> Callable[..., _R]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> _R:
            last_exc: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except OSError as exc:
                    last_exc = exc
                    if not is_transient_error(exc) or attempt == max_retries:
                        raise
                    delay = base_delay * (attempt + 1)
                    ErrorHandler.log(
                        f"I/O transient error in {func.__qualname__} "
                        f"(attempt {attempt + 1}/{max_retries}): {exc} — "
                        f"retrying in {delay:.1f}s",
                        level=ErrorLevel.WARNING,
                        context=ErrorContext.FILE_IO,
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


@retry_on_network_error(max_retries=2, base_delay=0.5)
def _replace_atomic(tmp: Path, target: Path) -> None:
    """Troca atômica com retry (sharing violation limpa sozinho)."""
    os.replace(tmp, target)


@contextmanager
def atomic_write_path(target: Path) -> Iterator[Path]:
    """Context manager para escrita atômica em shares de rede.

    Substitui o destino no fim limpo; deleta o temporário em exceção.
    """
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        yield tmp
        _replace_atomic(tmp, target)
    except BaseException:
        with suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
