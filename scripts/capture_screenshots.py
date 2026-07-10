"""Capture live UI screenshots for README (Windows)."""
from __future__ import annotations

import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PIL import Image, ImageGrab  # noqa: E402
import ctypes  # noqa: E402
import webview  # noqa: E402

from astral_party_auto.core.config import APP_ROOT  # noqa: E402
from astral_party_auto.web_app import WEB_DIR, DesktopApi, _set_windows_app_id  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

user32 = ctypes.windll.user32
try:
    user32.SetProcessDPIAware()
except Exception:
    pass


def find_hwnd(title_part: str = "吉星派对") -> int:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _lp):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, buf, 512)
        if title_part in (buf.value or "") and user32.IsWindowVisible(h):
            found.append(int(h))
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0


def grab_window(hwnd: int, path: Path) -> bool:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    box = (rect.left, rect.top, rect.right, rect.bottom)
    if box[2] - box[0] < 200:
        return False
    img = ImageGrab.grab(bbox=box)
    img.thumbnail((1280, 800), Image.Resampling.LANCZOS)
    img.save(path, "PNG", optimize=True)
    print("saved", path.name, img.size)
    return True


def main() -> None:
    _set_windows_app_id()
    api = DesktopApi()
    url = (WEB_DIR / "index.html").resolve().as_uri()
    title = "吉星派对 Mod 助手"
    window = webview.create_window(
        title,
        url=url,
        js_api=api,
        width=1100,
        height=720,
        background_color="#141019",
    )
    api.attach_window(window)

    def worker() -> None:
        time.sleep(3.8)
        hwnd = find_hwnd()
        print("hwnd", hwnd)
        if not hwnd:
            try:
                window.destroy()
            except Exception:
                pass
            return
        grab_window(hwnd, OUT / "01_dashboard.png")
        for page, name in (
            ("browse", "02_browse.png"),
            ("manage", "03_manage.png"),
            ("pack", "04_pack.png"),
            ("studio", "05_studio.png"),
        ):
            try:
                window.evaluate_js(
                    f"document.querySelector('.nav-button[data-page=\"{page}\"]').click();"
                )
            except Exception as exc:
                print("nav", page, exc)
            time.sleep(1.4)
            grab_window(hwnd, OUT / name)
        try:
            window.destroy()
        except Exception as exc:
            print("destroy", exc)

    threading.Thread(target=worker, daemon=True).start()
    webview.start()
    print("shots:", [p.name for p in sorted(OUT.glob("*.png"))])


if __name__ == "__main__":
    main()
