"""Cabeçalho do SS-54: duas barras superiores em um grid de 5 colunas.

As duas barras compartilham o mesmo grid de 5 colunas para que os campos
se alinhem verticalmente:

- Barra 1: tema | novo | nome do paciente (2 colunas) | telefone
- Barra 2: config | ciclo | solicitação | tipo | descrição

A busca de paciente e a busca por telefone são duas ``SearchableComboBox``
que se auto-preenchem (cross-fill) ao selecionar um paciente.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QGridLayout,
    QSizePolicy,
    QPushButton,
)

from bap.models import Paciente
from bap.constants import SOLICITACAO_LABELS
from bap.utils.text_utils import format_phone, format_phone_live, _digits
from andaime.widgets import static_search_fn, SearchableComboBox, CycleButton
from andaime.qt.theme import ThemeToggleButton, make_button
from andaime.qt.toggle_group import ToggleGroup


class Header(QWidget):
    """Cabeçalho com as duas barras superiores do SS-54."""

    patient_selected = Signal(object)  # Paciente | None
    theme_toggled = Signal(bool)
    filtros_changed = Signal()
    ciclo_changed = Signal(int)
    config_requested = Signal()
    novo_requested = Signal()

    # Pesos das 5 colunas compartilhadas pelas duas barras.
    _COL_STRETCH = (1, 1, 5, 5, 3)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_patient: Optional[Paciente] = None
        self._tipo: str = ""
        self._solicitacao: str = ""
        self._pacientes: list[Paciente] = []

        self._build_widgets()
        self._build_layout()

    # ========== Construção ==========

    def _build_widgets(self) -> None:
        self._theme_btn = ThemeToggleButton(self)
        self._theme_btn.theme_toggled.connect(lambda d: self.theme_toggled.emit(d))

        self._novo_btn = make_button("Novo", "flat")
        self._novo_btn.clicked.connect(lambda: self.novo_requested.emit())

        self._search = SearchableComboBox(
            search_fn=static_search_fn({}),
            placeholder="Buscar paciente...",
            parent=self,
        )
        self._search.setFixedHeight(34)
        self._search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._search.selection_changed.connect(self._on_patient_key_selected)

        self._telefone = SearchableComboBox(
            search_fn=static_search_fn({}),
            placeholder="Telefone",
        )
        self._telefone.setFixedHeight(34)
        self._telefone.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._telefone.line_edit.textEdited.connect(self._on_telefone_text_edited)
        self._telefone.selection_changed.connect(self._on_telefone_selected)

        self._grp_solicitacao = ToggleGroup(
            options=[(k, SOLICITACAO_LABELS[k]) for k in ("primeira", "renovacao")],
            default=None,
            allow_deselect=True,
        )
        self._grp_solicitacao.selection_changed.connect(
            lambda k: (setattr(self, "_solicitacao", k), self.filtros_changed.emit())
        )

        self._grp_tipo = ToggleGroup(
            options=[
                ("medicamento", "Medicamento"),
                ("nutricao", "Nutrição"),
                ("bomba", "Bomba"),
            ],
            default=None,
            allow_deselect=True,
        )
        self._grp_tipo.selection_changed.connect(
            lambda k: (setattr(self, "_tipo", k), self.filtros_changed.emit())
        )

        self._descricao = SearchableComboBox(
            search_fn=static_search_fn({}),
            placeholder="Descrição",
        )
        self._descricao.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._descricao.setFixedHeight(34)

        self._config_btn = QPushButton("\u2699")
        self._config_btn.setFixedSize(28, 28)
        self._config_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._config_btn.setProperty("class", "icon")
        self._config_btn.setToolTip("Configurações")
        self._config_btn.clicked.connect(lambda: self.config_requested.emit())

        self._cycle_btn = CycleButton(
            label="1",
            role="flat",
            modulus=10,
            base=1,
            initial=1,
            width=32,
            font_size=13,
            on_change=lambda v: self.ciclo_changed.emit(v),
        )
        self._cycle_btn.value = 1
        self._cycle_btn.setStyleSheet(
            "padding: 6px 0; font-size: 13px; font-weight: 600;"
        )

    def _build_layout(self) -> None:
        # Um único grid de 5 colunas para ambas as barras, garantindo que
        # as colunas tenham exatamente a mesma largura/prop达o nas duas
        # linhas, independentemente do tamanho da janela.
        grid = QGridLayout()
        grid.setContentsMargins(12, 6, 12, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, self._COL_STRETCH[0])
        grid.setColumnStretch(1, self._COL_STRETCH[1])
        grid.setColumnStretch(2, self._COL_STRETCH[2])
        grid.setColumnStretch(3, self._COL_STRETCH[3])
        grid.setColumnStretch(4, self._COL_STRETCH[4])

        # Barra 1: tema | novo | nome (2 colunas) | telefone
        grid.addWidget(self._theme_btn, 0, 0)
        grid.addWidget(self._novo_btn, 0, 1)
        grid.addWidget(self._search, 0, 2, 1, 2)
        grid.addWidget(self._telefone, 0, 4)
        # Barra 2: config | ciclo | solicitacao | tipo | descricao
        grid.addWidget(self._config_btn, 1, 0)
        grid.addWidget(self._cycle_btn, 1, 1)
        grid.addWidget(self._grp_solicitacao, 1, 2)
        grid.addWidget(self._grp_tipo, 1, 3)
        grid.addWidget(self._descricao, 1, 4)

        grid.setRowMinimumHeight(0, 40)
        grid.setRowMinimumHeight(1, 40)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(grid)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if getattr(self, "_novo_btn", None) is not None and getattr(self, "_cycle_btn", None) is not None:
            self._cycle_btn.setFixedWidth(self._novo_btn.width())

    # ========== Backend ==========

    def set_patients(self, pacientes: list[Paciente]) -> None:
        self._pacientes = list(pacientes)
        self._search.set_search_fn(
            static_search_fn({str(p.id): p.nome for p in self._pacientes})
        )
        self._telefone.set_search_fn(self._phone_search_fn())

    def _phone_search_fn(self):
        pacientes = self._pacientes

        def search(query: str) -> dict[str, str]:
            digits = _digits(query)
            if not digits:
                return {}
            out: dict[str, str] = {}
            for p in pacientes:
                # Telefones são armazenados apenas com dígitos.
                if p.telefone and digits in p.telefone:
                    out[str(p.id)] = format_phone(p.telefone)
            return out

        return search

    def _on_telefone_text_edited(self, text: str) -> None:
        """Aplica a máscara de telefone enquanto o usuário digita."""
        le = self._telefone.line_edit
        cursor = le.cursorPosition()
        digits_before = sum(1 for ch in text[:cursor] if ch.isdigit())
        formatted = format_phone_live(text)
        if formatted == text:
            return
        le.blockSignals(True)
        le.setText(formatted)
        # Reposiciona o cursor após a mesma quantidade de dígitos.
        new_pos = len(formatted)
        seen = 0
        for i, ch in enumerate(formatted):
            if seen >= digits_before:
                new_pos = i
                break
            if ch.isdigit():
                seen += 1
        le.setCursorPosition(new_pos)
        le.blockSignals(False)

    # ========== Seleção ==========

    def _on_patient_key_selected(self, key: object) -> None:
        if not isinstance(key, str):
            self._set_patient(None)
            return
        paciente = self._get_paciente(int(key))
        self._set_patient(paciente)

    def _on_telefone_selected(self, key: object) -> None:
        if not isinstance(key, str):
            self._set_patient(None)
            return
        paciente = self._get_paciente(int(key))
        if paciente is None:
            self._set_patient(None)
            return
        self._search.set_current(str(paciente.id), paciente.nome or "")
        self._set_patient(paciente)

    def _set_patient(self, paciente: Optional[Paciente]) -> None:
        self._current_patient = paciente
        if paciente is None:
            self._telefone.set_text("")
            self.patient_selected.emit(None)
            return
        self._telefone.set_text(format_phone(paciente.telefone) or "")
        self.patient_selected.emit(paciente)

    def _get_paciente(self, pid: int) -> Optional[Paciente]:
        for p in self._pacientes:
            if p.id == pid:
                return p
        return None

    # ========== API ==========

    @property
    def current_patient(self) -> Optional[Paciente]:
        return self._current_patient

    @property
    def tipo(self) -> str:
        return self._tipo

    @property
    def solicitacao(self) -> str:
        return self._solicitacao

    def set_descricoes(self, descricoes: list[str]) -> None:
        """Alimenta o autocomplete do campo descrição com valores já usados.

        O efeito fica restrito a este campo: selecionar uma sugestão apenas
        preenche a descrição (não cross-preenche nenhum outro campo), e a
        descrição pode ser digitada livremente em qualquer processo.
        """
        opts = {d: d for d in descricoes if d}
        self._descricao.set_search_fn(static_search_fn(opts))

    @property
    def descricao(self) -> str:
        return self._descricao.current_text().strip()

    def set_descricao(self, text: str) -> None:
        self._descricao.set_text(text or "")

    def set_tipo(self, key: str) -> None:
        self._tipo = key or ""
        self._grp_tipo.set_selected(key or None, emit=False)

    def set_solicitacao(self, key: str) -> None:
        self._solicitacao = key or ""
        self._grp_solicitacao.set_selected(key or None, emit=False)

    def set_paciente_by_id(self, pid: int | "Paciente") -> None:
        paciente = pid if isinstance(pid, Paciente) else self._get_paciente(pid)
        if paciente is not None:
            self._search.set_current(str(paciente.id), paciente.nome or "")
            self._set_patient(paciente)


    @property
    def nome(self) -> str:
        return self._search.current_text().strip()

    @property
    def telefone(self) -> str:
        return self._telefone.current_text().strip()

    @property
    def ciclo(self) -> int:
        return self._cycle_btn.value

    def set_ciclo(self, value: int) -> None:
        self._cycle_btn.value = value

    def reset(self) -> None:
        self._search.clear()
        self._telefone.set_text("")
        self._descricao.clear()
        self.set_tipo("")
        self.set_solicitacao("")
        self._set_patient(None)
