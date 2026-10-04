# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Version comparison for the update check."""
from __future__ import annotations


def _parse(version: str) -> list[int]:
    v = version.strip()
    if v[:1] in ("v", "V"):
        v = v[1:]
    v = v.split("-")[0]
    parts: list[int] = []
    for piece in v.split("."):
        digits = ""
        for ch in piece:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    return parts


def is_newer(remote: str, local: str) -> bool:
    """True when `remote` (e.g. "v1.2.0") is a higher version than `local` (e.g. "1.1.9")."""
    r, l = _parse(remote), _parse(local)
    for i in range(max(len(r), len(l))):
        a = r[i] if i < len(r) else 0
        b = l[i] if i < len(l) else 0
        if a != b:
            return a > b
    return False
