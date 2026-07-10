from __future__ import annotations

import sys
from pathlib import Path


def _app_root() -> Path:
    """可写根目录：modkit_data / made_mods 放这里。

    打包成 exe 后为 exe 所在文件夹；开发时为仓库根目录。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _resource_root() -> Path:
    """只读资源根：webui / assets。

    打包后在 PyInstaller 的 _MEIPASS；开发时为仓库根目录。
    """
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


APP_ROOT = _app_root()
RESOURCE_ROOT = _resource_root()
ASSETS_DIR = RESOURCE_ROOT / "assets"
# 兼容：若打包时 assets 没进包，再试 exe 旁
if not ASSETS_DIR.exists():
    ASSETS_DIR = APP_ROOT / "assets"
