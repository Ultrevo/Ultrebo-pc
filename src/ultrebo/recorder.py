# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Records mouse and keyboard input and turns it into editable steps.

Only the recording itself touches the operating system (through pynput). Turning the raw events
into steps is plain code in `events_to_steps`, so it can be tested without any display.
"""
from __future__ import annotations

import math
import statistics
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .inputs import MODIFIERS
from .model import Step, StepType


@dataclass
class RawEvent:
    kind: str  # mouse_down, mouse_up, scroll, key_down, key_up
    t: float  # seconds
    x: int = 0
    y: int = 0
    button: str = "left"
    dx: int = 0
    dy: int = 0
    key: str = ""


@dataclass
class _Timed:
    step: Step
    start: float
    end: float
    #: For a run of repeated key presses that was joined into one step: the pause between the presses.
    fixed_delay_ms: int | None = None


MIN_DELAY_MS = 30
LAST_DELAY_MS = 500
DOUBLE_CLICK_S = 0.35
SCROLL_JOIN_S = 0.25
#: The same key pressed again within this long counts as one run of fast presses (joined into a single repeated step).
KEY_GROUP_GAP_S = 0.5


def _join_repeated_keys(timed: list[_Timed]) -> list[_Timed]:
    """Turn a run of the same key pressed over and over, with nothing else in between, into one step with a repeat
    count. The press length and the pause between presses become the typical (median) ones of the run."""
    joined: list[_Timed] = []
    i = 0
    while i < len(timed):
        first = timed[i]
        run = [first]
        if first.step.type is StepType.KEY:
            while (
                i + len(run) < len(timed)
                and timed[i + len(run)].step.type is StepType.KEY
                and timed[i + len(run)].step.keys == first.step.keys
                and timed[i + len(run)].start - run[-1].end <= KEY_GROUP_GAP_S
            ):
                run.append(timed[i + len(run)])
        i += len(run)
        if len(run) == 1:
            joined.append(first)
            continue
        gaps = [max(int((b.start - a.end) * 1000), MIN_DELAY_MS) for a, b in zip(run, run[1:])]
        step = first.step
        step.repeat = len(run)
        step.hold_ms = int(statistics.median(r.step.hold_ms for r in run))
        joined.append(_Timed(step, first.start, run[-1].end, fixed_delay_ms=int(statistics.median(gaps))))
    return joined


def events_to_steps(events: list[RawEvent], slop: int = 8, first_priority: int = 10) -> list[Step]:
    """Convert raw events into steps, with the pauses between them as `delay_after_ms`."""
    timed: list[_Timed] = []
    mouse_down: dict[str, RawEvent] = {}
    key_down: dict[str, tuple[float, tuple[str, ...]]] = {}
    mod_down: dict[str, float] = {}
    mod_used: dict[str, bool] = {}
    held_mods: set[str] = set()

    for ev in sorted(events, key=lambda e: e.t):
        if ev.kind == "mouse_down":
            mouse_down[ev.button] = ev

        elif ev.kind == "mouse_up":
            down = mouse_down.pop(ev.button, None)
            if down is None:
                continue
            distance = math.hypot(ev.x - down.x, ev.y - down.y)
            hold = max(int((ev.t - down.t) * 1000), 20)
            if distance > slop:
                step = Step(
                    type=StepType.DRAG, x=down.x, y=down.y, x2=ev.x, y2=ev.y,
                    button=down.button, hold_ms=min(max(hold, 100), 5000),
                )
                timed.append(_Timed(step, down.t, ev.t))
            else:
                previous = timed[-1] if timed else None
                if (
                    previous is not None
                    and previous.step.type is StepType.CLICK
                    and previous.step.clicks == 1
                    and previous.step.button == down.button
                    and down.t - previous.end <= DOUBLE_CLICK_S
                    and math.hypot(previous.step.x - down.x, previous.step.y - down.y) <= slop
                ):
                    previous.step.clicks = 2
                    previous.end = ev.t
                else:
                    step = Step(type=StepType.CLICK, x=down.x, y=down.y, button=down.button, hold_ms=min(hold, 2000))
                    timed.append(_Timed(step, down.t, ev.t))

        elif ev.kind == "scroll":
            previous = timed[-1] if timed else None
            if previous is not None and previous.step.type is StepType.SCROLL and ev.t - previous.end <= SCROLL_JOIN_S:
                previous.step.scroll_dx += ev.dx
                previous.step.scroll_dy += ev.dy
                previous.end = ev.t
            else:
                timed.append(_Timed(Step(type=StepType.SCROLL, x=ev.x, y=ev.y, scroll_dx=ev.dx, scroll_dy=ev.dy), ev.t, ev.t))

        elif ev.kind == "key_down":
            if ev.key in MODIFIERS:
                if ev.key not in held_mods:
                    held_mods.add(ev.key)
                    mod_down[ev.key] = ev.t
                    mod_used[ev.key] = False
            elif ev.key not in key_down:  # ignore the operating system's key repeat
                mods = tuple(m for m in MODIFIERS if m in held_mods)
                key_down[ev.key] = (ev.t, mods)
                for m in mods:
                    mod_used[m] = True

        elif ev.kind == "key_up":
            if ev.key in MODIFIERS:
                held_mods.discard(ev.key)
                started = mod_down.pop(ev.key, None)
                if started is not None and not mod_used.pop(ev.key, False):
                    step = Step(type=StepType.KEY, keys=ev.key, hold_ms=max(int((ev.t - started) * 1000), 20))
                    timed.append(_Timed(step, started, ev.t))
            else:
                pressed = key_down.pop(ev.key, None)
                if pressed is None:
                    continue
                started, mods = pressed
                combo = "+".join(list(mods) + [ev.key])
                step = Step(type=StepType.KEY, keys=combo, hold_ms=max(int((ev.t - started) * 1000), 20))
                timed.append(_Timed(step, started, ev.t))

    timed.sort(key=lambda t: t.start)
    timed = _join_repeated_keys(timed)
    steps: list[Step] = []
    for i, item in enumerate(timed):
        if item.fixed_delay_ms is not None:
            item.step.delay_after_ms = item.fixed_delay_ms
        elif i + 1 < len(timed):
            gap = int((timed[i + 1].start - item.end) * 1000)
            item.step.delay_after_ms = max(gap, MIN_DELAY_MS)
        else:
            item.step.delay_after_ms = LAST_DELAY_MS
        item.step.priority = first_priority + i * 10
        steps.append(item.step)
    return steps


def _key_name(canonical_key, raw_key=None) -> str:
    """Our name for a pynput key (e.g. Key.ctrl_l -> "ctrl", KeyCode('a') -> "a").

    `raw_key` is the key as it arrived. pynput's "canonical" form turns Enter, Esc, Tab, Space, the arrows and the other
    named keys into a plain code with no name, so those have to be named from the raw key or they are lost.
    """
    name = getattr(raw_key, "name", None) or getattr(canonical_key, "name", None)
    if name:
        for suffix in ("_l", "_r", "_gr"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return {"cmd": "cmd", "alt": "alt", "ctrl": "ctrl", "shift": "shift"}.get(name, name)
    char = getattr(canonical_key, "char", None)
    if char:
        return char.lower()
    vk = getattr(canonical_key, "vk", None)
    if vk is not None and (48 <= vk <= 57 or 65 <= vk <= 90):
        return chr(vk).lower()
    return ""


class Recorder:
    """Listens to the mouse and keyboard until stopped. Real input still reaches the game."""

    def __init__(self, ignore_keys: set[str] | None = None, on_activity: Callable[[], None] | None = None):
        self.ignore_keys = {k.lower() for k in (ignore_keys or set())}
        self.on_activity = on_activity
        self._events: list[RawEvent] = []
        self._lock = threading.Lock()
        self._mouse_listener = None
        self._key_listener = None
        self._last_pos = (0, 0)
        self.recording = False

    def start(self) -> None:
        from pynput import keyboard, mouse

        self._events = []
        self.recording = True

        def add(ev: RawEvent) -> None:
            with self._lock:
                self._events.append(ev)
            if self.on_activity:
                self.on_activity()

        def on_move(x, y):
            self._last_pos = (int(x), int(y))

        def on_click(x, y, button, pressed):
            add(RawEvent("mouse_down" if pressed else "mouse_up", time.monotonic(), int(x), int(y), button.name))

        def on_scroll(x, y, dx, dy):
            add(RawEvent("scroll", time.monotonic(), int(x), int(y), dx=int(dx), dy=int(dy)))

        self._key_listener = keyboard.Listener(on_press=None, on_release=None)

        def on_press(key):
            name = _key_name(self._key_listener.canonical(key), key)
            if name and name not in self.ignore_keys:
                add(RawEvent("key_down", time.monotonic(), key=name))

        def on_release(key):
            name = _key_name(self._key_listener.canonical(key), key)
            if name and name not in self.ignore_keys:
                add(RawEvent("key_up", time.monotonic(), key=name))

        self._key_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._mouse_listener = mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll)
        self._key_listener.start()
        self._mouse_listener.start()

    def stop(self, first_priority: int = 10) -> list[Step]:
        self.recording = False
        for listener in (self._mouse_listener, self._key_listener):
            if listener is not None:
                listener.stop()
        self._mouse_listener = self._key_listener = None
        with self._lock:
            events = list(self._events)
        return events_to_steps(events, first_priority=first_priority)
