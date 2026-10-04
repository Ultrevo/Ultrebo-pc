# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from conftest import FakeInput, FakeScreen
from ultrebo.app import build_window
from ultrebo.model import Macro, RunMode, Step, StepType, WatchAction
from ultrebo.store import MacroStore
from ultrebo.ui.picker import PickerOverlay
from ultrebo.ui.step_dialog import StepDialog
from ultrebo.ui.theme import apply_theme


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture
def frame():
    rng = np.random.default_rng(3)
    return rng.integers(0, 255, size=(400, 640, 3), dtype=np.uint8)


@pytest.fixture
def window(qapp, tmp_path, frame):
    store = MacroStore(tmp_path)
    win, bridge = build_window(store, FakeScreen(lambda: frame), FakeInput(), None, None)
    win.show()
    qapp.processEvents()
    yield win
    win.ctx.runner.stop()
    win.close()


def dialog_for(window, step):
    return StepDialog(window.ctx, step, window, is_new=True)


def test_empty_state_then_new_macro(window):
    assert window.stack.currentIndex() == 0
    window.new_macro()
    assert window.stack.currentIndex() == 1
    assert [m.name for m in window.store.macros] == ["Macro 1"]
    assert window.table.rowCount() == 0


def test_click_dialog_round_trip(window):
    d = dialog_for(window, Step(type=StepType.CLICK))
    d.name.setText("Place tower")
    d.c_x.setValue(120)
    d.c_y.setValue(340)
    d.c_double.setChecked(True)
    d.c_button.setCurrentText("right")
    d.delay.setValue(900)
    d._accept()
    s = d.result_step()
    assert (s.type, s.name, s.x, s.y, s.clicks, s.button, s.delay_after_ms) == (StepType.CLICK, "Place tower", 120, 340, 2, "right", 900)


def test_each_kind_saves_its_fields(window):
    d = dialog_for(window, Step(type=StepType.DRAG))
    d.d_x.setValue(1); d.d_y.setValue(2); d.d_x2.setValue(30); d.d_y2.setValue(40); d.d_time.setValue(450)
    d._accept()
    s = d.result_step()
    assert (s.x, s.y, s.x2, s.y2, s.hold_ms) == (1, 2, 30, 40, 450)

    d = dialog_for(window, Step(type=StepType.SCROLL))
    d.s_dy.setValue(-5); d.s_x.setValue(7); d.s_y.setValue(8)
    d._accept()
    s = d.result_step()
    assert (s.scroll_dy, s.x, s.y) == (-5, 7, 8)

    d = dialog_for(window, Step(type=StepType.KEY))
    d.k_keys.setText("Ctrl+Shift+S")
    d._accept()
    assert d.result_step().keys == "Ctrl+Shift+S"


def test_text_step_with_watcher(window):
    d = dialog_for(window, Step(type=StepType.TEXT))
    d.t_text.setText("I'm here")
    d.t_threshold.setValue(0.75)
    d.watch.setChecked(True)
    d.on_seen.setCurrentIndex(d.on_seen.findData(WatchAction.RESTART.value))
    d.click_found.setChecked(False)
    d._accept()
    s = d.result_step()
    assert (s.text, s.threshold, s.watch, s.click_on_found) == ("I'm here", 0.75, True, False)
    assert s.on_seen is WatchAction.RESTART and s.on_seen.label  # a real enum, not a string


def test_dialog_refuses_incomplete_steps(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    bad = [
        (Step(type=StepType.KEY), lambda d: d.k_keys.setText("nonsense")),
        (Step(type=StepType.TEXT), lambda d: d.t_text.setText("  ")),
        (Step(type=StepType.IMAGE), lambda d: None),
    ]
    for step, prep in bad:
        d = dialog_for(window, step)
        prep(d)
        d._accept()
        assert d.result() != d.DialogCode.Accepted
    assert len(warnings) == 3


def test_picked_image_is_saved_and_shown(window, frame):
    d = dialog_for(window, Step(type=StepType.IMAGE))
    name = window.ctx.save_template(frame, 100, 50, 80, 60)
    assert name and window.store.template_path(name).exists()
    d._template = name
    d._update_thumb()
    d.t_threshold.setValue(0.8)
    d._accept()
    assert d.result_step().template_file == name


def test_too_small_crop_is_rejected(window, frame):
    assert window.ctx.save_template(frame, 10, 10, 2, 2) is None


def test_cancelling_the_dialog_removes_an_unsaved_image(window, frame):
    d = dialog_for(window, Step(type=StepType.IMAGE))
    name = window.ctx.save_template(frame, 100, 50, 80, 60)
    d._template = name
    d.reject()
    assert not window.store.template_path(name).exists()


def test_step_management_in_the_window(window):
    window.new_macro()
    macro = window._macro()
    macro.steps = [Step(name=n, priority=p, delay_after_ms=5) for n, p in (("a", 10), ("b", 20), ("c", 30))]
    window.store.save()
    window._load_editor()
    window.table.selectRow(1)
    window.move_step(-1)
    assert [s.name for s in macro.ordered()] == ["b", "a", "c"]
    window.duplicate_step()
    assert len(macro.steps) == 4
    window.table.selectRow(0)
    window.delete_step()
    assert len(macro.steps) == 3
    # toggling the checkbox disables a step and saves
    first = window.table.item(0, 0)
    first.setCheckState(Qt.CheckState.Unchecked)
    assert sum(1 for s in macro.steps if not s.enabled) == 1
    assert MacroStore(window.store.folder).macros[0].steps  # persisted


def test_macro_settings_tab_edits_the_macro(window):
    window.new_macro()
    window.s_name.setText("Farm")
    window.s_name.textEdited.emit("Farm")
    window.s_mode.setCurrentIndex(window.s_mode.findData(RunMode.REACTIVE.value))
    window.s_loops.setValue(4)
    window.s_scan.setValue(2500)
    m = window._macro()
    assert (m.name, m.loops, m.scan_interval_ms) == ("Farm", 4, 2500)
    assert m.mode is RunMode.REACTIVE
    assert MacroStore(window.store.folder).macros[0].name == "Farm"


def test_duplicate_and_delete_macro(window, frame, monkeypatch):
    window.new_macro()
    name = window.ctx.save_template(frame, 0, 0, 50, 50)
    window._macro().steps.append(Step(type=StepType.IMAGE, template_file=name))
    window.store.save()
    window.duplicate_macro()
    assert len(window.store.macros) == 2
    clone = window._macro()
    assert clone.steps[0].template_file != name and window.store.template_path(clone.steps[0].template_file).exists()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    window.delete_macro()
    assert len(window.store.macros) == 1


def test_start_button_explains_problems(window, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    window.new_macro()
    window.toggle_run_from_button()
    assert warnings and "no enabled steps" in warnings[0]


def test_hotkey_toggle_starts_and_stops(window):
    window.new_macro()
    window._macro().steps = [Step(type=StepType.CLICK, x=5, y=5, delay_after_ms=5, hold_ms=1)]
    window.store.save()
    window.toggle_run()
    QTest.qWait(200)
    assert window.ctx.runner.running and window._running
    window.toggle_run()
    QTest.qWait(200)
    assert not window.ctx.runner.running and not window._running
    assert window.start_button.text().startswith("Start")


def test_finished_recording_adds_steps(window, monkeypatch):
    window.new_macro()
    steps = [Step(type=StepType.CLICK, x=1, y=1), Step(type=StepType.KEY, keys="a")]

    class FakeRecorder:
        recording = True

        def stop(self, first_priority=10):
            return steps

    window.recorder = FakeRecorder()
    window._finish_recording()
    assert [s.type for s in window._macro().steps] == [StepType.CLICK, StepType.KEY]
    assert window.table.rowCount() == 2


def test_overlay_box_and_point_selection(qapp, frame):
    boxes, points, cancelled = [], [], []
    overlay = PickerOverlay(frame, "box")
    overlay.resize(320, 200)  # half the screenshot size
    overlay.box_picked.connect(lambda *a: boxes.append(a))
    overlay.cancelled.connect(lambda: cancelled.append(1))
    overlay.show()
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(40, 30))
    QTest.mouseMove(overlay, QPoint(100, 80))
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(100, 80))
    assert boxes and boxes[0] == (80, 60, 120, 100)  # converted to screenshot pixels (x2)

    tap = PickerOverlay(frame, "box")
    tap.resize(320, 200)
    tap.cancelled.connect(lambda: cancelled.append(1))
    tap.show()
    QTest.mouseClick(tap, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    assert cancelled  # a tap is not a box

    pt = PickerOverlay(frame, "point")
    pt.resize(320, 200)
    pt.point_picked.connect(lambda x, y: points.append((x, y)))
    pt.show()
    QTest.mouseClick(pt, Qt.MouseButton.LeftButton, pos=QPoint(50, 25))
    assert points == [(100, 50)]
