"""Dev Launcher — a Qt GUI for launching and monitoring multiple PySide6 apps.

Scans a root directory for projects containing ``main.py``, and provides a
button grid to launch/stop each one. A file watcher auto-restarts apps when
source files change. Per-app console output is available in a popup dialog.

Usage::

    python -m andaime.qt.dev.dev_launcher
    # or
    from andaime.qt.dev.dev_launcher import DevLauncher
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Allow direct-script execution (e.g. the Super+/ keybinding runs
# ``python3 …/dev_launcher.py --focus-or-launch``): ensure the project root
# is importable before the ``andaime.*`` imports below.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# File types that trigger an auto-restart when they change.
WATCHED_EXTENSIONS = (".py", ".qml", ".qss", ".json", ".toml", ".ui")

# Directories that never contain source (runtime data, DBs, logs, caches).
# Changes to them (e.g. saving a process) must not restart the app.
SKIP_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    "dist",
    ".egg-info",
    "node_modules",
    "_update_staging",
    "data",       # DBs, config.json, logs, tokens
    "REMESSAS",   # saved-process PDFs/folders
    "backups",
    ".ruff_cache",
    ".mypy_cache",
    ".pytest_cache",
    ".coverage",
    ".codebase-memory",
}

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

from andaime.qt.fs import reveal_path
from andaime.qt.theme import colors, make_button
from andaime.qt.dev.project_registry import Project, source_files

OPENCODE_WRAPPER = os.path.expanduser("~/.local/bin/opencode-fork")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_python_exe() -> str:
    """Find the bundled Python interpreter (falls back to sys.executable)."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent.parent / "python" / "bin" / "python",
        Path(__file__).resolve().parent.parent.parent.parent / "python" / "bin" / "python3",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    return sys.executable


def find_projects_root() -> Path:
    """Return the default projects root (the parent of the andaime dir)."""
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _shq(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


# ---------------------------------------------------------------------------
# tmux helpers — the control surface for session management
# ---------------------------------------------------------------------------

def _tmux_session_name(project_path: Path) -> str:
    safe = project_path.name.replace(" ", "_").replace(".", "-").replace("/", "-")
    return f"oc_{safe}"


def _tmux_has_session(name: str) -> bool:
    return subprocess.run(["tmux", "has-session", "-t", name],
                          capture_output=True).returncode == 0


def _tmux_ensure_session(name: str, path: Path) -> bool:
    """Create a detached tmux session if it doesn't exist. Returns True if new."""
    if _tmux_has_session(name):
        return False
    shell_cmd = f"cd {_shq(str(path))} && {OPENCODE_WRAPPER}; echo 'Exit: '$?; read -p 'Press Enter to close.'"
    subprocess.run(
        ["tmux", "new-session", "-d", "-s", name, "-c", str(path),
         "bash", "-lc", shell_cmd],
        capture_output=True,
    )
    # Configure the session for TUI apps: truecolor passthrough, mouse support
    # (clickable status-bar tabs), and name the window from the pane title.
    for args in [
        ["terminal-features", "*:RGB"],
        ["allow-passthrough", "on"],
        ["mouse", "on"],
    ]:
        subprocess.run(["tmux", "set-option", "-t", name, *args], capture_output=True)
    for args in [
        ["allow-rename", "on"],
        ["automatic-rename", "on"],
        ["automatic-rename-format", "#{pane_title}"],
    ]:
        subprocess.run(["tmux", "set-window-option", "-t", name, *args], capture_output=True)
    return True


def _tmux_new_window(name: str, path: Path) -> None:
    shell_cmd = f"cd {_shq(str(path))} && {OPENCODE_WRAPPER}; echo 'Exit: '$?; read -p 'Press Enter to close.'"
    subprocess.run(
        ["tmux", "new-window", "-t", name, "-c", str(path),
         "bash", "-lc", shell_cmd],
        capture_output=True,
    )
    for args in [
        ["allow-rename", "on"],
        ["automatic-rename", "on"],
        ["automatic-rename-format", "#{pane_title}"],
    ]:
        subprocess.run(["tmux", "set-window-option", "-t", name, *args], capture_output=True)


def _tmux_kill_window(name: str, index: int) -> None:
    subprocess.run(["tmux", "kill-window", "-t", f"{name}:{index}"],
                   capture_output=True)


def _tmux_list_windows(name: str) -> list[tuple[int, str, bool]]:
    """Return [(window_index, window_name, is_active)] for a tmux session."""
    result = subprocess.run(
        ["tmux", "list-windows", "-t", name, "-F",
         "#{window_index} #{window_active} #{window_name}"],
        capture_output=True, text=True,
    )
    windows: list[tuple[int, str, bool]] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3:
            try:
                windows.append((int(parts[0]), parts[2], parts[1] == "1"))
            except ValueError:
                continue
    return windows


def _tmux_window_busy(session: str, window_index: int) -> bool:
    """True if the opencode agent in the window is actively working.

    opencode's status bar shows ``esc interrupt`` only while the agent is
    running, which makes it a reliable on-screen busy signature.
    """
    result = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", f"{session}:{window_index}", "-S", "-10"],
        capture_output=True, text=True,
    )
    return "esc interrupt" in result.stdout


def _is_terminal_focused(session: str) -> bool:
    """True if the ptyxis window hosting the session currently has keyboard
    focus (via the devlauncher-window-raise shell extension). Degrades to
    False when the extension method is unavailable."""
    pid = _terminal_pid_for_session(session)
    if pid is None:
        return False
    try:
        result = subprocess.run(
            ["gdbus", "call", "--session",
             "--dest", "org.andaime.DevLauncher",
             "--object-path", "/org/andaime/DevLauncher/window",
             "--method", "org.andaime.DevLauncher.Window.IsActiveByPid", str(pid)],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "true" in result.stdout.lower()


def _shade(hex_color: str, factor: float) -> str:
    """Darken (factor<1) / lighten (factor>1) a #rrggbb color."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    clamp = lambda v: max(0, min(255, int(v)))  # noqa: E731
    return "#{:02x}{:02x}{:02x}".format(
        clamp(r * factor), clamp(g * factor), clamp(b * factor)
    )


def _find_terminal() -> str | None:
    for candidate in (os.environ.get("TERMINAL"), "ptyxis", "gnome-terminal", "kgx", "konsole"):
        if candidate and shutil.which(candidate):
            return candidate
    return None


def _tmux_has_client(name: str) -> bool:
    """True if any terminal is currently attached to the session."""
    result = subprocess.run(["tmux", "list-clients", "-t", name],
                            capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


def _tmux_select_window(name: str, window_index: int) -> None:
    """Make the given window the active one in the session (all clients follow)."""
    subprocess.run(["tmux", "select-window", "-t", f"{name}:{window_index}"],
                   capture_output=True)


def _tmux_attach(name: str) -> None:
    """Open a terminal window attached to the tmux session (once per session)."""
    term = _find_terminal()
    if not term:
        print("[dev-launcher] no terminal emulator found (set $TERMINAL)")
        return
    subprocess.Popen(
        [term, "--", "bash", "-lc", f"tmux attach -t {name}"],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _terminal_pid_for_session(name: str) -> int | None:
    """PID of the ptyxis window whose command attaches to the tmux session.

    Each session terminal is a standalone ``ptyxis -- bash -lc "tmux attach …"``
    process, so matching the cmdline gives a 1:1 session -> window mapping.
    """
    needle = f"tmux attach -t {name}"
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return None
    for proc in entries:
        pid_str = proc.name
        if not pid_str.isdigit():
            continue
        try:
            comm = (proc / "comm").read_text().strip()
            if not comm.startswith("ptyxis") or comm.startswith("ptyxis-"):
                continue
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                errors="replace"
            )
            if needle in cmdline:
                return int(pid_str)
        except (OSError, ValueError):
            continue
    return None


def _raise_window_by_pid(pid: int) -> bool:
    """Raise/focus the window of ``pid`` via the devlauncher-window-raise
    GNOME Shell extension (org.andaime.DevLauncher). No-op if unavailable."""
    try:
        result = subprocess.run(
            ["gdbus", "call", "--session",
             "--dest", "org.andaime.DevLauncher",
             "--object-path", "/org/andaime/DevLauncher/window",
             "--method", "org.andaime.DevLauncher.Window.RaiseByPid", str(pid)],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and "true" in result.stdout.lower()


def _raise_session_terminal(name: str, delay_ms: int = 0) -> None:
    """Bring the ptyxis window hosting the tmux session to the foreground."""
    def _do() -> None:
        pid = _terminal_pid_for_session(name)
        if pid is not None:
            _raise_window_by_pid(pid)
    if delay_ms > 0:
        QTimer.singleShot(delay_ms, _do)
    else:
        _do()


def _devlauncher_pids(exclude: int) -> list[int]:
    """PIDs of running DevLauncher GUI processes (python + dev_launcher)."""
    pids: list[int] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return pids
    for proc in entries:
        pid_str = proc.name
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        if pid == exclude:
            continue
        try:
            comm = (proc / "comm").read_text().strip()
            if not comm.startswith("python"):
                continue
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                errors="replace"
            )
            if "dev_launcher" in cmdline:
                pids.append(pid)
        except (OSError, ValueError):
            continue
    return pids


def _focus_or_launch() -> None:
    """Raise the running DevLauncher window, or start one if none is running.

    Invoked by the Super+/ custom keybinding via ``--focus-or-launch``.
    """
    for pid in _devlauncher_pids(exclude=os.getpid()):
        if _raise_window_by_pid(pid):
            return
    if not _devlauncher_pids(exclude=os.getpid()):
        script = Path(__file__).resolve()
        subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(_PROJECT_ROOT),
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


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
        self._dir_snapshots: dict[str, dict[str, tuple[int, int]]] = {}
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

        self._tmux_timer = QTimer(self)
        self._tmux_timer.setSingleShot(False)
        self._tmux_timer.setInterval(3000)
        self._tmux_timer.timeout.connect(self._reconcile_tmux)
        self._tmux_timer.start()

        # Agent activity: per-window state ("idle" | "running" | "unseen")
        # persists across row rebuilds; tmux window indices are the keys.
        self._win_states: dict[int, str] = {}
        self._dot_widgets: dict[int, QLabel] = {}
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setSingleShot(False)
        self._pulse_timer.setInterval(700)
        self._pulse_timer.timeout.connect(self._on_pulse)
        self._pulse_on = True

        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- header row (existing buttons + new session button) ----
        header = QHBoxLayout()
        header.setContentsMargins(8, 4, 8, 4)

        self.expand_label = QLabel("▸")
        self.expand_label.setFixedWidth(16)
        self.expand_label.setStyleSheet(
            f"color: {colors()['text_dim']}; font-size: 14px; font-family: monospace;"
        )
        self.expand_label.mousePressEvent = lambda e: self._toggle_sessions()
        header.addWidget(self.expand_label)

        self.status_label = QLabel("●")
        self.status_label.setStyleSheet("color: #444; font-size: 16px;")
        header.addWidget(self.status_label)

        self.name_label = QLabel(self.name)
        self.name_label.setMinimumWidth(200)
        self.name_label.setStyleSheet(f"font-weight: 600; color: {colors()['text']};")
        header.addWidget(self.name_label)
        self._set_src_tooltip()

        # Activity badges: "●N running  ⚑N finished-unseen" (hidden when 0)
        self.badge_label = QLabel("")
        self.badge_label.setStyleSheet("font-size: 12px;")
        header.addWidget(self.badge_label)

        if self.project.capabilities.git:
            self.git_stat_label = QLabel("")
            self.git_stat_label.setMinimumWidth(90)
            self.git_stat_label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            header.addWidget(self.git_stat_label)
        else:
            self.git_stat_label = None

        header.addStretch()

        if self.project.capabilities.launchable:
            self.btn_toggle = make_button("Launch", parent=self)
            self.btn_toggle.setFixedWidth(90)
            self.btn_toggle.clicked.connect(self.toggle)
            header.addWidget(self.btn_toggle)
        else:
            self.btn_toggle = None

        # Session "+" button — always present, spawns an opencode session
        self.btn_session = make_button("+", role="primary", parent=self)
        self.btn_session.setFixedWidth(40)
        self.btn_session.setToolTip("Open a new opencode session")
        self.btn_session.clicked.connect(self._spawn_session)
        header.addWidget(self.btn_session)

        # Folder button — always present, opens the project root in the file explorer
        self.btn_folder = make_button("Folder", role="flat", parent=self)
        self.btn_folder.setFixedWidth(90)
        self.btn_folder.setToolTip(f"Open {self.path} in the file explorer")
        self.btn_folder.clicked.connect(self._open_folder)
        header.addWidget(self.btn_folder)

        if self.project.capabilities.git:
            self.btn_console = make_button("Console", role="flat", parent=self)
            self.btn_console.setFixedWidth(90)
            self.btn_console.clicked.connect(self._show_console)
            header.addWidget(self.btn_console)

            self.btn_commit = make_button("Commit", role="flat", parent=self)
            self.btn_commit.setFixedWidth(90)
            self.btn_commit.clicked.connect(self._commit_assistant)
            header.addWidget(self.btn_commit)
        else:
            self.btn_console = None
            self.btn_commit = None

        outer.addLayout(header)

        # ---- collapsible session children (driven by tmux state) ----
        self._sessions_expanded = False
        self._sessions_container = QWidget()
        self._sessions_layout = QVBoxLayout(self._sessions_container)
        self._sessions_layout.setContentsMargins(24, 0, 8, 4)
        self._sessions_layout.setSpacing(0)
        self._sessions_container.setVisible(False)
        outer.addWidget(self._sessions_container)

        self._tmux_name = _tmux_session_name(self.path)
        self._reconcile_tmux()
        # Live sessions at startup (e.g. launcher reopened): show expanded,
        # otherwise the repopulated rows stay hidden behind the collapsed arrow.
        if self._sessions_layout.count() and not self._sessions_expanded:
            self._toggle_sessions()

        self._update_status(False)
        self.refresh_git_stat()

    # ---- session management (tmux-driven) ----

    @property
    def _tmux_session(self) -> str:
        return self._tmux_name

    def _toggle_sessions(self) -> None:
        self._sessions_expanded = not self._sessions_expanded
        self.expand_label.setText("▾" if self._sessions_expanded else "▸")
        self._sessions_container.setVisible(self._sessions_expanded)

    def _open_folder(self) -> None:
        reveal_path(str(self.path))

    def _spawn_session(self) -> None:
        if not self._sessions_expanded:
            self._toggle_sessions()
        was_new = _tmux_ensure_session(self._tmux_session, self.path)
        if not was_new:
            _tmux_new_window(self._tmux_session, self.path)
        if not _tmux_has_client(self._tmux_session):
            _tmux_attach(self._tmux_session)
            _raise_session_terminal(self._tmux_session, delay_ms=800)
        else:
            _raise_session_terminal(self._tmux_session)
        self._reconcile_tmux()

    def _close_session(self, window_index: int) -> None:
        _tmux_kill_window(self._tmux_session, window_index)
        self._reconcile_tmux()

    def _reconcile_tmux(self) -> None:
        """Rebuild session sub-rows from live tmux state + agent activity."""
        windows = _tmux_list_windows(self._tmux_session) if _tmux_has_session(self._tmux_session) else []

        # Focus check (1 subprocess) only when it can change an outcome.
        prev_states = dict(self._win_states)
        need_focus = any(s in ("running", "unseen") for s in prev_states.values())
        focused = _is_terminal_focused(self._tmux_session) if need_focus else False
        active_idx = next((idx for idx, _n, active in windows if active), None)

        for idx, _name, _active in windows:
            busy = _tmux_window_busy(self._tmux_session, idx)
            prev = prev_states.get(idx, "idle")
            if busy:
                new = "running"
            elif prev == "running":
                # Finished: gold flag unless the user is watching right now.
                new = "idle" if (focused and idx == active_idx) else "unseen"
            elif prev == "unseen":
                new = "idle" if (focused and idx == active_idx) else "unseen"
            else:
                new = "idle"
            self._win_states[idx] = new
        self._win_states = {i: s for i, s in self._win_states.items() if i in {w[0] for w in windows}}

        # Clear and rebuild — tmux is the source of truth.
        while self._sessions_layout.count():
            item = self._sessions_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._dot_widgets: dict[int, QLabel] = {}

        for idx, name, _active in windows:
            self._add_session_sub_row(idx, name, self._win_states.get(idx, "idle"))

        self._update_badges()
        if any(s == "running" for s in self._win_states.values()):
            if not self._pulse_timer.isActive():
                self._pulse_timer.start()
        else:
            self._pulse_timer.stop()

    def _dot_style(self, state: str) -> str:
        c = colors()
        if state == "running":
            color = c["status_success"] if self._pulse_on else _shade(c["status_success"], 0.45)
            return f"color: {color}; font-size: 13px;"
        if state == "unseen":
            return f"color: {c['status_warning']}; font-size: 13px;"
        return f"color: {c['text_dim']}; font-size: 12px;"

    def _on_pulse(self) -> None:
        """Alternate running dots between bright/dim while agents work."""
        self._pulse_on = not self._pulse_on
        for idx, dot in self._dot_widgets.items():
            if self._win_states.get(idx) == "running":
                dot.setStyleSheet(self._dot_style("running"))

    def _update_badges(self) -> None:
        running = sum(1 for s in self._win_states.values() if s == "running")
        unseen = sum(1 for s in self._win_states.values() if s == "unseen")
        c = colors()
        parts = []
        if running:
            parts.append(
                f"<span style='color:{c['status_success']}'>●{running}</span>"
            )
        if unseen:
            parts.append(
                f"<span style='color:{c['status_warning']}'>⚑{unseen}</span>"
            )
        self.badge_label.setText("  ".join(parts))
        tip = []
        if running:
            tip.append(f"{running} agent(s) running")
        if unseen:
            tip.append(f"{unseen} agent(s) finished — not yet viewed")
        self.badge_label.setToolTip(" / ".join(tip))

    def _add_session_sub_row(self, window_index: int, title: str, state: str) -> None:
        c = colors()
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 1, 0, 1)
        layout.setSpacing(6)

        # State dot (pulses for running via the shared timer)
        dot = QLabel({"running": "●", "unseen": "⚑", "idle": "○"}.get(state, "○"))
        dot.setStyleSheet(self._dot_style(state))
        dot.setToolTip(
            {"running": "Agent is working", "unseen": "Agent finished — not yet viewed"}.get(state, "Idle")
        )
        layout.addWidget(dot)
        self._dot_widgets[window_index] = dot

        label = QLabel(title)
        text_color = c["text"] if state != "idle" else c["text_dim"]
        label.setStyleSheet(f"color: {text_color}; font-size: 12px;")
        label.setCursor(Qt.CursorShape.PointingHandCursor)
        label.setToolTip("Click to switch this terminal to this session")
        layout.addWidget(label)
        layout.addStretch()

        def _focus(idx: int) -> None:
            self._win_states[idx] = "idle"  # clicking = seeing it
            if not _tmux_has_client(self._tmux_session):
                _tmux_attach(self._tmux_session)
                _raise_session_terminal(self._tmux_session, delay_ms=800)
            else:
                _tmux_select_window(self._tmux_session, idx)
                _raise_session_terminal(self._tmux_session)
            self._reconcile_tmux()
        label.mousePressEvent = lambda e, idx=window_index: _focus(idx)

        # Left accent bar colored by state distinguishes session rows from
        # project headers; unseen additionally gets a soft background tint.
        bar = {
            "running": c["status_success"],
            "unseen": c["status_warning"],
            "idle": c["panel_border"],
        }[state]
        bg = f"background-color: {c['box_bg']};" if state == "unseen" else ""
        row.setStyleSheet(f"border-left: 3px solid {bar}; {bg}")

        btn_close = make_button("x", role="negative", parent=row)
        btn_close.setFixedWidth(40)
        btn_close.setToolTip("Close this session")
        btn_close.clicked.connect(lambda _, idx=window_index: self._close_session(idx))
        layout.addWidget(btn_close)

        self._sessions_layout.addWidget(row)

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
            from andaime.qt.dev.commit_assistant import find_repo_root
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
        from andaime.qt.dev.commit_assistant import find_repo_root, present_commit

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
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in fnames:
                if f.endswith(WATCHED_EXTENSIONS):
                    files.append(str(Path(root) / f))

        # Watch individual files only (not directories) so that unrelated
        # changes like saving a PDF don't trigger a restart.
        # If there are too many files, watch directories but filter by extension.
        if len(files) > 200:
            directories = []
            for root, dirs, _ in os.walk(self.path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                directories.append(root)
            self.watcher.addPaths(directories)
            self._watched_files = directories
            # Snapshot all watched-type files under each directory so that a
            # change to a non-source file in the same dir (DB, log) can be
            # told apart from an actual edit (see _dir_snapshot_changed).
            self._dir_snapshots = {
                d: self._scan_watched_files(d) for d in directories
            }
        else:
            self.watcher.addPaths(files)
            self._watched_files = files
            self._dir_snapshots = {}

    def _unwatch_project(self) -> None:
        if self._watched_files:
            self.watcher.removePaths(self._watched_files)
            self._watched_files = []
            self._dir_snapshots = {}

    def _on_file_changed(self, path: str) -> None:
        self._restart_timer.start()

    def _on_dir_changed(self, path: str) -> None:
        # When watching directories (too many individual files), only trigger
        # if a watched file type actually changed in this directory.
        if not self._dir_snapshot_changed(path):
            return
        self._restart_timer.start()

    def _dir_snapshot_changed(self, dir_path: str) -> bool:
        """Return True only when a watched-type file in *dir_path* changed.

        QFileSystemWatcher only reports the directory in dir-watch mode, so
        runtime writes (DBs, logs, PDFs) that share a directory with source
        files otherwise masquerade as edits.
        """
        fresh = self._scan_watched_files(dir_path)
        prev = self._dir_snapshots.get(dir_path)
        # Unknown dir (created during the run): treat the presence of watched
        # files as a change.
        changed = fresh != prev if prev is not None else bool(fresh)
        self._dir_snapshots[dir_path] = fresh
        return changed

    @staticmethod
    def _scan_watched_files(dir_path: str) -> dict[str, tuple[int, int]]:
        """Snapshot ``{name: (mtime_ns, size)}`` of watched-type files."""
        snapshot: dict[str, tuple[int, int]] = {}
        try:
            for entry in os.scandir(dir_path):
                if not entry.is_file() or not entry.name.endswith(WATCHED_EXTENSIONS):
                    continue
                try:
                    st = entry.stat()
                    snapshot[entry.name] = (st.st_mtime_ns, st.st_size)
                except OSError:
                    pass
        except OSError:
            pass
        return snapshot

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
        self.resize(1000, 420)

        self.projects_root = projects_root or find_projects_root()
        self.python_exe = find_python_exe()
        self.andaime_root = Path(__file__).resolve().parent.parent.parent.parent

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
        from andaime.qt.dev.project_registry import add_project

        raw = self.path_edit.text().strip()
        if not raw:
            return
        add_project(Path(raw).expanduser())
        self._rebuild()

    def _refresh(self) -> None:
        from andaime.qt.dev.project_registry import refresh_capabilities

        refresh_capabilities()
        self._rebuild()

    def _clear_rows(self) -> None:
        for row in self._rows:
            row.stop()
            row.deleteLater()
        self._rows.clear()

    def _rebuild(self) -> None:
        from andaime.qt.dev.project_registry import load_registry

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
    if "--focus-or-launch" in sys.argv:
        _focus_or_launch()
        sys.exit(0)

    from PySide6.QtWidgets import QApplication
    from andaime.qt.theme import stylesheet, qpalette, colors

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(qpalette(colors()))
    app.setStyleSheet(stylesheet())
    window = DevLauncher()
    window.show()
    sys.exit(app.exec())
