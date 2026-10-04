# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Screen capture. Coordinates the input backend uses may differ from screenshot pixels (Retina)."""
from __future__ import annotations

import threading
from typing import Protocol

import numpy as np


class ScreenSource(Protocol):
    def grab(self) -> np.ndarray:
        """Current screenshot as a BGR uint8 array."""

    def to_input(self, px: float, py: float) -> tuple[int, int]:
        """Screenshot pixel -> the coordinates mouse input uses."""

    def to_pixels(self, x: float, y: float) -> tuple[int, int]:
        """Mouse input coordinates -> screenshot pixel."""


class MssScreen:
    """Captures the primary monitor with mss.

    On Windows (the app is DPI-aware) and Linux, screenshot pixels and mouse coordinates are the
    same. On a Retina Mac the screenshot has twice as many pixels as the mouse has points, so
    `scale` converts between them.
    """

    def __init__(self, monitor_index: int = 1):
        self.monitor_index = monitor_index
        self.scale = 1.0
        self.left = 0
        self.top = 0
        self._local = threading.local()

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss

            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab(self) -> np.ndarray:
        sct = self._sct()
        monitors = sct.monitors
        mon = monitors[self.monitor_index] if self.monitor_index < len(monitors) else monitors[0]
        shot = sct.grab(mon)
        self.left, self.top = mon["left"], mon["top"]
        if mon["width"]:
            self.scale = shot.width / mon["width"]
        frame = np.asarray(shot)  # BGRA
        return np.ascontiguousarray(frame[:, :, :3])

    def to_input(self, px: float, py: float) -> tuple[int, int]:
        return int(self.left + px / self.scale), int(self.top + py / self.scale)

    def to_pixels(self, x: float, y: float) -> tuple[int, int]:
        return int((x - self.left) * self.scale), int((y - self.top) * self.scale)
