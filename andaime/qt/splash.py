"""Splash screen shown during app startup."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

_BG = QColor("#1e1e2e")
_FG = QColor("#cdd6f4")
_SUB = QColor("#7f849c")
_ACCENT = QColor("#89b4fa")

_W, _H = 480, 280


class SplashScreen:
    """Branded splash screen shown while the app initializes.

    Usage::

        qapp = QApplication(sys.argv)
        splash = SplashScreen("RAC", icon_path)
        splash.show()
        # ... heavy initialization ...
        window.show()
        splash.finish(window)
    """

    def __init__(
        self,
        app_name: str,
        icon_path: Path | None = None,
    ) -> None:
        self._app_name = app_name
        self._icon_path = icon_path
        self._splash: QSplashScreen | None = None

    def show(self) -> None:
        if self._splash is not None:
            return
        self._splash = QSplashScreen(self._make_pixmap())
        self._splash.show()
        QApplication.processEvents()

    def finish(self, window: "QWidget") -> None:
        if self._splash is None:
            return
        self._splash.finish(window)
        self._splash = None

    def close(self) -> None:
        if self._splash is None:
            return
        self._splash.close()
        self._splash = None

    # ------------------------------------------------------------------
    def _make_pixmap(self) -> QPixmap:
        pixmap = QPixmap(_W, _H)
        pixmap.fill(_BG)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        y = 56

        # Icon
        if self._icon_path and self._icon_path.exists():
            icon = QPixmap(str(self._icon_path))
            if not icon.isNull():
                sz = 64
                icon = icon.scaled(
                    sz, sz,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.drawPixmap((_W - sz) // 2, y, icon)
                y += sz + 16

        # App name
        painter.setPen(_FG)
        font = QFont()
        font.setPointSize(22)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, y, _W, 42),
            Qt.AlignmentFlag.AlignCenter,
            self._app_name,
        )

        # Accent bar
        bar_w = 80
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_ACCENT)
        painter.drawRoundedRect(
            QRectF((_W - bar_w) / 2, y + 56, bar_w, 3), 1, 1,
        )

        # "Carregando..."
        painter.setPen(_SUB)
        font.setPointSize(10)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(
            QRectF(0, _H - 48, _W, 28),
            Qt.AlignmentFlag.AlignCenter,
            "Carregando...",
        )

        painter.end()
        return pixmap
