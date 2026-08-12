"""Project registry — curated list of projects with detected capabilities.

Stores an explicit list of projects (added by path) in
``~/.config/andaime/projects.json`` so the Dev Launcher is a registry the user
curates, rather than a scanner that guesses from the filesystem.

Each project records its path plus detected capabilities. Detection is run at
add-time and re-run on refresh:
  - ``git``        -> has a ``.git`` (Commit button, diff-stat, source view)
  - ``launchable`` -> has a ``main.py`` (Launch button)
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
    "data", ".codebase-memory", "test", "tests",
}


@dataclass
class Capabilities:
    git: bool = False
    launchable: bool = False

    @property
    def label(self) -> str:
        tags = []
        if self.git:
            tags.append("git")
        if self.launchable:
            tags.append("launch")
        return ", ".join(tags) if tags else "static"


@dataclass
class Project:
    path: Path
    capabilities: Capabilities = field(default_factory=Capabilities)

    @property
    def name(self) -> str:
        return self.path.name


def detect_capabilities(path: Path) -> Capabilities:
    """Detect what functions *path* supports."""
    return Capabilities(
        git=(path / ".git").exists(),
        launchable=(path / "main.py").is_file(),
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
            projects.append(
                Project(
                    path=path,
                    capabilities=Capabilities(
                        git=caps.get("git", False),
                        launchable=caps.get("launchable", False),
                    ),
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
            },
        }
        for p in projects
    ]
    REGISTRY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


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