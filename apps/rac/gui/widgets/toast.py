#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout

from rac.gui.styles import colors


class _ToastWidget(QWidget):
    def __init__(self, message: str, kind: str, parent=None):
        super().__init__(parent)
        self.setProperty("toastkind", kind)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 8, 8)

        c = colors()
        self.setStyleSheet(
            f"QWidget {{ background: {c.get('bg_card', '#1E293B')}; border-radius: 8px; }}"
        )

        msg = QLabel(message)
        msg.setStyleSheet(
            f"color: {c['text_primary']}; font-size: 13px; border: none; background: transparent;"
        )
        layout.addWidget(msg)


def show_toast(
    message: str,
    kind: str,
    parent: QWidget,
    path: str | None = None,
) -> None:
    win = parent.window()
    if hasattr(win, "show_status"):
        win.show_status(message, kind, path=path)  # type: ignore
    else:
        # Fallback: log to stderr if status line unavailable
        import sys
        print(f"[{kind}] {message}", file=sys.stderr)


class ToastMixin:
    def _toast(self, message: str, kind: str = "info"):
        self._mw.show_status(message, kind)  # type: ignore
