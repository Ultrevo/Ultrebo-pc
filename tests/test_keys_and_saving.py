# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import threading
import enum
import json
import types

import pytest

from ultrebo import inputs, winkeys
from ultrebo.inputs import parse_key_spec, validate_key_spec
from ultrebo.model import Macro, Step, StepType
from ultrebo.recorder import RawEvent, events_to_steps
from ultrebo.store import MacroStore


# ------------------------------------------------------------------ key names

@pytest.mark.parametrize("name", [
    "enter", "Enter", "return", "ctrl+enter", "menu", "pause", "num_lock", "print_screen", "scroll_lock", "numlock",
    "prtsc", "ctrl_l", "alt_gr", "shift_r", "media_play_pause", "media_volume_up", "f21", "f24", "insert", "caps_lock",
])
def test_every_key_a_recording_can_make_is_accepted_when_editing(name):
    assert validate_key_spec(name) is None


def test_names_that_are_not_keys_are_still_refused():
    assert validate_key_spec("enter key") and validate_key_spec("Key.enter") and validate_key_spec("f25")


def test_a_recorded_macro_of_unusual_keys_can_be_saved_back_unchanged():
    names = ["menu", "num_lock", "print_screen", "pause", "scroll_lock", "insert", "enter", "caps_lock"]
    events = []
    for i, name in enumerate(names):
        events += [RawEvent("key_down", 1 + i, key=name), RawEvent("key_up", 1.05 + i, key=name)]
    steps = events_to_steps(events)
    assert [s.keys for s in steps] == names
    assert all(validate_key_spec(s.keys) is None for s in steps)  # the edit window would refuse any that failed


# ------------------------------------------------------------------ scan codes

def test_scan_codes_are_split_into_code_and_extended_flag():
    assert winkeys.split_scan(0x1C) == (0x1C, False)  # Enter
    assert winkeys.split_scan(0xE04D) == (0x4D, True)  # right arrow
    assert winkeys.split_scan(0xE11D) == (0x1D, True)
    assert winkeys.split_scan(0) == (0, False)


class _Key(enum.Enum):
    enter = types.SimpleNamespace(vk=0x0D)
    ctrl = types.SimpleNamespace(vk=0x11)
    right = types.SimpleNamespace(vk=0x27)
    weird = types.SimpleNamespace(vk=0)  # a key with no virtual-key code


def make_backend(monkeypatch, sent, scans=None, chars=None, real=True):
    backend = object.__new__(inputs.PynputInput)
    backend._abort = threading.Event()
    backend._keyboard = types.SimpleNamespace(Key=_Key)
    backend._real_keys = real
    plain = []

    class Ctl:
        def press(self, k):
            plain.append(("press", k))

        def release(self, k):
            plain.append(("release", k))

    backend._key_ctl = Ctl()
    table = {0x0D: (0x1C, False), 0x11: (0x1D, False), 0x27: (0x4D, True)} if scans is None else scans
    monkeypatch.setattr(inputs.winkeys, "scan_for_vk", lambda vk: table.get(vk))
    monkeypatch.setattr(inputs.winkeys, "vk_for_char", lambda ch: {"a": 0x41, "!": None}.get(ch))
    monkeypatch.setattr(inputs.winkeys, "send_scan", lambda scan, ext, down: sent.append((scan, ext, down)))
    monkeypatch.setattr(inputs.time, "sleep", lambda s: None)
    return backend, plain


def test_enter_is_pressed_by_scan_code_like_a_real_keyboard(monkeypatch):
    sent = []
    backend, plain = make_backend(monkeypatch, sent)
    backend.press_keys("enter")
    assert sent == [(0x1C, False, True), (0x1C, False, False)] and plain == []


def test_modifiers_are_held_around_the_key_and_released_in_reverse(monkeypatch):
    sent = []
    backend, _ = make_backend(monkeypatch, sent)
    backend.press_keys("ctrl+right")
    assert sent == [(0x1D, False, True), (0x4D, True, True), (0x4D, True, False), (0x1D, False, False)]


def test_letters_use_their_scan_code_too(monkeypatch):
    sent = []
    backend, _ = make_backend(monkeypatch, sent, scans={0x41: (0x1E, False)})
    backend.press_keys("a")
    assert sent == [(0x1E, False, True), (0x1E, False, False)]


def test_a_key_that_cannot_be_pressed_by_scan_code_falls_back_to_the_plain_way(monkeypatch):
    sent = []
    backend, plain = make_backend(monkeypatch, sent)
    backend.press_keys("!")  # needs shift, so scan codes can't type it
    assert sent == [] and plain == [("press", "!"), ("release", "!")]


def test_nothing_stays_held_if_windows_refuses_part_way(monkeypatch):
    sent = []
    backend, plain = make_backend(monkeypatch, sent)
    calls = {"n": 0}

    def flaky(scan, ext, down):
        calls["n"] += 1
        if calls["n"] == 2:  # the main key's press is refused after the modifier went down
            raise OSError("no")
        sent.append((scan, ext, down))

    monkeypatch.setattr(inputs.winkeys, "send_scan", flaky)
    backend.press_keys("ctrl+enter")
    assert (0x1D, False, True) in sent and (0x1D, False, False) in sent  # the modifier was released again
    assert plain  # and the plain way was then used


def test_other_systems_keep_the_plain_way(monkeypatch):
    sent = []
    backend, plain = make_backend(monkeypatch, sent, real=False)
    backend.press_keys("enter")
    assert sent == [] and plain == [("press", _Key.enter), ("release", _Key.enter)]


def test_an_unavailable_key_gives_a_plain_message(monkeypatch):
    sent = []
    backend, _ = make_backend(monkeypatch, sent, real=False)
    with pytest.raises(ValueError, match="isn't available on this system"):
        backend.press_keys("menu")


# ------------------------------------------------------------------ saving

def test_a_locked_file_is_retried_until_it_lets_go(tmp_path, monkeypatch):
    store = MacroStore(tmp_path)
    real = __import__("os").replace
    calls = {"n": 0}

    def locked_twice(src, dst):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError("in use by another program")
        return real(src, dst)

    monkeypatch.setattr("ultrebo.store.os.replace", locked_twice)
    monkeypatch.setattr("ultrebo.store.time.sleep", lambda s: None)
    store.add(Macro(name="Kept"))
    assert calls["n"] == 3
    assert json.loads((tmp_path / "macros.json").read_text())[0]["name"] == "Kept"


def test_a_failed_save_is_reported_instead_of_lost_silently(tmp_path, monkeypatch):
    store = MacroStore(tmp_path)
    told = []
    store.on_save_error = told.append

    def always_locked(src, dst):
        raise PermissionError("in use by another program")

    monkeypatch.setattr("ultrebo.store.os.replace", always_locked)
    monkeypatch.setattr("ultrebo.store.time.sleep", lambda s: None)
    store.add(Macro(name="X"))
    assert len(told) == 1 and "couldn't save your macros" in told[0] and "in use by another program" in told[0]


def test_without_a_listener_a_failed_save_still_raises(tmp_path, monkeypatch):
    store = MacroStore(tmp_path)
    monkeypatch.setattr("ultrebo.store.os.replace", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr("ultrebo.store.time.sleep", lambda s: None)
    with pytest.raises(PermissionError):
        store.add(Macro(name="X"))


def test_arrow_keys_and_friends_are_always_sent_as_extended_keys():
    # The first Windows build showed Right arrow with scan code 0x4d but not flagged extended: it would have been read as number pad 6.
    for vk in (0x25, 0x26, 0x27, 0x28, 0x21, 0x22, 0x23, 0x24, 0x2D, 0x2E, 0xA3, 0xA5):
        assert vk in winkeys.EXTENDED_VKS
    for vk in (0x0D, 0x41, 0x20, 0x09, 0x1B, 0x11):  # enter, a, space, tab, esc, ctrl
        assert vk not in winkeys.EXTENDED_VKS


# ------------------------------------------------------------------ recording the named keys

def test_enter_esc_and_the_other_named_keys_are_recorded_by_their_raw_name():
    from ultrebo.recorder import _key_name

    plain_code = types.SimpleNamespace(vk=0x0D, char=None)  # what pynput's "canonical" form leaves of Enter: no name at all
    assert _key_name(plain_code, types.SimpleNamespace(name="enter")) == "enter"
    for raw in ("esc", "tab", "space", "backspace", "delete", "up", "down", "left", "right", "home", "end", "page_up",
                "page_down", "insert", "caps_lock", "f5", "menu", "print_screen", "pause", "num_lock"):
        name = _key_name(types.SimpleNamespace(vk=1, char=None), types.SimpleNamespace(name=raw))
        assert name == raw and validate_key_spec(name) is None  # and the edit window accepts what was recorded


def test_modifiers_and_letters_are_still_recorded_as_before():
    from ultrebo.recorder import _key_name

    assert _key_name(types.SimpleNamespace(name="ctrl"), types.SimpleNamespace(name="ctrl_l")) == "ctrl"
    assert _key_name(types.SimpleNamespace(name="alt"), types.SimpleNamespace(name="alt_gr")) == "alt"
    assert _key_name(types.SimpleNamespace(char="a", vk=65), types.SimpleNamespace(char="A", vk=65)) == "a"
    assert _key_name(types.SimpleNamespace(char=None, vk=66), types.SimpleNamespace(char=None, vk=66)) == "b"
    assert _key_name(types.SimpleNamespace(char=None, vk=0xFF), None) == ""  # a key we have no name for is skipped
