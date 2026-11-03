"""Record keyboard and mouse input and replay it on Windows."""

import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import appdata
import hotkeys
import theme
import updater
from version import APP_VERSION


def enable_dpi_awareness():
    """Use physical pixels so cursor positions match on every monitor."""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        shcore = ctypes.windll.shcore
        shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
        shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


enable_dpi_awareness()

from pynput import keyboard, mouse
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button

MOVE_INTERVAL = 1 / 60
UPDATE_INTERVAL_MS = 30 * 60 * 1000
MACRO_LIST_MAX_ROWS = 8
UNDO_LIMIT = 30


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def encode_key(key):
    if isinstance(key, Key):
        return f"key:{key.name}"
    char = getattr(key, "char", None)
    if char:
        return "char:" + char
    vk = getattr(key, "vk", None)
    if vk is not None:
        return f"vk:{int(vk)}"
    return None


def decode_key(token):
    kind, _, value = token.partition(":")
    if kind == "key":
        return getattr(Key, value)
    if kind == "char":
        return KeyCode.from_char(value)
    if kind == "vk":
        return KeyCode.from_vk(int(value))
    raise ValueError(token)


def wait_for(seconds, stop_event):
    if stop_event.is_set():
        return False
    deadline = time.perf_counter() + max(0.0, float(seconds))
    while True:
        if stop_event.is_set():
            return False
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return True
        time.sleep(min(0.05, remaining))


def valid_event(event):
    if not isinstance(event, dict):
        return False
    if event.get("type") not in {"move", "click", "scroll", "key"}:
        return False
    return isinstance(event.get("dt"), (int, float))


def read_recording(path):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    events = payload["events"]
    if not isinstance(events, list) or not all(valid_event(event) for event in events):
        raise ValueError("invalid events")
    return events


class RecorderApp:
    def __init__(self):
        self.events = []
        self.lock = threading.Lock()
        self.state = "idle"
        self.stop_event = threading.Event()
        self.play_thread = None
        self.last_event_time = None
        self.last_move_time = 0.0
        self.last_recorded_pos = None
        self.pending_pos = None
        self.hotkeys_down = set()
        self.mods_down = set()
        self.pass_index = 0
        self.pass_total = 1
        self.pass_loop = False
        self.dirty = False
        self.ui_queue = queue.Queue()
        self.current_macro = None
        self.settings = appdata.load_settings()
        self.hotkey_map = hotkeys.normalize_hotkeys(self.settings.get("hotkeys"))
        self.pending_update = None
        self.update_in_progress = False
        self._update_timer = None
        self._manual_update_check = False
        self.declined_update_version = None
        self.window_focused = True
        self._capture_action = None
        self._capture_callback = None
        self._rounded_buttons = []
        self._colors = theme.LIGHT
        self._undo_stack = []
        self._redo_stack = []

        self.mouse_ctl = mouse.Controller()
        self.key_ctl = keyboard.Controller()
        self.mouse_listener = None
        self.key_listener = None

        self.root = tk.Tk()
        self.root.title(f"Macro recorder v{APP_VERSION}")
        self.root.minsize(480, 420)
        self._set_app_icon()
        self.status_var = tk.StringVar(value="Idle — 0 events")
        self.hotkey_hint_var = tk.StringVar(value=hotkeys.format_hotkeys_hint(self.hotkey_map))
        self.repeat_var = tk.StringVar(
            value=str(appdata.clamp_repeat(self.settings.get("repeat", 1)))
        )
        self.loop_var = tk.BooleanVar(
            value=bool(self.settings.get("loop_until_stopped", False))
        )
        self.dark_mode_var = tk.BooleanVar(value=bool(self.settings.get("dark_mode")))
        self.check_updates_var = tk.BooleanVar(
            value=bool(self.settings.get("check_for_updates", True))
        )
        self.always_on_top_var = tk.BooleanVar(
            value=bool(self.settings.get("always_on_top", False))
        )
        self._build_ui()
        self._apply_theme()
        self._apply_always_on_top()
        self._refresh_hotkey_labels()
        self._refresh_macro_list(select_name=self.settings.get("last_macro"))
        self.repeat_var.trace_add("write", self._on_playback_settings_change)
        self.loop_var.trace_add("write", self._on_playback_settings_change)
        self._start_listeners()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.bind("<FocusIn>", self._on_focus_in)
        self.root.bind("<FocusOut>", self._on_focus_out)
        self.root.after(50, self._pump)
        self.root.after(200, self._autoload_last_macro)
        self.root.after(1500, self._start_update_schedule)

    def _set_app_icon(self):
        png = resource_path("assets", "app-icon.png")
        ico = resource_path("assets", "app-icon.ico")
        try:
            if png.is_file():
                self._icon_image = tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._icon_image)
        except Exception:
            self._icon_image = None
        try:
            if ico.is_file():
                self.root.iconbitmap(default=str(ico))
        except Exception:
            pass

    def _hwnd(self) -> int:
        try:
            return int(self.root.winfo_id())
        except Exception:
            return 0

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=14)
        frame.pack(fill="both", expand=True)
        self.main_frame = frame

        ttk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 12)).pack(anchor="w")
        ttk.Label(frame, textvariable=self.hotkey_hint_var, style="Muted.TLabel").pack(
            anchor="w", pady=(4, 12)
        )

        options = ttk.Frame(frame)
        options.pack(fill="x")
        ttk.Label(options, text="Repeat").pack(side="left")
        repeat = ttk.Spinbox(
            options,
            from_=1,
            to=9999,
            textvariable=self.repeat_var,
            width=8,
        )
        repeat.pack(side="left", padx=(8, 16))
        ttk.Checkbutton(
            options,
            text="Loop until stopped",
            variable=self.loop_var,
        ).pack(side="left")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=16)
        self.record_btn = theme.RoundedButton(
            buttons, text="Record (F6)", command=self.toggle_record, colors=self._colors
        )
        self.record_btn.pack(side="left")
        self.play_btn = theme.RoundedButton(
            buttons, text="Play (F7)", command=self.toggle_playback, colors=self._colors
        )
        self.play_btn.pack(side="left", padx=8)
        self.stop_btn = theme.RoundedButton(
            buttons, text="Stop (F8)", command=self.stop_all, colors=self._colors
        )
        self.stop_btn.pack(side="left")
        self._rounded_buttons.extend([self.record_btn, self.play_btn, self.stop_btn])

        self.settings_btn = theme.RoundedButton(
            buttons, text="Settings", command=self._open_settings_menu, colors=self._colors
        )
        self.settings_btn.pack(side="right")
        self._rounded_buttons.append(self.settings_btn)

        self.settings_menu = tk.Menu(self.root, tearoff=0)
        self.settings_menu.add_checkbutton(
            label="Dark mode",
            variable=self.dark_mode_var,
            command=self._on_dark_mode_toggle,
        )
        self.settings_menu.add_checkbutton(
            label="Always on top",
            variable=self.always_on_top_var,
            command=self._on_always_on_top_toggle,
        )
        self.settings_menu.add_checkbutton(
            label="Automatically check for updates",
            variable=self.check_updates_var,
            command=self._on_check_updates_toggle,
        )
        self.settings_menu.add_command(
            label="Check now…",
            command=self._check_for_updates_now,
        )
        self.settings_menu.add_separator()
        self.settings_menu.add_command(
            label="Change keybinds…",
            command=self._open_keybind_dialog,
        )
        self.settings_menu.add_command(
            label="Open app folder…",
            command=self._open_app_folder,
        )

        self.macros_panel = theme.RoundedPanel(frame, self._colors, radius=theme.CORNER_RADIUS)
        self.macros_panel.pack(fill="x", pady=(0, 8))
        library = self.macros_panel.body

        ttk.Label(library, text="Macros", style="Card.TLabel", font=("Segoe UI", 10, "bold")).pack(
            anchor="w", pady=(0, 6)
        )

        self.list_row = tk.Frame(library, bg=self._colors["panel"], highlightthickness=0)
        self.list_row.pack(fill="x")
        self.macro_list = tk.Listbox(self.list_row, height=1, exportselection=False)
        self.macro_scroll = ttk.Scrollbar(
            self.list_row, orient="vertical", command=self.macro_list.yview
        )
        self.macro_list.configure(yscrollcommand=self.macro_scroll.set)
        self.macro_list.pack(side="left", fill="x", expand=True)
        self.macro_list.bind("<Double-Button-1>", lambda _e: self.load_selected_macro())

        self.file_btns = tk.Frame(library, bg=self._colors["panel"], highlightthickness=0)
        self.file_btns.pack(fill="x", pady=(8, 0))
        file_btns = self.file_btns
        for text, cmd, padx in (
            ("Save", self.save_macro, (0, 6)),
            ("Save As", self.save_macro_as, (0, 6)),
            ("Load", self.load_selected_macro, (0, 6)),
            ("Delete", self.delete_macro, (0, 6)),
            ("Export…", self.export_macro, (6, 6)),
            ("Import…", self.import_macro, (0, 6)),
            ("Undo", self.undo_library, (6, 6)),
            ("Redo", self.redo_library, (0, 0)),
        ):
            btn = theme.RoundedButton(
                file_btns, text=text, command=cmd, colors=self._colors, padx=10, pady=5
            )
            btn.pack(side="left", padx=padx)
            self._rounded_buttons.append(btn)

        ttk.Label(
            frame,
            wraplength=440,
            style="Muted.TLabel",
            text="Hooks miss elevated apps. Run this recorder as administrator to control them.",
        ).pack(anchor="w", pady=(8, 0))

    def _open_settings_menu(self):
        try:
            self.settings_menu.tk_popup(
                self.settings_btn.winfo_rootx(),
                self.settings_btn.winfo_rooty() + self.settings_btn.winfo_height(),
            )
        finally:
            self.settings_menu.grab_release()

    def _apply_theme(self):
        self._colors = theme.apply_theme(
            self.root, bool(self.dark_mode_var.get()), self.macro_list
        )
        if hasattr(self, "macros_panel"):
            self.macros_panel.set_colors(self._colors)
        if hasattr(self, "list_row"):
            self.list_row.configure(bg=self._colors["panel"])
        if hasattr(self, "file_btns"):
            self.file_btns.configure(bg=self._colors["panel"])
        for btn in self._rounded_buttons:
            btn.set_colors(self._colors)
        try:
            self.settings_menu.configure(
                bg=self._colors["panel"],
                fg=self._colors["fg"],
                activebackground=self._colors["select_bg"],
                activeforeground=self._colors["select_fg"],
            )
        except tk.TclError:
            pass

    def _persist_settings(self):
        self.settings["dark_mode"] = bool(self.dark_mode_var.get())
        self.settings["check_for_updates"] = bool(self.check_updates_var.get())
        self.settings["always_on_top"] = bool(self.always_on_top_var.get())
        self.settings["last_macro"] = self.current_macro
        self.settings["hotkeys"] = hotkeys.normalize_hotkeys(self.hotkey_map)
        self.settings["repeat"] = appdata.clamp_repeat(self.repeat_var.get())
        self.settings["loop_until_stopped"] = bool(self.loop_var.get())
        appdata.save_settings(self.settings)

    def _on_dark_mode_toggle(self):
        self._apply_theme()
        self._persist_settings()

    def _apply_always_on_top(self):
        try:
            self.root.attributes("-topmost", bool(self.always_on_top_var.get()))
        except tk.TclError:
            pass

    def _on_always_on_top_toggle(self):
        self._apply_always_on_top()
        self._persist_settings()

    def _open_app_folder(self):
        path = appdata.app_root()
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            messagebox.showerror(
                "Macro recorder",
                f"Could not open folder:\n{path}",
                parent=self.root,
            )

    def _on_playback_settings_change(self, *_args):
        self._persist_settings()

    def _on_check_updates_toggle(self):
        enabled = bool(self.check_updates_var.get())
        self._persist_settings()
        if not enabled:
            self.pending_update = None
            self._cancel_update_timer()
        else:
            self._start_update_schedule()

    def _refresh_hotkey_labels(self):
        self.hotkey_hint_var.set(hotkeys.format_hotkeys_hint(self.hotkey_map))
        self.record_btn.set_text(f"Record ({hotkeys.format_binding(self.hotkey_map['record'])})")
        self.play_btn.set_text(f"Play ({hotkeys.format_binding(self.hotkey_map['play'])})")
        self.stop_btn.set_text(f"Stop ({hotkeys.format_binding(self.hotkey_map['stop'])})")

    def _set_hotkeys(self, new_map: dict) -> bool:
        error = hotkeys.validate_hotkeys(new_map, hwnd=self._hwnd())
        if error:
            messagebox.showwarning("Keybind in use", error, parent=self.root)
            return False
        self.hotkey_map = hotkeys.normalize_hotkeys(new_map)
        self.hotkeys_down.clear()
        self._refresh_hotkey_labels()
        self._persist_settings()
        return True

    def _open_keybind_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Change keybinds")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(bg=self._colors["bg"])

        draft = {action: dict(binding) for action, binding in self.hotkey_map.items()}
        labels = {}
        capture_note = tk.StringVar(value="Click a row, then press the new key combo.")

        outer = ttk.Frame(dialog, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, textvariable=capture_note).pack(anchor="w", pady=(0, 10))

        rows = ttk.Frame(outer)
        rows.pack(fill="x")

        def begin_capture(action: str):
            self._capture_action = action
            self._capture_callback = on_captured
            capture_note.set(f"Press a combo for {hotkeys.ACTION_LABELS[action]}… (Esc to cancel)")

        def on_captured(binding: dict | None):
            action = self._capture_action
            self._capture_action = None
            self._capture_callback = None
            if action is None:
                return
            if binding is None:
                capture_note.set("Capture cancelled.")
                return
            draft[action] = binding
            labels[action].configure(text=hotkeys.format_binding(binding))
            capture_note.set("Click a row, then press the new key combo.")

        for action in ("record", "play", "stop"):
            row = ttk.Frame(rows)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=hotkeys.ACTION_LABELS[action], width=10).pack(side="left")
            value = ttk.Label(
                row,
                text=hotkeys.format_binding(draft[action]),
                width=18,
                relief="solid",
                padding=6,
            )
            value.pack(side="left", padx=8)
            labels[action] = value
            ttk.Button(
                row,
                text="Capture",
                command=lambda a=action: begin_capture(a),
            ).pack(side="left")

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(14, 0))

        def apply_and_close():
            if self._set_hotkeys(draft):
                dialog.destroy()

        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Apply", command=apply_and_close).pack(side="right", padx=(0, 8))

        def on_dialog_close():
            self._capture_action = None
            self._capture_callback = None
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_dialog_close)
        dialog.bind("<Escape>", lambda _e: on_dialog_close())

    def _update_macro_scrollbar(self, count: int):
        if count > MACRO_LIST_MAX_ROWS:
            if not self.macro_scroll.winfo_manager():
                self.macro_scroll.pack(side="right", fill="y")
        else:
            if self.macro_scroll.winfo_manager():
                self.macro_scroll.pack_forget()

    def _refresh_macro_list(self, select_name=None):
        names = appdata.list_macros()
        self.macro_list.delete(0, tk.END)
        for name in names:
            self.macro_list.insert(tk.END, name)
        self.macro_list.configure(height=max(1, min(len(names), MACRO_LIST_MAX_ROWS)))
        self._update_macro_scrollbar(len(names))
        target = select_name or self.current_macro
        if target and target in names:
            index = names.index(target)
            self.macro_list.selection_clear(0, tk.END)
            self.macro_list.selection_set(index)
            self.macro_list.see(index)

    def _selected_macro_name(self):
        selection = self.macro_list.curselection()
        if not selection:
            return None
        return self.macro_list.get(selection[0])

    def _set_current_macro(self, name):
        self.current_macro = name
        self._persist_settings()
        self._refresh_macro_list(select_name=name)

    def _recording_payload(self):
        with self.lock:
            if self.state == "recording":
                self._flush_pending_move()
            return {"events": [dict(event) for event in self.events]}

    def _push_undo(self, entry: dict):
        self._undo_stack.append(entry)
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _apply_library_entry(self, name: str, content: str | None, was_current: bool):
        path = appdata.macro_path(name)
        if content is None:
            if path.is_file():
                path.unlink()
            if self.current_macro == name or was_current:
                self.current_macro = None
                self.settings["last_macro"] = None
                with self.lock:
                    self.events = []
                    self.pending_pos = None
                self._persist_settings()
            self._refresh_macro_list()
        else:
            path.write_text(content, encoding="utf-8")
            if was_current or self.current_macro == name:
                try:
                    events = read_recording(path)
                except Exception:
                    events = None
                if events is not None:
                    with self.lock:
                        self.events = events
                        self.pending_pos = None
                    self._set_current_macro(path.name)
                else:
                    self._refresh_macro_list(select_name=path.name)
            else:
                self._refresh_macro_list(select_name=path.name)
        self.refresh_status()

    def undo_library(self):
        if not self._undo_stack:
            self.status_var.set("Nothing to undo")
            return
        entry = self._undo_stack.pop()
        self._apply_library_entry(entry["name"], entry["before"], entry.get("was_current", False))
        self._redo_stack.append(entry)

    def redo_library(self):
        if not self._redo_stack:
            self.status_var.set("Nothing to redo")
            return
        entry = self._redo_stack.pop()
        self._apply_library_entry(entry["name"], entry["after"], entry.get("was_current", False))
        self._undo_stack.append(entry)

    def _write_macro_file(self, name, payload):
        path = appdata.macro_path(name)
        before = path.read_text(encoding="utf-8") if path.is_file() else None
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        after = path.read_text(encoding="utf-8")
        self._push_undo(
            {
                "name": path.name,
                "before": before,
                "after": after,
                "was_current": True,
            }
        )
        self._set_current_macro(path.name)
        self.refresh_status()

    def save_macro(self):
        payload = self._recording_payload()
        if not payload["events"]:
            self.status_var.set("Nothing to save")
            return
        if self.current_macro:
            self._write_macro_file(self.current_macro, payload)
            return
        self.save_macro_as()

    def save_macro_as(self):
        payload = self._recording_payload()
        if not payload["events"]:
            self.status_var.set("Nothing to save")
            return
        suggested = Path(self.current_macro).stem if self.current_macro else "macro"
        name = simpledialog.askstring(
            "Save As",
            "Macro name:",
            initialvalue=suggested,
            parent=self.root,
        )
        safe = appdata.sanitize_macro_name(name or "")
        if not safe:
            return
        path = appdata.macro_path(safe)
        if path.exists():
            if not messagebox.askyesno(
                "Macro recorder",
                f'"{safe}" already exists. Overwrite?',
                parent=self.root,
            ):
                return
        self._write_macro_file(safe, payload)

    def delete_macro(self):
        with self.lock:
            busy = self.state != "idle"
        if busy:
            messagebox.showinfo(
                "Macro recorder",
                "Stop recording or playback before deleting.",
                parent=self.root,
            )
            return
        name = self._selected_macro_name() or self.current_macro
        if not name:
            messagebox.showinfo(
                "Macro recorder",
                "Select a macro to delete.",
                parent=self.root,
            )
            return
        path = appdata.macro_path(name)
        if not path.is_file():
            messagebox.showinfo(
                "Macro recorder",
                "That macro file was not found.",
                parent=self.root,
            )
            self._refresh_macro_list()
            return
        if not messagebox.askyesno(
            "Macro recorder",
            f'Delete "{path.name}"?',
            parent=self.root,
        ):
            return
        before = path.read_text(encoding="utf-8")
        was_current = self.current_macro == path.name
        if not appdata.delete_macro(path.name):
            messagebox.showerror(
                "Macro recorder",
                "Could not delete that macro.",
                parent=self.root,
            )
            return
        self._push_undo(
            {
                "name": path.name,
                "before": before,
                "after": None,
                "was_current": was_current,
            }
        )
        if was_current:
            self.current_macro = None
            self.settings["last_macro"] = None
            with self.lock:
                self.events = []
                self.pending_pos = None
            self._persist_settings()
        self._refresh_macro_list()
        self.refresh_status()

    def load_selected_macro(self):
        name = self._selected_macro_name()
        if not name:
            messagebox.showinfo("Macro recorder", "Select a macro to load.", parent=self.root)
            return
        self._load_macro_file(appdata.macro_path(name), set_current=True)

    def _load_macro_file(self, path, set_current):
        with self.lock:
            busy = self.state != "idle"
        if busy:
            messagebox.showinfo(
                "Macro recorder",
                "Stop recording or playback before loading.",
                parent=self.root,
            )
            return False
        try:
            events = read_recording(path)
        except Exception:
            messagebox.showerror(
                "Macro recorder",
                "That file is not a recording.",
                parent=self.root,
            )
            return False
        with self.lock:
            if self.state != "idle":
                return False
            self.events = events
            self.pending_pos = None
        if set_current:
            self._set_current_macro(Path(path).name)
        self.refresh_status()
        return True

    def _autoload_last_macro(self):
        name = self.settings.get("last_macro")
        if not name:
            return
        path = appdata.macro_path(name)
        if path.is_file():
            self._load_macro_file(path, set_current=True)

    def export_macro(self):
        payload = self._recording_payload()
        if not payload["events"]:
            name = self._selected_macro_name() or self.current_macro
            if not name:
                self.status_var.set("Nothing to export")
                return
            path = appdata.macro_path(name)
            if not path.is_file():
                self.status_var.set("Nothing to export")
                return
            try:
                events = read_recording(path)
            except Exception:
                messagebox.showerror(
                    "Macro recorder",
                    "That file is not a recording.",
                    parent=self.root,
                )
                return
            payload = {"events": events}
            initial = name
        else:
            initial = self.current_macro or "macro.json"
        dest = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".json",
            filetypes=[("JSON recording", "*.json")],
            initialfile=initial,
            title="Export macro",
        )
        if not dest:
            return
        with open(dest, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def import_macro(self):
        with self.lock:
            busy = self.state != "idle"
        if busy:
            messagebox.showinfo(
                "Macro recorder",
                "Stop recording or playback before importing.",
                parent=self.root,
            )
            return
        source = filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("JSON recording", "*.json")],
            title="Import macro",
        )
        if not source:
            return
        try:
            events = read_recording(source)
        except Exception:
            messagebox.showerror(
                "Macro recorder",
                "That file is not a recording.",
                parent=self.root,
            )
            return
        suggested = Path(source).stem
        name = simpledialog.askstring(
            "Import",
            "Save imported macro as:",
            initialvalue=suggested,
            parent=self.root,
        )
        safe = appdata.sanitize_macro_name(name or "")
        if not safe:
            return
        path = appdata.macro_path(safe)
        if path.exists():
            if not messagebox.askyesno(
                "Macro recorder",
                f'"{safe}" already exists. Overwrite?',
                parent=self.root,
            ):
                return
        payload = {"events": events}
        with self.lock:
            self.events = [dict(event) for event in events]
            self.pending_pos = None
        self._write_macro_file(safe, payload)

    def _start_listeners(self):
        self.mouse_listener = mouse.Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll,
        )
        self.key_listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release,
        )
        self.mouse_listener.start()
        self.key_listener.start()

    def _pump(self):
        try:
            while True:
                fn = self.ui_queue.get_nowait()
                try:
                    fn()
                except tk.TclError:
                    return
        except queue.Empty:
            pass
        if self.dirty:
            self.dirty = False
            self.refresh_status()
        if self.root.winfo_exists():
            self.root.after(50, self._pump)

    def refresh_status(self):
        with self.lock:
            state = self.state
            count = len(self.events)
            pass_index = self.pass_index
            pass_total = self.pass_total
            looping = self.pass_loop
        if state == "recording":
            text = f"Recording — {count} events"
        elif state == "playing":
            if looping:
                text = f"Playing — loop {pass_index}"
            else:
                text = f"Playing — pass {pass_index} of {pass_total}"
        else:
            text = f"Idle — {count} events"
        if self.current_macro:
            text = f"{text}  [{self.current_macro}]"
        self.status_var.set(text)

    def _post(self, fn):
        self.ui_queue.put(fn)

    def _mark_dirty(self):
        self.dirty = True

    def _append(self, body):
        now = time.perf_counter()
        dt = 0.0 if self.last_event_time is None else now - self.last_event_time
        self.last_event_time = now
        self.events.append({"dt": dt, **body})

    def _flush_pending_move(self):
        if self.pending_pos is None or self.pending_pos == self.last_recorded_pos:
            self.pending_pos = None
            return
        x, y = self.pending_pos
        self._append({"type": "move", "x": x, "y": y})
        self.last_recorded_pos = self.pending_pos
        self.pending_pos = None

    def _remember_move(self, x, y, force):
        pos = (int(round(x)), int(round(y)))
        self.pending_pos = pos
        now = time.perf_counter()
        if not force and now - self.last_move_time < MOVE_INTERVAL:
            return
        if pos == self.last_recorded_pos:
            self.pending_pos = None
            return
        self._append({"type": "move", "x": pos[0], "y": pos[1]})
        self.last_recorded_pos = pos
        self.last_move_time = now
        self.pending_pos = None

    def on_move(self, x, y):
        with self.lock:
            if self.state != "recording":
                return
            self._remember_move(x, y, force=False)
        self._mark_dirty()

    def on_click(self, x, y, button, pressed):
        name = getattr(button, "name", None)
        if not name or name == "unknown":
            return
        with self.lock:
            if self.state != "recording":
                return
            self._remember_move(x, y, force=True)
            self._append(
                {
                    "type": "click",
                    "x": int(round(x)),
                    "y": int(round(y)),
                    "button": name,
                    "pressed": bool(pressed),
                }
            )
        self._mark_dirty()

    def on_scroll(self, x, y, dx, dy):
        with self.lock:
            if self.state != "recording":
                return
            self._remember_move(x, y, force=True)
            self._append(
                {
                    "type": "scroll",
                    "x": int(round(x)),
                    "y": int(round(y)),
                    "dx": int(dx),
                    "dy": int(dy),
                }
            )
        self._mark_dirty()

    def on_key_press(self, key):
        mod = hotkeys.modifier_name(key)
        if mod:
            self.mods_down.add(mod)
            if self._capture_action:
                return
            return

        token = hotkeys.key_token(key)
        if token is None:
            return

        if self._capture_action and self._capture_callback:
            if token in {"esc", "escape"} and not self.mods_down:
                callback = self._capture_callback
                self._post(lambda: callback(None))
                return
            binding = hotkeys.binding_from_mods_and_key(self.mods_down, token)
            if binding:
                callback = self._capture_callback
                self._post(lambda b=binding: callback(b))
            return

        action = hotkeys.match_action(self.hotkey_map, self.mods_down, token)
        if action:
            if action in self.hotkeys_down:
                return
            self.hotkeys_down.add(action)
            self._post(lambda hotkey=action: self.handle_hotkey(hotkey))
            return

        self._record_key(key, True)

    def on_key_release(self, key):
        mod = hotkeys.modifier_name(key)
        if mod:
            self.mods_down.discard(mod)
            if self._capture_action:
                return
            return

        token = hotkeys.key_token(key)
        if token is None:
            return

        if self._capture_action:
            return

        action = hotkeys.match_action(self.hotkey_map, self.mods_down, token)
        if action:
            self.hotkeys_down.discard(action)
            return
        # Also clear if the action key alone matches any binding key
        for name, binding in self.hotkey_map.items():
            if binding["key"] == token:
                self.hotkeys_down.discard(name)

        self._record_key(key, False)

    def _record_key(self, key, pressed):
        token = encode_key(key)
        if token is None:
            return
        with self.lock:
            if self.state != "recording":
                return
            self._append({"type": "key", "key": token, "pressed": bool(pressed)})
        self._mark_dirty()

    def handle_hotkey(self, name):
        if name == "record":
            self.toggle_record()
        elif name == "play":
            self.toggle_playback()
        elif name == "stop":
            self.stop_all()

    def toggle_record(self):
        with self.lock:
            if self.state == "playing":
                return
            if self.state == "recording":
                self._flush_pending_move()
                self.state = "idle"
            else:
                self.events.clear()
                self.last_event_time = None
                self.last_move_time = 0.0
                self.last_recorded_pos = None
                self.pending_pos = None
                self.state = "recording"
        self.refresh_status()
        self._maybe_apply_pending_update()

    def _repeat_settings(self):
        try:
            repeat = int(self.repeat_var.get())
        except (tk.TclError, ValueError):
            repeat = 1
        if repeat < 1:
            repeat = 1
        if repeat > 9999:
            repeat = 9999
        return repeat, bool(self.loop_var.get())

    def toggle_playback(self):
        with self.lock:
            if self.state == "playing":
                self.stop_event.set()
                return
            if self.state == "recording":
                self._flush_pending_move()
                self.state = "idle"
            if not self.events:
                self.status_var.set("Nothing recorded")
                return
            events = [dict(event) for event in self.events]
            self.state = "playing"
            self.stop_event.clear()
        repeat, loop = self._repeat_settings()
        self.play_thread = threading.Thread(
            target=self._play,
            args=(events, repeat, loop),
            daemon=True,
        )
        self.play_thread.start()
        self.refresh_status()

    def stop_all(self):
        self.stop_event.set()
        with self.lock:
            if self.state == "recording":
                self._flush_pending_move()
                self.state = "idle"
        self.refresh_status()
        self._maybe_apply_pending_update()

    def _play(self, events, repeat, loop):
        try:
            pass_index = 0
            while not self.stop_event.is_set():
                pass_index += 1
                if not loop and pass_index > repeat:
                    break
                with self.lock:
                    self.pass_index = pass_index
                    self.pass_total = repeat
                    self.pass_loop = loop
                self._mark_dirty()
                if not self._play_once(events):
                    break
                if not loop and pass_index >= repeat:
                    break
        finally:
            with self.lock:
                if self.state == "playing":
                    self.state = "idle"
            self._mark_dirty()
            self._post(self._maybe_apply_pending_update)

    def _play_once(self, events):
        held_keys = []
        held_buttons = []
        try:
            for event in events:
                if not wait_for(event.get("dt", 0), self.stop_event):
                    return False
                try:
                    self._emit(event, held_keys, held_buttons)
                except Exception:
                    continue
            return not self.stop_event.is_set()
        finally:
            self._release_held(held_keys, held_buttons)

    def _emit(self, event, held_keys, held_buttons):
        kind = event["type"]
        if kind == "move":
            self.mouse_ctl.position = (event["x"], event["y"])
        elif kind == "click":
            self.mouse_ctl.position = (event["x"], event["y"])
            button = getattr(Button, event["button"])
            if event["pressed"]:
                self.mouse_ctl.press(button)
                if button not in held_buttons:
                    held_buttons.append(button)
            else:
                self.mouse_ctl.release(button)
                if button in held_buttons:
                    held_buttons.remove(button)
        elif kind == "scroll":
            self.mouse_ctl.position = (event["x"], event["y"])
            self.mouse_ctl.scroll(int(event["dx"]), int(event["dy"]))
        elif kind == "key":
            key = decode_key(event["key"])
            if event["pressed"]:
                self.key_ctl.press(key)
                held_keys.append(key)
            else:
                self.key_ctl.release(key)
                if key in held_keys:
                    held_keys.remove(key)

    def _release_held(self, held_keys, held_buttons):
        for key in reversed(held_keys):
            try:
                self.key_ctl.release(key)
            except Exception:
                pass
        held_keys.clear()
        for button in reversed(held_buttons):
            try:
                self.mouse_ctl.release(button)
            except Exception:
                pass
        held_buttons.clear()

    def _on_focus_in(self, _event=None):
        self.window_focused = True
        self._maybe_apply_pending_update()

    def _on_focus_out(self, _event=None):
        try:
            focused = self.root.focus_displayof()
        except tk.TclError:
            focused = None
        self.window_focused = focused is not None

    def _cancel_update_timer(self):
        if self._update_timer is not None:
            try:
                self.root.after_cancel(self._update_timer)
            except Exception:
                pass
            self._update_timer = None

    def _start_update_schedule(self):
        self._cancel_update_timer()
        if not bool(self.check_updates_var.get()):
            return
        self._run_update_check_async(manual=False)
        self._update_timer = self.root.after(UPDATE_INTERVAL_MS, self._on_update_timer)

    def _on_update_timer(self):
        self._update_timer = None
        if not bool(self.check_updates_var.get()):
            return
        self._run_update_check_async(manual=False)
        self._update_timer = self.root.after(UPDATE_INTERVAL_MS, self._on_update_timer)

    def _check_for_updates_now(self):
        if self.update_in_progress or self._manual_update_check:
            return
        self.status_var.set("Checking for updates…")
        self._run_update_check_async(manual=True)

    def _run_update_check_async(self, *, manual: bool):
        if not manual and not bool(self.check_updates_var.get()):
            return
        if manual:
            self._manual_update_check = True

        def worker():
            pending = None
            error = False
            try:
                pending = updater.check_latest()
            except Exception:
                error = True
            self._post(
                lambda: self._on_update_check_result(pending, manual=manual, error=error)
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_result(self, pending, *, manual: bool = False, error: bool = False):
        if manual:
            self._manual_update_check = False
            if error:
                messagebox.showerror(
                    "Updates",
                    "Couldn't check for updates. Check your connection and try again.",
                    parent=self.root,
                )
                self.refresh_status()
                return
            if pending is None:
                messagebox.showinfo(
                    "Updates",
                    f"You're up to date (v{APP_VERSION}).",
                    parent=self.root,
                )
                self.refresh_status()
                return
            if self.declined_update_version == pending.version:
                self.declined_update_version = None
            self.pending_update = pending
            self._maybe_apply_pending_update(manual=True)
            return

        if not bool(self.check_updates_var.get()):
            self.pending_update = None
            return
        if error or pending is None:
            return
        if pending.version == self.declined_update_version:
            return
        self.pending_update = pending
        self._maybe_apply_pending_update()

    def _maybe_apply_pending_update(self, manual: bool = False):
        if self.update_in_progress:
            return
        if not manual and not bool(self.check_updates_var.get()):
            return
        if self.pending_update is None:
            return
        if not manual:
            if not self.window_focused:
                return
            with self.lock:
                idle = self.state == "idle"
            if not idle:
                return
            if self.pending_update.version == self.declined_update_version:
                return

        pending = self.pending_update
        if not messagebox.askyesno(
            "Update available",
            f"Version {pending.version} is available.\n\nUpdate now?",
            parent=self.root,
        ):
            self.declined_update_version = pending.version
            self.pending_update = None
            return

        self.pending_update = None
        self.declined_update_version = None
        self.update_in_progress = True
        self._begin_update(pending)

    def _begin_update(self, pending):
        dialog = tk.Toplevel(self.root)
        dialog.title("Updating")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        ttk.Label(
            dialog,
            text=f"Updating to v{pending.version}…",
            padding=16,
        ).pack()
        status = tk.StringVar(value="Downloading installer…")
        ttk.Label(dialog, textvariable=status, padding=(16, 0, 16, 16)).pack()
        dialog.update_idletasks()

        def worker():
            msi_path = None
            try:
                msi_path = updater.download_msi(pending.download_url)
                self._post(lambda: status.set("Starting installer…"))
                updater.launch_msi_installer(msi_path)
                self._post(self._quit_for_update)
            except Exception:
                def fail():
                    self.update_in_progress = False
                    try:
                        dialog.destroy()
                    except tk.TclError:
                        pass
                    if msi_path:
                        try:
                            Path(msi_path).unlink(missing_ok=True)
                        except OSError:
                            pass
                    self.status_var.set("Update failed — try again later")

                self._post(fail)

        threading.Thread(target=worker, daemon=True).start()

    def _quit_for_update(self):
        self.on_close()

    def on_close(self):
        self._cancel_update_timer()
        self._persist_settings()
        self.stop_event.set()
        if self.mouse_listener is not None:
            self.mouse_listener.stop()
        if self.key_listener is not None:
            self.key_listener.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if sys.platform != "win32":
        print("This recorder is for Windows.")
        return
    appdata.macros_dir()
    app = RecorderApp()
    app.run()


if __name__ == "__main__":
    main()
