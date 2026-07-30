#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
andaime.updater — Auto-update for Python-style SISTEMAS deployments.

Layout::

    <install_root>/
    ├── python/                          ← embedded CPython + deps
    │   └── Lib/site-packages/andaime/   ← shared chassis
    ├── apps/<module>/                   ← app code (e.g. apps/rac/)
    ├── data/                            ← user data (NEVER touched by updates)
    └── VERSION                          ← "1.2.3\\nruntime: <hash>"

Update flow::

    1. UpdateCheckWorker (background thread) queries GitHub Releases API.
    2. Compares app version + runtime hash.
    3. Downloads ``update.zip`` (small) or ``payload.zip`` (full python/).
    4. Extracts to ``_update_staging/``.
    5. User clicks Restart → ``restart_app()``.
    6. New process calls ``apply_pending_update()``.
    7. Directories swapped atomically (``.old`` suffix for rollback).
    8. New version launched with ``--post-update`` monitoring.
    9. On success signature → cleanup ``.old`` dirs.
   10. On failure/timeout → rollback ``.old`` dirs, relaunch old version.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

from andaime.error_handler import ErrorHandler, ErrorLevel

# ============================================================================
# Constants
# ============================================================================

STAGING_DIR = "_update_staging"
VERSION_FILE = "VERSION"
UPDATE_TAG = ".update_tag"
POST_UPDATE_ENV = "ANDAIME_POST_UPDATE"
SUCCESS_FILE = "success"
ROLLOUT_TIMEOUT = 30  # seconds to wait for launch signature

ANDAIME_REPO = "januvary/andaime"

# ============================================================================
# Install-root detection
# ============================================================================


def get_install_root() -> Path:
    """Return the SISTEMAS install root.

    Detects the ``<install_root>/python/pythonw.exe`` layout used by both
    standalone single-app builds and the SISTEMAS multi-app dist.

    Falls back to ``__main__`` file resolution for dev mode.
    """
    exe = Path(sys.executable).resolve()

    # SISTEMAS Python-style: <install_root>/python/pythonw.exe
    if exe.parent.name == "python":
        candidate = exe.parent.parent
        if (candidate / "apps").is_dir() or (candidate / VERSION_FILE).exists():
            return candidate

    # Frozen (legacy PyInstaller): <install_root>/<App>.exe
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent

    # Dev mode: derive from __main__ location
    try:
        import __main__

        main_file = getattr(__main__, "__file__", None)
        if main_file is not None:
            p = Path(main_file).resolve()
            # apps/<module>/__main__.py → install root is 3 levels up
            if p.parent.parent.name == "apps":
                return p.parent.parent.parent
            return p.parent
    except (ImportError, AttributeError):
        pass

    return Path.cwd()


def staging_path() -> Path:
    """Directory where update zips are extracted before applying."""
    return get_install_root() / STAGING_DIR


def _get_app_module() -> str:
    """Return the running app's module name (e.g. ``'rac'``).

    When launched as ``pythonw.exe -m rac``, ``__main__.__package__`` is
    ``'rac'``.
    """
    try:
        import __main__

        pkg = getattr(__main__, "__package__", None)
        if pkg:
            return pkg
    except (ImportError, AttributeError):
        pass
    return ""


# ============================================================================
# VERSION file I/O
# ============================================================================


def _read_version_file(path: Path) -> tuple[str, str]:
    """Parse a VERSION file, returning ``(app_version, runtime_hash)``.

    Expected format::

        1.2.3
        runtime: a1b2c3d4

    Lines starting with ``#`` are ignored.  If the file is absent,
    ``("0.0.0", "")`` is returned.
    """
    app_version = "0.0.0"
    runtime_hash = ""
    if path.exists():
        try:
            for line in path.read_text(encoding="utf-8").strip().splitlines():
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if line.lower().startswith("runtime:"):
                    runtime_hash = line.split(":", 1)[1].strip()
                elif "." in line:
                    app_version = line.lstrip("v")
        except OSError:
            pass
    return app_version, runtime_hash


def get_local_version() -> tuple[str, str]:
    """Return ``(app_version, runtime_hash)`` from the local VERSION file."""
    return _read_version_file(get_install_root() / VERSION_FILE)


# ============================================================================
# Version comparison
# ============================================================================


def _parse_version(tag: str) -> tuple[int, ...]:
    parts = tag.lstrip("v").split(".")
    result: list[int] = []
    for p in parts:
        try:
            result.append(int(p))
        except ValueError:
            break
    while len(result) < 3:
        result.append(0)
    return tuple(result)


def is_newer(remote_tag: str, current_version: str) -> bool:
    try:
        return _parse_version(remote_tag) > _parse_version(current_version)
    except (ValueError, IndexError):
        return False


# ============================================================================
# Zip safety + checksums
# ============================================================================


def _verify_zip_paths(zf: zipfile.ZipFile) -> None:
    """Reject absolute paths and ``..`` traversal in zip entries."""
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError(f"Unsafe path in zip: {info.filename}")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ============================================================================
# Shared data root (network / local)
# ============================================================================

MIGRATION_MARKER = ".local_install_source"


def _is_path_reachable(path: Path) -> bool:
    """Quick reachability test: can we list the directory?"""
    try:
        list(path.iterdir())
        return True
    except (OSError, PermissionError):
        return False


def get_shared_root() -> Path | None:
    """Return the shared data root, or ``None`` for standalone.

    Priority:

    1. ``SISTEMAS_DATA_ROOT`` env var (set by the smart launcher).
    2. ``.local_install_source`` marker file written during initial install.
    3. ``None`` (standalone / dev).
    """
    env_root = os.environ.get("SISTEMAS_DATA_ROOT")
    if env_root:
        return Path(env_root)

    marker = get_install_root() / MIGRATION_MARKER
    if marker.exists():
        try:
            return Path(marker.read_text(encoding="utf-8").strip())
        except Exception:
            return None
    return None


def resolve_data_root(app_folder: str) -> Path:
    """Resolve the data root directory.

    * If a network pointer exists **and** is reachable → ``<pointer>/<app_folder>``.
    * If a pointer exists but is unreachable → warn, fall back to install root.
    * No pointer → install root (standalone, silent).
    """
    shared = get_shared_root()

    if shared is not None:
        network_data = shared / app_folder
        if _is_path_reachable(shared):
            return network_data
        # Pointer exists but unreachable — warn and fall back
        ErrorHandler.log(
            f"Network data root unreachable: {shared}. "
            f"Using local data.",
            level=ErrorLevel.WARNING,
            context="Updater",
        )

    return get_install_root()


# ============================================================================
# Directory swap primitives
# ============================================================================


def _swap_directory(current: Path, new: Path) -> list[tuple[Path, Path]]:
    """Atomically swap *new* into *current*'s location.

    Renames ``current`` → ``current.old`` (for rollback), then moves
    *new* → *current*.  Returns ``[(old_path, final_path)]`` pairs.
    """
    swaps: list[tuple[Path, Path]] = []
    if current.exists() or current.is_symlink():
        old = current.with_name(current.name + ".old")
        with contextlib.suppress(Exception):
            if old.exists():
                shutil.rmtree(old)
        os.rename(current, old)
        swaps.append((old, current))
    current.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(new), str(current))
    return swaps


def _rollback(swaps: list[tuple[Path, Path]]) -> None:
    """Revert all directory swaps in reverse order."""
    for old, current in reversed(swaps):
        with contextlib.suppress(Exception):
            if current.exists():
                shutil.rmtree(current)
            if old.exists():
                os.rename(old, current)


def _cleanup_old_dirs(root: Path) -> None:
    """Remove ``*.old`` directories left by a previous successful update."""
    search_dirs = [
        root / "apps",
        root / "python" / "Lib" / "site-packages",
        root / "python",
    ]
    for d in search_dirs:
        if d.is_dir():
            for item in d.iterdir():
                if item.name.endswith(".old"):
                    with contextlib.suppress(Exception):
                        shutil.rmtree(item)
    # Also clean .old files (legacy frozen artifacts)
    for stale in root.glob("*.old"):
        with contextlib.suppress(Exception):
            stale.unlink()


# ============================================================================
# Install format detection
# ============================================================================


def _detect_install_format(root: Path) -> str:
    """Detect the deployment format of an installation.

    Returns one of:

    * ``"launcher"``   - SISTEMAS Python-style: ``apps/`` + ``python/`` dirs.
    * ``"pyinstaller"`` - PyInstaller one-dir: ``_internal/`` dir.
    * ``"unknown"``    - Cannot determine format.
    """
    if not root.exists():
        return "unknown"

    # Launcher/SISTEMAS layout
    if (root / "apps").is_dir() and (root / "python").is_dir():
        return "launcher"

    # PyInstaller one-dir layout
    if (root / "_internal").is_dir():
        return "pyinstaller"

    return "unknown"


def _format_error_message(current_format: str, staged_format: str) -> str:
    return (
        f"Formato de instalação incompatível.\n\n"
        f"Atual: {current_format}\n"
        f"Atualização: {staged_format}\n\n"
        f"Baixe a versão correta do aplicativo e instale novamente."
    )


# ============================================================================
# Update application
# ============================================================================


def apply_pending_update() -> bool:
    """Apply a staged update if one is waiting.

    Called at the very start of ``main()`` **before** ``andaime.App`` is
    constructed.  If a staging directory with a valid ``.update_tag`` exists,
    the directories are swapped and the new version is launched with
    post-update monitoring.

    Returns ``True`` if an update was applied (the current process will be
    replaced and should not continue initialisation).
    """
    root = get_install_root()
    staging = staging_path()

    # Always clean up stale rollback artifacts first.
    _cleanup_old_dirs(root)

    if not staging.is_dir():
        return False

    tag_file = staging / UPDATE_TAG
    if not tag_file.exists():
        with contextlib.suppress(Exception):
            shutil.rmtree(staging)
        return False

    app_module = _get_app_module()
    if not app_module:
        ErrorHandler.log(
            "Cannot determine app module; skipping pending update.",
            level=ErrorLevel.ERROR,
            context="Updater",
        )
        return False

    tag = tag_file.read_text(encoding="utf-8").strip()
    ErrorHandler.log(
        f"Applying pending update {tag}...",
        level=ErrorLevel.INFO,
        context="Updater",
    )

    # Detect installation format mismatch to avoid silently mixing
    # launcher-style and PyInstaller-style deployments.
    current_format = _detect_install_format(root)
    staged_format = _detect_install_format(staging)
    if (
        current_format != "unknown"
        and staged_format != "unknown"
        and current_format != staged_format
    ):
        ErrorHandler.log(
            f"Installation format mismatch: current={current_format}, "
            f"staged={staged_format}. Aborting update.",
            level=ErrorLevel.ERROR,
            context="Updater",
        )
        with contextlib.suppress(Exception):
            shutil.rmtree(staging)
        _show_update_error(
            Exception(_format_error_message(current_format, staged_format))
        )
        return False

    swaps: list[tuple[Path, Path]] = []

    try:
        # 1. Swap apps/<module>/
        new_app = staging / "apps" / app_module
        if new_app.is_dir():
            swaps.extend(
                _swap_directory(root / "apps" / app_module, new_app)
            )

        # 2. Swap andaime/ (in site-packages)
        new_andaime = staging / "andaime"
        if new_andaime.is_dir():
            sp = root / "python" / "Lib" / "site-packages" / "andaime"
            swaps.extend(_swap_directory(sp, new_andaime))

        # 3. Swap python/ (full payload — runtime hash changed)
        new_python = staging / "python"
        if new_python.is_dir():
            swaps.extend(_swap_directory(root / "python", new_python))

        # 4. Update VERSION
        new_version = staging / VERSION_FILE
        if new_version.exists():
            shutil.copy2(str(new_version), str(root / VERSION_FILE))

        # 5. Clean up staging
        shutil.rmtree(staging, ignore_errors=True)

        ErrorHandler.log(
            f"Update {tag} applied. Launching new version...",
            level=ErrorLevel.INFO,
            context="Updater",
        )

        # 6. Launch with monitoring (monopolises this process)
        _launch_with_monitoring(app_module, swaps)
        return True  # unreachable — _launch_with_monitoring exits

    except Exception as e:
        ErrorHandler.log(
            f"Update application failed: {e}. Rolling back...",
            level=ErrorLevel.ERROR,
            context="Updater",
        )
        _rollback(swaps)
        with contextlib.suppress(Exception):
            shutil.rmtree(staging)
        _show_update_error(e)
        return False


def _get_python_exe() -> Path:
    """Return the Python executable for (re)launching."""
    root = get_install_root()
    candidates = [
        root / "python" / "pythonw.exe",
        root / "python" / "python.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path(sys.executable)


def _launch_with_monitoring(
    app_module: str, swaps: list[tuple[Path, Path]]
) -> None:
    """Launch the updated app and monitor for a success signature.

    On success → exit (the new process takes over).
    On failure → rollback and relaunch the old version.
    """
    python_exe = _get_python_exe()
    temp_dir = Path(tempfile.mkdtemp(prefix="andaime_update_"))

    env = os.environ.copy()
    env[POST_UPDATE_ENV] = str(temp_dir)

    proc = subprocess.Popen(
        [str(python_exe), "-m", app_module],
        start_new_session=True,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    success_marker = temp_dir / SUCCESS_FILE
    deadline = time.monotonic() + ROLLOUT_TIMEOUT

    while time.monotonic() < deadline:
        if success_marker.exists():
            # New version initialised successfully — we're done.
            shutil.rmtree(temp_dir, ignore_errors=True)
            os._exit(0)

        rc = proc.poll()
        if rc is not None:
            # Process exited before writing success marker.
            stderr = b""
            with contextlib.suppress(Exception):
                stderr = proc.stderr.read() if proc.stderr else b""
            break

        time.sleep(0.5)
    else:
        # Timeout
        rc = -1
        stderr = b"timeout"

    # --- Failure path ---
    ErrorHandler.log(
        f"Post-update launch failed (rc={rc}). "
        f"Rolling back to previous version.",
        level=ErrorLevel.ERROR,
        context="Updater",
    )

    _rollback(swaps)

    with contextlib.suppress(Exception):
        shutil.rmtree(temp_dir)

    # Relaunch the old (restored) version
    subprocess.Popen(
        [str(python_exe), "-m", app_module],
        start_new_session=True,
    )
    os._exit(1)


def signal_post_update_success() -> None:
    """Write the success marker if running in post-update mode.

    Called by ``andaime.App.__init__`` after database + config are confirmed
    working.
    """
    temp_dir = os.environ.get(POST_UPDATE_ENV)
    if not temp_dir:
        return
    marker = Path(temp_dir) / SUCCESS_FILE
    with contextlib.suppress(Exception):
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("ok", encoding="utf-8")


# ============================================================================
# Restart
# ============================================================================


def restart_app() -> None:
    """Restart the current app (used after user clicks "Restart" in dialog)."""
    app_module = _get_app_module()
    python_exe = _get_python_exe()

    if app_module:
        subprocess.Popen(
            [str(python_exe), "-m", app_module],
            start_new_session=True,
        )
    else:
        subprocess.Popen([sys.executable], start_new_session=True)
    os._exit(0)


# ============================================================================
# Error UI
# ============================================================================


def _show_update_error(error: Exception) -> None:
    msg = (
        "Não foi possível aplicar a atualização.\n"
        "O aplicativo continuará funcionando normalmente.\n\n"
        f"Detalhes: {error}"
    )
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0, msg, "SISTEMAS — Atualização", 0x40
            )
            return
        except Exception:
            pass
    ErrorHandler.log(f"[Updater] {msg}", level=ErrorLevel.ERROR, context="Updater")


# ============================================================================
# Background update checker
# ============================================================================


class UpdateCheckWorker(QThread):
    """Background thread that checks GitHub for a newer release.

    Each app checks its own repo (``januvary/RAC``, ``januvary/Emissor``,
    …) via ``/releases/latest``.  In the shared SISTEMAS dist, all apps
    check ``januvary/andaime`` instead.

    Signals
    -------
    update_available(str, str) : ``(tag, release_notes)``
    update_ready(str)          : ``(tag,)`` — download complete, awaiting restart
    update_failed(str)         : ``(error_message,)``
    no_update()                — already up-to-date
    """

    update_available = Signal(str, str)
    update_ready = Signal(str)
    update_failed = Signal(str)
    no_update = Signal()

    def __init__(
        self,
        repo: str,
        current_version: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._current_version = current_version

    def run(self) -> None:
        try:
            # Skip if an update is already staged.
            staging = staging_path()
            if staging.is_dir() and (staging / UPDATE_TAG).exists():
                return

            import urllib.error
            import urllib.request
            import ssl

            headers = {
                "User-Agent": "SISTEMAS-Updater",
                "Accept": "application/vnd.github+json",
            }
            api_url = (
                f"https://api.github.com/repos/{self._repo}/releases/latest"
            )
            req = urllib.request.Request(api_url, headers=headers)

            context = ssl.create_default_context()
            try:
                with urllib.request.urlopen(
                    req, timeout=60, context=context
                ) as resp:
                    release = json.loads(resp.read())
            except urllib.error.URLError:
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(
                    req, timeout=60, context=context
                ) as resp:
                    release = json.loads(resp.read())

            tag = release.get("tag_name", "")
            if not tag or not is_newer(tag, self._current_version):
                self.no_update.emit()
                return

            notes = release.get("body", "") or f"Release {tag}"

            # Parse runtime hash from release notes.
            remote_runtime = ""
            for line in notes.splitlines():
                low = line.strip().lower()
                if low.startswith("runtime:"):
                    remote_runtime = low.split(":", 1)[1].strip()
                    break

            # Decide which asset to download.
            _, local_runtime = get_local_version()
            need_full_payload = bool(
                remote_runtime and remote_runtime != local_runtime
            ) or not remote_runtime

            asset_url = None
            expected_digest = None

            for asset in release.get("assets", []):
                name = asset.get("name", "").lower()
                if need_full_payload and "payload" in name:
                    asset_url = asset.get("browser_download_url")
                    expected_digest = asset.get("digest")
                    break
                if not need_full_payload and "update" in name:
                    asset_url = asset.get("browser_download_url")
                    expected_digest = asset.get("digest")
                    break

            # Fallback: any .zip asset.
            if not asset_url:
                for asset in release.get("assets", []):
                    if asset.get("name", "").endswith(".zip"):
                        asset_url = asset.get("browser_download_url")
                        expected_digest = asset.get("digest")
                        break

            if not asset_url:
                self.update_failed.emit("No downloadable asset found.")
                return

            self.update_available.emit(tag, notes)

            # ---- Download ----
            tmp = tempfile.mkdtemp(prefix="andaime_update_")
            try:
                zip_path = Path(tmp) / "update.zip"
                zip_req = urllib.request.Request(asset_url, headers=headers)
                with urllib.request.urlopen(
                    zip_req, timeout=120, context=context
                ) as resp:
                    with open(zip_path, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)

                # Checksum verification.
                if expected_digest:
                    algo, _, expected_hash = expected_digest.partition(":")
                    if algo == "sha256":
                        actual = _sha256_file(zip_path)
                        if actual != expected_hash:
                            self.update_failed.emit(
                                "Checksum verification failed."
                            )
                            return

                # ---- Extract to staging ----
                with zipfile.ZipFile(zip_path, "r") as zf:
                    _verify_zip_paths(zf)
                    staging = staging_path()
                    if staging.is_dir():
                        shutil.rmtree(staging)
                    zf.extractall(staging)

                # Handle a single top-level wrapper directory in the zip.
                top_level = [
                    p
                    for p in staging.iterdir()
                    if p.name not in (".update_tag",)
                ]
                if (
                    len(top_level) == 1
                    and top_level[0].is_dir()
                    and not (top_level[0] / VERSION_FILE).exists()
                    and not (top_level[0] / "apps").is_dir()
                ):
                    wrapper = top_level[0]
                    real_root = wrapper
                    # Check if wrapper contains the expected structure.
                    if (wrapper / "apps").is_dir() or (
                        wrapper / "python"
                    ).is_dir():
                        for item in wrapper.iterdir():
                            dest = staging / item.name
                            if dest.exists():
                                if item.is_dir():
                                    shutil.rmtree(dest)
                                else:
                                    dest.unlink()
                            shutil.move(str(item), str(dest))
                        shutil.rmtree(wrapper)

                # Detect cross-format updates early to prevent broken installs.
                current_format = _detect_install_format(get_install_root())
                staged_format = _detect_install_format(staging)
                if (
                    current_format != "unknown"
                    and staged_format != "unknown"
                    and current_format != staged_format
                ):
                    raise RuntimeError(
                        _format_error_message(current_format, staged_format)
                    )

                (staging / UPDATE_TAG).write_text(tag, encoding="utf-8")

                ErrorHandler.log(
                    f"Update {tag} staged and ready for restart.",
                    level=ErrorLevel.INFO,
                    context="Updater",
                )
                self.update_ready.emit(tag)
            finally:
                with contextlib.suppress(Exception):
                    shutil.rmtree(tmp)

        except Exception as e:
            self.update_failed.emit(str(e))
