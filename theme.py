"""Light, dark, and custom ttk themes for the recorder UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

THEME_MODES = ("light", "dark", "custom")

LIGHT = {
    "bg": "#f0f2f5",
    "fg": "#1a1a1a",
    "field_bg": "#ffffff",
    "select_bg": "#cce4f7",
    "select_fg": "#1a1a1a",
    "button_bg": "#e8eaed",
    "button_active": "#d5d9df",
    "border": "#c5cad3",
    "accent": "#2b6cb0",
    "panel": "#ffffff",
    "muted": "#5c6570",
}

DARK = {
    "bg": "#1a1d21",
    "fg": "#e8e8e8",
    "field_bg": "#2a2f36",
    "select_bg": "#3a4a5c",
    "select_fg": "#f0f0f0",
    "button_bg": "#3a4048",
    "button_active": "#4a515c",
    "border": "#555b66",
    "accent": "#6aa9d8",
    "panel": "#242830",
    "muted": "#9aa3ad",
}

CUSTOM = {
    "bg": "#1b2420",
    "fg": "#e6f0ea",
    "field_bg": "#24302a",
    "select_bg": "#3d5c4a",
    "select_fg": "#f2faf5",
    "button_bg": "#2f3f36",
    "button_active": "#3d5246",
    "border": "#4a6356",
    "accent": "#3ecf8e",
    "panel": "#222e28",
    "muted": "#8fa89a",
}

CUSTOM_COLOR_FIELDS = (
    ("accent", "Accent"),
    ("bg", "Background"),
    ("panel", "Panel"),
    ("fg", "Text"),
    ("muted", "Muted text"),
    ("button_bg", "Buttons"),
    ("button_active", "Buttons (hover)"),
    ("field_bg", "Fields"),
    ("border", "Borders"),
    ("select_bg", "Selection"),
    ("select_fg", "Selection text"),
)

CORNER_RADIUS = 12
BUTTON_RADIUS = 10


def normalize_theme_mode(mode) -> str:
    text = str(mode or "").strip().lower()
    if text in THEME_MODES:
        return text
    return "light"


def normalize_hex(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) == 7 and text.startswith("#"):
        body = text[1:]
    elif len(text) == 6:
        body = text
    else:
        return None
    try:
        int(body, 16)
    except ValueError:
        return None
    return f"#{body.lower()}"


def normalize_custom_colors(overrides) -> dict:
    colors = dict(CUSTOM)
    if not isinstance(overrides, dict):
        return colors
    for key in CUSTOM:
        hex_color = normalize_hex(overrides.get(key))
        if hex_color:
            colors[key] = hex_color
    return colors


def palette(mode: str | bool, custom_colors=None) -> dict:
    if isinstance(mode, bool):
        return dict(DARK if mode else LIGHT)
    mode = normalize_theme_mode(mode)
    if mode == "dark":
        return dict(DARK)
    if mode == "custom":
        return normalize_custom_colors(custom_colors)
    return dict(LIGHT)


def apply_theme(
    root: tk.Tk,
    mode: str | bool,
    listbox: tk.Listbox | None = None,
    custom_colors=None,
) -> dict:
    colors = palette(mode, custom_colors=custom_colors)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(bg=colors["bg"])
    style.configure(
        ".",
        background=colors["bg"],
        foreground=colors["fg"],
        fieldbackground=colors["field_bg"],
    )
    style.configure("TFrame", background=colors["bg"])
    style.configure("Card.TFrame", background=colors["panel"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["fg"])
    style.configure("Card.TLabel", background=colors["panel"], foreground=colors["fg"])
    style.configure("Muted.TLabel", background=colors["bg"], foreground=colors["muted"])
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
        padding=(10, 6),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("active", colors["button_active"]),
            ("pressed", colors["select_bg"]),
        ],
        foreground=[("disabled", colors["border"])],
    )
    style.configure(
        "TEntry",
        fieldbackground=colors["field_bg"],
        foreground=colors["fg"],
        bordercolor=colors["border"],
        insertcolor=colors["fg"],
        padding=4,
    )
    style.configure(
        "TSpinbox",
        fieldbackground=colors["field_bg"],
        foreground=colors["fg"],
        bordercolor=colors["border"],
        arrowsize=12,
        insertcolor=colors["fg"],
        padding=4,
    )
    style.map(
        "TSpinbox",
        fieldbackground=[("readonly", colors["field_bg"])],
        foreground=[("disabled", colors["border"])],
    )
    style.configure(
        "TLabelframe",
        background=colors["panel"],
        foreground=colors["fg"],
        bordercolor=colors["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=colors["panel"],
        foreground=colors["fg"],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=colors["button_bg"],
        troughcolor=colors["panel"],
        bordercolor=colors["border"],
        arrowcolor=colors["fg"],
    )
    style.configure(
        "Vertical.TScrollbar",
        background=colors["button_bg"],
        troughcolor=colors["panel"],
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
            borderwidth=0,
            relief="flat",
            activestyle="none",
        )
    return colors


def draw_rounded_rect(
    canvas: tk.Canvas,
    x1,
    y1,
    x2,
    y2,
    radius: int,
    fill: str,
    outline: str = "",
    tags=(),
):
    radius = max(0, min(radius, int((x2 - x1) / 2), int((y2 - y1) / 2)))
    points = [
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    ]
    return canvas.create_polygon(
        points,
        smooth=True,
        splinesteps=24,
        fill=fill,
        outline=outline or fill,
        tags=tags,
    )


class RoundedPanel(tk.Frame):
    """Frame with a rounded canvas background."""

    def __init__(self, master, colors: dict, radius: int = CORNER_RADIUS, padding: int = 10, **kwargs):
        bg = colors["bg"]
        super().__init__(master, bg=bg, highlightthickness=0, **kwargs)
        self._colors = colors
        self._radius = radius
        self._padding = padding
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=colors["panel"], highlightthickness=0)
        self._window = self.canvas.create_window(padding, padding, anchor="nw", window=self.body)
        self.bind("<Configure>", self._on_configure)
        self.body.bind("<Configure>", self._on_body_configure)

    def set_colors(self, colors: dict) -> None:
        self._colors = colors
        self.configure(bg=colors["bg"])
        self.canvas.configure(bg=colors["bg"])
        self.body.configure(bg=colors["panel"])
        self._redraw()

    def _on_configure(self, _event=None) -> None:
        self._redraw()

    def _on_body_configure(self, _event=None) -> None:
        pad = self._padding
        req_w = self.body.winfo_reqwidth() + pad * 2
        req_h = self.body.winfo_reqheight() + pad * 2
        self.canvas.configure(width=req_w, height=req_h)
        self.configure(width=req_w, height=req_h)
        self.canvas.itemconfigure(self._window, width=max(1, self.body.winfo_reqwidth()))
        self._redraw()

    def _redraw(self, _event=None) -> None:
        pad = self._padding
        body_w = max(self.body.winfo_reqwidth(), self.winfo_width() - pad * 2, 40)
        body_h = max(self.body.winfo_reqheight(), 20)
        w = body_w + pad * 2
        h = body_h + pad * 2
        self.canvas.delete("shape")
        draw_rounded_rect(
            self.canvas,
            1,
            1,
            w - 2,
            h - 2,
            self._radius,
            self._colors["panel"],
            self._colors["border"],
            tags=("shape",),
        )
        self.canvas.tag_lower("shape")
        self.canvas.itemconfigure(self._window, width=body_w)
        self.canvas.coords(self._window, pad, pad)
        self.canvas.configure(width=w, height=h)


class RoundedButton(tk.Canvas):
    """Simple rounded clickable button."""

    def __init__(
        self,
        master,
        text: str,
        command=None,
        colors: dict | None = None,
        radius: int = BUTTON_RADIUS,
        padx: int = 14,
        pady: int = 8,
        **kwargs,
    ):
        colors = colors or LIGHT
        super().__init__(
            master,
            highlightthickness=0,
            bd=0,
            bg=colors["bg"],
            cursor="hand2",
            **kwargs,
        )
        self._text = text
        self._command = command
        self._colors = colors
        self._radius = radius
        self._padx = padx
        self._pady = pady
        self._shape = None
        self._label = None
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self._draw(active=False)

    def set_text(self, text: str) -> None:
        self._text = text
        self._draw(active=False)

    def set_colors(self, colors: dict) -> None:
        self._colors = colors
        self.configure(bg=colors["bg"])
        self._draw(active=False)

    def _draw(self, active: bool) -> None:
        self.delete("all")
        fill = self._colors["button_active"] if active else self._colors["button_bg"]
        # Measure text
        probe = self.create_text(0, 0, text=self._text, font=("Segoe UI", 10), anchor="nw")
        bbox = self.bbox(probe)
        self.delete(probe)
        tw = bbox[2] - bbox[0] if bbox else 40
        th = bbox[3] - bbox[1] if bbox else 14
        w = tw + self._padx * 2
        h = th + self._pady * 2
        self.configure(width=w, height=h)
        draw_rounded_rect(
            self,
            1,
            1,
            w - 1,
            h - 1,
            self._radius,
            fill,
            self._colors["border"],
            tags=("shape",),
        )
        self.create_text(
            w / 2,
            h / 2,
            text=self._text,
            fill=self._colors["fg"],
            font=("Segoe UI", 10),
            tags=("label",),
        )

    def _on_enter(self, _event=None) -> None:
        self._draw(active=True)

    def _on_leave(self, _event=None) -> None:
        self._draw(active=False)

    def _on_click(self, _event=None) -> None:
        if self._command:
            self._command()
