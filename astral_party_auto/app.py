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


def main(argv: list[str] | None = None) -> None:
    _set_windows_app_id()
    args = list(sys.argv[1:] if argv is None else argv)
    # 默认 HTML/pywebview；--legacy 走旧 customtkinter
    if "--legacy" in args or "--ctk" in args:
        from .ui.main_window import MainWindow

        app = MainWindow()
        app.mainloop()
        return
    from .web_app import main as web_main

    web_main()


if __name__ == "__main__":
    main()
