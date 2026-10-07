# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""A rule can press a key when its image or text appears (after the click, or instead of it)."""
import cv2
import numpy as np
from conftest import FakeInput, FakeScreen, wait_until, with_pattern
from PySide6.QtCore import QEvent

from ultrebo import rulepack
from ultrebo.model import Macro, Step, StepType
from ultrebo.runner import Runner
from ultrebo.store import MacroStore
from ultrebo.ui.context import AppContext
from ultrebo.ui.step_dialog import StepDialog


def rule(**kw):
    return Step(type=StepType.IMAGE, template_file="button.png", watch=True, priority=10, delay_after_ms=20,
                name="Claim", **kw)


def make_runner(templates_dir, frame):
    inp = FakeInput()
    errors = []
    return Runner(inp, FakeScreen(lambda: frame), None, templates_dir, on_error=errors.append), inp, errors


def test_the_key_is_pressed_after_the_click(templates_dir, blank, pattern):
    r, inp, errors = make_runner(templates_dir, with_pattern(blank, pattern))
    r.start(Macro(loops=0, scan_interval_ms=100, rules=[rule(press_key="e")]))
    assert wait_until(lambda: any(c[1] == "keys" for c in inp.calls))
    r.stop()
    kinds = [c[1] for c in inp.calls]
    assert kinds[:2] == ["click", "keys"]
    assert [c[2] for c in inp.calls if c[1] == "keys"][0] == "e"
    assert errors == []


def test_a_rule_can_press_a_key_without_clicking(templates_dir, blank, pattern):
    r, inp, _ = make_runner(templates_dir, with_pattern(blank, pattern))
    r.start(Macro(loops=0, scan_interval_ms=100, rules=[rule(press_key="ctrl+s", click_on_found=False)]))
    assert wait_until(lambda: any(c[1] == "keys" for c in inp.calls))
    r.stop()
    assert inp.clicks() == []
    assert [c[2] for c in inp.calls if c[1] == "keys"][0] == "ctrl+s"


def test_without_a_key_nothing_is_pressed(templates_dir, blank, pattern):
    r, inp, _ = make_runner(templates_dir, with_pattern(blank, pattern))
    r.start(Macro(loops=0, scan_interval_ms=100, rules=[rule()]))
    assert wait_until(lambda: len(inp.clicks()) >= 1)
    r.stop()
    assert not any(c[1] == "keys" for c in inp.calls)


def test_a_key_that_makes_no_sense_stops_the_macro_from_starting(templates_dir, blank, pattern):
    r, inp, _ = make_runner(templates_dir, with_pattern(blank, pattern))
    error = r.validate(Macro(loops=0, rules=[rule(press_key="ctrl+")]))
    assert error and "Claim" in error and "key" in error
    assert r.start(Macro(loops=0, rules=[rule(press_key="bogus")])) is not None


def test_the_rule_test_button_presses_the_key_too(templates_dir, blank, pattern):
    r, inp, _ = make_runner(templates_dir, with_pattern(blank, pattern))
    assert r.test_step(rule(press_key="enter")) is None
    assert wait_until(lambda: any(c[1] == "keys" for c in inp.calls))


def test_the_rules_list_says_which_key_is_pressed():
    assert rule(press_key="e").rule_summary().startswith("When an image appears: click it, then press e, then ")
    assert "press" not in rule().rule_summary()
    assert "click it" not in rule(press_key="f5", click_on_found=False).rule_summary()


def test_the_rule_dialog_saves_the_key(qapp, tmp_path):
    ctx = AppContext(store=MacroStore(tmp_path), screen=None, runner=None)
    d = StepDialog(ctx, Step(type=StepType.TEXT, watch=True, press_key="x"), None, rule=True, groups=[])
    assert d.press_key.text() == "x"
    d.t_text.setText("hi")
    d.press_key.setText(" ctrl+e ")
    d._accept()
    assert d.result_step().press_key == "ctrl+e"
    d.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_the_rule_dialog_refuses_a_bad_key(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    ctx = AppContext(store=MacroStore(tmp_path), screen=None, runner=None)
    d = StepDialog(ctx, Step(type=StepType.TEXT, watch=True), None, rule=True, groups=[])
    d.t_text.setText("hi")
    d.press_key.setText("ctrl+")
    d._accept()
    assert warned and d.result() != d.DialogCode.Accepted
    d.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_shared_rules_keep_a_valid_key_and_drop_a_bad_one(tmp_path):
    store, other = MacroStore(tmp_path / "a"), MacroStore(tmp_path / "b")
    ok, data = cv2.imencode(".png", np.random.default_rng(1).integers(0, 255, size=(20, 30, 3), dtype=np.uint8))
    picture = store.save_template_bytes(data.tobytes())
    macro = Macro(name="m", rules=[
        Step(type=StepType.IMAGE, template_file=picture, watch=True, name="good", priority=1, press_key="e"),
        Step(type=StepType.IMAGE, template_file=picture, watch=True, name="bad", priority=2, press_key="not-a-key"),
    ])
    path = tmp_path / f"p{rulepack.EXTENSION}"
    rulepack.export_pack(macro, store.templates_dir, path)
    _, rules, _ = rulepack.read_pack(path, other.save_template_bytes, other.delete_template)
    assert [(r.name, r.press_key) for r in rules] == [("good", "e"), ("bad", "")]
