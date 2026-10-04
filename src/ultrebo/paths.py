# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Where Ultrebo keeps its files on each operating system."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """Per-user folder for macros, cropped images and settings (created if missing)."""
    override = os.environ.get("ULTREBO_DATA_DIR")
    if override:
        path = Path(override)
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / "Ultrebo"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "Ultrebo"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "ultrebo"
    path.mkdir(parents=True, exist_ok=True)
    return path
