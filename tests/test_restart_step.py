# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
from conftest import FakeInput, FakeScreen, wait_until, with_pattern
from ultrebo.model import Macro, RunMode, Step, StepType, WatchAction
from ultrebo.runner import Runner


def make_runner(templates_dir, frame_fn):
    inp = FakeInput()
    errors = []
    r = Runner(inp, FakeScreen(frame_fn), None, templates_dir, on_status=lambda s: None, on_error=errors.append)
    return r, inp, errors


def image_step(restart, priority=10, **kw):
    return Step(type=StepType.IMAGE, template_file="button.png", priority=priority, delay_after_ms=5, timeout_ms=300,
                on_seen=WatchAction.RESTART if restart else WatchAction.CONTINUE, **kw)


def click_step(x, y, priority):
    return Step(type=StepType.CLICK, x=x, y=y, priority=priority, delay_after_ms=5, hold_ms=1)


def finished(r):
    return wait_until(lambda: not r.running, timeout=6)


def test_without_the_option_the_macro_carries_on_to_the_next_step(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp, _ = make_runner(templates_dir, lambda: frame)
    r.start(Macro(loops=1, steps=[image_step(False), click_step(5, 5, 20)]))
    assert finished(r)
    assert [(x, y) for _, x, y in inp.clicks()][-1] == (5, 5)


def test_a_found_step_set_to_start_over_goes_back_to_the_first_step(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)  # the image never goes away, so the macro keeps starting over
    r, inp, errors = make_runner(templates_dir, lambda: frame)
    r.start(Macro(loops=0, steps=[image_step(True), click_step(5, 5, 20)]))
    assert wait_until(lambda: len(inp.clicks()) >= 4)
    r.stop()
    assert not errors
    assert all((x, y) != (5, 5) for _, x, y in inp.clicks())  # the step after it never gets its turn


def test_starting_over_does_not_use_up_a_loop(templates_dir, blank, pattern):
    state = {"frame": with_pattern(blank, pattern)}
    r, inp, _ = make_runner(templates_dir, lambda: state["frame"])
    r.start(Macro(loops=1, loop_delay_ms=5, steps=[image_step(True), click_step(5, 5, 20)]))
    assert wait_until(lambda: len(inp.clicks()) >= 2)
    state["frame"] = blank  # the image goes away: the step is skipped and the loop can finish
    assert finished(r)
    clicks = [(x, y) for _, x, y in inp.clicks()]
    assert clicks[-1] == (5, 5) and clicks.count((5, 5)) == 1 and len(clicks) >= 3


def test_a_wait_only_step_can_start_over_too(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp, _ = make_runner(templates_dir, lambda: frame)
    r.start(Macro(loops=0, steps=[image_step(True, click_on_found=False), click_step(5, 5, 20)]))
    assert wait_until(lambda: r.running)
    import time
    time.sleep(0.4)
    r.stop()
    assert inp.clicks() == []  # it found the image, did not click it, and started over without running the click step


def test_in_reactive_mode_the_option_changes_nothing(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp, _ = make_runner(templates_dir, lambda: frame)
    r.start(Macro(mode=RunMode.REACTIVE, loops=2, scan_interval_ms=100, steps=[image_step(True), click_step(5, 5, 20)]))
    assert finished(r)
    assert len(inp.clicks()) == 2


def test_the_summary_says_so():
    step = Step(type=StepType.IMAGE, template_file="a.png", on_seen=WatchAction.RESTART)
    assert "start the macro over" in step.summary()
    assert "start the macro over" not in Step(type=StepType.IMAGE, template_file="a.png").summary()
    rule = Step(type=StepType.IMAGE, template_file="a.png", on_seen=WatchAction.RESTART, watch=True)
    assert "start the macro over" not in rule.summary()  # rules have their own wording in the Rules list


def test_the_option_survives_saving(templates_dir):
    step = Step(type=StepType.TEXT, text="Go", on_seen=WatchAction.RESTART)
    assert Step.from_dict(step.to_dict()).on_seen is WatchAction.RESTART
