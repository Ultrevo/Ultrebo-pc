# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import threading
import time

import pytest

from conftest import FakeInput, FakeOcr, FakeScreen, wait_until, with_pattern
from ultrebo import runner as runner_module
from ultrebo.model import Macro, RunMode, Step, StepType, WatchAction
from ultrebo.runner import Runner
from ultrebo.textmatch import OcrWord


def click_step(x, y, priority=0, delay=10, **kw):
    return Step(type=StepType.CLICK, x=x, y=y, priority=priority, delay_after_ms=delay, hold_ms=1, **kw)


def make_runner(templates_dir, frame_fn=None, ocr=None, input_backend=None):
    inp = input_backend or FakeInput()
    screen = FakeScreen(frame_fn) if frame_fn else None
    states, errors, statuses = [], [], []
    r = Runner(inp, screen, ocr, templates_dir, on_status=statuses.append, on_state=states.append, on_error=errors.append)
    return r, inp, states, errors


def finished(r):
    return wait_until(lambda: not r.running, timeout=6)


@pytest.fixture(autouse=True)
def short_cooldown(monkeypatch):
    monkeypatch.setattr(runner_module, "WATCH_COOLDOWN_S", 0.4)


def test_sequence_runs_in_priority_order(tmp_path):
    r, inp, states, errors = make_runner(tmp_path)
    macro = Macro(loops=1, steps=[click_step(3, 3, 30), click_step(1, 1, 10), click_step(2, 2, 20)])
    assert r.start(macro) is None
    assert finished(r) and not errors
    assert [(x, y) for _, x, y in inp.clicks()] == [(1, 1), (2, 2), (3, 3)]
    assert states[0] is True and states[-1] is False


def test_loops_repeat_and_disabled_steps_are_skipped(tmp_path):
    r, inp, *_ = make_runner(tmp_path)
    off = click_step(9, 9, 5)
    off.enabled = False
    macro = Macro(loops=3, loop_delay_ms=5, steps=[off, click_step(1, 1, 10, repeat=2)])
    r.start(macro)
    assert finished(r)
    assert len(inp.clicks()) == 6 and all((x, y) == (1, 1) for _, x, y in inp.clicks())


def test_every_action_type_is_performed(tmp_path):
    r, inp, *_ = make_runner(tmp_path)
    macro = Macro(loops=1, steps=[
        click_step(1, 2, 10, button="right", clicks=2),
        Step(type=StepType.DRAG, x=1, y=2, x2=3, y2=4, priority=20, delay_after_ms=5),
        Step(type=StepType.SCROLL, scroll_dy=-3, priority=30, delay_after_ms=5),
        Step(type=StepType.KEY, keys="ctrl+c", priority=40, delay_after_ms=5),
    ])
    r.start(macro)
    assert finished(r)
    assert inp.names() == [("click", 1, 2, "right", 2), ("drag", 1, 2, 3, 4), ("scroll", 0, -3), ("keys", "ctrl+c")]


def test_stop_ends_an_endless_macro_quickly(tmp_path):
    r, inp, *_ = make_runner(tmp_path)
    r.start(Macro(loops=0, steps=[click_step(1, 1, 10, delay=5)]))
    assert wait_until(lambda: len(inp.clicks()) >= 3)
    t0 = time.monotonic()
    r.stop()
    assert time.monotonic() - t0 < 2 and not r.running
    n = len(inp.clicks())
    time.sleep(0.15)
    assert len(inp.clicks()) == n


def test_validation_messages(tmp_path, templates_dir):
    r, *_ = make_runner(tmp_path)
    assert "no enabled steps" in r.start(Macro())
    assert "no image" in r.start(Macro(steps=[Step(type=StepType.IMAGE, name="Btn")]))
    assert "no text" in r.start(Macro(steps=[Step(type=StepType.TEXT)]))
    assert "Screen capture" in r.start(Macro(steps=[Step(type=StepType.TEXT, text="hi")]))


def test_find_image_clicks_where_it_is(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern, x=200, y=120)
    r, inp, *_ = make_runner(templates_dir, lambda: frame)
    step = Step(type=StepType.IMAGE, template_file="button.png", priority=10, delay_after_ms=5, timeout_ms=1000)
    r.start(Macro(loops=1, scan_interval_ms=100, steps=[step]))
    assert finished(r)
    [(_, x, y)] = inp.clicks()
    assert abs(x - 230) <= 2 and abs(y - 140) <= 2


def test_find_image_skips_when_not_found(templates_dir, blank):
    r, inp, *_ = make_runner(templates_dir, lambda: blank)
    steps = [
        Step(type=StepType.IMAGE, template_file="button.png", priority=10, timeout_ms=250),
        click_step(5, 5, 20),
    ]
    r.start(Macro(loops=1, scan_interval_ms=100, steps=steps))
    assert finished(r)
    assert [(x, y) for _, x, y in inp.clicks()] == [(5, 5)]  # image step skipped, the next step still ran


def test_wait_only_image_step_does_not_click(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp, *_ = make_runner(templates_dir, lambda: frame)
    step = Step(type=StepType.IMAGE, template_file="button.png", click_on_found=False, priority=10, delay_after_ms=5)
    r.start(Macro(loops=1, steps=[step, click_step(1, 1, 20)]))
    assert finished(r)
    assert [(x, y) for _, x, y in inp.clicks()] == [(1, 1)]


def test_find_text_clicks_the_words(tmp_path, blank):
    ocr = FakeOcr([[OcrWord("Press", 10, 10, 60, 30), OcrWord("here", 70, 10, 120, 30)]])
    r, inp, *_ = make_runner(tmp_path, lambda: blank, ocr=ocr)
    r.start(Macro(loops=1, steps=[Step(type=StepType.TEXT, text="press HERE", priority=10, delay_after_ms=5, timeout_ms=500)]))
    assert finished(r)
    [(_, x, y)] = inp.clicks()
    assert (x, y) == (65, 20)


def test_search_region_limits_where_it_looks(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern, x=200, y=120)
    step = Step(type=StepType.IMAGE, template_file="button.png", priority=10, delay_after_ms=5, timeout_ms=200,
                region=[0, 0, 150, 300])  # does not include the pattern
    r, inp, *_ = make_runner(templates_dir, lambda: frame)
    r.start(Macro(loops=1, scan_interval_ms=100, steps=[step]))
    assert finished(r) and inp.clicks() == []

    step2 = Step(type=StepType.IMAGE, template_file="button.png", priority=10, delay_after_ms=5, timeout_ms=500,
                 region=[150, 80, 200, 150])
    r2, inp2, *_ = make_runner(templates_dir, lambda: frame)
    r2.start(Macro(loops=1, scan_interval_ms=100, steps=[step2]))
    assert finished(r2)
    [(_, x, y)] = inp2.clicks()
    assert abs(x - 230) <= 2 and abs(y - 140) <= 2  # coordinates are still full-screen


def test_reactive_mode_prefers_the_higher_priority_target(templates_dir, blank, pattern):
    state = {"frame": blank}
    r, inp, *_ = make_runner(templates_dir, lambda: state["frame"])
    steps = [
        Step(type=StepType.IMAGE, template_file="button.png", priority=10, delay_after_ms=20),
        click_step(7, 7, 20, delay=20),  # fallback: always met, lowest priority
    ]
    r.start(Macro(mode=RunMode.REACTIVE, loops=0, scan_interval_ms=100, steps=steps))
    assert wait_until(lambda: any((x, y) == (7, 7) for _, x, y in inp.clicks()))
    state["frame"] = with_pattern(blank, pattern)
    assert wait_until(lambda: any(abs(x - 230) <= 2 for _, x, y in inp.clicks()))
    r.stop()
    first_hit = next(i for i, (_, x, y) in enumerate(inp.clicks()) if abs(x - 230) <= 2)
    # once the image is visible the fallback no longer runs
    assert all((x, y) != (7, 7) for _, x, y in inp.clicks()[first_hit:])


def test_reactive_wait_only_step_holds_back_lower_steps(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp, *_ = make_runner(templates_dir, lambda: frame)
    steps = [
        Step(type=StepType.IMAGE, template_file="button.png", click_on_found=False, priority=10, delay_after_ms=20),
        click_step(7, 7, 20),
    ]
    r.start(Macro(mode=RunMode.REACTIVE, scan_interval_ms=100, steps=steps))
    time.sleep(0.5)
    r.stop()
    assert inp.clicks() == []


def watcher_macro(action, delay_ms, main_steps, **kw):
    watcher = Step(type=StepType.IMAGE, template_file="button.png", watch=True, on_seen=action,
                   delay_after_ms=delay_ms, priority=5, name="Watch")
    return Macro(loops=0, loop_delay_ms=10, scan_interval_ms=100, steps=[watcher] + main_steps, **kw)


def test_watcher_pauses_the_macro_then_it_carries_on(templates_dir, blank, pattern):
    state = {"frame": blank}
    r, inp, *_ = make_runner(templates_dir, lambda: state["frame"])
    macro = watcher_macro(WatchAction.CONTINUE, 400, [click_step(1, 1, 10, delay=30)])
    r.start(macro)
    assert wait_until(lambda: len(inp.clicks()) >= 3)  # main macro is busy clicking

    state["frame"] = with_pattern(blank, pattern)
    assert wait_until(lambda: any(abs(x - 230) <= 2 for _, x, y in inp.clicks()))
    watcher_time = next(t for t, x, y in inp.clicks() if abs(x - 230) <= 2)
    state["frame"] = blank  # the pop-up goes away
    assert wait_until(lambda: any(t > watcher_time + 0.3 and (x, y) == (1, 1) for t, x, y in inp.clicks()), timeout=4)
    r.stop()

    main_times = [t for t, x, y in inp.clicks() if (x, y) == (1, 1)]
    around = [t for t in main_times if watcher_time + 0.01 < t < watcher_time + 0.38]
    assert around == []  # paused for (most of) the 400 ms wait
    assert any(t > watcher_time + 0.38 for t in main_times)  # and carried on afterwards


def test_watcher_restart_begins_again_from_the_first_step(templates_dir, blank, pattern):
    state = {"frame": blank}
    r, inp, *_ = make_runner(templates_dir, lambda: state["frame"])
    main = [click_step(1, 1, 10, delay=40), click_step(2, 2, 20, delay=40), click_step(3, 3, 30, delay=300)]
    r.start(watcher_macro(WatchAction.RESTART, 50, main))
    assert wait_until(lambda: (3, 3) in [(x, y) for _, x, y in inp.clicks()])  # one full pass

    # show the pop-up right after step 1 of the next pass so the cut-off is visible
    seen = len(inp.clicks())
    assert wait_until(lambda: len(inp.clicks()) > seen)
    state["frame"] = with_pattern(blank, pattern)
    assert wait_until(lambda: any(abs(x - 230) <= 2 for _, x, y in inp.clicks()))
    state["frame"] = blank
    idx = next(i for i, (_, x, y) in enumerate(inp.clicks()) if abs(x - 230) <= 2)
    assert wait_until(lambda: len(inp.clicks()) > idx + 2)
    r.stop()

    after = [(x, y) for _, x, y in inp.clicks()[idx + 1:]]
    assert after[0] == (1, 1)  # restarted from step 1


def test_watcher_without_clicking_only_waits(templates_dir, blank, pattern):
    frame = with_pattern(blank, pattern)
    r, inp, *_ = make_runner(templates_dir, lambda: frame)
    macro = watcher_macro(WatchAction.CONTINUE, 50, [click_step(1, 1, 10, delay=30)])
    macro.steps[0].click_on_found = False
    r.start(macro)
    assert wait_until(lambda: len(inp.clicks()) >= 3)
    r.stop()
    assert all((x, y) == (1, 1) for _, x, y in inp.clicks())


def test_watchers_only_macro_keeps_running_until_stopped(templates_dir, blank):
    r, inp, *_ = make_runner(templates_dir, lambda: blank)
    macro = watcher_macro(WatchAction.CONTINUE, 50, [])
    r.start(macro)
    time.sleep(0.4)
    assert r.running
    r.stop()
    assert not r.running


def test_test_step_runs_once_and_reports_state(tmp_path):
    r, inp, states, errors = make_runner(tmp_path)
    assert r.test_step(click_step(4, 4)) is None
    assert finished(r)
    assert [(x, y) for _, x, y in inp.clicks()] == [(4, 4)]
    assert states[-1] is False


def test_errors_from_input_are_reported_and_stop_the_run(tmp_path):
    class Boom(FakeInput):
        def click(self, *a, **k):
            raise RuntimeError("no permission")

    r, inp, states, errors = make_runner(tmp_path, input_backend=Boom())
    r.start(Macro(loops=0, steps=[click_step(1, 1, 10)]))
    assert finished(r)
    assert errors and "no permission" in errors[0]


def test_retina_scaling_is_applied(templates_dir, blank, pattern):
    # Screenshot pixels are twice the mouse coordinates (a Retina Mac).
    big = __import__("cv2").resize(with_pattern(blank, pattern, 200, 120), None, fx=2, fy=2, interpolation=__import__("cv2").INTER_NEAREST)
    import cv2
    cv2.imwrite(str(templates_dir / "big.png"), cv2.resize(pattern, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    screen = FakeScreen(lambda: big, scale=2.0)
    inp = FakeInput()
    r = Runner(inp, screen, None, templates_dir)
    step = Step(type=StepType.IMAGE, template_file="big.png", priority=10, delay_after_ms=5, timeout_ms=500)
    r.start(Macro(loops=1, scan_interval_ms=100, steps=[step]))
    assert finished(r)
    [(_, x, y)] = inp.clicks()
    assert abs(x - 230) <= 3 and abs(y - 140) <= 3  # in mouse units, not screenshot pixels
