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
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
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


def get_shared_root() -> Path:
    """Return the directory that contains the running exe (data root).

    When launched by the SISTEMAS launcher, ``SISTEMAS_DATA_ROOT`` is
    set to the exe's directory so that data lives next to the exe
    regardless of where the Python runtime is installed.
    Falls back to ``Path.cwd()`` for dev mode.
    """
    data_root = os.environ.get("SISTEMAS_DATA_ROOT")
    if data_root:
        return Path(data_root)
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
# VERSION file I/O (hash-based manifest)
# ============================================================================


def parse_manifest_text(text: str) -> dict[str, str]:
    """Parse a VERSION manifest from raw text.

    Format::

        26.07.31-2202
        runtime: d4c3b2a1
        rac: f8e7d6c5
        andaime: a1b2c3d4
    """
    manifest: dict[str, str] = {"datestamp": "", "runtime": ""}
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            manifest[key.strip()] = value.strip()
        else:
            manifest["datestamp"] = line
    return manifest


def read_version_manifest(path: Path | None = None) -> dict[str, str]:
    """Return the manifest from a VERSION file on disk."""
    if path is None:
        path = get_install_root() / VERSION_FILE
    if path.exists():
        try:
            return parse_manifest_text(path.read_text(encoding="utf-8"))
        except OSError:
            pass
    return {"datestamp": "", "runtime": ""}


def get_local_manifest() -> dict[str, str]:
    """Return the local VERSION manifest."""
    return read_version_manifest()


def get_local_hash(module: str) -> str:
    """Return the local hash for a given module, or empty string."""
    return get_local_manifest().get(module, "")


def get_local_runtime_hash() -> str:
    """Return the local runtime hash, or empty string."""
    return get_local_manifest().get("runtime", "")


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
    # Also clean .old files (legacy frozen artifacts) and any top-level
    # .old directories (e.g. python.old left by a payload swap).
    for stale in root.glob("*.old"):
        with contextlib.suppress(Exception):
            if stale.is_dir():
                shutil.rmtree(stale)
            else:
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


def _acquire_lock(lock_path: Path) -> int | None:
    """Exclusively acquire a lockfile, or return ``None`` if held.

    Uses ``O_CREAT | O_EXCL`` so only one process can create it.  Stale
    lockfiles (left by a killed process) are broken after a grace period.
    """
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except FileExistsError:
        try:
            age = time.time() - lock_path.stat().st_mtime
        except OSError:
            return None
        if age > 60:
            try:
                lock_path.unlink()
            except OSError:
                return None
            return _acquire_lock(lock_path)
        return None
    except OSError:
        return None


def _release_lock(lock_path: Path, lock_handle: int | None) -> None:
    if lock_handle is not None:
        with contextlib.suppress(OSError):
            os.close(lock_handle)
    with contextlib.suppress(OSError):
        lock_path.unlink()


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

    # Always clean up stale rollback artifacts first.
    _cleanup_old_dirs(root)

    if not staging_path().is_dir():
        return False

    # Guard against two apps applying to the shared install concurrently.
    # Use an exclusive lockfile; if another process holds it, skip and let
    # that process apply the update on its own relaunch.
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "update.lock"
    lock_handle = _acquire_lock(lock_path)
    if lock_handle is None:
        return False

    try:
        return _apply_pending_update_locked()
    finally:
        _release_lock(lock_path, lock_handle)


def _apply_pending_update_locked() -> bool:
    """Apply a staged update. Caller must hold the update lock."""
    root = get_install_root()
    staging = staging_path()

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
    old_version_content: str | None = None

    try:
        # 1. Swap all apps found in staging (covers multi-app portable installs)
        new_apps = staging / "apps"
        if new_apps.is_dir():
            for app_dir in new_apps.iterdir():
                if app_dir.is_dir():
                    target = root / "apps" / app_dir.name
                    swaps.extend(_swap_directory(target, app_dir))

        # 2. Swap andaime/ (in site-packages)
        new_andaime = staging / "andaime"
        if new_andaime.is_dir():
            sp = root / "python" / "Lib" / "site-packages" / "andaime"
            swaps.extend(_swap_directory(sp, new_andaime))

        # 3. Swap python/ (full payload — runtime hash changed)
        new_python = staging / "python"
        if new_python.is_dir():
            swaps.extend(_swap_directory(root / "python", new_python))

        # 4. Update VERSION (save old for rollback)
        version_file = root / VERSION_FILE
        new_version = staging / VERSION_FILE
        if new_version.exists():
            if version_file.exists():
                old_version_content = version_file.read_text(encoding="utf-8")
            shutil.copy2(str(new_version), str(version_file))

        # 5. Clean up staging
        shutil.rmtree(staging, ignore_errors=True)

        # Stale error log from a previous failed attempt — the update
        # applied now, so remove it to avoid confusion later.
        with contextlib.suppress(Exception):
            (root / "update_error.log").unlink(missing_ok=True)

        ErrorHandler.log(
            f"Update {tag} applied. Launching new version...",
            level=ErrorLevel.INFO,
            context="Updater",
        )

        # 6. Launch with monitoring (monopolises this process)
        # Small delay to let Windows release file handles from the swap
        # before starting the new process. Prevents [WinError 6] on
        # slower machines where handle release takes longer.
        time.sleep(0.5)
        _launch_with_monitoring(app_module, swaps, old_version_content)
        return True  # unreachable — _launch_with_monitoring exits

    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        ErrorHandler.log(
            f"Update application failed: {e}. Rolling back...\n{tb}",
            level=ErrorLevel.ERROR,
            context="Updater",
        )
        # Persist the traceback where it's easy to find and survives
        # relaunches, regardless of stdout redirection.
        with contextlib.suppress(Exception):
            (root / "update_error.log").write_text(
                f"tag: {tag}\nswaps so far: {swaps}\n\n{tb}",
                encoding="utf-8",
            )
        _rollback(swaps)

        # Restore old VERSION so hashes match the restored code
        if old_version_content is not None:
            with contextlib.suppress(Exception):
                (root / VERSION_FILE).write_text(
                    old_version_content, encoding="utf-8"
                )

        with contextlib.suppress(Exception):
            shutil.rmtree(staging)
        _show_update_error(e)
        return False


def _get_python_exe() -> Path:
    """Return the Python executable for (re)launching."""
    root = get_install_root()
    candidates = [
        root / "python" / "python.exe",
        root / "python" / "pythonw.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path(sys.executable)


def _launch_with_monitoring(
    app_module: str,
    swaps: list[tuple[Path, Path]],
    old_version_content: str | None = None,
) -> None:
    """Launch the updated app and monitor for a success signature.

    On success → exit (the new process takes over).
    On failure → rollback and relaunch the old version.
    """
    python_exe = _get_python_exe()
    root = get_install_root()
    temp_dir = Path(tempfile.mkdtemp(prefix="andaime_update_"))

    env = os.environ.copy()
    env[POST_UPDATE_ENV] = str(temp_dir)

    for attempt in range(2):
        try:
            proc = subprocess.Popen(
                [str(python_exe), "-m", app_module],
                start_new_session=True,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            break
        except OSError:
            if attempt == 0:
                time.sleep(0.5)
            else:
                raise

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
    stderr_text = ""
    with contextlib.suppress(Exception):
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

    ErrorHandler.log(
        f"Post-update launch failed (rc={rc}, stderr={stderr_text}). "
        f"Rolling back to previous version.",
        level=ErrorLevel.ERROR,
        context="Updater",
    )
    with contextlib.suppress(Exception):
        (root / "update_error.log").write_text(
            f"post-update launch failed: rc={rc}\n\nstderr:\n{stderr_text}",
            encoding="utf-8",
        )

    _rollback(swaps)

    # Restore old VERSION so hashes match the restored code
    if old_version_content is not None:
        with contextlib.suppress(Exception):
            (root / VERSION_FILE).write_text(old_version_content, encoding="utf-8")

    with contextlib.suppress(Exception):
        shutil.rmtree(temp_dir)

    # Relaunch the old (restored) version
    subprocess.Popen(
        [str(python_exe), "-m", app_module],
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
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

    _NO_INHERIT = dict(
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if app_module:
        subprocess.Popen(
            [str(python_exe), "-m", app_module],
            start_new_session=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **_NO_INHERIT,
        )
    else:
        subprocess.Popen(
            [sys.executable],
            start_new_session=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **_NO_INHERIT,
        )
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
    """Background thread that checks januvary/andaime for updates.

    Uses hash-based comparison: downloads payload.zip when the runtime
    hash differs, and app-update.zip when the local app hash differs.

    Signals
    -------
    update_available(str, str) : ``(tag, release_notes)``
    update_ready(str)          : ``(tag,)`` — download complete, awaiting restart
    update_failed(str)         : ``(error_message,)``
    no_update()                — all hashes match, already up to date
    """

    update_available = Signal(str, str)
    update_ready = Signal(str)
    update_failed = Signal(str)
    no_update = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

    def run(self) -> None:
        try:
            # Skip if an update is already staged.
            staging = staging_path()
            if staging.is_dir() and (staging / UPDATE_TAG).exists():
                return

            module = _get_app_module()
            if not module:
                self.update_failed.emit("Cannot determine app module.")
                return

            local_manifest = get_local_manifest()
            local_app_hash = local_manifest.get(module, "")
            local_runtime = local_manifest.get("runtime", "")

            headers = {
                "User-Agent": "SISTEMAS-Updater",
                "Accept": "application/vnd.github+json",
            }
            api_url = "https://api.github.com/repos/januvary/andaime/releases/latest"
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
            if not tag:
                self.no_update.emit()
                return

            notes = release.get("body", "") or ""

            # Read manifest from VERSION asset.
            remote_manifest: dict[str, str] = {}
            for asset in release.get("assets", []):
                if asset.get("name", "") == VERSION_FILE:
                    asset_url = asset.get("browser_download_url")
                    if asset_url:
                        try:
                            req2 = urllib.request.Request(asset_url, headers=headers)
                            with urllib.request.urlopen(
                                req2, timeout=30, context=context
                            ) as resp2:
                                remote_manifest = parse_manifest_text(
                                    resp2.read().decode("utf-8")
                                )
                        except Exception:
                            pass
                    break

            remote_app_hash = remote_manifest.get(module, "")
            remote_runtime = remote_manifest.get("runtime", "")
            remote_andaime = remote_manifest.get("andaime", "")

            local_andaime = local_manifest.get("andaime", "")

            # Decide which asset to download.
            need_payload = bool(
                remote_runtime and remote_runtime != local_runtime
            ) or not remote_runtime
            need_app_update = (
                need_payload
                or bool(remote_app_hash and remote_app_hash != local_app_hash)
                or not remote_app_hash
                or bool(remote_andaime and remote_andaime != local_andaime)
                or not remote_andaime
            )

            if not need_payload and not need_app_update:
                self.no_update.emit()
                return

            self.update_available.emit(tag, notes)

            # ---- Download assets ----
            tmp = tempfile.mkdtemp(prefix="andaime_update_")
            lock_handle = None
            try:
                staging = staging_path()

                # Guard against concurrent staging (another app's worker,
                # or the launcher's staging mutex on the C side). If the
                # lock is held, skip — that process's staging gets applied
                # on the next launch.
                lock_handle = _acquire_lock(staging.parent / "update.lock")
                if lock_handle is None:
                    self.no_update.emit()
                    return
                lock_path = staging.parent / "update.lock"

                if staging.is_dir():
                    shutil.rmtree(staging)

                for asset in release.get("assets", []):
                    name = asset.get("name", "")
                    asset_url = asset.get("browser_download_url")
                    if not asset_url:
                        continue

                    if need_payload and "payload" in name and name.endswith(".zip"):
                        self._download_and_stage(
                            asset_url, tmp, "payload.zip", headers, context,
                            keepalive=lock_path,
                        )
                        need_payload = False
                    elif need_app_update and "app-update" in name and name.endswith(".zip"):
                        self._download_and_stage(
                            asset_url, tmp, "app-update.zip", headers, context,
                            keepalive=lock_path,
                        )
                        need_app_update = False

                if not staging.is_dir():
                    self.update_failed.emit("No matching assets found in release.")
                    return

                (staging / UPDATE_TAG).write_text(tag, encoding="utf-8")
                self.update_ready.emit(tag)
            finally:
                if lock_handle is not None:
                    _release_lock(staging.parent / "update.lock", lock_handle)
                with contextlib.suppress(Exception):
                    shutil.rmtree(tmp)

        except Exception as e:
            self.update_failed.emit(str(e))

    def _download_and_stage(
        self,
        url: str,
        tmp: str,
        filename: str,
        headers: dict,
        context: ssl.SSLContext,
        keepalive: Path | None = None,
    ) -> None:
        zip_path = Path(tmp) / filename
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=120, context=context) as resp:
            with zip_path.open("wb") as f:
                n = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    n += 1
                    # Refresh the staging lock's mtime every ~4MB so slow
                    # downloads aren't mistaken for a stale (dead) holder.
                    if keepalive is not None and n % 64 == 0:
                        with contextlib.suppress(OSError):
                            keepalive.touch()

        staging = staging_path()
        staging.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            _verify_zip_paths(zf)
            zf.extractall(staging)
