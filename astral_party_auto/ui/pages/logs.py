from __future__ import annotations

import customtkinter as ctk

from ..theme import COLORS, font
from ..widgets import make_button


class LogsPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self.app = app

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text="安装、还原、预览与制作过程都会记在这里。",
            font=font(12),
            text_color=COLORS["muted"],
        ).pack(side="left")
        make_button(header, "清空日志", self.clear, kind="ghost", height=34, width=96).pack(side="right")

        self.textbox = ctk.CTkTextbox(
            self,
            fg_color="#0f0b16",
            text_color=COLORS["text"],
            border_width=1,
            border_color=COLORS["card_line"],
            corner_radius=14,
            font=("Consolas", 12),
            wrap="word",
        )
        self.textbox.pack(fill="both", expand=True, pady=(14, 0))
        self.textbox.configure(state="disabled")
        # 文本框本身支持滚轮；加大单位滚动更跟手
        self.textbox.bind("<MouseWheel>", self._on_wheel)

    def _on_wheel(self, event):
        delta = getattr(event, "delta", 0) or 0
        if not delta:
            return
        units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        if units == 0:
            units = -1 if delta > 0 else 1
        # CTkTextbox 内部是 tk Text
        try:
            self.textbox._textbox.yview_scroll(units * 3, "units")
        except Exception:
            pass
        return "break"

    def append(self, line: str) -> None:
        self.textbox.configure(state="normal")
        self.textbox.insert("end", line + "\n")
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def clear(self) -> None:
        self.textbox.configure(state="normal")
        self.textbox.delete("1.0", "end")
        self.textbox.configure(state="disabled")
