"""浏览资源：类型下拉 + 细分类列表 + 列表 + 预览。"""
from __future__ import annotations

import queue
import threading
from pathlib import Path

import customtkinter as ctk
from PIL import Image

from tkinter import filedialog, messagebox

from ...modkit.categories import ASSET_TYPES, dedupe_by_texture_name
from ..theme import COLORS, font
from ..widgets import FlowButtonBar, enable_mousewheel, make_button


PAGE_SIZE = 25

# 下拉显示名 → 内部类型 id
_TYPE_BY_LABEL = {label: tid for tid, label in ASSET_TYPES}
_TYPE_LABELS = [label for _tid, label in ASSET_TYPES]


class BrowsePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._asset_type = "texture"  # texture | text | mesh | anim
        self._cat_id = "hand_card"
        self._query = ""
        self._page = 0
        # (bundle, name, dup_count)
        self._rows: list[tuple[str, str, int]] = []
        self._cat_rows: dict[str, ctk.CTkFrame] = {}
        self._row_pool: list[tuple[ctk.CTkFrame, ctk.CTkLabel]] = []
        self._row_frames: list[ctk.CTkFrame] = []
        self._visible_row_keys: list[tuple[str, str]] = []
        self._preview_requests: queue.Queue[tuple[int, str, str, str]] = queue.Queue()
        self._preview_results: queue.Queue[tuple[int, dict | None, str | None]] = queue.Queue()
        self._preview_request_id = 0
        self._preview_worker = None
        self._selected_key: tuple[str, str] | None = None
        self._preview_ref = None
        self._render_gen = 0
        self._type_menu_lock = False  # 程序改下拉时不触发回调

        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(0, weight=1)

        self._build_cats()
        self._build_list()
        self._build_preview()
        # UnityPy 解包放到单个后台线程；快速连点时只处理队列里最新的一项。
        self._preview_worker = threading.Thread(
            target=self._preview_worker_loop,
            name="bundle-preview",
            daemon=True,
        )
        self._preview_worker.start()
        self.after(40, self._drain_preview_results)

    def _build_cats(self) -> None:
        left = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14, width=176)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        left.grid_propagate(False)
        ctk.CTkLabel(left, text="分类", font=font(16, bold=True), text_color=COLORS["text"]).pack(
            anchor="w", padx=12, pady=(12, 6)
        )

        # 类型：一行下拉（贴图/文本/3D模型/动画）
        self.type_menu = ctk.CTkOptionMenu(
            left,
            values=_TYPE_LABELS,
            command=self._on_type_menu,
            height=32,
            font=font(13),
            dropdown_font=font(12),
            fg_color=COLORS["input"],
            button_color=COLORS["purple"],
            button_hover_color=COLORS["purple_hover"],
            dropdown_fg_color=COLORS["card"],
            dropdown_hover_color=COLORS["card_soft"],
            text_color=COLORS["text"],
            anchor="w",
        )
        self.type_menu.set("贴图")
        self.type_menu.pack(fill="x", padx=10, pady=(0, 4))

        self.var_type_hint = ctk.StringVar(value="")
        ctk.CTkLabel(
            left,
            textvariable=self.var_type_hint,
            font=font(10),
            text_color=COLORS["soft"],
            wraplength=150,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=12, pady=(0, 6), fill="x")

        self.cat_scroll = ctk.CTkScrollableFrame(left, fg_color="transparent", width=152)
        self.cat_scroll.pack(fill="both", expand=True, padx=4, pady=(0, 8))
        enable_mousewheel(self.cat_scroll, step=10)

    def _on_type_menu(self, label: str) -> None:
        if self._type_menu_lock:
            return
        tid = _TYPE_BY_LABEL.get(label, "texture")
        self.select_asset_type(tid)

    def _build_list(self) -> None:
        mid = ctk.CTkFrame(self, fg_color="transparent")
        mid.grid(row=0, column=1, sticky="nsew", padx=4)
        mid.grid_rowconfigure(2, weight=1)
        mid.grid_columnconfigure(0, weight=1)

        bar = ctk.CTkFrame(mid, fg_color=COLORS["card"], corner_radius=12)
        bar.grid(row=0, column=0, sticky="ew")
        self.search_entry = ctk.CTkEntry(
            bar,
            placeholder_text="搜索资源名 / 包名…",
            height=34,
            fg_color=COLORS["input"],
            border_color=COLORS["card_line"],
        )
        self.search_entry.pack(fill="x", padx=10, pady=(8, 4))
        self.search_entry.bind("<Return>", lambda _e: self.do_search())
        self.tool_bar = FlowButtonBar(bar, gap=8)
        self.tool_bar.pack(fill="x", padx=10, pady=(0, 4))
        self.tool_bar.add_button("搜索", self.do_search, kind="ghost", height=34)
        self.index_btn = self.tool_bar.add_button("刷新索引", self.build_index, kind="purple", height=34)

        self.var_status = ctk.StringVar(value="左侧选类型与分类 → 点列表 → 右侧预览")
        ctk.CTkLabel(bar, textvariable=self.var_status, font=font(11), text_color=COLORS["soft"]).pack(
            anchor="w", padx=12, pady=(0, 8)
        )

        page_bar = ctk.CTkFrame(mid, fg_color="transparent")
        page_bar.grid(row=1, column=0, sticky="ew", pady=(6, 2))
        self.var_page = ctk.StringVar(value="")
        ctk.CTkLabel(page_bar, textvariable=self.var_page, font=font(11), text_color=COLORS["muted"]).pack(
            anchor="w"
        )
        self.page_btns = FlowButtonBar(page_bar, gap=6)
        self.page_btns.pack(fill="x", pady=(3, 0))
        self.page_btns.add_button("上一页", lambda: self._flip(-1), kind="ghost", height=28)
        self.page_btns.add_button("下一页", lambda: self._flip(1), kind="ghost", height=28)

        self.list_frame = ctk.CTkScrollableFrame(mid, fg_color=COLORS["card"], corner_radius=12)
        self.list_frame.grid(row=2, column=0, sticky="nsew")
        enable_mousewheel(self.list_frame, step=14)
        self._empty_label = ctk.CTkLabel(
            self.list_frame,
            text="没有匹配。",
            font=font(13),
            text_color=COLORS["soft"],
            anchor="w",
        )

    def _build_preview(self) -> None:
        self._preview_panel = ctk.CTkFrame(self, fg_color=COLORS["card"], corner_radius=14, width=280)
        self._preview_panel.grid(row=0, column=2, sticky="nse", padx=(8, 0))
        self._preview_panel.grid_propagate(False)

        ctk.CTkLabel(self._preview_panel, text="预览", font=font(16, bold=True), text_color=COLORS["text"]).pack(
            anchor="w", padx=14, pady=(12, 4)
        )
        self.var_caption = ctk.StringVar(value="还没选资源")
        ctk.CTkLabel(
            self._preview_panel,
            textvariable=self.var_caption,
            font=font(12, bold=True),
            text_color=COLORS["accent"],
            wraplength=240,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=14, fill="x")
        self.var_desc = ctk.StringVar(value="点中间列表一项")
        ctk.CTkLabel(
            self._preview_panel,
            textvariable=self.var_desc,
            font=font(11),
            text_color=COLORS["muted"],
            wraplength=240,
            justify="left",
            anchor="w",
        ).pack(anchor="w", padx=14, pady=(2, 0), fill="x")

        self._preview_host = ctk.CTkFrame(self._preview_panel, fg_color="transparent", height=260)
        self._preview_host.pack(fill="both", expand=True, padx=12, pady=8)
        self._preview_host.pack_propagate(False)
        self.preview_label = ctk.CTkLabel(
            self._preview_host, text="（选列表项）", font=font(12), text_color=COLORS["soft"]
        )
        self.preview_label.pack(expand=True)

        btns = ctk.CTkFrame(self._preview_panel, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 12), side="bottom")
        self.btn_replace = make_button(btns, "去替换这张 →", self.goto_edit, kind="primary", height=38)
        self.btn_replace.pack(fill="x")
        exp = ctk.CTkFrame(btns, fg_color="transparent")
        exp.pack(fill="x", pady=(6, 0))
        self.btn_export_a = make_button(exp, "导出 PNG", lambda: self.export_asset("a"), kind="ghost", height=32)
        self.btn_export_a.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_export_b = make_button(exp, "导出 JPG", lambda: self.export_asset("b"), kind="ghost", height=32)
        self.btn_export_b.pack(side="left", fill="x", expand=True, padx=(4, 0))
        make_button(btns, "打开作品集", lambda: self.app.show_page("pack"), kind="ghost", height=32).pack(
            fill="x", pady=(6, 0)
        )

    def _resizing(self) -> bool:
        return bool(getattr(self.app, "_resizing", False))

    def on_show(self) -> None:
        try:
            if not self.app.controller.index_ready:
                self.refresh_categories()
                return
            if not self._cat_rows:
                self.refresh_categories()
                return
            if not self._rows:
                self._reload_rows()
            elif not self.list_frame.winfo_children():
                self._render_page()
            sel = self.app.controller.selection
            if sel:
                self.var_caption.set(sel.get("caption", ""))
                self.var_desc.set(sel.get("category_desc", "") or "")
                if sel.get("preview") and Path(sel["preview"]).exists():
                    self._show_preview(sel["preview"])
                elif sel.get("text_preview"):
                    self._show_text_preview(sel["text_preview"])
        except Exception as exc:
            self.var_status.set(f"提示：{exc}")

    def select_asset_type(self, asset_type: str) -> None:
        if asset_type == self._asset_type and self._cat_rows:
            return
        self._asset_type = asset_type
        self._sync_type_menu()
        self._selected_key = None
        self._preview_request_id += 1
        self.app.controller.clear_selection()
        self.var_caption.set("还没选资源")
        self.var_desc.set("点中间列表一项")
        self._reset_preview_placeholder()
        # 贴图默认手牌；其它类型只有「全部」
        self._cat_id = "hand_card" if asset_type == "texture" else "all"
        self.refresh_categories()

    def _sync_type_menu(self) -> None:
        label = next((lb for t, lb in ASSET_TYPES if t == self._asset_type), "贴图")
        self._type_menu_lock = True
        try:
            self.type_menu.set(label)
        except Exception:
            pass
        finally:
            self._type_menu_lock = False
        hints = {
            "texture": "图片资源。走路/攻击的一帧帧图在下面「角色动作帧」。",
            "text": "配置/文案类 TextAsset。",
            "mesh": "3D 三角面模型，不是动画。",
            "anim": "Unity 动画片段（Idle/Walk/Hit）。若列表空，请刷新索引。",
        }
        try:
            self.var_type_hint.set(hints.get(self._asset_type, ""))
        except Exception:
            pass

    def refresh_categories(self) -> None:
        for child in self.cat_scroll.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        self._cat_rows.clear()
        self._sync_type_menu()

        if not self.app.controller.index_ready:
            ctk.CTkLabel(
                self.cat_scroll,
                text="还没有索引\n点「刷新索引」",
                font=font(12),
                text_color=COLORS["soft"],
                justify="left",
                anchor="w",
            ).pack(anchor="w", padx=8, pady=10)
            self._rows = []
            self._clear_list()
            self.var_status.set("请先点「刷新索引」。")
            return

        cats = self.app.controller.categories(
            include_advanced=False, asset_type=self._asset_type
        )
        type_counts = self.app.controller.asset_type_counts()
        # 旧索引缺该类型时提示
        if self._asset_type != "texture" and type_counts.get(self._asset_type, 0) == 0:
            tips = {
                "text": "文本",
                "mesh": "3D模型",
                "anim": "动画片段",
            }
            tip = tips.get(self._asset_type, "此类")
            ctk.CTkLabel(
                self.cat_scroll,
                text=f"还没有「{tip}」数据\n请点上方「刷新索引」\n重新扫描全部资源包",
                font=font(12),
                text_color=COLORS["soft"],
                justify="left",
                anchor="w",
            ).pack(anchor="w", padx=8, pady=10)
            self._rows = []
            self._clear_list()
            self.var_status.set(f"索引里没有{tip}，请刷新索引（动画以前可能没扫进索引）。")
            return

        for cid, label, count in cats:
            if self._asset_type == "texture" and count == 0 and cid not in ("all", "hand_card"):
                continue
            unit = "张" if self._asset_type == "texture" else "条"
            self._add_cat_row(cid, label, count, unit=unit)

        if self._asset_type == "texture":
            prefer = "hand_card" if any(c[0] == "hand_card" and c[2] > 0 for c in cats) else "all"
        else:
            prefer = "all"
        if self._cat_id not in self._cat_rows:
            self._cat_id = prefer if prefer in self._cat_rows else next(iter(self._cat_rows), "all")
        self.select_category(self._cat_id)

    def _add_cat_row(self, cid: str, label: str, count: int, *, unit: str = "张") -> None:
        row = ctk.CTkFrame(self.cat_scroll, fg_color="transparent", corner_radius=10, height=46)
        row.pack(fill="x", pady=1, padx=2)
        row.pack_propagate(False)
        title = ctk.CTkLabel(
            row, text=label, font=font(12, bold=True), text_color=COLORS["text"], anchor="w", justify="left"
        )
        title.pack(anchor="w", padx=10, pady=(5, 0), fill="x")
        sub = ctk.CTkLabel(
            row, text=f"{count} {unit}", font=font(11), text_color=COLORS["soft"], anchor="w", justify="left"
        )
        sub.pack(anchor="w", padx=10, pady=(0, 4), fill="x")

        def on_click(_e=None, c=cid):
            self.select_category(c)

        def on_enter(_e=None, r=row, c=cid):
            if c != self._cat_id:
                r.configure(fg_color="#4a3f66")

        def on_leave(_e=None, r=row, c=cid):
            if c != self._cat_id:
                r.configure(fg_color="transparent")

        for w in (row, title, sub):
            w.bind("<Button-1>", on_click)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
        self._cat_rows[cid] = row

    def _paint_cat_selection(self) -> None:
        for cid, row in self._cat_rows.items():
            on = cid == self._cat_id
            try:
                row.configure(fg_color=COLORS["accent"] if on else "transparent")
                kids = row.winfo_children()
                if len(kids) >= 1:
                    kids[0].configure(text_color="#ffffff" if on else COLORS["text"])
                if len(kids) >= 2:
                    kids[1].configure(text_color="#ffd6e8" if on else COLORS["soft"])
            except Exception:
                pass

    def select_category(self, cat_id: str) -> None:
        self._cat_id = cat_id
        self._page = 0
        self._selected_key = None
        self._preview_request_id += 1
        self.app.controller.clear_selection()
        self.var_caption.set("还没选资源")
        self.var_desc.set("点中间列表一项")
        self._reset_preview_placeholder()
        self._paint_cat_selection()
        self._reload_rows()

    def do_search(self) -> None:
        self._query = self.search_entry.get().strip()
        self._page = 0
        self._reload_rows()

    def _reload_rows(self) -> None:
        if not self.app.controller.index_ready:
            self.var_status.set("请先刷新索引。")
            return
        try:
            lim = 200 if self._cat_id in ("all", "other", "fx", "sprite_anim", "lightmap") else 500
            if self._asset_type != "texture":
                lim = 200
            self.var_status.set("加载中…")
            raw = self.app.controller.browse(
                self._cat_id, self._query, limit=lim * 3, asset_type=self._asset_type
            )
            self._rows = dedupe_by_texture_name(raw)[:lim]
            self._render_page()
        except Exception as exc:
            self.var_status.set(f"加载失败：{exc}")
            self._rows = []

    def _flip(self, delta: int) -> None:
        total_pages = max(1, (len(self._rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        self._page = max(0, min(total_pages - 1, self._page + delta))
        self._render_page()

    def _ensure_row_pool(self) -> None:
        if self._row_pool:
            return
        for index in range(PAGE_SIZE):
            row = ctk.CTkFrame(
                self.list_frame,
                fg_color=COLORS["card_soft"],
                corner_radius=8,
                height=36,
            )
            row.pack_propagate(False)
            label = ctk.CTkLabel(
                row,
                text="",
                font=font(12),
                text_color=COLORS["text"],
                anchor="w",
            )
            label.pack(side="left", fill="x", expand=True, padx=10)
            row.bind("<Button-1>", lambda _event, i=index: self._activate_row(i))
            label.bind("<Button-1>", lambda _event, i=index: self._activate_row(i))
            self._row_pool.append((row, label))

    def _activate_row(self, index: int) -> None:
        if not (0 <= index < len(self._visible_row_keys)):
            return
        bundle_name, asset_name = self._visible_row_keys[index]
        self.select_resource(bundle_name, asset_name)

    def _clear_list(self) -> None:
        try:
            self._empty_label.pack_forget()
        except Exception:
            pass
        for row, _label in self._row_pool:
            row.pack_forget()
        self._row_frames.clear()
        self._visible_row_keys.clear()

    def _render_page(self) -> None:
        self._render_gen += 1
        try:
            self._clear_list()
            total = len(self._rows)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            self._page = min(self._page, total_pages - 1)
            start = self._page * PAGE_SIZE
            chunk = self._rows[start : start + PAGE_SIZE]
            self.var_page.set(f"{total} 条 · 第 {self._page + 1}/{total_pages} 页")
            type_label = next((lb for t, lb in ASSET_TYPES if t == self._asset_type), self._asset_type)
            if self._asset_type != "texture":
                self.var_status.set(f"{type_label} · 已加载 {total} 条（同名已合并）")
            elif self._cat_id == "land":
                self.var_status.set(
                    f"地图格子 · 已按贴图名去重（{total} 个）。Center 等会在多地图包各有一份。"
                )
            elif self._cat_id in ("other", "fx", "lightmap"):
                self.var_status.set(f"少碰类，仅加载 {total} 条。改这些容易出问题。")
            elif self._cat_id == "sprite_anim":
                self.var_status.set(
                    f"角色动作帧 · 一帧一张贴图（{total} 条）。Unity 动画片段请改下拉为「动画」。"
                )
            elif self._cat_id == "event":
                self.var_status.set("事件图 · UT_Event / UT_MapEvent")
            elif self._cat_id == "chip":
                self.var_status.set("筹码 · 局内筹码资源")
            elif self._cat_id == "currency":
                self.var_status.set("货币 · 星币等（不是筹码）")
            elif self._cat_id == "hand_card":
                self.var_status.set("手牌/技能卡（UT_HandCard）")
            else:
                self.var_status.set(f"贴图 · 已加载 {total} 条（同名已合并）")

            if not chunk:
                self._empty_label.pack(anchor="w", padx=12, pady=16)
                return

            self._ensure_row_pool()
            for index, (bundle, tex, dup) in enumerate(chunk):
                selected = self._selected_key == (bundle, tex)
                row, name_label = self._row_pool[index]
                row.configure(fg_color=COLORS["accent"] if selected else COLORS["card_soft"])
                row.pack(fill="x", padx=6, pady=1)
                name_label.configure(
                    text=tex if dup <= 1 else f"{tex}  ×{dup}包",
                    text_color="#ffffff" if selected else COLORS["text"],
                )
                self._row_frames.append(row)
                self._visible_row_keys.append((bundle, tex))

            try:
                self.list_frame._parent_canvas.yview_moveto(0)
            except Exception:
                pass
        except Exception as exc:
            self.var_status.set(f"渲染失败：{exc}")

    def _highlight_rows(self) -> None:
        for i, row in enumerate(self._row_frames):
            if i >= len(self._visible_row_keys):
                break
            selected = self._selected_key == self._visible_row_keys[i]
            try:
                row.configure(fg_color=COLORS["accent"] if selected else COLORS["card_soft"])
                self._row_pool[i][1].configure(text_color="#ffffff" if selected else COLORS["text"])
            except Exception:
                pass

    def select_resource(self, bundle_name: str, asset_name: str) -> None:
        self._preview_request_id += 1
        request_id = self._preview_request_id
        self.app.controller.clear_selection()
        self._selected_key = (bundle_name, asset_name)
        self.var_caption.set("正在加载预览…")
        self.var_desc.set(asset_name)
        self._reset_preview_placeholder("加载中…")
        for button in (self.btn_replace, self.btn_export_a, self.btn_export_b):
            button.configure(state="disabled")
        self._highlight_rows()
        self._preview_requests.put((request_id, bundle_name, asset_name, self._asset_type))

    def _preview_worker_loop(self) -> None:
        while True:
            request = self._preview_requests.get()
            # 排队期间又点了别项时，只保留最新请求。
            while True:
                try:
                    request = self._preview_requests.get_nowait()
                except queue.Empty:
                    break
            request_id, bundle_name, asset_name, asset_type = request
            if request_id != self._preview_request_id:
                continue
            selection = None
            error = None
            try:
                selection = self.app.controller.set_selection(
                    bundle_name,
                    asset_name,
                    asset_type=asset_type,
                )
            except Exception as exc:
                error = str(exc)
            if request_id != self._preview_request_id:
                if selection is not None and self.app.controller.selection is selection:
                    self.app.controller.clear_selection()
                continue
            self._preview_results.put((request_id, selection, error))

    def _drain_preview_results(self) -> None:
        latest = None
        while True:
            try:
                result = self._preview_results.get_nowait()
            except queue.Empty:
                break
            if result[0] == self._preview_request_id:
                latest = result

        if latest is not None:
            _request_id, selection, error = latest
            if error or selection is None:
                self.var_caption.set("预览失败")
                self.var_desc.set(error or "没有可预览内容")
                self._reset_preview_placeholder((error or "预览失败")[:40])
            else:
                self._apply_selection(selection)

        try:
            if self.winfo_exists():
                self.after(40, self._drain_preview_results)
        except Exception:
            pass

    def _apply_selection(self, selection: dict) -> None:
        self.var_caption.set(selection["caption"])
        self.var_desc.set(selection.get("category_desc") or "")
        kind = selection.get("asset_type") or selection.get("kind") or "texture"
        # 贴图、动画（有第一帧预览图）走图片预览
        if kind in ("texture", "anim") and selection.get("preview"):
            ok = self._show_preview(selection["preview"])
            if not ok:
                self.var_status.set("预览图显示失败，请再点一次或换一项")
            elif kind == "anim" and selection.get("preview_texture"):
                self.var_status.set(f"动画预览：同包贴图 {selection['preview_texture']}（第一帧/图集）")
        else:
            self._show_text_preview(selection.get("text_preview") or selection.get("category_desc") or "")
        self._set_action_buttons(kind)
        self._highlight_rows()

    def _set_action_buttons(self, kind: str) -> None:
        """按资源类型切换替换/导出。3D 模型仅导出；其余可替换。"""
        try:
            if kind == "texture":
                self.btn_replace.configure(text="去替换这张 →", state="normal")
                self.btn_export_a.configure(text="导出 PNG", state="normal")
                self.btn_export_b.configure(text="导出 JPG", state="normal")
            elif kind == "text":
                self.btn_replace.configure(text="去编辑替换 →", state="normal")
                self.btn_export_a.configure(text="导出文本", state="normal")
                self.btn_export_b.configure(text="导出", state="normal")
            elif kind == "mesh":
                self.btn_replace.configure(text="3D模型不替换", state="disabled")
                self.btn_export_a.configure(text="导出 OBJ", state="normal")
                self.btn_export_b.configure(text="导出", state="normal")
            elif kind == "anim":
                self.btn_replace.configure(text="去替换动画 →", state="normal")
                self.btn_export_a.configure(text="导出 JSON", state="normal")
                self.btn_export_b.configure(text="导出二进制", state="normal")
            else:
                self.btn_replace.configure(text="去替换 →", state="normal")
                self.btn_export_a.configure(text="导出", state="normal")
                self.btn_export_b.configure(text="导出", state="normal")
        except Exception:
            pass

    def _reset_preview_placeholder(self, text: str = "（选列表项）") -> None:
        self._preview_ref = None
        try:
            for w in list(self._preview_host.winfo_children()):
                w.destroy()
        except Exception:
            pass
        self.preview_label = ctk.CTkLabel(
            self._preview_host, text=text, font=font(12), text_color=COLORS["soft"]
        )
        self.preview_label.pack(expand=True)

    def _show_text_preview(self, text: str) -> None:
        self._preview_ref = None
        try:
            for w in list(self._preview_host.winfo_children()):
                w.destroy()
        except Exception:
            pass
        box = ctk.CTkTextbox(
            self._preview_host,
            font=font(11),
            fg_color=COLORS.get("input", "#2a2438"),
            text_color=COLORS["text"],
            wrap="word",
            activate_scrollbars=True,
        )
        box.pack(fill="both", expand=True)
        box.insert("1.0", text or "（无内容）")
        box.configure(state="disabled")
        self.preview_label = box  # type: ignore[assignment]

    def _show_preview(self, path) -> bool:
        """重建 Label 再贴图，避免 CTk pyimage 失效后永远空白。"""
        try:
            p = Path(path)
            if not p.exists():
                self._reset_preview_placeholder("文件不存在")
                return False
            img = Image.open(p).convert("RGBA")
            img.load()
            img.thumbnail((280, 280), Image.Resampling.LANCZOS)
            if img.width < 1 or img.height < 1:
                self._reset_preview_placeholder("图片无效")
                return False
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
            self._preview_ref = cimg
            for w in list(self._preview_host.winfo_children()):
                try:
                    w.destroy()
                except Exception:
                    pass
            self.preview_label = ctk.CTkLabel(self._preview_host, text="", image=cimg)
            self.preview_label.pack(expand=True)
            return True
        except Exception as exc:
            self._reset_preview_placeholder("预览失败")
            self.var_status.set(f"预览失败：{exc}")
            return False

    def goto_edit(self) -> None:
        sel = self.app.controller.selection
        if not sel:
            self.app._error("先选资源", "在列表里点一项。")
            return
        kind = sel.get("asset_type") or sel.get("kind") or "texture"
        if kind == "mesh":
            self.app._error("3D模型", "3D 模型只支持导出 OBJ，不做替换。")
            return
        # 贴图 / 文本 / 动画 → 制作页
        self.app.show_page("studio")

    def export_asset(self, mode: str = "a") -> None:
        """导出当前选中资源。mode: a=主格式 / b=副格式（贴图 JPG、动画二进制）。"""
        sel = self.app.controller.selection
        if not sel:
            self.app._error("先选资源", "在列表里点一项再导出。")
            return
        kind = sel.get("asset_type") or sel.get("kind") or "texture"
        name = sel.get("name") or "asset"
        slot = "b" if str(mode).lower() in ("b", "jpg", "jpeg", "bin", "animbin", "binary") else "a"

        if kind == "texture":
            fmt = "jpg" if slot == "b" else "png"
            default = f"{name}.{fmt}"
            filetypes = [
                ("PNG 图片", "*.png"),
                ("JPEG 图片", "*.jpg;*.jpeg"),
                ("所有文件", "*.*"),
            ]
            defext = f".{fmt}"
            title = f"导出贴图 {fmt.upper()}"
        elif kind == "text":
            fmt = None
            default = f"{name}.txt"
            filetypes = [("文本", "*.txt"), ("二进制", "*.bytes"), ("所有文件", "*.*")]
            defext = ".txt"
            title = "导出文本"
        elif kind == "mesh":
            fmt = None
            default = f"{name}.obj"
            filetypes = [("OBJ 模型", "*.obj"), ("所有文件", "*.*")]
            defext = ".obj"
            title = "导出 3D 模型 OBJ"
        elif kind == "anim":
            if slot == "b":
                fmt = "animbin"
                default = f"{name}.animbin"
                filetypes = [("动画原始字节", "*.animbin"), ("所有文件", "*.*")]
                defext = ".animbin"
                title = "导出动画二进制"
            else:
                fmt = "json"
                default = f"{name}.json"
                filetypes = [("JSON 摘要", "*.json"), ("所有文件", "*.*")]
                defext = ".json"
                title = "导出动画 JSON"
        else:
            fmt = None
            default = self.app.controller.default_export_filename()
            filetypes = [("所有文件", "*.*")]
            defext = Path(default).suffix or ".bin"
            title = "导出资源"

        path = filedialog.asksaveasfilename(
            title=title,
            defaultextension=defext,
            initialfile=default,
            filetypes=filetypes,
        )
        if not path:
            return
        try:
            if kind == "texture":
                out = self.app.controller.export_selection(path, fmt=fmt)
            elif kind == "anim" and fmt == "animbin":
                p = Path(path)
                if p.suffix.lower() != ".animbin":
                    p = p.with_suffix(".animbin")
                out = self.app.controller.export_selection(p)
            else:
                out = self.app.controller.export_selection(path)
        except Exception as exc:
            self.app._error("导出失败", str(exc))
            return
        messagebox.showinfo("导出完成", f"已保存：\n{out}")
        self.var_status.set(f"已导出 {out.name}")

    def export_image(self, fmt: str = "png") -> None:
        """兼容旧调用。"""
        self.export_asset("b" if str(fmt).lower() in ("jpg", "jpeg") else "a")

    def build_index(self) -> None:
        if not self.app.controller.has_game:
            self.app._error("没有游戏", "没有检测到游戏资源目录。")
            return
        self.index_btn.configure(state="disabled")
        self.var_status.set("正在扫描资源包（贴图/文本/3D模型/动画）…")

        def progress(done, total):
            self.app.after(0, lambda: self.var_status.set(f"建索引… {done}/{total}"))

        def on_done(count):
            def ui():
                counts = self.app.controller.asset_type_counts()
                parts = [
                    f"贴图{counts.get('texture', 0)}",
                    f"文本{counts.get('text', 0)}",
                    f"3D模型{counts.get('mesh', 0)}",
                    f"动画{counts.get('anim', 0)}",
                ]
                self.var_status.set(f"索引完成：{count} 个资源包 · " + " / ".join(parts))
                self.index_btn.configure(state="normal")
                self.refresh_categories()

            self.app.after(0, ui)

        self.app.controller.build_index_async(progress, on_done)
