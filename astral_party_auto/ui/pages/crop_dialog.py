"""裁剪对话框：粉框可拖动；Shift+拖 才重画新框。默认贴合游戏原资源比例。"""
from __future__ import annotations

from pathlib import Path
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from ..theme import COLORS, font
from ..widgets import make_button


class CropDialog(ctk.CTkToplevel):
    def __init__(self, master, image_path: str | Path, target_size: tuple[int, int] | None = None):
        super().__init__(master)
        self.title("裁剪替换图")
        self.geometry("760x680")
        self.minsize(600, 520)
        self.configure(fg_color=COLORS["window"])
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self.result: tuple[int, int, int, int] | None = None
        self._img = Image.open(image_path).convert("RGBA")
        self._target = target_size if target_size and target_size[0] > 0 and target_size[1] > 0 else None
        self._scale = 1.0
        self._ox = 0
        self._oy = 0
        self._box: tuple[int, int, int, int] | None = None
        self._tk_img = None
        self._drawing = False
        self._mode: str | None = None  # "move" | "draw"
        self._press: tuple[int, int] | None = None
        self._box_at_press: tuple[int, int, int, int] | None = None
        self._rect_id = None

        if self._target:
            tip = (
                f"将按游戏原尺寸输出：{self._target[0]}×{self._target[1]}（先裁切再缩放）。\n"
                "拖动粉框可移动；按住 Shift 再拖可重新框选。"
            )
        else:
            tip = "拖动粉框移动；Shift+拖 重新框选。"
        ctk.CTkLabel(
            self, text=tip, font=font(12), text_color=COLORS["muted"], wraplength=720, justify="left"
        ).pack(anchor="w", padx=16, pady=(12, 4))

        self.canvas = tk.Canvas(self, bg="#0f0b16", highlightthickness=0, height=480, cursor="fleur")
        self.canvas.pack(fill="both", expand=True, padx=16, pady=8)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_resize)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(0, 10))
        make_button(bar, "贴合原资源比例", self._smart_crop, kind="ghost", height=36).pack(side="left")
        make_button(bar, "重置为整图", self._reset_full, kind="ghost", height=36).pack(side="left", padx=8)
        make_button(bar, "取消", self._cancel, kind="ghost", height=36).pack(side="right")
        make_button(bar, "确认裁剪", self._ok, kind="primary", height=36).pack(side="right", padx=8)

        self._var_info = ctk.StringVar(value="")
        ctk.CTkLabel(self, textvariable=self._var_info, font=font(11), text_color=COLORS["soft"]).pack(
            anchor="w", padx=16, pady=(0, 10)
        )

        self._smart_crop(draw=False)
        self.after(100, self._draw_image)

    def _img_to_canvas(self, x: int, y: int) -> tuple[float, float]:
        return self._ox + x * self._scale, self._oy + y * self._scale

    def _canvas_to_img(self, x: float, y: float) -> tuple[int, int]:
        if self._scale <= 0:
            return 0, 0
        ix = int(round((x - self._ox) / self._scale))
        iy = int(round((y - self._oy) / self._scale))
        return max(0, min(self._img.width, ix)), max(0, min(self._img.height, iy))

    def _point_in_box_canvas(self, x: int, y: int) -> bool:
        if not self._box:
            return False
        x0, y0 = self._img_to_canvas(self._box[0], self._box[1])
        x1, y1 = self._img_to_canvas(self._box[2], self._box[3])
        return min(x0, x1) <= x <= max(x0, x1) and min(y0, y1) <= y <= max(y0, y1)

    def _draw_image(self) -> None:
        if self._drawing:
            return
        self._drawing = True
        try:
            self.canvas.update_idletasks()
            cw = max(int(self.canvas.winfo_width()), 120)
            ch = max(int(self.canvas.winfo_height()), 120)
            if cw < 40 or ch < 40:
                return
            img = self._img.copy()
            img.thumbnail((max(cw - 24, 40), max(ch - 24, 40)), Image.Resampling.LANCZOS)
            self._scale = img.width / self._img.width if self._img.width else 1.0
            self._tk_img = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self._ox = (cw - img.width) // 2
            self._oy = (ch - img.height) // 2
            self.canvas.create_image(self._ox, self._oy, anchor="nw", image=self._tk_img)
            if self._box:
                self._paint_box(self._box)
            self._update_info()
        finally:
            self._drawing = False

    def _paint_box(self, box: tuple[int, int, int, int]) -> None:
        x0, y0 = self._img_to_canvas(box[0], box[1])
        x1, y1 = self._img_to_canvas(box[2], box[3])
        if self._rect_id:
            try:
                self.canvas.delete(self._rect_id)
            except Exception:
                pass
        self._rect_id = self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ff4d94", width=2)

    def _on_resize(self, event=None) -> None:
        if event is not None and event.widget is not self:
            return
        job = getattr(self, "_resize_job", None)
        if job:
            try:
                self.after_cancel(job)
            except Exception:
                pass
        self._resize_job = self.after(120, self._draw_image)

    def _on_press(self, event) -> None:
        self._press = (event.x, event.y)
        shift = bool(event.state & 0x0001)
        if self._box and self._point_in_box_canvas(event.x, event.y) and not shift:
            self._mode = "move"
            self._box_at_press = self._box
            self.canvas.configure(cursor="fleur")
        else:
            # 仅 Shift+拖 或无框时重画；普通框外点击不毁掉现有框
            if shift or not self._box:
                self._mode = "draw"
                self._box_at_press = None
                if self._rect_id:
                    self.canvas.delete(self._rect_id)
                    self._rect_id = None
                self.canvas.configure(cursor="crosshair")
            else:
                self._mode = "move"
                self._box_at_press = self._box
                self.canvas.configure(cursor="fleur")

    def _on_drag(self, event) -> None:
        if not self._press:
            return
        if self._mode == "move" and self._box_at_press and self._scale > 0:
            dx = (event.x - self._press[0]) / self._scale
            dy = (event.y - self._press[1]) / self._scale
            l, t, r, b = self._box_at_press
            w, h = r - l, b - t
            nl = int(round(l + dx))
            nt = int(round(t + dy))
            # 钳制在图内
            nl = max(0, min(self._img.width - w, nl))
            nt = max(0, min(self._img.height - h, nt))
            self._box = (nl, nt, nl + w, nt + h)
            self._paint_box(self._box)
            self._update_info()
        elif self._mode == "draw":
            x0, y0 = self._press
            if self._rect_id:
                self.canvas.delete(self._rect_id)
            self._rect_id = self.canvas.create_rectangle(
                x0, y0, event.x, event.y, outline="#ff4d94", width=2
            )

    def _on_release(self, event) -> None:
        if not self._press:
            return
        if self._mode == "draw":
            x0, y0 = self._press
            x1, y1 = event.x, event.y
            if abs(x1 - x0) >= 6 and abs(y1 - y0) >= 6:
                l, r = sorted((x0, x1))
                t, b = sorted((y0, y1))
                il, it = self._canvas_to_img(l, t)
                ir, ib = self._canvas_to_img(r, b)
                if ir - il >= 2 and ib - it >= 2:
                    self._box = (il, it, ir, ib)
            self._draw_image()
        elif self._mode == "move":
            self._update_info()
        self._press = None
        self._mode = None
        self._box_at_press = None
        self.canvas.configure(cursor="fleur")

    def _smart_crop(self, draw: bool = True) -> None:
        w, h = self._img.size
        if self._target:
            tw, th = self._target
            src_ratio = w / max(h, 1)
            tgt_ratio = tw / max(th, 1)
            if src_ratio > tgt_ratio:
                nh = h
                nw = max(1, int(round(h * tgt_ratio)))
            else:
                nw = w
                nh = max(1, int(round(w / tgt_ratio)))
            l = max(0, (w - nw) // 2)
            t = max(0, (h - nh) // 2)
            self._box = (l, t, min(w, l + nw), min(h, t + nh))
        else:
            side = min(w, h)
            l = (w - side) // 2
            t = (h - side) // 2
            self._box = (l, t, l + side, t + side)
        if draw:
            self._draw_image()

    def _reset_full(self) -> None:
        self._box = (0, 0, self._img.width, self._img.height)
        self._draw_image()

    def _update_info(self) -> None:
        if not self._box:
            self._var_info.set(f"原图 {self._img.width}×{self._img.height}")
            return
        l, t, r, b = self._box
        cw, ch = r - l, b - t
        if self._target:
            self._var_info.set(
                f"裁切区 {cw}×{ch}  →  游戏原尺寸输出 {self._target[0]}×{self._target[1]}"
            )
        else:
            self._var_info.set(f"原图 {self._img.width}×{self._img.height}  →  裁切 {cw}×{ch}")

    def _ok(self) -> None:
        if self._box is None:
            self._smart_crop(draw=False)
        if self._box is None:
            self._box = (0, 0, self._img.width, self._img.height)
        l, t, r, b = self._box
        if r <= l or b <= t:
            self._box = (0, 0, self._img.width, self._img.height)
        self.result = self._box
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def show(self) -> tuple[int, int, int, int] | None:
        self.wait_window()
        return self.result
