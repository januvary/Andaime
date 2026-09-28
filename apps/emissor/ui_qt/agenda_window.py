#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AgendaWindow — calendário de retornos (Qt)."""

from __future__ import annotations

from functools import lru_cache

import calendar
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Signal, Qt
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


@lru_cache(maxsize=None)
def _load_special_dates(year: int, root: Path) -> frozenset[str]:
    """Feriados nacionais + facultativos para year; retorna frozenset YYYY-MM-DD."""
    from andaime.dates import DateCalculator

    return frozenset(
        dt.strftime("%Y-%m-%d")
        for dt in DateCalculator.get_holidays()
        if dt.year == year
    )


def _date_status_color(date_str: str, palette: dict[str, str]) -> tuple[str, str]:
    """Cor de célula conforme data (hoje, passado, futuro); retorna (bg, fg)."""
    today = datetime.now().strftime("%Y-%m-%d")
    if date_str < today:
        return "#d4946a", "white"
    if date_str == today:
        return "#88dceb", "#1f1f25"
    return "#9daec2", "white"


class _RetiradaDialog(QDialog):
    """Diálogo de seleção de retirada para uma data."""

    def __init__(
        self,
        parent: QWidget,
        date_str: str,
        retiradas: list[dict[str, Any]],
        save_location: Path,
        palette: dict[str, str],
        service: Any = None,
    ) -> None:
        super().__init__(parent)
        self._save_location = save_location
        self._palette = palette
        self._service = service

        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        self.setWindowTitle(f"Retiradas - {date_obj.strftime('%d/%m/%Y')}")
        self.setMinimumSize(800, 400)
        self.setStyleSheet(f"background-color: {palette['window_bg']};")

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        self.setLayout(layout)

        header = QLabel(f"Retiradas agendadas para {date_obj.strftime('%d/%m/%Y')}")
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

        for retirada in retiradas:
            content_layout.addWidget(self._build_retirada_card(retirada))

        content_layout.addStretch()

        close_btn = make_button("Fechar", "flat-fill", self)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def _build_retirada_card(self, retirada: dict[str, Any]) -> QFrame:
        """Constrói um card de retirada com nome, status e ações."""
        palette = self._palette
        status = retirada.get("status", "pendente")
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

        paciente_id = retirada.get("patient_id")
        nome = retirada.get("nome", "")
        name_btn = QPushButton(nome)
        name_btn.setStyleSheet(
            f"font-size: 13px; color: {palette['text']}; text-align: left;"
            f"background: transparent; border: none; padding: 0;"
        )
        name_btn.clicked.connect(
            lambda: self._show_paciente(paciente_id)
        )
        name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(name_btn, stretch=1)

        open_btn = make_button("Abrir PDF", "primary", self)
        open_btn.setFixedSize(100, 32)
        open_btn.clicked.connect(lambda: self._open_pdf(retirada.get("pdf_path", "")))
        row.addWidget(open_btn)

        if is_retirado and retirada.get("data_retirada"):
            retirada_date = datetime.strptime(
                retirada["data_retirada"], "%Y-%m-%d"
            ).strftime("%d/%m/%Y")
            retirada_path = retirada.get("retirada_pdf_path")
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

    def _show_paciente(self, paciente_id: int | None) -> None:
        """Abre o diálogo do paciente (todas as suas retiradas)."""
        if not paciente_id or not self._service:
            return
        dialog = _PacienteDialog(
            self, paciente_id, self._service, self._palette
        )
        dialog.exec()


class _PacienteDialog(QDialog):
    """Diálogo do paciente: lista todas as suas retiradas."""

    def __init__(
        self,
        parent: QWidget,
        paciente_id: int,
        service: Any,
        palette: dict[str, str],
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._palette = palette

        retiradas = service.get_patient_retiradas(paciente_id)
        paciente_name = retiradas[0].get("patient_name", "") if retiradas else ""
        self.setWindowTitle(f"Paciente: {paciente_name}")
        self.setMinimumSize(650, 400)
        self.setStyleSheet(f"background-color: {palette['window_bg']};")

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        self.setLayout(layout)

        header = QLabel(f"Retiradas — {len(retiradas)} encontrada(s)")
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

        for paciente in sorted(retiradas, key=lambda e: e["data_retirada"]):
            content_layout.addWidget(self._build_paciente_card(paciente))

        content_layout.addStretch()

        close_btn = make_button("Fechar", "flat-fill", self)
        close_btn.clicked.connect(self.reject)
        layout.addWidget(close_btn)

    def _build_paciente_card(self, paciente: dict[str, Any]) -> QFrame:
        """Constrói um card de paciente com data, status e ações."""
        palette = self._palette
        status = paciente.get("status", "pendente")
        is_retirado = status == "retirado"
        status_color = "#6cbd72" if is_retirado else "#c9916d"
        status_text = "RETIRADO" if is_retirado else "PENDENTE"
        data_retirada = paciente.get("data_retirada", "")
        data_proxima = paciente.get("data_proxima_retirada", "")
        data_retirada_fmt = (
            datetime.strptime(data_retirada, "%Y-%m-%d").strftime("%d/%m/%Y")
            if data_retirada
            else ""
        )
        data_proxima_fmt = (
            datetime.strptime(data_proxima, "%Y-%m-%d").strftime("%d/%m/%Y")
            if data_proxima
            else ""
        )

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

        date_btn = make_button(data_retirada_fmt, "primary", self)
        date_btn.setFixedSize(130, 32)
        date_btn.clicked.connect(
            lambda: self._open_pdf(paciente.get("pdf_path", ""))
        )
        row.addWidget(date_btn)

        proxima_label = QLabel(f"Próxima: {data_proxima_fmt}")
        proxima_label.setStyleSheet(
            f"color: {palette['text']}; font-size: 12px;"
        )
        row.addWidget(proxima_label, stretch=1)

        if is_retirado and paciente.get("data_retirada_real"):
            retirada_date = (
                datetime.strptime(paciente["data_retirada_real"], "%Y-%m-%d").strftime("%d/%m/%Y")
                if paciente["data_retirada_real"]
                else ""
            )
            retirada_path = paciente.get("retirada_pdf_path")
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
            save_root = self._service._save_root
            if save_root is not None:
                pdf_path = str(save_root / pdf_path)
        try:
            open_file(pdf_path)
        except (FileNotFoundError, OSError) as e:
            print(f"[ERRO] Falha ao abrir PDF: {e}")


class _CalendarView(QWidget):
    """Calendário 6 semanas (42 células) reutilizando widgets."""

    date_data_changed = Signal(dict)

    def __init__(
        self,
        parent: QWidget | None = None,
        service: Any = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
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
        flat = [d for week in cal for d in week]  # 42 cells, 0 = empty

        num_prev = sum(1 for d in flat[:7] if d == 0)
        num_actual = sum(1 for d in flat if d != 0)
        num_next = 42 - num_actual - num_prev

        _, prev_month_days = calendar.monthrange(prev_year, prev_month)
        prev_filler = list(range(prev_month_days - num_prev + 1, prev_month_days + 1))
        next_filler = list(range(1, num_next + 1))
        all_filler = prev_filler + next_filler

        date_strings = {
            d: f"{self._current_year}-{self._current_month:02d}-{d:02d}"
            for d in flat if d != 0
        }

        filler_idx = 0
        for btn_idx, day in enumerate(flat):
            btn = self._day_buttons[btn_idx]
            if day == 0:
                self._style_day(
                    btn,
                    str(all_filler[filler_idx]),
                    palette["panel_bg"],
                    palette["text_dim"],
                    palette["panel_border"],
                    "",
                )
                filler_idx += 1
                continue

            date_str = date_strings[day]
            patients = self._date_data.get(date_str, [])
            count = len(patients)
            is_special = date_str in special_dates

            if count > 0:
                bg_color, text_color = _date_status_color(date_str, palette)
                day_text = f"{day}\n{count} retirada{'s' if count > 1 else ''}"
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

        self._month_label.setText(
            f"{_MONTH_NAMES_PT[self._current_month]} {self._current_year}"
        )
        self.date_data_changed.emit(self._date_data)

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
        """Abre o diálogo de retiradas para o dia clicado."""
        btn = self.sender()
        if not isinstance(btn, QPushButton):
            return
        date_str = btn.property("date_str")
        if not date_str:
            return
        retiradas = self._date_data.get(date_str, [])
        if retiradas:
            self._show_retiradas(date_str, retiradas)

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

    def _show_retiradas(
        self, date_str: str, retiradas: list[dict[str, Any]]
    ) -> None:
        """Abre o diálogo de retiradas."""
        dialog = _RetiradaDialog(
            self, date_str, retiradas, self._save_location, self._palette,
            self._service,
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
        self.setWindowTitle("Agenda - Calendário de Retiradas")
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

        self._calendar = _CalendarView(self, service=self._service)
        self._calendar.set_root(self._root)
        self._calendar.set_save_location(self._save_location)
        self._calendar.set_palette(self._palette)
        self._calendar.set_date_data(self._date_data)
        layout.addWidget(self._calendar, stretch=1)

        self._stats_label = QLabel()
        self._stats_label.setStyleSheet(
            f"font-size: 12px; color: {self._palette['text_dim']};"
        )
        self._stats_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._stats_label)

        self._calendar.date_data_changed.connect(self._update_stats)
        self._update_stats(self._date_data)

    def _update_stats(self, date_data: dict[str, list[dict[str, Any]]]) -> None:
        """Atualiza o rótulo de estatísticas com o total de retornos."""
        total = sum(len(p) for p in date_data.values())
        self._stats_label.setText(f"Total de retornos: {total}")


def open_agenda(
    parent: QWidget, db: Any, config_manager: Any, root: Path
) -> AgendaWindow:
    """Abre AgendaWindow; retorna a janela exibida."""
    window = AgendaWindow(parent, db, config_manager, root)
    window.show()
    return window
