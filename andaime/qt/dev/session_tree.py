"""Session Launcher — a tree view over opencode sessions per project.

Extends the Dev Launcher idea: each registered project is a top-level tree
row, and expanding it reveals the opencode sessions launched for that project.
A ``+`` spawns opencode (the local fork) for a project in a GNOME Terminal
window/tab; an ``x`` closes the running session. Sessions persist in the
project registry so they can be relaunched later with ``--session <id>``.

The heavy lifting (daemonized terminals, tabs, titles) is delegated to GNOME
Terminal via ``gnome-terminal`` CLI + D-Bus; this widget only tracks the
mapping between tree rows, terminal windows/tabs, and opencode session ids.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from andaime.qt.dev.project_registry import (
    Project,
    Session,
    find_project,
    load_registry,
    refresh_capabilities,
    save_registry,
)
from andaime.qt.theme import colors, make_button

# Path to the local opencode fork wrapper (absolute, so it works from any cwd).
OPENCODE_WRAPPER = os.path.expanduser("~/.local/bin/opencode-fork")

# The opencode session-id prefix opencode uses for its ids.
_SESSION_ID_PREFIX = "ses_"


def _new_session_id() -> str:
    """Generate a fresh opencode-style session id (opencode accepts a client-
    supplied id via ``--session``; we reuse its ``ses_<timestamp><ulid>``
    shape enough to be stable and sortable)."""
    return f"{_SESSION_ID_PREFIX}{uuid.uuid4().hex}"


class SessionTree(QWidget):
    """Qt tree linking projects -> opencode sessions -> GNOME Terminal tabs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tree = QTreeWidget()
        self._tree.setColumnCount(4)
        self._cols = ["Project", "Session", "Status", ""]
        self._tree.setHeaderLabels(self._cols)
        self._tree.setRootIsDecorated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)

        self._rebuild()

    # ---- persistence helpers -------------------------------------------------

    def _refresh_registry(self) -> None:
        """Reload projects from disk and refresh capability detection."""
        refresh_capabilities()

    def _save(self) -> None:
        save_registry(load_registry())

    # ---- tree construction ---------------------------------------------------

    def _rebuild(self) -> None:
        self._tree.clear()
        projects = load_registry()
        if not projects:
            empty = QTreeWidgetItem(["No projects yet"])
            self._tree.addTopLevelItem(empty)
            return
        for project in projects:
            self._add_project_row(project)

    def _add_project_row(self, project: Project) -> QTreeWidgetItem:
        root = QTreeWidgetItem()
        root.setFlags(Qt.ItemFlag.ItemIsEnabled)
        # Column 1: project name + capabilities tag
        name = project.name
        if project.capabilities.git:
            name += "  (git)"
        root.setText(0, name)
        root.setData(0, Qt.ItemDataRole.UserRole, str(project.path))

        for i in range(4):
            root.setFlags(root.flags() | Qt.ItemFlag.ItemIsEnabled)
            if i:
                root.setText(i, "")

        # Each session becomes a child row
        for session in project.sessions:
            child = self._add_session_row(root, session)
            child.setData(0, Qt.ItemDataRole.UserRole, str(project.path))

        # Hack: keep a reference to the project's path on the root so the
        # methods below can find-register sessions without re-resolving.
        root.setData(3, Qt.ItemDataRole.UserRole, str(project.path))
        self._tree.addTopLevelItem(root)
        return root

    def _add_session_row(self, parent: QTreeWidgetItem, session: Session) -> QTreeWidgetItem:
        child = QTreeWidgetItem()
        child.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemNeverHasChildren
        )
        child.setText(1, session.title or (session.session_id or "new session"))
        child.setText(
            2,
            "running" if session.launched else ("ready" if session.session_id else "new"),
        )
        child.setData(1, Qt.ItemDataRole.UserRole, session.session_id)
        parent.addChild(child)

        # Action column: close button for running sessions, relaunch otherwise.
        btn = self._make_session_button(session, child)
        self._tree.setItemWidget(child, 3, btn)
        return child

    def _make_session_button(self, session: Session, item: QTreeWidgetItem) -> QPushButton:
        if session.launched:
            btn = make_button("x", role="negative")
            btn.setToolTip("Close this session")
            btn.clicked.connect(lambda: self._close_session(item))
        elif session.session_id:
            btn = make_button("open", role="primary")
            btn.setToolTip("Relaunch this session")
            btn.clicked.connect(lambda: self._relaunch_session(item))
        else:
            btn = make_button("+", role="primary")
            btn.setToolTip("Open a new session")
            btn.clicked.connect(lambda: self._open_session(item.parent() or item))
        btn.setFixedWidth(72)
        return btn

    # ---- actions --------------------------------------------------------------

    def _project_path_of(self, item: QTreeWidgetItem) -> Path:
        path = item.data(0, Qt.ItemDataRole.UserRole) or item.data(3, Qt.ItemDataRole.UserRole)
        return Path(str(path))

    def _add_session_to_project(self, project: Project, session: Session) -> None:
        """Persist a session back into the registry for *project*."""
        projects = load_registry()
        target = next((p for p in projects if p.path == project.path), None)
        if target is None:
            target = project
            projects.append(target)
        target.sessions = [s for s in target.sessions if s.session_id != session.session_id]
        target.sessions.append(session)
        save_registry(projects)

    def _open_session(self, project_item: QTreeWidgetItem) -> None:
        """Spawn a brand-new opencode session for the project in a new tab."""
        path = Path(self._project_path_of(project_item))
        session = Session(session_id=_new_session_id(), title="new session", launched=True)
        project = find_project(path)
        if project is None:
            return
        self._launch(path, session.session_id)
        self._add_session_to_project(project, session)
        self._add_session_row_with_reload(project, session)

    def _relaunch_session(self, item: QTreeWidgetItem) -> None:
        session_id = item.data(1, Qt.ItemDataRole.UserRole)
        path = Path(self._project_path_of(item))
        project = find_project(path)
        if project is None or not session_id:
            return
        self._launch(path, session_id)
        session = next((s for s in project.sessions if s.session_id == session_id), None)
        if session is not None:
            session.launched = True
        save_registry(load_registry())

    def _close_session(self, item: QTreeWidgetItem) -> None:
        """Terminate the running opencode process for *item*."""
        session_id = item.data(1, Qt.ItemDataRole.UserRole)
        if not session_id:
            return
        try:
            subprocess.run(
                ["pkill", "-TERM", "-f", f"--session {session_id}"],
                capture_output=True,
                check=False,
            )
        except OSError:
            pass
        path = Path(self._project_path_of(item))
        project = find_project(path)
        if project is not None:
            for s in project.sessions:
                if s.session_id == session_id:
                    s.launched = False
            save_registry(load_registry())
        item.setText(2, "ready")

    def _add_session_row_with_reload(self, project: Project, session: Session) -> None:
        # Find the matching top-level item and append the child.
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            if root.data(3, Qt.ItemDataRole.UserRole) == str(project.path):
                self._add_session_row(root, session)
                root.setExpanded(True)
                return

    # ---- launching ------------------------------------------------------------

    def _launch(self, path: Path, session_id: str) -> None:
        """Open a GNOME Terminal tab running opencode-fork for *path*.

        The terminal command cd's into the project, then runs the opencode
        fork with ``--session <id>`` so opencode both resumes/creates that
        session and sets the tab title (OSC) to the session's topic.
        """
        shell_cmd = f"cd {_shq(str(path))} && {OPENCODE_WRAPPER} --session {_shq(session_id)}"
        gnome = [
            "gnome-terminal",
            "--tab",
            "--title",
            path.name,
            "--",
            "bash",
            "-lc",
            shell_cmd,
        ]
        # Detached (own session) so the terminal outlives this widget and the
        # UI never blocks. On no-display/headless this is a no-op print.
        try:
            subprocess.Popen(
                gnome,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            print(f"[session-launcher] failed to launch terminal: {e}")


def _shq(value: str) -> str:
    """Shell-quote *value* for embedding in an sh -c command."""
    return "'" + value.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from andaime.qt.theme import get_stylesheet, qpalette, colors

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(qpalette(colors()))
    app.setStyleSheet(get_stylesheet())
    window = SessionTree()
    window.resize(720, 460)
    window.show()
    sys.exit(app.exec())
