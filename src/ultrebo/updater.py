# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Asks GitHub whether a newer release exists. Only the request itself is sent; nothing about you."""
from __future__ import annotations

import json
import platform
import re
import ssl
import sys
import urllib.request
from dataclasses import dataclass

from . import REPO
from .versions import is_newer

API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
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
    size: int


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


def check_detailed(current_version: str, timeout: float = 8.0) -> CheckResult:
    """Asks GitHub for the latest release and says what it found, or why it couldn't."""
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


def check(current_version: str, timeout: float = 8.0) -> Update | None:
    """The newer release, or None when up to date or anything goes wrong."""
    return check_detailed(current_version, timeout).update
