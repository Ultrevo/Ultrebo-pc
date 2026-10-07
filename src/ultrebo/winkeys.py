# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Presses keys on Windows the way a real keyboard reports them: by scan code.

pynput presses keys by virtual-key code. Many games (Roblox among them) read the physical key's scan code instead,
so a key such as Enter can do nothing even though a text box accepts it. `SendInput` with the scan-code flag
is what a real keyboard produces, and works for both kinds of program. Nothing here is used on other systems.
"""
from __future__ import annotations

import sys

#: Windows reports "extended" keys (arrows, Insert/Delete, Home/End, right Ctrl/Alt, ...) with 0xE0 in front of the scan code.
EXTENDED_PREFIXES = (0xE0, 0xE1)


#: Keys that must be sent as "extended" even though Windows' scan-code lookup doesn't say so for them (the arrow keys share
#: scan codes with the number pad, and without the flag they would be read as number pad keys).
EXTENDED_VKS = frozenset({
    0x21, 0x22, 0x23, 0x24,  # page up, page down, end, home
    0x25, 0x26, 0x27, 0x28,  # left, up, right, down
    0x2C, 0x2D, 0x2E,  # print screen, insert, delete
    0x5B, 0x5C, 0x5D,  # left and right Windows keys, menu
    0x6F, 0x90,  # number pad divide, num lock
    0xA3, 0xA5,  # right ctrl, right alt
    0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3,  # volume and media keys
})


def split_scan(mapped: int) -> tuple[int, bool]:
    """Windows' answer for a key -> (scan code, is it an extended key). 0 means the key has no scan code."""
    return mapped & 0xFF, (mapped >> 8) in EXTENDED_PREFIXES


def available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _INPUT_KEYBOARD = 1
    _EXTENDEDKEY, _KEYUP, _SCANCODE = 0x0001, 0x0002, 0x0008
    _MAPVK_VK_TO_VSC_EX = 4

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _MOUSEINPUT(ctypes.Structure):  # only here so the union is as big as Windows expects (40 bytes in all)
        _fields_ = [
            ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    def scan_for_vk(vk: int) -> tuple[int, bool] | None:
        """(scan code, extended) for a virtual-key code, or None when Windows has none."""
        scan, extended = split_scan(_user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC_EX))
        return (scan, extended or vk in EXTENDED_VKS) if scan else None

    def vk_for_char(char: str) -> int | None:
        """The virtual-key code that types `char` with no modifier keys, or None if it needs shift/ctrl/alt (or doesn't exist)."""
        result = _user32.VkKeyScanW(ord(char))
        if result == -1 or (result >> 8) & 0xFF:
            return None
        return result & 0xFF

    def send_scan(scan: int, extended: bool, down: bool) -> None:
        flags = _SCANCODE | (_EXTENDEDKEY if extended else 0) | (0 if down else _KEYUP)
        item = _INPUT(type=_INPUT_KEYBOARD, ki=_KEYBDINPUT(0, scan, flags, 0, None))
        if _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(_INPUT)) != 1:
            raise OSError("Windows did not accept the key press")

    def probe() -> str:
        """For the build's self-test: do the scan codes come out right? (Enter is 0x1c, A is 0x1e, Right arrow is extended 0x4d.)"""
        enter, a, right = scan_for_vk(0x0D), scan_for_vk(0x41), scan_for_vk(0x27)
        return f"enter={enter} a={a} right={right}"

else:  # pragma: no cover - only Windows uses these
    def scan_for_vk(vk: int):
        return None

    def vk_for_char(char: str):
        return None

    def send_scan(scan: int, extended: bool, down: bool) -> None:
        raise OSError("scan-code keys are only used on Windows")

    def probe() -> str:
        return "not used on this system"
