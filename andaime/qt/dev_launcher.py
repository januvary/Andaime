"""Dev Launcher — a Qt GUI for launching and monitoring multiple PySide6 apps.

Scans a root directory for projects containing ``main.py``, and provides a
button grid to launch/stop each one. A file watcher auto-restarts apps when
source files change. Per-app console output is available in a popup dialog.

Usage::

    python -m andaime.qt.dev_launcher
    # or
    from andaime.qt.dev_launcher import DevLauncher
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    QProcess,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from andaime.qt.theme import colors, make_button
from andaime.project_registry import Project, source_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_python_exe() -> str:
    """Find the bundled Python interpreter (falls back to sys.executable)."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "python" / "bin" / "python",
        Path(__file__).resolve().parent.parent.parent / "python" / "bin" / "python3",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return sys.executable


def find_projects_root() -> Path:
    """Return the default projects root (the parent of the andaime dir)."""
    return Path(__file__).resolve().parent.parent.parent.parent


# ---------------------------------------------------------------------------
# Console dialog
# ---------------------------------------------------------------------------

class ConsoleDialog(QDialog):
    """Shows live console output for a running app."""

    def __init__(self, app_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Console — {app_name}")
        self.resize(800, 400)

        layout = QVBoxLayout(self)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            f"QTextEdit {{ background: {colors()['box_bg']}; color: {colors()['text']}; }}"
        )
        layout.addWidget(self.text_edit)

        btn_close = make_button("Close", role="flat", parent=self)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def append(self, text: str) -> None:
        self.text_edit.moveCursor(self.text_edit.textCursor().MoveOperation.End)
        self.text_edit.insertPlainText(text)
        self.text_edit.moveCursor(self.text_edit.textCursor().MoveOperation.End)


# ---------------------------------------------------------------------------
# Project row widget
# ---------------------------------------------------------------------------

class ProjectRow(QWidget):
    """A single row in the launcher: name + launch/stop + console + commit.

    Buttons adapt to the project's detected capabilities.
    """

    def __init__(
        self,
        project: Project,
        python_exe: str,
        andaime_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project = project
        self.name = project.name
        self.path = project.path
        self.python_exe = python_exe
        self.andaime_root = andaime_root

        self.process: QProcess | None = None
        self.console: ConsoleDialog | None = None
        self._watched_files: list[str] = []
        self._restart_timer = QTimer(self)
        self._restart_timer.setSingleShot(True)
        self._restart_timer.setInterval(500)
        self._restart_timer.timeout.connect(self._on_restart_triggered)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._on_file_changed)
        self.watcher.directoryChanged.connect(self._on_dir_changed)

        self._git_stat_timer = QTimer(self)
        self._git_stat_timer.setSingleShot(False)
        self._git_stat_timer.setInterval(4000)
        self._git_stat_timer.timeout.connect(self.refresh_git_stat)
        self._git_stat_timer.start()

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self.status_label = QLabel("●")
        self.status_label.setStyleSheet("color: #444; font-size: 16px;")
        layout.addWidget(self.status_label)

        self.name_label = QLabel(self.name)
        self.name_label.setMinimumWidth(200)
        layout.addWidget(self.name_label)
        self._set_src_tooltip()

        if self.project.capabilities.git:
            self.git_stat_label = QLabel("")
            self.git_stat_label.setMinimumWidth(90)
            self.git_stat_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            layout.addWidget(self.git_stat_label)
        else:
            self.git_stat_label = None

        layout.addStretch()

        if self.project.capabilities.launchable:
            self.btn_toggle = make_button("Launch", parent=self)
            self.btn_toggle.setFixedWidth(90)
            self.btn_toggle.clicked.connect(self.toggle)
            layout.addWidget(self.btn_toggle)
        else:
            self.btn_toggle = None

        if self.project.capabilities.git:
            self.btn_console = make_button("Console", role="flat", parent=self)
            self.btn_console.setFixedWidth(90)
            self.btn_console.clicked.connect(self._show_console)
            layout.addWidget(self.btn_console)

            self.btn_commit = make_button("Commit", role="flat", parent=self)
            self.btn_commit.setFixedWidth(90)
            self.btn_commit.clicked.connect(self._commit_assistant)
            layout.addWidget(self.btn_commit)
        else:
            self.btn_console = None
            self.btn_commit = None

        self._update_status(False)
        self.refresh_git_stat()

    # ---- git diff stat ----

    def _set_src_tooltip(self) -> None:
        """Set up the source-file viewer on the project name.

        Clicking the name toggles a popup listing each counted source file
        sorted by line count, most to least. No hover tooltip.
        """
        self._src_files = source_files(self.path)
        self._popup: QFrame | None = None

        self.name_label.mousePressEvent = lambda e: self._toggle_src_popup()

    def _toggle_src_popup(self) -> None:
        if self._popup is not None and self._popup.isVisible():
            self._hide_src_popup()
            return
        self._show_src_popup()

    def _show_src_popup(self) -> None:
        if not self._src_files:
            return
        if self._popup is None:
            self._popup = self._build_src_popup()
        # Position near the name label, below it.
        global_pos = self.name_label.mapToGlobal(self.name_label.rect().bottomLeft())
        self._popup.move(global_pos.x(), global_pos.y() + 4)
        self._popup.show()
        self._popup.raise_()

    def _build_src_popup(self) -> QFrame:
        popup = QFrame()
        popup.setWindowFlags(Qt.WindowType.ToolTip)
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        popup.setObjectName("srcPopup")

        layout = QVBoxLayout(popup)
        layout.setContentsMargins(8, 6, 8, 6)

        title = QLabel(f"{self.name}: {len(self._src_files)} files, "
                       f"{sum(l for _, l in self._src_files)} lines")
        title.setStyleSheet(f"color: {colors()['text_dim']}; font-weight: bold;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(360)
        scroll.setFixedHeight(280)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(1)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for path, lines in self._src_files[:80]:
            rel = os.path.relpath(path, self.path)
            row = QLabel(f"{lines:>6}  {rel}")
            row.setStyleSheet(f"color: {colors()['text']}; font-family: monospace;")
            content_layout.addWidget(row)

        scroll.setWidget(content)
        layout.addWidget(scroll)

        popup.setStyleSheet(
            f"QFrame#srcPopup {{ background-color: {colors()['box_bg']}; "
            f"border: 1px solid {colors()['text']}40; }}"
        )
        return popup

    def _hide_src_popup(self, _event=None) -> None:
        if self._popup is not None:
            self._popup.hide()

    def refresh_git_stat(self) -> None:
        """Show a +x/−y diff-stat for the project's repo, or nothing if N/A."""
        if self.git_stat_label is None:
            return
        try:
            from andaime.qt.commit_assistant import find_repo_root
            import subprocess

            repo = find_repo_root(self.path)
            if repo is None:
                self.git_stat_label.setText("")
                return
            proc = subprocess.run(
                ["git", "-C", str(repo), "diff", "--numstat"],
                capture_output=True,
                text=True,
            )
            lines = [l for l in proc.stdout.splitlines() if l.strip()]
            added = removed = 0
            for line in lines:
                parts = line.split("\t")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    added += int(parts[0])
                    removed += int(parts[1])
            # Untracked files don't appear in --numstat; count them as added lines.
            status_proc = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"],
                capture_output=True,
                text=True,
            )
            untracked = [
                l[3:].strip()
                for l in status_proc.stdout.splitlines()
                if l.startswith("??")
            ]
            if untracked:
                from pathlib import Path

                for rel in untracked:
                    p = Path(repo) / rel
                    if p.is_file():
                        added += len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            if added or removed or untracked:
                label = f'<span style="color:#5dff5d;">+{added}</span> '
                if removed:
                    label += f'<span style="color:#ff5d5d;">−{removed}</span>'
                self.git_stat_label.setText(label)
            else:
                self.git_stat_label.setText("")
        except Exception:
            self.git_stat_label.setText("")

    # ---- process management ----

    def toggle(self) -> None:
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.stop()
        else:
            self.start()

    def start(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.waitForFinished(1000)

        self.process = QProcess(self)
        self.process.setProgram(self.python_exe)
        self.process.setArguments([str(self.path / "main.py")])
        self.process.setWorkingDirectory(str(self.path))

        env = QProcess.systemEnvironment()
        env.append(f"PYTHONPATH={self.andaime_root}")
        self.process.setProcessEnvironment(
            QProcessEnvironment_from_list(env)
        )

        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._on_finished)

        self.process.start()
        if not self.process.waitForStarted(3000):
            self._append_to_console(f"[launcher] Failed to start {self.name}\n")
            return

        self._update_status(True)
        self._watch_project()

    def stop(self) -> None:
        if self.process is not None:
            self.process.kill()
            self.process.waitForFinished(2000)
        self._update_status(False)
        self._unwatch_project()

    # ---- UI updates ----

    def _update_status(self, running: bool) -> None:
        if running:
            self.status_label.setStyleSheet("color: #5dff5d; font-size: 16px;")
        else:
            self.status_label.setStyleSheet("color: #444; font-size: 16px;")
        if self.btn_toggle is not None:
            self.btn_toggle.setText("Stop" if running else "Launch")

    # ---- console ----

    def _show_console(self) -> None:
        if self.console is None:
            self.console = ConsoleDialog(self.name, self)
        self.console.show()
        self.console.raise_()

    def _commit_assistant(self) -> None:
        from andaime.qt.commit_assistant import find_repo_root, present_commit

        repo = find_repo_root(self.path)
        if repo is None:
            self._append_to_console(f"[commit] {self.name}: not a git repository\n")
            return
        committed, detail = present_commit(self.name, repo, self)
        self._append_to_console(f"[commit] {self.name}: {detail}\n")
        self.refresh_git_stat()

    def _append_to_console(self, text: str) -> None:
        if self.console is not None:
            self.console.append(text)

    # ---- process I/O ----

    def _read_stdout(self) -> None:
        if self.process is None:
            return
        data = self.process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._append_to_console(data)

    def _read_stderr(self) -> None:
        if self.process is None:
            return
        data = self.process.readAllStandardError().data().decode("utf-8", errors="replace")
        self._append_to_console(data)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._append_to_console(f"\n[launcher] {self.name} exited with code {exit_code}\n")
        self._update_status(False)
        self._unwatch_project()

    # ---- file watcher ----

    def _watch_project(self) -> None:
        self._unwatch_project()
        files = []
        for root, dirs, fnames in os.walk(self.path):
            # Skip common non-project dirs
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", "dist", ".egg-info", "node_modules", "_update_staging"}]
            for f in fnames:
                if f.endswith((".py", ".qml", ".qss", ".json", ".toml", ".ui")):
                    files.append(str(Path(root) / f))

        # Watch individual files only (not directories) so that unrelated
        # changes like saving a PDF don't trigger a restart.
        # If there are too many files, watch directories but filter by extension.
        if len(files) > 200:
            directories = []
            for root, dirs, _ in os.walk(self.path):
                dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", "dist", ".egg-info", "node_modules", "_update_staging"}]
                directories.append(root)
            self.watcher.addPaths(directories)
            self._watched_files = directories
        else:
            self.watcher.addPaths(files)
            self._watched_files = files

    def _unwatch_project(self) -> None:
        if self._watched_files:
            self.watcher.removePaths(self._watched_files)
            self._watched_files = []

    def _on_file_changed(self, path: str) -> None:
        self._restart_timer.start()

    def _on_dir_changed(self, path: str) -> None:
        # When watching directories (too many individual files), only trigger
        # if a relevant file type was actually changed.
        if not self._has_recent_relevant_change(path):
            return
        self._restart_timer.start()

    def _has_recent_relevant_change(self, dir_path: str) -> bool:
        """Check if *dir_path* contains any watched file types."""
        try:
            for entry in os.scandir(dir_path):
                if entry.is_file() and entry.name.endswith((".py", ".qml", ".qss", ".json", ".toml", ".ui")):
                    return True
        except OSError:
            pass
        return False

    def _on_restart_triggered(self) -> None:
        if self.process is not None and self.process.state() == QProcess.ProcessState.Running:
            self._append_to_console(f"\n[launcher] File change detected — restarting {self.name}\n\n")
            self.stop()
            QTimer.singleShot(300, self.start)


# ---------------------------------------------------------------------------
# QProcessEnvironment helper
# ---------------------------------------------------------------------------

def QProcessEnvironment_from_list(env_list: list[str]):
    """Build a QProcessEnvironment from a list of ``KEY=VALUE`` strings."""
    from PySide6.QtCore import QProcessEnvironment

    env = QProcessEnvironment.systemEnvironment()
    for item in env_list:
        if item.startswith("PYTHONPATH="):
            # Append rather than overwrite
            existing = env.value("PYTHONPATH", "")
            new_path = item[len("PYTHONPATH="):]
            if existing:
                env.insert("PYTHONPATH", f"{new_path}{os.pathsep}{existing}")
            else:
                env.insert("PYTHONPATH", new_path)
        elif "=" in item:
            key, _, value = item.partition("=")
            env.insert(key, value)
    return env


# ---------------------------------------------------------------------------
# Main launcher widget
# ---------------------------------------------------------------------------

class DevLauncher(QWidget):
    """Main launcher window — curated project registry with capability-aware rows."""

    def __init__(self, projects_root: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dev Launcher")
        self.resize(640, 420)

        self.projects_root = projects_root or find_projects_root()
        self.python_exe = find_python_exe()
        self.andaime_root = Path(__file__).resolve().parent.parent.parent

        self._rows: list[ProjectRow] = []

        self._build_ui()
        self._rebuild()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header: add-by-path bar + add/refresh buttons
        header = QHBoxLayout()
        header.addWidget(QLabel("Add project:"))
        self.path_edit = QLineEdit(str(self.projects_root))
        self.path_edit.setPlaceholderText("/path/to/project")
        header.addWidget(self.path_edit, 1)
        self.btn_add = make_button("+", role="primary", parent=self)
        self.btn_add.setFixedWidth(40)
        self.btn_add.clicked.connect(self._add_project)
        header.addWidget(self.btn_add)
        btn_refresh = make_button("Refresh", role="flat", parent=self)
        btn_refresh.clicked.connect(self._refresh)
        header.addWidget(btn_refresh)
        layout.addLayout(header)

        # Project rows container (scrollable for many projects)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows_layout.setSpacing(0)
        self.scroll.setWidget(self.rows_widget)
        layout.addWidget(self.scroll, 1)

        # Footer info
        info = QLabel(f"Python: {self.python_exe}")
        info.setStyleSheet(f"color: {colors()['text_dim']};")
        layout.addWidget(info)

    def _add_project(self) -> None:
        from andaime.project_registry import add_project

        raw = self.path_edit.text().strip()
        if not raw:
            return
        add_project(Path(raw).expanduser())
        self._rebuild()

    def _refresh(self) -> None:
        from andaime.project_registry import refresh_capabilities

        refresh_capabilities()
        self._rebuild()

    def _clear_rows(self) -> None:
        for row in self._rows:
            row.stop()
            row.deleteLater()
        self._rows.clear()

    def _rebuild(self) -> None:
        from andaime.project_registry import load_registry

        self._clear_rows()
        projects = load_registry()
        if not projects:
            empty = QLabel("  No projects yet — enter a path above and press +.")
            empty.setStyleSheet(f"color: {colors()['text_dim']};")
            self.rows_layout.addWidget(empty)
            return

        for project in projects:
            row = ProjectRow(
                project=project,
                python_exe=self.python_exe,
                andaime_root=self.andaime_root,
                parent=self.rows_widget,
            )
            self.rows_layout.addWidget(row)
            self._rows.append(row)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from andaime.qt.theme import stylesheet, qpalette, colors

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(qpalette(colors()))
    app.setStyleSheet(stylesheet())
    window = DevLauncher()
    window.show()
    sys.exit(app.exec())
