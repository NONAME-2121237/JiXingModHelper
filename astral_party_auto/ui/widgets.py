"""可复用的界面组件：卡片、按钮、状态块、滚动辅助。"""
from __future__ import annotations

import customtkinter as ctk

from .theme import COLORS, font


BUTTON_KINDS = {
    # fg, hover, text
    "primary": (COLORS["accent"], COLORS["accent_hover"], "#ffffff"),
    "purple": (COLORS["purple"], COLORS["purple_hover"], "#ffffff"),
    "gold": (COLORS["gold"], COLORS["gold_hover"], "#231505"),
    "danger": (COLORS["danger"], COLORS["danger_hover"], "#ffffff"),
    # ghost：悬停用更亮的紫灰，避免 hover=描边色看起来像「没色了」
    "ghost": (COLORS["card_soft"], "#4a3f66", COLORS["text"]),
}


def _auto_btn_width(text: str, minimum: int = 72) -> int:
    """按文案估宽，避免 width=0 / 过窄导致按钮塌成方块。"""
    w = 32
    for ch in text:
        w += 16 if ord(ch) > 127 else 9
    return max(minimum, w)


def make_button(parent, text: str, command, *, kind: str = "ghost", height: int = 42, width: int = 0, **kwargs) -> ctk.CTkButton:
    fg, hover, text_color = BUTTON_KINDS.get(kind, BUTTON_KINDS["ghost"])
    # 始终保证最小可读宽度；禁止被 pack 挤成 0 宽
    need = _auto_btn_width(text)
    if width is None or width <= 0:
        width = need
    else:
        width = max(int(width), need)
    btn = ctk.CTkButton(
        parent,
        text=text,
        command=command,
        fg_color=fg,
        hover_color=hover,
        text_color=text_color,
        text_color_disabled=COLORS["soft"],
        border_width=0,
        corner_radius=12,
        height=height,
        width=width,
        font=font(13, bold=True),
        **kwargs,
    )
    # 记住设计宽度，供 FlowButtonBar 换行用
    btn._design_width = width  # type: ignore[attr-defined]
    btn._design_height = height  # type: ignore[attr-defined]
    return btn


class FlowButtonBar(ctk.CTkFrame):
    """窄窗口时按钮自动换行，并正确处理 Windows 的 DPI 缩放。"""

    def __init__(self, parent, *, gap: int = 8, **kwargs):
        kwargs.setdefault("height", 36)
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._gap = gap
        self._btns: list[ctk.CTkButton] = []
        self._hidden_btns: set[ctk.CTkButton] = set()
        self._reflow_job = None
        self._physical_width = 1
        self._last_layout = None
        # place 子项不会贡献请求尺寸，高度统一由 _reflow 管理。
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.bind("<Configure>", self._on_configure)

    def add(self, btn: ctk.CTkButton) -> ctk.CTkButton:
        self._btns.append(btn)
        # 先放到可见位置，随后合并到最近一次布局计算。
        btn.place(x=0, y=0)
        self._schedule_reflow()
        return btn

    def add_button(self, text: str, command, *, kind: str = "ghost", height: int = 36, **kwargs) -> ctk.CTkButton:
        btn = make_button(self, text, command, kind=kind, height=height, **kwargs)
        return self.add(btn)

    def hide(self, btn: ctk.CTkButton) -> None:
        """临时隐藏按钮，同时让后面的按钮补位。"""
        self._hidden_btns.add(btn)
        btn.place_forget()
        self._last_layout = None
        self._schedule_reflow()

    def show(self, btn: ctk.CTkButton) -> None:
        """重新显示由 hide 隐藏的按钮。"""
        self._hidden_btns.discard(btn)
        self._last_layout = None
        self._schedule_reflow()

    def _on_configure(self, event=None) -> None:
        if event is not None:
            self._physical_width = max(int(event.width), 1)
        self._schedule_reflow()

    def _schedule_reflow(self) -> None:
        # Configure 在拖动窗口时会密集触发。每 24ms 最多布局一次，
        # 既能跟手，又不会为每一个像素递归 update_idletasks。
        if self._reflow_job is None:
            self._reflow_job = self.after(24, self._reflow)

    def _logical_width(self) -> int:
        physical = max(self._physical_width, int(self.winfo_width()), 1)
        try:
            # winfo_width 是屏幕像素，place/cget 使用的是 CTk 逻辑尺寸。
            return max(int(self._reverse_widget_scaling(physical)), 1)
        except Exception:
            return physical

    def _reflow(self) -> None:
        self._reflow_job = None
        visible = [btn for btn in self._btns if btn not in self._hidden_btns]
        if not visible:
            if int(float(self.cget("height"))) != 1:
                self.configure(height=1)
            return

        available = self._logical_width()
        x = y = row_height = 0
        positions: list[tuple[int, int]] = []
        for btn in visible:
            width = int(getattr(btn, "_design_width", 0) or btn.cget("width") or 80)
            height = int(getattr(btn, "_design_height", 0) or btn.cget("height") or 36)
            if x > 0 and x + width > available:
                x = 0
                y += row_height + self._gap
                row_height = 0
            positions.append((x, y))
            x += width + self._gap
            row_height = max(row_height, height)

        total_height = max(y + row_height, 1)
        layout = (available, total_height, tuple(positions), tuple(visible))
        if layout == self._last_layout:
            return
        self._last_layout = layout

        for btn, (x, y) in zip(visible, positions):
            # CTk 的 place 会自行应用 DPI 缩放，因此这里必须传逻辑尺寸。
            btn.place(x=x, y=y)
        if int(float(self.cget("height"))) != total_height:
            self.configure(height=total_height)


def enable_mousewheel(scrollable: ctk.CTkScrollableFrame, *, step: int = 14) -> None:
    """让 CTkScrollableFrame 在子控件上也能用滚轮；step 默认 14，滚得更跟手。

    customtkinter 默认只在 canvas 空白处响应滚轮；列表项上滚不动。
    内容刷新后请再调 scrollable.rebind_mousewheel()。
    """
    canvas = scrollable._parent_canvas

    def _scroll(units: int) -> None:
        canvas.yview_scroll(units * step, "units")

    def _on_wheel(event):
        delta = getattr(event, "delta", 0) or 0
        if not delta:
            return "break"
        # Windows 常 ±120；高精触控板可能 ±10~40，也放大
        if abs(delta) >= 120:
            units = int(-delta / 120)
        else:
            units = -3 if delta > 0 else 3
        if units == 0:
            units = -1 if delta > 0 else 1
        _scroll(units)
        return "break"

    def _on_up(_event):
        _scroll(-1)
        return "break"

    def _on_down(_event):
        _scroll(1)
        return "break"

    def _bind_tree(widget) -> None:
        # 嵌套的其它 ScrollableFrame 自己处理滚轮，避免外层抢走
        if widget is not scrollable and isinstance(widget, ctk.CTkScrollableFrame):
            return
        widget.bind("<MouseWheel>", _on_wheel)
        widget.bind("<Button-4>", _on_up)
        widget.bind("<Button-5>", _on_down)
        for child in widget.winfo_children():
            _bind_tree(child)

    def rebind() -> None:
        _bind_tree(scrollable)
        canvas.bind("<MouseWheel>", _on_wheel)
        canvas.bind("<Button-4>", _on_up)
        canvas.bind("<Button-5>", _on_down)

    rebind()
    scrollable.rebind_mousewheel = rebind  # type: ignore[attr-defined]


class Card(ctk.CTkFrame):
    """带标题/副标题的卡片，内容放进 self.body。"""

    def __init__(self, parent, title: str | None = None, subtitle: str | None = None, wrap: int = 720, **kwargs):
        super().__init__(
            parent,
            fg_color=COLORS["card"],
            corner_radius=16,
            border_width=1,
            border_color=COLORS["card_line"],
            **kwargs,
        )
        if title:
            ctk.CTkLabel(self, text=title, font=font(16, bold=True), text_color=COLORS["text"]).pack(
                anchor="w", padx=20, pady=(18, 0)
            )
        if subtitle:
            ctk.CTkLabel(
                self,
                text=subtitle,
                font=font(12),
                text_color=COLORS["muted"],
                wraplength=wrap,
                justify="left",
            ).pack(anchor="w", padx=20, pady=(4, 0))
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=20, pady=(14, 18))


class StatTile(ctk.CTkFrame):
    """仪表盘上的状态小块：一个圆点 + 标题 + 数值。"""

    def __init__(self, parent, title: str, value_var, dot_color: str = COLORS["good"]):
        super().__init__(
            parent,
            fg_color=COLORS["card"],
            corner_radius=14,
            border_width=1,
            border_color=COLORS["card_line"],
        )
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 2))
        self.dot = ctk.CTkLabel(top, text="●", font=font(12), text_color=dot_color)
        self.dot.pack(side="left")
        ctk.CTkLabel(top, text=title, font=font(12), text_color=COLORS["muted"]).pack(side="left", padx=(6, 0))
        ctk.CTkLabel(
            self,
            textvariable=value_var,
            font=font(15, bold=True),
            text_color=COLORS["text"],
            anchor="w",
            justify="left",
            wraplength=230,
        ).pack(fill="x", padx=16, pady=(0, 14))

    def set_dot(self, color: str) -> None:
        self.dot.configure(text_color=color)


class FormRow:
    """设置页的一行：左边标签 + 说明，右边控件。返回时自己 grid 好。"""

    def __init__(self, parent, row: int, label: str, help_text: str = ""):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=0, sticky="nw", pady=(10, 0))
        ctk.CTkLabel(box, text=label, font=font(13, bold=True), text_color=COLORS["text"]).pack(anchor="w")
        if help_text:
            ctk.CTkLabel(
                box,
                text=help_text,
                font=font(11),
                text_color=COLORS["soft"],
                wraplength=250,
                justify="left",
            ).pack(anchor="w", pady=(2, 0))
