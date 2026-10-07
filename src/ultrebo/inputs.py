# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Sends mouse and keyboard input. The runner only talks to the InputBackend interface."""
from __future__ import annotations

import time
from typing import Protocol

from . import winkeys, winmouse

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
_FUNCTION_KEYS = {f"f{i}" for i in range(1, 25)}
#: Other keys by the names pynput gives them (a recording can produce any of these).
_NAMED_KEYS = {
    "alt_l", "alt_r", "alt_gr", "ctrl_l", "ctrl_r", "shift_l", "shift_r", "cmd_l", "cmd_r",
    "menu", "num_lock", "pause", "print_screen", "scroll_lock",
    "media_play_pause", "media_stop", "media_volume_mute", "media_volume_down", "media_volume_up",
    "media_previous", "media_next",
}
_MORE_ALIASES = {"numlock": "num_lock", "scrolllock": "scroll_lock", "printscreen": "print_screen", "prtsc": "print_screen",
                 "apps": "menu", "break": "pause"}


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
    if n in _FUNCTION_KEYS or n in _NAMED_KEYS:
        return n
    if n in _MORE_ALIASES:
        return _MORE_ALIASES[n]
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
        #: On Windows the pointer is moved with real mouse input; see winmouse.py for why that matters to some games.
        self._real_mouse = winmouse.available()
        #: Same idea for the keyboard: on Windows keys are pressed by scan code, which games understand.
        self._real_keys = winkeys.available()

    def _place(self, x: int, y: int) -> None:
        """Put the pointer at (x, y)."""
        if self._real_mouse:
            try:
                winmouse.move_to(x, y)
                return
            except Exception:  # noqa: BLE001 - fall back to the plain way rather than failing the macro
                self._real_mouse = False
        self._mouse_ctl.position = (x, y)

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
            self._place(round(sx + (x - sx) * t), round(sy + (y - sy) * t))
            time.sleep(0.008)
        for dx, dy in WIGGLE:
            self._place(x + dx, y + dy)
            time.sleep(0.012)
        if self._real_mouse:
            # games that read raw mouse movement want to see a small push of the mouse, then back on the spot
            try:
                winmouse.move_by(2, 1)
                time.sleep(0.012)
                winmouse.move_by(-2, -1)
                time.sleep(0.012)
            except Exception:  # noqa: BLE001
                pass
            self._place(x, y)
            time.sleep(0.05)  # let the game draw a frame with the pointer over the target before the click
        time.sleep(0.02)

    def click(
        self, x: int, y: int, button: str = "left", hold_ms: int = 60, clicks: int = 1, nudge: bool = False
    ) -> None:
        if nudge:
            self._approach(x, y)
        else:
            self._place(x, y)
            time.sleep(0.05 if self._real_mouse else 0.01)
        b = self._button(button)
        for i in range(max(1, clicks)):
            self._mouse_ctl.press(b)
            time.sleep(max(hold_ms, 1) / 1000.0)
            self._mouse_ctl.release(b)
            if i < clicks - 1:
                time.sleep(0.05)

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: str = "left", duration_ms: int = 300) -> None:
        b = self._button(button)
        self._place(x1, y1)
        time.sleep(0.02)
        self._mouse_ctl.press(b)
        steps = max(2, int(duration_ms / 15))
        for i in range(1, steps + 1):
            t = i / steps
            self._place(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
            time.sleep(duration_ms / 1000.0 / steps)
        self._mouse_ctl.release(b)

    def scroll(self, dx: int, dy: int, x: int | None = None, y: int | None = None) -> None:
        if x is not None and y is not None:
            self._place(x, y)
            time.sleep(0.01)
        self._mouse_ctl.scroll(dx, dy)

    def _to_key(self, name: str):
        if len(name) == 1:
            return name
        key = getattr(self._keyboard.Key, name, None)
        if key is None:
            raise ValueError(f'The key "{name}" isn\'t available on this system.')
        return key

    def _scan_codes(self, names: list[str]) -> list[tuple[int, bool]]:
        """Scan code and extended flag for each key name, or raises when one can't be pressed this way."""
        out = []
        for name in names:
            vk = winkeys.vk_for_char(name) if len(name) == 1 else getattr(self._to_key(name), "value").vk
            code = winkeys.scan_for_vk(vk) if vk else None
            if code is None:
                raise ValueError(name)
            out.append(code)
        return out

    def _press_by_scan_code(self, mods: list[str], key: str, hold_ms: int) -> None:
        codes = self._scan_codes([*mods, key])  # work everything out first, so a failure sends nothing
        down: list[tuple[int, bool]] = []
        try:
            for code in codes:
                winkeys.send_scan(*code, True)
                down.append(code)
            time.sleep(max(hold_ms, 1) / 1000.0)
        finally:
            for code in reversed(down):  # never leave a key held down, whatever went wrong
                try:
                    winkeys.send_scan(*code, False)
                except Exception:  # noqa: BLE001
                    pass

    def press_keys(self, spec: str, hold_ms: int = 60) -> None:
        mods, key = parse_key_spec(spec)
        if self._real_keys:
            try:
                self._press_by_scan_code(mods, key, hold_ms)
                return
            except Exception:  # noqa: BLE001 - a key with no scan code (or a refusal): use the plain way instead
                pass
        held = [self._to_key(m) for m in mods]
        main = self._to_key(key)
        for m in held:
            self._key_ctl.press(m)
        self._key_ctl.press(main)
        time.sleep(max(hold_ms, 1) / 1000.0)
        self._key_ctl.release(main)
        for m in reversed(held):
            self._key_ctl.release(m)
