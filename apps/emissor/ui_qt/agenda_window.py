#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgendaWindow — Visualizador de Calendário de Retornos (Qt).

Janela interna do Emissor. Compartilha a conexão de banco e configuração
com a aplicação principal.
"""

from __future__ import annotations

import calendar
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from emissor.services.agenda_service import AgendaService
from emissor.ui_qt.theme import DARK, get_palette, make_button
from emissor.utils.file_utils import open_file

_MONTH_NAMES_PT = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


_HOLIDAY_BORDER_COLOR = "#d4af37"


def _load_special_dates(year: int, root: Path) -> set[str]:
    """
    Carrega feriados nacionais e pontos facultativos para o ano.

    Args:
        year: Ano de referência.
        root: Raiz do projeto (mantido para compatibilidade de assinatura).

    Returns:
        Conjunto de datas no formato YYYY-MM-DD.
    """
    from andaime.dates import DateCalculator

    special: set[str] = set()
    for dt in DateCalculator.get_holidays():
        if dt.year == year:
            special.add(dt.strftime("%Y-%m-%d"))
    return special


def _date_status_color(date_str: str, palette: dict[str, str]) -> tuple[str, str]:
    """
    Retorna (cor_fundo, cor_texto) para uma célula de dia conforme a data.

    Args:
        date_str: Data no formato YYYY-MM-DD.
        palette: Paleta de cores atual.

    Returns:
        Tupla (cor_fundo, cor_texto).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if date_str < today:
        return "#d4946a", "white"
    if date_str == today:
        return "#88dceb", "#1f1f25"
    return "#9daec2", "white"


class _PatientDialog(QDialog):
    """
    Diálogo com a lista de pacientes para uma data selecionada.
    """

    def __init__(
        self,
        parent: QWidget,
        date_str: str,
        patients: list[dict[str, Any]],
        save_location: Path,
        palette: dict[str, str],
    ) -> None:
        super().__init__(parent)
        self._save_location = save_location
        self._palette = palette

        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        self.setWindowTitle(f"Pacientes - {date_str}")
        self.setMinimumSize(800, 400)
        self.setStyleSheet(f"background-color: {palette['window_bg']};")

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        self.setLayout(layout)

        header = QLabel(f"Retornos agendados para {date_obj.strftime('%d/%m/%Y')}")
        header.setStyleSheet(f"font-size: 16px; color: {palette['text']};")
        layout.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background-color: transparent; border: none;")
        layout.addWidget(scroll)

        content = QWidget()
        content.setStyleSheet(f"background-color: {palette['window_bg']};")
        content_layout = QVBoxLayout()
        content_layout.setSpacing(8)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content.setLayout(content_layout)
        scroll.setWidget(content)

        for patient in patients:
            content_layout.addWidget(self._build_patient_card(patient))

        content_layout.addStretch()

        close_btn = make_button("Fechar", "flat-fill", self)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def _build_patient_card(self, patient: dict[str, Any]) -> QFrame:
        """Constrói um card de paciente com nome, status e ações."""
        palette = self._palette
        status = patient.get("status", "pendente")
        is_retirado = status == "retirado"

        status_color = "#6cbd72" if is_retirado else "#c9916d"
        status_text = "RETIRADO" if is_retirado else "PENDENTE"

        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {palette['panel_bg']};
            }}
            """)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.setContentsMargins(12, 10, 12, 10)
        card.setLayout(row)

        name_label = QLabel(patient.get("nome", ""))
        name_label.setStyleSheet(f"font-size: 13px; color: {palette['text']};")
        row.addWidget(name_label, stretch=1)

        open_btn = make_button("Abrir PDF", "primary", self)
        open_btn.setFixedSize(100, 32)
        open_btn.clicked.connect(lambda: self._open_pdf(patient.get("pdf_path", "")))
        row.addWidget(open_btn)

        if is_retirado and patient.get("data_retirada"):
            retirada_date = datetime.strptime(
                patient["data_retirada"], "%Y-%m-%d"
            ).strftime("%d/%m/%Y")
            retirada_path = patient.get("retirada_pdf_path")
            if retirada_path:
                info_btn = make_button(f"Retirado em: {retirada_date}", "flat-fill", self)
                info_btn.clicked.connect(lambda: self._open_pdf(retirada_path))
                row.addWidget(info_btn)
            else:
                info_label = QLabel(f"Retirado em: {retirada_date}")
                info_label.setStyleSheet(
                    f"color: {palette['text_dim']}; font-size: 10px;"
                )
                row.addWidget(info_label)

        status_label = QLabel(status_text)
        status_label.setMinimumWidth(90)
        status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_label.setStyleSheet(
            f"font-weight: bold; font-size: 11px; color: {palette['panel_bg']};"
            f"background-color: {status_color}; border-radius: 4px; padding: 2px 6px;"
        )
        row.addWidget(status_label)

        return card

    def _open_pdf(self, pdf_path: str) -> None:
        """Abre PDF relativo ou absoluto."""
        if not pdf_path:
            return
        path_obj = Path(pdf_path)
        if not path_obj.is_absolute():
            pdf_path = str(self._save_location / pdf_path)
        try:
            open_file(pdf_path)
        except (FileNotFoundError, OSError) as e:
            print(f"[ERRO] Falha ao abrir PDF: {e}")


class _CalendarView(QWidget):
    """
    Grade de calendário com 6 semanas (42 células) reutilizando os widgets.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._date_data: dict[str, list[dict[str, Any]]] = {}
        self._current_month = datetime.now().month
        self._current_year = datetime.now().year
        self._palette = get_palette(True)
        self._day_buttons: list[QPushButton] = []
        self._root = Path(__file__).resolve().parent.parent.parent
        self._save_location: Path = self._root
        self._setup_ui()
        self._update_calendar()

    def set_save_location(self, save_location: Path) -> None:
        """Define o local de salvamento real (vem da configuração)."""
        self._save_location = Path(save_location)

    def set_date_data(self, date_data: dict[str, list[dict[str, Any]]]) -> None:
        """Atualiza os dados de retornos e redesenha."""
        self._date_data = date_data
        self._update_calendar()

    def set_palette(self, palette: dict[str, str]) -> None:
        """Aplica nova paleta ao calendário."""
        self._palette = palette
        self._update_calendar()

    def set_root(self, root: Path) -> None:
        """Atualiza a raiz para carga de pontos facultativos."""
        self._root = root
        self._update_calendar()

    def _setup_ui(self) -> None:
        """Monta header e grade de dias."""
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)

        header = QHBoxLayout()
        header.setSpacing(12)

        self._prev_btn = make_button("◀ Anterior", "flat-fill", self)
        self._prev_btn.setFixedSize(100, 36)
        self._prev_btn.clicked.connect(self._prev_month)
        header.addWidget(self._prev_btn)

        self._month_label = QLabel()
        self._month_label.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {self._palette['text']};"
        )
        self._month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._month_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        header.addWidget(self._month_label, stretch=1)

        self._next_btn = make_button("Próximo ▶", "flat-fill", self)
        self._next_btn.setFixedSize(100, 36)
        self._next_btn.clicked.connect(self._next_month)
        header.addWidget(self._next_btn)

        layout.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setContentsMargins(0, 0, 0, 0)

        day_headers = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]
        for col, day in enumerate(day_headers):
            label = QLabel(day)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(
                f"font-weight: bold; color: {self._palette['text_dim']}; padding: 4px;"
            )
            grid.addWidget(label, 0, col)

        for idx in range(42):
            row = (idx // 7) + 1
            col = idx % 7
            btn = QPushButton()
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            btn.setMinimumSize(40, 50)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setProperty("class", "flat-fill")
            btn.setProperty("date_str", "")
            btn.clicked.connect(self._on_day_clicked)
            grid.addWidget(btn, row, col)
            self._day_buttons.append(btn)

        for i in range(7):
            grid.setColumnStretch(i, 1)
        for i in range(1, 7):
            grid.setRowStretch(i, 1)

        layout.addLayout(grid)

    def _update_calendar(self) -> None:
        """Redesenha o calendário para o mês/ano atual."""
        palette = self._palette
        calendar.setfirstweekday(calendar.SUNDAY)
        cal = calendar.monthcalendar(self._current_year, self._current_month)
        special_dates = _load_special_dates(self._current_year, self._root)

        prev_month = self._current_month - 1 if self._current_month > 1 else 12
        prev_year = (
            self._current_year if self._current_month > 1 else self._current_year - 1
        )
        _, prev_month_days = calendar.monthrange(prev_year, prev_month)

        first_week = cal[0]
        num_prev_days = sum(1 for d in first_week if d == 0)
        prev_days_to_show = (
            list(range(prev_month_days - num_prev_days + 1, prev_month_days + 1))
            if num_prev_days > 0
            else []
        )

        date_strings = {}
        for week in cal:
            for day in week:
                if day != 0:
                    date_strings[day] = (
                        f"{self._current_year}-{self._current_month:02d}-{day:02d}"
                    )

        button_idx = 0
        prev_day_idx = 0
        next_day = 1

        for week in cal:
            for day in week:
                btn = self._day_buttons[button_idx]
                button_idx += 1

                if day == 0:
                    if prev_day_idx < len(prev_days_to_show):
                        other_day = prev_days_to_show[prev_day_idx]
                        prev_day_idx += 1
                    else:
                        other_day = next_day
                        next_day += 1
                    self._style_day(
                        btn,
                        str(other_day),
                        palette["panel_bg"],
                        palette["text_dim"],
                        palette["panel_border"],
                        "",
                    )
                    continue

                date_str = date_strings[day]
                patients = self._date_data.get(date_str, [])
                count = len(patients)
                is_special = date_str in special_dates

                if count > 0:
                    bg_color, text_color = _date_status_color(date_str, palette)
                    day_text = f"{day}\n{count} paciente{'s' if count > 1 else ''}"
                else:
                    bg_color = palette["input_bg"]
                    text_color = palette["text"]
                    day_text = str(day)

                if is_special:
                    border_color = _HOLIDAY_BORDER_COLOR
                    border_width = 3 if palette is not DARK else 2
                elif count == 0:
                    border_color = palette["input_border"]
                    border_width = 1
                else:
                    border_color = bg_color
                    border_width = 1

                self._style_day(
                    btn,
                    day_text,
                    bg_color,
                    text_color,
                    border_color,
                    date_str,
                    border_width,
                )

        while button_idx < 42:
            btn = self._day_buttons[button_idx]
            button_idx += 1
            self._style_day(
                btn,
                str(next_day),
                palette["panel_bg"],
                palette["text_dim"],
                palette["panel_border"],
                "",
            )
            next_day += 1

        self._month_label.setText(
            f"{_MONTH_NAMES_PT[self._current_month]} {self._current_year}"
        )

    def _style_day(
        self,
        btn: QPushButton,
        text: str,
        bg_color: str,
        text_color: str,
        border_color: str,
        date_str: str,
        border_width: int = 1,
    ) -> None:
        """Aplica estilo e data a uma célula de dia."""
        btn.setText(text)
        btn.setProperty("date_str", date_str)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg_color};
                color: {text_color};
                border: {border_width}px solid {border_color};
                border-radius: 4px;
                padding: 4px;
                font-size: 13px;
                text-align: center;
            }}
            QPushButton:hover {{
                background-color: {border_color};
            }}
            """)

    def _on_day_clicked(self) -> None:
        """Abre o diálogo de pacientes para o dia clicado."""
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        date_str = btn.property("date_str")
        if not date_str:
            return
        patients = self._date_data.get(date_str, [])
        if patients:
            self._show_patients(date_str, patients)

    def _prev_month(self) -> None:
        """Navega para o mês anterior."""
        if self._current_month == 1:
            self._current_month = 12
            self._current_year -= 1
        else:
            self._current_month -= 1
        self._update_calendar()

    def _next_month(self) -> None:
        """Navega para o próximo mês."""
        if self._current_month == 12:
            self._current_month = 1
            self._current_year += 1
        else:
            self._current_month += 1
        self._update_calendar()

    def _show_patients(self, date_str: str, patients: list[dict[str, Any]]) -> None:
        """Abre o diálogo de pacientes."""
        dialog = _PatientDialog(
            self, date_str, patients, self._save_location, self._palette
        )
        dialog.exec()


class AgendaWindow(QMainWindow):
    """Janela principal da Agenda interna."""

    def __init__(
        self,
        parent: QWidget | None,
        db: Any,
        config_manager: Any,
        root: Path,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._config_manager = config_manager
        self._root = root
        self.setWindowTitle("Agenda - Calendário de Retornos")
        self.setMinimumSize(1000, 700)

        dark_mode = bool(self._config_manager.get("dark_mode", True))
        self._palette = get_palette(dark_mode)

        save_location = self._config_manager.get("save_location")
        if not save_location:
            print("[ERRO] Local de salvamento não configurado.")
            self.close()
            return

        self._save_location = Path(save_location)
        self._service = AgendaService(
            self._db, self._save_location
        )
        self._date_data = self._service.get_appointments_by_date()
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Monta a UI principal."""
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        central.setLayout(layout)

        self._calendar = _CalendarView(self)
        self._calendar.set_root(self._root)
        self._calendar.set_save_location(self._save_location)
        self._calendar.set_palette(self._palette)
        self._calendar.set_date_data(self._date_data)
        layout.addWidget(self._calendar, stretch=1)

        total = sum(len(p) for p in self._date_data.values())
        self._stats_label = QLabel(f"Total de retornos: {total}")
        self._stats_label.setStyleSheet(
            f"font-size: 12px; color: {self._palette['text_dim']};"
        )
        self._stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._stats_label)


def open_agenda(
    parent: QWidget, db: Any, config_manager: Any, root: Path
) -> AgendaWindow:
    """
    Abre a janela da Agenda.

    Args:
        parent: Widget pai.
        db: Instância do banco de dados.
        config_manager: Gerenciador de configuração.
        root: Raiz do projeto.

    Returns:
        A janela da Agenda já exibida.
    """
    window = AgendaWindow(parent, db, config_manager, root)
    window.show()
    return window
