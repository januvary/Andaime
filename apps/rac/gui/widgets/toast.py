#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QPushButton
from PySide6.QtCore import Qt, QTimer

from rac.gui.styles import colors


class _ToastWidget(QWidget):
    def __init__(
        self,
        message: str,
        kind: str = "info",
        action_label: str | None = None,
        action_callback=None,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("toastkind", kind)
        self._action_callback = action_callback
        self._acted = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 8, 8)
        layout.setSpacing(12)

        c = colors()
        self.setStyleSheet(
            f"QWidget {{ background: {c.get('bg_card', '#1E293B')}; border-radius: 8px; }}"
        )

        msg = QLabel(message)
        msg.setStyleSheet(
            f"color: {c['text_primary']}; font-size: 13px; border: none; background: transparent;"
        )
        layout.addWidget(msg)

        if action_label and action_callback:
            btn = QPushButton(action_label)
            btn.setStyleSheet(
                f"QPushButton {{ background: {c.get('accent', '#3B82F6')}; color: white; "
                f"border: none; border-radius: 4px; padding: 4px 12px; "
                f"font-size: 12px; font-weight: 600; }}"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(self._on_action)
            layout.addWidget(btn)

    def _on_action(self):
        if not self._acted:
            self._acted = True
            self._action_callback()
        self.deleteLater()

    def mousePressEvent(self, event):
        self.deleteLater()


def show_toast(
    message: str,
    kind: str,
    parent: QWidget,
    action_label: str | None = None,
    action_callback=None,
    timeout_ms: int = 3000,
):
    win = parent.window()
    toast = _ToastWidget(message, kind, action_label, action_callback, win)
    toast.adjustSize()
    toast.setFixedWidth(min(toast.width() + 32, win.width() - 48))
    toast.move(
        (win.width() - toast.width()) // 2,
        win.height() - toast.height() - 16,
    )
    toast.show()
    toast.raise_()
    QTimer.singleShot(timeout_ms, toast.deleteLater)


class ToastMixin:
    def _toast(self, message: str, kind: str = "info"):
        show_toast(message, kind, self)  # type: ignore[arg-type]
