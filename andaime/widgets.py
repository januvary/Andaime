"""PySide6 search-enabled combo box widget with accent-insensitive matching."""

from PySide6.QtCore import Qt, Signal, QTimer, QStringListModel, QEvent
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QWidget,
)

from andaime.text import normalize_text


class _SearchCompleter(QCompleter):
    def __init__(self, model, parent=None):
        super().__init__(model, parent)
        self._escape_pressed = False
        self._user_selected = False
        self._activated = False
        self._spurious_close = False
        self._reshow_count = 0
        self.activated.connect(lambda _: setattr(self, "_activated", True))

    def _is_spurious_hide(self, obj) -> bool:
        if obj is not self.popup():
            return False
        widget = self.widget()
        if not isinstance(widget, QLineEdit):
            return False
        if not widget.text().strip():
            return False
        if self._escape_pressed or self._user_selected or self._activated:
            return False
        if not self._spurious_close:
            return False
        if self._reshow_count >= 3:
            return False
        return True

    def _reshow(self):
        if self._escape_pressed or self._user_selected or self._activated:
            return
        widget = self.widget()
        if not isinstance(widget, QLineEdit) or not widget.text().strip():
            return
        self._reshow_count += 1
        super().complete()

    def eventFilter(self, obj, event):
        et = event.type()

        if et == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Escape:
                self._escape_pressed = True
        elif et == QEvent.Type.MouseButtonPress and obj is self.popup():
            self._user_selected = True
        elif et == QEvent.Type.Close and obj is self.popup():
            self._spurious_close = True

        if et == QEvent.Type.Hide and self._is_spurious_hide(obj):
            QTimer.singleShot(0, self._reshow)

        result = super().eventFilter(obj, event)

        if et == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self._escape_pressed = False

        return result

    def complete(self, rect=None):
        self._escape_pressed = False
        self._user_selected = False
        self._activated = False
        self._spurious_close = False
        self._reshow_count = 0
        if rect is not None:
            super().complete(rect)
        else:
            super().complete()


class SearchableComboBox(QWidget):
    selection_changed = Signal(object)
    exact_match_changed = Signal(object)

    def __init__(
        self,
        placeholder: str = "Buscar...",
        parent=None,
        on_search: object = None,
        on_delete_empty: object = None,
        min_chars: int = 0,
        max_results: int = 0,
        debounce_ms: int = 0,
    ):
        super().__init__(parent)
        self._on_search = on_search
        self._on_delete_empty = on_delete_empty
        self._min_chars = min_chars
        self._max_results = max_results
        self._debounce_ms = debounce_ms
        self._selected_key: str | None = None
        self._selected_label: str | None = None
        self._options: dict[str, str] = {}
        self._search_labels: dict[str, str] = {}
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        self._model = QStringListModel(self)
        self._completer = _SearchCompleter(self._model, self)
        if on_search:
            self._completer.setCompletionMode(
                QCompleter.CompletionMode.UnfilteredPopupCompletion
            )
        else:
            self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
            self._completer.setCompletionMode(
                QCompleter.CompletionMode.PopupCompletion
            )
            self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.activated.connect(self._on_activated)

        self._line_edit = QLineEdit()
        self._line_edit.setPlaceholderText(placeholder)
        self._line_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._line_edit.setCompleter(self._completer)
        self._line_edit.textEdited.connect(self._on_text_edited)
        self._line_edit.textChanged.connect(self._on_text_changed)
        self._line_edit.installEventFilter(self)

        layout.addWidget(self._line_edit)

    def set_options(self, options: dict[str, str]):
        self._options = options.copy()
        self._search_labels = {v: k for k, v in options.items()}
        self._model.setStringList(list(options.values()))
        if self._selected_key and self._selected_key in self._options:
            self._selected_label = self._options[self._selected_key]

    def current_data(self) -> str | None:
        return self._selected_key

    def set_current_by_data(self, data: str):
        label = self._options.get(data)
        if label is not None:
            self._selected_key = data
            self._selected_label = label
            self._line_edit.setText(label)

    def current_text(self) -> str:
        return self._line_edit.text()

    def focus_search(self):
        self._line_edit.setFocus()
        self._line_edit.selectAll()

    def clear(self):
        self._selected_key = None
        self._selected_label = None
        self._line_edit.clear()

    def add_option(self, key: str, label: str):
        self._options[key] = label
        self._search_labels[label] = key
        self._model.setStringList(list(self._options.values()))

    def eventFilter(self, obj, event):
        if (
            obj is self._line_edit
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Delete
            and self._line_edit.text().strip() == ""
            and self._on_delete_empty
        ):
            self._on_delete_empty()
            return True
        return super().eventFilter(obj, event)

    def _on_debounce_timeout(self):
        self._do_search(self._line_edit.text().strip())

    def _on_text_edited(self, text: str):
        if self._on_search:
            if self._debounce_ms > 0:
                self._debounce_timer.start(self._debounce_ms)
            else:
                self._do_search(text.strip())
        elif text:
            QTimer.singleShot(0, lambda: self._explicit_complete(text))
        else:
            popup = self._completer.popup()
            if popup:
                popup.hide()

    def _explicit_complete(self, text: str):
        self._completer.setCompletionPrefix(text)
        self._completer.complete()

    def _on_text_changed(self, text: str):
        if self._selected_label and text != self._selected_label:
            self._selected_key = None
            self._selected_label = None
            self.selection_changed.emit(None)

    def _on_activated(self, text: str):
        key = self._search_labels.get(text)
        if key is not None:
            self._selected_key = key
            self._selected_label = text
            self._line_edit.setText(text)
            self.selection_changed.emit(key)

    def _do_search(self, query: str):
        if not query:
            self._model.setStringList([])
            self._search_labels.clear()
            return
        if self._min_chars > 0 and len(query) < self._min_chars:
            return
        assert self._on_search is not None
        results = self._on_search(query)
        if results is None:
            return
        if self._max_results > 0:
            items = list(results.items())
            results = dict(items[: self._max_results])
        labels = list(results.values())
        self._search_labels = {v: k for k, v in results.items()}
        self._model.setStringList(labels)
        self._completer.setCompletionPrefix("")
        self._completer.complete()
        normalized_query = normalize_text(query)
        for key, label in results.items():
            if normalize_text(label) == normalized_query:
                self.exact_match_changed.emit(key)
                break
