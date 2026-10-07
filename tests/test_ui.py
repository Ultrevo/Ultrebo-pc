# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from conftest import FakeInput, FakeScreen
from ultrebo.app import build_window
from ultrebo.model import Macro, RunMode, Step, StepType, WatchAction
from ultrebo.store import MacroStore
from ultrebo.ui.picker import PickerOverlay
from ultrebo.ui.step_dialog import StepDialog
from ultrebo.ui.theme import apply_theme


@pytest.fixture(scope="session", autouse=True)
def _theme(qapp):
    apply_theme(qapp)


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


def dialog_for(window, step, rule=False):
    return StepDialog(window.ctx, step, window, is_new=True, rule=rule)


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


def test_text_rule(window):
    d = dialog_for(window, Step(type=StepType.TEXT), rule=True)
    d.t_text.setText("I'm here")
    d.t_threshold.setValue(0.75)
    d.on_seen.setCurrentIndex(d.on_seen.findData(WatchAction.RESTART.value))
    d.click_found.setChecked(False)
    d._accept()
    s = d.result_step()
    assert (s.text, s.threshold, s.watch, s.click_on_found, s.priority) == ("I'm here", 0.75, True, False, 0)
    assert not hasattr(d, "priority")  # order in the list is the priority; there is no number to type
    assert s.on_seen is WatchAction.RESTART and s.on_seen.label  # a real enum, not a string


def test_plain_steps_never_watch_and_rules_only_offer_image_and_text(window):
    d = dialog_for(window, Step(type=StepType.TEXT))
    d.t_text.setText("hi")
    d._accept()
    assert d.result_step().watch is False
    assert d.watch_group.isHidden()

    rule = dialog_for(window, Step(type=StepType.CLICK), rule=True)  # a non image/text step opens as image
    shown = [k for k, b in rule._kind_buttons.items() if not b.isHidden()]
    assert shown == [StepType.IMAGE, StepType.TEXT]
    assert rule.windowTitle() == "New rule"


def test_rules_tab_add_order_and_delete(window, monkeypatch):
    window.new_macro()
    macro = window._macro()
    tab = window.rules_tab

    def add(text):
        # the dialog is not shown in tests: fill it in the way the user would, via exec's replacement
        original = StepDialog.exec

        def fill(self):
            self.t_text.setText(text)
            self._accept()
            return StepDialog.DialogCode.Accepted

        monkeypatch.setattr(StepDialog, "exec", fill)
        tab.add_rule(StepType.TEXT)
        monkeypatch.setattr(StepDialog, "exec", original)

    add("first")
    add("second")
    assert [r.text for r in macro.ordered_rules()] == ["first", "second"]
    assert all(r.watch for r in macro.rules) and macro.steps == []
    assert tab.table.rowCount() == 2

    tab.table.selectRow(1)
    tab.move_rule(-1)
    assert [r.text for r in macro.ordered_rules()] == ["second", "first"]
    assert tab.table.item(0, 2).text() == "Find text"  # titles are listed in priority order
    assert "second" in tab.table.item(0, 4).text()

    tab.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert macro.ordered_rules()[0].enabled is False
    tab.table.selectRow(0)
    tab.delete_rule()
    assert [r.text for r in macro.rules] == ["first"]
    assert window.store.macros[0].rules[0].text == "first"  # saved


def test_duplicate_macro_copies_rule_images(window, frame):
    window.new_macro()
    macro = window._macro()
    name = window.ctx.save_template(frame, 10, 10, 50, 40)
    macro.rules.append(Step(type=StepType.IMAGE, template_file=name, watch=True))
    window.duplicate_macro()
    copy_ = window._macro()
    assert copy_.id != macro.id and len(copy_.rules) == 1
    assert copy_.rules[0].template_file != name and window.store.template_path(copy_.rules[0].template_file).exists()
    assert copy_.rules[0].id != macro.rules[0].id


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


def test_rules_can_be_exported_and_imported_between_macros(window, frame, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    window.new_macro()
    source = window._macro()
    name = window.ctx.save_template(frame, 10, 10, 50, 40)
    source.rules = [
        Step(type=StepType.IMAGE, template_file=name, watch=True, priority=10, name="Claim"),
        Step(type=StepType.TEXT, text="I'm here", watch=True, priority=20),
    ]
    window.rules_tab.refresh()
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: messages.append(a[2]))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: messages.append(a[2]))
    target = str(tmp_path / "shared")  # no extension typed: it is added
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (target, ""))
    window.rules_tab.export_rules()
    assert (tmp_path / "shared.ultrebo-rules").exists() and "Saved 2 rules" in messages[-1]

    window.new_macro()
    dest = window._macro()
    assert dest.id != source.id and dest.rules == []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (target + ".ultrebo-rules", ""))
    window.rules_tab.import_rules()
    assert [r.name or r.text for r in dest.ordered_rules()] == ["Claim", "I'm here"]
    assert dest.rules[0].template_file != name and window.store.template_path(dest.rules[0].template_file).exists()
    assert window.rules_tab.table.rowCount() == 2 and "Added 2 rules" in messages[-1]

    bad = tmp_path / "bad.ultrebo-rules"
    bad.write_bytes(b"nope")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bad), ""))
    window.rules_tab.import_rules()
    assert "isn't a rule pack" in messages[-1] and len(dest.rules) == 2


def test_exporting_with_no_rules_explains_why(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    window.new_macro()
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: messages.append(a[2]))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "x"), ""))
    window.rules_tab.export_rules()
    assert "no rules" in messages[-1] and not (tmp_path / "x.ultrebo-rules").exists()


def test_update_now_downloads_installs_and_closes(window, monkeypatch, qapp):
    from ultrebo import selfupdate
    from ultrebo.updater import Update

    quits, applied = [], []
    prepared = object()

    def fake_prepare(update, progress, cancelled):
        progress(50, 100)
        progress(100, 100)
        return prepared

    monkeypatch.setattr(selfupdate, "prepare", fake_prepare)
    monkeypatch.setattr(selfupdate, "apply", lambda p: applied.append(p))
    monkeypatch.setattr(window, "_quit_for_update", lambda: quits.append(True))
    window._start_self_update(Update("0.2.0", "https://github.com/Ultrevo/Ultrebo-pc/releases/tag/v0.2.0"))
    from conftest import wait_until

    assert wait_until(lambda: (qapp.processEvents() or True) and quits, timeout=5)
    assert applied == [prepared]


def test_a_failed_update_offers_the_release_page(window, monkeypatch, qapp):
    from ultrebo import selfupdate
    from ultrebo.updater import Update

    shown = []
    monkeypatch.setattr(selfupdate, "prepare", lambda *a: (_ for _ in ()).throw(selfupdate.UpdateError("checksum mismatch")))
    monkeypatch.setattr(window, "_update_failed", lambda update, message: shown.append(message))
    window._start_self_update(Update("0.2.0", "https://github.com/x"))
    from conftest import wait_until

    assert wait_until(lambda: (qapp.processEvents() or True) and shown, timeout=5)
    assert shown == ["checksum mismatch"]


def test_update_is_refused_while_a_macro_runs(window, monkeypatch):
    from ultrebo import selfupdate
    from ultrebo.updater import Update

    messages = []
    window._running = True
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: messages.append(a[2]))
    monkeypatch.setattr(selfupdate, "prepare", lambda *a: pytest.fail("must not start"))
    window._start_self_update(Update("0.2.0", "u"))
    assert "Stop the macro first" in messages[-1]


def test_about_check_for_updates_tells_you_what_happened(window, monkeypatch):
    from ultrebo import updater as upd

    seen = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: seen.append(("warn", a[2])))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: seen.append(("info", a[2])))
    shown = []
    monkeypatch.setattr(window, "_on_update", lambda update: shown.append(update.version))

    window._on_update_result(upd.CheckResult(None, error="SSLError: certificate verify failed"))
    assert seen[-1][0] == "warn" and "certificate verify failed" in seen[-1][1]
    window._on_update_result(upd.CheckResult(None, latest="0.1.0"))
    assert seen[-1][0] == "info" and "latest version" in seen[-1][1]
    window._on_update_result(upd.CheckResult(upd.Update("0.9.0", "https://github.com/x"), "0.9.0"))
    assert shown == ["0.9.0"]


def test_finder_dialogs_remember_the_discord_option(window):
    for rule in (False, True):
        d = dialog_for(window, Step(type=StepType.TEXT), rule=rule)
        assert not d.notify.isChecked()
        d.t_text.setText("Victory")
        d.notify.setChecked(True)
        d._accept()
        assert d.result_step().notify is True
        again = dialog_for(window, d.result_step(), rule=rule)
        assert again.notify.isChecked()
        for dialog in (d, again):
            dialog.deleteLater()


def test_a_save_that_fails_tells_the_user_instead_of_quietly_losing_the_edit(window, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: shown.append(a[2]))
    window.new_macro()
    monkeypatch.setattr("ultrebo.store.os.replace", lambda a, b: (_ for _ in ()).throw(PermissionError("locked")))
    monkeypatch.setattr("ultrebo.store.time.sleep", lambda s: None)
    window._macro().name = "Renamed"
    window.store.save()
    assert shown and "couldn't save your macros" in shown[0] and "locked" in shown[0]


def test_a_finder_step_remembers_the_start_over_option_but_a_rule_does_not_show_it(window):
    d = dialog_for(window, Step(type=StepType.TEXT))
    assert not d.restart_after.isChecked()
    d.t_text.setText("Victory")
    d.restart_after.setChecked(True)
    d._accept()
    assert d.result_step().on_seen is WatchAction.RESTART
    again = dialog_for(window, d.result_step())
    assert again.restart_after.isChecked()
    rule = dialog_for(window, Step(type=StepType.TEXT), rule=True)
    assert rule.restart_after.isHidden()
    for dialog in (d, again, rule):
        dialog.deleteLater()


# ------------------------------------------------------------------ picking on screen from inside a dialog
# Hiding a dialog ends its exec(), which used to throw away the step after "Pick image from screen" (or any other pick).

_pickers: list = []


class _FakePicker(QObject):
    """Stands in for the full-screen picker: after a moment it reports a pick (or a cancel)."""

    box_picked = Signal(int, int, int, int)
    point_picked = Signal(int, int)
    cancelled = Signal()
    outcome = "box"

    def __init__(self, frame, mode, hint=""):
        super().__init__()
        _pickers.append(self)

    def showFullScreen(self):
        QTimer.singleShot(80, self._report)

    def _report(self):
        {
            "box": lambda: self.box_picked.emit(10, 10, 40, 30),
            "point": lambda: self.point_picked.emit(25, 35),
            "cancel": lambda: self.cancelled.emit(),
        }[type(self).outcome]()

    def activateWindow(self): pass
    def raise_(self): pass
    def setScreen(self, s): pass
    def setGeometry(self, g): pass


@pytest.fixture(autouse=True)
def _delete_pickers(qapp):
    """Qt objects left for the garbage collector can crash the test run at exit, so delete them as each test ends."""
    yield
    for obj in _pickers:
        obj.deleteLater()
    _pickers.clear()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _delete_dialogs(window):
    for dialog in window.findChildren(StepDialog):
        dialog.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _run_with_user(window, monkeypatch, step, outcome, do_pick, rule=False, is_new=True):
    """Open the real dialog, let `do_pick(dialog)` press a pick button, then press Save. Returns (dialog, result of exec)."""
    from PySide6.QtCore import QTimer

    from ultrebo.ui import context as context_module

    _FakePicker.outcome = outcome
    monkeypatch.setattr(context_module, "PickerOverlay", _FakePicker)
    dialog = StepDialog(window.ctx, step, window, is_new=is_new, rule=rule)
    QTimer.singleShot(50, lambda: do_pick(dialog))
    QTimer.singleShot(900, dialog._accept)  # "the user presses Save" once the picker is gone
    QTimer.singleShot(4000, dialog.reject)  # never hang a test run
    return dialog, dialog.exec()


def test_picking_an_image_and_then_saving_adds_the_step(window, monkeypatch):
    window.new_macro()
    from PySide6.QtCore import QTimer

    from ultrebo.ui import context as context_module

    _FakePicker.outcome = "box"
    monkeypatch.setattr(context_module, "PickerOverlay", _FakePicker)
    original_init = StepDialog.__init__

    def init(self, *a, **k):
        original_init(self, *a, **k)
        QTimer.singleShot(50, self.pick_image.click)
        QTimer.singleShot(900, self._accept)
        QTimer.singleShot(4000, self.reject)

    monkeypatch.setattr(StepDialog, "__init__", init)
    window.add_step(StepType.IMAGE)
    steps = window._macro().steps
    assert len(steps) == 1 and steps[0].template_file and window.table.rowCount() == 1
    assert window.store.template_path(steps[0].template_file).exists()
    _delete_dialogs(window)


def test_picking_a_position_while_editing_keeps_the_edit(window, monkeypatch):
    window.new_macro()
    step = Step(type=StepType.CLICK, x=1, y=2)
    window._macro().steps.append(step)
    window.store.save()
    window._load_editor()
    window._fill_table(select_id=step.id)
    from PySide6.QtCore import QTimer

    from ultrebo.ui import context as context_module

    _FakePicker.outcome = "point"
    monkeypatch.setattr(context_module, "PickerOverlay", _FakePicker)
    original_init = StepDialog.__init__

    def init(self, *a, **k):
        original_init(self, *a, **k)
        QTimer.singleShot(50, lambda: self._pick_point(self.c_x, self.c_y))
        QTimer.singleShot(900, lambda: (self.name.setText("Moved"), self._accept()))
        QTimer.singleShot(4000, self.reject)

    monkeypatch.setattr(StepDialog, "__init__", init)
    window.edit_step()
    saved = window._macro().steps[0]
    assert (saved.x, saved.y) == (25, 35) and saved.name == "Moved"
    reloaded = MacroStore(window.store.folder).macros[0].steps[0]
    assert (reloaded.x, reloaded.y, reloaded.name) == (25, 35, "Moved")
    _delete_dialogs(window)


def test_cancelling_a_pick_brings_the_dialog_back_ready_to_save(window, monkeypatch):
    dialog, result = _run_with_user(
        window, monkeypatch, Step(type=StepType.TEXT, text="Go"), "cancel", lambda d: d._pick_region(),
    )
    assert result == StepDialog.DialogCode.Accepted and dialog.isVisible() is False
    assert dialog.picking is False
    dialog.deleteLater()


def test_a_dialog_that_is_not_picking_behaves_as_before(window):
    from PySide6.QtCore import QTimer

    d = StepDialog(window.ctx, Step(type=StepType.CLICK), window, is_new=True)
    QTimer.singleShot(50, d.reject)
    assert d.exec() == StepDialog.DialogCode.Rejected
    d.deleteLater()


# ------------------------------------------------------------------ several steps at once, and "Move to #"

def _steps_window(window, n=5):
    window.new_macro()
    macro = window._macro()
    macro.steps = [Step(type=StepType.CLICK, x=i, y=i, name=f"S{i}", priority=(i + 1) * 10) for i in range(n)]
    window.store.save()
    window._load_editor()
    return macro


def _select_rows(window, *rows):
    from PySide6.QtCore import QItemSelectionModel

    window.table.clearSelection()
    for row in rows:
        window.table.selectionModel().select(
            window.table.model().index(row, 0), QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )


def _names(window):
    return [s.name for s in window._macro().ordered()]


def test_the_table_lets_you_select_several_steps(window):
    from PySide6.QtWidgets import QAbstractItemView

    _steps_window(window)
    assert window.table.selectionMode() is QAbstractItemView.SelectionMode.ExtendedSelection
    _select_rows(window, 1, 2, 3)
    assert [s.name for s in window._selected_steps()] == ["S1", "S2", "S3"]


def test_deleting_several_steps_asks_once_and_removes_them_all(window, monkeypatch):
    _steps_window(window)
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.Yes)
    _select_rows(window, 1, 2, 3)
    window.delete_step()
    assert _names(window) == ["S0", "S4"] and len(asked) == 1 and "3 steps" in asked[0]
    assert MacroStore(window.store.folder).macros[0].steps and len(MacroStore(window.store.folder).macros[0].steps) == 2


def test_deleting_several_steps_can_be_cancelled(window, monkeypatch):
    _steps_window(window)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    _select_rows(window, 0, 1)
    window.delete_step()
    assert len(_names(window)) == 5


def test_deleting_one_step_does_not_ask(window, monkeypatch):
    _steps_window(window)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not ask")))
    _select_rows(window, 2)
    window.delete_step()
    assert _names(window) == ["S0", "S1", "S3", "S4"]


def test_duplicating_several_steps_puts_the_copies_after_the_last_one_in_order(window):
    _steps_window(window, 4)
    _select_rows(window, 1, 2)
    window.duplicate_step()
    assert _names(window) == ["S0", "S1", "S2", "S1", "S2", "S3"]
    assert len({s.id for s in window._macro().steps}) == 6
    assert [s.name for s in window._selected_steps()] == ["S1", "S2"]  # the copies are the ones left selected
    assert window._selected_step_ids() == [s.id for s in window._macro().ordered()[3:5]]


def test_move_to_number_puts_a_step_at_that_position(window):
    _steps_window(window)
    _select_rows(window, 3)
    assert window.move_to.value() == 4  # the box shows where the selected step is now
    window.move_to.setValue(2)
    window.move_selected_to_number()
    assert _names(window) == ["S0", "S3", "S1", "S2", "S4"]
    assert [s.name for s in window._selected_steps()] == ["S3"]
    window.move_to.setValue(1)
    window.move_selected_to_number()
    assert _names(window)[0] == "S3"
    window.move_to.setValue(5)
    window.move_selected_to_number()
    assert _names(window)[-1] == "S3"
    assert [s.priority for s in window._macro().ordered()] == [10, 20, 30, 40, 50]  # a real, saved order


def test_move_to_number_moves_a_whole_selection_together(window):
    _steps_window(window)
    _select_rows(window, 1, 2)
    window.move_to.setValue(4)
    window.move_selected_to_number()
    assert _names(window) == ["S0", "S3", "S4", "S1", "S2"]  # kept in their order, first one at the top of the block


def test_a_number_past_the_end_just_means_the_end(window):
    _steps_window(window)
    _select_rows(window, 0)
    window.move_selected_to(99)
    assert _names(window) == ["S1", "S2", "S3", "S4", "S0"]
    assert window.move_to.maximum() == 5


def test_the_old_up_and_down_buttons_are_gone_and_the_number_box_is_there(window):
    from PySide6.QtWidgets import QPushButton

    _steps_window(window)
    labels = {b.text() for b in window.tabs.widget(0).findChildren(QPushButton)}  # the Steps tab (Rules keeps its own Up/Down)
    assert "Up" not in labels and "Down" not in labels and "Move" in labels


def test_editing_or_testing_with_several_selected_does_nothing(window, monkeypatch):
    _steps_window(window)
    monkeypatch.setattr(StepDialog, "exec", lambda self: (_ for _ in ()).throw(AssertionError("should not open")))
    _select_rows(window, 0, 1)
    window.edit_step()
    window.test_step()
    assert "just one" in window.status_label.text()
