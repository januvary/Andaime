"""Inspetor de widgets para desenvolvimento (andaime.qt).

Permite apontar um widget e descobrir onde sua classe (de código da
aplicação) está definida — útil para "clicar no componente e ir ao código".

Gatilhos (apenas quando a var. de ambiente ``DEV`` está setada):

- ``F12`` (atalho de teclado), ou
- ``Ctrl+Shift+Click`` sobre um widget (fallback quando o window manager
  intercepta teclas de função).

O resultado aparece em um diálogo persistente, rolável e copiável com
``arquivo:linha`` da classe correspondente. **Não abre editor
automaticamente** — apenas mostra o caminho, evitando asociar/rodar o
arquivo por engano.

Uso::

    from andaime.qt.dev_inspector import enable_if_env
    enable_if_env(app)  # ativa com a var. de ambiente DEV=1
"""

from __future__ import annotations

import inspect
import os
import time
import traceback
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QObject
from PySide6.QtGui import QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

_QT_PACKAGES = ("PySide6", "PyQt6", "PyQt5")
_DEFAULT_SHORTCUT = "F12"
_CLICK_MODS = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
_ENV_VAR = "DEV"
_DEBOUNCE_S = 0.2
_ATTR_KEEPALIVE = "_dev_inspector"


def _is_qt_class(cls: type) -> bool:
    """Retorna True se a classe pertence a um dos pacotes Qt suportados."""
    return cls.__module__.split(".", 1)[0] in _QT_PACKAGES


def _build_chain(
    widget: object,
) -> list[tuple[str, Optional[str], Optional[int], bool]]:
    """Sobe a hierarquia de widgets do leaf até a janela raiz.

    Retorna uma lista de (nome_qualificado, arquivo, linha, is_qt), do widget
    mais específico (sob o cursor) até o top-level. ``is_qt`` marca classes
    de biblioteca Qt (não de código da aplicação).
    """
    cadeia: list[tuple[str, Optional[str], Optional[int], bool]] = []
    atual = widget
    while atual is not None:
        cls = type(atual)
        nome = f"{cls.__module__}.{cls.__name__}"
        arquivo, linha = _source_location(atual)
        cadeia.append((nome, arquivo, linha, _is_qt_class(cls)))
        atual = atual.parent()  # type: ignore[union-attr]
    return cadeia


def _source_location(obj: object) -> tuple[Optional[str], Optional[int]]:
    """Retorna (arquivo, linha) da definição da classe, ou (None, None)."""
    cls = type(obj)
    try:
        arquivo = inspect.getsourcefile(cls) or inspect.getfile(cls)
        _, linha = inspect.getsourcelines(cls)
        return arquivo, linha
    except (OSError, TypeError):
        return None, None


def _show_dialog(titulo: str, corpo: str, copiar: Optional[str] = None) -> None:
    """Diálogo persistente, rolável e copiável."""
    dlg = QDialog()
    dlg.setWindowTitle("dev-inspector")
    dlg.resize(620, 320)

    layout = QVBoxLayout(dlg)
    etiqueta = QLabel(f"<b>{titulo}</b>")
    etiqueta.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(etiqueta)

    texto = QTextEdit()
    texto.setReadOnly(True)
    texto.setPlainText(corpo)
    layout.addWidget(texto)

    botoes = QHBoxLayout()
    if copiar:
        btn_copiar = QPushButton("Copiar caminho")
        btn_copiar.clicked.connect(
            lambda: QApplication.clipboard().setText(copiar)
        )
        botoes.addWidget(btn_copiar)
    botoes.addStretch(1)
    btn_fechar = QPushButton("Fechar")
    btn_fechar.clicked.connect(dlg.accept)
    botoes.addWidget(btn_fechar)
    layout.addLayout(botoes)

    dlg.exec()


def _show_chain_dialog(
    widget: object,
    cadeia: list[tuple[str, Optional[str], Optional[int], bool]],
) -> None:
    """Mostra a hierarquia de widgets; clicar num item copia arquivo:linha."""
    dlg = QDialog()
    dlg.setWindowTitle("dev-inspector — hierarquia")
    dlg.resize(760, 440)
    layout = QVBoxLayout(dlg)

    topo = QLabel(
        f"<b>{len(cadeia)} níveis</b> sob o cursor. "
        "Clique num item para copiar <i>arquivo:linha</i>."
    )
    topo.setTextFormat(Qt.TextFormat.RichText)
    layout.addWidget(topo)

    lista = QListWidget()
    layout.addWidget(lista)

    for nivel, (nome, arquivo, linha, is_qt) in enumerate(cadeia):
        if is_qt:
            rotulo = f"[{nivel}] {nome}    (biblioteca Qt)"
        elif arquivo:
            rotulo = f"[{nivel}] {nome}    {arquivo}:{linha}"
        else:
            rotulo = f"[{nivel}] {nome}    (sem fonte)"
        item = QListWidgetItem(rotulo)
        item.setData(Qt.ItemDataRole.UserRole, f"{arquivo}:{linha}" if arquivo else None)
        if is_qt:
            item.setForeground(Qt.GlobalColor.gray)
        lista.addItem(item)

    status = QLabel("")
    status.setStyleSheet("color: #888;")
    layout.addWidget(status)

    def _ao_clicar(item: QListWidgetItem) -> None:
        caminho = item.data(Qt.ItemDataRole.UserRole)
        if caminho:
            QApplication.clipboard().setText(caminho)
            status.setText(f"copiado: {caminho}")

    lista.itemClicked.connect(_ao_clicar)

    botoes = QHBoxLayout()
    botoes.addStretch(1)
    btn_fechar = QPushButton("Fechar")
    btn_fechar.clicked.connect(dlg.accept)
    botoes.addWidget(btn_fechar)
    layout.addLayout(botoes)

    dlg.exec()


class _DevInspector(QObject):
    """Observa todos os eventos da QApplication para disparar a inspeção.

    Instala o filtro de eventos na própria QApplication: assim o gatilho
    funciona independentemente de qual widget (ou nenhum) tem o foco.
    """

    def __init__(self, app: QApplication, atalho: str = _DEFAULT_SHORTCUT) -> None:
        super().__init__()
        combinacao = QKeySequence(atalho)[0]
        self._tecla = combinacao.key()
        self._mods = combinacao.keyboardModifiers()
        self._ultimo_disparo = 0.0
        app.installEventFilter(self)

    def eventFilter(self, _obj, event) -> bool:  # noqa: D401 - assinatura Qt
        """Consome o gatilho (tecla ou clique) e dispara a inspeção."""
        tipo = event.type()
        if tipo == QEvent.Type.KeyPress:
            acionado = (
                event.key() == self._tecla
                and (event.modifiers() & self._mods) == self._mods
            )
        elif tipo == QEvent.Type.MouseButtonPress:
            acionado = (
                event.button() == Qt.MouseButton.LeftButton
                and (event.modifiers() & _CLICK_MODS) == _CLICK_MODS
            )
        else:
            acionado = False

        if not acionado:
            return False

        agora = time.monotonic()
        if agora - self._ultimo_disparo < _DEBOUNCE_S:
            return True  # consumido, mas ignora disparo duplicado
        self._ultimo_disparo = agora
        self._inspecionar()
        return True

    def _inspecionar(self) -> None:
        """Monta a hierarquia do widget sob o cursor e mostra a cadeia."""
        try:
            app = QApplication.instance()
            if app is None:
                return
            widget = app.widgetAt(QCursor.pos())
            if widget is None:
                _show_dialog("Nenhum widget", "O cursor está fora de qualquer widget.")
                return
            cadeia = _build_chain(widget)
            _show_chain_dialog(widget, cadeia)
        except Exception:
            _show_dialog("Erro ao inspecionar", traceback.format_exc())


def install_dev_inspector(
    app: Optional[QApplication] = None, atalho: str = _DEFAULT_SHORTCUT
) -> _DevInspector:
    """Instala o inspetor na QApplication e o mantém vivo enquanto o app viver.

    Args:
        app: QApplication (usa a instância ativa se None).
        atalho: Combinação de teclas para o gatilho de teclado.

    Returns:
        A instância do inspetor (também guardada em ``app._dev_inspector``).
    """
    app = app or QApplication.instance()
    if app is None:
        raise RuntimeError("QApplication precisa existir antes de install_dev_inspector")
    inst = _DevInspector(app, atalho)
    # Mantém o inspector vivo: sem referência, o Python coletaria o QObject
    # e o filtro de eventos seria removido.
    setattr(app, _ATTR_KEEPALIVE, inst)
    return inst


def enable_if_env(
    app: Optional[QApplication] = None,
    var: str = _ENV_VAR,
    atalho: str = _DEFAULT_SHORTCUT,
) -> Optional[_DevInspector]:
    """Instala o inspetor apenas se a variável de ambiente ``var`` estiver setada.

    Mostra um diálogo de confirmação na ativação. Retorna a instância ou
    ``None`` se a variável não estiver definida.
    """
    if not os.environ.get(var):
        return None
    resolved = app or QApplication.instance()
    if resolved is None:
        return None
    inst = install_dev_inspector(resolved, atalho)
    return inst
