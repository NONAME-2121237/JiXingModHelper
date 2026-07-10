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
    # 默认原生界面：不依赖 pywebview/pythonnet，打包后更稳定。
    # HTML 界面保留给开发调试；显式传 --web 才会启动。
    if "--web" in args:
        from .web_app import main as web_main

        web_main()
        return
    _run_legacy_ui()


if __name__ == "__main__":
    main()
