"""Project registry — curated list of projects with detected capabilities.

Stores an explicit list of projects (added by path) in
``~/.config/andaime/projects.json`` so the Dev Launcher is a registry the user
curates, rather than a scanner that guesses from the filesystem.

Each project records its path plus detected capabilities. Detection is run at
add-time and re-run on refresh:
  - ``git``        -> has a ``.git`` (Commit button, diff-stat, source view)
  - ``launchable`` -> has a ``main.py`` (Launch button)
  - ``node_dev``   -> has a ``package.json`` with a ``dev`` script (Launch button)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~/.config/andaime"))
REGISTRY_FILE = CONFIG_DIR / "projects.json"

_SRC_EXTS = (".py", ".qml", ".qss", ".ts", ".tsx")
_SKIP_DIRS = {
    ".git", "__pycache__", "venv", "dist", ".egg-info", "node_modules",
    "_update_staging", ".mypy_cache", ".ruff_cache", "htmlcov", ".coverage",
    "python", "include", "lib", "lib64", "site-packages", "backups", "logs",
    "data", ".codebase-memory", "test", "tests", "apps",
}


@dataclass
class Capabilities:
    git: bool = False
    launchable: bool = False
    node_dev: bool = False

    @property
    def label(self) -> str:
        tags = []
        if self.git:
            tags.append("git")
        if self.launchable:
            tags.append("launch")
        if self.node_dev:
            tags.append("npm")
        return ", ".join(tags) if tags else "static"


@dataclass
class Session:
    """A single opencode session launched for a project.

    ``session_id`` is the opencode session id ('' for an unsaved/unnamed
    session), used both to relaunch it later and to show its topic. ``title``
    is the last-known window/terminal title. ``launched`` is whether the agent
    is currently running.
    """

    session_id: str = ""
    title: str = ""
    launched: bool = False


@dataclass
class Project:
    path: Path
    capabilities: Capabilities = field(default_factory=Capabilities)
    sessions: list[Session] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name


def detect_capabilities(path: Path) -> Capabilities:
    """Detect what functions *path* supports."""
    node_dev = False
    pkg_json = path / "package.json"
    if pkg_json.is_file():
        try:
            import json as _json
            data = _json.loads(pkg_json.read_text(encoding="utf-8"))
            node_dev = isinstance(data.get("scripts", {}).get("dev"), str)
        except (OSError, ValueError, AttributeError):
            pass
    return Capabilities(
        git=(path / ".git").exists(),
        launchable=(path / "main.py").is_file(),
        node_dev=node_dev,
    )


def source_files(path: Path, limit: int | None = None) -> list[tuple[str, int]]:
    """Return ``(path, line_count)`` for relevant source files, sorted desc."""
    results: list[tuple[str, int]] = []
    for root, dirs, fnames in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in fnames:
            if f.endswith(_SRC_EXTS):
                full = os.path.join(root, f)
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        lines = sum(1 for _ in fh)
                    results.append((full, lines))
                except OSError:
                    pass
    results.sort(key=lambda item: item[1], reverse=True)
    return results if limit is None else results[:limit]


def load_registry() -> list[Project]:
    """Read the registry from disk, or return empty."""
    if not REGISTRY_FILE.is_file():
        return []
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    projects = []
    for item in data:
        try:
            path = Path(item["path"])
            caps = item.get("capabilities", {})
            sessions = [
                Session(
                    session_id=s.get("session_id", ""),
                    title=s.get("title", ""),
                    launched=s.get("launched", False),
                )
                for s in item.get("sessions", [])
            ]
            projects.append(
                Project(
                    path=path,
                    capabilities=Capabilities(
                        git=caps.get("git", False),
                        launchable=caps.get("launchable", False),
                        node_dev=caps.get("node_dev", False),
                    ),
                    sessions=sessions,
                )
            )
        except (KeyError, TypeError):
            continue
    return projects


def save_registry(projects: list[Project]) -> None:
    """Write the registry to disk, ensuring the config dir exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "path": str(p.path),
            "capabilities": {
                "git": p.capabilities.git,
                "launchable": p.capabilities.launchable,
                "node_dev": p.capabilities.node_dev,
            },
            "sessions": [
                {
                    "session_id": s.session_id,
                    "title": s.title,
                    "launched": s.launched,
                }
                for s in p.sessions
            ],
        }
        for p in projects
    ]
    REGISTRY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def find_project(path: Path) -> Project | None:
    """Return the registered project for *path*, or None."""
    resolved = path.expanduser().resolve()
    for p in load_registry():
        if p.path == resolved:
            return p
    return None


def add_project(path: Path) -> None:
    """Add *path* (detecting capabilities) to the registry, dedup by path."""
    projects = load_registry()
    resolved = path.expanduser().resolve()
    for p in projects:
        if p.path == resolved:
            return
    projects.append(Project(path=resolved, capabilities=detect_capabilities(resolved)))
    save_registry(projects)


def remove_project(path: Path) -> None:
    """Remove *path* from the registry."""
    projects = load_registry()
    resolved = path.expanduser().resolve()
    save_registry([p for p in projects if p.path != resolved])


def refresh_capabilities() -> None:
    """Re-run capability detection on every registered project."""
    projects = load_registry()
    for p in projects:
        p.capabilities = detect_capabilities(p.path)
    save_registry(projects)