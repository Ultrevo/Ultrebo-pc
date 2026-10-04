# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Asks GitHub whether a newer release exists. Only the request itself is sent; nothing about you."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from . import REPO
from .versions import is_newer

API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE_PREFIX = "https://github.com/"


@dataclass(frozen=True)
class Update:
    version: str
    url: str


def parse_release(body: str, current_version: str) -> Update | None:
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
    return Update(tag.lstrip("vV"), page)


def check(current_version: str, timeout: float = 8.0) -> Update | None:
    """The newer release, or None when up to date or anything goes wrong."""
    try:
        request = urllib.request.Request(
            API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Ultrebo"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            return parse_release(response.read().decode("utf-8"), current_version)
    except Exception:  # noqa: BLE001 - an update check must never get in the way
        return None
