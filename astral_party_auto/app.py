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


def _run_legacy_ui() -> None:
    from .ui.main_window import MainWindow

    app = MainWindow()
    app.mainloop()


def _run_html_ui() -> None:
    from .native_host_app import main as web_main

    web_main()


def main(argv: list[str] | None = None) -> None:
    _fix_frozen_data_paths()
    _set_windows_app_id()
    args = list(sys.argv[1:] if argv is None else argv)
    # 默认 HTML 前端由 C# WebView2 原生窗口承载；--legacy 回退原项目界面。
    if "--legacy" in args or "--ctk" in args:
        _run_legacy_ui()
        return
    _run_html_ui()


if __name__ == "__main__":
    main()
