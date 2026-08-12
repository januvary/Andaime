"""Context menu utilities — themed QMenu creation and common patterns.

Provides a styled ``QMenu`` factory and a checkable menu builder that
eliminates repeated boilerplate across projects.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QMenu, QWidget

from andaime.qt.theme import colors


def context_menu_stylesheet() -> str:
    """QSS for themed context menus, derived from the active palette."""
    c = colors()
    return f"""
        QMenu {{
            background-color: {c['panel_bg']};
            border: 1px solid {c['panel_border']};
            border-radius: 4px;
            padding: 4px;
        }}
        QMenu::item {{
            background-color: transparent;
            padding: 6px 20px;
            border-radius: 3px;
            color: {c['text']};
        }}
        QMenu::item:selected {{
            background-color: {c['bg_hover']};
        }}
        QMenu::item:checked {{
            background-color: {c['selection_bg']};
            color: {c['selection_text']};
        }}
        QMenu::item:checked:selected {{
            background-color: {c['selection_bg']};
            color: {c['selection_text']};
        }}
        QMenu::indicator {{
            width: 0px;
            margin: 0px;
        }}
    """


def styled_menu(parent: QWidget) -> QMenu:
    """Create a QMenu with the app's context menu theme applied."""
    menu = QMenu(parent)
    menu.setStyleSheet(context_menu_stylesheet())
    return menu


def build_checkable_menu(
    parent: QWidget,
    items: dict[str, str],
    current: str,
    on_select: Callable[[str], None],
    exclusions: set[str] | None = None,
) -> QMenu:
    """Build a QMenu with checkable items (radio-style selection).

    Args:
        parent: Parent widget for the menu.
        items: Mapping of ``{key: label}`` for each menu item.
        current: The key of the currently selected item.
        on_select: Callback invoked with the selected key.
        exclusions: Keys to skip (not shown in the menu).

    Returns:
        A styled QMenu ready to be shown with ``menu.exec()``.
    """
    menu = styled_menu(parent)
    skip = exclusions or set()
    for key, label in items.items():
        if key in skip:
            continue
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(key == current)
        action.triggered.connect(
            lambda checked=False, k=key: on_select(k)
        )
    return menu
