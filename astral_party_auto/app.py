from __future__ import annotations


def _set_windows_app_id() -> None:
    # 不设的话 Windows 任务栏会归到 pythonw.exe、显示 Python 图标。
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AstralParty.ModHelper.1.0")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> None:
    """HTML 界面：本地小服务 + Edge 应用窗口，不依赖 pythonnet/.NET。"""
    _set_windows_app_id()
    from .web_app import main as web_main

    web_main()


if __name__ == "__main__":
    main()
