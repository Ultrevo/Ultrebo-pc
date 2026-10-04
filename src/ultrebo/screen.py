# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Screen capture. Coordinates the input backend uses may differ from screenshot pixels (Retina)."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class MonitorInfo:
    index: int  # 1-based, as mss numbers them
    left: int
    top: int
    width: int
    height: int


class ScreenSource(Protocol):
    def grab(self) -> np.ndarray:
        """Current screenshot as a BGR uint8 array."""

    def to_input(self, px: float, py: float) -> tuple[int, int]:
        """Screenshot pixel -> the coordinates mouse input uses."""

    def to_pixels(self, x: float, y: float) -> tuple[int, int]:
        """Mouse input coordinates -> screenshot pixel."""


class MssScreen:
    """Captures one monitor (monitor 1 unless `set_monitor` says otherwise) with mss.

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

    def list_monitors(self) -> list[MonitorInfo]:
        """The real monitors (not the combined "all screens" entry), numbered from 1."""
        return [
            MonitorInfo(i, m["left"], m["top"], m["width"], m["height"])
            for i, m in enumerate(self._sct().monitors)
            if i > 0
        ]

    def set_monitor(self, index: int) -> None:
        """Choose the monitor to watch (1, 2, ...). An unknown number falls back to monitor 1."""
        self.monitor_index = index if 1 <= index < len(self._sct().monitors) else 1

    def grab(self) -> np.ndarray:
        sct = self._sct()
        monitors = sct.monitors
        mon = monitors[self.monitor_index] if 1 <= self.monitor_index < len(monitors) else monitors[min(1, len(monitors) - 1)]
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
