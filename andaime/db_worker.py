"""
Database worker — executa operações de banco numa única thread dedicada.

O ``BaseDatabase`` já é thread-safe (``RLock`` + ``check_same_thread=False``),
então este worker chama os métodos do db diretamente. As operações são
serializadas em ordem FIFO (``ThreadPoolExecutor`` com 1 worker), garantindo
que duas chamadas nunca concorram na conexão. Os resultados chegam via
``concurrent.futures.Future``; a camada de UI faz o marshal de volta para a
sua própria thread (Qt: signal; Tk: ``after``).

Princípio: uma única thread de DB → sem locking extra, sem corrupção de
conexão, e a UI nunca bloqueia numa chamada demorada.
"""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

from andaime.error_handler import ErrorHandler, ErrorContext, ErrorLevel
from andaime.net_io import is_transient_error

_R = TypeVar("_R")

#: Exceções que nunca disparam reconexão (bug ou violação real).
_NON_RETRYABLE = (sqlite3.IntegrityError, sqlite3.ProgrammingError)


def call_with_reconnect(
    db: Any, fn: Callable[..., _R], *args: Any, **kwargs: Any
) -> _R:
    """Executa ``fn``; em erro de rede/transient, reconecta e repete 1x."""
    try:
        return fn(*args, **kwargs)
    except _NON_RETRYABLE:
        raise
    except (sqlite3.DatabaseError, OSError) as e:
        if isinstance(e, OSError) and not is_transient_error(e):
            raise
        ErrorHandler.log(
            f"Erro de banco/rede em {getattr(fn, '__name__', fn)}: {e} — "
            f"verificando conexão e repetindo...",
            level=ErrorLevel.WARNING,
            context=ErrorContext.DATABASE,
        )
        try:
            db._ensure_connection()
        except Exception as ensure_exc:
            ErrorHandler.log(
                f"Reconexão falhou: {ensure_exc}",
                level=ErrorLevel.WARNING,
                context=ErrorContext.DATABASE,
            )
            raise
        return fn(*args, **kwargs)


def drain_worker(worker: Any, timeout: float = 5.0) -> bool:
    """Encerra o worker aguardando tarefas pendentes até ``timeout``.

    Roda numa thread daemon: operação presa em I/O de rede nunca trava
    o fechamento. ``timeout=0`` dispara sem esperar. Retorna True se drenou.
    """
    if worker is None:
        return True
    if timeout <= 0:
        try:
            worker.shutdown(wait=False)
        except Exception:
            pass
        return False
    try:
        drainer = threading.Thread(
            target=worker.shutdown,
            kwargs={"wait": True},
            daemon=True,
            name="db-drain",
        )
        drainer.start()
        drainer.join(timeout=timeout)
        if drainer.is_alive():
            ErrorHandler.log(
                f"DB worker não drenou em {timeout:.0f}s "
                "(operação presa em I/O de rede?) — fechando mesmo assim",
                level=ErrorLevel.WARNING,
                context=ErrorContext.SHUTDOWN,
            )
            return False
        return True
    except Exception as e:
        ErrorHandler.log(
            f"Erro ao encerrar DB worker: {e}",
            level=ErrorLevel.WARNING,
            context=ErrorContext.SHUTDOWN,
        )
        return False


class DatabaseWorker:
    """
    Executa operações de banco numa thread dedicada e serializada.

    Attributes:
        db: A instância do banco (tipicamente um BaseDatabase).
    """

    def __init__(self, db: Any) -> None:
        """
        Inicializa o worker.

        Args:
            db: Instância do banco cujos métodos serão executados off-thread.
        """
        self._db = db
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        self._shutdown = False

    @property
    def db(self) -> Any:
        """A instância do banco associada ao worker."""
        return self._db

    def submit(self, fn: Callable[..., _R], *args: Any, **kwargs: Any) -> Future[_R]:
        """
        Enfileira ``fn(*args, **kwargs)`` na thread de DB e devolve um Future.

        A chamada retorna imediatamente (não bloqueia). O resultado (ou
        exceção) fica disponível no Future retornado. Operações são
        executadas na ordem de submissão (FIFO), uma por vez.

        Args:
            fn: Função a executar (tipicamente um método do db).
            *args: Argumentos posicionais para fn.
            **kwargs: Argumentos nomeados para fn.

        Returns:
            Future para o resultado de fn.

        Raises:
            RuntimeError: Se chamado após shutdown().
        """
        with self._lock:
            if self._shutdown:
                raise RuntimeError("DatabaseWorker já foi encerrado")
            return self._executor.submit(fn, *args, **kwargs)

    def shutdown(self, wait: bool = True) -> None:
        """
        Encerra o worker, liberando a thread.

        Chamadas posteriores a submit() levantam RuntimeError. Operações
        já enfileiradas são concluídas antes do encerramento (se wait=True).

        Args:
            wait: Se True, aguarda as tarefas pendentes terminarem.
        """
        with self._lock:
            self._shutdown = True
        ErrorHandler.log(
            "DatabaseWorker encerrado",
            level=ErrorLevel.INFO,
            context=ErrorContext.DATABASE,
        )
        self._executor.shutdown(wait=wait)


class RetryingDatabaseWorker(DatabaseWorker):
    """Worker que repete cada operação uma vez após reconexão."""

    def submit(
        self, fn: Callable[..., _R], *args: Any, **kwargs: Any
    ):  # type: ignore[override]
        """Enfileira ``fn`` embrulhada em tentativa + reconexão."""
        return super().submit(call_with_reconnect, self.db, fn, *args, **kwargs)
