"""Windows taskbar identity helpers."""

from __future__ import annotations

import sys
from pathlib import Path


def register_taskbar_identity(
    app_id: str, display_name: str, icon_path: Path | str | None = None
) -> None:
    """Set AppUserModelID and register it in the Windows registry.

    This ensures the taskbar shows the correct icon and display name for
    processes that are not the app's own .exe (e.g. pythonw.exe running
    ``-m``).  Must be called *before* QApplication is created.

    - Sets ``SetCurrentProcessExplicitAppUserModelID`` so Windows groups
      the process under *app_id*.
    - Writes ``HKCU\\Software\\Classes\\AppUserModelId\\<app_id>`` with
      ``DisplayName`` and ``IconUri`` so the taskbar resolves the icon
      from the registry regardless of which process hosts the window.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import winreg

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)

        key_path = f"Software\\Classes\\AppUserModelId\\{app_id}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, display_name)
            if icon_path:
                p = Path(icon_path)
                if p.exists():
                    winreg.SetValueEx(
                        key, "IconUri", 0, winreg.REG_SZ, str(p.resolve())
                    )

        # Notify the shell that icon associations may have changed so the
        # taskbar drops any cached icon for this AppUserModelId.
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
    except Exception:
        pass
