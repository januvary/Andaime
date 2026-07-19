"""Página de Documentos (SS-54): cada página possui seu próprio chrome.

Esta página reúne, em um único widget:
- ``Header`` (duas barras superiores);
- a linha de status (abaixo do cabeçalho);
- o ``DocumentGrid`` (conteúdo);
- a ``BottomBar`` inferior (RemessaLabel + StatusLabel + ações).

A ``MainWindow`` conecta-se aos sinais reemitidos e injeta o estado do
backend (pacientes, remessa ativa, status, itens da grade).
"""

from __future__ import annotations


from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget, QFrame

from src.ui_qt.widgets.header import Header
from src.ui_qt.widgets.remessa import RemessaLabel
from src.ui_qt.widgets.status_label import StatusLabel
from src.ui_qt.widgets.document_grid import DocumentGrid
from andaime.qt import StatusLine
from src.models import Paciente
from andaime.qt.bottom_bar import BottomBar


class DocumentPage(QWidget):
    """Página de documentos com chrome próprio."""

    patient_selected = Signal(object)  # Paciente | None
    theme_toggled = Signal(bool)
    filtros_changed = Signal()
    ciclo_changed = Signal(int)
    remessa_changed = Signal(object)  # Lote | None
    status_changed = Signal(str, str)  # (status_key, observacoes)
    retornar = Signal()
    salvar = Signal()
    config_requested = Signal()
    novo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)

        self.header = Header(self)
        self.header.patient_selected.connect(self.patient_selected.emit)
        self.header.theme_toggled.connect(self.theme_toggled.emit)
        self.header.filtros_changed.connect(self.filtros_changed.emit)
        self.header.ciclo_changed.connect(self.ciclo_changed.emit)
        self.header.config_requested.connect(self.config_requested.emit)
        self.header.novo_requested.connect(self.novo_requested.emit)
        self.header.novo_requested.connect(self.reset)

        self.remessa_label = RemessaLabel(self)
        self.remessa_label.remessa_changed.connect(self.remessa_changed.emit)

        self.status_selector = StatusLabel(self)
        self.status_selector.status_changed.connect(self.status_changed.emit)

        self._status_line = StatusLine(self)

        self.grid = DocumentGrid()
        self.grid.files_dropped.connect(
            lambda n: self.set_status(
                f"{n} {'item' if n == 1 else 'itens'} "
                f"adicionado{'s' if n != 1 else ''} à grade."
            )
        )

        self._bottom_bar = BottomBar(
            parent=self,
            left_widget=self.remessa_label,
            status_widget=self.status_selector,
            actions=[
                ("Retornar", "flat-fill", self.retornar.emit)
            ],
            right_actions=[("Salvar", "flat-fill", self.salvar.emit)],
            col_weights=(2, 4, 4, 4),
        )

        # Painel único (padrão Emissor): cabeçalho + conteúdo + rodapé
        # dentro de um QFrame "panel" com borda e cantos arredondados.
        panel = QFrame()
        panel.setProperty("class", "panel")
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(0, 0, 0, 0)
        panel_lay.setSpacing(0)

        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(10, 8, 10, 8)
        content_lay.setSpacing(8)
        content_lay.addWidget(self._status_line, stretch=0)
        content_lay.addWidget(self.grid, stretch=1)

        panel_lay.addWidget(self.header, stretch=0)
        panel_lay.addWidget(content, stretch=1)
        panel_lay.addWidget(self._bottom_bar, stretch=0)

        layout.addWidget(panel, stretch=1)

    # ========== Linha de status ==========

    def set_status(self, text: str, color: str | None = None) -> None:
        self._status_line.set_status(text, color)

    # ========== Atalhos de backend ==========

    @property
    def nome(self) -> str:
        return self.header.nome

    @property
    def telefone(self) -> str:
        return self.header.telefone

    @property
    def tipo(self) -> str:
        return self.header.tipo

    @property
    def solicitacao(self) -> str:
        return self.header.solicitacao

    @property
    def descricao(self) -> str:
        return self.header.descricao

    def set_descricao(self, text: str) -> None:
        self.header.set_descricao(text)

    def set_ciclo(self, value: int) -> None:
        self.header.set_ciclo(value)

    def set_patients(self, pacientes: list[Paciente]) -> None:
        self.header.set_patients(pacientes)

    def set_remessa_db(self, db) -> None:
        self.remessa_label.set_db(db)

    def set_remessa_active(self, lote, emit: bool = True) -> None:
        self.remessa_label.set_active(lote, emit=emit)

    def remessa_active(self):
        return self.remessa_label.active()

    def focus_search(self) -> None:
        """Foca o campo de busca de paciente (atalho Ctrl+R)."""
        search = self.header._search
        if search is not None:
            search.focus_search()

    def status_key(self) -> str:
        return self.status_selector.status()

    def reset(self) -> None:
        self.header.reset()
        self.grid.clear()
        self.status_selector.set_status(None, emit=False)
        self.set_status("")
