from __future__ import annotations

import os
import sys
from pathlib import Path


def _set_windows_app_id() -> None:
    # Without this, Windows taskbar groups under pythonw.exe and shows the Python icon.
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "AstralParty.ModHelper.1.0"
        )
    except Exception:
        pass


def _fix_frozen_data_paths() -> None:
    """打包后确保 archspec 能找到 cpu json（ASTC 解压依赖）。"""
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    arch_cpu = Path(meipass) / "archspec" / "json" / "cpu"
    if arch_cpu.is_dir():
        os.environ.setdefault("ARCHSPEC_CPU_DIR", str(arch_cpu))


def main(argv: list[str] | None = None) -> None:
    _fix_frozen_data_paths()
    _set_windows_app_id()
    from .native_host_app import main as run_html

    run_html()


if __name__ == "__main__":
    main()
