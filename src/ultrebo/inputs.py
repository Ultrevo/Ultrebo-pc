# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Sends mouse and keyboard input. The runner only talks to the InputBackend interface."""
from __future__ import annotations

import time
from typing import Protocol

MODIFIERS = ("ctrl", "shift", "alt", "cmd")

# Names accepted in key specs, mapped to pynput's Key attribute names.
_KEY_ALIASES = {
    "enter": "enter", "return": "enter",
    "esc": "esc", "escape": "esc",
    "tab": "tab", "space": "space", "backspace": "backspace",
    "delete": "delete", "del": "delete", "insert": "insert",
    "home": "home", "end": "end",
    "pageup": "page_up", "page_up": "page_up",
    "pagedown": "page_down", "page_down": "page_down",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "capslock": "caps_lock", "caps_lock": "caps_lock",
    "ctrl": "ctrl", "control": "ctrl",
    "shift": "shift",
    "alt": "alt", "option": "alt",
    "cmd": "cmd", "win": "cmd", "windows": "cmd", "super": "cmd", "command": "cmd",
}
_FUNCTION_KEYS = {f"f{i}" for i in range(1, 21)}


def parse_key_spec(spec: str) -> tuple[list[str], str]:
    """Split "ctrl+shift+s" into (["ctrl", "shift"], "s"). Raises ValueError when it makes no sense."""
    text = spec.strip().lower()
    if text == "+":
        parts = ["+"]
    elif text.endswith("++"):  # "ctrl++" means ctrl and the plus key
        head = text[:-2]
        parts = ([p.strip() for p in head.split("+")] if head else []) + ["+"]
    else:
        parts = [p.strip() for p in text.split("+")]
    if not text or any(p == "" for p in parts):
        raise ValueError("Incomplete key")
    names = [normalize_key_name(p) for p in parts]
    *mods, key = names
    for m in mods:
        if m not in MODIFIERS:
            raise ValueError(f'"{m}" can only be the last key; use ctrl, shift, alt or cmd before the "+"')
    return mods, key


def normalize_key_name(name: str) -> str:
    n = name.strip().lower()
    if n in _KEY_ALIASES:
        return _KEY_ALIASES[n]
    if n in _FUNCTION_KEYS:
        return n
    if len(n) == 1:
        return n
    raise ValueError(f'Unknown key "{name}"')


def validate_key_spec(spec: str) -> str | None:
    """Error message for the interface, or None when the spec is usable."""
    try:
        parse_key_spec(spec)
    except ValueError as e:
        return str(e)
    return None


GLIDE_STEPS = 8
#: Offsets (pixels) of the little wiggle before a nudged click; it always ends exactly on the target.
WIGGLE = ((3, 2), (-3, -2), (2, -1), (0, 0))


class InputBackend(Protocol):
    def click(
        self, x: int, y: int, button: str = "left", hold_ms: int = 60, clicks: int = 1, nudge: bool = False
    ) -> None: ...

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: str = "left", duration_ms: int = 300) -> None: ...

    def scroll(self, dx: int, dy: int, x: int | None = None, y: int | None = None) -> None: ...

    def press_keys(self, spec: str, hold_ms: int = 60) -> None: ...


class PynputInput:
    """Real input via pynput (Windows, macOS and Linux/X11)."""

    def __init__(self) -> None:
        from pynput import keyboard, mouse

        self._keyboard = keyboard
        self._mouse = mouse
        self._mouse_ctl = mouse.Controller()
        self._key_ctl = keyboard.Controller()

    def _button(self, name: str):
        return {
            "left": self._mouse.Button.left,
            "right": self._mouse.Button.right,
            "middle": self._mouse.Button.middle,
        }.get(name, self._mouse.Button.left)

    def _approach(self, x: int, y: int) -> None:
        """Glide to (x, y) and give the mouse a tiny wiggle on arrival.

        Some games (Roblox, for one) only notice the mouse when they see it move, not when the cursor is
        placed straight on a spot, so a click right after a teleport can land on nothing.
        """
        ctl = self._mouse_ctl
        try:
            sx, sy = ctl.position
        except Exception:  # noqa: BLE001
            sx, sy = x, y
        for i in range(1, GLIDE_STEPS + 1):
            t = i / GLIDE_STEPS
            ctl.position = (round(sx + (x - sx) * t), round(sy + (y - sy) * t))
            time.sleep(0.008)
        for dx, dy in WIGGLE:
            ctl.position = (x + dx, y + dy)
            time.sleep(0.012)
        time.sleep(0.02)

    def click(
        self, x: int, y: int, button: str = "left", hold_ms: int = 60, clicks: int = 1, nudge: bool = False
    ) -> None:
        if nudge:
            self._approach(x, y)
        else:
            self._mouse_ctl.position = (x, y)
            time.sleep(0.01)
        b = self._button(button)
        for i in range(max(1, clicks)):
            self._mouse_ctl.press(b)
            time.sleep(max(hold_ms, 1) / 1000.0)
            self._mouse_ctl.release(b)
            if i < clicks - 1:
                time.sleep(0.05)

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: str = "left", duration_ms: int = 300) -> None:
        b = self._button(button)
        self._mouse_ctl.position = (x1, y1)
        time.sleep(0.02)
        self._mouse_ctl.press(b)
        steps = max(2, int(duration_ms / 15))
        for i in range(1, steps + 1):
            t = i / steps
            self._mouse_ctl.position = (int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
            time.sleep(duration_ms / 1000.0 / steps)
        self._mouse_ctl.release(b)

    def scroll(self, dx: int, dy: int, x: int | None = None, y: int | None = None) -> None:
        if x is not None and y is not None:
            self._mouse_ctl.position = (x, y)
            time.sleep(0.01)
        self._mouse_ctl.scroll(dx, dy)

    def _to_key(self, name: str):
        if len(name) == 1:
            return name
        return getattr(self._keyboard.Key, name)

    def press_keys(self, spec: str, hold_ms: int = 60) -> None:
        mods, key = parse_key_spec(spec)
        held = [self._to_key(m) for m in mods]
        main = self._to_key(key)
        for m in held:
            self._key_ctl.press(m)
        self._key_ctl.press(main)
        time.sleep(max(hold_ms, 1) / 1000.0)
        self._key_ctl.release(main)
        for m in reversed(held):
            self._key_ctl.release(m)
