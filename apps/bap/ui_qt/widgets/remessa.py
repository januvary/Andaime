"""Seletor da remessa ativa (lote) — espelha o seletor de Malote do RAC.

Um rótulo clicável na barra inferior esquerda mostra a data da remessa
ativa; ao clicar, abre um diálogo listando as remessas existentes
(selecionar uma a torna ativa). Ao contrário do RAC:
- não há cálculo de data de retorno;
- "malotes" chamam-se "remessas" aqui.

O diálogo possui barra inferior com "Nova Remessa" (criação manual) e
"Fechar". O sinal ``remessa_changed`` é emitido uma única vez, ao fechar
o diálogo, e apenas quando a remessa ativa realmente mudou.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
    QHBoxLayout,
    QSizePolicy,
)
from datetime import date, datetime
import operator
from andaime.qt.widgets import DateLineEdit
from andaime.dates import parse_date, format_date
from andaime.qt import styled_menu
from andaime.qt.dialogs import (
    KEEP_OPEN,
    confirm_dialog,
    make_dialog_toolbar,
    prompt_dialog,
    scaffold_dialog,
)

from bap.database.ss54_database import SS54Database
from bap.models import Lote
from bap.utils.date_utils import format_date_display


class RemessaLabel(QWidget):
    """Seletor clicável (esquerda da barra inferior) da remessa ativa.

    Espelha o ``MaloteLabel`` do RAC: um rótulo "Remessa:" em cinza
    seguido da data em destaque, clicável.
    """

    remessa_changed = Signal(object)  # Lote | None
    status_message = Signal(str, object)  # (texto, cor|None) — feedback do diálogo

    def __init__(self, parent=None, db: SS54Database | None = None):
        super().__init__(parent)
        self._db = db
        self._active: Optional[Lote] = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._prefix = QLabel("Remessa:")
        self._prefix.setFixedHeight(28)
        self._prefix.setProperty("class", "dim")

        self._date = QLabel()
        self._date.setFixedHeight(28)
        self._date.setProperty("batchlabel", "true")
        self._date.setCursor(Qt.CursorShape.PointingHandCursor)
        self._date.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed
        )

        layout.addWidget(self._prefix)
        layout.addSpacing(2)
        layout.addWidget(self._date)
        layout.addStretch()

        self._prefix.installEventFilter(self)
        self._date.installEventFilter(self)

        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.refresh()

    def eventFilter(self, obj, event) -> bool:
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and obj in (self._prefix, self._date)
        ):
            self.mousePressEvent(event)
            return True
        return super().eventFilter(obj, event)

    def set_db(self, db: SS54Database) -> None:
        self._db = db

    def set_active(self, lote: Optional[Lote], emit: bool = True) -> None:
        self._active = lote
        self.refresh()
        if emit:
            self.remessa_changed.emit(lote)

    def active(self) -> Optional[Lote]:
        return self._active

    def refresh(self) -> None:
        if self._active:
            self._date.setText(format_date_display(self._active.date))
        else:
            self._date.setText("Nenhuma remessa ativa")

    def emit_status(self, text: str, color: str | None = None) -> None:
        """Feedback do diálogo via linha de status (conectada pelas páginas)."""
        self.status_message.emit(text, color)

    def mousePressEvent(self, event) -> None:
        show_remessa_dialog(self)


def _lote_key(lote: Optional[Lote]):
    return (lote.id, lote.date) if lote is not None else None


def _activate_if_changed(label: "RemessaLabel", lote: Lote) -> bool:
    """Aplica ``lote`` como ativo silenciosamente, apenas se mudou de fato.

    O ``remessa_changed`` do rótulo só é emitido ao fechar o diálogo, pelo
    próprio ``show_remessa_dialog``, e somente quando a chave diferir da
    inicial — evita refreshes redundantes na MainWindow (padrão RAC).
    """
    current = label.active()
    if current is not None and current.id == lote.id and current.date == lote.date:
        return False
    label.set_active(lote, emit=False)
    return True


def show_remessa_dialog(label: "RemessaLabel") -> None:
    db = label._db
    if db is None:
        return

    parent = label.window()

    dlg, layout = scaffold_dialog(parent, "Remessas", spacing=12, min_width=170)
    dlg.setMinimumHeight(320)

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(True)
    tree.setAnimated(True)
    tree.setIndentation(0)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    tree.setProperty("class", "remessa-tree")

    def _repopulate() -> None:
        active = label.active()
        _populate_remessa_tree(tree, db, active.id if active else None)

    _repopulate()

    def _on_item(item: QTreeWidgetItem, _column: int) -> None:
        lote = item.data(0, Qt.ItemDataRole.UserRole)
        if lote is not None:
            _activate_if_changed(label, lote)
            dlg.accept()
        else:
            item.setExpanded(not item.isExpanded())

    tree.itemClicked.connect(_on_item)
    tree.itemActivated.connect(_on_item)
    tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tree.customContextMenuRequested.connect(
        lambda pos: _show_tree_menu(label, tree, pos, _repopulate)
    )
    layout.addWidget(tree)

    btn_row, [nova_btn, fechar_btn] = make_dialog_toolbar(
        left=[("Nova Remessa", "flat")],
        right=[("Fechar", "flat")],
    )
    nova_btn.clicked.connect(lambda: (_show_new_remessa_dialog(label), _repopulate()))
    fechar_btn.clicked.connect(dlg.reject)
    layout.addLayout(btn_row)

    initial = _lote_key(label.active())
    dlg.exec()
    if _lote_key(label.active()) != initial:
        label.remessa_changed.emit(label.active())


def _populate_remessa_tree(
    tree: QTreeWidget, db: SS54Database, active_id: object
) -> None:
    tree.clear()

    current_year = datetime.now().year
    current_month = datetime.now().month
    year_items: dict[int, QTreeWidgetItem] = {}
    month_items: dict[tuple[int, int], QTreeWidgetItem] = {}

    sorted_lotes: list[tuple[object, date, int]] = []
    for lote, cnt in db.get_lotes_with_counts():
        dt = parse_date(lote.date) or date.today()
        sorted_lotes.append((lote, dt, cnt))
    sorted_lotes.sort(key=operator.itemgetter(1), reverse=True)

    for lote, dt, cnt in sorted_lotes:
        year = dt.year
        month = dt.month
        is_past_month = (year, month) < (current_year, current_month)
        is_past_year = year < current_year

        child = QTreeWidgetItem()
        lote_id = lote.id
        is_active = lote_id == active_id
        prefix = "✓ " if is_active else "    "
        count = cnt
        child.setText(0, f"{prefix}{dt.strftime('%d/%m/%Y')} ({count})")
        child.setData(0, Qt.ItemDataRole.UserRole, lote)
        if is_active:
            font = child.font(0)
            font.setBold(True)
            child.setFont(0, font)

        if not is_past_month:
            tree.addTopLevelItem(child)
        elif is_past_year:
            if year not in year_items:
                year_item = QTreeWidgetItem()
                year_item.setText(0, str(year))
                year_item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
                year_item.setExpanded(False)
                year_items[year] = year_item
                tree.addTopLevelItem(year_item)
            key = (year, month)
            if key not in month_items:
                month_item = QTreeWidgetItem()
                month_item.setText(0, f"{month:02d}/{year}")
                month_item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
                month_item.setExpanded(False)
                month_items[key] = month_item
                year_items[year].addChild(month_item)
            month_items[key].addChild(child)
        else:
            key = (year, month)
            if key not in month_items:
                month_item = QTreeWidgetItem()
                month_item.setText(0, f"{month:02d}/{year}")
                month_item.setChildIndicatorPolicy(
                    QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                )
                month_item.setExpanded(True)
                month_items[key] = month_item
                tree.addTopLevelItem(month_item)
            month_items[key].addChild(child)


def _show_tree_menu(
    label: "RemessaLabel", tree: QTreeWidget, pos, on_done
) -> None:
    item = tree.itemAt(pos)
    if not item:
        return
    lote = item.data(0, Qt.ItemDataRole.UserRole)
    if not lote:
        return

    db = label._db
    menu = styled_menu(tree)
    edit_action = menu.addAction("Editar")
    delete_action = None
    counts = {lo.id: c for lo, c in db.get_lotes_with_counts()}
    if counts.get(lote.id, 0) <= 0:
        delete_action = menu.addAction("Excluir")

    action = menu.exec(tree.viewport().mapToGlobal(pos))
    if action == edit_action:
        _show_edit_date_dialog(label, lote, on_done)
    elif action == delete_action and delete_action is not None:
        _confirm_delete_remessa(label, lote, on_done)


def _confirm_delete_remessa(
    label: "RemessaLabel", lote: Lote, on_done
) -> None:
    db = label._db
    if not confirm_dialog(
        label.window(),
        "Excluir Remessa",
        f'Excluir a remessa "{format_date_display(lote.date)}"?',
        confirm_label="Excluir",
        danger=True,
    ):
        return

    if not db.delete_lote(lote.id):
        label.emit_status("Não foi possível excluir a remessa.", "status_error")
        return

    # Se a remessa excluída era a ativa, reatribui para a mais recente restante.
    active = label.active()
    if active is not None and active.id == lote.id:
        remaining = db.get_all_lotes()
        label.set_active(remaining[0] if remaining else None, emit=False)
    label.refresh()
    on_done()
    label.emit_status("Remessa excluída.", "status_success")


def _show_new_remessa_dialog(label: "RemessaLabel") -> None:
    from bap.utils.remessa_service import next_remessa_date

    db = label._db
    parent = label.window()

    date_input = DateLineEdit()
    date_input.setPlaceholderText("DD/MM/AAAA")
    existing = db.get_lotes_with_counts()
    dates = {lo.date for lo, _ in existing}
    if existing:
        last = parse_date(existing[0][0].date)
        suggested = next_remessa_date(last) if last else date.today()
    else:
        suggested = date.today()
    date_input.setText(suggested.strftime("%d/%m/%Y"))
    date_input.selectAll()

    def on_confirm(edit: DateLineEdit):
        parsed = parse_date(edit.text())
        if not parsed:
            label.emit_status("Data inválida.", "status_error")
            return KEEP_OPEN
        iso = parsed.isoformat()
        if iso in dates:
            label.emit_status("Já existe uma remessa nesta data.", "status_error")
            return KEEP_OPEN
        lote = db.create_lote(iso)
        if lote.id is None:
            label.emit_status("Não foi possível criar a remessa.", "status_error")
            return KEEP_OPEN
        db.move_incompletos_to_lote(lote.id)
        label.set_active(lote, emit=False)
        label.refresh()
        label.emit_status(f"Remessa criada: {format_date_display(iso)}.", "status_success")

    prompt_dialog(
        parent,
        "Nova Remessa",
        widget=date_input,
        confirm_label="Criar",
        on_confirm=on_confirm,
    )


def _show_edit_date_dialog(label: "RemessaLabel", lote: Lote, on_done) -> None:
    db = label._db
    parent = label.window()

    date_input = DateLineEdit()
    date_input.setPlaceholderText("DD/MM/AAAA")
    dt = parse_date(lote.date)
    date_input.setText(format_date(dt) if dt else "")
    date_input.selectAll()

    dates = {lo.date for lo, _ in db.get_lotes_with_counts() if lo.id != lote.id}

    def on_confirm(edit: DateLineEdit):
        parsed = parse_date(edit.text())
        if not parsed:
            label.emit_status("Data inválida.", "status_error")
            return KEEP_OPEN
        iso = parsed.isoformat()
        if iso == lote.date:
            return  # sem mudança — fecha sem feedback
        if iso in dates:
            label.emit_status("Já existe uma remessa nesta data.", "status_error")
            return KEEP_OPEN
        db.update_lote_date(lote.id, iso)
        lote.date = iso
        active = label.active()
        if active is not None and active.id == lote.id:
            fresh = db.get_lote_by_id(lote.id)
            if fresh is not None:
                label.set_active(fresh, emit=False)
        label.refresh()
        on_done()
        label.emit_status("Remessa atualizada.", "status_success")

    prompt_dialog(
        parent,
        "Data de envio",
        widget=date_input,
        confirm_label="Salvar",
        on_confirm=on_confirm,
    )
