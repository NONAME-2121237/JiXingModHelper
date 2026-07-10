"""安装 / 还原 mod：替换资源包前先备份原文件，随时可以一键还原。

解决三个痛点：替换麻烦、看不到实时图（预览在 bundles 里）、打了 mod 还原不了（这里备份）。
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ModAnalysis:
    name: str
    mod_dir: Path
    files_map: dict[str, Path] = field(default_factory=dict)  # 资源包名 -> mod 里的实际路径
    matched: list[str] = field(default_factory=list)          # 当前游戏里存在、能替换的
    unmatched: list[str] = field(default_factory=list)        # 当前版本已不存在（版本对不上）

    @property
    def total(self) -> int:
        return len(self.files_map)


class ModManager:
    def __init__(self, aa_dir: str | Path, data_dir: str | Path):
        self.aa_dir = Path(aa_dir)
        self.data_dir = Path(data_dir)
        self.backup_dir = self.data_dir / "backups"
        self.state_path = self.data_dir / "mods_state.json"

    # ---- 分析 ----
    def analyze_mod(self, mod_dir: str | Path) -> ModAnalysis:
        mod_dir = Path(mod_dir)
        files_map: dict[str, Path] = {}
        for path in sorted(mod_dir.rglob("*.bundle")):
            files_map.setdefault(path.name, path)
        matched = [name for name in files_map if (self.aa_dir / name).exists()]
        unmatched = [name for name in files_map if not (self.aa_dir / name).exists()]
        return ModAnalysis(
            name=mod_dir.name,
            mod_dir=mod_dir,
            files_map=files_map,
            matched=sorted(matched),
            unmatched=sorted(unmatched),
        )

    def _store_dir(self, mod_name: str) -> Path:
        return self.data_dir / "mod_store" / mod_name

    # ---- 安装 ----
    def install_mod(self, mod_dir: str | Path, name: str | None = None) -> ModAnalysis:
        analysis = self.analyze_mod(mod_dir)
        mod_name = name or analysis.name
        if not analysis.matched:
            raise RuntimeError("这个 mod 里没有一个资源包和当前游戏版本对得上，无法安装。")

        self.backup_dir.mkdir(parents=True, exist_ok=True)
        store = self._store_dir(mod_name)
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)
        store.mkdir(parents=True, exist_ok=True)

        applied: list[str] = []
        for fname in analysis.matched:
            target = self.aa_dir / fname
            backup = self.backup_dir / fname
            if not backup.exists():  # 只在第一次替换时备份最原始的文件
                shutil.copy2(target, backup)
            shutil.copy2(analysis.files_map[fname], target)
            # 缓存一份，禁用后再启用不依赖临时解压目录
            shutil.copy2(analysis.files_map[fname], store / fname)
            applied.append(fname)

        state = self._load_state()
        state["mods"][mod_name] = {
            "installed_at": datetime.now().isoformat(timespec="seconds"),
            "files": applied,
            "source": str(Path(mod_dir)),
            "store": str(store),
            "disabled": False,
        }
        self._save_state(state)
        return analysis

    # ---- 还原 ----
    def uninstall_mod(self, name: str) -> int:
        state = self._load_state()
        mod = state["mods"].get(name)
        if not mod:
            return 0
        restored = self._restore_mod_files(mod)
        store = Path(mod.get("store") or self._store_dir(name))
        if store.exists():
            shutil.rmtree(store, ignore_errors=True)
        del state["mods"][name]
        self._save_state(state)
        return restored

    def _restore_mod_files(self, mod: dict) -> int:
        restored = 0
        for fname in mod.get("files", []):
            backup = self.backup_dir / fname
            target = self.aa_dir / fname
            if backup.exists() and target.exists():
                shutil.copy2(backup, target)
                restored += 1
            elif backup.exists():
                shutil.copy2(backup, target)
                restored += 1
        return restored

    def disable_mod(self, name: str) -> int:
        """禁用：把该 mod 改过的文件还原成备份，但保留记录，可再启用。"""
        state = self._load_state()
        mod = state["mods"].get(name)
        if not mod:
            raise RuntimeError(f"未找到已装 mod：{name}")
        if mod.get("disabled"):
            return 0
        restored = self._restore_mod_files(mod)
        mod["disabled"] = True
        state["mods"][name] = mod
        self._save_state(state)
        return restored

    def enable_mod(self, name: str) -> int:
        """启用：从 mod_store 或 source 再拷回游戏目录。"""
        state = self._load_state()
        mod = state["mods"].get(name)
        if not mod:
            raise RuntimeError(f"未找到已装 mod：{name}")
        if not mod.get("disabled"):
            return 0
        store = Path(mod.get("store") or self._store_dir(name))
        source = Path(mod.get("source") or "")
        applied = 0
        for fname in mod.get("files", []):
            src = None
            if (store / fname).exists():
                src = store / fname
            elif source.exists():
                cand = source / fname
                if cand.exists():
                    src = cand
                else:
                    found = list(source.rglob(fname))
                    if found:
                        src = found[0]
            if src is None:
                continue
            target = self.aa_dir / fname
            # 启用前若还没备份，先备份当前（可能是原版）
            backup = self.backup_dir / fname
            if not backup.exists() and target.exists():
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            shutil.copy2(src, target)
            applied += 1
        if applied == 0:
            raise RuntimeError("无法启用：找不到该 mod 的缓存文件（安装来源可能已删除）。请重新安装。")
        mod["disabled"] = False
        state["mods"][name] = mod
        self._save_state(state)
        return applied

    def restore_all(self) -> int:
        """把所有备份过的原文件全部还原（终极还原按钮）。"""
        restored = 0
        for backup in self.backup_dir.glob("*.bundle"):
            target = self.aa_dir / backup.name
            if target.exists():
                shutil.copy2(backup, target)
                restored += 1
        self._save_state({"mods": {}})
        return restored

    def installed_mods(self) -> list[dict]:
        state = self._load_state()
        result = []
        for name, info in state.get("mods", {}).items():
            result.append({
                "name": name,
                "count": len(info.get("files", [])),
                "installed_at": info.get("installed_at", ""),
                "source": info.get("source", ""),
                "disabled": bool(info.get("disabled", False)),
                "store": info.get("store", ""),
            })
        return result

    def is_installed(self, name: str) -> bool:
        return name in self._load_state().get("mods", {})

    # ---- 状态存取 ----
    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"mods": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            data.setdefault("mods", {})
            return data
        except (OSError, json.JSONDecodeError):
            return {"mods": {}}

    def _save_state(self, state: dict) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
