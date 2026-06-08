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


def apply_pending_update() -> bool:
    if not getattr(sys, "frozen", False):
        return False

    app = _app_dir()
    old_internal = app / OLD_INTERNAL_DIR
    with contextlib.suppress(Exception):
        if old_internal.is_dir():
            shutil.rmtree(old_internal)

    staging = staging_path()
    if not staging.is_dir():
        return False

    staging_internal = staging / "_internal"
    if not staging_internal.is_dir():
        with contextlib.suppress(Exception):
            shutil.rmtree(staging)
        return False

    internal = app / "_internal"

    try:
        if old_internal.is_dir():
            shutil.rmtree(old_internal, ignore_errors=True)

        os.rename(internal, old_internal)
        os.rename(staging_internal, internal)
        shutil.rmtree(staging, ignore_errors=True)

        subprocess.Popen([sys.executable], start_new_session=True)
        os._exit(0)
    except Exception as e:
        if old_internal.is_dir() and not internal.is_dir():
            os.rename(old_internal, internal)
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
    print(f"[Updater] {msg}")


def restart_app() -> None:
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable], start_new_session=True)
    else:
        subprocess.Popen(
            [sys.executable, "-m", "main"],
            start_new_session=True,
        )
    os._exit(0)


class UpdateCheckWorker(QThread):
    update_available = Signal(str, str)
    update_ready = Signal(str)
    update_failed = Signal(str)
    no_update = Signal()

    def __init__(self, repo: str, current_version: str, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._current_version = current_version

    def run(self):
        try:
            staging = staging_path()
            tag_file = staging / ".update_tag"
            if staging.is_dir() and tag_file.exists():
                return

            import urllib.request

            headers = {
                "User-Agent": "Andaime-Updater",
                "Accept": "application/vnd.github+json",
            }
            api_url = f"https://api.github.com/repos/{self._repo}/releases/latest"
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

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
                with urllib.request.urlopen(zip_req, timeout=120) as resp:
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
