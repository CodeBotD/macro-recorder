"""Record keyboard and mouse input and replay it on Windows."""

import ctypes
import json
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


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


def hotkey_name(key):
    if key == Key.f6 or getattr(key, "vk", None) == 0x75:
        return "f6"
    if key == Key.f7 or getattr(key, "vk", None) == 0x76:
        return "f7"
    if key == Key.f8 or getattr(key, "vk", None) == 0x77:
        return "f8"
    return None


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
        self.pass_index = 0
        self.pass_total = 1
        self.pass_loop = False
        self.dirty = False
        self.ui_queue = queue.Queue()

        self.mouse_ctl = mouse.Controller()
        self.key_ctl = keyboard.Controller()
        self.mouse_listener = None
        self.key_listener = None

        self.root = tk.Tk()
        self.root.title("Macro recorder")
        self.root.minsize(420, 260)
        self.status_var = tk.StringVar(value="Idle — 0 events")
        self.repeat_var = tk.StringVar(value="1")
        self.loop_var = tk.BooleanVar(value=False)
        self._build_ui()
        self._start_listeners()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(50, self._pump)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, textvariable=self.status_var, font=("Segoe UI", 12)).pack(anchor="w")
        ttk.Label(
            frame,
            text="F6 record    F7 play    F8 stop",
        ).pack(anchor="w", pady=(4, 12))

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
        ttk.Button(buttons, text="Record (F6)", command=self.toggle_record).pack(side="left")
        ttk.Button(buttons, text="Play (F7)", command=self.toggle_playback).pack(side="left", padx=8)
        ttk.Button(buttons, text="Stop (F8)", command=self.stop_all).pack(side="left")

        files = ttk.Frame(frame)
        files.pack(fill="x")
        ttk.Button(files, text="Save", command=self.save_recording).pack(side="left")
        ttk.Button(files, text="Load", command=self.load_recording).pack(side="left", padx=8)

        ttk.Label(
            frame,
            wraplength=390,
            text="Hooks miss elevated apps. Run this recorder as administrator to control them.",
        ).pack(anchor="w", pady=(16, 0))

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
        name = hotkey_name(key)
        if name:
            if name in self.hotkeys_down:
                return
            self.hotkeys_down.add(name)
            self._post(lambda hotkey=name: self.handle_hotkey(hotkey))
            return
        self._record_key(key, True)

    def on_key_release(self, key):
        name = hotkey_name(key)
        if name:
            self.hotkeys_down.discard(name)
            return
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
        if name == "f6":
            self.toggle_record()
        elif name == "f7":
            self.toggle_playback()
        elif name == "f8":
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

    def save_recording(self):
        with self.lock:
            if self.state == "recording":
                self._flush_pending_move()
            payload = {"events": [dict(event) for event in self.events]}
        if not payload["events"]:
            self.status_var.set("Nothing to save")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".json",
            filetypes=[("JSON recording", "*.json")],
            title="Save recording",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        self.refresh_status()

    def load_recording(self):
        with self.lock:
            if self.state != "idle":
                busy = True
            else:
                busy = False
        if busy:
            messagebox.showinfo("Macro recorder", "Stop recording or playback before loading.")
            return
        path = filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("JSON recording", "*.json")],
            title="Load recording",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            events = payload["events"]
            if not isinstance(events, list) or not all(valid_event(event) for event in events):
                raise ValueError("invalid events")
        except Exception:
            messagebox.showerror("Macro recorder", "That file is not a recording.")
            return
        with self.lock:
            if self.state != "idle":
                return
            self.events = events
            self.pending_pos = None
        self.refresh_status()

    def on_close(self):
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
    app = RecorderApp()
    app.run()


if __name__ == "__main__":
    main()
