"""角色/怪物名单读取。"""
from __future__ import annotations

import csv
from pathlib import Path

from .config import APP_ROOT, RESOURCE_ROOT

CHARACTER_CSV_NAME = "角色表.csv"


def _candidate_paths() -> list[Path]:
    return [
        APP_ROOT / CHARACTER_CSV_NAME,
        RESOURCE_ROOT / CHARACTER_CSV_NAME,
        Path(__file__).resolve().parents[2] / CHARACTER_CSV_NAME,
    ]


def load_character_list() -> list[str]:
    """从根目录 角色表.csv 读取角色/怪物名，返回去重后的列表。"""
    for path in _candidate_paths():
        if not path.exists():
            continue
        for encoding in ("utf-8-sig", "gb18030", "gbk"):
            try:
                with path.open(encoding=encoding, newline="") as f:
                    reader = csv.reader(f)
                    names: list[str] = []
                    seen: set[str] = set()
                    for row in reader:
                        for cell in row:
                            name = (cell or "").strip()
                            if name and name not in seen:
                                seen.add(name)
                                names.append(name)
                    if names:
                        return names
            except (OSError, csv.Error, UnicodeDecodeError):
                continue
    return []
