# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import threading
import time

import cv2
import numpy as np
import pytest

from ultrebo.textmatch import OcrWord


class FakeInput:
    """Records every action with a timestamp."""

    def __init__(self):
        self.calls = []
        self._lock = threading.Lock()

    def _log(self, *call):
        with self._lock:
            self.calls.append((time.monotonic(), *call))

    def click(self, x, y, button="left", hold_ms=60, clicks=1):
        self._log("click", x, y, button, clicks)
        time.sleep(0.005)

    def drag(self, x1, y1, x2, y2, button="left", duration_ms=300):
        self._log("drag", x1, y1, x2, y2)

    def scroll(self, dx, dy, x=None, y=None):
        self._log("scroll", dx, dy)

    def press_keys(self, spec, hold_ms=60):
        self._log("keys", spec)

    def clicks(self):
        return [(c[0], c[2], c[3]) for c in self.calls if c[1] == "click"]

    def names(self):
        return [c[1:] for c in self.calls]


class FakeScreen:
    """Screenshots come from a function so a test can change what is 'on screen'."""

    def __init__(self, frame_fn, scale=1.0):
        self.frame_fn = frame_fn
        self.scale = scale

    def grab(self):
        return self.frame_fn()

    def to_input(self, px, py):
        return int(px / self.scale), int(py / self.scale)

    def to_pixels(self, x, y):
        return int(x * self.scale), int(y * self.scale)


class FakeOcr:
    def __init__(self, lines):
        self.lines = lines  # list[list[OcrWord]] or callable returning it
        self.calls = 0

    def read(self, image):
        self.calls += 1
        return self.lines() if callable(self.lines) else self.lines


@pytest.fixture
def pattern():
    """A distinctive 60x40 patch (random noise) used as the 'button' to find."""
    rng = np.random.default_rng(7)
    return rng.integers(0, 255, size=(40, 60, 3), dtype=np.uint8)


@pytest.fixture
def blank():
    rng = np.random.default_rng(1)
    base = np.full((300, 400, 3), 40, dtype=np.uint8)
    noise = rng.integers(0, 12, size=base.shape, dtype=np.uint8)
    return base + noise


def with_pattern(blank, pattern, x=200, y=120):
    frame = blank.copy()
    h, w = pattern.shape[:2]
    frame[y:y + h, x:x + w] = pattern
    return frame


@pytest.fixture
def templates_dir(tmp_path, pattern):
    d = tmp_path / "templates"
    d.mkdir()
    cv2.imwrite(str(d / "button.png"), pattern)
    return d


def wait_until(predicate, timeout=5.0, interval=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
