"""App data paths and persisted settings."""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR_NAME = "MacroRecorder"
SETTINGS_FILE = "settings.json"
MACROS_DIR_NAME = "macros"

DEFAULT_SETTINGS = {
    "dark_mode": False,
    "check_for_updates": True,
    "last_macro": None,
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


def load_settings() -> dict:
    path = settings_path()
    data = dict(DEFAULT_SETTINGS)
    if not path.is_file():
        return data
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            if "dark_mode" in loaded:
                data["dark_mode"] = bool(loaded["dark_mode"])
            if "check_for_updates" in loaded:
                data["check_for_updates"] = bool(loaded["check_for_updates"])
            last = loaded.get("last_macro")
            data["last_macro"] = last if isinstance(last, str) and last else None
    except Exception:
        pass
    return data


def save_settings(settings: dict) -> None:
    path = settings_path()
    payload = {
        "dark_mode": bool(settings.get("dark_mode", DEFAULT_SETTINGS["dark_mode"])),
        "check_for_updates": bool(
            settings.get("check_for_updates", DEFAULT_SETTINGS["check_for_updates"])
        ),
        "last_macro": settings.get("last_macro") or None,
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
