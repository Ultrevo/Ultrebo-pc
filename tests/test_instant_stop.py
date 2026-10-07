# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Pressing the stop key ends the macro at once, even in the middle of a click or key press."""
import threading
import time
import types

from conftest import FakeInput, FakeScreen, wait_until

from ultrebo.inputs import PynputInput
from ultrebo.model import Macro, Step, StepType
from ultrebo.runner import Runner


class _Mouse:
    def __init__(self):
        self.events = []
        self.position = (0, 0)

    def press(self, b):
        self.events.append("press")

    def release(self, b):
        self.events.append("release")


class _Keys:
    def __init__(self):
        self.events = []

    def press(self, k):
        self.events.append(("press", k))

    def release(self, k):
        self.events.append(("release", k))


def slow_input():
    """A real PynputInput wired to fake mouse and keyboard, so its waits and aborts are the real ones."""
    inp = PynputInput.__new__(PynputInput)
    inp._abort = threading.Event()
    inp._real_mouse = False
    inp._real_keys = False
    inp._mouse_ctl = _Mouse()
    inp._key_ctl = _Keys()
    inp._mouse = types.SimpleNamespace(Button=types.SimpleNamespace(left="L", right="R", middle="M"))
    inp._keyboard = types.SimpleNamespace(Key=types.SimpleNamespace(enter="ENTER"))
    return inp


def make_runner(inp, templates_dir, states):
    return Runner(inp, FakeScreen(lambda: None), None, templates_dir, on_state=states.append, on_error=print)


def test_stopping_cuts_a_long_click_short_and_lets_the_button_go(templates_dir):
    inp, states = slow_input(), []
    r = make_runner(inp, templates_dir, states)
    macro = Macro(name="m", steps=[Step(type=StepType.CLICK, x=5, y=5, hold_ms=10_000)])
    assert r.start(macro) is None
    assert wait_until(lambda: "press" in inp._mouse_ctl.events)

    began = time.monotonic()
    r.request_stop()
    took = time.monotonic() - began

    assert took < 0.5  # it used to wait out the whole 10-second click
    assert states == [True, False]  # "stopped" is reported straight away
    assert wait_until(lambda: not r.running, timeout=4)
    assert inp._mouse_ctl.events == ["press", "release"]  # the button is never left held down


def test_stopping_cuts_a_long_key_press_short_and_lets_the_key_go(templates_dir):
    inp, states = slow_input(), []
    r = make_runner(inp, templates_dir, states)
    macro = Macro(name="m", steps=[Step(type=StepType.KEY, keys="enter", hold_ms=10_000)])
    assert r.start(macro) is None
    assert wait_until(lambda: inp._key_ctl.events)

    began = time.monotonic()
    r.request_stop()

    assert time.monotonic() - began < 0.5
    assert wait_until(lambda: not r.running, timeout=4)
    assert inp._key_ctl.events == [("press", "ENTER"), ("release", "ENTER")]


def test_a_stopped_macro_does_no_more_clicks(templates_dir):
    inp, states = slow_input(), []
    r = make_runner(inp, templates_dir, states)
    macro = Macro(name="m", steps=[Step(type=StepType.CLICK, x=5, y=5, hold_ms=1, delay_after_ms=1)])
    r.start(macro)
    assert wait_until(lambda: len(inp._mouse_ctl.events) >= 4)
    r.request_stop()
    assert wait_until(lambda: not r.running, timeout=4)
    seen = list(inp._mouse_ctl.events)
    time.sleep(0.1)
    assert inp._mouse_ctl.events == seen
    assert seen.count("press") == seen.count("release")


def test_stopping_is_reported_once_and_a_quick_restart_is_not_overwritten(templates_dir):
    inp, states = slow_input(), []
    r = make_runner(inp, templates_dir, states)
    macro = Macro(name="m", steps=[Step(type=StepType.CLICK, x=5, y=5, hold_ms=10_000)])
    r.start(macro)
    assert wait_until(lambda: "press" in inp._mouse_ctl.events)
    r.request_stop()
    r.request_stop()  # pressing twice changes nothing
    r.start(macro)  # and starting again at once works, and the first run's wind-down doesn't say "stopped" over it
    assert wait_until(lambda: inp._mouse_ctl.events.count("press") == 2)
    assert states == [True, False, True]
    r.stop()
    assert states == [True, False, True, False]


def test_a_finished_macro_still_reports_stopped(templates_dir):
    states = []
    r = make_runner(FakeInput(), templates_dir, states)
    r.start(Macro(name="m", loops=1, steps=[Step(type=StepType.CLICK, x=1, y=1, delay_after_ms=1)]))
    assert wait_until(lambda: states == [True, False])
