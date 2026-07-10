from __future__ import annotations

import customtkinter as ctk

from ..theme import COLORS, font
from ..widgets import Card, FlowButtonBar, StatTile, enable_mousewheel, make_button


class ModDashboardPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        self.page_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.page_scroll.pack(fill="both", expand=True)
        enable_mousewheel(self.page_scroll, step=6)

        tiles = ctk.CTkFrame(self.page_scroll, fg_color="transparent")
        tiles.pack(fill="x")
        # 窄窗时 2×2，避免四格挤没
        for col in range(2):
            tiles.columnconfigure(col, weight=1, uniform="tile")
        self.tile_game = StatTile(tiles, "游戏检测", app.var_game, COLORS["soft"])
        self.tile_bundles = StatTile(tiles, "资源包", app.var_bundles, COLORS["gold"])
        self.tile_installed = StatTile(tiles, "已装 Mod", app.var_installed, COLORS["accent"])
        self.tile_backup = StatTile(tiles, "已备份原文件", app.var_backup, COLORS["good"])
        self.tile_game.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))
        self.tile_bundles.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        self.tile_installed.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.tile_backup.grid(row=1, column=1, sticky="ew")

        quick = Card(
            self.page_scroll,
            "快速开始",
            "装 mod 会自动备份原文件；不满意随时「一键全还原」，不怕改坏。",
            wrap=780,
        )
        quick.pack(fill="x", pady=(16, 0))
        self.quick_bar = FlowButtonBar(quick.body, gap=8)
        self.quick_bar.pack(fill="x")
        self.quick_bar.add_button("启动游戏", app.launch_game, kind="primary", height=40)
        self.quick_bar.add_button("去装 Mod", lambda: app.show_page("manage"), kind="purple", height=40)
        self.quick_bar.add_button("浏览资源", lambda: app.show_page("browse"), kind="ghost", height=40)
        self.quick_bar.add_button("我的作品集", lambda: app.show_page("pack"), kind="ghost", height=40)
        self.quick_bar.add_button("刷新检测", app.refresh_detection, kind="ghost", height=40)
        self.quick_bar.add_button("打开资源目录", app.open_asset_dir, kind="ghost", height=40)

        self.var_exe = ctk.StringVar(value="")
        ctk.CTkLabel(
            quick.body, textvariable=self.var_exe, font=font(11), text_color=COLORS["soft"], wraplength=780, justify="left"
        ).pack(anchor="w", pady=(10, 0))

        tips = Card(self.page_scroll, "怎么用", wrap=780)
        tips.pack(fill="x", pady=(16, 8))
        ctk.CTkLabel(
            tips.body,
            text=(
                "· 「浏览资源」：下拉选类型——贴图 / 文本 / 3D模型 / 动画。\n"
                "· 可替换：贴图、文本、动画（动画预览为同包第一帧图；也可用 .animbin）。\n"
                "· 3D模型只导出不替换。走路攻击序列帧也在「贴图 → 角色动作帧」。\n"
                "· 「制作替换」：换图、裁剪后「确认替换并加入作品集」。\n"
                "· 「我的作品集」：预览对比、导出 ZIP、安装；Mod 可禁用/启用。\n"
                "· 资源范围：StreamingAssets/aa 下 Addressable 的 *.bundle。大量音效用 Wwise，不一定在包内。\n"
                "· 全程本地文件替换，不注入进程。"
            ),
            font=font(13),
            text_color=COLORS["muted"],
            justify="left",
            anchor="nw",
            wraplength=780,
        ).pack(fill="x", anchor="nw")

    def set_status(self, has_game: bool, mod_count: int) -> None:
        self.tile_game.set_dot(COLORS["good"] if has_game else COLORS["danger"])
        self.tile_installed.set_dot(COLORS["accent"] if mod_count else COLORS["soft"])
        try:
            path = self.app.controller.game_exe_display()
            self.var_exe.set(f"自动找到的游戏：{path}" if has_game else "未找到游戏，请确认 Steam 已安装吉星派对。")
        except Exception:
            pass
