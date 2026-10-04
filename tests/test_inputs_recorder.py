# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import pytest

from ultrebo.hotkeys import to_pynput_format
from ultrebo.inputs import normalize_key_name, parse_key_spec, validate_key_spec
from ultrebo.model import StepType
from ultrebo.recorder import RawEvent, events_to_steps
from ultrebo import updater


def test_key_specs():
    assert parse_key_spec("a") == ([], "a")
    assert parse_key_spec("Ctrl+Shift+S") == (["ctrl", "shift"], "s")
    assert parse_key_spec("win+d") == (["cmd"], "d")
    assert parse_key_spec("ctrl++") == (["ctrl"], "+")
    assert parse_key_spec("PageDown") == ([], "page_down")
    assert parse_key_spec("f12") == ([], "f12")
    for bad in ("", "ctrl+", "a+b", "nonsense", "f99"):
        assert validate_key_spec(bad) is not None
    assert validate_key_spec("ctrl+c") is None
    assert normalize_key_name("ESC") == "esc"


def test_hotkey_formatting():
    assert to_pynput_format("f8") == "<f8>"
    assert to_pynput_format("ctrl+shift+s") == "<ctrl>+<shift>+s"
    assert to_pynput_format("page_up") == "<page_up>"


def ev(kind, t, **kw):
    return RawEvent(kind, t, **kw)


def test_click_drag_and_delays():
    events = [
        ev("mouse_down", 1.00, x=100, y=100), ev("mouse_up", 1.06, x=101, y=100),
        ev("mouse_down", 2.00, x=10, y=10), ev("mouse_up", 2.30, x=210, y=10),
    ]
    steps = events_to_steps(events)
    assert [s.type for s in steps] == [StepType.CLICK, StepType.DRAG]
    assert (steps[0].x, steps[0].y, steps[0].hold_ms) == (100, 100, 60)
    assert steps[0].delay_after_ms == 940 and steps[1].delay_after_ms == 500
    assert (steps[1].x2, steps[1].y2) == (210, 10)
    assert [s.priority for s in steps] == [10, 20]


def test_double_click_is_merged():
    events = [
        ev("mouse_down", 1.00, x=50, y=50), ev("mouse_up", 1.05, x=50, y=50),
        ev("mouse_down", 1.15, x=51, y=50), ev("mouse_up", 1.20, x=51, y=50),
    ]
    steps = events_to_steps(events)
    assert len(steps) == 1 and steps[0].clicks == 2


def test_right_click_keeps_button():
    steps = events_to_steps([ev("mouse_down", 1, x=5, y=5, button="right"), ev("mouse_up", 1.05, x=5, y=5, button="right")])
    assert steps[0].button == "right"


def test_scroll_events_are_joined():
    events = [ev("scroll", 1.00, dy=-1), ev("scroll", 1.05, dy=-1), ev("scroll", 1.10, dy=-1), ev("scroll", 3.0, dy=2)]
    steps = events_to_steps(events)
    assert [(s.type, s.scroll_dy) for s in steps] == [(StepType.SCROLL, -3), (StepType.SCROLL, 2)]


def test_keys_combos_and_lone_modifiers():
    events = [
        ev("key_down", 1.0, key="a"), ev("key_up", 1.1, key="a"),
        ev("key_down", 2.0, key="ctrl"), ev("key_down", 2.05, key="c"), ev("key_up", 2.15, key="c"), ev("key_up", 2.2, key="ctrl"),
        ev("key_down", 3.0, key="shift"), ev("key_up", 3.1, key="shift"),
    ]
    steps = events_to_steps(events)
    assert [s.keys for s in steps] == ["a", "ctrl+c", "shift"]
    assert all(s.type is StepType.KEY for s in steps)


def test_key_repeat_is_ignored():
    events = [ev("key_down", 1.0, key="w"), ev("key_down", 1.03, key="w"), ev("key_down", 1.06, key="w"), ev("key_up", 1.5, key="w")]
    steps = events_to_steps(events)
    assert len(steps) == 1 and steps[0].hold_ms == 500


def test_unmatched_events_do_not_crash():
    assert events_to_steps([ev("mouse_up", 1, x=1, y=1), ev("key_up", 2, key="a")]) == []


def test_update_parsing():
    body = '{"tag_name":"v0.2.0","html_url":"https://github.com/Ultrevo/Ultrebo-pc/releases/tag/v0.2.0"}'
    u = updater.parse_release(body, "0.1.0")
    assert u is not None and u.version == "0.2.0"
    assert updater.parse_release(body, "0.2.0") is None
    assert updater.parse_release('{"tag_name":"v9","html_url":"https://evil.example/x"}', "0.1.0") is None
    assert updater.parse_release("not json", "0.1.0") is None
