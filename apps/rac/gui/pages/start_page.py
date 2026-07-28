#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Start Page — malote header, search, tipo buttons, export
"""

from contextlib import suppress

from PySide6.QtWidgets import (
    QVBoxLayout,
    QHBoxLayout,
    QSizePolicy,
    QFrame,
    QLabel,
    QWidget,
)
from PySide6.QtCore import Qt

from andaime.widgets import SearchableComboBox
from rac.gui.brasao import get_brasao_pixmap, get_rac_pixmap
from rac.gui.widgets import (
    TipoButton,
    make_button,
    make_hbox,
    MaloteLabel,
    ThemeToggleButton,
    BasePage,
    export_with_fallback,
    confirm_past_malote,
)
from rac.gui.constants import (
    TIPO_LABELS,
    TIPO_HEX,
    SHORTCUT_LABELS,
    TIPO_SHORTCUT_KEYS,
    TIPO_SYMBOLS,
)

from rac.export.excel_exporter import ExcelExporter
from rac.models import Malote
from rac.utils.text_utils import format_malote_date, is_malote_past
from rac.gui.styles import colors


class StartPage(BasePage):
    # Constants for easier customization
    BRASAO_HEIGHT = 42
    RAC_HEIGHT = 42
    SUBTITLE_FONT_SIZE = "10pt"
    USAFA_FONT_SIZE = "9pt"
    RAC_SPACING = 8
    SUBTITLE_SPACING = 8
    BRASAO_SPACING = 8
    
    def __init__(self, main_window):
        super().__init__(main_window)
        self._pre_search_malote = None
        self._sep_line: QFrame | None = None
        self._brasao_label: QLabel | None = None
        self._rac_label: QLabel | None = None
        self._subtitle_label: QLabel | None = None
        self._usafa_label: QLabel | None = None
        self._build_ui()

    def _build_ui(self):
        layout = self._scaffold()
        
        self._build_malote_header(layout)
        layout.addSpacing(20)

        self._build_search(layout)
        layout.addSpacing(20)

        self._build_columns(layout)
        
        # Bottom container for brasao centering
        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 40, 0, 0)
        bottom_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self._build_brasao(bottom_layout)
        
        layout.addWidget(bottom_container)
        layout.addStretch(1)

    def _build_malote_header(self, layout: QVBoxLayout):
        h = make_hbox()

        theme_btn = ThemeToggleButton()
        h.addWidget(theme_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._malote_label = MaloteLabel(self._mw)
        self._malote_label.malote_changed.connect(self.refresh)
        self._mw.theme_changed.connect(self._on_theme_changed)
        h.addStretch()
        h.addWidget(self._malote_label, 0, Qt.AlignmentFlag.AlignTop)

        layout.addLayout(h)

    def _build_search(self, layout: QVBoxLayout):
        self._search_combo = SearchableComboBox(
            self._search_registros, "Buscar registro..."
        )
        self._search_combo.selection_changed.connect(self._on_search_select)
        layout.addWidget(self._search_combo)
        self._shortcut_searches = [
            ("Buscar registro...", self._search_combo._line_edit),
        ]

    def _build_brasao(self, layout: QVBoxLayout):
        """Build brasao section with subtitles and brasão."""
        from rac.gui.styles import colors as _colors
        
        # R.A.C logo text (temporary replacement for RAC SVG)
        layout.addSpacing(self.RAC_SPACING)
        c = _colors()
        title_color = c.get('text_primary', c.get('text', '#000000'))
        self._rac_label = QLabel("R.A.C")
        self._rac_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rac_label.setStyleSheet(f"border: none; background: transparent; color: {title_color}; font-size: 16pt; font-weight: bold;")
        layout.addWidget(self._rac_label)
        
        # Subtitles
        layout.addSpacing(self.SUBTITLE_SPACING)
        self._build_subtitles(layout)
        
        # Brasão (bottom)
        layout.addSpacing(self.BRASAO_SPACING)
        self._brasao_label = QLabel()
        self._brasao_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._brasao_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(self._brasao_label)
        
        self._update_brasao()
    
    def _build_subtitles(self, layout: QVBoxLayout):
        """Build subtitle labels with theme colors."""
        from rac.gui.styles import colors as _colors
        
        c = _colors()
        subtitle_color = c.get('text_primary', c.get('text', '#000000'))
        style_base = f"border: none; background: transparent; color: {subtitle_color};"
        
        # Division subtitle
        self._subtitle_label = QLabel("Divisão de Assistência Farmacêutica - Praia Grande")
        self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle_label.setStyleSheet(f"{style_base} font-size: {self.SUBTITLE_FONT_SIZE};")
        layout.addWidget(self._subtitle_label)
        
        # USAFA name
        usafa_name = self._mw.config.get("usafa_name") or "Sua unidade de saúde"
        self._usafa_label = QLabel(usafa_name)
        self._usafa_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._usafa_label.setStyleSheet(f"{style_base} font-size: {self.USAFA_FONT_SIZE};")
        self._usafa_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._usafa_label.mousePressEvent = self._on_usafa_click
        layout.addWidget(self._usafa_label)

    def _build_columns(self, layout: QVBoxLayout):
        from rac.gui.styles import colors as _colors, faded_tipo_color

        c = _colors()

        columns = QHBoxLayout()
        columns.setSpacing(0)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._tipo_btns: list[TipoButton] = []
        for tipo_key in TIPO_LABELS:
            btn = TipoButton(tipo_key)
            btn.clicked_tipo.connect(self._on_tipo_click)
            btn.setFixedHeight(54)
            faded = faded_tipo_color(TIPO_HEX[tipo_key])
            btn.setStyleSheet(self._flat_btn_style(c, "left", faded))
            self._tipo_btns.append(btn)
            left.addWidget(btn)

        left.addSpacing(24)

        columns.addLayout(left, 1)
        columns.addSpacing(8)

        self._sep_line = QFrame()
        self._sep_line.setFrameShape(QFrame.Shape.VLine)
        self._sep_line.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding
        )
        self._sep_line.setStyleSheet(
            f"color: {c['border']}; border: none; background: {c['border']}; max-width: 1px;"
        )
        columns.addWidget(self._sep_line)

        columns.addSpacing(8)

        right = QVBoxLayout()
        right.setSpacing(8)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._shortcut_widgets = {}

        for key, handler in (
            ("preview", self._on_preview),
            ("export", self._on_export),
            ("medicamentos", self._on_medicamentos),
            ("pacientes", self._on_pacientes),
            ("stats", self._on_stats),
        ):
            _, label = SHORTCUT_LABELS[key]
            shortcut_btn = make_button(label, "flat")
            shortcut_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            shortcut_btn.setFixedHeight(54)
            shortcut_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            shortcut_btn.setStyleSheet(self._flat_btn_style(c, "right"))
            shortcut_btn.clicked.connect(handler)
            right.addWidget(shortcut_btn)
            self._shortcut_widgets[key] = shortcut_btn

        right.addSpacing(24)

        columns.addLayout(right, 1)
        layout.addLayout(columns)

    def refresh(self):
        if self._pre_search_malote is not None:
            self._mw.state.set_active_malote(self._pre_search_malote)
            self._pre_search_malote = None
        self._malote_label.refresh()
        self._search_combo.clear()

    def _search_registros(self, query: str) -> dict[str, str]:
        if not query:
            return {}
        malote = self._mw.state.get_active_malote()
        active_id = malote.id if malote else None
        resultados = self._mw.services.registro.search_by_paciente(query, active_id)
        return {
            str(
                r.id
            ): f"{format_malote_date(Malote(date=r.malote_date or ''))} — {r.paciente_name or ''} ({TIPO_LABELS.get(r.tipo, '')})"
            for r in resultados
        }

    def _on_search_select(self, data):
        if not data:
            return
        with suppress(ValueError, TypeError):
            reg_id = int(data)
            reg = self._mw.services.registro.get(reg_id)
            if reg:
                self._pre_search_malote = self._mw.state.get_active_malote()
                self._mw.navigate_to("patient", paciente_id=reg.paciente_id, highlight_registro=reg_id)
    
    def _require_malote(self) -> bool:
        if not self._mw.state.has_active_malote():
            self._toast("Selecione um malote primeiro!", "warning")
            return False
        return True
    
    def _on_tipo_click(self, tipo_key: str):
        if not self._require_malote():
            return
        malote = self._mw.state.get_active_malote()
        if malote and is_malote_past(malote):
            if not confirm_past_malote(
                self.window(), malote, on_change=self._malote_label.open_dialog
            ):
                return
        self._mw.navigate_to("entry", tipo=tipo_key)

    def _on_preview(self):
        if not self._require_malote():
            return
        self._mw.navigate_to("preview")

    def _on_export(self):
        if not self._require_malote():
            return
        malote = self._mw.state.get_active_malote()
        exporter = ExcelExporter(self._mw.db)
        export_with_fallback(
            self,
            lambda: exporter.export_malote(malote.id),
            "Nenhum registro para exportar",
        )

    def _on_medicamentos(self):
        self._mw.navigate_to("medicamentos")

    def _on_pacientes(self):
        self._mw.navigate_to("pacientes")

    def _on_stats(self):
        self._mw.navigate_to("stats")

    @staticmethod
    def _flat_btn_style(c: dict, align: str, color: str | None = None) -> str:
        text_color = color or c["text_secondary"]
        hover_color = c["text_primary"] if not color else ""
        hover = f"color: {hover_color};" if hover_color else ""
        return (
            f'QPushButton {{ background: transparent; border: 1px solid {c["border"]}; '
            f"border-radius: 6px; padding: 12px 20px; text-align: {align}; "
            f"color: {text_color}; }}"
            f'QPushButton:hover {{ background: {c["bg_hover"]}; {hover} }}'
            f'QPushButton:pressed {{ background: {c["bg_pressed"]}; }}'
        )

    def _on_theme_changed(self):
        self._malote_label.refresh()
        from rac.gui.styles import colors as _colors, faded_tipo_color

        c = _colors()
        for btn in self._tipo_btns:
            faded = faded_tipo_color(TIPO_HEX[btn.tipo_key])
            btn.setStyleSheet(self._flat_btn_style(c, "left", faded))
        for btn in self._shortcut_widgets.values():
            btn.setStyleSheet(self._flat_btn_style(c, "right"))
        if self._sep_line:
            self._sep_line.setStyleSheet(
                f"color: {c['border']}; border: none; background: {c['border']}; max-width: 1px;"
            )
        
        self._update_brasao()

    def _update_brasao(self):
        """Update all logos and subtitle colors on theme change."""
        if not all([self._brasao_label, self._rac_label, self._subtitle_label, self._usafa_label]):
            return
        
        theme = self._mw.config.get("theme", "light")
        dark_mode = (theme == "dark")
        
        # Update brasão logo
        brasao_pixmap = get_brasao_pixmap(height=self.BRASAO_HEIGHT, dark_mode=dark_mode)
        if brasao_pixmap:
            self._brasao_label.setPixmap(brasao_pixmap)
        
        # Update R.A.C text color
        self._update_subtitle_colors()
    
    def _update_subtitle_colors(self):
        """Update subtitle label colors on theme change."""
        from rac.gui.styles import colors as _colors
        
        c = _colors()
        subtitle_color = c.get('text_primary', c.get('text', '#000000'))
        style_base = f"border: none; background: transparent; color: {subtitle_color};"
        
        self._rac_label.setStyleSheet(f"{style_base} font-size: 16pt; font-weight: bold;")
        self._subtitle_label.setStyleSheet(f"{style_base} font-size: {self.SUBTITLE_FONT_SIZE};")
        self._usafa_label.setStyleSheet(f"{style_base} font-size: {self.USAFA_FONT_SIZE};")
    
    def _on_usafa_click(self, event):
        """Handle click on USAFA name to edit it."""
        from main import _show_usafa_dialog
        
        new_name = _show_usafa_dialog(self._mw.config, parent=self.window())
        if new_name:
            self._usafa_label.setText(new_name)

    def set_shortcuts_visible(self, show: bool):
        super().set_shortcuts_visible(show)
        for btn in self._tipo_btns:
            label = TIPO_LABELS[btn.tipo_key]
            symbol = TIPO_SYMBOLS[btn.tipo_key]
            if show:
                key = TIPO_SHORTCUT_KEYS[btn.tipo_key]
                btn.setText(f"{symbol}  {label}  ({key})")
            else:
                btn.setText(f"{symbol}  {label}")
        self._malote_label.set_shortcut_hint_visible(show)

