"""
DbAsyncRunner — executa ops num worker e devolve o resultado na thread Qt principal.

A UI chama ``runner.run(worker.submit_fn, args..., on_done=...)``: a operação
roda na thread dedicada do DatabaseWorker, e ``on_done(result)`` é invocada na
thread principal do Qt (segura para tocar widgets). O marshal cross-thread é
feito por um Signal Qt (emitir um signal de outra thread é seguro — o Qt
enfileira a chamada para a thread do receptor).
"""

from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from andaime.db_worker import DatabaseWorker


class DbAsyncRunner(QObject):
    """
    Ponte entre o DatabaseWorker (stdlib) e a thread principal do Qt.

    Fluxo: worker executa fn -> add_done_callback emite _dispatch (signal) ->
    Qt entrega na main thread -> slot roda o thunk que chama on_done/on_error.
    """

    # Carrega um thunk () -> None para ser executado na thread principal.
    _dispatch = Signal(object)

    def __init__(self, worker: DatabaseWorker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker = worker
        # AutoConnection cross-thread -> QueuedConnection: o slot roda na main thread.
        self._dispatch.connect(self._run_thunk)

    def run(
        self,
        fn: Callable[..., Any],
        *args: Any,
        on_done: Callable[[Any], None],
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        """Submete ``fn(*args)`` ao worker; ``on_done(result)`` roda na main
        thread. ``on_error`` opcional (senão loga via ErrorHandler)."""
        try:
            fut = self._worker.submit(fn, *args)
        except RuntimeError:
            # Worker já encerrado: future sintético com a exceção, para manter
            # o contrato "run nunca levanta — erros vão para on_error/log".
            fut = Future()
            fut.set_exception(RuntimeError("DatabaseWorker encerrado"))

        def _thunk() -> None:
            try:
                on_done(fut.result())
            except Exception as e:
                if on_error is not None:
                    on_error(e)
                else:
                    from andaime.error_handler import ErrorHandler, ErrorLevel

                    ErrorHandler.log(
                        f"Erro em operação assíncrona: {e}",
                        level=ErrorLevel.WARNING,
                        context="Database",
                    )

        # Se fut já está concluído (shutdown), o callback dispara imediatamente
        # na thread atual; caso contrário, dispara na thread do worker.
        fut.add_done_callback(lambda _f: self._dispatch.emit(_thunk))

    @staticmethod
    def _run_thunk(thunk: Callable[[], None]) -> None:
        """Slot que executa o thunk na thread principal do Qt."""
        thunk()


def run_or_sync(
    runner: DbAsyncRunner | None,
    fn: Callable[..., Any],
    *,
    on_done: Callable[[Any], None],
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Executa ``fn`` via ``runner`` se disponível; senão, síncrono.

    Usado durante a inicialização, quando o ``DbAsyncRunner`` ainda não foi
    injetado: chama ``fn()`` diretamente e entrega o resultado a ``on_done``.
    Erros vão para ``on_error`` ou são re-levantados.
    """
    if runner is not None:
        runner.run(fn, on_done=on_done, on_error=on_error)
    else:
        try:
            on_done(fn())
        except Exception as e:
            if on_error is not None:
                on_error(e)
            else:
                raise
