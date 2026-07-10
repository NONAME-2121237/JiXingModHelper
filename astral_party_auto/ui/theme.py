"""统一的配色与字体，取自应用图标的粉 / 紫 / 金色调。"""
from __future__ import annotations

import customtkinter as ctk


# 深色主题配色。整套界面只用这里的颜色，保证观感统一。
COLORS = {
    "window": "#141019",
    "sidebar": "#1b1626",
    "card": "#221c30",
    "card_soft": "#2a2340",
    "card_line": "#352c4a",
    "input": "#2c2540",
    "text": "#f5f2fa",
    "muted": "#a89fc0",
    "soft": "#7b7398",
    "accent": "#ff4d94",       # 主粉色
    "accent_hover": "#ff6ba6",
    "accent_dim": "#3a2035",
    "purple": "#9b6dff",
    "purple_hover": "#ad86ff",
    "gold": "#ffc44d",
    "gold_hover": "#ffd275",
    "good": "#45e0a0",
    "warn": "#ffce5a",
    "danger": "#ff5d6c",
    "danger_hover": "#ff7c88",
}

FONT_FAMILY = "Microsoft YaHei UI"


def font(size: int = 13, *, bold: bool = False) -> tuple:
    return (FONT_FAMILY, size, "bold" if bold else "normal")


def apply_appearance() -> None:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")
