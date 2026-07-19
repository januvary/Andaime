"""Seletor da remessa ativa (lote) — espelha o seletor de Malote do RAC.

Um rótulo clicável na barra inferior esquerda mostra a data da remessa
ativa; ao clicar, abre um diálogo listando as remessas existentes
(selecionar uma a torna ativa). Ao contrário do RAC:
- não há botões de ação no rodapé do diálogo;
- não há cálculo de data de retorno;
- "malotes" chamam-se "remessas" aqui;
- novas remessas não são criadas manualmente.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QSizePolicy,
)
from datetime import date, datetime
from andaime.widgets import DateLineEdit
from andaime.qt.theme import make_button
from andaime.dates import parse_date, format_date
import operator

from src.database.ss54_database import SS54Database
from src.models import Lote
from src.utils.date_utils import format_date_display
from src.ui_qt.styles import context_menu_stylesheet


class RemessaLabel(QWidget):
    """Seletor clicável (esquerda da barra inferior) da remessa ativa.

    Espelha o ``MaloteLabel`` do RAC: um rótulo "Remessa:" em cinza
    seguido da data em destaque, clicável.
    """

    remessa_changed = Signal(object)  # Lote | None

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

    def mousePressEvent(self, event) -> None:
        show_remessa_dialog(self.window(), self._db, self._active, self.set_active)


def show_remessa_dialog(
    parent,
    db: SS54Database | None,
    active: Optional[Lote],
    on_select: Callable[[Optional[Lote]], None],
) -> None:
    if db is None:
        return

    dlg = QDialog(parent)
    dlg.setWindowTitle("Remessas")
    dlg.setMinimumWidth(170)
    dlg.setMinimumHeight(320)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)

    tree = QTreeWidget()
    tree.setHeaderHidden(True)
    tree.setRootIsDecorated(True)
    tree.setAnimated(True)
    tree.setIndentation(0)
    tree.setAlternatingRowColors(True)
    tree.setColumnCount(1)
    tree.setProperty("class", "remessa-tree")

    active_id = active.id if active else None
    _populate_remessa_tree(tree, db, active_id)

    def _repopulate() -> None:
        _populate_remessa_tree(tree, db, active_id)

    def _on_item(item: QTreeWidgetItem, _column: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data is not None:
            on_select(data)
            dlg.accept()
        else:
            item.setExpanded(not item.isExpanded())

    tree.itemClicked.connect(_on_item)
    tree.itemActivated.connect(_on_item)
    tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
    tree.customContextMenuRequested.connect(
        lambda pos: _show_tree_menu(tree, pos, db, active, _repopulate, on_select)
    )
    layout.addWidget(tree)

    dlg.exec()


def _populate_remessa_tree(
    tree: QTreeWidget, db: SS54Database, active_id: object
) -> None:
    tree.clear()

    current_year = datetime.now().year
    current_month = datetime.now().month
    year_items: dict[int, QTreeWidgetItem] = {}
    month_items: dict[tuple[int, int], QTreeWidgetItem] = {}

    sorted_lotes: list[tuple[object, date]] = []
    for lote in db.get_all_lotes():
        dt = parse_date(lote.date) or date.today()
        sorted_lotes.append((lote, dt))
    sorted_lotes.sort(key=operator.itemgetter(1), reverse=True)

    counts = db.count_processos_by_lote()

    for lote, dt in sorted_lotes:
        year = dt.year
        month = dt.month
        is_past_month = (year, month) < (current_year, current_month)
        is_past_year = year < current_year

        child = QTreeWidgetItem()
        is_active = lote.id == active_id
        prefix = "✓ " if is_active else "    "
        count = counts.get(lote.id, 0)
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


def _show_tree_menu(tree, pos, db, active, on_done, on_select) -> None:
    item = tree.itemAt(pos)
    if not item:
        return
    lote = item.data(0, Qt.ItemDataRole.UserRole)
    if not lote:
        return

    menu = QMenu(tree)
    menu.setStyleSheet(context_menu_stylesheet())
    edit_action = menu.addAction("Editar")
    action = menu.exec(tree.viewport().mapToGlobal(pos))
    if action == edit_action:
        _show_edit_date_dialog(tree.window(), db, lote, active, on_done, on_select)


def _show_edit_date_dialog(parent, db, lote, active, on_done, on_select) -> None:
    dlg = QDialog(parent)
    dlg.setWindowTitle("Data de envio")
    dlg.setMinimumWidth(300)

    layout = QVBoxLayout(dlg)
    layout.setSpacing(12)

    date_input = DateLineEdit()
    date_input.setPlaceholderText("DD/MM/AAAA")
    dt = parse_date(lote.date)
    date_input.setText(format_date(dt) if dt else "")
    date_input.selectAll()
    layout.addWidget(date_input)

    btn_row = QHBoxLayout()
    cancel = make_button("Cancelar", "flat-fill")
    cancel.clicked.connect(dlg.reject)
    save = make_button("Salvar", "flat-fill")
    btn_row.addStretch()
    btn_row.addWidget(cancel)
    btn_row.addWidget(save)
    layout.addLayout(btn_row)

    def do_save() -> None:
        parsed = parse_date(date_input.text())
        if not parsed:
            return
        iso = parsed.isoformat()
        db.update_lote_date(lote.id, iso)
        on_done()
        fresh = db.get_lote_by_id(lote.id)
        if on_select is not None and active is not None and fresh is not None:
            if active.id == fresh.id:
                on_select(fresh)
        dlg.accept()

    save.clicked.connect(do_save)
    date_input.returnPressed.connect(do_save)
    dlg.exec()
