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

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

_R = TypeVar("_R")


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
        self._executor.shutdown(wait=wait)
