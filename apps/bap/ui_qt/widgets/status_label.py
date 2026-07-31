"""Seletor de status do processo (barra inferior, ao lado da remessa).

Um rótulo clicável "Status: [STATUS]" que abre um diálogo com as opções
de status possíveis (definidas em ``src.constants.STATUS_LABELS``).
Selecionar uma atualiza o rótulo e emite ``status_changed`` com a chave
canônica do status (minúscula).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QLabel,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
    QHBoxLayout,
    QSizePolicy,
)

from bap.constants import (
    STATUS_LABELS,
    NULL_STATUS,
    allowed_status_transitions,
    status_display_label,
)
from bap.ui_qt.widgets.dialogs import scaffold_dialog, make_dialog_button_row
from bap.ui_qt.widgets.labels import SectionLabel

_STATUS_DEFAULT = NULL_STATUS


class StatusLabel(QWidget):
    """Seletor clicável do status do processo."""

    status_changed = Signal(str, str)  # (status_key, observacoes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status_key = _STATUS_DEFAULT
        # Observação digitada no diálogo antes do processo existir (primeiro
        # Save). Fica pendente até o Save persistir; limpa ao trocar de processo.
        self.pending_obs = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._prefix = QLabel("Status:")
        self._prefix.setFixedHeight(28)
        self._prefix.setProperty("class", "dim")

        self._value = QLabel()
        self._value.setFixedHeight(28)
        self._value.setProperty("batchlabel", "true")
        self._value.setCursor(Qt.CursorShape.PointingHandCursor)
        self._value.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )

        layout.addWidget(self._prefix)
        layout.addSpacing(2)
        layout.addWidget(self._value)
        layout.addStretch()

        self._prefix.installEventFilter(self)
        self._value.installEventFilter(self)

        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            """
            QLabel[batchlabel="true"] { font-size: 19px; }
            """
        )
        self.refresh()

    def eventFilter(self, obj, event) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and obj in (self._prefix, self._value)
        ):
            self.mousePressEvent(event)
            return True
        return super().eventFilter(obj, event)

    def set_status(self, key: str, emit: bool = True) -> None:
        self._status_key = key
        self.pending_obs = ""  # descarta nota pendente de edição não salva
        self.refresh()
        if emit:
            self.status_changed.emit(key, "")

    def _apply_status(self, key: str, observacoes: str) -> None:
        """Callback do diálogo: aplica status + nota da transição."""
        self._status_key = key
        self.refresh()
        self.status_changed.emit(key, observacoes)

    def _apply_observation(self, text: str) -> None:
        """Callback do diálogo: registra observação sem trocar status."""
        self.status_changed.emit(self._status_key, text)

    def status(self) -> str:
        return self._status_key

    def refresh(self) -> None:
        self._value.setText(status_display_label(self._status_key))

    def mousePressEvent(self, event) -> None:
        show_status_dialog(
            self.window(),
            self._status_key,
            self._apply_status,
            on_observation=self._apply_observation,
        )


def show_status_dialog(
    parent,
    active: str,
    on_select,
    on_observation=None,
    preselect: str | None = None,
) -> None:
    """Diálogo de status: escolha uma transição, adicione uma observação e
    salve. Selecionar um status apenas o destaca; o diálogo só fecha ao
    clicar em "Salvar" (ou "Cancelar").

    ``on_select`` é chamado como ``on_select(key, observacoes)`` quando há
    transição.  ``on_observation`` (opcional) é chamado como
    ``on_observation(text)`` quando o usuário salva apenas uma observação
    sem selecionar nova transição.
    """
    dlg, layout = scaffold_dialog(parent, "Status", spacing=12, min_width=300)

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(False)
    tree.setIndentation(0)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    tree.setProperty("class", "remessa-tree")
    tree.setMaximumHeight(130)

    # Status atual (apenas contexto, não selecionável).
    if active and active != NULL_STATUS:
        current = QTreeWidgetItem()
        current.setText(0, f"✓ {STATUS_LABELS.get(active, active)}")
        current.setData(0, Qt.ItemDataRole.UserRole, None)
        font = current.font(0)
        font.setBold(True)
        current.setFont(0, font)
        current.setFlags(
            current.flags()
            & ~Qt.ItemFlag.ItemIsSelectable
            & ~Qt.ItemFlag.ItemIsEnabled
        )
        tree.addTopLevelItem(current)

    # Transições permitidas a partir do status atual.
    preselect_item = None
    for key in allowed_status_transitions(active):
        item = QTreeWidgetItem()
        item.setText(0, f"    {status_display_label(key)}")
        item.setData(0, Qt.ItemDataRole.UserRole, key)
        tree.addTopLevelItem(item)
        if key == preselect:
            preselect_item = item

    layout.addWidget(tree)

    # Campo de observações da transição.
    layout.addWidget(SectionLabel("Observações"))
    obs = QTextEdit()
    obs.setAcceptRichText(False)
    obs.setPlaceholderText("Observações...")
    obs.setFixedHeight(56)
    layout.addWidget(obs)

    btn_row, [cancel, salvar] = make_dialog_button_row([
        ("Cancelar", "flat-fill"),
        ("Salvar", "flat-fill"),
    ])
    salvar.setEnabled(False)
    cancel.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    selected: dict = {"key": None}

    def _update_salvar() -> None:
        has_status = selected["key"] is not None
        has_obs = bool(obs.toPlainText().strip())
        salvar.setEnabled(has_status or has_obs)

    def _on_selection_changed() -> None:
        items = tree.selectedItems()
        selected["key"] = items[0].data(0, Qt.ItemDataRole.UserRole) if items else None
        _update_salvar()

    tree.itemSelectionChanged.connect(_on_selection_changed)
    obs.textChanged.connect(_update_salvar)

    def _save() -> None:
        key = selected["key"]
        text = obs.toPlainText().strip()
        if key is None and not text:
            return
        if key is None:
            if on_observation:
                on_observation(text)
            dlg.accept()
            return
        if key == NULL_STATUS:
            key = None
        on_select(key, text)
        dlg.accept()

    salvar.clicked.connect(_save)

    if preselect_item is not None:
        preselect_item.setSelected(True)

    dlg.exec()
