"""本地自检：改完代码后 python selfcheck.py，不要每次靠人手点。"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

errors: list[str] = []


def check(name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        fn()
        print(f"  OK  {name}  ({time.perf_counter() - t0:.3f}s)")
    except Exception as exc:
        print(f" FAIL {name}  ({time.perf_counter() - t0:.3f}s): {exc}")
        traceback.print_exc()
        errors.append(name)


def main() -> int:
    print("=== controller ===")
    from astral_party_auto.mod_controller import MADE_DIR, ModController

    c = ModController(lambda m: None)
    check("has_game", lambda: (_ for _ in ()).throw(AssertionError("no game")) if not c.has_game else None)
    check("index", lambda: (_ for _ in ()).throw(AssertionError("no index")) if not c.index_ready else None)

    def hand():
        rows = c.browse("hand_card", "", 50, asset_type="texture")
        assert rows, "hand empty"
        sel = c.set_selection(*rows[0], asset_type="texture")
        assert Path(sel["preview"]).exists()
        assert Path(sel["preview"]).name.startswith("orig_")

    check("hand browse+preview", hand)

    def chip_label():
        from astral_party_auto.modkit.categories import category_label, ASSET_TYPES

        assert category_label("chip") == "筹码"
        assert "遗物" not in category_label("chip")
        assert [t for t, _ in ASSET_TYPES] == ["texture", "text", "mesh", "anim"]

    check("chip is 筹码 only + type tabs", chip_label)

    def export_types():
        from tempfile import TemporaryDirectory

        from astral_party_auto.modkit.export_assets import export_by_type

        # 贴图走 controller
        rows = c.browse("hand_card", "", 5, asset_type="texture")
        assert rows
        c.set_selection(*rows[0], asset_type="texture")
        with TemporaryDirectory() as td:
            out = c.export_selection(Path(td) / "t.png", fmt="png")
            assert out.exists() and out.stat().st_size > 50
        # 网格 / 动画：直接用已知样例包（不依赖是否已刷新多类型索引）
        if c.aa_dir:
            mesh_b = c.aa_dir / "007f94b0c58c6f4e01ddb09224efbcca.bundle"
            anim_b = c.aa_dir / "014384d605bf10b9bad39dc24ab08425.bundle"
            with TemporaryDirectory() as td:
                td = Path(td)
                if mesh_b.exists():
                    out = export_by_type("mesh", mesh_b, "YuanHuan_33", td / "m.obj")
                    assert out.exists() and "v " in out.read_text(encoding="utf-8")[:200]
                if anim_b.exists():
                    out = export_by_type("anim", anim_b, "Hit", td / "a.json")
                    assert out.exists() and out.stat().st_size > 20
                    raw = export_by_type("anim", anim_b, "Hit", td / "a.animbin")
                    assert raw.exists() and raw.stat().st_size > 10

    check("export texture/mesh/anim", export_types)

    def anim_preview_replace():
        from astral_party_auto.modkit.maker import find_anim_preview_texture
        from tempfile import TemporaryDirectory
        from PIL import Image

        if not c.aa_dir:
            return
        b = c.aa_dir / "014384d605bf10b9bad39dc24ab08425.bundle"
        if not b.exists():
            return
        assert find_anim_preview_texture(b, "Walk") == "Walk-001"
        sel = c.set_selection(b.name, "Walk", asset_type="anim")
        assert sel.get("preview") and Path(sel["preview"]).exists()
        assert sel.get("preview_texture") == "Walk-001"
        with TemporaryDirectory() as td:
            p = Path(td) / "r.png"
            Image.new("RGBA", (sel["width"], sel["height"]), (0, 255, 0, 255)).save(p)
            item = c.add_anim_to_draft(b, "Walk", image_path=p, preview_texture="Walk-001")
            assert item.get("name") == "Walk-001"
        c.clear_draft()

    check("anim first-frame preview+replace", anim_preview_replace)

    def text_not_garbled():
        from astral_party_auto.modkit.maker import is_readable_text_asset, read_text_asset
        import UnityPy

        rows = c.browse("all", "", 20, asset_type="text")
        assert not any(n.endswith("_fui") for _b, n in rows), "fui should be filtered"
        assert rows, "should have readable text"
        t = read_text_asset(c.original_bundle_path(rows[0][0]), rows[0][1])
        assert t.lstrip()[:1] in "{[<\"" or "nodes" in t[:200] or len(t) > 10
        # FGUI not readable
        for bn, names in (c.typed_index.get("text") or {}).items():
            pass
        # find a fui bundle by scanning a known one if present
        aa = c.aa_dir
        if aa:
            hit = None
            for b in aa.glob("*.bundle"):
                if hit:
                    break
                try:
                    env = UnityPy.load(str(b))
                except Exception:
                    continue
                for o in env.objects:
                    if o.type.name != "TextAsset":
                        continue
                    d = o.read()
                    if str(getattr(d, "m_Name", "")).endswith("_fui"):
                        assert not is_readable_text_asset(d)
                        hit = True
                        break
                if hit:
                    break

    check("text filter no fgui garbled", text_not_garbled)

    def caps():
        assert len(c.browse("other", "", 500, asset_type="texture")) <= 200
        assert "__advanced__" not in [x[0] for x in c.categories(include_advanced=False)]

    check("category caps", caps)

    def clear():
        d = MADE_DIR / "_draft"
        d.mkdir(parents=True, exist_ok=True)
        (d / "junk.txt").write_text("x", encoding="utf-8")
        c.clear_draft()
        assert not (d / "junk.txt").exists()
        assert c.draft_items == []

    check("clear_draft", clear)

    print("=== web api ===")

    def web_api():
        from astral_party_auto.web_app import DesktopApi, WEB_DIR

        assert (WEB_DIR / "app.js").exists()
        assert (WEB_DIR / "index.html").exists()
        api = DesktopApi()
        boot = api.bootstrap()
        assert boot["ok"], boot
        rows = api.browse_assets("texture", "hand_card", "")
        assert rows["ok"] and rows["data"]
        sel = api.select_asset("texture", rows["data"][0]["bundle"], rows["data"][0]["name"])
        assert sel["ok"] and sel["data"].get("preview_data")

    check("web DesktopApi", web_api)

    print("=== UI (legacy ctk) ===")
    from astral_party_auto.ui.main_window import MainWindow

    app = MainWindow()
    app.update()

    def wait_for(predicate, timeout: float = 15.0) -> None:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            app.update()
            if predicate():
                return
            time.sleep(0.01)
        raise AssertionError("UI background task timed out")
    check(
        "geom",
        lambda: (_ for _ in ()).throw(AssertionError(app.geometry()))
        if not (
            app.winfo_width() <= 1400
            or "1100x" in app.geometry()
            or "1080x" in app.geometry()
            or "x720" in app.geometry()
            or "x700" in app.geometry()
        )
        else None,
    )
    for p in ("dashboard", "manage", "browse", "studio", "pack", "logs"):
        check(f"page {p}", lambda pg=p: (app.show_page(pg), app.update()))

    def preview_ui():
        app.show_page("browse")
        app.update()
        bp = app.browse_page
        assert hasattr(bp, "type_menu")
        assert list(bp.type_menu.cget("values")) == ["贴图", "文本", "3D模型", "动画"]
        bp.select_asset_type("texture")
        app.update()
        bp.select_category("hand_card")
        app.update()
        assert bp._rows
        bp.select_resource(*bp._rows[0][:2])
        wait_for(lambda: app.controller.selection is not None)
        assert bp.preview_label.cget("image"), "preview image missing"

    check("browse shows image + type dropdown", preview_ui)

    def manage():
        app.show_page("manage")
        app.update()
        mods = app.controller.installed_mods()
        kids = app.manage.list_frame.winfo_children()
        if mods:
            assert kids, "installed not listed"

    check("manage list", manage)

    def switch():
        app.show_page("browse")
        app.update()
        bp = app.browse_page
        for cid in list(bp._cat_rows.keys())[:5]:
            t0 = time.perf_counter()
            bp.select_category(cid)
            app.update()
            assert time.perf_counter() - t0 < 3.0, cid
            if bp._rows:
                b, t = bp._rows[0][0], bp._rows[0][1]
                bp.select_resource(b, t)
                wait_for(lambda: (app.controller.selection or {}).get("bundle") == b)
                if bp._asset_type == "texture":
                    assert bp.preview_label.cget("image")

    check("switch cats+preview", switch)

    app.destroy()
    print()
    if errors:
        print("FAILED:", errors)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
