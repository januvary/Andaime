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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from andaime.qt.theme import colors, make_button


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


def scan_projects(root: Path) -> list[tuple[str, Path]]:
    """Scan *root* for directories containing a ``main.py`` file.

    Returns a list of ``(name, path)`` tuples sorted by name.
    """
    projects: list[tuple[str, Path]] = []
    if not root.is_dir():
        return projects
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and (entry / "main.py").is_file():
            projects.append((entry.name, entry))
    return projects


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
    """A single row in the launcher: name + launch/stop + console buttons."""

    def __init__(
        self,
        name: str,
        path: Path,
        python_exe: str,
        andaime_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self.path = path
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

        layout.addStretch()

        self.btn_toggle = make_button("Launch", parent=self)
        self.btn_toggle.setFixedWidth(90)
        self.btn_toggle.clicked.connect(self.toggle)
        layout.addWidget(self.btn_toggle)

        self.btn_console = make_button("Console", role="flat", parent=self)
        self.btn_console.setFixedWidth(90)
        self.btn_console.clicked.connect(self._show_console)
        layout.addWidget(self.btn_console)

        self._update_status(False)

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
            self.btn_toggle.setText("Stop")
        else:
            self.status_label.setStyleSheet("color: #444; font-size: 16px;")
            self.btn_toggle.setText("Launch")

    # ---- console ----

    def _show_console(self) -> None:
        if self.console is None:
            self.console = ConsoleDialog(self.name, self)
        self.console.show()
        self.console.raise_()

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
    """Main launcher window — auto-scans for projects and displays rows."""

    def __init__(self, projects_root: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dev Launcher")
        self.resize(600, 400)

        self.projects_root = projects_root or find_projects_root()
        self.python_exe = find_python_exe()
        self.andaime_root = Path(__file__).resolve().parent.parent.parent

        self._rows: list[ProjectRow] = []

        self._build_ui()
        self._scan()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Projects:"))
        self.path_edit = QLineEdit(str(self.projects_root))
        header.addWidget(self.path_edit, 1)
        btn_browse = make_button("Rescan", role="flat", parent=self)
        btn_browse.clicked.connect(self._scan)
        header.addWidget(btn_browse)
        layout.addLayout(header)

        # Project rows container
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.rows_layout.setSpacing(0)
        layout.addWidget(self.rows_widget)

        layout.addStretch()

        # Footer info
        info = QLabel(f"Python: {self.python_exe}")
        info.setStyleSheet(f"color: {colors()['text_dim']};")
        layout.addWidget(info)

    def _scan(self) -> None:
        # Clear existing rows
        for row in self._rows:
            row.stop()
            row.deleteLater()
        self._rows.clear()

        # Parse custom root if changed
        custom = self.path_edit.text().strip()
        if custom:
            self.projects_root = Path(custom)

        projects = scan_projects(self.projects_root)
        if not projects:
            self.rows_layout.addWidget(QLabel("  No projects with main.py found."))
            return

        for name, path in projects:
            row = ProjectRow(
                name=name,
                path=path,
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
