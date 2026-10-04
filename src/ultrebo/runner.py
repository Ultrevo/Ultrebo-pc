# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Runs macros: sequence and reactive modes, plus background "watcher" steps.

Threads
-------
* a supervisor thread owns one run;
* a main worker thread performs the normal steps;
* an optional watcher thread keeps checking the screen for steps marked "watch".

Only one thing touches the mouse and keyboard at a time (the action lock). When a watcher sees its
target it takes that lock, so the main macro pauses between actions, then either lets it carry on
or stops it and starts it again from the first step.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from . import textmatch
from .imagematch import TemplateCache, find_template, to_gray
from .inputs import InputBackend
from .model import Macro, RunMode, Step, StepType, WatchAction
from .ocr import OcrEngine
from .screen import ScreenSource

MIN_SCAN_S = 0.1
DEFAULT_SCAN_S = 0.25
WATCH_COOLDOWN_S = 1.5


class Cancel:
    """A stop flag that can be chained to a parent (stopping the run stops its workers)."""

    def __init__(self, parent: "Cancel | None" = None):
        self._event = threading.Event()
        self._parent = parent

    def set(self) -> None:
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set() or (self._parent is not None and self._parent.is_set())

    def root(self) -> "Cancel":
        """The top of the chain: setting it stops the whole run."""
        return self._parent.root() if self._parent is not None else self

    def wait(self, seconds: float) -> bool:
        """Sleep up to `seconds`. Returns True if cancelled while waiting."""
        deadline = time.monotonic() + max(seconds, 0.0)
        while True:
            if self.is_set():
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._event.wait(min(remaining, 0.02))


@dataclass(frozen=True)
class Target:
    x: int
    y: int


class Frame:
    """One screenshot shared by every step checked against it; OCR runs at most once per area."""

    def __init__(self, image: np.ndarray, screen: ScreenSource, ocr: OcrEngine | None):
        self.image = image
        self._screen = screen
        self._ocr = ocr
        self._gray: np.ndarray | None = None
        self._lines: dict[tuple, list] = {}

    def _crop(self, region: list[int] | None) -> tuple[np.ndarray, int, int]:
        if not region:
            return self.image, 0, 0
        x, y, w, h = region
        px, py = self._screen.to_pixels(x, y)
        px2, py2 = self._screen.to_pixels(x + w, y + h)
        px, py = max(px, 0), max(py, 0)
        px2, py2 = min(px2, self.image.shape[1]), min(py2, self.image.shape[0])
        if px2 - px < 2 or py2 - py < 2:
            return self.image, 0, 0
        return self.image[py:py2, px:px2], px, py

    def gray(self, region: list[int] | None = None) -> tuple[np.ndarray, int, int]:
        crop, ox, oy = self._crop(region)
        if region:
            return to_gray(crop), ox, oy
        if self._gray is None:
            self._gray = to_gray(self.image)
        return self._gray, 0, 0

    def text_lines(self, region: list[int] | None = None) -> tuple[list, int, int]:
        key = tuple(region) if region else ()
        crop, ox, oy = self._crop(region)
        if key not in self._lines:
            self._lines[key] = self._ocr.read(crop) if self._ocr is not None else []
        return self._lines[key], ox, oy


class Finder:
    """Looks for a step's image or text on the screen."""

    def __init__(self, screen: ScreenSource, ocr: OcrEngine | None, templates: TemplateCache):
        self.screen = screen
        self.ocr = ocr
        self.templates = templates

    def capture(self) -> Frame:
        return Frame(self.screen.grab(), self.screen, self.ocr)

    def find(self, frame: Frame, step: Step) -> Target | None:
        if step.is_image:
            if not step.template_file:
                return None
            template = self.templates.load(step.template_file)
            if template is None:
                return None
            gray, ox, oy = frame.gray(step.region)
            match = find_template(gray, template, step.threshold)
            if match is None:
                return None
            x, y = self.screen.to_input(match.x + ox, match.y + oy)
            return Target(x, y)
        if step.is_text:
            if not step.text.strip():
                return None
            lines, ox, oy = frame.text_lines(step.region)
            match = textmatch.find(lines, step.text, step.threshold)
            if match is None:
                return None
            x, y = self.screen.to_input(match.x + ox, match.y + oy)
            return Target(x, y)
        return None


@dataclass
class _Worker:
    thread: threading.Thread
    cancel: Cancel


class Runner:
    def __init__(
        self,
        input_backend: InputBackend,
        screen: ScreenSource | None,
        ocr: OcrEngine | None,
        templates_dir: Path,
        on_status: Callable[[str], None] | None = None,
        on_state: Callable[[bool], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ):
        self.input = input_backend
        self.finder = Finder(screen, ocr, TemplateCache(templates_dir)) if screen is not None else None
        self._on_status = on_status or (lambda s: None)
        self._on_state = on_state or (lambda r: None)
        self._on_error = on_error or (lambda m: None)
        self._action_lock = threading.Lock()
        self._stop: Cancel | None = None
        self._supervisor: threading.Thread | None = None
        self._main: _Worker | None = None
        self._scan_s = DEFAULT_SCAN_S
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------ public

    @property
    def running(self) -> bool:
        return self._supervisor is not None and self._supervisor.is_alive()

    def validate(self, macro: Macro) -> str | None:
        enabled = [s for s in macro.steps if s.enabled]
        if not enabled:
            return "This macro has no enabled steps."
        for s in enabled:
            if s.is_image and not s.template_file:
                return f'The step "{s.title()}" has no image picked.'
            if s.is_text and not s.text.strip():
                return f'The step "{s.title()}" has no text entered.'
        if any(s.is_finder for s in enabled) and self.finder is None:
            return "Screen capture is not available."
        return None

    def start(self, macro: Macro) -> str | None:
        """Start running `macro`. Returns an error message, or None when it started."""
        error = self.validate(macro)
        if error:
            return error
        self.stop()
        self._scan_s = max(macro.scan_interval_ms / 1000.0, MIN_SCAN_S)
        stop = Cancel()
        self._stop = stop
        self._supervisor = threading.Thread(target=self._supervise, args=(macro, stop), daemon=True, name="ultrebo-run")
        self._set_state(True)
        self._supervisor.start()
        return None

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        sup = self._supervisor
        if sup is not None and sup is not threading.current_thread():
            sup.join(timeout=3)

    def test_step(self, step: Step) -> str | None:
        """Run one step once (the per-step test button)."""
        if self.running:
            return "A macro is already running."
        if step.is_finder and self.finder is None:
            return "Screen capture is not available."
        stop = Cancel()
        self._stop = stop
        self._scan_s = DEFAULT_SCAN_S

        def work() -> None:
            try:
                self._set_state(True)
                self._run_step(step, stop, locked=True)
            except Exception as e:  # noqa: BLE001 - report anything to the interface
                self._on_error(str(e))
            finally:
                self._set_state(False)
                self._on_status("")

        self._supervisor = threading.Thread(target=work, daemon=True, name="ultrebo-test")
        self._supervisor.start()
        return None

    # --------------------------------------------------------------- internals

    def _set_state(self, running: bool) -> None:
        self._on_state(running)

    def _supervise(self, macro: Macro, stop: Cancel) -> None:
        try:
            enabled = [s for s in macro.ordered() if s.enabled]
            watchers = [s for s in enabled if s.is_finder and s.watch]
            main_steps = [s for s in enabled if not (s.is_finder and s.watch)]

            self._main = self._spawn_main(macro, main_steps, stop)
            watcher_thread = None
            if watchers:
                watcher_thread = threading.Thread(
                    target=self._watch_loop,
                    args=(macro, watchers, main_steps, stop),
                    daemon=True,
                    name="ultrebo-watch",
                )
                watcher_thread.start()

            # Wait for the main macro to finish. A restart swaps in a new worker, so keep following it.
            while not stop.is_set():
                worker = self._main
                worker.thread.join(timeout=0.05)
                if not worker.thread.is_alive() and worker is self._main and not worker.cancel.is_set():
                    break  # finished by itself (finite loops)
            stop.set()
            if self._main is not None:
                self._main.cancel.set()
                self._main.thread.join(timeout=2)
            if watcher_thread is not None:
                watcher_thread.join(timeout=2)
        except Exception as e:  # noqa: BLE001
            self._on_error(str(e))
        finally:
            stop.set()
            self._set_state(False)
            self._on_status("")

    def _spawn_main(self, macro: Macro, steps: list[Step], stop: Cancel) -> _Worker:
        cancel = Cancel(parent=stop)
        thread = threading.Thread(target=self._run_main, args=(macro, steps, cancel), daemon=True, name="ultrebo-main")
        worker = _Worker(thread, cancel)
        thread.start()
        return worker

    def _run_main(self, macro: Macro, steps: list[Step], cancel: Cancel) -> None:
        try:
            if not steps:
                while not cancel.wait(1.0):  # only watchers: keep running until stopped
                    pass
                return
            rounds = 0
            while not cancel.is_set() and (macro.loops == 0 or rounds < macro.loops):
                rounds += 1
                if macro.mode is RunMode.SEQUENCE:
                    for step in steps:
                        if cancel.is_set():
                            return
                        self._run_step(step, cancel)
                    if cancel.wait(macro.loop_delay_ms / 1000.0):
                        return
                else:
                    self._reactive_cycle(steps, cancel)
        except Exception as e:  # noqa: BLE001
            self._on_error(str(e))
            cancel.root().set()  # a failure ends the whole run, not just this worker

    # -- one step in sequence mode
    def _run_step(self, step: Step, cancel: Cancel, locked: bool = False) -> None:
        self._on_status(step.title())
        times = max(step.repeat, 1)
        if not step.is_finder:
            for _ in range(times):
                if not self._act(step, None, cancel, locked):
                    return
                if cancel.wait(step.delay_after_ms / 1000.0):
                    return
            return
        target = self._wait_for_target(step, cancel)
        if target is None:
            return  # not found in time: skip the step
        if step.click_on_found:
            for _ in range(times):
                if not self._act(step, target, cancel, locked):
                    return
                if cancel.wait(step.delay_after_ms / 1000.0):
                    return
        else:
            cancel.wait(step.delay_after_ms / 1000.0)

    # -- reactive mode: run only the first step whose condition is met
    def _reactive_cycle(self, steps: list[Step], cancel: Cancel) -> None:
        frame = self.finder.capture() if (self.finder and any(s.is_finder for s in steps)) else None
        for step in steps:
            if cancel.is_set():
                return
            if not step.is_finder:
                self._on_status(step.title())
                self._act(step, None, cancel)
                cancel.wait(step.delay_after_ms / 1000.0)
                return
            target = self.finder.find(frame, step) if frame is not None else None
            if target is not None:
                self._on_status(step.title())
                if step.click_on_found:
                    for _ in range(max(step.repeat, 1)):
                        if not self._act(step, target, cancel):
                            return
                        if cancel.wait(step.delay_after_ms / 1000.0):
                            return
                else:
                    cancel.wait(step.delay_after_ms / 1000.0)
                return
        self._on_status("Waiting...")
        cancel.wait(self._scan_s)

    def _wait_for_target(self, step: Step, cancel: Cancel) -> Target | None:
        deadline = time.monotonic() + step.timeout_ms / 1000.0
        while not cancel.is_set():
            frame = self.finder.capture()
            target = self.finder.find(frame, step)
            if target is not None:
                return target
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if cancel.wait(min(self._scan_s, remaining)):
                return None
        return None

    # -- watchers
    def _watch_loop(self, macro: Macro, watchers: list[Step], main_steps: list[Step], stop: Cancel) -> None:
        last_seen: dict[str, float] = {}
        try:
            while not stop.wait(self._scan_s):
                frame = self.finder.capture()
                hit: tuple[Step, Target] | None = None
                now = time.monotonic()
                for w in watchers:
                    if now - last_seen.get(w.id, -1e9) < WATCH_COOLDOWN_S:
                        continue
                    target = self.finder.find(frame, w)
                    if target is not None:
                        hit = (w, target)
                        break
                if hit is None:
                    continue
                step, target = hit
                self._on_status(f"Watcher: {step.title()}")
                restart = step.on_seen is WatchAction.RESTART
                if not self._acquire(stop):
                    return
                try:
                    if step.click_on_found:
                        self.input.click(target.x, target.y, step.button, step.hold_ms, step.clicks)
                    if restart and self._main is not None:
                        self._main.cancel.set()
                        self._main.thread.join(timeout=5)
                    stop.wait(step.delay_after_ms / 1000.0)
                finally:
                    self._action_lock.release()
                if restart and not stop.is_set():
                    self._main = self._spawn_main(macro, main_steps, stop)
                last_seen[step.id] = time.monotonic()
        except Exception as e:  # noqa: BLE001
            self._on_error(str(e))
            stop.set()

    # -- doing things
    def _acquire(self, cancel: Cancel) -> bool:
        while not cancel.is_set():
            if self._action_lock.acquire(timeout=0.05):
                return True
        return False

    def _act(self, step: Step, target: Target | None, cancel: Cancel, locked: bool = False) -> bool:
        """Perform the step's action while holding the action lock. False when cancelled first."""
        if locked:
            self._perform(step, target)
            return True
        if not self._acquire(cancel):
            return False
        try:
            self._perform(step, target)
        finally:
            self._action_lock.release()
        return True

    def _perform(self, step: Step, target: Target | None) -> None:
        t = step.type
        if t is StepType.CLICK:
            self.input.click(step.x, step.y, step.button, step.hold_ms, step.clicks)
        elif t is StepType.DRAG:
            self.input.drag(step.x, step.y, step.x2, step.y2, step.button, step.hold_ms)
        elif t is StepType.SCROLL:
            at = (step.x, step.y) if (step.x or step.y) else (None, None)
            self.input.scroll(step.scroll_dx, step.scroll_dy, *at)
        elif t is StepType.KEY:
            self.input.press_keys(step.keys, step.hold_ms)
        elif target is not None:
            self.input.click(target.x, target.y, step.button, step.hold_ms, step.clicks)
