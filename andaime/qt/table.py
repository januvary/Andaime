"""Table helpers for Qt — two approaches, same module.

**QTableWidget**: use ``table_batch_populate`` to freeze column resize
during batch ``setItem``, avoiding quadratic re-measure.

**QTableView + model**: use ``TableViewModel`` with ``ColumnSpec``.
The model holds plain data objects; the view only paints visible rows.
``beginResetModel``/``endResetModel`` batches updates atomically.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QPalette, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableView,
    QTableWidget,
)


@contextmanager
def table_batch_populate(table: QTableWidget) -> Iterator[None]:
    """Context manager for efficient batch population of a QTableWidget."""
    header = table.horizontalHeader()
    dynamic = [
        c
        for c in range(table.columnCount())
        if header.sectionResizeMode(c) == QHeaderView.ResizeMode.ResizeToContents
    ]

    was_sorting = table.isSortingEnabled()
    sort_state = None
    if was_sorting:
        sort_state = (
            header.sortIndicatorSection(),
            header.sortIndicatorOrder(),
        )
        table.setSortingEnabled(False)

    table.blockSignals(True)
    for c in dynamic:
        header.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
    try:
        yield
    finally:
        for c in dynamic:
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        table.blockSignals(False)
        for c in dynamic:
            table.resizeColumnToContents(c)
        if sort_state is not None:
            table.setSortingEnabled(True)
            table.sortByColumn(*sort_state)


class NoElideDelegate(QStyledItemDelegate):
    """Draws cell text without ellipsis and adds a bottom separator."""

    _TEXT_HMARGIN = 8

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> None:
        painter.save()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, widget
        )

        from andaime.qt.theme import colors

        sep = QColor(colors().get("panel_border", "#E5E7EB"))
        painter.setPen(sep)
        painter.drawLine(opt.rect.bottomLeft(), opt.rect.bottomRight())

        rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, widget
        )
        rect = rect.adjusted(self._TEXT_HMARGIN, 0, -self._TEXT_HMARGIN, 0)
        role = (
            QPalette.ColorRole.HighlightedText
            if opt.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        )
        painter.setPen(opt.palette.color(role))
        flags = int(opt.displayAlignment) | Qt.TextFlag.TextSingleLine
        painter.drawText(rect, flags, opt.text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        padding = index.data(_PADDING_ROLE) or 0
        extra = int(padding) * 2 + self._TEXT_HMARGIN * 2
        size.setWidth(size.width() + extra)
        return size


# ============================================================
# QTableView + model path
# ============================================================

_DEFAULT_ALIGN = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
_PADDING_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True)
class ColumnSpec:
    """Declarative column definition for ``TableViewModel``."""

    header: str
    getter: Callable[[Any], str]
    alignment: Qt.AlignmentFlag = _DEFAULT_ALIGN
    header_alignment: Qt.AlignmentFlag = _DEFAULT_ALIGN
    resize_mode: QHeaderView.ResizeMode = QHeaderView.ResizeMode.Interactive
    width: int | None = None
    foreground: Callable[[Any], QColor | None] | None = None
    padding: int = 0


class TableViewModel(QAbstractTableModel):
    """Generic table model backed by a list of plain data objects."""

    def __init__(
        self,
        columns: list[ColumnSpec],
        id_getter: Callable[[Any], Any] | None = None,
    ) -> None:
        super().__init__()
        self._columns = columns
        self._id_getter = id_getter or (lambda row: getattr(row, "id", None))
        self._rows: list[Any] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._columns[section].header
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(self._columns[section].header_alignment)
        return None

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        col = self._columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return col.getter(row)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(col.alignment)
        if role == Qt.ItemDataRole.ForegroundRole and col.foreground is not None:
            return col.foreground(row)
        if role == Qt.ItemDataRole.UserRole:
            return self._id_getter(row)
        if role == _PADDING_ROLE:
            return col.padding
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def set_rows(self, rows: list[Any]) -> None:
        """Replace all rows atomically (single view update pass)."""
        self.beginResetModel()
        self._rows = rows.copy()
        self.endResetModel()

    def row_id(self, row: int) -> Any:
        """Return the ID of the row at ``row``, or ``None`` if out of range."""
        if 0 <= row < len(self._rows):
            return self._id_getter(self._rows[row])
        return None

    def find_row_by_id(self, id_value: Any) -> int | None:
        """Return the row index for ``id_value``, or ``None`` if not found."""
        for i, row in enumerate(self._rows):
            if self._id_getter(row) == id_value:
                return i
        return None


def configure_table_view(
    view: QTableView, columns: list[ColumnSpec]
) -> None:
    """Apply column resize modes and fixed widths from a ``ColumnSpec`` list.

    Call once after ``view.setModel(model)`` to configure the header.
    """
    header = view.horizontalHeader()
    for col, spec in enumerate(columns):
        header.setSectionResizeMode(col, spec.resize_mode)
        if spec.width is not None:
            view.setColumnWidth(col, spec.width)
