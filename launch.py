"""打包入口 / 开发入口：无控制台启动界面。"""
from __future__ import annotations

import sys


def main() -> None:
    from astral_party_auto.app import main as app_main

    app_main(sys.argv[1:])


if __name__ == "__main__":
    main()
