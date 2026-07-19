#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import contextlib
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

from andaime.error_handler import ErrorHandler, ErrorLevel

STAGING_DIR = "_update_staging"
OLD_INTERNAL_DIR = "_internal_old"


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


def staging_path() -> Path:
    return _app_dir() / STAGING_DIR


def _parse_version(tag: str) -> tuple:
    parts = tag.lstrip("v").split(".")
    result = []
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


def _verify_zip_paths(zf: zipfile.ZipFile) -> None:
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


def _swap_top_level_files(staging: Path, app: Path) -> list[tuple[Path, Path]]:
    """Move top-level launcher files (e.g. RAC.exe) from staging into the app dir.

    The Windows PE subsystem flag (console vs windowed) is compiled into the
    launcher exe at build time, so updates must replace the launcher alongside
    _internal/ — otherwise stale launcher behavior survives. A running exe
    cannot be overwritten on Windows, so the existing file is renamed aside to
    ``<name>.old`` first (renaming a running exe is allowed). Returns
    ``(old_path, final_path)`` pairs for rollback.
    """
    swapped: list[tuple[Path, Path]] = []
    for item in staging.iterdir():
        if item.name in ("_internal", ".update_tag") or not item.is_file():
            continue
        dest = app / item.name
        if dest.exists() or dest.is_symlink():
            old_dest = dest.with_name(dest.name + ".old")
            with contextlib.suppress(FileNotFoundError):
                old_dest.unlink()
            os.rename(dest, old_dest)
            swapped.append((old_dest, dest))
        shutil.move(str(item), str(dest))
    return swapped


def apply_pending_update() -> bool:
    if not getattr(sys, "frozen", False):
        return False

    app = _app_dir()
    old_internal = app / OLD_INTERNAL_DIR

    # Clean up rollback artifacts left by a previous successful swap.
    with contextlib.suppress(Exception):
        if old_internal.is_dir():
            shutil.rmtree(old_internal)
    for stale in app.glob("*.old"):
        with contextlib.suppress(Exception):
            stale.unlink()

    staging = staging_path()
    if not staging.is_dir():
        return False

    staging_internal = staging / "_internal"
    if not staging_internal.is_dir():
        with contextlib.suppress(Exception):
            shutil.rmtree(staging)
        return False

    internal = app / "_internal"

    swapped: list[tuple[Path, Path]] = []
    try:
        swapped = _swap_top_level_files(staging, app)

        os.rename(internal, old_internal)
        os.rename(staging_internal, internal)
        shutil.rmtree(staging, ignore_errors=True)

        subprocess.Popen([sys.executable], start_new_session=True)
        os._exit(0)
    except Exception as e:
        with contextlib.suppress(Exception):
            if old_internal.is_dir() and not internal.is_dir():
                os.rename(old_internal, internal)
        for old_dest, dest in reversed(swapped):
            with contextlib.suppress(Exception):
                if dest.exists():
                    os.remove(dest)
                if old_dest.exists():
                    os.rename(old_dest, dest)
        with contextlib.suppress(Exception):
            shutil.rmtree(staging)
        _show_update_error(e)
        return False


def _show_update_error(error: Exception) -> None:
    msg = (
        f"Não foi possível aplicar a atualização.\n"
        f"O aplicativo continuará funcionando normalmente.\n\n"
        f"Detalhes: {error}"
    )
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, "RAC - Atualização", 0x40)
            return
        except Exception:
            pass
    ErrorHandler.log(f"[Updater] {msg}", level=ErrorLevel.ERROR, context="Updater")


def restart_app() -> None:
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable], start_new_session=True)
    else:
        subprocess.Popen(
            [sys.executable, "-m", "main"],
            start_new_session=True,
        )
    os._exit(0)


# ============================================================================
# Local shadow install (network-shared-folder support)
# ----------------------------------------------------------------------------
# When launched from a network/UNC or read-only location, copy the binaries
# (exe + _internal) to %LOCALAPPDATA% and re-exec from there. The user data
# directory is intentionally left on the shared location so every local copy
# keeps sharing the same database.
# ============================================================================

LOCAL_VENDOR = "Emissor"
MIGRATION_MARKER = ".local_install_source"
_FORCE_MIGRATE_FLAG = ".migrate_local"


def _is_network_location(app_dir: Path) -> bool:
    s = str(app_dir)
    # UNC path (\\server\share\...)
    if s.startswith("\\\\"):
        return True
    # Explicit opt-in sentinel dropped by the user/IT on a mapped drive.
    if (app_dir / _FORCE_MIGRATE_FLAG).exists():
        return True
    # Read-only location (cannot write into the app folder).
    try:
        probe = app_dir / f".write_test_{os.getpid()}"
        probe.write_text("")
        probe.unlink()
    except OSError:
        return True
    return False


def _local_install_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = Path.home() / "AppData" / "Local"
    return Path(base) / LOCAL_VENDOR / Path(sys.executable).parent.name


def ensure_local_install() -> None:
    """If running from a shared/network location, migrate to a local copy.

    Copies the launcher and ``_internal`` into ``%LOCALAPPDATA%`` (leaving the
    shared ``data/`` in place) and re-executes the local copy. Idempotent:
    once migrated, the marker short-circuits.
    """
    if not getattr(sys, "frozen", False):
        return

    current_dir = Path(sys.executable).parent
    if (current_dir / MIGRATION_MARKER).exists():
        return  # already the local copy

    if not _is_network_location(current_dir):
        return

    local_dir = _local_install_dir()
    local_dir.mkdir(parents=True, exist_ok=True)

    # Record where the shared data lives (sibling of the network app folder).
    shared_root = current_dir.parent
    (local_dir / MIGRATION_MARKER).write_text(str(shared_root))

    # Move any data that already lives inside _internal out to the shared root
    # so it isn't trapped/duplicated in the local copy.
    src_internal = current_dir / "_internal"
    orphan_data = src_internal / "data"
    if orphan_data.exists():
        shared_data = shared_root / "data"
        shared_data.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(Exception):
            for item in orphan_data.iterdir():
                dest = shared_data / item.name
                if not dest.exists():
                    shutil.move(str(item), str(dest))
        with contextlib.suppress(Exception):
            orphan_data.rmdir()

    # Copy launcher + _internal (do NOT copy data into the local copy).
    shutil.copy2(sys.executable, local_dir / Path(sys.executable).name)
    dst_internal = local_dir / "_internal"
    if dst_internal.exists():
        shutil.rmtree(dst_internal, ignore_errors=True)
    if src_internal.exists():
        shutil.copytree(src_internal, dst_internal)

    subprocess.Popen([str(local_dir / Path(sys.executable).name)], start_new_session=True)
    os._exit(0)


def get_shared_root() -> Path | None:
    """Returns the shared data root recorded at migration time, else None.

    Pass the result as ``root=`` to ``andaime.App`` so the local copy keeps
    using the network-shared database instead of a per-user one.
    """
    marker = Path(sys.executable).parent / MIGRATION_MARKER
    if not marker.exists():
        return None
    try:
        return Path(marker.read_text().strip())
    except Exception:
        return None


class UpdateCheckWorker(QThread):
    update_available = Signal(str, str)
    update_ready = Signal(str)
    update_failed = Signal(str)
    no_update = Signal()

    def __init__(self, repo: str, current_version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._repo = repo
        self._current_version = current_version

    def run(self) -> None:
        try:
            staging = staging_path()
            tag_file = staging / ".update_tag"
            if staging.is_dir() and tag_file.exists():
                return

            import urllib.request

            import ssl

            headers = {
                "User-Agent": "Andaime-Updater",
                "Accept": "application/vnd.github+json",
            }
            api_url = f"https://api.github.com/repos/{self._repo}/releases/latest"
            req = urllib.request.Request(api_url, headers=headers)

            import urllib.error

            context = ssl.create_default_context()
            try:
                with urllib.request.urlopen(req, timeout=60, context=context) as resp:
                    data = json.loads(resp.read())
            except urllib.error.URLError:
                context = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=60, context=context) as resp:
                    data = json.loads(resp.read())

            _ssl_context = context

            tag = data.get("tag_name", "")
            if not tag or not is_newer(tag, self._current_version):
                self.no_update.emit()
                return

            notes = data.get("body", "") or f"Release {tag}"
            asset_url = None
            expected_digest = None
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.endswith(".zip"):
                    asset_url = asset.get("browser_download_url")
                    expected_digest = asset.get("digest")
                    break

            if not asset_url:
                self.update_failed.emit("No downloadable asset found.")
                return

            self.update_available.emit(tag, notes)

            tmp = tempfile.mkdtemp(prefix="andaime_update_")
            try:
                zip_path = Path(tmp) / "update.zip"
                zip_req = urllib.request.Request(asset_url, headers=headers)
                with urllib.request.urlopen(
                    zip_req, timeout=120, context=_ssl_context
                ) as resp:
                    with open(zip_path, "wb") as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)

                if expected_digest:
                    algo, _, expected_hash = expected_digest.partition(":")
                    if algo == "sha256":
                        actual = _sha256_file(zip_path)
                        if actual != expected_hash:
                            self.update_failed.emit("Checksum verification failed.")
                            return

                with zipfile.ZipFile(zip_path, "r") as zf:
                    _verify_zip_paths(zf)
                    staging = staging_path()
                    if staging.is_dir():
                        shutil.rmtree(staging)
                    zf.extractall(staging)

                if not (staging / "_internal").is_dir():
                    for child in staging.iterdir():
                        if child.is_dir() and (child / "_internal").is_dir():
                            for item in child.iterdir():
                                dest = staging / item.name
                                if dest.exists():
                                    if item.is_dir():
                                        shutil.rmtree(dest)
                                    else:
                                        dest.unlink()
                                if item.is_dir():
                                    shutil.copytree(item, dest)
                                else:
                                    shutil.copy2(item, dest)
                            shutil.rmtree(child)
                            break

                (staging / ".update_tag").write_text(tag)
                self.update_ready.emit(tag)
            finally:
                with contextlib.suppress(Exception):
                    shutil.rmtree(tmp)

        except Exception as e:
            self.update_failed.emit(str(e))
