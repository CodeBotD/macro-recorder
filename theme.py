"""Light and dark ttk themes for the recorder UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

LIGHT = {
    "bg": "#f3f3f3",
    "fg": "#1a1a1a",
    "field_bg": "#ffffff",
    "select_bg": "#cce4f7",
    "select_fg": "#1a1a1a",
    "button_bg": "#e5e5e5",
    "border": "#c0c0c0",
    "accent": "#2b6cb0",
}

DARK = {
    "bg": "#1e1e1e",
    "fg": "#e8e8e8",
    "field_bg": "#2d2d2d",
    "select_bg": "#3a4a5c",
    "select_fg": "#f0f0f0",
    "button_bg": "#3a3a3a",
    "border": "#555555",
    "accent": "#6aa9d8",
}


def apply_theme(root: tk.Tk, dark: bool, listbox: tk.Listbox | None = None) -> None:
    colors = DARK if dark else LIGHT
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=colors["bg"])
    style.configure(".", background=colors["bg"], foreground=colors["fg"], fieldbackground=colors["field_bg"])
    style.configure("TFrame", background=colors["bg"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["fg"])
    style.configure(
        "TCheckbutton",
        background=colors["bg"],
        foreground=colors["fg"],
        focuscolor=colors["bg"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", colors["bg"])],
        foreground=[("disabled", colors["border"])],
    )
    style.configure(
        "TButton",
        background=colors["button_bg"],
        foreground=colors["fg"],
        bordercolor=colors["border"],
        focusthickness=1,
        focuscolor=colors["accent"],
        padding=4,
    )
    style.map(
        "TButton",
        background=[("active", colors["select_bg"]), ("pressed", colors["select_bg"])],
        foreground=[("disabled", colors["border"])],
    )
    style.configure(
        "TEntry",
        fieldbackground=colors["field_bg"],
        foreground=colors["fg"],
        bordercolor=colors["border"],
        insertcolor=colors["fg"],
    )
    style.configure(
        "TSpinbox",
        fieldbackground=colors["field_bg"],
        foreground=colors["fg"],
        bordercolor=colors["border"],
        arrowsize=12,
        insertcolor=colors["fg"],
    )
    style.map(
        "TSpinbox",
        fieldbackground=[("readonly", colors["field_bg"])],
        foreground=[("disabled", colors["border"])],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=colors["button_bg"],
        troughcolor=colors["bg"],
        bordercolor=colors["border"],
        arrowcolor=colors["fg"],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=colors["button_bg"],
        troughcolor=colors["bg"],
        bordercolor=colors["border"],
        arrowcolor=colors["fg"],
    )

    if listbox is not None:
        listbox.configure(
            bg=colors["field_bg"],
            fg=colors["fg"],
            selectbackground=colors["select_bg"],
            selectforeground=colors["select_fg"],
            highlightthickness=1,
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
            borderwidth=1,
            relief="solid",
        )
