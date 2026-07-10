# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir, windowed (no console)
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH)

def gather(pkg: str):
    try:
        return collect_all(pkg)
    except Exception:
        return [], [], []

datas = [
    (str(ROOT / "astral_party_auto" / "webui"), "astral_party_auto/webui"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "icon.ico"), "."),
    (str(ROOT / "icon.png"), "."),
]
binaries = []
hiddenimports = [
    "astral_party_auto",
    "astral_party_auto.app",
    "astral_party_auto.web_app",
    "astral_party_auto.mod_controller",
    "astral_party_auto.ui.main_window",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "bottle",
    "proxy_tools",
    "clr",
    "clr_loader",
    "pythonnet",
    "windnd",
]

for pkg in (
    "webview",
    "UnityPy",
    "customtkinter",
    "texture2ddecoder",
    "etcpak",
    "astc_encoder",
    "fmod_toolkit",
    "PIL",
    "darkdetect",
):
    d, b, h = gather(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# 保险：整包拷贝 UnityPy（含 resources/lzma.tpk）
import UnityPy as _upy

_upy_root = Path(_upy.__file__).resolve().parent
datas.append((str(_upy_root), "UnityPy"))

hiddenimports += collect_submodules("UnityPy")
hiddenimports = sorted(set(hiddenimports))

a = Analysis(
    [str(ROOT / "launch.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pandas", "matplotlib", "scipy", "IPython", "notebook"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JiXingModHelper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app_icon.ico"),
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="JiXingModHelper",
)
