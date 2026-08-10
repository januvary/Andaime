#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import QPushButton, QSizePolicy, QStyle, QStyleOptionButton
from PySide6.QtCore import Qt, Signal, QRect, QSize
from PySide6.QtGui import QIcon, QPainter
from pathlib import Path

from andaime.qt.theme import make_button
from rac.gui.styles import tipo_button_qss, toggle_theme, get_stylesheet, get_theme, faded_tipo_color
from rac.gui.constants import TIPO_LABELS, TIPO_SYMBOLS, TIPO_HEX


def _load_material_icon(name: str, white: bool = False, color: str | None = None) -> QIcon:
    """Load pre-rendered Material Symbol icon PNG.

    If *color* is given, load the tinted variant (e.g. tipo icons). Otherwise
    load the black or white theme variant.
    """
    base_dir = Path(__file__).parent.parent / "img" / "material-icons"
    if color:
        icon_path = base_dir / f"{name}-color.png"
    elif white:
        icon_path = base_dir / f"{name}-white.png"
    else:
        icon_path = base_dir / f"{name}.png"
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()


def make_icon_button(text: str, role: str, width: int = 40, font_size: int = 14) -> QPushButton:
    btn = make_button(text, role)
    btn.setFixedWidth(width)
    btn.setStyleSheet(f"padding: 9px 0; font-size: {font_size}px; font-weight: 600;")
    return btn


class IconButtonBase(QPushButton):
    """QPushButton with manually positioned icon (left or right) and matching text alignment.

    This guarantees consistent icon-to-edge spacing regardless of the Qt style.
    """

    def __init__(self, text: str, icon_align: str = "left", parent=None):
        super().__init__(text, parent)
        self._icon_align = icon_align.lower()
        self.setIconSize(QSize(16, 16))

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.icon = QIcon()
        option.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)

        painter.setPen(option.palette.buttonText().color())
        painter.setFont(self.font())
        icon_size = self.iconSize()
        margin = 18
        spacing = 6
        icon_width = icon_size.width() + spacing if not self.icon().isNull() else 0

        if self._icon_align == "right":
            text_rect = QRect(margin, 0, self.width() - margin * 2 - icon_width, self.height())
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            icon_x = self.width() - margin - icon_size.width()
        else:
            text_rect = QRect(margin + icon_width, 0, self.width() - margin * 2 - icon_width, self.height())
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            icon_x = margin

        painter.drawText(text_rect, align, self.text())

        if not self.icon().isNull():
            icon_rect = QRect(
                icon_x,
                (self.height() - icon_size.height()) // 2,
                icon_size.width(),
                icon_size.height(),
            )
            self.icon().paint(painter, icon_rect)

        painter.end()


class TipoButton(IconButtonBase):
    clicked_tipo = Signal(str)

    def __init__(self, tipo_key: str, parent=None):
        label = TIPO_LABELS[tipo_key]
        self._hex_color = TIPO_HEX[tipo_key]
        self._icon_name = TIPO_SYMBOLS[tipo_key]

        super().__init__(label, icon_align="left", parent=parent)
        self.tipo_key = tipo_key
        self.setProperty("tipobtn", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(68)
        self._apply_style()
        self.clicked.connect(lambda: self.clicked_tipo.emit(self.tipo_key))

    def _apply_style(self):
        icon = _load_material_icon(self._icon_name, color=self._hex_color)
        self.setIcon(icon)
        self.setStyleSheet(tipo_button_qss(faded_tipo_color(self._hex_color)))

    def refresh_style(self):
        self._apply_style()


class ThemeToggleButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("class", "theme-toggle")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(28, 28)
        self.clicked.connect(self._toggle)
        self._update_icon()

    def _toggle(self):
        from PySide6.QtWidgets import QApplication

        toggle_theme()
        QApplication.instance().setStyleSheet(get_stylesheet())
        self._update_icon()
        window = self.window()
        if hasattr(window, "theme_changed"):
            window.theme_changed.emit()

    def _update_icon(self):
        self.setText("\u263e" if get_theme() == "dark" else "\u2600")
