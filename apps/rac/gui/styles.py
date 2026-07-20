#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Global QSS stylesheet — native Qt feel with theme support.

As cores neutras são mapeadas a partir da paleta compartilhada
(``andaime.qt.theme``: rampa + níveis), mantendo o motor de tema
centralizado. Cores de identidade do RAC (azul de acento, vermelhos
destrutivos, sistema ``btnrole``, tipos de medicamento) continuam
definidas localmente neste módulo.
"""

_current_theme: str = "light"

from andaime.qt.theme import LIGHT as _SHARED_LIGHT, DARK as _SHARED_DARK


# RAC key -> chave correspondente na paleta compartilhada. Chaves com o mesmo
# nome não precisam de mapeamento (pass-through).
_RAC_TO_SHARED = {
    "bg_main": "window_bg",
    "bg_card": "panel_bg",
    "bg_card_alt": "panel_header_bg",
    "bg_input": "input_bg",
    "border": "panel_border",
    "text_primary": "text",
    "separator": "separador",
    "table_alt_bg": "window_bg",
    "toast_positive_fg": "status_success",
    "toast_warning_fg": "status_warning",
    "toast_negative_fg": "status_error",
}

# Chaves do RAC (text_dark era morta e foi removida).
_RAC_KEYS = (
    "bg_main", "bg_card", "bg_card_alt", "bg_hover", "bg_pressed",
    "bg_input", "border", "border_light", "text_primary", "text_secondary",
    "selection_bg", "selection_text", "separator", "gridline", "scrollbar",
    "scrollbar_hover", "table_alt_bg", "toast_positive_fg", "toast_positive_bg",
    "toast_warning_fg", "toast_warning_bg", "toast_negative_fg",
    "toast_negative_bg", "toast_info_fg", "toast_info_bg",
)


def _rac_palette(shared: dict) -> dict:
    """Mapeia o vocabulário do RAC sobre a paleta compartilhada.

    Os valores vêm de ``andaime.qt.theme`` (rama + níveis), centralizando o
    motor de tema. Cores de identidade do RAC (azul de acento, vermelhos
    destrutivos, sistema ``btnrole``, tipos de medicamento) continuam locais.
    """
    return {key: shared[_RAC_TO_SHARED.get(key, key)] for key in _RAC_KEYS}


LIGHT_COLORS = _rac_palette(_SHARED_LIGHT)
DARK_COLORS = _rac_palette(_SHARED_DARK)


def set_theme(theme: str) -> None:
    global _current_theme
    _current_theme = theme


def get_theme() -> str:
    return _current_theme


def toggle_theme() -> str:
    global _current_theme
    _current_theme = "light" if _current_theme == "dark" else "dark"
    from andaime.config import ConfigManager

    ConfigManager().set("theme", _current_theme)
    return _current_theme


def colors() -> dict:
    return DARK_COLORS if _current_theme == "dark" else LIGHT_COLORS


def _blend_hex(hex_a: str, hex_b: str, ratio: float) -> str:
    ra, ga, ba = int(hex_a[1:3], 16), int(hex_a[3:5], 16), int(hex_a[5:7], 16)
    rb, gb, bb = int(hex_b[1:3], 16), int(hex_b[3:5], 16), int(hex_b[5:7], 16)
    r = int(ra * ratio + rb * (1 - ratio))
    g = int(ga * ratio + gb * (1 - ratio))
    b = int(ba * ratio + bb * (1 - ratio))
    return f"#{r:02x}{g:02x}{b:02x}"


def faded_tipo_color(hex_color: str) -> str:
    if _current_theme == "dark":
        return _blend_hex(hex_color, colors()["text_primary"], 0.85)
    return _blend_hex(hex_color, colors()["text_primary"], 0.55)


def get_stylesheet(theme: str | None = None) -> str:
    resolved = theme or _current_theme
    c = DARK_COLORS if resolved == "dark" else LIGHT_COLORS
    return _build_qss(c)


def tipo_button_qss(text_color: str | None = None, c: dict | None = None) -> str:
    if c is None:
        c = colors()
    if text_color is None:
        text_color = c["text_primary"]
    return f"""
        QPushButton[tipobtn="true"] {{
            background-color: {c["bg_card"]};
            border: 1px solid {c["border_light"]};
            border-radius: 8px;
            padding: 20px 16px;
            font-size: 15px;
            font-weight: 500;
            color: {text_color};
        }}
        QPushButton[tipobtn="true"]:hover {{
            background-color: {c["bg_card_alt"]};
            border-color: {c["border"]};
        }}
        QPushButton[tipobtn="true"]:pressed {{
            background-color: {c["bg_hover"]};
        }}
    """


def combo_style_qss(
    text_color: str,
    bg: str,
    bg_hover: str,
    dropdown_bg: str,
    selection_bg: str,
    selection_text: str,
    border: str = "none",
    font_size: str = "14px",
    font_weight: str = "400",
    padding: str = "9px 14px",
    min_height: str = "22px",
    max_height: str | None = None,
) -> str:
    max_height_rule = f"\n                max-height: {max_height};" if max_height else ""
    return f"""
        QComboBox {{
            border: {border};
            border-radius: 6px;
            padding: {padding};
            background: {bg};
            color: {text_color};
            font-size: {font_size};
            font-weight: {font_weight};
            min-height: {min_height};{max_height_rule}
        }}
        QComboBox:hover {{
            background: {bg_hover};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 16px;
        }}
        QComboBox::down-arrow {{
            image: none;
            border: none;
        }}
        QComboBox QAbstractItemView {{
            border: none;
            background-color: {dropdown_bg};
            selection-background-color: {selection_bg};
            selection-color: {selection_text};
            outline: none;
            padding: 2px;
        }}
        QComboBox QAbstractItemView::item {{
            padding: 6px 10px;
            min-height: 22px;
        }}
    """


def _build_qss(c: dict) -> str:
    return f"""
/* -- Global -- */
* {{
    font-family: "Geist", sans-serif;
}}
QMainWindow {{
    background-color: {c["bg_main"]};
}}
QWidget#central {{
    background-color: {c["bg_main"]};
}}

/* -- Section headings -- */
QLabel[heading="true"] {{
    font-size: 16px;
    font-weight: 600;
    color: {c["text_primary"]};
    padding: 0px;
    margin: 0px;
}}
QLabel[heading="section"] {{
    font-size: 12px;
    font-weight: 600;
    color: {c["text_secondary"]};
    padding: 0px;
    margin: 0px;
}}

/* -- Separator -- */
QFrame[separator="true"] {{
    background-color: {c["separator"]};
    max-height: 1px;
    border: none;
}}

/* -- Buttons -- */
QPushButton {{
    background-color: transparent;
    border: 1px solid {c["bg_main"]};
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 14px;
    font-weight: 500;
    color: {c["text_primary"]};
    min-height: 22px;
}}
QPushButton:hover {{
    background-color: {c["bg_hover"]};
    border-color: {c["bg_main"]};
}}
QPushButton:pressed {{
    background-color: {c["bg_pressed"]};
}}

QPushButton[btnrole="primary"], QPushButton[btnrole="positive"] {{
    background-color: {c["bg_card"]};
    border: 1px solid {c["border_light"]};
    border-radius: 6px;
    color: {c["text_primary"]};
}}
QPushButton[btnrole="primary"]:hover, QPushButton[btnrole="positive"]:hover {{
    background-color: {c["bg_card_alt"]};
    border-color: {c["border"]};
}}
QPushButton[btnrole="primary"]:pressed, QPushButton[btnrole="positive"]:pressed {{
    background-color: {c["bg_hover"]};
}}

QPushButton[btnrole="negative"] {{
    background-color: transparent;
    border-color: #FCA5A5;
    color: #DC2626;
}}
QPushButton[btnrole="negative"]:hover {{
    background-color: #FEF2F2;
    border-color: #F87171;
}}
QPushButton[btnrole="negative"]:pressed {{
    background-color: #FEE2E2;
}}

QPushButton[btnrole="flat"] {{
    background-color: transparent;
    border: none;
    padding: 4px 12px;
    color: {c["text_secondary"]};
}}
QPushButton[btnrole="flat"]:hover {{
    background-color: {c["bg_hover"]};
    color: {c["text_primary"]};
}}
QPushButton[btnrole="flat"]:pressed {{
    background-color: {c["bg_pressed"]};
}}

QPushButton[btnrole="destructive"] {{
    background-color: #EF4444;
    border-color: #EF4444;
    color: white;
}}
QPushButton[btnrole="destructive"]:hover {{
    background-color: #DC2626;
    border-color: #DC2626;
}}

/* -- Inputs / ComboBox -- */
QLineEdit {{
    border: 1px solid {c["border"]};
    border-radius: 6px;
    padding: 9px 14px;
    background: {c["bg_input"]};
    color: {c["text_primary"]};
    font-size: 14px;
    min-height: 22px;
    selection-background-color: {c["selection_bg"]};
    selection-color: {c["selection_text"]};
}}

QLineEdit:focus {{
    border-color: #3B82F6;
}}

{combo_style_qss(
    text_color=c["text_primary"],
    bg=c["bg_input"],
    bg_hover=c["bg_input"],
    dropdown_bg=c["bg_card"],
    selection_bg=c["selection_bg"],
    selection_text=c["selection_text"],
    border=f'1px solid {c["border"]}',
)}
QComboBox:focus {{
    border-color: #3B82F6;
}}

/* -- Tipo Button -- */
{tipo_button_qss(c["text_primary"], c)}

/* -- Dialog -- */
QDialog {{
    background-color: {c["bg_card"]};
    color: {c["text_primary"]};
}}

/* -- Scrollbar -- */
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {c["scrollbar"]};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c["scrollbar_hover"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* -- List Widget -- */
QListWidget {{
    border: 1px solid {c["border_light"]};
    border-radius: 6px;
    background: {c["bg_card"]};
    color: {c["text_primary"]};
    outline: none;
    padding: 2px;
}}
QListWidget::item {{
    padding: 8px 12px;
    border-radius: 4px;
}}
QListWidget::item:hover {{
    background-color: {c["bg_hover"]};
}}
QListWidget::item:selected {{
    background-color: {c["selection_bg"]};
    color: {c["selection_text"]};
}}

/* -- Status Bar -- */
QStatusBar {{
    background-color: {c["bg_card"]};
    border-top: 1px solid {c["border_light"]};
    color: {c["text_secondary"]};
    font-size: 12px;
    padding: 4px 12px;
}}

/* -- Check Box -- */
QCheckBox {{
    spacing: 6px;
    color: {c["text_primary"]};
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid {c["border"]};
    background: {c["bg_input"]};
}}
QCheckBox::indicator:checked {{
    background-color: #3B82F6;
    border-color: #3B82F6;
}}

/* -- Remove Button -- */
QPushButton[btnrole="remove"] {{
    background-color: transparent;
    border: none;
    color: {c["text_secondary"]};
    padding: 0px;
    font-size: 16px;
    border-radius: 4px;
}}
QPushButton[btnrole="remove"]:hover {{
    background-color: #FEF2F2;
    color: #EF4444;
}}

/* -- Tree Widget -- */
QTreeWidget {{
    border: 1px solid {c["border_light"]};
    border-radius: 6px;
    background: {c["bg_card"]};
    color: {c["text_primary"]};
    outline: none;
    padding: 2px;
}}
QTreeWidget::item {{
    padding: 6px 12px;
    border-radius: 4px;
}}
QTreeWidget::item:hover {{
    background-color: {c["bg_hover"]};
}}
QTreeWidget::item:selected {{
    background-color: {c["selection_bg"]};
    color: {c["selection_text"]};
}}
QTreeWidget::branch {{
    background-color: {c["bg_card"]};
}}

/* -- Completer Popup -- */
QListView {{
    background-color: {c["bg_card"]};
    color: {c["text_primary"]};
    border: 1px solid {c["border_light"]};
    border-radius: 6px;
    selection-background-color: {c["selection_bg"]};
    selection-color: {c["selection_text"]};
    outline: none;
    padding: 2px;
}}

/* -- Table alternating rows -- */
QTableWidget {{
    alternate-background-color: {c["table_alt_bg"]};
}}

/* -- Malote Label -- */
QLabel[malotelabel="true"] {{
    color: {c["text_primary"]};
    font-size: 22px;
    font-weight: 400;
}}

/* -- Theme Toggle Button -- */
QPushButton[btnrole="theme-toggle"] {{
    border: none;
    font-size: 16px;
    padding: 0;
}}

/* -- Toast -- */
QLabel[toastkind] {{
    border-radius: 7px;
    padding: 9px 17px;
    font-weight: 500;
    font-size: 15px;
}}
QLabel[toastkind="positive"] {{
    background-color: {c["toast_positive_bg"]};
    color: {c["toast_positive_fg"]};
    border: 1px solid {c["toast_positive_fg"]}33;
}}
QLabel[toastkind="warning"] {{
    background-color: {c["toast_warning_bg"]};
    color: {c["toast_warning_fg"]};
    border: 1px solid {c["toast_warning_fg"]}33;
}}
QLabel[toastkind="negative"] {{
    background-color: {c["toast_negative_bg"]};
    color: {c["toast_negative_fg"]};
    border: 1px solid {c["toast_negative_fg"]}33;
}}
        QLabel[toastkind="info"] {{
            background-color: {c["toast_info_bg"]};
            color: {c["toast_info_fg"]};
            border: 1px solid {c["toast_info_fg"]}33;
        }}
    """


def tab_style_qss(accent_color: str = "#3B82F6") -> str:
    c = colors()
    return f"""
        QTabWidget::pane {{
            border: 1px solid {c["border_light"]};
            border-radius: 6px;
            background: {c["bg_card"]};
        }}
        QTabBar::tab {{
            padding: 8px 20px;
            border: 1px solid {c["border_light"]};
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            background: {c["bg_card_alt"]};
            color: {c["text_secondary"]};
            font-size: 13px;
            font-weight: 500;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            background: {c["bg_card"]};
            color: {accent_color};
            border-bottom: 2px solid {c["bg_card"]};
            font-weight: 600;
        }}
        QTabBar::tab:hover {{
            background: {c["bg_hover"]};
            color: {c["text_primary"]};
        }}
    """


def data_view_style_qss(
    widget_type="QTableWidget",
    border="none",
    item_padding="8px 12px",
    include_selected=True,
    include_hover=False,
    header_bg_key="bg_card",
    header_padding="4px 8px",
    header_border_key="gridline",
    extra_header_hover="",
    outline="",
):
    c = colors()
    selected_block = ""
    if include_selected:
        selected_block = f"""
        {widget_type}::item:selected {{
            background-color: {c["selection_bg"]};
            color: {c["selection_text"]};
        }}"""
    hover_block = ""
    if include_hover:
        hover_block = f"""
        {widget_type}::item:hover {{
            background-color: {c["bg_hover"]};
        }}"""
    outline_rule = f"\n            outline: {outline};" if outline else ""
    return f"""
        {widget_type} {{
            border: {border};
            border-radius: 6px;
            background: transparent;
            alternate-background-color: {c["table_alt_bg"]};
            gridline-color: {c["gridline"]};
            font-size: 13px;
            color: {c["text_primary"]};{outline_rule}
        }}
        {widget_type}::item {{
            padding: {item_padding};
            border-bottom: 1px solid {c["gridline"]};
            color: {c["text_primary"]};
        }}{selected_block}{hover_block}
        QHeaderView::section {{
            background: {c[header_bg_key]};
            color: {c["text_secondary"]};
            font-size: 11px;
            font-weight: 600;
            padding: {header_padding};
            border: none;
            border-bottom: 1px solid {c[header_border_key]};
        }}{extra_header_hover}
    """


def filter_table_rows(table, text: str):
    query = text.strip().lower()
    for row in range(table.rowCount()):
        match = False
        if not query:
            match = True
        else:
            for col in range(table.columnCount()):
                item = table.item(row, col)
                if item and query in item.text().lower():
                    match = True
                    break
        table.setRowHidden(row, not match)
