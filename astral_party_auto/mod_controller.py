"""界面与 modkit 之间的编排层：检测游戏、安装/还原、分类浏览、作品集制作。"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from .core.config import APP_ROOT
from .core.detector import find_game_install, launch_direct, launch_with_steam
from .modkit import (
    ModManager,
    aa_dir_for_exe,
    all_categories,
    build_asset_index,
    default_export_name,
    export_by_type,
    export_mod_pack,
    extract_texture_png,
    find_anim_preview_texture,
    list_text_assets,
    load_asset_index,
    read_text_asset,
    replace_bundle_animation_raw,
    replace_bundle_text,
    replace_bundle_texture,
)
from .modkit.categories import (
    ASSET_TYPES,
    category_desc,
    category_label,
    categorize,
    describe_selection,
)


DATA_DIR = APP_ROOT / "modkit_data"
INDEX_CACHE = DATA_DIR / "texture_index.json"
PREVIEW_DIR = DATA_DIR / "previews"
MADE_DIR = APP_ROOT / "made_mods"
DRAFT_META = DATA_DIR / "draft_pack.json"

SEVENZIP_CANDIDATES = [
    Path(r"C:\Program Files\7-Zip\7z.exe"),
    Path(r"C:\Program Files (x86)\7-Zip\7z.exe"),
    Path(r"C:\Program Files\WinRAR\UnRAR.exe"),
]


class ModController:
    def __init__(self, log: Callable[[str], None]):
        self.log = log
        self.game_install = None
        self.aa_dir: Path | None = None
        self.manager: ModManager | None = None
        # 多类型索引：texture/text/mesh/anim → {bundle: [names]}
        self.typed_index: dict[str, dict[str, list[str]]] = load_asset_index(INDEX_CACHE)
        self._category_cache_lock = threading.Lock()
        self._category_cache_source: dict[str, list[str]] | None = None
        self._category_rows: dict[str, list[tuple[str, str]]] = {}
        self._category_counts: dict[str, int] = {}
        self._indexing = False
        # 作品集草稿：[{kind, bundle, name, note, file?}]
        self.draft_items: list[dict] = []
        self.draft_name: str = "我的Mod套装"
        # 当前在「浏览」里选中的资源，供「制作」页使用
        self.selection: dict | None = None
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
        MADE_DIR.mkdir(parents=True, exist_ok=True)
        self._load_draft()
        self.refresh_detection()
        self._prime_texture_category_cache()

    @property
    def index(self) -> dict[str, list[str]]:
        """贴图索引（兼容旧代码）。"""
        return self.typed_index.get("texture", {})

    @index.setter
    def index(self, value: dict[str, list[str]]) -> None:
        self.typed_index["texture"] = value or {}
        self._category_cache_source = None
        self._prime_texture_category_cache()

    def _prime_texture_category_cache(self) -> None:
        """空闲时预先把 12 万张贴图按分类分组，避免点分类时卡 UI。"""
        texture_index = self.index
        if not texture_index or self._category_cache_source is texture_index:
            return
        threading.Thread(
            target=self._ensure_texture_category_cache,
            name="texture-category-cache",
            daemon=True,
        ).start()

    def _ensure_texture_category_cache(self) -> dict[str, list[tuple[str, str]]]:
        """每份贴图索引只扫描一次；索引刷新后按对象身份自动失效。"""
        texture_index = self.index
        if self._category_cache_source is texture_index:
            return self._category_rows

        with self._category_cache_lock:
            texture_index = self.index
            if self._category_cache_source is texture_index:
                return self._category_rows

            rows: dict[str, list[tuple[str, str]]] = {}
            counts: dict[str, int] = {"all": 0}
            for bundle, names in texture_index.items():
                counts["all"] += len(names)
                for name in names:
                    category_id = categorize(name)
                    rows.setdefault(category_id, []).append((bundle, name))
                    counts[category_id] = counts.get(category_id, 0) + 1

            # 最后一次性替换，UI 线程不会读到只构建了一半的缓存。
            self._category_rows = rows
            self._category_counts = counts
            self._category_cache_source = texture_index
            return rows

    # ---------- 检测 ----------
    def refresh_detection(self) -> None:
        self.game_install = find_game_install()
        exe = None
        if self.game_install:
            exe = self.game_install.cn_exe or self.game_install.int_exe
        if exe and Path(exe).exists():
            self.aa_dir = aa_dir_for_exe(exe)
            if self.aa_dir and self.aa_dir.exists():
                self.manager = ModManager(self.aa_dir, DATA_DIR)
            else:
                # exe 在但 aa 路径不对时再试另一种 exe
                other = None
                if self.game_install:
                    other = self.game_install.int_exe if exe == self.game_install.cn_exe else self.game_install.cn_exe
                if other and Path(other).exists():
                    alt = aa_dir_for_exe(other)
                    if alt.exists():
                        self.aa_dir = alt
                        self.manager = ModManager(self.aa_dir, DATA_DIR)
                    else:
                        self.aa_dir = None
                        self.manager = None
                else:
                    self.aa_dir = None
                    self.manager = None
        else:
            self.aa_dir = None
            self.manager = None

    @property
    def has_game(self) -> bool:
        return self.aa_dir is not None and self.aa_dir.exists()

    @property
    def bundle_count(self) -> int:
        if not self.has_game:
            return 0
        # 缓存：避免每次仪表盘都扫 5000+ 个文件
        cached = getattr(self, "_bundle_count_cache", None)
        key = str(self.aa_dir)
        if cached and cached[0] == key:
            return cached[1]
        n = sum(1 for _ in self.aa_dir.glob("*.bundle"))
        self._bundle_count_cache = (key, n)
        return n

    # ---------- 安装 / 还原 ----------
    def analyze(self, mod_path: str | Path):
        self._require_game()
        return self.manager.analyze_mod(self._as_mod_dir(mod_path))

    def install(self, mod_path: str | Path, name: str | None = None):
        self._require_game()
        src = Path(mod_path)
        # 显示名用原始 zip/文件夹名，不要 apmod_临时目录名
        if not name:
            name = src.stem if src.is_file() else src.name
            if name.startswith("apmod_"):
                name = src.name
        mod_dir = self._as_mod_dir(mod_path)
        analysis = self.manager.install_mod(mod_dir, name)
        self.log(
            f"已安装「{name}」：替换 {len(analysis.matched)} 个资源包"
            f"（版本不符跳过 {len(analysis.unmatched)} 个），原文件已备份，可随时还原。"
        )
        return analysis

    def uninstall(self, name: str) -> int:
        self._require_game()
        n = self.manager.uninstall_mod(name)
        self.log(f"已卸载「{name}」，还原 {n} 个原始资源包。")
        return n

    def disable_mod(self, name: str) -> int:
        self._require_game()
        n = self.manager.disable_mod(name)
        self.log(f"已禁用「{name}」，还原 {n} 个文件（记录保留，可再启用）。")
        return n

    def enable_mod(self, name: str) -> int:
        self._require_game()
        n = self.manager.enable_mod(name)
        self.log(f"已启用「{name}」，重新应用 {n} 个资源包。")
        return n

    def restore_all(self) -> int:
        self._require_game()
        n = self.manager.restore_all()
        self.log(f"一键全还原：恢复 {n} 个原始资源包，游戏回到未改状态。")
        return n

    def installed_mods(self) -> list[dict]:
        return self.manager.installed_mods() if self.manager else []

    def game_exe_display(self) -> str:
        """仪表盘展示：解析到的 exe 短路径。"""
        if not self.game_install:
            return "未检测到游戏"
        exe = self.game_install.cn_exe or self.game_install.int_exe
        if exe and exe.exists():
            return str(exe)
        return str(self.game_install.install_dir)

    # ---------- 启动游戏 ----------
    def launch_game(self, region: str = "CN") -> None:
        """启动吉星派对：优先直启本地 exe，失败再走 Steam。"""
        self.refresh_detection()
        if self.game_install:
            exe = self.game_install.executable_for_region(region)
            if exe and exe.exists():
                launch_direct(exe)
                self.log(f"已启动游戏：{exe}")
                return
            other = self.game_install.cn_exe or self.game_install.int_exe
            if other and other.exists():
                launch_direct(other)
                self.log(f"已启动游戏：{other}")
                return
        # 仍尝试 Steam；同时让界面能提示用户检查路径
        try:
            launch_with_steam()
            self.log("未找到本地 exe，已尝试通过 Steam 启动（AppID 2622000）。")
        except Exception as exc:
            raise RuntimeError(
                "找不到游戏。请确认 Steam 已安装《吉星派对》，"
                r"常见路径：D:\Steam\steamapps\common\Astral Party\8vJXn6CN\AstralParty_CN.exe"
                f"\n详情：{exc}"
            ) from exc

    # ---------- 浏览 / 预览 ----------
    def asset_type_counts(self) -> dict[str, int]:
        """四类选项卡上的资源数量。"""
        out: dict[str, int] = {}
        for tid, _label in ASSET_TYPES:
            block = self.typed_index.get(tid) or {}
            out[tid] = sum(len(names) for names in block.values())
        return out

    def categories(
        self,
        *,
        include_advanced: bool = False,
        asset_type: str = "texture",
    ) -> list[tuple[str, str, int]]:
        if asset_type != "texture":
            # 非贴图：只有「全部」一类，避免硬套贴图分类
            block = self.typed_index.get(asset_type) or {}
            total = sum(len(names) for names in block.values())
            return [("all", "全部", total)]

        if self.index:
            self._ensure_texture_category_cache()
        counts = self._category_counts
        category_rows = [("all", "全部", counts.get("all", 0))]
        for category_id, label in all_categories(include_advanced=include_advanced):
            category_rows.append((category_id, label, counts.get(category_id, 0)))
        if include_advanced:
            return category_rows
        from .modkit.categories import ADVANCED_IDS

        for category_id in ("fx", "lightmap", "other"):
            if category_id in ADVANCED_IDS:
                count = counts.get(category_id, 0)
                if count:
                    label = next((lb for cid, lb in all_categories(include_advanced=True) if cid == category_id), category_id)
                    category_rows.append((category_id, f"{label}（少碰）", count))
        return category_rows

    def browse(
        self,
        cat_id: str = "all",
        query: str = "",
        limit: int = 500,
        *,
        asset_type: str = "texture",
    ) -> list[tuple[str, str]]:
        """分页列表用。绝不扫全库再 sort 上万条——会卡死 UI。"""
        block = self.typed_index.get(asset_type) or {}
        if not block:
            return []
        if cat_id in ("all", "", "other", "fx", "lightmap", "sprite_anim") or asset_type != "texture":
            limit = min(limit, 200)
        else:
            limit = min(limit, 400)

        q = (query or "").strip().lower()
        out: list[tuple[str, str]] = []

        # 文本 / 网格 / 动画：无细分类，只搜全部
        if asset_type != "texture" or cat_id in ("all", ""):
            for bundle, names in block.items():
                for name in names:
                    # 旧索引里 *_fui 是 FairyGUI 二进制，不当文本列
                    if asset_type == "text" and (
                        name.endswith("_fui") or name.endswith("fui") or name.startswith("FGUI")
                    ):
                        continue
                    if q and q not in name.lower() and q not in bundle.lower():
                        continue
                    out.append((bundle, name))
                    if len(out) >= limit:
                        return out
            return out

        category_rows = self._ensure_texture_category_cache().get(cat_id, ())
        for bundle, name in category_rows:
            if q and q not in name.lower() and q not in bundle.lower():
                continue
            out.append((bundle, name))
            if len(out) >= limit:
                break
        out.sort(key=lambda x: x[1].lower())
        return out

    def preview_bundle(
        self,
        bundle_path: str | Path,
        texture_name: str | None = None,
        *,
        tag: str = "browse",
    ):
        """导出预览 PNG。tag 必须区分来源，避免 game/draft 同 stem 互相覆盖。"""
        bundle_path = Path(bundle_path)
        stem = bundle_path.stem
        safe = re.sub(r"[^\w\-]+", "_", texture_name or "first")[:40]
        tag = re.sub(r"[^\w\-]+", "_", tag or "browse")[:24]
        out = PREVIEW_DIR / f"{tag}_{stem}_{safe}.png"
        info = extract_texture_png(bundle_path, out, target_name=texture_name)
        return (out, info) if info else (None, None)

    def original_bundle_path(self, bundle_name: str) -> Path | None:
        """真·原版资源：有备份用备份，否则游戏目录（可能已被 mod 覆盖）。"""
        backup = DATA_DIR / "backups" / bundle_name
        if backup.exists():
            return backup
        return self.bundle_path(bundle_name)

    def set_selection(
        self,
        bundle_name: str,
        asset_name: str,
        *,
        asset_type: str = "texture",
    ) -> dict:
        """浏览页选中资源，供制作页读取。预览优先备份原皮。"""
        path = self.original_bundle_path(bundle_name)
        if not path:
            raise RuntimeError(f"找不到资源包：{bundle_name}")
        game_path = self.bundle_path(bundle_name)

        if asset_type == "texture":
            png, info = self.preview_bundle(path, asset_name, tag="orig")
            if not png or not info:
                raise RuntimeError("无法预览该贴图。")
            cat = categorize(info.name, info.width, info.height)
            self.selection = {
                "kind": "texture",
                "asset_type": "texture",
                "bundle": bundle_name,
                "bundle_path": str(game_path or path),
                "original_path": str(path),
                "name": info.name,
                "width": info.width,
                "height": info.height,
                "preview": str(png),
                "text_preview": "",
                "category": cat,
                "category_label": category_label(cat),
                "category_desc": category_desc(cat),
                "caption": describe_selection(info.name, info.width, info.height),
            }
            return self.selection

        if asset_type == "text":
            from .modkit.maker import decode_text_asset_raw
            import UnityPy

            text = ""
            kind = "binary"
            try:
                text = read_text_asset(path, asset_name)
                kind = "text"
            except Exception as exc:
                # 尽量给出原因，而不是把乱码塞进预览
                try:
                    env = UnityPy.load(str(path))
                    for obj in env.objects:
                        if obj.type.name != "TextAsset":
                            continue
                        data = obj.read()
                        if str(getattr(data, "m_Name", "") or "") != asset_name:
                            continue
                        raw = getattr(data, "m_Script", None)
                        if raw is None:
                            raw = getattr(data, "script", b"")
                        _t, kind = decode_text_asset_raw(raw)
                        break
                except Exception:
                    pass
                if kind == "fgui":
                    text = (
                        f"「{asset_name}」是 FairyGUI 界面包（*_fui），二进制资源，不是可读文本。\n"
                        f"刷新索引后这类条目会从「文本」列表里去掉。\n\n{exc}"
                    )
                else:
                    text = f"无法按文本打开「{asset_name}」。\n{exc}"
            snippet = (text[:800] + "…") if len(text) > 800 else text
            self.selection = {
                "kind": "text",
                "asset_type": "text",
                "bundle": bundle_name,
                "bundle_path": str(game_path or path),
                "original_path": str(path),
                "name": asset_name,
                "width": 0,
                "height": 0,
                "preview": "",
                "text_preview": snippet or "（空）",
                "category": "all",
                "category_label": "文本",
                "category_desc": (
                    "可读文本（地图 JSON / 词库等）"
                    if kind == "text"
                    else "二进制 TextAsset（非可读文本）"
                ),
                "caption": f"文本 · {asset_name}",
            }
            return self.selection

        if asset_type == "anim":
            # 第一帧/图集预览：同包里找 Walk-001 这类贴图
            preview_tex = find_anim_preview_texture(path, asset_name)
            png = None
            width = height = 0
            if preview_tex:
                png, info = self.preview_bundle(path, preview_tex, tag="animprev")
                if info:
                    width, height = info.width, info.height
            self.selection = {
                "kind": "anim",
                "asset_type": "anim",
                "bundle": bundle_name,
                "bundle_path": str(game_path or path),
                "original_path": str(path),
                "name": asset_name,
                "preview_texture": preview_tex or "",
                "width": width,
                "height": height,
                "preview": str(png) if png else "",
                "text_preview": (
                    f"动画片段 {asset_name}\n"
                    f"预览贴图：{preview_tex or '（同包未找到对应图）'}\n"
                    "换图 = 替换该预览贴图/图集；也可用 .animbin 替换动画数据。"
                ),
                "category": "all",
                "category_label": "动画",
                "category_desc": (
                    f"AnimationClip · 预览 {preview_tex}" if preview_tex else "AnimationClip · 无预览贴图"
                ),
                "caption": f"动画 · {asset_name}" + (f" · 预览 {preview_tex}" if preview_tex else ""),
            }
            return self.selection

        # mesh 等：仅浏览导出
        labels = {"mesh": "3D模型"}
        hints = {
            "mesh": "3D 三角面模型（Mesh），可导出 OBJ。不做替换。",
        }
        lab = labels.get(asset_type, asset_type)
        self.selection = {
            "kind": asset_type,
            "asset_type": asset_type,
            "bundle": bundle_name,
            "bundle_path": str(game_path or path),
            "original_path": str(path),
            "name": asset_name,
            "width": 0,
            "height": 0,
            "preview": "",
            "text_preview": hints.get(asset_type, ""),
            "category": "all",
            "category_label": lab,
            "category_desc": hints.get(asset_type, ""),
            "caption": f"{lab} · {asset_name}",
        }
        return self.selection

    def clear_selection(self) -> None:
        self.selection = None

    def export_selection(
        self,
        dest: str | Path,
        *,
        fmt: str | None = None,
    ) -> Path:
        """导出当前选中资源（贴图/文本/网格/动画）。"""
        if not self.selection:
            raise RuntimeError("还没有选中资源。")
        asset_type = self.selection.get("asset_type") or self.selection.get("kind") or "texture"
        path = self.original_bundle_path(self.selection["bundle"])
        if not path:
            raise RuntimeError("找不到资源包。")
        out = export_by_type(
            asset_type,
            path,
            self.selection["name"],
            dest,
            fmt=fmt,
        )
        self.log(f"已导出：{out}")
        return out

    def default_export_filename(self) -> str:
        if not self.selection:
            return "export.bin"
        kind = self.selection.get("asset_type") or "texture"
        return default_export_name(kind, self.selection.get("name") or "asset")

    def draft_preview_paths(self, index: int) -> tuple[Path | None, Path | None]:
        """返回 (游戏原图预览, 作品集内替换后预览)。缓存 tag 隔离，互不覆盖。"""
        if not (0 <= index < len(self.draft_items)):
            return None, None
        item = self.draft_items[index]
        bundle_name = item.get("bundle", "")
        tex = item.get("name", "")
        orig = None
        modded = None
        if item.get("kind") != "texture":
            return None, None
        src_orig = self.original_bundle_path(bundle_name)
        if src_orig and src_orig.exists():
            try:
                png, _ = self.preview_bundle(src_orig, tex, tag="orig")
                orig = png
            except Exception:
                pass
        draft_b = self._draft_dir() / bundle_name
        if draft_b.exists():
            try:
                png, _ = self.preview_bundle(draft_b, tex, tag="draft")
                modded = png
            except Exception:
                pass
        return orig, modded

    def preview_mod_bundle(
        self, bundle_path: str | Path, texture_name: str | None = None
    ):
        """预览外部 mod 包内资源（不写游戏目录）。"""
        return self.preview_bundle(bundle_path, texture_name, tag="modpreview")

    def list_bundle_texture_names(self, bundle_path: str | Path) -> list[str]:
        from .modkit import read_bundle_textures

        try:
            return [t.name for t in read_bundle_textures(bundle_path)]
        except Exception:
            return []

    def update_draft_texture(
        self,
        index: int,
        image_path: str | Path,
        crop_box: tuple[int, int, int, int] | None = None,
    ) -> dict:
        if not (0 <= index < len(self.draft_items)):
            raise RuntimeError("作品集项不存在。")
        item = self.draft_items[index]
        if item.get("kind") != "texture":
            raise RuntimeError("只能替换贴图类作品集项。")
        bundle_name = item["bundle"]
        game_b = self.bundle_path(bundle_name)
        if not game_b:
            raise RuntimeError("找不到对应游戏资源包。")
        pack_dir = self._draft_dir()
        out_bundle = pack_dir / bundle_name
        # 用游戏原版（或备份）为底再替换，避免叠改
        backup = DATA_DIR / "backups" / bundle_name
        base = backup if backup.exists() else game_b
        # 若同包还有其它贴图替换，应基于 draft；单贴图项用 base 更干净
        others = [
            x for i, x in enumerate(self.draft_items)
            if i != index and x.get("bundle") == bundle_name and x.get("kind") == "texture"
        ]
        src = out_bundle if (others and out_bundle.exists()) else base
        replaced = replace_bundle_texture(
            src, image_path, out_bundle, target_name=item.get("name"), crop_box=crop_box
        )
        item["name"] = replaced
        item["note"] = Path(image_path).name
        item["at"] = datetime.now().isoformat(timespec="seconds")
        self._save_draft()
        self.log(f"已更新作品集项：{replaced} ← {Path(image_path).name}")
        return item

    def install_draft(self) -> None:
        """把当前作品集当作 mod 装进游戏。"""
        if not self.draft_items:
            raise RuntimeError("作品集是空的。")
        pack = self._draft_dir()
        export_mod_pack(pack, None, pack_name=self.draft_name, items=self.draft_items)
        self.install(pack, name=self.draft_name)

    def bundle_path(self, bundle_name: str) -> Path | None:
        if not self.has_game:
            return None
        candidate = self.aa_dir / bundle_name
        return candidate if candidate.exists() else None

    def list_texts(self, bundle_path: str | Path) -> list[tuple[str, str]]:
        try:
            return list_text_assets(bundle_path)
        except Exception as exc:
            self.log(f"读取文本失败：{exc}")
            return []

    def read_text(self, bundle_path: str | Path, asset_name: str) -> str:
        return read_text_asset(bundle_path, asset_name)

    # ---------- 作品集（多资源一套，方便分享） ----------
    def set_draft_name(self, name: str) -> None:
        name = (name or "").strip() or "我的Mod套装"
        self.draft_name = re.sub(r'[<>:"/\\|?*]', "_", name)[:60]
        self._save_draft()

    def draft_count(self) -> int:
        return len(self.draft_items)

    def add_texture_to_draft(
        self,
        bundle_path: str | Path,
        image_path: str | Path,
        texture_name: str | None = None,
        crop_box: tuple[int, int, int, int] | None = None,
    ) -> dict:
        self._require_game()
        bundle_path = Path(bundle_path)
        # 统一用游戏目录下的文件名（备份与 aa 包同名）
        bundle_name = bundle_path.name
        pack_dir = self._draft_dir()
        out_bundle = pack_dir / bundle_name
        # 底图：优先备份原皮 → 传入路径 → 游戏目录
        backup = DATA_DIR / "backups" / bundle_name
        game_b = self.bundle_path(bundle_name)
        if backup.exists():
            base = backup
        elif bundle_path.exists():
            base = bundle_path
        elif game_b:
            base = game_b
        else:
            raise RuntimeError(f"找不到资源包：{bundle_name}")
        # 同包已有其它贴图修改时，在 draft 上继续改
        others_in_draft = any(
            x.get("bundle") == bundle_name and x.get("kind") == "texture" and x.get("name") != texture_name
            for x in self.draft_items
        )
        src = out_bundle if (others_in_draft and out_bundle.exists()) else base
        replaced = replace_bundle_texture(
            src, image_path, out_bundle, target_name=texture_name, crop_box=crop_box, match_original_size=True
        )
        item = {
            "kind": "texture",
            "bundle": bundle_name,
            "name": replaced,
            "note": Path(image_path).name,
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        self.draft_items = [x for x in self.draft_items if not (
            x.get("bundle") == item["bundle"] and x.get("name") == item["name"] and x.get("kind") == "texture"
        )]
        self.draft_items.append(item)
        self._save_draft()
        self.log(f"已加入作品集：{replaced} ← {Path(image_path).name}（共 {len(self.draft_items)} 项）")
        return item

    def add_text_to_draft(self, bundle_path: str | Path, asset_name: str, new_text: str) -> dict:
        self._require_game()
        bundle_path = Path(bundle_path)
        pack_dir = self._draft_dir()
        out_bundle = pack_dir / bundle_path.name
        # 若作品集里已有同 bundle，基于作品集版本继续改，否则用原版
        src = out_bundle if out_bundle.exists() else bundle_path
        replaced = replace_bundle_text(src, asset_name, new_text, out_bundle)
        item = {
            "kind": "text",
            "bundle": bundle_path.name,
            "name": replaced,
            "note": f"文本 {len(new_text)} 字",
            "at": datetime.now().isoformat(timespec="seconds"),
        }
        self.draft_items = [x for x in self.draft_items if not (
            x.get("bundle") == item["bundle"] and x.get("name") == item["name"] and x.get("kind") == "text"
        )]
        self.draft_items.append(item)
        self._save_draft()
        self.log(f"已加入作品集（文本）：{replaced}（共 {len(self.draft_items)} 项）")
        return item

    def add_anim_to_draft(
        self,
        bundle_path: str | Path,
        anim_name: str,
        *,
        image_path: str | Path | None = None,
        raw_path: str | Path | None = None,
        preview_texture: str | None = None,
        crop_box: tuple[int, int, int, int] | None = None,
    ) -> dict:
        """动画替换：给图则换同包预览贴图；给 .animbin 则换 AnimationClip 字节。"""
        self._require_game()
        bundle_path = Path(bundle_path)
        pack_dir = self._draft_dir()
        out_bundle = pack_dir / bundle_path.name
        backup = DATA_DIR / "backups" / bundle_path.name
        game_b = self.bundle_path(bundle_path.name)
        if backup.exists():
            base = backup
        elif bundle_path.exists():
            base = bundle_path
        elif game_b:
            base = game_b
        else:
            raise RuntimeError(f"找不到资源包：{bundle_path.name}")
        src = out_bundle if out_bundle.exists() else base

        if raw_path:
            raw = Path(raw_path).read_bytes()
            replaced = replace_bundle_animation_raw(src, anim_name, raw, out_bundle)
            item = {
                "kind": "anim",
                "bundle": out_bundle.name,
                "name": replaced,
                "note": f"动画数据 ← {Path(raw_path).name}",
                "at": datetime.now().isoformat(timespec="seconds"),
            }
        elif image_path:
            tex = preview_texture or find_anim_preview_texture(src, anim_name)
            if not tex:
                raise RuntimeError(
                    f"动画「{anim_name}」同包没有可替换的预览贴图。可改用 .animbin 替换动画数据，"
                    "或到「贴图 → 角色动作帧」改序列帧。"
                )
            replaced_tex = replace_bundle_texture(
                src, image_path, out_bundle, target_name=tex, crop_box=crop_box, match_original_size=True
            )
            item = {
                "kind": "texture",
                "bundle": out_bundle.name,
                "name": replaced_tex,
                "note": f"动画 {anim_name} 预览图 ← {Path(image_path).name}",
                "from_anim": anim_name,
                "at": datetime.now().isoformat(timespec="seconds"),
            }
            # 去重按贴图名
            self.draft_items = [
                x
                for x in self.draft_items
                if not (
                    x.get("bundle") == item["bundle"]
                    and x.get("name") == item["name"]
                    and x.get("kind") == "texture"
                )
            ]
            self.draft_items.append(item)
            self._save_draft()
            self.log(f"已加入作品集（动画预览图）：{anim_name} → {replaced_tex}")
            return item
        else:
            raise RuntimeError("请提供替换图片，或 .animbin 动画字节文件。")

        self.draft_items = [
            x
            for x in self.draft_items
            if not (x.get("bundle") == item["bundle"] and x.get("name") == item["name"] and x.get("kind") == "anim")
        ]
        self.draft_items.append(item)
        self._save_draft()
        self.log(f"已加入作品集（动画数据）：{replaced}")
        return item

    def remove_draft_item(self, index: int) -> None:
        if 0 <= index < len(self.draft_items):
            item = self.draft_items.pop(index)
            self._save_draft()
            self.log(f"已从作品集移除：{item.get('name')}")

    def clear_draft(self) -> None:
        """清空作品集元数据 + _draft 目录 + draft 预览缓存，不留残留。"""
        pack = self._draft_dir()
        if pack.exists():
            for f in sorted(pack.rglob("*"), reverse=True):
                try:
                    if f.is_file():
                        f.unlink(missing_ok=True)
                    elif f.is_dir():
                        f.rmdir()
                except OSError:
                    pass
            shutil.rmtree(pack, ignore_errors=True)
        # 清掉 draft 预览图，避免作品集空了还占磁盘/显示旧图
        if PREVIEW_DIR.exists():
            for p in PREVIEW_DIR.glob("draft_*"):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        self.draft_items = []
        self._save_draft()
        # 确保目录空着
        pack.mkdir(parents=True, exist_ok=True)
        self.log("作品集已清空（含草稿文件与预览缓存）。")

    def export_draft(self, as_zip: bool = True) -> Path:
        if not self.draft_items:
            raise RuntimeError("作品集是空的，先加入一些替换再导出。")
        pack_dir = self._draft_dir()
        # 确保 meta 写入
        export_mod_pack(pack_dir, None, pack_name=self.draft_name, items=self.draft_items)
        # 复制一份到 made_mods/<name>_<time>
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_dir = MADE_DIR / f"{self.draft_name}_{stamp}"
        if final_dir.exists():
            shutil.rmtree(final_dir)
        shutil.copytree(pack_dir, final_dir)
        export_mod_pack(final_dir, None, pack_name=self.draft_name, items=self.draft_items)
        if as_zip:
            zip_path = MADE_DIR / f"{self.draft_name}_{stamp}.zip"
            export_mod_pack(final_dir, zip_path, pack_name=self.draft_name, items=self.draft_items)
            self.log(f"已导出分享包：{zip_path}（{len(self.draft_items)} 项，也可直接装文件夹 {final_dir.name}）")
            return zip_path
        self.log(f"已导出作品集文件夹：{final_dir}")
        return final_dir

    # ---------- 后台建索引 ----------
    def build_index_async(self, progress: Callable[[int, int], None], on_done: Callable[[int], None]) -> None:
        if self._indexing or not self.has_game:
            return
        self._indexing = True

        def worker():
            try:
                typed = build_asset_index(
                    self.aa_dir, INDEX_CACHE, progress=lambda d, t, _n: (progress(d, t) or True)
                )
                self.typed_index = typed
                self._prime_texture_category_cache()
                # on_done 仍传「含资源的包数」（各类型并集）
                packs = set()
                for block in typed.values():
                    packs.update(block.keys())
                on_done(len(packs))
            finally:
                self._indexing = False

        threading.Thread(target=worker, daemon=True).start()

    @property
    def index_ready(self) -> bool:
        return any(bool(block) for block in self.typed_index.values())

    # ---------- 内部 ----------
    def _require_game(self) -> None:
        if not self.has_game:
            raise RuntimeError("没有检测到游戏资源目录，请确认吉星派对已通过 Steam 安装。")

    def _draft_dir(self) -> Path:
        d = MADE_DIR / "_draft"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save_draft(self) -> None:
        DRAFT_META.write_text(
            json.dumps({"name": self.draft_name, "items": self.draft_items}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_draft(self) -> None:
        if not DRAFT_META.exists():
            return
        try:
            data = json.loads(DRAFT_META.read_text(encoding="utf-8"))
            self.draft_name = data.get("name") or self.draft_name
            self.draft_items = list(data.get("items") or [])
        except (OSError, json.JSONDecodeError):
            pass

    def _as_mod_dir(self, mod_path: str | Path) -> Path:
        path = Path(mod_path)
        if path.is_dir():
            return path
        if path.suffix.lower() == ".zip":
            temp = Path(tempfile.mkdtemp(prefix="apmod_"))
            with zipfile.ZipFile(path) as zf:
                zf.extractall(temp)
            return temp
        if path.suffix.lower() == ".rar":
            temp = Path(tempfile.mkdtemp(prefix="apmod_"))
            seven = next((p for p in SEVENZIP_CANDIDATES if p.exists()), None)
            if not seven:
                raise RuntimeError("需要 7-Zip 或 WinRAR 才能解压 .rar，请先手动解压成文件夹再选。")
            subprocess.run(
                [str(seven), "x", str(path), f"-o{temp}", "-y"],
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return temp
        raise RuntimeError("请选择 mod 文件夹，或 .zip / .rar 压缩包。")
