"""制作替换：按当前选中资源类型换贴图 / 文本 / 动画。"""
from __future__ import annotations

import tempfile
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from ..theme import COLORS, font
from ..widgets import FlowButtonBar, enable_mousewheel, make_button
from .crop_dialog import CropDialog

try:
    import windnd
except ImportError:
    windnd = None  # type: ignore


class StudioPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self.replacement: Path | None = None
        self.crop_box: tuple[int, int, int, int] | None = None
        self._orig_ref = None
        self._repl_ref = None
        self._text_names: list[str] = []
        self._mode = "texture"  # texture | text | anim

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        enable_mousewheel(scroll, step=14)
        self._scroll = scroll

        banner = ctk.CTkFrame(
            scroll, fg_color="#2a1830", corner_radius=12, border_width=1, border_color=COLORS["accent"]
        )
        banner.pack(fill="x", pady=(0, 14))
        self.var_caption = ctk.StringVar(value="还没选资源 — 请先到「浏览资源」选一项")
        ctk.CTkLabel(
            banner,
            textvariable=self.var_caption,
            font=font(15, bold=True),
            text_color=COLORS["accent"],
            wraplength=900,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(12, 4))
        self.var_hint = ctk.StringVar(value="")
        ctk.CTkLabel(
            banner, textvariable=self.var_hint, font=font(12), text_color=COLORS["muted"], wraplength=900, justify="left"
        ).pack(anchor="w", padx=16, pady=(0, 12))

        # —— 贴图 / 动画：双栏图预览 ——
        self.img_block = ctk.CTkFrame(scroll, fg_color="transparent")
        self.img_block.pack(fill="x")
        self.img_block.grid_columnconfigure(0, weight=1)
        self.img_block.grid_columnconfigure(1, weight=1)

        left = ctk.CTkFrame(self.img_block, fg_color=COLORS["card"], corner_radius=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.var_orig_title = ctk.StringVar(value="游戏原图")
        ctk.CTkLabel(left, textvariable=self.var_orig_title, font=font(14, bold=True), text_color=COLORS["text"]).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self.orig_label = ctk.CTkLabel(left, text="—", font=font(12), text_color=COLORS["soft"], height=280)
        self.orig_label.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        right = ctk.CTkFrame(self.img_block, fg_color=COLORS["card"], corner_radius=14)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.var_repl_title = ctk.StringVar(value="你的替换图（可拖入）")
        ctk.CTkLabel(right, textvariable=self.var_repl_title, font=font(14, bold=True), text_color=COLORS["text"]).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self.drop_zone = ctk.CTkFrame(right, fg_color=COLORS["card_soft"], corner_radius=12, height=280)
        self.drop_zone.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        self.drop_zone.pack_propagate(False)
        self.repl_label = ctk.CTkLabel(self.drop_zone, text="拖入图片或点「选图」", font=font(13), text_color=COLORS["soft"])
        self.repl_label.pack(expand=True)
        self.drop_zone.bind("<Button-1>", lambda _e: self.pick_replacement())
        self.repl_label.bind("<Button-1>", lambda _e: self.pick_replacement())

        # —— 文本编辑 ——
        self.text_block = ctk.CTkFrame(scroll, fg_color=COLORS["card"], corner_radius=14)
        ctk.CTkLabel(self.text_block, text="编辑文本", font=font(14, bold=True), text_color=COLORS["text"]).pack(
            anchor="w", padx=16, pady=(14, 6)
        )
        self.text_box = ctk.CTkTextbox(self.text_block, height=280, fg_color=COLORS["input"], font=font(12), wrap="word")
        self.text_box.pack(fill="both", expand=True, padx=16, pady=(0, 12))

        self.actions = FlowButtonBar(scroll, gap=8)
        self.actions.pack(fill="x", pady=14)
        self.actions.add_button(
            "← 回浏览", lambda: self.app.show_page("browse"), kind="ghost", height=40, width=100
        )
        self.btn_pick = self.actions.add_button(
            "选图…", self.pick_replacement, kind="ghost", height=40, width=90
        )
        self.btn_crop = self.actions.add_button(
            "裁剪", self.crop_replacement, kind="ghost", height=40, width=80
        )
        self.btn_anim_raw = self.actions.add_button(
            "选动画字节…", self.pick_anim_raw, kind="ghost", height=40, width=110
        )
        self.actions.add_button(
            "打开作品集 →", lambda: self.app.show_page("pack"), kind="purple", height=40, width=120
        )
        self.add_btn = self.actions.add_button(
            "确认替换并加入作品集", self.confirm_replace, kind="primary", height=40, width=180
        )

        self.var_status = ctk.StringVar(value="")
        ctk.CTkLabel(scroll, textvariable=self.var_status, font=font(12), text_color=COLORS["muted"]).pack(anchor="w")

        # 兼容旧「文本加入」：隐藏副卡，主流程用 text_block
        self._text_menu_legacy = None

        self._hook_drop()

    def _hook_drop(self) -> None:
        if windnd is None:
            return

        def _dropped(files):
            if not files:
                return
            path = files[0]
            if isinstance(path, bytes):
                path = path.decode("gbk", errors="ignore")
            path = str(path).strip("\x00")
            p = Path(path)
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                self.app.after(0, lambda: self._set_replacement(p))
            elif p.suffix.lower() in {".animbin", ".bin"}:
                self.app.after(0, lambda: self._set_anim_raw(p))

        try:
            windnd.hook_dropfiles(self.drop_zone, func=_dropped)
        except Exception:
            pass

    def _hide_all_modes(self) -> None:
        self.img_block.pack_forget()
        self.text_block.pack_forget()
        for button in (self.btn_pick, self.btn_crop, self.btn_anim_raw):
            self.actions.hide(button)

    def _show_mode(self, block: ctk.CTkFrame) -> None:
        block.pack(fill="x", before=self.actions)

    def on_show(self) -> None:
        sel = self.app.controller.selection
        self.replacement = None
        self.crop_box = None
        self._repl_ref = None
        try:
            self.repl_label.configure(image=None, text="拖入图片或点「选图」")
        except Exception:
            pass

        if not sel:
            self.var_caption.set("还没选资源 — 请先到「浏览资源」选一项")
            self.var_hint.set("")
            self.orig_label.configure(image=None, text="—")
            self.add_btn.configure(state="disabled")
            self._hide_all_modes()
            self._show_mode(self.img_block)
            return

        kind = sel.get("asset_type") or sel.get("kind") or "texture"
        self._mode = kind if kind in ("texture", "text", "anim") else "texture"
        self.var_caption.set(sel.get("caption") or "")
        self.var_hint.set(sel.get("category_desc") or sel.get("text_preview") or "")
        self.add_btn.configure(state="normal")
        self._hide_all_modes()

        if self._mode in ("texture", "anim"):
            self._show_mode(self.img_block)
            if self._mode == "anim":
                tex = sel.get("preview_texture") or ""
                self.var_orig_title.set(f"动画预览图（{tex or '无'}）")
                self.var_repl_title.set("替换图（改预览贴图/图集）")
                self.actions.show(self.btn_anim_raw)
                self.var_hint.set(
                    (sel.get("category_desc") or "")
                    + "  ·  选图=换预览贴图；「选动画字节」=用导出的 .animbin 换片段数据。"
                )
            else:
                self.var_orig_title.set("游戏原图")
                self.var_repl_title.set("你的替换图（可拖入）")
            self.btn_pick.configure(text="选图…", command=self.pick_replacement, width=90)
            self.btn_pick._design_width = 90
            self.actions.show(self.btn_pick)
            self.actions.show(self.btn_crop)
            prev = sel.get("preview") or ""
            if prev and Path(prev).exists():
                try:
                    img = Image.open(prev).convert("RGBA")
                    img.thumbnail((320, 320), Image.Resampling.LANCZOS)
                    cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                    self._orig_ref = cimg
                    self.orig_label.configure(image=cimg, text="")
                except Exception:
                    self.orig_label.configure(image=None, text="原图加载失败")
            else:
                self.orig_label.configure(
                    image=None,
                    text="无预览图\n（可用「选动画字节」换数据）" if self._mode == "anim" else "—",
                )

        elif self._mode == "text":
            self._show_mode(self.text_block)
            self.actions.hide(self.btn_pick)
            self.actions.hide(self.btn_crop)
            self.text_box.delete("1.0", "end")
            try:
                base = sel.get("original_path") or sel.get("bundle_path")
                content = self.app.controller.read_text(base, sel["name"])
                self.text_box.insert("1.0", content)
            except Exception as exc:
                self.text_box.insert("1.0", f"（读取失败：{exc}）")
                self.var_status.set(str(exc))

        if hasattr(self._scroll, "rebind_mousewheel"):
            self._scroll.rebind_mousewheel()

    def pick_replacement(self) -> None:
        path = filedialog.askopenfilename(
            title="选择替换图片", filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp")]
        )
        if path:
            self._set_replacement(Path(path))

    def pick_anim_raw(self) -> None:
        path = filedialog.askopenfilename(
            title="选择动画原始字节（.animbin）",
            filetypes=[("动画字节", "*.animbin *.bin"), ("所有文件", "*.*")],
        )
        if path:
            self._set_anim_raw(Path(path))

    def _set_anim_raw(self, path: Path) -> None:
        self.replacement = path
        self.crop_box = None
        self.var_status.set(f"已载入动画字节 {path.name}。点确认将替换 AnimationClip 数据。")
        try:
            self.repl_label.configure(image=None, text=f"动画字节\n{path.name}")
        except Exception:
            pass

    def _set_replacement(self, path: Path) -> None:
        self.replacement = path
        self.crop_box = None
        try:
            img = Image.open(path).convert("RGBA")
            img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._repl_ref = cimg
            self.repl_label.configure(image=cimg, text="")
        except Exception as exc:
            self.app._error("读图失败", str(exc))
            return
        self.var_status.set(f"已载入 {path.name}（仅预览）。点「确认替换并加入作品集」才会写入。")

    def crop_replacement(self) -> None:
        if not self.replacement:
            self.app._error("先选图", "先拖入或选择替换图。")
            return
        if self.replacement.suffix.lower() in {".animbin", ".bin"}:
            self.app._error("不能裁剪", "当前文件不是图片。")
            return
        sel = self.app.controller.selection
        target = (sel["width"], sel["height"]) if sel and sel.get("width") else None
        dlg = CropDialog(self.winfo_toplevel(), self.replacement, target)
        box = dlg.show()
        if not box:
            return
        img = Image.open(self.replacement).convert("RGBA").crop(box)
        tmp = Path(tempfile.gettempdir()) / "ap_crop_preview.png"
        img.save(tmp)
        self.replacement = tmp
        self.crop_box = None
        try:
            preview = img.copy()
            preview.thumbnail((320, 320), Image.Resampling.LANCZOS)
            cimg = ctk.CTkImage(light_image=preview, dark_image=preview, size=preview.size)
            self._repl_ref = cimg
            self.repl_label.configure(image=cimg, text="")
        except Exception:
            pass
        self.var_status.set(
            f"已裁剪为 {box[2] - box[0]}×{box[3] - box[1]}（仅预览）。点「确认替换并加入作品集」写入。"
        )

    def confirm_replace(self) -> None:
        sel = self.app.controller.selection
        if not sel:
            self.app._error("先选资源", "请先到「浏览资源」选择资源。")
            return
        kind = sel.get("asset_type") or sel.get("kind") or "texture"
        base = sel.get("original_path") or sel.get("bundle_path")

        try:
            if kind == "texture":
                if not self.replacement:
                    self.app._error("先选替换图", "拖入或选择你的图片。")
                    return
                self.app.controller.add_texture_to_draft(
                    base, self.replacement, texture_name=sel["name"], crop_box=self.crop_box
                )
            elif kind == "anim":
                if not self.replacement:
                    self.app._error("先选文件", "选一张图替换预览贴图，或选 .animbin 替换动画数据。")
                    return
                suf = self.replacement.suffix.lower()
                if suf in {".animbin", ".bin"}:
                    self.app.controller.add_anim_to_draft(base, sel["name"], raw_path=self.replacement)
                else:
                    self.app.controller.add_anim_to_draft(
                        base,
                        sel["name"],
                        image_path=self.replacement,
                        preview_texture=sel.get("preview_texture") or None,
                        crop_box=self.crop_box,
                    )
            elif kind == "text":
                content = self.text_box.get("1.0", "end-1c")
                self.app.controller.add_text_to_draft(base, sel["name"], content)
            else:
                self.app._error("不支持", f"类型 {kind} 不支持替换。")
                return
        except Exception as exc:
            self.app._error("替换失败", str(exc))
            return

        self.var_status.set("已确认替换并加入作品集。可到「我的作品集」导出或安装。")
        if hasattr(self.app, "pack_page"):
            self.app.pack_page.refresh()

    # 旧接口名兼容
    def add_texture(self) -> None:
        self.confirm_replace()

    def add_text(self) -> None:
        self.confirm_replace()
