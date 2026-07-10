from __future__ import annotations

from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk
from PIL import Image

from ...mod_controller import DATA_DIR
from ..theme import COLORS, font
from ..widgets import Card, enable_mousewheel, make_button


class ManagePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app
        self._pending = None
        self._preview_root: Path | None = None  # 当前预览用的目录（待装 / 已装缓存）
        self._preview_files: dict[str, Path] = {}
        self._preview_ref = None
        self._selected_fname: str | None = None

        self.page = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.page.pack(fill="both", expand=True)
        enable_mousewheel(self.page, step=12)

        install = Card(
            self.page,
            "安装 Mod",
            "选文件夹或 .zip/.rar。安装前可在下方预览；装好后点「已装」里的「预览」继续查看。",
            wrap=780,
        )
        install.pack(fill="x")
        row = ctk.CTkFrame(install.body, fg_color="transparent")
        row.pack(fill="x")
        make_button(row, "选 Mod 文件夹", self.pick_folder, kind="ghost").pack(side="left")
        make_button(row, "选压缩包 (.zip/.rar)", self.pick_archive, kind="ghost").pack(side="left", padx=8)
        self.install_btn = make_button(row, "确认安装", self.do_install, kind="primary")
        self.install_btn.pack(side="left", padx=8)
        self.install_btn.configure(state="disabled")
        self.var_analysis = ctk.StringVar(value="还没选 mod。")
        ctk.CTkLabel(
            install.body,
            textvariable=self.var_analysis,
            font=font(13),
            text_color=COLORS["muted"],
            justify="left",
            anchor="w",
            wraplength=760,
        ).pack(anchor="w", pady=(12, 0))

        preview_card = Card(self.page, "Mod 预览（可点选资源包看图）", wrap=780)
        preview_card.pack(fill="x", pady=(12, 0))
        body = ctk.CTkFrame(preview_card.body, fg_color="transparent")
        body.pack(fill="x")
        body.grid_columnconfigure(0, weight=1)
        self.mod_list = ctk.CTkScrollableFrame(body, fg_color=COLORS["card_soft"], height=140, corner_radius=10)
        self.mod_list.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        enable_mousewheel(self.mod_list, step=10)
        right = ctk.CTkFrame(body, fg_color="transparent", width=220)
        right.grid(row=0, column=1, sticky="ns")
        self.var_mod_cap = ctk.StringVar(value="选左侧一项看图")
        ctk.CTkLabel(
            right, textvariable=self.var_mod_cap, font=font(11), text_color=COLORS["muted"], wraplength=200, justify="left"
        ).pack(anchor="w")
        self._preview_host = ctk.CTkFrame(right, fg_color="transparent", height=140)
        self._preview_host.pack(fill="x", pady=6)
        self._preview_host.pack_propagate(False)
        self.mod_preview = ctk.CTkLabel(self._preview_host, text="—", font=font(12), text_color=COLORS["soft"])
        self.mod_preview.pack(expand=True)

        listed = Card(self.page, "已装 Mod", "可禁用（还原原皮但保留记录）、启用、卸载。点「预览」查看该 mod 里的图。", wrap=780)
        listed.pack(fill="x", pady=(12, 16))
        toolbar = ctk.CTkFrame(listed.body, fg_color="transparent")
        toolbar.pack(fill="x")
        self.var_installed_count = ctk.StringVar(value="")
        ctk.CTkLabel(toolbar, textvariable=self.var_installed_count, font=font(12), text_color=COLORS["muted"]).pack(
            side="left"
        )
        make_button(toolbar, "一键全还原", self.app.restore_all, kind="danger", height=34).pack(side="right")
        self.list_frame = ctk.CTkFrame(listed.body, fg_color="transparent")
        self.list_frame.pack(fill="x", pady=(10, 0))
        self._fill_mod_preview_list()

    def pick_folder(self) -> None:
        path = filedialog.askdirectory(title="选择 mod 文件夹")
        if path:
            self._prepare(path)

    def pick_archive(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 mod 压缩包",
            filetypes=[("Mod 压缩包", "*.zip *.rar"), ("所有文件", "*.*")],
        )
        if path:
            self._prepare(path)

    def _prepare(self, path: str) -> None:
        try:
            # analyze 内部会解压，目录在 analysis.mod_dir
            analysis = self.app.controller.analyze(path)
        except Exception as exc:
            self.app._error("分析失败", str(exc))
            return
        self._pending = path
        self._preview_root = Path(analysis.mod_dir)
        self._preview_files = dict(analysis.files_map)
        self.var_analysis.set(
            f"「{Path(path).stem if Path(path).is_file() else Path(path).name}」"
            f"共 {analysis.total} 个资源包：能装 {len(analysis.matched)} 个，"
            f"版本不符 {len(analysis.unmatched)} 个。"
            + ("" if analysis.matched else "  ← 一个都对不上，可能是旧版本的 mod。")
        )
        self.install_btn.configure(state="normal" if analysis.matched else "disabled")
        # 预览优先 matched
        if analysis.matched:
            self._preview_files = {n: analysis.files_map[n] for n in analysis.matched if n in analysis.files_map}
        self._fill_mod_preview_list()

    def _fill_mod_preview_list(self) -> None:
        for child in list(self.mod_list.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        self._set_preview_image(None)
        self.var_mod_cap.set("选左侧一项看图")
        self._selected_fname = None

        if not self._preview_files:
            ctk.CTkLabel(
                self.mod_list, text="先选 mod 包，或点下方已装的「预览」。", font=font(12), text_color=COLORS["soft"]
            ).pack(anchor="w", padx=8, pady=8)
            return

        names = sorted(self._preview_files.keys())
        for fname in names[:100]:
            row = ctk.CTkFrame(self.mod_list, fg_color="transparent", corner_radius=8, height=30)
            row.pack(fill="x", pady=1, padx=4)
            row.pack_propagate(False)
            lab = ctk.CTkLabel(
                row,
                text=fname[:36] + ("…" if len(fname) > 36 else ""),
                font=font(11),
                text_color=COLORS["muted"],
                anchor="w",
            )
            lab.pack(side="left", fill="x", expand=True, padx=8)

            def on_click(_e=None, f=fname, r=row):
                self._select_preview_item(f, r)

            row.bind("<Button-1>", on_click)
            lab.bind("<Button-1>", on_click)
            row.bind("<Enter>", lambda _e, r=row: r.configure(fg_color="#4a3f66"))
            row.bind("<Leave>", lambda _e, r=row, f=fname: r.configure(
                fg_color=COLORS["accent"] if f == self._selected_fname else "transparent"
            ))

    def _select_preview_item(self, bundle_name: str, row_widget=None) -> None:
        self._selected_fname = bundle_name
        # 高亮
        for child in self.mod_list.winfo_children():
            try:
                child.configure(fg_color="transparent")
            except Exception:
                pass
        if row_widget is not None:
            try:
                row_widget.configure(fg_color=COLORS["accent"])
            except Exception:
                pass
        self._preview_mod_file(bundle_name)

    def _preview_mod_file(self, bundle_name: str) -> None:
        path = self._preview_files.get(bundle_name)
        if path is None or not Path(path).exists():
            # 已装：从 store 找
            if self._preview_root:
                cand = self._preview_root / bundle_name
                if cand.exists():
                    path = cand
        if not path or not Path(path).exists():
            self.var_mod_cap.set("找不到该资源包文件")
            self._set_preview_image(None)
            return
        try:
            names = self.app.controller.list_bundle_texture_names(path)
            tex = names[0] if names else None
            png, info = self.app.controller.preview_mod_bundle(path, tex)
        except Exception as exc:
            self.var_mod_cap.set(f"预览失败：{exc}")
            self._set_preview_image(None)
            return
        if not png:
            self.var_mod_cap.set("包内无可预览贴图")
            self._set_preview_image(None)
            return
        try:
            img = Image.open(png).convert("RGBA")
            img.load()
            img.thumbnail((200, 200), Image.Resampling.LANCZOS)
            cimg = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self._preview_ref = cimg
            self._set_preview_image(cimg)
            cap = info.name if info else bundle_name
            size = f" · {info.width}×{info.height}" if info else ""
            self.var_mod_cap.set(f"{cap}{size}")
        except Exception as exc:
            self.var_mod_cap.set(f"显示失败：{exc}")
            self._set_preview_image(None)

    def _set_preview_image(self, cimg) -> None:
        for w in list(self._preview_host.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        if cimg is None:
            self.mod_preview = ctk.CTkLabel(
                self._preview_host, text="—", font=font(12), text_color=COLORS["soft"]
            )
        else:
            self.mod_preview = ctk.CTkLabel(self._preview_host, text="", image=cimg)
        self.mod_preview.pack(expand=True)

    def do_install(self) -> None:
        if not self._pending:
            return
        src = Path(self._pending)
        nice_name = src.stem if src.is_file() else src.name
        try:
            self.app.controller.install(self._pending, name=nice_name)
        except Exception as exc:
            self.app._error("安装失败", str(exc))
            return
        self.install_btn.configure(state="disabled")
        self.var_analysis.set(f"安装完成「{nice_name}」。下方可继续预览（来自本地缓存）。")
        # 安装后改从 mod_store 预览，不依赖临时目录
        store = DATA_DIR / "mod_store" / nice_name
        if store.exists():
            self._preview_root = store
            self._preview_files = {p.name: p for p in store.glob("*.bundle")}
            self._fill_mod_preview_list()
        self._pending = None
        self.app.refresh_ui_state()
        self.refresh_installed()

    def _load_installed_for_preview(self, mod_name: str) -> None:
        """点已装 mod 的「预览」：优先 mod_store，否则从游戏目录按记录文件名读。"""
        # 直接读 state，保证有 files 列表
        mgr = self.app.controller.manager
        if not mgr:
            self.app._error("预览失败", "未检测到游戏。")
            return
        state = mgr._load_state()
        mod = state.get("mods", {}).get(mod_name)
        if not mod:
            self.app._error("预览失败", "找不到该 mod 记录。")
            return
        file_names = list(mod.get("files") or [])
        store = Path(mod.get("store") or (DATA_DIR / "mod_store" / mod_name))
        files: dict[str, Path] = {}
        if store.exists():
            files = {p.name: p for p in store.glob("*.bundle")}
        # store 空：从游戏目录按记录文件名填充（装过就是 mod 内容）
        aa = self.app.controller.aa_dir
        if not files and aa and file_names:
            store.mkdir(parents=True, exist_ok=True)
            import shutil

            for fname in file_names:
                src = aa / fname
                if src.exists():
                    dst = store / fname
                    try:
                        shutil.copy2(src, dst)
                        files[fname] = dst
                    except OSError:
                        files[fname] = src
            # 写回 store 路径，方便下次和启用
            mod["store"] = str(store)
            state["mods"][mod_name] = mod
            mgr._save_state(state)
        if not files and aa and file_names:
            for fname in file_names:
                p = aa / fname
                if p.exists():
                    files[fname] = p
        if not files:
            self.app._error("预览失败", "没有可预览的文件。请重新安装该 mod。")
            return
        self._preview_root = store if any(store.glob("*.bundle")) else aa
        self._preview_files = files
        self.var_analysis.set(f"正在预览已装 mod「{mod_name}」（{len(files)} 个包）。点左侧资源包看图。")
        self._fill_mod_preview_list()
        first = sorted(files.keys())[0]
        self._select_preview_item(first)

    def refresh_installed(self) -> None:
        for child in list(self.list_frame.winfo_children()):
            try:
                child.destroy()
            except Exception:
                pass
        mods = self.app.controller.installed_mods()
        self.var_installed_count.set(f"共 {len(mods)} 个")
        if not mods:
            ctk.CTkLabel(
                self.list_frame, text="还没有安装任何 mod。", font=font(13), text_color=COLORS["soft"]
            ).pack(anchor="w", pady=8, padx=4)
            return
        for mod in mods:
            display = mod["name"]
            disabled = bool(mod.get("disabled"))
            status = "已禁用" if disabled else "已启用"
            rowf = ctk.CTkFrame(
                self.list_frame,
                fg_color="#2a2438" if disabled else COLORS["card_soft"],
                corner_radius=10,
            )
            rowf.pack(fill="x", pady=4)
            ctk.CTkLabel(
                rowf,
                text=display,
                font=font(13, bold=True),
                text_color=COLORS["soft"] if disabled else COLORS["text"],
            ).pack(side="left", padx=(14, 6), pady=10)
            ctk.CTkLabel(
                rowf,
                text=f"{status} · {mod['count']} 个包 · {(mod.get('installed_at') or '')[:16]}",
                font=font(11),
                text_color=COLORS["muted"],
            ).pack(side="left")
            make_button(
                rowf, "卸载", lambda n=mod["name"]: self._uninstall(n), kind="ghost", height=32
            ).pack(side="right", padx=(4, 10))
            if disabled:
                make_button(
                    rowf, "启用", lambda n=mod["name"]: self._enable(n), kind="primary", height=32
                ).pack(side="right", padx=4)
            else:
                make_button(
                    rowf, "禁用", lambda n=mod["name"]: self._disable(n), kind="purple", height=32
                ).pack(side="right", padx=4)
            make_button(
                rowf, "预览", lambda n=mod["name"]: self._load_installed_for_preview(n), kind="ghost", height=32
            ).pack(side="right", padx=4)

    def _uninstall(self, name: str) -> None:
        try:
            self.app.controller.uninstall(name)
        except Exception as exc:
            self.app._error("卸载失败", str(exc))
            return
        if self._preview_root and "mod_store" in str(self._preview_root) and name in str(self._preview_root):
            self._preview_files = {}
            self._fill_mod_preview_list()
        self.app.refresh_ui_state()
        self.refresh_installed()

    def _disable(self, name: str) -> None:
        try:
            self.app.controller.disable_mod(name)
        except Exception as exc:
            self.app._error("禁用失败", str(exc))
            return
        self.app.refresh_ui_state()
        self.refresh_installed()

    def _enable(self, name: str) -> None:
        try:
            self.app.controller.enable_mod(name)
        except Exception as exc:
            self.app._error("启用失败", str(exc))
            return
        self.app.refresh_ui_state()
        self.refresh_installed()
