# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Asks GitHub whether a newer release exists. Only the request itself is sent; nothing about you."""
from __future__ import annotations

import json
import platform
import re
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import REPO
from .versions import is_newer

API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
LATEST_URL = f"https://github.com/{REPO}/releases/latest"  # an ordinary web address that forwards to the newest release
TAG_PATTERN = re.compile(r"^v?\d+(\.\d+){1,3}$")
PAGE_PREFIX = "https://github.com/"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
MAX_DOWNLOAD_BYTES = 600 * 1024 * 1024


def ssl_context() -> ssl.SSLContext:
    """TLS settings that also work in the packaged app (a Mac build has no system certificates of its own)."""
    context = ssl.create_default_context()  # the computer's own certificates (also covers antivirus and proxies)
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())  # plus a standard set, for builds that have none
    except Exception:  # noqa: BLE001
        pass
    return context


@dataclass(frozen=True)
class CheckResult:
    update: "Update | None"
    latest: str | None = None  # the newest release found, e.g. "0.1.2"
    error: str | None = None  # why the check failed, when it did


@dataclass(frozen=True)
class Asset:
    """The release file for this computer, with the checksum GitHub publishes for it."""

    name: str
    url: str
    sha256: str
    size: int = 0  # 0 = not known; the download is then limited by MAX_DOWNLOAD_BYTES instead


@dataclass(frozen=True)
class Update:
    version: str
    url: str
    #: None when this computer can't update itself (the user downloads from the release page instead).
    asset: Asset | None = None


def platform_key() -> str | None:
    """Which release file fits this computer: windows-x64, macos-apple-silicon or macos-intel."""
    machine = platform.machine().lower()
    if sys.platform == "win32":
        return "windows-x64" if machine in ("amd64", "x86_64") else None
    if sys.platform == "darwin":
        return "macos-apple-silicon" if machine in ("arm64", "aarch64") else "macos-intel"
    return None


def pick_asset(assets: object, target: str | None) -> Asset | None:
    """The trusted release file for `target`, or None. Anything unexpected means "no self-update"."""
    if not target or not isinstance(assets, list):
        return None
    for item in assets:
        if not isinstance(item, dict):
            continue
        name, url, digest, size = item.get("name"), item.get("browser_download_url"), item.get("digest"), item.get("size")
        if not (isinstance(name, str) and isinstance(url, str) and isinstance(digest, str) and isinstance(size, int)):
            continue
        if target not in name or not name.endswith(".zip") or not url.startswith(DOWNLOAD_PREFIX):
            continue
        match = re.fullmatch(r"sha256:([0-9a-fA-F]{64})", digest)
        if match and 0 < size <= MAX_DOWNLOAD_BYTES:
            return Asset(name, url, match.group(1).lower(), size)
    return None


def parse_release(body: str, current_version: str, target: str | None = None) -> Update | None:
    """Pure parsing of GitHub's "latest release" JSON (split out so it can be tested)."""
    try:
        data = json.loads(body)
        tag = data["tag_name"]
        page = data["html_url"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(tag, str) or not isinstance(page, str) or not page.startswith(PAGE_PREFIX):
        return None
    if not is_newer(tag, current_version):
        return None
    return Update(tag.lstrip("vV"), page, pick_asset(data.get("assets"), target))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # hand the redirect back to us instead of following it


def latest_tag_from_web(timeout: float = 8.0) -> str:
    """The newest release's tag, read from where github.com/<repo>/releases/latest forwards to.

    This is a normal web page, not the API, so it isn't held to the API's small per-address limit (60 an hour,
    shared by everyone behind the same internet connection), which made the old check fail without a word.
    """
    opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=ssl_context()))
    request = urllib.request.Request(LATEST_URL, method="HEAD", headers={"User-Agent": "Ultrebo"})
    try:
        opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        location = e.headers.get("Location") if e.code in (301, 302, 303, 307, 308) else None
        match = re.fullmatch(re.escape(f"https://github.com/{REPO}/releases/tag/") + r"([^/?#]+)", (location or "").split("?")[0])
        if match and TAG_PATTERN.match(match.group(1)):
            return match.group(1)
        raise RuntimeError(f"GitHub answered with status {e.code} and no release to follow") from e
    raise RuntimeError("GitHub did not point to a latest release")


def _get_text(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Ultrebo"})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return response.read(4096).decode("utf-8", "replace")


def asset_from_checksum_file(tag: str, target: str, timeout: float = 8.0) -> Asset | None:
    """This computer's download for release `tag`, with the checksum the release build publishes next to it.

    Builds from v0.1.3 on attach `<file>.zip.sha256`. Returns None when it isn't there (older releases)."""
    name = f"Ultrebo-{tag}-{target}.zip"
    url = f"{DOWNLOAD_PREFIX}{tag}/{name}"
    try:
        match = re.match(r"\s*([0-9a-fA-F]{64})\b", _get_text(url + ".sha256", timeout))
    except Exception:  # noqa: BLE001
        return None
    return Asset(name, url, match.group(1).lower()) if match else None


def _check_with_api(current_version: str, timeout: float) -> CheckResult:
    try:
        request = urllib.request.Request(
            API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Ultrebo"}
        )
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            if response.status != 200:
                return CheckResult(None, error=f"GitHub answered with status {response.status}")
            body = response.read().decode("utf-8")
    except Exception as e:  # noqa: BLE001 - an update check must never get in the way
        return CheckResult(None, error=f"{type(e).__name__}: {e}")
    try:
        latest = str(json.loads(body)["tag_name"]).lstrip("vV")
    except (ValueError, KeyError, TypeError):
        return CheckResult(None, error="GitHub's reply was not what Ultrebo expected")
    return CheckResult(parse_release(body, current_version, platform_key()), latest=latest)


def check_detailed(current_version: str, timeout: float = 8.0) -> CheckResult:
    """Asks GitHub for the latest release and says what it found, or why it couldn't."""
    try:
        tag = latest_tag_from_web(timeout)
    except Exception as web_error:  # noqa: BLE001
        result = _check_with_api(current_version, timeout)  # the web address failed: try the API as a second way
        if result.error:
            return CheckResult(None, error=f"{result.error} (and {type(web_error).__name__}: {web_error})")
        return result
    if not is_newer(tag, current_version):
        return CheckResult(None, latest=tag.lstrip("vV"))
    target = platform_key()
    asset = asset_from_checksum_file(tag, target, timeout) if target else None
    if asset is None and target:
        asset = _check_with_api(current_version, timeout).update  # older releases: the checksum comes from the API
        asset = asset.asset if asset else None
    return CheckResult(Update(tag.lstrip("vV"), f"https://github.com/{REPO}/releases/tag/{tag}", asset), latest=tag.lstrip("vV"))


def check(current_version: str, timeout: float = 8.0) -> Update | None:
    """The newer release, or None when up to date or anything goes wrong."""
    return check_detailed(current_version, timeout).update
