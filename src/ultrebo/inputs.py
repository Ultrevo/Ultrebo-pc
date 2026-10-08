# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Sends mouse and keyboard input. The runner only talks to the InputBackend interface."""
from __future__ import annotations

import math
import threading
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


class Aborted(Exception):
    """Raised inside an input action when the macro is stopped partway through it."""


#: How long the cursor takes to travel to a click position unless the macro says otherwise.
DEFAULT_MOVE_MS = 50
MAX_MOVE_MS = 5000
#: The wiggle before a nudged click is tiny: it never goes further than this many pixels from the target, and no
#: single move of it is longer than this either.
WIGGLE_MAX_PX = 3
#: Offsets (pixels) of the little wiggle; it always ends exactly on the target.
WIGGLE = ((1, 1), (-1, -1), (1, -1), (0, 0))
#: The small push the real mouse is given on Windows (and then taken back), in pixels.
PUSH = (1, 0)


class InputBackend(Protocol):
    def click(
        self, x: int, y: int, button: str = "left", hold_ms: int = 60, clicks: int = 1, nudge: bool = False
    ) -> None: ...

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: str = "left", duration_ms: int = 300) -> None: ...

    def scroll(self, dx: int, dy: int, x: int | None = None, y: int | None = None) -> None: ...

    def press_keys(self, spec: str, hold_ms: int = 60) -> None: ...


class PynputInput:
    """Real input via pynput (Windows, macOS and Linux/X11)."""

    _move_ms = DEFAULT_MOVE_MS
    last_lead_s = 0.0

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
        #: Set when the macro is stopped: any click, drag or key press in progress ends right away.
        self._abort = threading.Event()
        self._move_ms = DEFAULT_MOVE_MS
        #: How long the last click, drag or scroll spent getting the cursor there and settling, before it pressed.
        self.last_lead_s = 0.0

    def set_move_ms(self, ms: int) -> None:
        """How long the cursor takes to travel to each position (0 = jump straight there)."""
        self._move_ms = min(max(int(ms), 0), MAX_MOVE_MS)

    def abort(self) -> None:
        """Cut short whatever is being pressed or moved. Buttons and keys already down are still let go."""
        self._abort.set()

    def reset_abort(self) -> None:
        self._abort.clear()

    def _nap(self, seconds: float) -> None:
        """Sleep, but give up the moment the macro is stopped."""
        if self._abort.wait(max(seconds, 0.0)):
            raise Aborted()

    def _place(self, x: int, y: int) -> None:
        """Put the pointer at (x, y)."""
        if self._real_mouse:
            try:
                winmouse.move_to(x, y)
                return
            except Exception:  # noqa: BLE001 - fall back to the plain way rather than failing the macro
                self._real_mouse = False
        self._mouse_ctl.position = (x, y)

    def _glide_to(self, x: int, y: int) -> None:
        """Move the cursor to (x, y) over the macro's move time, instead of teleporting there.

        The path is worked out from the clock, not from a fixed number of steps, so it takes the time asked for
        however coarse the computer's timer is, and always ends exactly on (x, y)."""
        try:
            sx, sy = self._mouse_ctl.position
        except Exception:  # noqa: BLE001
            sx, sy = x, y
        total = self._move_ms / 1000.0
        if total <= 0 or math.hypot(x - sx, y - sy) < 2:
            self._place(x, y)
            return
        began = time.perf_counter()
        while True:
            t = (time.perf_counter() - began) / total
            if t >= 1.0:
                break
            self._place(round(sx + (x - sx) * t), round(sy + (y - sy) * t))
            self._nap(0.004)
        self._place(x, y)

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
        self._glide_to(x, y)
        for dx, dy in WIGGLE:
            self._place(x + dx, y + dy)
            self._nap(0.012)
        if self._real_mouse:
            # games that read raw mouse movement want to see a small push of the mouse, then back on the spot
            try:
                winmouse.move_by(*PUSH)
                self._nap(0.012)
                winmouse.move_by(-PUSH[0], -PUSH[1])
                self._nap(0.012)
            except Aborted:
                raise
            except Exception:  # noqa: BLE001
                pass
            self._place(x, y)
            self._nap(0.05)  # let the game draw a frame with the pointer over the target before the click
        self._nap(0.02)

    def click(
        self, x: int, y: int, button: str = "left", hold_ms: int = 60, clicks: int = 1, nudge: bool = False
    ) -> None:
        began = time.perf_counter()
        self.last_lead_s = 0.0
        if nudge:
            self._approach(x, y)
        else:
            self._glide_to(x, y)
            self._nap(0.05 if self._real_mouse else 0.01)
        self.last_lead_s = time.perf_counter() - began
        b = self._button(button)
        for i in range(max(1, clicks)):
            self._mouse_ctl.press(b)
            try:
                self._nap(max(hold_ms, 1) / 1000.0)
            finally:
                self._mouse_ctl.release(b)  # never leave the button held down, even when stopped mid-click
            if i < clicks - 1:
                self._nap(0.05)

    def drag(self, x1: int, y1: int, x2: int, y2: int, button: str = "left", duration_ms: int = 300) -> None:
        b = self._button(button)
        began = time.perf_counter()
        self.last_lead_s = 0.0
        self._glide_to(x1, y1)
        self._nap(0.02)
        self.last_lead_s = time.perf_counter() - began
        self._mouse_ctl.press(b)
        try:
            steps = max(2, int(duration_ms / 15))
            for i in range(1, steps + 1):
                t = i / steps
                self._place(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
                self._nap(duration_ms / 1000.0 / steps)
        finally:
            self._mouse_ctl.release(b)

    def scroll(self, dx: int, dy: int, x: int | None = None, y: int | None = None) -> None:
        began = time.perf_counter()
        self.last_lead_s = 0.0
        if x is not None and y is not None:
            self._glide_to(x, y)
            self._nap(0.01)
        self.last_lead_s = time.perf_counter() - began
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
            self._nap(max(hold_ms, 1) / 1000.0)
        finally:
            for code in reversed(down):  # never leave a key held down, whatever went wrong
                try:
                    winkeys.send_scan(*code, False)
                except Exception:  # noqa: BLE001
                    pass

    def press_keys(self, spec: str, hold_ms: int = 60) -> None:
        self.last_lead_s = 0.0
        mods, key = parse_key_spec(spec)
        if self._real_keys:
            try:
                self._press_by_scan_code(mods, key, hold_ms)
                return
            except Aborted:
                raise
            except Exception:  # noqa: BLE001 - a key with no scan code (or a refusal): use the plain way instead
                pass
        held = [self._to_key(m) for m in mods]
        main = self._to_key(key)
        pressed = []
        try:
            for m in [*held, main]:
                self._key_ctl.press(m)
                pressed.append(m)
            self._nap(max(hold_ms, 1) / 1000.0)
        finally:
            for k in reversed(pressed):  # never leave a key held down, even when stopped mid-press
                self._key_ctl.release(k)
