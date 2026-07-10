"""HTML/CSS 桌面界面：pywebview 只负责窗口，资源处理仍复用 ModController。"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import subprocess
import sys
import threading
from collections import deque
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from .core.config import APP_ROOT, ASSETS_DIR, RESOURCE_ROOT
from .mod_controller import DATA_DIR, MADE_DIR, ModController
from .modkit.categories import ASSET_TYPES, dedupe_by_texture_name


def _web_dir() -> Path:
    candidates = [
        RESOURCE_ROOT / "astral_party_auto" / "webui",
        RESOURCE_ROOT / "webui",
        Path(__file__).resolve().parent / "webui",
        APP_ROOT / "astral_party_auto" / "webui",
    ]
    for path in candidates:
        if (path / "index.html").exists():
            return path
    return candidates[0]


WEB_DIR = _web_dir()


def _configure_frozen_pythonnet() -> None:
    """打包版：强制用 Windows 自带的 .NET Framework(netfx)，并指向随程序的 Python DLL。

    不设 netfx，pythonnet 3.x 会去找 .NET Core，精简系统上直接崩。netfx（4.7.2+）Win10/11 一定有。
    另外 build_exe.spec 会把 pythonnet/runtime 里的 coreclr facade（netstandard/System.*）剔掉，
    否则 netfx 加载 Python.Runtime.dll 时和这些 facade 冲突，报 Loader.Initialize 失败。
    """
    if not getattr(sys, "frozen", False):
        return
    os.environ.setdefault("PYTHONNET_RUNTIME", "netfx")
    runtime_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    for base in {runtime_root, runtime_root / "_internal", Path(sys.executable).resolve().parent}:
        python_dll = base / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        if python_dll.exists():
            os.environ.setdefault("PYTHONNET_PYDLL", str(python_dll))
            break


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def exposed(method: Callable) -> Callable:
    """所有 JS API 都返回统一结构，前端不用处理 Python 异常对象。"""

    @wraps(method)
    def wrapped(self: "DesktopApi", *args, **kwargs):
        try:
            with self._controller_lock:
                data = method(self, *args, **kwargs)
            return {"ok": True, "data": _json_safe(data)}
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self._append_log(f"操作失败：{message}")
            return {"ok": False, "error": message}

    return wrapped


class DesktopApi:
    def __init__(self) -> None:
        self._controller_lock = threading.RLock()
        self._logs: deque[str] = deque(maxlen=800)
        self._window = None
        self._image_cache: dict[tuple, str] = {}
        self._pending_mod_path: Path | None = None
        self._replacement_path: Path | None = None
        # Mod 管理预览：{bundle文件名: Path}
        self._mod_preview_files: dict[str, Path] = {}
        self._mod_preview_title: str = ""
        self.controller = ModController(self._append_log)

    def attach_window(self, window) -> None:
        self._window = window

    def _append_log(self, message: str) -> None:
        from datetime import datetime

        line = f"[{datetime.now():%H:%M:%S}] {message}"
        self._logs.append(line)
        self._emit("log", {"line": line})

    def _emit(self, event: str, payload: dict) -> None:
        if self._window is None:
            return
        packet = json.dumps({"event": event, "payload": payload}, ensure_ascii=False)
        try:
            self._window.run_js(f"window.handleBackendEvent({packet})")
        except Exception:
            pass

    def _image_data(self, path: str | Path | None) -> str:
        if not path:
            return ""
        image_path = Path(path)
        if not image_path.exists() or not image_path.is_file():
            return ""
        stat = image_path.stat()
        cache_key = (str(image_path), stat.st_mtime_ns, stat.st_size)
        cached = self._image_cache.get(cache_key)
        if cached:
            return cached
        mime = mimetypes.guess_type(image_path.name)[0] or "image/png"
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        data_url = f"data:{mime};base64,{encoded}"
        if len(self._image_cache) > 40:
            self._image_cache.clear()
        self._image_cache[cache_key] = data_url
        return data_url

    def _selection_payload(self, selection: dict | None = None, *, full_text: bool = False) -> dict | None:
        selection = selection or self.controller.selection
        if not selection:
            return None
        payload = dict(selection)
        payload["preview_data"] = self._image_data(selection.get("preview"))
        if full_text and selection.get("asset_type") == "text":
            source = selection.get("original_path") or selection.get("bundle_path")
            payload["full_text"] = self.controller.read_text(source, selection["name"])
        return payload

    def _dashboard_state(self) -> dict:
        controller = self.controller
        installed = controller.installed_mods()
        backup_count = 0
        if controller.manager and controller.manager.backup_dir.exists():
            backup_count = sum(1 for _ in controller.manager.backup_dir.glob("*.bundle"))
        game_name = "未检测到"
        if controller.game_install:
            game_name = controller.game_install.install_dir.name
        return {
            "has_game": controller.has_game,
            "game_name": game_name,
            "game_exe": controller.game_exe_display(),
            "bundle_count": controller.bundle_count,
            "texture_bundle_count": len(controller.index),
            "installed_count": len(installed),
            "backup_count": backup_count,
            "index_ready": controller.index_ready,
            "asset_type_counts": controller.asset_type_counts(),
        }

    def _draft_state(self) -> dict:
        return {
            "name": self.controller.draft_name,
            "items": [dict(item) for item in self.controller.draft_items],
        }

    def _pick_path(self, dialog_type, *, file_types=(), save_filename: str = "") -> Path | None:
        if self._window is None:
            raise RuntimeError("桌面窗口还没有准备好。")
        result = self._window.create_file_dialog(
            dialog_type,
            allow_multiple=False,
            save_filename=save_filename or "",
            file_types=tuple(file_types) if file_types else (),
        )
        if not result:
            return None
        # pywebview 有时返回 str，有时 list/tuple
        if isinstance(result, (list, tuple)):
            if not result:
                return None
            return Path(result[0])
        return Path(result)

    @exposed
    def bootstrap(self) -> dict:
        # 启动时强制再检一次：WebView 冷启动 / 杀软拦截注册表时，构造期检测可能为空
        self.controller.refresh_detection()
        if not self.controller.has_game:
            # 再试一轮（Steam 库盘刚就绪等情况）
            self.controller.refresh_detection()
        dash = self._dashboard_state()
        if dash.get("has_game"):
            self._append_log(f"已连接游戏：{dash.get('game_exe') or dash.get('game_name')}")
        else:
            self._append_log("未检测到游戏。可点「刷新检测」，或确认 Steam 已安装吉星派对。")
        return {
            "dashboard": dash,
            "installed": self.controller.installed_mods(),
            "draft": self._draft_state(),
            "logs": list(self._logs),
            "asset_types": [{"id": type_id, "label": label} for type_id, label in ASSET_TYPES],
        }

    @exposed
    def refresh_detection(self) -> dict:
        self.controller.refresh_detection()
        if self.controller.has_game:
            self._append_log(f"已刷新游戏检测：{self.controller.game_exe_display()}")
        else:
            self._append_log("已刷新游戏检测：仍未找到。")
        return self._dashboard_state()

    @exposed
    def launch_game(self) -> dict:
        self.controller.launch_game("CN")
        return self._dashboard_state()

    @exposed
    def restore_all(self) -> dict:
        restored = self.controller.restore_all()
        return {"restored": restored, "dashboard": self._dashboard_state(), "installed": self.controller.installed_mods()}

    @exposed
    def open_asset_dir(self) -> bool:
        if not self.controller.has_game:
            raise RuntimeError("没有检测到游戏资源目录。")
        os.startfile(str(self.controller.aa_dir))
        return True

    @exposed
    def open_made_dir(self) -> bool:
        MADE_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(MADE_DIR))
        return True

    @exposed
    def get_installed_mods(self) -> list[dict]:
        return self.controller.installed_mods()

    def _set_mod_preview_files(self, files: dict[str, Path], title: str) -> list[str]:
        self._mod_preview_files = dict(files)
        self._mod_preview_title = title
        return sorted(self._mod_preview_files.keys())

    @exposed
    def choose_mod(self, mode: str) -> dict | None:
        import webview

        folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        open_dlg = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        if mode == "folder":
            path = self._pick_path(folder)
        else:
            path = self._pick_path(
                open_dlg,
                file_types=("Mod 压缩包 (*.zip;*.rar)", "所有文件 (*.*)"),
            )
        if path is None:
            return None
        analysis = self.controller.analyze(path)
        self._pending_mod_path = path
        name = path.stem if path.is_file() else path.name
        # 可装的包优先列入预览列表
        if analysis.matched:
            files = {n: analysis.files_map[n] for n in analysis.matched if n in analysis.files_map}
        else:
            files = dict(analysis.files_map)
        bundles = self._set_mod_preview_files(files, f"待装 · {name}")
        return {
            "path": str(path),
            "name": name,
            "total": analysis.total,
            "matched": len(analysis.matched),
            "unmatched": len(analysis.unmatched),
            "preview_title": self._mod_preview_title,
            "bundles": bundles,
        }

    @exposed
    def install_pending_mod(self) -> dict:
        if self._pending_mod_path is None:
            raise RuntimeError("请先选择 Mod。")
        source = self._pending_mod_path
        name = source.stem if source.is_file() else source.name
        analysis = self.controller.install(source, name=name)
        self._pending_mod_path = None
        # 装完后从 mod_store 继续预览
        store = DATA_DIR / "mod_store" / name
        bundles: list[str] = []
        if store.exists():
            files = {p.name: p for p in sorted(store.glob("*.bundle"))}
            bundles = self._set_mod_preview_files(files, f"已装 · {name}")
        return {
            "name": name,
            "matched": len(analysis.matched),
            "unmatched": len(analysis.unmatched),
            "installed": self.controller.installed_mods(),
            "dashboard": self._dashboard_state(),
            "preview_title": self._mod_preview_title,
            "bundles": bundles,
        }

    @exposed
    def change_mod(self, action: str, name: str) -> dict:
        if action == "enable":
            count = self.controller.enable_mod(name)
        elif action == "disable":
            count = self.controller.disable_mod(name)
        elif action == "uninstall":
            count = self.controller.uninstall(name)
            if self._mod_preview_title.endswith(name) or name in self._mod_preview_title:
                self._mod_preview_files = {}
                self._mod_preview_title = ""
        else:
            raise RuntimeError(f"不支持的操作：{action}")
        return {"changed": count, "installed": self.controller.installed_mods(), "dashboard": self._dashboard_state()}

    def _load_mod_preview_impl(self, name: str) -> dict:
        """点已装 Mod「预览」：列出该 mod 全部资源包，供左侧点选看图。"""
        manager = self.controller.manager
        if manager is None:
            raise RuntimeError("没有检测到游戏。")
        state = manager._load_state()
        info = state.get("mods", {}).get(name)
        if not info:
            raise RuntimeError("找不到该 Mod 的安装记录。")
        file_names = list(info.get("files") or [])
        store = Path(info.get("store") or (DATA_DIR / "mod_store" / name))
        files: dict[str, Path] = {}
        if store.exists():
            files = {p.name: p for p in store.glob("*.bundle")}
        aa = self.controller.aa_dir
        if not files and aa and file_names:
            store.mkdir(parents=True, exist_ok=True)
            import shutil

            for fname in file_names:
                src = aa / fname
                if not src.exists():
                    continue
                dst = store / fname
                try:
                    shutil.copy2(src, dst)
                    files[fname] = dst
                except OSError:
                    files[fname] = src
            info["store"] = str(store)
            state["mods"][name] = info
            manager._save_state(state)
        if not files and aa and file_names:
            for fname in file_names:
                p = aa / fname
                if p.exists():
                    files[fname] = p
        if not files:
            raise RuntimeError("没有可预览的文件。请重新安装该 mod。")
        bundles = self._set_mod_preview_files(files, f"已装 · {name}")
        first = bundles[0] if bundles else ""
        first_preview = self._preview_mod_bundle_impl(first) if first else None
        return {
            "title": self._mod_preview_title,
            "name": name,
            "bundles": bundles,
            "first": first_preview,
        }

    def _preview_mod_bundle_impl(self, bundle_name: str) -> dict:
        """预览当前预览会话中某个资源包的第一张贴图。"""
        path = self._mod_preview_files.get(bundle_name)
        if path is None or not Path(path).exists():
            raise RuntimeError(f"找不到资源包：{bundle_name}")
        names = self.controller.list_bundle_texture_names(path)
        if not names:
            return {
                "bundle": bundle_name,
                "texture": "",
                "size": "",
                "preview_data": "",
                "message": "包内无可预览贴图",
            }
        preview, texture_info = self.controller.preview_mod_bundle(path, names[0])
        return {
            "bundle": bundle_name,
            "texture": texture_info.name if texture_info else names[0],
            "size": f"{texture_info.width}×{texture_info.height}" if texture_info else "",
            "preview_data": self._image_data(preview),
            "message": "",
        }

    @exposed
    def load_mod_preview(self, name: str) -> dict:
        return self._load_mod_preview_impl(name)

    @exposed
    def preview_mod_bundle(self, bundle_name: str) -> dict:
        return self._preview_mod_bundle_impl(bundle_name)

    @exposed
    def preview_installed_mod(self, name: str) -> dict:
        """兼容旧调用：加载列表并返回第一张预览。"""
        data = self._load_mod_preview_impl(name)
        first = data.get("first") or {}
        return {
            "bundle": first.get("bundle", ""),
            "texture": first.get("texture", ""),
            "size": first.get("size", ""),
            "preview_data": first.get("preview_data", ""),
            "title": data.get("title", ""),
            "bundles": data.get("bundles", []),
            "name": name,
        }

    @exposed
    def get_categories(self, asset_type: str) -> list[dict]:
        return [
            {"id": category_id, "label": label, "count": count}
            for category_id, label, count in self.controller.categories(
                include_advanced=False,
                asset_type=asset_type,
            )
        ]

    @exposed
    def browse_assets(self, asset_type: str, category_id: str, query: str = "") -> list[dict]:
        limit = 500 if asset_type == "texture" else 200
        rows = self.controller.browse(category_id, query, limit=limit, asset_type=asset_type)
        return [
            {"bundle": bundle, "name": name, "duplicates": duplicates}
            for bundle, name, duplicates in dedupe_by_texture_name(rows)
        ]

    @exposed
    def select_asset(self, asset_type: str, bundle: str, name: str) -> dict:
        selection = self.controller.set_selection(bundle, name, asset_type=asset_type)
        return self._selection_payload(selection) or {}

    @exposed
    def get_studio_state(self) -> dict | None:
        return self._selection_payload(full_text=True)

    @exposed
    def export_selection(self, variant: str = "primary") -> dict | None:
        import webview

        selection = self.controller.selection
        if not selection:
            raise RuntimeError("请先选择资源。")
        asset_type = selection.get("asset_type") or "texture"
        default_name = self.controller.default_export_filename()
        fmt = None
        if asset_type == "texture":
            fmt = "jpg" if variant == "secondary" else "png"
            default_name = str(Path(default_name).with_suffix(f".{fmt}"))
        elif asset_type == "anim" and variant == "secondary":
            default_name = str(Path(default_name).with_suffix(".animbin"))
        save_dlg = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        file_path = self._pick_path(
            save_dlg,
            save_filename=default_name,
            file_types=("所有文件 (*.*)",),
        )
        if file_path is None:
            return None
        output = self.controller.export_selection(file_path, fmt=fmt)
        return {"path": str(output)}

    @exposed
    def choose_replacement(self) -> dict | None:
        import webview

        selection = self.controller.selection
        if not selection:
            raise RuntimeError("请先选择资源。")
        asset_type = selection.get("asset_type") or "texture"
        if asset_type in ("texture", "anim"):
            file_types = (
                "图片或动画字节 (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.animbin;*.bin)",
                "所有文件 (*.*)",
            )
        else:
            raise RuntimeError("当前类型不需要选择替换文件。")
        open_dlg = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        path = self._pick_path(open_dlg, file_types=file_types)
        if path is None:
            return None
        self._replacement_path = path
        preview_data = ""
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            preview_data = self._image_data(path)
        return {"path": str(path), "name": path.name, "size": path.stat().st_size, "preview_data": preview_data}

    @exposed
    def commit_replacement(self, text_content: str = "") -> dict:
        selection = self.controller.selection
        if not selection:
            raise RuntimeError("请先选择资源。")
        asset_type = selection.get("asset_type") or "texture"
        source = selection.get("original_path") or selection.get("bundle_path")
        if asset_type == "text":
            item = self.controller.add_text_to_draft(source, selection["name"], text_content)
        else:
            if self._replacement_path is None:
                raise RuntimeError("请先选择替换文件。")
            replacement = self._replacement_path
            if asset_type == "texture":
                item = self.controller.add_texture_to_draft(source, replacement, texture_name=selection["name"])
            elif asset_type == "anim":
                if replacement.suffix.lower() in {".animbin", ".bin"}:
                    item = self.controller.add_anim_to_draft(source, selection["name"], raw_path=replacement)
                else:
                    item = self.controller.add_anim_to_draft(
                        source,
                        selection["name"],
                        image_path=replacement,
                        preview_texture=selection.get("preview_texture"),
                    )
            else:
                raise RuntimeError("3D 模型目前只支持导出。")
        self._replacement_path = None
        return {"item": item, "draft": self._draft_state()}

    @exposed
    def get_draft(self) -> dict:
        return self._draft_state()

    @exposed
    def set_draft_name(self, name: str) -> dict:
        self.controller.set_draft_name(name)
        return self._draft_state()

    @exposed
    def get_draft_detail(self, index: int) -> dict:
        index = int(index)
        if not (0 <= index < len(self.controller.draft_items)):
            raise RuntimeError("作品集项不存在。")
        original, modified = self.controller.draft_preview_paths(index)
        return {
            "index": index,
            "item": dict(self.controller.draft_items[index]),
            "original_data": self._image_data(original),
            "modified_data": self._image_data(modified),
        }

    @exposed
    def replace_draft_image(self, index: int) -> dict | None:
        import webview

        open_dlg = getattr(getattr(webview, "FileDialog", None), "OPEN", None) or webview.OPEN_DIALOG
        path = self._pick_path(
            open_dlg,
            file_types=("图片 (*.png;*.jpg;*.jpeg;*.webp;*.bmp)", "所有文件 (*.*)"),
        )
        if path is None:
            return None
        item = self.controller.update_draft_texture(int(index), path)
        return {"item": item, "draft": self._draft_state()}

    @exposed
    def remove_draft_item(self, index: int) -> dict:
        self.controller.remove_draft_item(int(index))
        return self._draft_state()

    @exposed
    def clear_draft(self) -> dict:
        self.controller.clear_draft()
        return self._draft_state()

    @exposed
    def export_draft(self) -> dict:
        output = self.controller.export_draft(as_zip=True)
        return {"path": str(output), "draft": self._draft_state()}

    @exposed
    def install_draft(self) -> dict:
        self.controller.install_draft()
        return {"installed": self.controller.installed_mods(), "dashboard": self._dashboard_state()}

    @exposed
    def build_index(self) -> dict:
        if not self.controller.has_game:
            raise RuntimeError("没有检测到游戏。")

        def progress(done: int, total: int) -> None:
            self._emit("index_progress", {"done": done, "total": total})

        def finished(count: int) -> None:
            self._emit(
                "index_done",
                {
                    "bundles": count,
                    "counts": self.controller.asset_type_counts(),
                },
            )

        self.controller.build_index_async(progress, finished)
        return {"started": True}

    @exposed
    def get_logs(self) -> list[str]:
        return list(self._logs)

    @exposed
    def clear_logs(self) -> list[str]:
        self._logs.clear()
        return []

    @exposed
    def launch_legacy_ui(self) -> bool:
        if getattr(sys, "frozen", False):
            raise RuntimeError("打包版请使用默认界面；开发环境可用 --legacy。")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [sys.executable, "-m", "astral_party_auto", "--legacy"],
            cwd=str(APP_ROOT),
            creationflags=creation_flags,
        )
        return True


def _set_windows_app_id() -> None:
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "AstralParty.ModHelper.1.0"
        )
    except Exception:
        pass


def _apply_windows_icon(window_title: str, ico_path: Path) -> None:
    """EdgeChromium/pywebview 任务栏常仍是 Python 图标，用 Win32 强制换掉。"""
    if os.name != "nt" or not ico_path.exists():
        return
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return

    user32 = ctypes.windll.user32
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x0010
    WM_SETICON = 0x0080
    ICON_SMALL, ICON_BIG = 0, 1
    GW_OWNER = 4

    ico = str(ico_path.resolve())
    h_big = user32.LoadImageW(0, ico, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
    h_sm = user32.LoadImageW(0, ico, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
    if not h_big:
        h_big = user32.LoadImageW(0, ico, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
    if not h_sm:
        h_sm = h_big
    if not h_big and not h_sm:
        return

    def set_on(hwnd: int) -> None:
        if not hwnd:
            return
        if h_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
        if h_sm:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_sm)

    # 按标题找主窗；再补 owner（任务栏有时挂在 owner 上）
    hwnd = int(user32.FindWindowW(None, window_title) or 0)
    if not hwnd:
        # 模糊：枚举含标题的顶层窗
        titles = (window_title, "吉星派对 Mod 助手")
        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_cb(h, _lp):
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, buf, 512)
            text = buf.value or ""
            if any(t in text for t in titles):
                found.append(int(h))
            return True

        user32.EnumWindows(enum_cb, 0)
        hwnd = found[0] if found else 0

    targets = []
    if hwnd:
        targets.append(hwnd)
        owner = int(user32.GetWindow(hwnd, GW_OWNER) or 0)
        parent = int(user32.GetParent(hwnd) or 0)
        if owner:
            targets.append(owner)
        if parent:
            targets.append(parent)
    for h in targets:
        set_on(h)


def main() -> None:
    _configure_frozen_pythonnet()
    import webview

    _set_windows_app_id()
    os.chdir(APP_ROOT)
    # 打包后 webui 在 _MEIPASS，需重新解析
    global WEB_DIR
    WEB_DIR = _web_dir()
    api = DesktopApi()
    index = (WEB_DIR / "index.html").resolve()
    if not index.exists():
        raise FileNotFoundError(f"找不到界面文件：{index}")
    url = index.as_uri()
    icon = ASSETS_DIR / "app_icon.ico"
    if not icon.exists():
        icon = APP_ROOT / "assets" / "app_icon.ico"
    title = "吉星派对 Mod 助手"
    window_kwargs = {
        "title": title,
        "url": url,
        "js_api": api,
        "width": 1100,
        "height": 720,
        "min_size": (860, 600),
        "resizable": True,
        "background_color": "#141019",
        "text_select": False,
    }
    if icon.exists():
        try:
            window = webview.create_window(**window_kwargs, icon=str(icon.resolve()))
        except TypeError:
            window = webview.create_window(**window_kwargs)
    else:
        window = webview.create_window(**window_kwargs)
    api.attach_window(window)

    def after_start() -> None:
        # WebView2 建窗偏晚，多刷几次图标
        import time

        if not icon.exists():
            return
        for delay in (0.2, 0.5, 1.0, 2.0, 3.5):
            time.sleep(delay)
            try:
                _apply_windows_icon(title, icon)
            except Exception:
                pass

    debug = os.environ.get("ASTRAL_WEB_DEBUG", "").strip() == "1"

    def boot():
        threading.Thread(target=after_start, daemon=True).start()

    webview.start(func=boot, debug=debug)
