from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ASTRAL_PARTY_APP_ID = "2622000"


@dataclass(frozen=True)
class GameInstall:
    app_id: str
    name: str
    install_dir: Path
    cn_exe: Path | None
    int_exe: Path | None

    def executable_for_region(self, region: str) -> Path | None:
        normalized = region.strip().upper()
        if normalized == "INT":
            return self.int_exe or self.cn_exe
        return self.cn_exe or self.int_exe


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _acf_value(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', text)
    if not match:
        return None
    return match.group(1)


def _steam_paths_from_registry() -> list[Path]:
    paths: list[Path] = []
    try:
        import winreg
    except ImportError:
        return paths

    keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    ]

    for hive, key_name in keys:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for value_name in ("SteamPath", "InstallPath"):
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if value:
                        paths.append(Path(str(value)))
        except OSError:
            continue

    return paths


def _candidate_steam_roots() -> list[Path]:
    roots: list[Path] = []
    roots.extend(_steam_paths_from_registry())
    roots.extend(
        [
            Path(r"D:\Steam"),
            Path(r"C:\Program Files (x86)\Steam"),
            Path(r"C:\Program Files\Steam"),
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _parse_library_paths(libraryfolders_path: Path) -> list[Path]:
    try:
        text = _read_text(libraryfolders_path)
    except OSError:
        return []

    paths = []
    for raw_path in re.findall(r'"path"\s+"([^"]+)"', text):
        paths.append(Path(raw_path.replace(r"\\", "\\")))
    return paths


def iter_steamapps_dirs() -> Iterable[Path]:
    steamapps: list[Path] = []
    for steam_root in _candidate_steam_roots():
        primary = steam_root / "steamapps"
        if primary.exists():
            steamapps.append(primary)
            for library_root in _parse_library_paths(primary / "libraryfolders.vdf"):
                library_steamapps = library_root / "steamapps"
                if library_steamapps.exists():
                    steamapps.append(library_steamapps)

    seen: set[str] = set()
    for path in steamapps:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        yield path


def find_game_install(app_id: str = ASTRAL_PARTY_APP_ID) -> GameInstall | None:
    for steamapps_dir in iter_steamapps_dirs():
        manifest = steamapps_dir / f"appmanifest_{app_id}.acf"
        if not manifest.exists():
            continue

        text = _read_text(manifest)
        install_dir_name = _acf_value(text, "installdir") or "Astral Party"
        game_name = (_acf_value(text, "name") or "Astral Party").strip()
        install_dir = steamapps_dir / "common" / install_dir_name
        install = _build_install(app_id, game_name, install_dir)
        if install.cn_exe or install.int_exe:
            return install

    # 常见盘符硬探 + 在各 steamapps/common 下找目录名
    for steamapps_dir in iter_steamapps_dirs():
        common = steamapps_dir / "common"
        if not common.exists():
            continue
        for child in common.iterdir():
            if not child.is_dir():
                continue
            name_l = child.name.lower()
            if "astral" not in name_l and "party" not in name_l:
                continue
            install = _build_install(app_id, child.name, child)
            if install.cn_exe or install.int_exe:
                return install

    for known_dir in (
        Path(r"D:\Steam\steamapps\common\Astral Party"),
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Astral Party"),
        Path(r"C:\Steam\steamapps\common\Astral Party"),
        Path(r"E:\Steam\steamapps\common\Astral Party"),
        Path(r"F:\Steam\steamapps\common\Astral Party"),
    ):
        if known_dir.exists():
            install = _build_install(app_id, "Astral Party", known_dir)
            if install.cn_exe or install.int_exe:
                return install

    return None


def _build_install(app_id: str, game_name: str, install_dir: Path) -> GameInstall:
    cn_exe = install_dir / "8vJXn6CN" / "AstralParty_CN.exe"
    int_exe = install_dir / "8vJXnINT" / "AstralParty_INT.exe"
    # 有的安装布局 exe 直接在根下
    if not cn_exe.exists():
        alt = install_dir / "AstralParty_CN.exe"
        if alt.exists():
            cn_exe = alt
    if not int_exe.exists():
        alt = install_dir / "AstralParty_INT.exe"
        if alt.exists():
            int_exe = alt
    return GameInstall(
        app_id=app_id,
        name=game_name,
        install_dir=install_dir,
        cn_exe=cn_exe if cn_exe.exists() else None,
        int_exe=int_exe if int_exe.exists() else None,
    )


def launch_with_steam(app_id: str = ASTRAL_PARTY_APP_ID) -> None:
    os.startfile(f"steam://rungameid/{app_id}")


def launch_direct(executable: Path) -> subprocess.Popen:
    return subprocess.Popen([str(executable)], cwd=str(executable.parent))
