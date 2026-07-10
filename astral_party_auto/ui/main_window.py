from __future__ import annotations

import os
import queue
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from ..core.config import ASSETS_DIR
from ..mod_controller import ModController
from .pages import BrowsePage, LogsPage, ManagePage, ModDashboardPage, PackPage, StudioPage
from .theme import COLORS, apply_appearance, font
from .widgets import make_button


PAGE_TITLES = {
    "dashboard": "仪表盘",
    "manage": "Mod 管理",
    "browse": "浏览资源",
    "studio": "制作替换",
    "pack": "我的作品集",
    "logs": "运行日志",
}


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        apply_appearance()
        self.title("吉星派对 Mod 助手")
        # 窗口偏小，减轻 CTk 拉伸时整树 layout 卡顿
        self.geometry("1100x720")
        # 最小宽度保证按钮行能排开；再窄会换行而不是挤没
        self.minsize(900, 620)
        self.configure(fg_color=COLORS["window"])

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.controller = ModController(self.log_queue.put)

        self.var_game = ctk.StringVar(value="检测中…")
        self.var_bundles = ctk.StringVar(value="—")
        self.var_installed = ctk.StringVar(value="0")
        self.var_backup = ctk.StringVar(value="0")
        self.var_page_title = ctk.StringVar(value="仪表盘")
        self.var_header_status = ctk.StringVar(value="● 就绪")
        self.var_pack_badge = ctk.StringVar(value="")

        self._resize_job = None
        self._resizing = False
        self._load_icon()
        self._build_sidebar()
        self._build_main()
        self._enable_deferred_shell_layout()
        self._build_pages()
        self._bind_hotkeys()
        self.bind("<Configure>", self._on_configure_debounce)
        self.show_page("dashboard")
        self.refresh_detection()
        self.log("欢迎使用吉星派对 Mod 助手。装 mod 前会自动备份原文件，随时可一键还原。")
        self.after(120, self._drain_logs)
        self.after(500, self._refresh_pack_badge)

    # ---------- 外观 ----------
    def _load_icon(self) -> None:
        self.logo_image = None
        self._win_hicons: list[int] = []
        self._icon_photos: list = []
        ico = ASSETS_DIR / "app_icon.ico"
        png = ASSETS_DIR / "app_icon.png"

        if ico.exists():
            ico_path = str(ico.resolve())
            try:
                self.iconbitmap(default=ico_path)
                self.wm_iconbitmap(ico_path)
            except Exception:
                pass
            for delay in (0, 100, 400, 1000):
                self.after(delay, lambda p=ico_path: self._apply_win_icon(p))

        if png.exists():
            try:
                image = Image.open(png).convert("RGBA")
                self.logo_image = ctk.CTkImage(light_image=image, dark_image=image, size=(60, 60))
                # 标题栏兜底：多尺寸 iconphoto
                from PIL import ImageTk

                for size in (16, 32, 48):
                    frame = image.copy()
                    frame.thumbnail((size, size), Image.Resampling.LANCZOS)
                    photo = ImageTk.PhotoImage(frame)
                    self._icon_photos.append(photo)
                if self._icon_photos:
                    self.iconphoto(True, *self._icon_photos)
            except Exception:
                self.logo_image = None

    def _apply_win_icon(self, ico_path: str) -> None:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            WM_SETICON = 0x0080
            ICON_SMALL, ICON_BIG = 0, 1

            h_big = user32.LoadImageW(0, ico_path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            h_sm = user32.LoadImageW(0, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            if not h_big:
                h_big = user32.LoadImageW(0, ico_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
            if not h_sm:
                h_sm = h_big
            if not h_big and not h_sm:
                return

            self._win_hicons.extend([h for h in (h_big, h_sm) if h])
            hwnd = int(self.winfo_id())
            parent = int(user32.GetParent(hwnd) or 0)
            targets = [hwnd]
            if parent:
                targets.append(parent)
            for h in targets:
                if h_big:
                    user32.SendMessageW(h, WM_SETICON, ICON_BIG, h_big)
                if h_sm:
                    user32.SendMessageW(h, WM_SETICON, ICON_SMALL, h_sm)
        except Exception:
            pass

    def _build_sidebar(self) -> None:
        self.sidebar = ctk.CTkFrame(self, fg_color=COLORS["sidebar"], corner_radius=0, width=232)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=20, pady=(16, 10))
        if self.logo_image:
            ctk.CTkLabel(brand, image=self.logo_image, text="").pack(anchor="w")
        ctk.CTkLabel(brand, text="吉星派对", font=font(20, bold=True), text_color=COLORS["text"]).pack(
            anchor="w", pady=(10, 0)
        )
        ctk.CTkLabel(brand, text="Mod 助手 · 换皮/立绘", font=font(12), text_color=COLORS["muted"]).pack(anchor="w")

        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("dashboard", "仪表盘"),
            ("manage", "Mod 管理"),
            ("browse", "浏览资源"),
            ("studio", "制作替换"),
            ("pack", "我的作品集"),
            ("logs", "运行日志"),
        ]
        for key, label in nav_items:
            button = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                command=lambda k=key: self.show_page(k),
                fg_color="transparent",
                hover_color=COLORS["card"],
                text_color=COLORS["muted"],
                corner_radius=10,
                height=40,
                font=font(14, bold=True),
            )
            button.pack(fill="x", padx=14, pady=2)
            self.nav_buttons[key] = button

        self.pack_badge = ctk.CTkLabel(
            self.sidebar, textvariable=self.var_pack_badge, font=font(11), text_color=COLORS["accent"]
        )
        self.pack_badge.pack(anchor="w", padx=22, pady=(0, 4))

        # 底部操作区先按 side=bottom 预留空间，再让中间空白区吃剩余高度。
        # 这样窗口变矮时只会缩小空白，不会把按钮压成一条线。
        self.sidebar_footer = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_footer.pack(side="bottom", fill="x", padx=18, pady=(0, 12))
        self.sidebar_launch_btn = make_button(self.sidebar_footer, "启动游戏", self.launch_game, kind="primary")
        self.sidebar_launch_btn.pack(fill="x", pady=(0, 8))
        self.sidebar_restore_btn = make_button(self.sidebar_footer, "一键全还原", self.restore_all, kind="danger")
        self.sidebar_restore_btn.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(
            self.sidebar_footer,
            text="安装前自动备份，可随时还原",
            font=font(10),
            text_color=COLORS["soft"],
            wraplength=196,
            justify="left",
        ).pack(anchor="w")

        ctk.CTkFrame(self.sidebar, fg_color="transparent").pack(fill="both", expand=True)

    def _build_main(self) -> None:
        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.pack(side="right", fill="both", expand=True)

        header = ctk.CTkFrame(self.main, fg_color="transparent", height=72)
        header.pack(fill="x", padx=28, pady=(18, 0))
        header.pack_propagate(False)
        ctk.CTkLabel(header, textvariable=self.var_page_title, font=font(24, bold=True), text_color=COLORS["text"]).pack(
            side="left"
        )
        self.header_pill = ctk.CTkFrame(header, fg_color=COLORS["card"], corner_radius=16)
        self.header_pill.pack(side="right", pady=14)
        ctk.CTkLabel(
            self.header_pill, textvariable=self.var_header_status, font=font(12, bold=True), text_color=COLORS["good"]
        ).pack(padx=16, pady=7)

        self.content = ctk.CTkFrame(self.main, fg_color="transparent")
        self.content.pack(fill="both", expand=True, padx=28, pady=(6, 20))
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

    def _enable_deferred_shell_layout(self) -> None:
        """主容器永久用 place；窗口拖动时保持旧尺寸，松手后再更新一次。"""
        self.sidebar.pack_forget()
        self.main.pack_forget()
        self.main.pack_propagate(False)
        self._place_shell(1100, 720)

    def _place_shell(self, logical_width: int, logical_height: int) -> None:
        logical_width = max(int(logical_width), 1)
        logical_height = max(int(logical_height), 1)
        main_width = max(logical_width - 232, 1)
        self.sidebar.configure(width=232, height=logical_height)
        self.main.configure(width=main_width, height=logical_height)
        self.sidebar.place(x=0, y=0)
        self.main.place(x=232, y=0)

    def _build_pages(self) -> None:
        # 懒加载：首次进入某页才创建，隐藏页 grid_remove 不参与布局（拉伸只重排当前页）
        self.pages: dict = {}
        self._page_factory = {
            "dashboard": lambda: ModDashboardPage(self.content, self),
            "manage": lambda: ManagePage(self.content, self),
            "browse": lambda: BrowsePage(self.content, self),
            "studio": lambda: StudioPage(self.content, self),
            "pack": lambda: PackPage(self.content, self),
            "logs": lambda: LogsPage(self.content, self),
        }
        # 兼容旧属性名
        self.dashboard = None
        self.manage = None
        self.browse_page = None
        self.studio = None
        self.pack_page = None
        self.logs = None

    def _ensure_page(self, page: str):
        if page not in self.pages:
            frame = self._page_factory[page]()
            frame.grid(row=0, column=0, sticky="nsew")
            self.pages[page] = frame
            if page == "dashboard":
                self.dashboard = frame
            elif page == "manage":
                self.manage = frame
            elif page == "browse":
                self.browse_page = frame
            elif page == "studio":
                self.studio = frame
            elif page == "pack":
                self.pack_page = frame
            elif page == "logs":
                self.logs = frame
                # 把缓冲的日志灌进去
                for line in getattr(self, "_log_buffer", []):
                    try:
                        frame.append(line)
                    except Exception:
                        pass
                self._log_buffer = []
        return self.pages[page]

    def show_page(self, page: str) -> None:
        self.var_page_title.set(PAGE_TITLES.get(page, page))
        for key, button in self.nav_buttons.items():
            if key == page:
                button.configure(fg_color=COLORS["accent"], text_color="#ffffff", hover_color=COLORS["accent_hover"])
            else:
                button.configure(fg_color="transparent", text_color=COLORS["muted"], hover_color=COLORS["card"])
        # 先卸下旧页再创建新页，避免两个复杂页面在同一轮布局里互相影响。
        for frame in self.pages.values():
            frame.grid_remove()
        current = self._ensure_page(page)
        current.grid()
        if page == "manage" and self.manage:
            self.manage.refresh_installed()
        if page == "browse" and self.browse_page and hasattr(self.browse_page, "on_show"):
            self.browse_page.on_show()
        if page == "studio" and self.studio and hasattr(self.studio, "on_show"):
            self.studio.on_show()
        if page == "pack" and self.pack_page and hasattr(self.pack_page, "on_show"):
            self.pack_page.on_show()
        self._refresh_pack_badge()

    def _refresh_pack_badge(self) -> None:
        n = self.controller.draft_count()
        self.var_pack_badge.set(f"作品集 {n} 项" if n else "")

    def _bind_hotkeys(self) -> None:
        self.bind_all("<Control-f>", self._hotkey_search)
        self.bind_all("<Control-F>", self._hotkey_search)
        self.bind_all("<Control-e>", self._hotkey_export)
        self.bind_all("<Control-E>", self._hotkey_export)
        self.bind_all("<Control-i>", self._hotkey_index)
        self.bind_all("<Control-I>", self._hotkey_index)

    def _hotkey_search(self, _event=None):
        self.show_page("browse")
        try:
            self.browse_page.search_entry.focus_set()
        except Exception:
            pass
        return "break"

    def _hotkey_export(self, _event=None):
        self.show_page("pack")
        try:
            self.pack_page.export_zip()
        except Exception:
            pass
        return "break"

    def _hotkey_index(self, _event=None):
        self.show_page("browse")
        try:
            self.browse_page.build_index()
        except Exception:
            pass
        return "break"

    def _on_configure_debounce(self, event) -> None:
        # 只处理主窗口自身，且忽略纯移动（宽高不变）
        if event.widget is not self:
            return
        try:
            w, h = int(event.width), int(event.height)
        except Exception:
            return
        last = getattr(self, "_last_geo", None)
        if last is not None:
            lw, lh = last
            # 变化太小不处理
            if abs(w - lw) < 4 and abs(h - lh) < 4:
                return
        self._last_geo = (w, h)
        self._resizing = True
        if self._resize_job is not None:
            try:
                self.after_cancel(self._resize_job)
            except Exception:
                pass
        # 鼠标松开后尽快恢复；按着边框时 _finish_resize 会继续等待。
        self._resize_job = self.after(30, self._finish_resize)

    @staticmethod
    def _resize_drag_active() -> bool:
        """窗口边框属于非客户区，Tk 收不到它的 ButtonRelease。"""
        try:
            import ctypes

            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception:
            return False

    def _finish_resize(self) -> None:
        # 只要用户还按着窗口边框，就绝不刷新页面。
        if self._resize_drag_active():
            self._resize_job = self.after(50, self._finish_resize)
            return
        self._resize_job = None
        self._resizing = False
        if not self._last_geo:
            return
        physical_width, physical_height = self._last_geo
        logical_width = max(int(self._reverse_window_scaling(physical_width)), 1)
        logical_height = max(int(self._reverse_window_scaling(physical_height)), 1)
        self._place_shell(logical_width, logical_height)

    # ---------- 回调 ----------
    def refresh_detection(self) -> None:
        self.controller.refresh_detection()
        self.refresh_ui_state()

    def restore_all(self) -> None:
        if not self.controller.has_game:
            self._error("没有游戏", "没有检测到游戏资源目录。")
            return
        if not messagebox.askyesno("一键全还原", "把所有被 mod 替换过的资源包恢复成原始文件？"):
            return
        try:
            self.controller.restore_all()
        except Exception as exc:
            self._error("还原失败", str(exc))
        self.refresh_ui_state()
        self.manage.refresh_installed()

    def open_asset_dir(self) -> None:
        if self.controller.has_game:
            os.startfile(str(self.controller.aa_dir))
        else:
            self._error("打开失败", "没有检测到游戏资源目录。")

    def launch_game(self) -> None:
        try:
            self.controller.launch_game("CN")
            self.var_header_status.set("● 已启动游戏")
            path = self.controller.game_exe_display()
            self.log(f"启动游戏：{path}")
        except Exception as exc:
            self._error("启动失败", str(exc))

    def refresh_ui_state(self) -> None:
        controller = self.controller
        if controller.has_game:
            exe = controller.game_install.cn_exe or controller.game_install.int_exe
            name = controller.game_install.install_dir.name
            self.var_game.set(f"已检测\n{name}")
            # 5500=全部 bundle；含贴图=索引里的包数（更有用）
            total = controller.bundle_count
            tex_n = len(controller.index) if controller.index else 0
            if tex_n:
                self.var_bundles.set(f"{total} 个包\n含贴图 {tex_n}")
            else:
                self.var_bundles.set(f"{total} 个包\n未建索引")
            if exe:
                self.var_header_status.set("● 就绪 · 可启动")
        else:
            self.var_game.set("未检测到")
            self.var_bundles.set("—")
            self.var_header_status.set("● 未找到游戏")
        mods = controller.installed_mods()
        self.var_installed.set(str(len(mods)))
        backups = 0
        if controller.manager and controller.manager.backup_dir.exists():
            backups = sum(1 for _ in controller.manager.backup_dir.glob("*.bundle"))
        self.var_backup.set(str(backups))
        if self.dashboard is not None:
            self.dashboard.set_status(controller.has_game, len(mods))
        self._refresh_pack_badge()

    # ---------- 日志 ----------
    def log(self, message: str) -> None:
        self.log_queue.put(message)

    def _drain_logs(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            stamp = datetime.now().strftime("%H:%M:%S")
            # 日志页懒加载：未打开时只堆积，打开后再灌入
            if self.logs is not None:
                self.logs.append(f"[{stamp}] {message}")
            else:
                if not hasattr(self, "_log_buffer"):
                    self._log_buffer: list[str] = []
                self._log_buffer.append(f"[{stamp}] {message}")
                if len(self._log_buffer) > 500:
                    self._log_buffer = self._log_buffer[-500:]
        self.after(120, self._drain_logs)

    def _error(self, title: str, message: str) -> None:
        self.log(f"{title}：{message}")
        messagebox.showerror(title, message)
