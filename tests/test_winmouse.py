# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import threading
import pytest

from ultrebo import inputs, winmouse


@pytest.mark.parametrize("size, origin", [(1920, 0), (2560, 0), (3840, 0), (1366, 0), (3840, -1920), (4480, -2560)])
def test_every_pixel_converts_to_the_scale_windows_uses_and_back_to_the_same_pixel(size, origin):
    for pixel in list(range(origin, origin + size, 37)) + [origin, origin + size - 1]:
        value = winmouse.to_absolute(pixel, origin, size)
        assert 0 <= value <= 65535
        assert origin + (value * size) // 65536 == pixel  # Windows turns the value back into a pixel this way


def test_positions_outside_the_desktop_are_held_inside_it():
    assert winmouse.to_absolute(-500, 0, 1920) == 0
    assert winmouse.to_absolute(99999, 0, 1920) == 65535


def test_only_windows_uses_real_mouse_input():
    import sys

    assert winmouse.available() == (sys.platform == "win32")


class FakeController:
    def __init__(self):
        self.position = (0, 0)
        self.events = []

    def press(self, b):
        self.events.append(("press", self.position))

    def release(self, b):
        self.events.append(("release", self.position))

    def scroll(self, dx, dy):
        self.events.append(("scroll", dx, dy))


class _Mouse:
    class Button:
        left = "left"
        right = "right"
        middle = "middle"


def make_backend(real, monkeypatch, log, fail=False):
    backend = object.__new__(inputs.PynputInput)  # skip pynput, which needs a real display
    backend._abort = threading.Event()
    backend._mouse = _Mouse
    backend._mouse_ctl = FakeController()
    backend._real_mouse = real

    def move_to(x, y):
        if fail:
            raise OSError("no")
        log.append(("to", x, y))
        backend._mouse_ctl.position = (x, y)

    monkeypatch.setattr(inputs.winmouse, "move_to", move_to)
    monkeypatch.setattr(inputs.winmouse, "move_by", lambda dx, dy: log.append(("by", dx, dy)))
    monkeypatch.setattr(inputs.time, "sleep", lambda s: None)
    return backend


def test_a_nudged_click_moves_with_real_input_and_ends_exactly_on_the_target(monkeypatch):
    log = []
    backend = make_backend(True, monkeypatch, log)
    backend.click(300, 200, nudge=True)
    assert ("by", 2, 1) in log and ("by", -2, -1) in log  # a push of the mouse, then back
    last_move = [e for e in log if e[0] == "to"][-1]
    assert last_move == ("to", 300, 200)
    assert backend._mouse_ctl.events == [("press", (300, 200)), ("release", (300, 200))]


def test_a_plain_click_on_windows_is_also_placed_with_real_input(monkeypatch):
    log = []
    backend = make_backend(True, monkeypatch, log)
    backend.click(10, 20)
    assert log == [("to", 10, 20)] and backend._mouse_ctl.events[0] == ("press", (10, 20))


def test_other_systems_keep_the_plain_way(monkeypatch):
    log = []
    backend = make_backend(False, monkeypatch, log)
    backend.click(300, 200, nudge=True)
    assert log == [] and backend._mouse_ctl.position == (300, 200)


def test_if_real_input_fails_the_macro_carries_on_the_plain_way(monkeypatch):
    log = []
    backend = make_backend(True, monkeypatch, log, fail=True)
    backend.click(50, 60)
    assert backend._real_mouse is False and backend._mouse_ctl.events[0] == ("press", (50, 60))
