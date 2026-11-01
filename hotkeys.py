"""Hotkey combo parsing, formatting, and Windows conflict checks."""

from __future__ import annotations

import ctypes
from typing import Iterable

from pynput.keyboard import Key, KeyCode

DEFAULT_HOTKEYS = {
    "record": {"mods": [], "key": "f6"},
    "play": {"mods": [], "key": "f7"},
    "stop": {"mods": [], "key": "f8"},
}

ACTION_LABELS = {
    "record": "Record",
    "play": "Play",
    "stop": "Stop",
}

MOD_ORDER = ("ctrl", "alt", "shift", "win")

MOD_KEYS = {
    Key.ctrl,
    Key.ctrl_l,
    Key.ctrl_r,
    Key.alt,
    Key.alt_l,
    Key.alt_r,
    Key.alt_gr,
    Key.shift,
    Key.shift_l,
    Key.shift_r,
    Key.cmd,
    Key.cmd_l,
    Key.cmd_r,
}

# Common Windows / shell shortcuts that should not be remapped.
_WINDOWS_DENY = {
    frozenset({"win", "s"}),
    frozenset({"win", "e"}),
    frozenset({"win", "r"}),
    frozenset({"win", "d"}),
    frozenset({"win", "l"}),
    frozenset({"win", "i"}),
    frozenset({"win", "x"}),
    frozenset({"win", "tab"}),
    frozenset({"win", "a"}),
    frozenset({"win", "v"}),
    frozenset({"win", "g"}),
    frozenset({"win", "h"}),
    frozenset({"win", "k"}),
    frozenset({"win", "n"}),
    frozenset({"win", "p"}),
    frozenset({"win", "u"}),
    frozenset({"win", "w"}),
    frozenset({"win", "z"}),
    frozenset({"win", "period"}),
    frozenset({"win", "comma"}),
    frozenset({"win", "space"}),
    frozenset({"ctrl", "c"}),
    frozenset({"ctrl", "v"}),
    frozenset({"ctrl", "x"}),
    frozenset({"ctrl", "a"}),
    frozenset({"ctrl", "z"}),
    frozenset({"ctrl", "y"}),
    frozenset({"ctrl", "s"}),
    frozenset({"ctrl", "o"}),
    frozenset({"ctrl", "n"}),
    frozenset({"ctrl", "p"}),
    frozenset({"ctrl", "w"}),
    frozenset({"ctrl", "f"}),
    frozenset({"ctrl", "h"}),
    frozenset({"ctrl", "esc"}),
    frozenset({"alt", "tab"}),
    frozenset({"alt", "f4"}),
    frozenset({"alt", "esc"}),
    frozenset({"alt", "space"}),
    frozenset({"ctrl", "shift", "esc"}),
    frozenset({"ctrl", "alt", "delete"}),
}

_VK_MAP = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "page_up": 0x21,
    "page_down": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "period": 0xBE,
    "comma": 0xBC,
    "slash": 0xBF,
    "backslash": 0xDC,
    "semicolon": 0xBA,
    "quote": 0xDE,
    "minus": 0xBD,
    "equal": 0xBB,
    "caps_lock": 0x14,
    "print_screen": 0x2C,
    "scroll_lock": 0x91,
    "pause": 0x13,
    "num_lock": 0x90,
}

for _i in range(1, 13):
    _VK_MAP[f"f{_i}"] = 0x70 + (_i - 1)
for _i in range(10):
    _VK_MAP[str(_i)] = 0x30 + _i
for _code in range(ord("a"), ord("z") + 1):
    _VK_MAP[chr(_code)] = _code - 32


def _canonical_mod(name: str) -> str | None:
    name = (name or "").strip().lower()
    if name in {"ctrl", "control", "ctl"}:
        return "ctrl"
    if name in {"alt", "option", "menu"}:
        return "alt"
    if name in {"shift"}:
        return "shift"
    if name in {"win", "windows", "cmd", "super", "meta"}:
        return "win"
    return None


def _canonical_key(name: str) -> str | None:
    name = (name or "").strip().lower()
    if not name:
        return None
    aliases = {
        "return": "enter",
        "escape": "esc",
        "control_l": "ctrl",
        "control_r": "ctrl",
        "alt_l": "alt",
        "alt_r": "alt",
        "alt_gr": "alt",
        "shift_l": "shift",
        "shift_r": "shift",
        "cmd_l": "win",
        "cmd_r": "win",
        "cmd": "win",
    }
    name = aliases.get(name, name)
    if _canonical_mod(name):
        return None
    if len(name) == 1 and name.isprintable():
        return name
    if name in _VK_MAP:
        return name
    return name


def normalize_binding(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key = _canonical_key(str(raw.get("key", "")))
    if not key:
        return None
    mods: list[str] = []
    seen = set()
    for item in raw.get("mods") or []:
        mod = _canonical_mod(str(item))
        if mod and mod not in seen:
            seen.add(mod)
            mods.append(mod)
    mods = [m for m in MOD_ORDER if m in seen]
    return {"mods": mods, "key": key}


def normalize_hotkeys(raw) -> dict:
    result = {action: dict(binding) for action, binding in DEFAULT_HOTKEYS.items()}
    if not isinstance(raw, dict):
        return result
    for action in DEFAULT_HOTKEYS:
        normalized = normalize_binding(raw.get(action))
        if normalized:
            result[action] = normalized
    return result


def binding_key(binding: dict) -> frozenset[str]:
    parts = set(binding.get("mods") or [])
    parts.add(binding["key"])
    return frozenset(parts)


def format_binding(binding: dict) -> str:
    parts = [m.capitalize() if m != "ctrl" else "Ctrl" for m in binding.get("mods") or []]
    key = binding["key"]
    if len(key) == 1:
        parts.append(key.upper())
    else:
        pretty = {
            "esc": "Esc",
            "enter": "Enter",
            "space": "Space",
            "tab": "Tab",
            "page_up": "Page Up",
            "page_down": "Page Down",
            "print_screen": "Print Screen",
            "caps_lock": "Caps Lock",
            "num_lock": "Num Lock",
            "scroll_lock": "Scroll Lock",
        }
        if key.startswith("f") and key[1:].isdigit():
            parts.append(key.upper())
        else:
            parts.append(pretty.get(key, key.replace("_", " ").title()))
    return "+".join(parts)


def format_hotkeys_hint(hotkeys: dict) -> str:
    return "    ".join(
        f"{format_binding(hotkeys[action])} {ACTION_LABELS[action].lower()}"
        for action in ("record", "play", "stop")
    )


def is_modifier_key(key) -> bool:
    if key in MOD_KEYS:
        return True
    name = getattr(key, "name", None)
    return bool(name and _canonical_mod(name))


def modifier_name(key) -> str | None:
    if key in (Key.ctrl, Key.ctrl_l, Key.ctrl_r):
        return "ctrl"
    if key in (Key.alt, Key.alt_l, Key.alt_r, Key.alt_gr):
        return "alt"
    if key in (Key.shift, Key.shift_l, Key.shift_r):
        return "shift"
    if key in (Key.cmd, Key.cmd_l, Key.cmd_r):
        return "win"
    name = getattr(key, "name", None)
    return _canonical_mod(name) if name else None


def key_token(key) -> str | None:
    if is_modifier_key(key):
        return None
    if isinstance(key, Key):
        return _canonical_key(key.name)
    char = getattr(key, "char", None)
    if char:
        if char.isprintable() and not char.isspace():
            return _canonical_key(char.lower())
        if char == " ":
            return "space"
    vk = getattr(key, "vk", None)
    if vk is not None:
        for name, code in _VK_MAP.items():
            if code == int(vk) and not _canonical_mod(name):
                return name
        if 0x30 <= int(vk) <= 0x39:
            return str(int(vk) - 0x30)
        if 0x41 <= int(vk) <= 0x5A:
            return chr(int(vk) + 32)
        if 0x70 <= int(vk) <= 0x7B:
            return f"f{int(vk) - 0x6F}"
    return None


def binding_from_mods_and_key(mods: Iterable[str], key: str) -> dict | None:
    return normalize_binding({"mods": list(mods), "key": key})


def match_action(hotkeys: dict, mods: set[str], key: str) -> str | None:
    current = binding_key({"mods": [m for m in MOD_ORDER if m in mods], "key": key})
    for action, binding in hotkeys.items():
        if binding_key(binding) == current:
            return action
    return None


def find_duplicate_actions(hotkeys: dict) -> tuple[str, str] | None:
    seen: dict[frozenset[str], str] = {}
    for action, binding in hotkeys.items():
        key = binding_key(binding)
        if key in seen:
            return seen[key], action
        seen[key] = action
    return None


def is_windows_reserved(binding: dict) -> bool:
    return binding_key(binding) in _WINDOWS_DENY


def binding_vk(binding: dict) -> int | None:
    key = binding["key"]
    return _VK_MAP.get(key)


def binding_win_mods(binding: dict) -> int:
    mods = set(binding.get("mods") or [])
    flags = 0
    if "alt" in mods:
        flags |= 0x0001
    if "ctrl" in mods:
        flags |= 0x0002
    if "shift" in mods:
        flags |= 0x0004
    if "win" in mods:
        flags |= 0x0008
    return flags | 0x4000  # MOD_NOREPEAT


def probe_register_hotkey(binding: dict, hwnd: int = 0) -> bool:
    """Return True if Windows accepts a temporary RegisterHotKey for this combo."""
    vk = binding_vk(binding)
    if vk is None:
        return False
    user32 = ctypes.windll.user32
    hotkey_id = 0x4D52  # 'MR'
    modifiers = binding_win_mods(binding)
    # Plain function keys without mods usually register; combos may fail if taken.
    ok = bool(user32.RegisterHotKey(hwnd, hotkey_id, modifiers, vk))
    if ok:
        user32.UnregisterHotKey(hwnd, hotkey_id)
        return True
    # Single unmodified F-keys and letters: RegisterHotKey often works even when
    # another app uses them via hooks. For unmodified keys, treat as available
    # unless on the deny-list (already checked separately).
    if not binding.get("mods"):
        return True
    return False


def validate_hotkeys(hotkeys: dict, hwnd: int = 0) -> str | None:
    """Return an error message if invalid, else None."""
    dup = find_duplicate_actions(hotkeys)
    if dup:
        a, b = dup
        return (
            f"Cannot use the same combo for {ACTION_LABELS[a]} and "
            f"{ACTION_LABELS[b]}."
        )
    for action, binding in hotkeys.items():
        label = format_binding(binding)
        if is_windows_reserved(binding):
            return (
                f"You can't use {label} because it is already in use "
                f"by Windows ({ACTION_LABELS[action]})."
            )
        if not probe_register_hotkey(binding, hwnd=hwnd):
            return (
                f"You can't use {label} because it is already in use "
                f"({ACTION_LABELS[action]})."
            )
    return None
