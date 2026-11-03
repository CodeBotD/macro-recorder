"""Check GitHub Releases and install MSI updates."""

from __future__ import annotations

import json
import os
import ssl
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from version import APP_VERSION, GITHUB_REPO, MSI_ASSET_NAME

USER_AGENT = f"MacroRecorder/{APP_VERSION}"
API_LATEST = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_LATEST = f"https://github.com/{GITHUB_REPO}/releases/latest"


class UpdateCheckError(Exception):
    """Raised when an update check fails for a user-visible reason."""


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


def _ssl_context() -> ssl.SSLContext:
    """Prefer certifi CAs (reliable in frozen builds), else the OS store."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
        try:
            context.load_default_certs()
        except Exception:
            pass
        return context


def _friendly_network_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError) or isinstance(exc, urllib.error.URLError) and isinstance(
        getattr(exc, "reason", None), TimeoutError
    ):
        return "Timed out reaching GitHub. Try again later."
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403:
            return "GitHub rate-limited the update check. Try again in a few minutes."
        if exc.code == 404:
            return "Update info was not found on GitHub."
        return f"GitHub returned HTTP {exc.code}."
    text = str(exc).lower()
    if "certificate" in text or "ssl" in text or "tls" in text:
        return (
            "Secure connection to GitHub failed. "
            "A firewall, proxy, or antivirus may be blocking Macro Recorder."
        )
    if isinstance(exc, urllib.error.URLError):
        return (
            "Could not reach GitHub. "
            "Check Wi‑Fi, or allow Macro Recorder through Windows Firewall."
        )
    return "Couldn't check for updates. Check your connection and try again."


def _http_open(url: str, *, timeout: float, headers: dict | None = None):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
    )
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


def _http_json(url: str) -> dict:
    with _http_open(
        url,
        timeout=20,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _tag_from_latest_url(url: str) -> str | None:
    marker = "/releases/tag/"
    if marker not in url:
        return None
    tag = url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")
    return tag or None


def _msi_download_url(tag: str) -> str:
    return f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/{MSI_ASSET_NAME}"


def _check_via_api() -> PendingUpdate | None:
    data = _http_json(API_LATEST)
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
        download_url = _msi_download_url(tag if tag.lower().startswith("v") else f"v{version}")
    notes = (data.get("body") or "").strip()
    return PendingUpdate(version=version, download_url=download_url, notes=notes)


def _check_via_github_redirect() -> PendingUpdate | None:
    """Fallback when api.github.com is blocked but github.com works."""
    with _http_open(GITHUB_LATEST, timeout=20) as response:
        tag = _tag_from_latest_url(response.geturl())
    if not tag:
        raise UpdateCheckError("Could not read the latest release from GitHub.")
    if not is_newer(tag):
        return None
    version = tag[1:] if tag.lower().startswith("v") else tag
    return PendingUpdate(
        version=version,
        download_url=_msi_download_url(tag),
        notes="",
    )


def check_latest() -> PendingUpdate | None:
    """Return a pending update if a newer release exists.

    Raises UpdateCheckError on network/API failures so callers can distinguish
    errors from 'already up to date'.
    """
    api_error: BaseException | None = None
    try:
        return _check_via_api()
    except Exception as exc:
        api_error = exc
    try:
        return _check_via_github_redirect()
    except Exception as exc:
        raise UpdateCheckError(_friendly_network_error(api_error or exc)) from exc


def download_msi(url: str, progress: Callable[[int, int | None], None] | None = None) -> str:
    with _http_open(url, timeout=120) as response:
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
