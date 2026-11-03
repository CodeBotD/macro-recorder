"""Fetch community macros from the GitHub community/ folder."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from version import APP_VERSION, GITHUB_REPO

USER_AGENT = f"MacroRecorder/{APP_VERSION}"
CONTENTS_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/community"
RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/community"


class CommunityError(Exception):
    """Raised when community macros cannot be listed or fetched."""


@dataclass
class CommunityMacro:
    name: str
    author: str
    description: str
    download_url: str
    raw_text: str | None = None


def _ssl_context():
    try:
        import certifi
        import ssl

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        import ssl

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
            return "GitHub rate-limited the request. Try again in a few minutes."
        if exc.code == 404:
            return "Community macros folder was not found on GitHub."
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
    return "Couldn't load community macros. Check your connection and try again."


def _http_open(url: str, *, timeout: float = 20, headers: dict | None = None):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
    )
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


def _http_json(url: str):
    with _http_open(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_text(url: str) -> str:
    with _http_open(url) as response:
        return response.read().decode("utf-8")


def _decode_base64_content(entry: dict) -> str | None:
    """Decode GitHub Contents API file payload (avoids raw CDN cache)."""
    encoding = entry.get("encoding")
    content = entry.get("content")
    if encoding == "base64" and isinstance(content, str) and content.strip():
        try:
            return base64.b64decode(content).decode("utf-8")
        except Exception:
            return None
    return None


def _file_entry_payload(entry: dict) -> str | None:
    """Load one community JSON file's text from a directory listing entry."""
    text = _decode_base64_content(entry)
    if text is not None:
        return text
    api_url = entry.get("url")
    if isinstance(api_url, str) and api_url:
        try:
            detail = _http_json(api_url)
        except Exception:
            detail = None
        if isinstance(detail, dict):
            text = _decode_base64_content(detail)
            if text is not None:
                return text
    # Last resort only — raw.githubusercontent.com can lag behind pushes.
    download_url = entry.get("download_url")
    if isinstance(download_url, str) and download_url:
        try:
            return _http_text(download_url)
        except Exception:
            pass
    name = entry.get("name")
    if isinstance(name, str) and name:
        try:
            return _http_text(f"{RAW_BASE}/{name}")
        except Exception:
            pass
    return None


def _parse_macro_payload(name: str, text: str, download_url: str) -> CommunityMacro | None:
    try:
        payload = json.loads(text)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    events = payload.get("events")
    if not isinstance(events, list):
        return None
    author = payload.get("author")
    description = payload.get("description")
    return CommunityMacro(
        name=name,
        author=author.strip() if isinstance(author, str) and author.strip() else "Unknown",
        description=(
            description.strip()
            if isinstance(description, str) and description.strip()
            else "No description"
        ),
        download_url=download_url,
        raw_text=text,
    )


def list_community_catalog(
    exclude_names: set[str] | None = None,
) -> tuple[list[CommunityMacro], list[str]]:
    """Fetch the live community catalog from GitHub.

    Does not write into the local library. Returns (macros, skipped_invalid_names).
    """
    exclude = {n.lower() for n in (exclude_names or set())}
    try:
        listing = _http_json(CONTENTS_URL)
    except Exception as exc:
        raise CommunityError(_friendly_network_error(exc)) from exc

    if not isinstance(listing, list):
        raise CommunityError("Unexpected response from GitHub.")

    macros: list[CommunityMacro] = []
    skipped: list[str] = []
    for entry in listing:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "file":
            continue
        name = entry.get("name") or ""
        if not isinstance(name, str) or not name.lower().endswith(".json"):
            continue
        if name.lower() in exclude:
            continue
        download_url = entry.get("download_url") or f"{RAW_BASE}/{name}"
        text = _file_entry_payload(entry)
        if text is None:
            skipped.append(name)
            continue
        parsed = _parse_macro_payload(name, text, download_url)
        if parsed is None:
            skipped.append(name)
            continue
        macros.append(parsed)

    macros.sort(key=lambda item: item.name.lower())
    skipped.sort(key=str.lower)
    return macros, skipped


def list_community_macros(exclude_names: set[str] | None = None) -> list[CommunityMacro]:
    """List community macros from GitHub. Does not write to the local library."""
    macros, _skipped = list_community_catalog(exclude_names=exclude_names)
    return macros


def fetch_macro_text(item: CommunityMacro) -> str:
    """Return JSON text for installing. Uses cached raw_text when available."""
    if item.raw_text:
        return item.raw_text
    api_url = f"{CONTENTS_URL}/{item.name}"
    try:
        detail = _http_json(api_url)
        if isinstance(detail, dict):
            text = _decode_base64_content(detail)
            if text:
                return text
    except Exception:
        pass
    try:
        return _http_text(item.download_url)
    except Exception as exc:
        raise CommunityError(_friendly_network_error(exc)) from exc
