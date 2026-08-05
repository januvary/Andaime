"""Utilitários de sistema de arquivos para a interface Qt (andaime)."""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


def reveal_path(path: str) -> None:
    """Abre o explorador de arquivos no arquivo/pasta informado.

    No Windows usa ``explorer /select``; no macOS ``open -R``; no Linux tenta
    ``xdg-open`` no diretório pai (a seleção de arquivo não é portável). Como
    fallback, abre a URL via ``QDesktopServices``.
    """
    if not path:
        return
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run(["explorer", "/select,", path], check=False)
        elif system == "Darwin":
            subprocess.run(["open", "-R", path], check=False)
        else:
            target = Path(path)
            if target.is_file():
                target = target.parent
            subprocess.run(["xdg-open", str(target)], check=False)
    except (OSError, RuntimeError):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def relative_path(root: str | Path | None, path: str | Path) -> str:
    """Caminho ``path`` relativo a ``root`` (estilo POSIX), ou ``str(path)``.

    Se ``root`` for None ou ``path`` não estiver sob ``root``, retorna o
    caminho completo.
    """
    path = Path(path)
    if root is not None:
        try:
            return path.relative_to(Path(root)).as_posix()
        except ValueError:
            return str(path)
    return str(path)

