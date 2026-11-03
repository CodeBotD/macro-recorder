"""App data paths and persisted settings."""

from __future__ import annotations

import json
import os
from pathlib import Path

import hotkeys as hotkey_defs
import theme

APP_DIR_NAME = "MacroRecorder"
SETTINGS_FILE = "settings.json"
MACROS_DIR_NAME = "macros"

DEFAULT_SETTINGS = {
    "theme_mode": "light",
    "custom_colors": dict(theme.CUSTOM),
    "check_for_updates": True,
    "last_macro": None,
    "hotkeys": hotkey_defs.normalize_hotkeys(None),
    "repeat": 1,
    "loop_until_stopped": False,
    "always_on_top": False,
}


def app_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def macros_dir() -> Path:
    path = app_root() / MACROS_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return app_root() / SETTINGS_FILE


def clamp_repeat(value) -> int:
    try:
        repeat = int(value)
    except (TypeError, ValueError):
        repeat = DEFAULT_SETTINGS["repeat"]
    if repeat < 1:
        return 1
    if repeat > 9999:
        return 9999
    return repeat


def _theme_mode_from_loaded(loaded: dict) -> str:
    if "theme_mode" in loaded:
        return theme.normalize_theme_mode(loaded.get("theme_mode"))
    if "dark_mode" in loaded:
        return "dark" if bool(loaded.get("dark_mode")) else "light"
    return DEFAULT_SETTINGS["theme_mode"]


def load_settings() -> dict:
    path = settings_path()
    data = {
        "theme_mode": DEFAULT_SETTINGS["theme_mode"],
        "custom_colors": dict(DEFAULT_SETTINGS["custom_colors"]),
        "check_for_updates": DEFAULT_SETTINGS["check_for_updates"],
        "last_macro": DEFAULT_SETTINGS["last_macro"],
        "hotkeys": hotkey_defs.normalize_hotkeys(None),
        "repeat": DEFAULT_SETTINGS["repeat"],
        "loop_until_stopped": DEFAULT_SETTINGS["loop_until_stopped"],
        "always_on_top": DEFAULT_SETTINGS["always_on_top"],
    }
    if not path.is_file():
        return data
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            data["theme_mode"] = _theme_mode_from_loaded(loaded)
            data["custom_colors"] = theme.normalize_custom_colors(loaded.get("custom_colors"))
            if "check_for_updates" in loaded:
                data["check_for_updates"] = bool(loaded["check_for_updates"])
            last = loaded.get("last_macro")
            data["last_macro"] = last if isinstance(last, str) and last else None
            data["hotkeys"] = hotkey_defs.normalize_hotkeys(loaded.get("hotkeys"))
            if "repeat" in loaded:
                data["repeat"] = clamp_repeat(loaded.get("repeat"))
            if "loop_until_stopped" in loaded:
                data["loop_until_stopped"] = bool(loaded["loop_until_stopped"])
            if "always_on_top" in loaded:
                data["always_on_top"] = bool(loaded["always_on_top"])
    except Exception:
        pass
    return data


def save_settings(settings: dict) -> None:
    path = settings_path()
    theme_mode = theme.normalize_theme_mode(
        settings.get("theme_mode", DEFAULT_SETTINGS["theme_mode"])
    )
    payload = {
        "theme_mode": theme_mode,
        "custom_colors": theme.normalize_custom_colors(settings.get("custom_colors")),
        "check_for_updates": bool(
            settings.get("check_for_updates", DEFAULT_SETTINGS["check_for_updates"])
        ),
        "last_macro": settings.get("last_macro") or None,
        "hotkeys": hotkey_defs.normalize_hotkeys(settings.get("hotkeys")),
        "repeat": clamp_repeat(settings.get("repeat", DEFAULT_SETTINGS["repeat"])),
        "loop_until_stopped": bool(
            settings.get("loop_until_stopped", DEFAULT_SETTINGS["loop_until_stopped"])
        ),
        "always_on_top": bool(
            settings.get("always_on_top", DEFAULT_SETTINGS["always_on_top"])
        ),
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def list_macros() -> list[str]:
    names = []
    for path in sorted(macros_dir().glob("*.json")):
        names.append(path.name)
    return names


def macro_path(name: str) -> Path:
    name = Path(name).name
    if not name.lower().endswith(".json"):
        name += ".json"
    return macros_dir() / name


def delete_macro(name: str) -> bool:
    path = macro_path(name)
    if not path.is_file():
        return False
    path.unlink()
    return True


def sanitize_macro_name(name: str) -> str | None:
    name = (name or "").strip()
    if not name:
        return None
    name = Path(name).name
    if not name.lower().endswith(".json"):
        name += ".json"
    # Reject empty / path tricks after basename
    stem = Path(name).stem.strip()
    if not stem or stem in {".", ".."}:
        return None
    return name
