"""PySide6 search-enabled combo box widget with accent-insensitive matching."""

from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal, QStringListModel
from PySide6.QtWidgets import (
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from andaime.dates import parse_date
from andaime.text import scored_search_dict


SearchFn = Callable[[str], dict[str, str]]


def static_search_fn(options: dict[str, str]) -> SearchFn:
    """
    Retorna uma função de busca local accent/case insensitive.

    Args:
        options: Dicionário de opções (key -> label).

    Returns:
        Função que recebe uma query e retorna as opções filtradas.
    """
    def _search(query: str) -> dict[str, str]:
        if not query:
            return options.copy()
        # Filtra e ordena por relevância (prefixo antes de "contém").
        return scored_search_dict(options, query)

    return _search


class SearchableComboBox(QWidget):
    """
    Campo de busca com autocomplete.

    Recebe uma função `search_fn(query) -> dict[key, label]`. A busca é
    síncrona: o chamador decide se filtra um dict local ou consulta o banco.
    """

    selection_changed = Signal(object)

    def __init__(
        self,
        search_fn: SearchFn,
        placeholder: str = "Buscar...",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._search_fn = search_fn
        self._selected_key: str | None = None
        self._selected_label: str | None = None
        self._search_labels: dict[str, str] = {}

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        self._model = QStringListModel(self)
        self._completer = QCompleter(self._model, self)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.UnfilteredPopupCompletion
        )
        self._completer.activated.connect(self._on_activated)

        self._line_edit = QLineEdit()
        self._line_edit.setPlaceholderText(placeholder)
        self._line_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._line_edit.setCompleter(self._completer)
        self._line_edit.textEdited.connect(self._on_text_edited)
        self._line_edit.textChanged.connect(self._on_text_changed)

        layout.addWidget(self._line_edit)

    @property
    def line_edit(self) -> QLineEdit:
        """Acesso ao ``QLineEdit`` interno (ex.: para máscaras/formatação)."""
        return self._line_edit

    def set_search_fn(self, search_fn: SearchFn) -> None:
        """Atualiza a fonte de busca e reexecuta com o texto atual."""
        self._search_fn = search_fn
        self._update_model(self._line_edit.text().strip())

    def current_data(self) -> str | None:
        """Retorna a key selecionada."""
        return self._selected_key

    def set_current(self, data: str, label: str) -> None:
        """Seleciona uma key/label conhecida sem disparar busca."""
        self._selected_key = data
        self._selected_label = label
        self._line_edit.setText(label)

    def set_current_by_data(self, data: str) -> None:
        """Seleciona uma key sem disparar busca."""
        results = self._search_fn("")
        label = results.get(data)
        if label is not None:
            self._selected_key = data
            self._selected_label = label
            self._line_edit.setText(label)

    def set_text(self, text: str) -> None:
        """Define o texto do campo sem disparar busca.

        Atualiza o estado interno (``_selected_label``/``_selected_key``) ANTES
        de escrever no ``QLineEdit``: ``setText`` dispara ``textChanged``
        sincronamente e ``_on_text_changed`` compara o texto com
        ``_selected_label``. Se o rótulo fosse atualizado depois, um valor
        legado faria ``_on_text_changed`` emitir ``selection_changed(None)``
        espúrio durante uma seleção programática (ex.: trocar de paciente
        diretamente, sem passar por "vazio").
        """
        text = str(text) if text is not None else ""
        self._selected_key = None
        self._selected_label = text
        self._line_edit.setText(text)

    def current_text(self) -> str:
        """Retorna o texto atual do campo."""
        return self._line_edit.text()

    def focus_search(self) -> None:
        """Foca o campo e seleciona o texto."""
        self._line_edit.setFocus()
        self._line_edit.selectAll()

    def clear(self) -> None:
        """Limpa seleção e texto."""
        self._selected_key = None
        self._selected_label = None
        self._line_edit.clear()

    def _on_text_edited(self, text: str) -> None:
        self._update_model(text.strip(), show_popup=True)

    def _update_model(self, query: str, show_popup: bool = False) -> None:
        # A search_fn é a fonte da verdade sobre o que casa e em que ordem.
        # O widget NÃO refiltra pelo label (senão buscas por um campo que não
        # aparece no label — ex.: telefone — seriam descartadas).
        results = self._search_fn(query)
        self._search_labels = {v: k for k, v in results.items()}
        self._model.setStringList(list(results.values()))
        if show_popup:
            self._completer.setCompletionPrefix("")
            self._completer.complete()

    def _on_text_changed(self, text: str) -> None:
        if self._selected_label and text != self._selected_label:
            self._selected_key = None
            self._selected_label = None
            self.selection_changed.emit(None)

    def _on_activated(self, text: str) -> None:
        key = self._search_labels.get(text)
        if key is not None:
            self._selected_key = key
            self._selected_label = text
            self._line_edit.setText(text)
            self.selection_changed.emit(key)


import calendar
from datetime import date, timedelta


def _add_months(d: date, n: int) -> date:
    """Return ``d`` shifted by ``n`` months, clamping the day to the target month."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class DateLineEdit(QLineEdit):
    """Date entry that combines free typing with QDateEdit-style arrow stepping.

    Typed input is auto-formatted to ``DD/MM/YYYY`` (slashes inserted as digits
    are entered, with a ``DD/MM/YYYY`` placeholder when empty). Pressing
    Up/Down steps the day/month/year under the cursor -- like QDateEdit's
    section editing -- without giving up the text-field typing experience.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("DD/MM/YYYY")
        self.textEdited.connect(self._on_text_edited)

    @staticmethod
    def _format(text: str) -> str:
        digits = "".join(c for c in text if c.isdigit())[:8]
        if len(digits) <= 2:
            return digits
        if len(digits) <= 4:
            return f"{digits[:2]}/{digits[2:]}"
        return f"{digits[:2]}/{digits[2:4]}/{digits[4:]}"

    def _on_text_edited(self, text: str) -> None:
        formatted = self._format(text)
        if formatted == text:
            return
        digits_before = sum(
            1 for c in text[: self.cursorPosition()] if c.isdigit()
        )
        cursor = 0
        seen = 0
        for ch in formatted:
            if ch.isdigit():
                seen += 1
                if seen > digits_before:
                    break
            cursor += 1
        self.blockSignals(True)
        self.setText(formatted)
        self.blockSignals(False)
        self.setCursorPosition(cursor)

    def keyPressEvent(self, event: Any) -> None:
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self._step(
            event.key() == Qt.Key.Key_Up
        ):
            event.accept()
            return
        super().keyPressEvent(event)

    def _step(self, up: bool) -> bool:
        pos = self.cursorPosition()
        if pos <= 2:
            field, start, length = "day", 0, 2
        elif pos <= 5:
            field, start, length = "month", 3, 2
        else:
            field, start, length = "year", 6, 4
        current = parse_date(self.text()) or date.today()
        sign = 1 if up else -1
        if field == "day":
            new = current + timedelta(days=sign)
        elif field == "month":
            new = _add_months(current, sign)
        else:
            new = _add_months(current, 12 * sign)
        self.setText(new.strftime("%d/%m/%Y"))
        self.setSelection(start, length)
        return True


class CycleButton(QPushButton):
    def __init__(
        self,
        label: str,
        role: str,
        *,
        modulus: int,
        base: int,
        initial: int,
        width: int = 40,
        font_size: int = 14,
        format_fn=None,
        on_change=None,
    ):
        super().__init__(label)
        self.setProperty("btnrole", role)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(width)
        self.setStyleSheet(f"padding: 9px 0; font-size: {font_size}px; font-weight: 600;")
        self._modulus = modulus
        self._base = base
        self._value = initial
        self._format_fn = format_fn
        self._on_change = on_change

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self._value = ((self._value - self._base - 1) % self._modulus) + self._base
        else:
            self._value = ((self._value - self._base + 1) % self._modulus) + self._base
        self._apply_label()
        self.setDown(True)
        QTimer.singleShot(120, lambda: self.setDown(False))
        if self._on_change:
            self._on_change(self._value)
        super().mousePressEvent(event)

    def _apply_label(self):
        self.setText(self._format_fn(self._value) if self._format_fn else str(self._value))

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, v: int):
        self._value = v
        self._apply_label()
