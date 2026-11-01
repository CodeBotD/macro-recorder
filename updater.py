"""Check GitHub Releases and install MSI updates."""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from version import APP_VERSION, GITHUB_REPO, MSI_ASSET_NAME

USER_AGENT = f"MacroRecorder/{APP_VERSION}"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass
class PendingUpdate:
    version: str
    download_url: str
    notes: str


def _parse_version(text: str) -> tuple[int, ...]:
    text = (text or "").strip()
    if text.lower().startswith("v"):
        text = text[1:]
    parts = []
    for chunk in text.split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while parts and parts[-1] == 0 and len(parts) > 1:
        parts.pop()
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _http_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def check_latest() -> PendingUpdate | None:
    try:
        data = _http_json(API_LATEST)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, ValueError):
        return None
    tag = data.get("tag_name") or ""
    if not is_newer(tag):
        return None
    version = tag[1:] if tag.lower().startswith("v") else tag
    download_url = None
    for asset in data.get("assets") or []:
        if asset.get("name") == MSI_ASSET_NAME and asset.get("browser_download_url"):
            download_url = asset["browser_download_url"]
            break
    if not download_url:
        return None
    notes = (data.get("body") or "").strip()
    return PendingUpdate(version=version, download_url=download_url, notes=notes)


def download_msi(url: str, progress: Callable[[int, int | None], None] | None = None) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        total = response.headers.get("Content-Length")
        total_size = int(total) if total and total.isdigit() else None
        fd, path = tempfile.mkstemp(prefix="MacroRecorder-", suffix=".msi")
        os.close(fd)
        written = 0
        try:
            with open(path, "wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    written += len(chunk)
                    if progress:
                        progress(written, total_size)
        except Exception:
            try:
                os.remove(path)
            except OSError:
                pass
            raise
    return path


def launch_msi_installer(msi_path: str) -> None:
    import ctypes

    # Elevate via ShellExecute so per-machine MSI can install.
    result = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        "msiexec",
        f'/i "{msi_path}"',
        None,
        1,
    )
    if result <= 32:
        raise OSError(f"ShellExecute failed with code {result}")
