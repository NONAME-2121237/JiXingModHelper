"""读取游戏的 Unity 资源包（Addressable bundle）：列出资源、导出预览、建立索引。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import UnityPy


# 资源包相对客户端 exe 所在目录的位置
AA_SUBPATH = ("StreamingAssets", "aa", "StandaloneWindows64")

_TEXTURE_TYPES = {"Texture2D", "Sprite"}
# Unity 类型名 → 我们的四类选项卡
_TYPE_MAP = {
    "Texture2D": "texture",
    "Sprite": "texture",
    "TextAsset": "text",
    "Mesh": "mesh",
    "AnimationClip": "anim",
}

ASSET_TYPE_KEYS = ("texture", "text", "mesh", "anim")
INDEX_VERSION = 3


@dataclass(frozen=True)
class TextureInfo:
    name: str
    width: int
    height: int


def aa_dir_for_exe(exe_path: str | Path) -> Path:
    """由客户端 exe 推出资源包目录：<exe目录>/<exe名>_Data/StreamingAssets/aa/StandaloneWindows64。"""
    exe = Path(exe_path)
    data_dir = exe.parent / f"{exe.stem}_Data"
    return data_dir.joinpath(*AA_SUBPATH)


def read_bundle_textures(bundle_path: str | Path) -> list[TextureInfo]:
    """读出一个资源包里的所有贴图信息（名字 + 尺寸），不导出像素，尽量快。"""
    textures: list[TextureInfo] = []
    env = UnityPy.load(str(bundle_path))
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        name = getattr(data, "m_Name", "") or getattr(data, "name", "") or "(未命名)"
        width = int(getattr(data, "m_Width", 0) or 0)
        height = int(getattr(data, "m_Height", 0) or 0)
        textures.append(TextureInfo(name=str(name), width=width, height=height))
    return textures


def read_bundle_asset_names(bundle_path: str | Path) -> dict[str, list[str]]:
    """一次扫包，按类型收集资源名。返回 texture/text/mesh/anim → [name,...]。

    TextAsset 只收录可读文本，跳过 FairyGUI（*_fui）等二进制，避免列表全是乱码。
    本游戏音效不在 Addressable bundle 的 AudioClip 里，故不索引音频。
    """
    from .maker import is_readable_text_asset

    out: dict[str, list[str]] = {k: [] for k in ASSET_TYPE_KEYS}
    env = UnityPy.load(str(bundle_path))
    for obj in env.objects:
        kind = _TYPE_MAP.get(obj.type.name)
        if not kind:
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        name = str(getattr(data, "m_Name", "") or getattr(data, "name", "") or "(未命名)")
        # Sprite 与 Texture2D 可能重名，贴图侧去重
        if kind == "texture" and name in out["texture"]:
            continue
        # 文本：过滤 FGUI / 二进制
        if kind == "text" and not is_readable_text_asset(data):
            continue
        out[kind].append(name)
    return out


def extract_texture_png(
    bundle_path: str | Path,
    out_png: str | Path,
    target_name: str | None = None,
) -> TextureInfo | None:
    """导出资源包里的贴图为 PNG。target_name 为空时取第一张。"""
    env = UnityPy.load(str(bundle_path))
    for obj in env.objects:
        if obj.type.name != "Texture2D":
            continue
        data = obj.read()
        name = str(getattr(data, "m_Name", "") or getattr(data, "name", "") or "(未命名)")
        if target_name and name != target_name:
            continue
        image = data.image
        if image is None:
            continue
        out = Path(out_png)
        out.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGBA").save(out)
        return TextureInfo(name=name, width=image.width, height=image.height)
    return None


def iter_bundle_files(aa_dir: str | Path) -> Iterable[Path]:
    aa = Path(aa_dir)
    if not aa.exists():
        return []
    return sorted(aa.glob("*.bundle"))


def _empty_typed_index() -> dict[str, dict[str, list[str]]]:
    return {k: {} for k in ASSET_TYPE_KEYS}


def build_asset_index(
    aa_dir: str | Path,
    cache_path: str | Path,
    progress: Callable[[int, int, str], bool] | None = None,
) -> dict[str, dict[str, list[str]]]:
    """扫描所有资源包，建立多类型索引并缓存。

    返回 {texture|text|mesh|anim: {bundle文件名: [资源名...]}}
    progress(done, total, current) 返回 False 可中断。
    """
    aa = Path(aa_dir)
    bundles = list(iter_bundle_files(aa))
    total = len(bundles)
    typed = _empty_typed_index()
    for done, bundle in enumerate(bundles, start=1):
        try:
            names_by_type = read_bundle_asset_names(bundle)
        except Exception:
            names_by_type = {k: [] for k in ASSET_TYPE_KEYS}
        for kind, names in names_by_type.items():
            if names:
                typed[kind][bundle.name] = names
        if progress is not None and not progress(done, total, bundle.name):
            break
    _save_typed_index(cache_path, typed)
    return typed


def _save_typed_index(cache_path: str | Path, typed: dict[str, dict[str, list[str]]]) -> None:
    cache = Path(cache_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": INDEX_VERSION, **{k: typed.get(k, {}) for k in ASSET_TYPE_KEYS}}
    cache.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_asset_index(cache_path: str | Path) -> dict[str, dict[str, list[str]]]:
    """加载多类型索引。兼容旧版纯贴图 dict。"""
    cache = Path(cache_path)
    typed = _empty_typed_index()
    if not cache.exists():
        return typed
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return typed
    if not isinstance(data, dict):
        return typed
    # v2：带 version 与各类型键
    if data.get("version") == INDEX_VERSION or any(k in data for k in ASSET_TYPE_KEYS):
        for k in ASSET_TYPE_KEYS:
            block = data.get(k)
            if isinstance(block, dict):
                typed[k] = {
                    str(bn): [str(n) for n in names]
                    for bn, names in block.items()
                    if isinstance(names, list)
                }
        # 若只有 texture 且旧字段混在顶层，已处理
        if any(typed.get(k) for k in ASSET_TYPE_KEYS):
            return typed
    # 旧版：{bundle: [tex,...]}
    if all(isinstance(v, list) for v in data.values()):
        typed["texture"] = {
            str(bn): [str(n) for n in names]
            for bn, names in data.items()
            if isinstance(names, list)
        }
    return typed
