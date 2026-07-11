"""我的作品集：点选、预览对比、换图、导出、安装。"""
from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from ...mod_controller import MADE_DIR
from ..theme import COLORS, font
from ..widgets import FlowButtonBar
from .crop_dialog import CropDialog


class PackPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._selected = -1
        self._orig_ref = None
        self._mod_ref = None
        self._item_btns: list[ctk.CTkFrame] = []

        self.grid_columnconfigure(0, weight=1, minsize=220)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(1, weight=1)

        # 顶栏：标题 + 数量，提示单独一行避免挤成一团
        head = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14)
        head.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        top = ctk.CTkFrame(head, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(top, text="我的作品集", font=font(18, bold=True), text_color=COLORS["accent"]).pack(side="left")
        self.var_count = ctk.StringVar(value="0 项")
        ctk.CTkLabel(top, textvariable=self.var_count, font=font(14, bold=True), text_color=COLORS["text"]).pack(
            side="left", padx=(10, 0)
        )
        name_row = ctk.CTkFrame(top, fg_color="transparent")
        name_row.pack(side="right")
        ctk.CTkLabel(name_row, text="套装名", font=font(12), text_color=COLORS["muted"]).pack(side="left")
        self.pack_name = ctk.CTkEntry(
            name_row, width=160, height=32, fg_color=COLORS["input"], border_color=COLORS["card_line"]
        )
        self.pack_name.pack(side="left", padx=6)
        self.pack_name.insert(0, self.app.controller.draft_name)
        self.pack_name.bind("<FocusOut>", lambda _e: self._sync_name())

        self.var_hint = ctk.StringVar(value="在左侧点选一项，可预览、换图或导出 ZIP。")
        ctk.CTkLabel(
            head,
            textvariable=self.var_hint,
            font=font(12),
            text_color=COLORS["muted"],
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=16, pady=(0, 12))

        # 左：普通 Frame + 内部按需滚动（条目少时不出现空白滚动手感）
        left = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.grid_rowconfigure(0, weight=1)
        left.grid_columnconfigure(0, weight=1)
        self.list_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self.list_scroll.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.list_frame = self.list_scroll  # 子项挂这里
        # 不默认 enable_mousewheel；在 refresh 后按内容高度决定

        # 右详情
        right = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14)
        right.grid(row=1, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_columnconfigure(1, weight=1)
        right.grid_rowconfigure(2, weight=1)

        self.var_detail = ctk.StringVar(value="尚未选择")
        ctk.CTkLabel(
            right,
            textvariable=self.var_detail,
            font=font(14, bold=True),
            text_color=COLORS["text"],
            wraplength=480,
            justify="left",
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 6))

        ctk.CTkLabel(right, text="游戏原图", font=font(12, bold=True), text_color=COLORS["muted"], anchor="w").grid(
            row=1, column=0, sticky="w", padx=16
        )
        ctk.CTkLabel(right, text="你的替换图", font=font(12, bold=True), text_color=COLORS["muted"], anchor="w").grid(
            row=1, column=1, sticky="w", padx=16
        )

        self._orig_host = ctk.CTkFrame(right, fg_color=COLORS["card_soft"], corner_radius=10, height=240)
        self._orig_host.grid(row=2, column=0, sticky="nsew", padx=(16, 8), pady=8)
        self._orig_host.grid_propagate(False)
        self.orig_label = ctk.CTkLabel(self._orig_host, text="—", font=font(12), text_color=COLORS["soft"])
        self.orig_label.pack(expand=True)

        self._mod_host = ctk.CTkFrame(right, fg_color=COLORS["card_soft"], corner_radius=10, height=240)
        self._mod_host.grid(row=2, column=1, sticky="nsew", padx=(8, 16), pady=8)
        self._mod_host.grid_propagate(False)
        self.mod_label = ctk.CTkLabel(self._mod_host, text="—", font=font(12), text_color=COLORS["soft"])
        self.mod_label.pack(expand=True)

        ops = FlowButtonBar(right, gap=8)
        ops.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 4))
        ops.add_button("换图…", self.replace_image, kind="primary", height=36)
        ops.add_button("裁剪换图", self.crop_replace, kind="ghost", height=36)
        ops.add_button("移除这项", self.remove_selected, kind="danger", height=36)

        bottom = FlowButtonBar(right, gap=8)
        bottom.grid(row=4, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 14))
        bottom.add_button("导出 ZIP 分享", self.export_zip, kind="primary", height=40)
        bottom.add_button("安装到游戏", self.install_draft, kind="purple", height=40)
        bottom.add_button("打开导出目录", self.open_made, kind="ghost", height=40)
        bottom.add_button("清空全部", self.clear_all, kind="ghost", height=40)


    def on_show(self) -> None:
        self.refresh()

    def _unbind_list_wheel(self) -> None:
        """内容装得下时禁止滚轮，避免空白区域还能往上滚。"""
        try:
            canvas = self.list_scroll._parent_canvas
            canvas.unbind_all("<MouseWheel>")
            # 只解绑本 canvas，避免影响其它页：用局部 bind
            canvas.unbind("<MouseWheel>")
            canvas.unbind("<Button-4>")
            canvas.unbind("<Button-5>")
            for w in (self.list_scroll, canvas):
                try:
                    w.unbind("<MouseWheel>")
                except Exception:
                    pass
            # 钉在顶部
            canvas.yview_moveto(0)
            # 若内容高度小于可视区，把 scrollregion 收紧
            self.list_scroll.update_idletasks()
            bbox = canvas.bbox("all")
            if bbox:
                content_h = bbox[3] - bbox[1]
                view_h = canvas.winfo_height()
                if content_h <= view_h + 2:
                    canvas.configure(scrollregion=(0, 0, bbox[2], view_h))
                    canvas.yview_moveto(0)
        except Exception:
            pass

    def _bind_list_wheel_if_needed(self) -> None:
        try:
            canvas = self.list_scroll._parent_canvas
            self.list_scroll.update_idletasks()
            bbox = canvas.bbox("all")
            if not bbox:
                self._unbind_list_wheel()
                return
            content_h = bbox[3] - bbox[1]
            view_h = max(canvas.winfo_height(), 1)
            if content_h <= view_h + 4:
                self._unbind_list_wheel()
                return

            def on_wheel(event):
                delta = getattr(event, "delta", 0) or 0
                if not delta:
                    return
                units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
                canvas.yview_scroll(units * 3, "units")
                return "break"

            canvas.bind("<MouseWheel>", on_wheel)
            self.list_scroll.bind("<MouseWheel>", on_wheel)
        except Exception:
            pass

    def refresh(self) -> None:
        for child in list(self.list_frame.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        self._item_btns.clear()
        items = self.app.controller.draft_items
        self.var_count.set(f"{len(items)} 项")
        if self.pack_name.get() != self.app.controller.draft_name:
            self.pack_name.delete(0, "end")
            self.pack_name.insert(0, self.app.controller.draft_name)

        if not items:
            self.var_hint.set("作品集为空。到「浏览资源」选图，再在「制作替换」加入。")
            ctk.CTkLabel(
                self.list_frame,
                text="还没有项目",
                font=font(13, bold=True),
                text_color=COLORS["muted"],
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(16, 4))
            ctk.CTkLabel(
                self.list_frame,
                text="浏览资源 → 制作替换 → 加入作品集",
                font=font(12),
                text_color=COLORS["soft"],
                anchor="w",
            ).pack(anchor="w", padx=12, pady=(0, 16))
            self._selected = -1
            self.var_detail.set("尚未选择")
            self._put_label(self._orig_host, "—", "_orig_ref")
            self._put_label(self._mod_host, "—", "_mod_ref")
            self.after(50, self._unbind_list_wheel)
            return

        self.var_hint.set("点左侧一项可预览对比；可换图、导出 ZIP 或安装到游戏。")
        if self._selected < 0 or self._selected >= len(items):
            self._selected = 0
        for i, item in enumerate(items):
            selected = i == self._selected
            row = ctk.CTkFrame(
                self.list_frame,
                fg_color=COLORS["accent"] if selected else COLORS["card_soft"],
                corner_radius=10,
                height=48,
            )
            row.pack(fill="x", pady=3, padx=4)
            row.pack_propagate(False)
            kind = "图" if item.get("kind") == "texture" else "文"
            title = f"[{kind}] {item.get('name', '')}"
            note = str(item.get("note") or "")
            lab = ctk.CTkLabel(
                row,
                text=title if not note else f"{title}\n{note}",
                font=font(12),
                text_color="#ffffff" if selected else COLORS["text"],
                anchor="w",
                justify="left",
            )
            lab.pack(side="left", fill="both", expand=True, padx=12, pady=6)
            for w in (row, lab):
                w.bind("<Button-1>", lambda _e, idx=i: self.select_item(idx))
            self._item_btns.append(row)
        self.select_item(self._selected)
        self.after(80, self._bind_list_wheel_if_needed)

    def select_item(self, index: int) -> None:
        items = self.app.controller.draft_items
        if not (0 <= index < len(items)):
            return
        self._selected = index
        item = items[index]
        kind = "贴图" if item.get("kind") == "texture" else "文本"
        bname = str(item.get("bundle", ""))
        short = (bname[:14] + "…") if len(bname) > 14 else bname
        self.var_detail.set(f"{kind}  ·  {item.get('name')}  ·  {short}")
        for i, row in enumerate(self._item_btns):
            try:
                on = i == index
                row.configure(fg_color=COLORS["accent"] if on else COLORS["card_soft"])
                kids = row.winfo_children()
                if kids:
                    kids[0].configure(text_color="#ffffff" if on else COLORS["text"])
            except Exception:
                pass
        if item.get("kind") != "texture":
            self._put_label(self._orig_host, "文本项无图预览", "_orig_ref")
            self._put_label(self._mod_host, "文本项无图预览", "_mod_ref")
            return
        orig, modded = self.app.controller.draft_preview_paths(index)
        self._set_img(self._orig_host, orig, "_orig_ref")
        self._set_img(self._mod_host, modded, "_mod_ref")

    def _put_label(self, host, text: str, attr: str) -> None:
        setattr(self, attr, None)
        for w in list(host.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        lab = ctk.CTkLabel(host, text=text, font=font(12), text_color=COLORS["soft"])
        lab.pack(expand=True)
        if attr == "_orig_ref":
            self.orig_label = lab
        else:
            self.mod_label = lab

    def _set_img(self, host, path, attr: str) -> None:
        if not path or not Path(path).exists():
            self._put_label(host, "暂无预览", attr)
            return
        try:
            img = Image.open(path).convert("RGBA")
            img.load()
            img.thumbnail((240, 240), Image.Resampling.LANCZOS)
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            setattr(self, attr, cimg)
            for w in list(host.winfo_children()):
                try:
                    w.destroy()
                except Exception:
                    pass
            lab = ctk.CTkLabel(host, text="", image=cimg)
            lab.pack(expand=True)
            if attr == "_orig_ref":
                self.orig_label = lab
            else:
                self.mod_label = lab
        except Exception:
            self._put_label(host, "加载失败", attr)

    def _sync_name(self) -> None:
        self.app.controller.set_draft_name(self.pack_name.get())

    def replace_image(self) -> None:
        if self._selected < 0:
            self.app._error("先选一项", "在左侧点选作品集里的一项。")
            return
        path = filedialog.askopenfilename(title="换图", filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path:
            return
        try:
            self.app.controller.update_draft_texture(self._selected, path)
        except Exception as exc:
            self.app._error("更新失败", str(exc))
            return
        self.refresh()

    def crop_replace(self) -> None:
        if self._selected < 0:
            self.app._error("先选一项", "在左侧点选作品集里的一项。")
            return
        path = filedialog.askopenfilename(title="选图并裁剪", filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if not path:
            return
        item = self.app.controller.draft_items[self._selected]
        target = None
        bp = self.app.controller.bundle_path(item.get("bundle", ""))
        if bp:
            try:
                _, info = self.app.controller.preview_bundle(bp, item.get("name"), tag="orig")
                if info:
                    target = (info.width, info.height)
            except Exception:
                pass
        dlg = CropDialog(self.winfo_toplevel(), path, target)
        box = dlg.show()
        if not box:
            return
        try:
            self.app.controller.update_draft_texture(self._selected, path, crop_box=box)
        except Exception as exc:
            self.app._error("更新失败", str(exc))
            return
        self.refresh()

    def remove_selected(self) -> None:
        if self._selected < 0:
            return
        self.app.controller.remove_draft_item(self._selected)
        self._selected = min(self._selected, len(self.app.controller.draft_items) - 1)
        self.refresh()

    def clear_all(self) -> None:
        if self.app.controller.draft_items:
            if not messagebox.askyesno("清空作品集", "确定清空全部？"):
                return
        self.app.controller.clear_draft()
        self._selected = -1
        self.refresh()
        if hasattr(self.app, "_refresh_pack_badge"):
            self.app._refresh_pack_badge()

    def export_zip(self) -> None:
        self._sync_name()
        try:
            path = self.app.controller.export_draft(as_zip=True)
        except Exception as exc:
            self.app._error("导出失败", str(exc))
            return
        messagebox.showinfo("导出完成", f"已生成：\n{path}\n\n别人用「Mod 管理」选这个 zip 安装。")
        try:
            os.startfile(str(path.parent))
        except Exception:
            pass

    def install_draft(self) -> None:
        self._sync_name()
        if not messagebox.askyesno(
            "安装到游戏", f"把作品集「{self.app.controller.draft_name}」装进游戏？\n会先备份原文件。"
        ):
            return
        try:
            self.app.controller.install_draft()
        except Exception as exc:
            self.app._error("安装失败", str(exc))
            return
        self.app.refresh_ui_state()
        messagebox.showinfo("完成", "已安装。进游戏看看效果；不满意可一键全还原。")

    def open_made(self) -> None:
        MADE_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(MADE_DIR))
