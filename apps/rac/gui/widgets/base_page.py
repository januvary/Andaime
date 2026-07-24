#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
    QLineEdit,
)
from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QKeyEvent
from typing import Callable

from rac.gui.widgets.toast import ToastMixin
from rac.gui.widgets.buttons import make_button
from rac.gui.constants import SHORTCUT_LABELS


class BasePage(QWidget, ToastMixin):
    def __init__(self, main_window=None):
        super().__init__()
        self._mw = main_window
        self._shortcut_widgets: dict = {}
        self._shortcut_searches: list[tuple[str, QLineEdit]] = []
        self._keyboard_nav: list[tuple[QWidget, QLineEdit, Callable]] = []

    def _scaffold(self, expand_vertical: bool = False) -> QVBoxLayout:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(48, 32, 48, 32)
        outer.setSpacing(0)
        if expand_vertical:
            outer.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        else:
            outer.setAlignment(
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter
            )

        from PySide6.QtWidgets import QWidget as _W

        container = _W()
        container.setMaximumWidth(720)
        container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding if expand_vertical else QSizePolicy.Policy.Maximum,
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        outer.addWidget(container)
        return layout

    def register_keyboard_nav(
        self, widget: QWidget, search: QLineEdit, on_enter: Callable
    ):
        widget.installEventFilter(self)
        search.installEventFilter(self)
        self._keyboard_nav.append((widget, search, on_enter))

    def clear_keyboard_nav(self):
        self._keyboard_nav.clear()

    def _move_row(self, widget, direction):
        row = widget.currentRow()
        count = widget.count() if hasattr(widget, "count") else widget.rowCount()
        if count == 0:
            return
        if row < 0:
            new_row = 0
        else:
            new_row = row + direction
            if new_row < 0:
                new_row = 0
            elif new_row >= count:
                new_row = count - 1
        sm = widget.selectionModel()
        if sm is not None:
            sm.setCurrentIndex(
                widget.model().index(new_row, 0),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )

    def eventFilter(self, obj, event):
        if isinstance(event, QKeyEvent) and event.type() == event.Type.KeyPress:
            for widget, search, on_enter in self._keyboard_nav:
                is_widget = obj is widget or obj is widget.viewport()
                is_search = obj is search
                if not (is_widget or is_search):
                    continue
                key = event.key()
                if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not is_search:
                    on_enter(widget)
                    return True
                if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                    direction = -1 if key == Qt.Key.Key_Up else 1
                    self._move_row(widget, direction)
                    return True
                if is_widget and event.text() and not event.modifiers():
                    search.setFocus()
                    search.setText(event.text())
                    return True
                break
        return super().eventFilter(obj, event)

    def set_shortcuts_visible(self, show: bool):
        for name, widget in self._shortcut_widgets.items():
            _, label = SHORTCUT_LABELS[name]
            if show:
                key = SHORTCUT_LABELS[name][0]
                widget.setText(f"{label} ({key})")
            else:
                widget.setText(label)
        for placeholder, line_edit in self._shortcut_searches:
            line_edit.setPlaceholderText(
                f"{placeholder} (Ctrl+R)" if show else placeholder
            )

    def _handle_error(self, e, context=None):
        from andaime.error_handler import ErrorContext, ErrorHandler
        if context is None:
            context = ErrorContext.APP
        ErrorHandler.handle_error(e, context=context, show_dialog=False)
        self._toast(f"Erro: {e}", "negative")

    def _add_back_button(
        self, layout: QVBoxLayout, target: str = "start"
    ) -> QHBoxLayout:
        h = make_hbox()

        back_btn = make_button("Voltar", "flat")
        back_btn.clicked.connect(lambda: self._mw.navigate_to(target))
        h.addWidget(back_btn)
        self._shortcut_widgets["back"] = back_btn
        h.addStretch()

        layout.addLayout(h)
        return h

    def _add_export_button(self, layout: QVBoxLayout, on_export, label: str = "Exportar Planilha"):
        btn = make_button(label, "positive")
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setFixedHeight(44)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(on_export)
        layout.addWidget(btn)
        return btn

    def _export_active_malote(self):
        from rac.export.excel_exporter import ExcelExporter

        if not self._mw.state.has_active_malote():
            self._toast("Selecione um malote primeiro!", "warning")
            return
        malote = self._mw.state.get_active_malote()
        exporter = ExcelExporter(self._mw.db)
        export_with_fallback(
            self,
            lambda: exporter.export_malote(malote.id),
            "Nenhum registro para exportar",
        )


def make_tab(margins=(16, 16, 16, 16), spacing=12):
    from PySide6.QtWidgets import QWidget, QVBoxLayout

    tab = QWidget()
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return tab, layout


def make_hbox(margins=(0, 0, 0, 0), spacing=8):
    from PySide6.QtWidgets import QHBoxLayout

    h = QHBoxLayout()
    h.setContentsMargins(*margins)
    h.setSpacing(spacing)
    return h


def _open_file_location(path: str):
    import subprocess
    import sys
    from pathlib import Path
    p = Path(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p.parent)])


def export_with_fallback(page, export_fn, no_data_msg="Nenhum dado para exportar"):
    from PySide6.QtWidgets import QFileDialog
    from pathlib import Path
    from rac.export.excel_exporter import SavePathError
    from andaime.error_handler import ErrorContext, ErrorHandler

    from rac.gui.widgets.toast import show_toast

    def _export_toast(path):
        show_toast(
            f"Exportado: {path}", "positive", page,
            path=path,
        )

    try:
        result = export_fn()
        if result:
            _export_toast(result)
        else:
            page._toast(no_data_msg, "warning")
    except SavePathError:
        folder = QFileDialog.getExistingDirectory(
            page, "Selecionar pasta para salvar", str(Path.home()),
        )
        if not folder:
            return
        page._mw.config.set("save_path", folder)
        try:
            result = export_fn()
            if result:
                _export_toast(result)
            else:
                page._toast(no_data_msg, "warning")
        except SavePathError as e:
            page._toast(f"Erro ao exportar: {e}", "negative")
    except Exception as e:
        ErrorHandler.handle_error(e, context=ErrorContext.EXPORT, show_dialog=False)
        page._toast(f"Erro ao exportar: {e}", "negative")
