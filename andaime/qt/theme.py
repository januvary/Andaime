"""Tema Qt neutro compartilhado (andaime.qt).

Paleta light/dark em tons de cinza (sem azul/verde/vermelho) + QPalette
nativa + QSS global, além de ``ThemeToggleButton`` e ``make_button``.

As chaves da paleta seguem o esquema do Emissor (``window_bg``,
``panel_bg``, ``panel_header_bg``, ``panel_border``, ``box_bg``, ``text``,
``text_dim``, ``input_bg``, ``input_border``, ``btn_*``, ``action_*``,
``status_*``, ``date_*``). Chaves extras usadas pelo SS-54 (``bg_hover``,
``bg_pressed``, ``border_light``, ``text_secondary``, ``selection_*``,
``separador``, ``gridline``, ``scrollbar*``, ``toast_*``) foram agregadas
com nomes consistentes. O foreground dos toasts positive/warning/negative
é deduplicado em ``status_success``/``status_warning``/``status_error``
(apenas ``toast_info_fg`` permanece próprio); ver ``_build_qss``.
"""

from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton

# ============================================================================
# Fonte base por plataforma
# ============================================================================


def _platform_font() -> str:
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "DejaVu Sans"


FONT_FAMILY = _platform_font()

PX = 13
PX_SMALL = 12
PX_HEADER = 14
PX_LARGE = 16


# ============================================================================
# Paletas (light / dark) — tons de cinza, sem cores de destaque
# ============================================================================

# ---- Chaves neutras e semânticas (fonte única para o modelo de rampa) ----
SURFACE_KEYS: tuple[str, ...] = (
    "window_bg",
    "panel_bg",
    "panel_header_bg",
    "box_bg",
    "panel_border",
    "border_light",
    "input_bg",
    "input_border",
    "text",
    "text_dim",
    "text_secondary",
    "bg_hover",
    "bg_pressed",
    "selection_bg",
    "selection_text",
    "separador",
    "gridline",
    "scrollbar",
    "scrollbar_hover",
    "date_editable",
    "date_calc_1",
    "date_calc_2",
    "btn_flat_hover",
    "btn_flat_fill",
    "btn_flat_fill_hover",
    "btn_primary",
    "btn_primary_hover",
    "action_1",
    "action_2",
    "action_3",
    "action_4",
    "action_5",
)

SEMANTIC_KEYS: tuple[str, ...] = (
    "status_success",
    "status_warning",
    "status_error",
    "toast_positive_bg",
    "toast_warning_bg",
    "toast_negative_bg",
    "toast_info_fg",
    "toast_info_bg",
    "brasao_ink",
)

# Comentários inline preservados por nível ao gravar _LEVELS.
LEVEL_COMMENTS: dict[int, str] = {
    1: "preto profundo",
    2: "tinta quase-preta",
    3: "tinta (ink)",
    4: "tinta esmaecida",
    5: "linhas / bordas",
    6: "preenchimentos",
    7: "hover",
    8: "superfície baixa",
    9: "superfície média",
    10: "superfície alta",
    11: "branco quase-puro",
    12: "branco puro",
}


# ---- Rampa neutra (fonte da verdade das superfícies) ----
# Cada modo tem 2 extremos (escuro, claro). As superfícies não guardam cor
# própria: cada papel (role) aponta para um NÍVEL numerado (1..12), e cada
# nível é uma posição t na rampa (0=papel escuro, 1=papel claro). DARK usa
# (1 - t), i.e. o modo escuro é o negativo fotográfico da rampa.
#
# Ajustar um nível remaneja todos os papéis nele; trocar o nível de um papel
# realoca só aquele papel. É só isso que define toda a paleta neutra.
_RAMP: dict[str, tuple[str, str]] = {
    "LIGHT": ("#0c2a2c", "#faffff"),
    "DARK": ("#252b37", "#fcfff0"),
}

# Nível -> posição t na rampa (do mais escuro ao mais claro).
_LEVELS: dict[int, float] = {
    1: -0.4,  # preto profundo
    2: -0.15,  # tinta quase-preta
    3: 0.0023,  # tinta (ink)
    4: 0.2609,  # tinta esmaecida
    5: 0.7245,  # linhas / bordas
    6: 0.8023,  # preenchimentos
    7: 0.9004,  # hover
    8: 0.9322,  # superfície baixa
    9: 0.9625,  # superfície média
    10: 1.0,  # superfície alta
    11: 1.11,  # branco quase-puro
    12: 1.2,  # branco puro
}

# Papel (role) -> nível, por modo (Light/Dark).
_ROLE_LEVEL: dict[str, dict[str, int]] = {
    "LIGHT": {
        "text": 1,
        "text_secondary": 3,
        "selection_text": 3,
        "text_dim": 4,
        "panel_border": 5,
        "input_border": 5,
        "bg_pressed": 5,
        "selection_bg": 5,
        "separador": 5,
        "scrollbar_hover": 5,
        "border_light": 6,
        "gridline": 6,
        "scrollbar": 6,
        "panel_header_bg": 7,
        "bg_hover": 7,
        "btn_flat_hover": 7,
        "panel_bg": 8,
        "date_calc_1": 8,
        "btn_flat_fill_hover": 8,
        "btn_primary_hover": 8,
        "action_2": 8,
        "date_calc_2": 9,
        "btn_primary": 9,
        "action_1": 9,
        "action_3": 9,
        "window_bg": 10,
        "date_editable": 10,
        "btn_flat_fill": 10,
        "action_4": 10,
        "action_5": 10,
        "box_bg": 12,
        "input_bg": 12,
    },
    "DARK": {
        "text": 1,
        "text_secondary": 3,
        "selection_text": 3,
        "text_dim": 4,
        "panel_border": 5,
        "input_border": 5,
        "bg_pressed": 5,
        "selection_bg": 5,
        "separador": 5,
        "scrollbar_hover": 5,
        "border_light": 6,
        "gridline": 6,
        "scrollbar": 6,
        "bg_hover": 7,
        "btn_flat_hover": 7,
        "panel_bg": 8,
        "panel_header_bg": 8,
        "date_calc_1": 8,
        "btn_flat_fill_hover": 8,
        "btn_primary_hover": 8,
        "action_2": 8,
        "date_calc_2": 9,
        "btn_primary": 9,
        "action_1": 9,
        "action_3": 9,
        "window_bg": 10,
        "box_bg": 10,
        "input_bg": 10,
        "date_editable": 10,
        "btn_flat_fill": 10,
        "action_4": 10,
        "action_5": 10,
    },
}

_SEMANTIC: dict[str, dict[str, str]] = {
    "LIGHT": {
        "status_success": "#14d57c",
        "status_warning": "#c29b35",
        "status_error": "#cb3c48",
        "toast_positive_bg": "#f0fff0",
        "toast_warning_bg": "#fffff0",
        "toast_negative_bg": "#fde1d7",
        "toast_info_fg": "#7662af",
        "toast_info_bg": "#f3f3ff",
        "brasao_ink": "#342a2c",
    },
    "DARK": {
        "status_success": "#6bca86",
        "status_warning": "#f0b580",
        "status_error": "#ff5376",
        "toast_positive_bg": "#005a3c",
        "toast_warning_bg": "#5a3c28",
        "toast_negative_bg": "#503200",
        "toast_info_fg": "#bbd6ff",
        "toast_info_bg": "#2b2b49",
        "brasao_ink": "#ddf5e4",
    },
}


def _lerp_hex(lo: str, hi: str, t: float) -> str:
    """Interpola linearmente entre dois hex #rrggbb na posição t."""
    a = [int(lo[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(hi[i : i + 2], 16) for i in (1, 3, 5)]
    c = [max(0, min(255, round(a[i] + (b[i] - a[i]) * t))) for i in range(3)]
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


def _build_palette(mode: str) -> dict[str, str]:
    """Gera a paleta do modo a partir da rampa + semânticas literais."""
    lo, hi = _RAMP[mode]
    flip = mode == "DARK"
    pal = {}
    for role, level in _ROLE_LEVEL[mode].items():
        t = _LEVELS[level]
        pal[role] = _lerp_hex(lo, hi, (1 - t) if flip else t)
    pal.update(_SEMANTIC[mode])
    return pal


LIGHT: dict[str, str] = _build_palette("LIGHT")
DARK: dict[str, str] = _build_palette("DARK")


# ============================================================================
# Estado de tema (nível de módulo; persistência é responsabilidade do app)
# ============================================================================

_current_theme: str = "dark"


def set_theme(theme: str) -> None:
    global _current_theme
    _current_theme = theme


def get_theme() -> str:
    return _current_theme


def toggle_theme() -> str:
    global _current_theme
    _current_theme = "light" if _current_theme == "dark" else "dark"
    return _current_theme


def colors() -> dict[str, str]:
    """Paleta atual (dict de chaves unificadas)."""
    return DARK if _current_theme == "dark" else LIGHT


def get_palette(dark_mode: bool = True) -> dict[str, str]:
    return DARK if dark_mode else LIGHT


def qpalette(palette: dict[str, str]) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(palette["window_bg"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(palette["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(palette["input_bg"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(palette["panel_bg"]))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(palette["panel_bg"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(palette["text"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(palette["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(palette["panel_header_bg"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(palette["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(palette["selection_bg"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(palette["selection_text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(palette["text_dim"]))
    pal.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(palette["text_dim"]),
    )
    pal.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(palette["text_dim"]),
    )
    return pal


# ============================================================================
# QSS global (gerado a partir da paleta)
# ============================================================================


def get_stylesheet(theme: Optional[str] = None) -> str:
    resolved = theme or _current_theme
    c = DARK if resolved == "dark" else LIGHT
    return _build_qss(c)


# Alias (Emissor usa stylesheet())
stylesheet = get_stylesheet


def _build_qss(c: dict) -> str:
    return f"""
    * {{
        font-family: "{FONT_FAMILY}";
        font-size: {PX}px;
        color: {c["text"]};
    }}

    QWidget#central {{
        background-color: {c["window_bg"]};
    }}

    QDialog {{
        background-color: {c["window_bg"]};
    }}

    /* ===== Títulos / labels ===== */
    QLabel[heading="true"] {{
        font-size: {PX_LARGE}px;
        font-weight: 600;
        color: {c["text"]};
        padding: 0px;
        margin: 0px;
    }}
    QLabel[heading="section"] {{
        font-size: {PX_HEADER}px;
        font-weight: 600;
        color: {c["text_dim"]};
        padding: 0px;
        margin: 0px;
    }}
    QLabel[class="dim"] {{
        color: {c["text_dim"]};
        font-size: {PX_SMALL}px;
    }}
    QLabel[class="panel-title"] {{
        font-size: {PX_HEADER}px;
        font-weight: 600;
        color: {c["text"]};
        padding: 0px;
    }}
    QLabel[batchlabel="true"] {{
        color: {c["text"]};
        font-size: 20px;
        font-weight: 500;
    }}
    QTreeWidget[class="remessa-tree"] {{
        border: none;
        background-color: {c["panel_bg"]};
        alternate-background-color: {c["window_bg"]};
        font-size: 16px;
    }}

    /* ===== Painéis ===== */
    QFrame[class="panel"] {{
        background-color: {c["panel_bg"]};
        border: 1px solid {c["panel_border"]};
        border-radius: 4px;
    }}
    QFrame[class="panel-header"] {{
        background-color: {c["panel_header_bg"]};
        border: none;
        border-bottom: 1px solid {c["panel_border"]};
        padding: 6px 12px;
    }}
    QFrame[class="panel-header"][seamless="true"] {{
        border-bottom: none;
    }}
    QFrame[class="panel-footer"] {{
        background-color: {c["panel_header_bg"]};
        border: none;
        border-top: 1px solid {c["panel_border"]};
        padding: 6px 12px;
    }}
    QFrame[class="box"] {{
        background-color: {c["box_bg"]};
        border: 1px solid {c["panel_border"]};
        border-radius: 4px;
    }}
    QFrame[class="date-box-1"] {{
        background-color: {c["date_editable"]};
        border-radius: 4px;
        border: 1px solid {c["panel_border"]};
    }}
    QFrame[class="date-box-2"] {{
        background-color: {c["date_calc_1"]};
        border-radius: 4px;
        border: 1px solid {c["panel_border"]};
    }}
    QFrame[class="date-box-3"] {{
        background-color: {c["date_calc_2"]};
        border-radius: 4px;
        border: 1px solid {c["panel_border"]};
    }}
    QFrame[separador="true"] {{
        background-color: {c["separador"]};
        max-height: 1px;
        border: none;
    }}

    /* ===== Inputs ===== */
    QLineEdit, QTextEdit, QSpinBox, QComboBox, QDateEdit {{
        border: 1px solid {c["input_border"]};
        border-radius: 4px;
        padding: 5px 8px;
        background-color: {c["input_bg"]};
        color: {c["text"]};
        font-size: {PX}px;
        min-height: 22px;
        selection-background-color: {c["selection_bg"]};
        selection-color: {c["selection_text"]};
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDateEdit:focus {{
        border-color: {c["btn_primary"]};
    }}
    QLineEdit:read-only {{
        background: transparent;
        border: none;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        width: 14px;
        border: none;
        background: transparent;
    }}
    QSpinBox::up-button {{ border-bottom: 1px solid {c["input_border"]}; }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background: {c["btn_flat_hover"]};
    }}
    QSpinBox::up-arrow, QSpinBox::down-arrow {{
        width: 5px; height: 5px;
    }}

    /* ===== ComboBox (autocomplete) ===== */
    QComboBox::drop-down {{ border: none; width: 0px; }}
    QComboBox::down-arrow {{ image: none; width: 0px; border: none; }}
    QComboBox QAbstractItemView {{
        border: 1px solid {c["border_light"]};
        border-radius: 4px;
        background-color: {c["panel_bg"]};
        color: {c["text"]};
        selection-background-color: {c["selection_bg"]};
        selection-color: {c["selection_text"]};
        outline: none;
        padding: 2px;
    }}
    QComboBox QAbstractItemView::item {{
        padding: 6px 10px;
        min-height: 22px;
        color: {c["text"]};
    }}

    /* ===== CheckBox / RadioButton ===== */
    QCheckBox::indicator {{
        width: 18px; height: 18px;
        border: 1px solid {c["input_border"]};
        border-radius: 3px;
        background: {c["input_bg"]};
    }}
    QCheckBox::indicator:checked {{
        background: {c["text_dim"]};
        border-color: {c["text_dim"]};
    }}
    QCheckBox::indicator:disabled {{
        border: 1px solid {c["text_dim"]};
        background: transparent;
    }}
    QRadioButton::indicator {{
        width: 16px; height: 16px;
        border: 1px solid {c["input_border"]};
        border-radius: 8px;
        background: {c["input_bg"]};
    }}
    QRadioButton::indicator:checked {{
        background: {c["btn_primary"]};
        border-color: {c["btn_primary"]};
    }}
    QRadioButton {{ spacing: 6px; }}
    QRadioButton:disabled, QCheckBox:disabled {{
        color: {c["text_dim"]};
    }}
    QRadioButton::indicator:disabled {{
        border: 1px solid {c["text_dim"]};
        background: transparent;
    }}

    /* ===== Botões (roles via class) =====
       Sem class = flat (padrão): transparente + borda + hover neutro. */
    QPushButton {{
        background-color: transparent;
        border: 1px solid {c["panel_border"]};
        border-radius: 4px;
        padding: 6px 16px;
        font-size: {PX}px;
        font-weight: 500;
        color: {c["text"]};
        min-height: 22px;
    }}
    QPushButton:hover {{ background-color: {c["bg_hover"]}; }}
    QPushButton:pressed {{ background-color: {c["bg_pressed"]}; }}
    QPushButton:disabled {{
        color: {c["text_dim"]};
        border-color: {c["panel_border"]};
    }}

    QPushButton[class="primary"] {{
        background-color: {c["btn_primary"]};
        border: none;
        color: {c["text"]};
    }}
    QPushButton[class="primary"]:hover {{ background-color: {c["btn_primary_hover"]}; }}
    QPushButton[class="primary"]:disabled {{
        background-color: {c["panel_header_bg"]};
        color: {c["text_dim"]};
    }}

    QPushButton[class="flat"] {{
        background-color: transparent;
        border: 1px solid {c["panel_border"]};
        color: {c["text_dim"]};
    }}
    QPushButton[class="flat"]:hover {{
        background-color: {c["bg_hover"]};
        color: {c["text"]};
    }}

    QPushButton[class="flat-fill"] {{
        background-color: {c["btn_flat_fill"]};
    }}
    QPushButton[class="flat-fill"]:hover {{ background-color: {c["btn_flat_fill_hover"]}; }}

    QPushButton[class="icon"] {{
        background-color: transparent;
        border: none;
        padding: 0px;
        font-size: {PX_HEADER}px;
    }}
    QPushButton[class="icon"]:hover {{
        background-color: {c["bg_hover"]};
        border-radius: 4px;
    }}

    QPushButton[class="action-1"],
    QPushButton[class="action-2"],
    QPushButton[class="action-3"],
    QPushButton[class="action-4"],
    QPushButton[class="action-5"] {{
        background-color: {c["action_1"]};
        border: 1px solid {c["panel_border"]};
    }}
    QPushButton[class="action-2"] {{ background-color: {c["action_2"]}; }}
    QPushButton[class="action-3"] {{ background-color: {c["action_3"]}; }}
    QPushButton[class="action-4"] {{ background-color: {c["action_4"]}; }}
    QPushButton[class="action-5"] {{ background-color: {c["action_5"]}; }}
    QPushButton[class="action-1"]:hover,
    QPushButton[class="action-2"]:hover,
    QPushButton[class="action-3"]:hover,
    QPushButton[class="action-4"]:hover,
    QPushButton[class="action-5"]:hover {{
        background-color: {c["bg_hover"]};
    }}

    /* ===== ToggleGroup (controle segmentado) ===== */
    ToggleGroup {{
        border: 1px solid {c['panel_border']};
        border-radius: 4px;
        background-color: {c['panel_bg']};
    }}
    ToggleGroup QPushButton {{
        border: none !important;
        border-top: 1px solid {c['panel_border']} !important;
        border-bottom: 1px solid {c['panel_border']} !important;
        border-left: 1px solid {c['panel_border']} !important;
        border-radius: 0 !important;
    }}
    ToggleGroup QPushButton[edge="first"] {{
        border-top-left-radius: 4px !important;
        border-bottom-left-radius: 4px !important;
    }}
    ToggleGroup QPushButton[edge="last"] {{
        border-right: 1px solid {c['panel_border']} !important;
        border-top-right-radius: 4px !important;
        border-bottom-right-radius: 4px !important;
    }}

    /* ===== Tabelas ===== */
    QTableWidget {{
        gridline-color: {c["gridline"]};
        border: none;
        background-color: {c["panel_bg"]};
        alternate-background-color: {c["window_bg"]};
        selection-background-color: {c["selection_bg"]};
        selection-color: {c["selection_text"]};
    }}
    QTableWidget::item {{
        padding: 2px 6px;
        border-bottom: 1px solid {c["gridline"]};
        border-left: 1px solid {c["gridline"]};
    }}
    QHeaderView::section {{
        padding: 4px 8px;
        font-weight: 600;
        font-size: {PX_SMALL}px;
        background-color: {c["panel_header_bg"]};
        color: {c["text"]};
        border: none;
        border-bottom: 1px solid {c["panel_border"]};
        border-right: 1px solid {c["panel_border"]};
    }}

    /* ===== Scrollbars ===== */
    QScrollBar:vertical {{
        background: {c["window_bg"]};
        width: 8px;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {c["scrollbar"]};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c["scrollbar_hover"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

    /* ===== Toasts ===== */
    QLabel[toastkind] {{
        border-radius: 7px;
        padding: 9px 17px;
        font-weight: 500;
        font-size: {PX_LARGE}px;
    }}
    QLabel[toastkind="positive"] {{
        background-color: {c["toast_positive_bg"]};
        color: {c["status_success"]};
        border: 1px solid {c["status_success"]}33;
    }}
    QLabel[toastkind="warning"] {{
        background-color: {c["toast_warning_bg"]};
        color: {c["status_warning"]};
        border: 1px solid {c["status_warning"]}33;
    }}
    QLabel[toastkind="negative"] {{
        background-color: {c["toast_negative_bg"]};
        color: {c["status_error"]};
        border: 1px solid {c["status_error"]}33;
    }}
    QLabel[toastkind="info"] {{
        background-color: {c["toast_info_bg"]};
        color: {c["toast_info_fg"]};
        border: 1px solid {c["toast_info_fg"]}33;
    }}
    """


# ============================================================================
# Helpers de botão
# ============================================================================


def make_button(
    text: str,
    role: str = "flat",
    parent=None,
) -> QPushButton:
    """Cria QPushButton com papel visual padronizado.

    Roles: "flat" (padrão, transparente + borda), "primary" (preenchimento
    neutro), "icon" (sem borda), "flat-fill", "action-1".."action-5".
    """
    btn = QPushButton(text, parent)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if role != "flat":
        btn.setProperty("class", role)
    return btn


class ThemeToggleButton(QPushButton):
    """Botão de alternância de tema (claro/escuro).

    Mostra ☾ no modo escuro e ☀ no modo claro (reflete o estado atual).
    Emite ``theme_toggled(bool dark_mode)`` — a aplicação conecta esse sinal
    para persistir a preferência e reaplicar palette/QSS.
    """

    theme_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dark = get_theme() == "dark"
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("class", "icon")
        self.clicked.connect(self._toggle)
        self._update_icon()

    def _toggle(self):
        self._dark = not self._dark
        self._update_icon()
        self.theme_toggled.emit(self._dark)

    def _update_icon(self):
        self.setText("\u263e" if self._dark else "\u2600")
