from __future__ import annotations

import sys


def _set_windows_app_id() -> None:
    # Without this, Windows taskbar groups under pythonw.exe and shows the Python icon.
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "AstralParty.ModHelper.1.0"
        )
    except Exception:
        pass


def _run_legacy_ui() -> None:
    from .ui.main_window import MainWindow

    app = MainWindow()
    app.mainloop()


def main(argv: list[str] | None = None) -> None:
    _set_windows_app_id()
    args = list(sys.argv[1:] if argv is None else argv)
    # 默认 HTML/pywebview；--legacy 走旧 customtkinter
    if "--legacy" in args or "--ctk" in args:
        _run_legacy_ui()
        return
    from .web_app import main as web_main

    try:
        web_main()
    except Exception as exc:
        # 部分精简系统缺少 pywebview 所需 .NET 组件时，仍让工具可用。
        from tkinter import messagebox

        messagebox.showwarning(
            "已切换兼容界面",
            "HTML 界面启动失败，已自动切换为兼容界面。\n\n"
            f"原因：{exc}",
        )
        _run_legacy_ui()


if __name__ == "__main__":
    main()
