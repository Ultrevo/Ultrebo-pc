# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Moves the mouse on Windows the way a real mouse does.

pynput moves the cursor with `SetCursorPos`, which only puts the pointer somewhere. It sends no mouse-move
event, so some games (Roblox, for one) never learn the cursor is over a button and ignore the click that
follows. `SendInput` produces real mouse input, which every game sees. Nothing here is loaded on other systems.
"""
from __future__ import annotations

import sys

ABSOLUTE_RANGE = 65536  # SendInput's absolute coordinates run from 0 to 65535 across the whole virtual desktop


def to_absolute(value: int, origin: int, size: int) -> int:
    """A pixel position -> SendInput's 0..65535 scale, for a desktop `size` pixels wide starting at `origin`.

    Windows turns the 0..65535 value back into a pixel by multiplying by size / 65536 and rounding down, so
    rounding up here lands on the wanted pixel instead of the one before it.
    """
    size = max(size, 1)
    scaled = -(-(value - origin) * ABSOLUTE_RANGE // size)  # ceiling division
    return min(max(scaled, 0), ABSOLUTE_RANGE - 1)


def available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _INPUT_MOUSE = 0
    _MOVE, _VIRTUALDESK, _ABSOLUTE = 0x0001, 0x4000, 0x8000
    _SM_XVIRTUALSCREEN, _SM_YVIRTUALSCREEN, _SM_CXVIRTUALSCREEN, _SM_CYVIRTUALSCREEN = 76, 77, 78, 79

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def _send(dx: int, dy: int, flags: int) -> None:
        item = _INPUT(type=_INPUT_MOUSE, mi=_MOUSEINPUT(dx, dy, 0, flags, 0, None))
        _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))

    def move_to(x: int, y: int) -> None:
        """Move the pointer to screen position (x, y) with real mouse input, then make sure it is exactly there."""
        vx, vy = _user32.GetSystemMetrics(_SM_XVIRTUALSCREEN), _user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)
        vw, vh = _user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN), _user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)
        _send(to_absolute(x, vx, vw), to_absolute(y, vy, vh), _MOVE | _ABSOLUTE | _VIRTUALDESK)
        point = wintypes.POINT()
        if _user32.GetCursorPos(ctypes.byref(point)) and (abs(point.x - x) > 1 or abs(point.y - y) > 1):
            _user32.SetCursorPos(int(x), int(y))  # a scaled or unusual display: place it exactly

    def move_by(dx: int, dy: int) -> None:
        """A small move relative to where the pointer is, as a physical mouse sends."""
        _send(int(dx), int(dy), _MOVE)

    def probe() -> str:
        """For the build's self-test: does Windows accept our mouse input? Sends a move of zero, which changes nothing."""
        item = _INPUT(type=_INPUT_MOUSE, mi=_MOUSEINPUT(0, 0, 0, _MOVE, 0, None))
        sent = _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT))
        return f"ok size={ctypes.sizeof(_INPUT)}" if sent == 1 else f"refused (error {ctypes.get_last_error() or ctypes.GetLastError()}) size={ctypes.sizeof(_INPUT)}"

else:  # pragma: no cover - only Windows uses these
    def move_to(x: int, y: int) -> None:
        raise OSError("real mouse input is only used on Windows")

    def move_by(dx: int, dy: int) -> None:
        raise OSError("real mouse input is only used on Windows")

    def probe() -> str:
        return "not used on this system"
