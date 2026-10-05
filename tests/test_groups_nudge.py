# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from conftest import FakeInput, FakeScreen, wait_until, with_pattern
from ultrebo import inputs
from ultrebo import runner as runner_module
from ultrebo.inputs import PynputInput
from ultrebo.model import Macro, RuleGroup, RunMode, Step, StepType, WatchAction
from ultrebo.runner import Runner
from ultrebo.ui.groups_dialog import GroupsDialog
from ultrebo.ui.step_dialog import StepDialog


# ------------------------------------------------------------------------------- the mouse wiggle

class FakeMouse:
    def __init__(self, start=(900, 700)):
        self.moves = [start]
        self.events = []

    @property
    def position(self):
        return self.moves[-1]

    @position.setter
    def position(self, pos):
        self.moves.append(tuple(pos))

    def press(self, b):
        self.events.append(("press", self.moves[-1]))

    def release(self, b):
        self.events.append(("release", self.moves[-1]))


def real_input(mouse):
    inp = PynputInput.__new__(PynputInput)
    inp._mouse_ctl = mouse
    inp._real_mouse = False  # these tests are about the plain way of moving; see test_winmouse.py for Windows

    class Buttons:
        left = right = middle = "b"

    class Mouse:
        Button = Buttons

    inp._mouse = Mouse
    return inp


def test_a_nudged_click_glides_in_and_wiggles_before_it_clicks():
    mouse = FakeMouse(start=(900, 700))
    real_input(mouse).click(200, 150, hold_ms=1, nudge=True)
    moves = mouse.moves[1:]
    assert len(moves) >= inputs.GLIDE_STEPS + len(inputs.WIGGLE)  # many small moves, not one jump
    assert moves[inputs.GLIDE_STEPS - 1] == (200, 150)  # the glide arrives on the target
    assert any(m != (200, 150) for m in moves[inputs.GLIDE_STEPS:-1])  # then it wiggles around it
    assert moves[-1] == (200, 150)  # and ends exactly on it
    xs = [m[0] for m in moves[:inputs.GLIDE_STEPS]]
    assert xs == sorted(xs, reverse=True)  # coming from the right, in order
    assert [e[0] for e in mouse.events] == ["press", "release"] and all(e[1] == (200, 150) for e in mouse.events)


def test_a_plain_click_still_just_places_the_cursor():
    mouse = FakeMouse()
    real_input(mouse).click(200, 150, hold_ms=1)
    assert mouse.moves[1:] == [(200, 150)]


# -------------------------------------------------------------------------------- rules and groups

@pytest.fixture(autouse=True)
def short_cooldown(monkeypatch):
    monkeypatch.setattr(runner_module, "WATCH_COOLDOWN_S", 0.3)


def pictures(templates_dir, pattern):
    other = np.flip(pattern, axis=0).copy()
    cv2.imwrite(str(templates_dir / "other.png"), other)
    return other


def rule(file, priority, group=None, **kw):
    return Step(type=StepType.IMAGE, template_file=file, watch=True, priority=priority, delay_after_ms=20,
                name=file, group_id=group, **kw)


def make_runner(templates_dir, frame):
    inp = FakeInput()
    return Runner(inp, FakeScreen(lambda: frame), None, templates_dir), inp


def test_rules_ask_for_the_mouse_wiggle_unless_switched_off(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp = make_runner(templates_dir, frame)
    r.start(Macro(loops=0, scan_interval_ms=100, rules=[rule("button.png", 10)]))
    assert wait_until(lambda: len(inp.clicks()) >= 1)
    r.stop()
    assert inp.nudged[0] is True

    r, inp = make_runner(templates_dir, frame)
    r.start(Macro(loops=0, scan_interval_ms=100, rules=[rule("button.png", 10, nudge=False)]))
    assert wait_until(lambda: len(inp.clicks()) >= 1)
    r.stop()
    assert set(inp.nudged) == {False}


def test_the_rule_test_button_wiggles_like_the_real_rule(templates_dir, blank, pattern):
    r, inp = make_runner(templates_dir, with_pattern(blank, pattern))
    assert r.test_step(rule("button.png", 10)) is None
    assert wait_until(lambda: inp.nudged)
    assert inp.nudged[0] is True


def test_once_one_rule_in_a_group_is_found_the_whole_group_stops(templates_dir, blank, pattern):
    other = pictures(templates_dir, pattern)
    frame = with_pattern(with_pattern(blank, pattern, 200, 120), other, 40, 40)  # both pictures are on screen
    group = RuleGroup(name="Pop-ups", pause_s=0)
    r, inp = make_runner(templates_dir, frame)
    solo = rule("other.png", 30)  # not in the group: keeps being handled
    r.start(Macro(loops=0, scan_interval_ms=100, groups=[group], rules=[
        rule("button.png", 10, group.id), rule("other.png", 20, group.id), solo]))
    time.sleep(1.6)  # several cooldowns' worth
    r.stop()
    spots = [round(x, -1) for _, x, y in inp.clicks()]
    # the first rule is found, then its group rests: the group's second rule never fires, the solo rule keeps going
    assert spots.count(230) == 1
    assert spots.count(70) >= 2  # the same picture is also watched by the solo rule, which is not in the group


def test_a_group_can_wake_up_again_after_its_pause(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    group = RuleGroup(name="Pop-ups", pause_s=1)
    r, inp = make_runner(templates_dir, frame)
    r.start(Macro(loops=0, scan_interval_ms=100, groups=[group], rules=[rule("button.png", 10, group.id)]))
    assert wait_until(lambda: len(inp.clicks()) >= 2, timeout=6)
    r.stop()
    first, second = inp.clicks()[0][0], inp.clicks()[1][0]
    assert second - first >= 0.9  # it rested for the pause, then looked again


def test_rules_without_a_group_are_unaffected(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp = make_runner(templates_dir, frame)
    r.start(Macro(loops=0, scan_interval_ms=100, rules=[rule("button.png", 10)]))
    assert wait_until(lambda: len(inp.clicks()) >= 3, timeout=5)
    r.stop()


# ----------------------------------------------------------------------------------------- model

def test_groups_survive_saving_and_stale_group_ids_are_dropped():
    g = RuleGroup(name="A", pause_s=12)
    macro = Macro(groups=[g], rules=[Step(type=StepType.TEXT, text="x", watch=True, group_id=g.id),
                                     Step(type=StepType.TEXT, text="y", watch=True, group_id="gone")])
    again = Macro.from_dict(macro.to_dict())
    assert again.groups[0].name == "A" and again.groups[0].pause_s == 12
    assert again.rules[0].group_id == g.id and again.rules[1].group_id is None
    assert again.group_name(g.id) == "A" and again.group_name("nope") == ""
    again.delete_group(g.id)
    assert again.groups == [] and again.rules[0].group_id is None
    assert RuleGroup.from_dict({"pause_s": "junk", "name": ""}).pause_s == 0


# ------------------------------------------------------------------------------------------- UI

def test_rule_dialog_offers_the_group_and_wiggle_choices(qapp, tmp_path):
    from ultrebo.store import MacroStore
    from ultrebo.ui.context import AppContext

    store = MacroStore(tmp_path)
    ctx = AppContext(store=store, screen=None, runner=None)
    g = RuleGroup(name="Pop-ups")
    d = StepDialog(ctx, Step(type=StepType.TEXT, watch=True, group_id=g.id), None, rule=True, groups=[g])
    assert [d.group_box.itemText(i) for i in range(d.group_box.count())] == ["(no group)", "Pop-ups"]
    assert d.group_box.currentData() == g.id and d.nudge.isChecked()
    d.t_text.setText("hi")
    d.nudge.setChecked(False)
    d.group_box.setCurrentIndex(0)
    d._accept()
    s = d.result_step()
    assert s.group_id is None and s.nudge is False
    d.deleteLater()  # a top-level dialog left for garbage collection can crash Qt at exit
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_groups_dialog_adds_renames_and_deletes(qapp, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    macro = Macro(rules=[Step(type=StepType.TEXT, text="x", watch=True)])
    d = GroupsDialog(macro)
    names = iter(["Pop-ups", "Pop-ups", "Daily"])  # the second one clashes with the first
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: (next(names), True))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    d._new()
    d._new()
    assert [g.name for g in macro.groups] == ["Pop-ups"] and "already a group" in warnings[-1]
    d.pause.setValue(45)
    assert macro.groups[0].pause_s == 45
    d._rename()
    assert macro.groups[0].name == "Daily"
    macro.rules[0].group_id = macro.groups[0].id
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    d._delete()
    assert macro.groups == [] and macro.rules[0].group_id is None
    d.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ------------------------------------------------------------------ groups waking up on a restart

def test_group_gate_rests_pauses_and_resets():
    now = [100.0]
    a = RuleGroup(name="forever")
    b = RuleGroup(name="timed", pause_s=10)
    c = RuleGroup(name="resets", reset_on_restart=True)
    from ultrebo.runner import GroupGate

    gate = GroupGate([a, b, c], clock=lambda: now[0])
    assert not gate.is_resting(None) and not gate.is_resting(a.id)
    assert gate.found(None) is None and gate.found("unknown") is None
    for g in (a, b, c):
        assert gate.found(g.id) is g
        assert gate.is_resting(g.id)
    now[0] += 11
    assert not gate.is_resting(b.id) and gate.is_resting(a.id) and gate.is_resting(c.id)  # the pause is over
    gate.restarted()
    assert gate.is_resting(a.id) and not gate.is_resting(c.id)  # only groups set to re-enable wake up


def loop_macro(group, rules, steps=None):
    steps = steps if steps is not None else [Step(type=StepType.CLICK, x=1, y=1, delay_after_ms=10, hold_ms=1, priority=10)]
    return Macro(loops=0, loop_delay_ms=50, scan_interval_ms=100, groups=[group], steps=steps, rules=rules)


def rule_clicks(inp):
    return [x for _, x, y in inp.clicks() if x > 100]  # the rule's picture is on the right of the screen


def test_a_finished_loop_wakes_groups_that_reenable_on_restart(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp = make_runner(templates_dir, frame)
    group = RuleGroup(name="Pop-ups", reset_on_restart=True)
    r.start(loop_macro(group, [rule("button.png", 10, group.id)]))
    assert wait_until(lambda: len(rule_clicks(inp)) >= 3, timeout=8)  # found again after each loop starts over
    r.stop()


def test_without_the_option_a_finished_loop_does_not_wake_the_group(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp = make_runner(templates_dir, frame)
    group = RuleGroup(name="Pop-ups", reset_on_restart=False)
    r.start(loop_macro(group, [rule("button.png", 10, group.id)]))
    time.sleep(2.5)
    r.stop()
    assert len(rule_clicks(inp)) == 1


def test_a_rule_that_restarts_the_macro_wakes_groups_set_to_reenable(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    for reset, expected_many in ((True, True), (False, False)):
        r, inp = make_runner(templates_dir, frame)
        group = RuleGroup(name="Pop-ups", reset_on_restart=reset)
        restarting = rule("button.png", 10, group.id, on_seen=WatchAction.RESTART)
        # reactive mode never counts a cycle as a restart, so only the rule's restart can wake the group
        macro = loop_macro(group, [restarting])
        macro.mode = RunMode.REACTIVE
        r.start(macro)
        time.sleep(2.5)
        r.stop()
        assert (len(rule_clicks(inp)) >= 3) is expected_many
