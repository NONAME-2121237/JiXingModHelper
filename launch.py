"""打包入口 / 开发入口：无控制台启动界面。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _fix_frozen_data_paths() -> None:
    """PyInstaller 打包后 archspec / astc 依赖的 json 需显式指定目录。

    否则 ASTC 贴图预览会报：
    [Errno 2] No such file or directory: ...\\_internal\\archspec\\...
    """
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    root = Path(meipass)
    arch_cpu = root / "archspec" / "json" / "cpu"
    if arch_cpu.is_dir():
        # archspec.cpu.schema 支持此环境变量覆盖 json 位置
        os.environ.setdefault("ARCHSPEC_CPU_DIR", str(arch_cpu))


def main() -> None:
    _fix_frozen_data_paths()
    from astral_party_auto.app import main as app_main

    app_main(sys.argv[1:])


if __name__ == "__main__":
    main()
