# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import json

from ultrebo.model import Macro, RunMode, Step, StepType, WatchAction
from ultrebo.store import MacroStore
from ultrebo.versions import is_newer


def test_ordered_sorts_by_priority_then_list_position():
    macro = Macro(steps=[Step(name="c", priority=30), Step(name="a", priority=10),
                         Step(name="b1", priority=20), Step(name="b2", priority=20)])
    assert [s.name for s in macro.ordered()] == ["a", "b1", "b2", "c"]


def test_next_priority_and_renumber():
    assert Macro().next_priority() == 10
    macro = Macro(steps=[Step(name="a", priority=30), Step(name="b", priority=5)])
    assert macro.next_priority() == 40
    macro.renumber([macro.steps[1], macro.steps[0]])
    assert [(s.name, s.priority) for s in macro.steps] == [("b", 10), ("a", 20)]


def test_macro_survives_json_round_trip():
    macro = Macro(
        name="Farm", mode=RunMode.REACTIVE, loops=3, scan_interval_ms=2500,
        steps=[
            Step(type=StepType.IMAGE, template_file="x.png", threshold=0.9, watch=True,
                 on_seen=WatchAction.RESTART, region=[1, 2, 30, 40]),
            Step(type=StepType.KEY, keys="ctrl+shift+s"),
            Step(type=StepType.DRAG, x=1, y=2, x2=3, y2=4),
        ],
    )
    again = Macro.from_dict(json.loads(json.dumps(macro.to_dict())))
    assert again.to_dict() == macro.to_dict()
    assert again.steps[0].on_seen is WatchAction.RESTART


def test_old_or_partial_files_still_load():
    macro = Macro.from_dict({"name": "Old", "steps": [{"type": "click", "x": 5, "y": 6, "future_field": 1}]})
    step = macro.steps[0]
    assert (step.x, step.y, step.delay_after_ms, step.threshold) == (5, 6, 500, 0.8)
    assert Macro.from_dict({"mode": "nonsense"}).mode is RunMode.SEQUENCE
    assert Step.from_dict({"type": "nonsense"}).type is StepType.CLICK


def test_summary_text():
    assert "Click left at (1, 2)" in Step(x=1, y=2).summary()
    assert Step(type=StepType.IMAGE).summary() == "no image picked"
    assert Step(type=StepType.TEXT).summary() == "no text entered"
    assert 'click "hi"' in Step(type=StepType.TEXT, text="hi").summary()


def test_store_saves_and_reloads(tmp_path):
    store = MacroStore(tmp_path)
    macro = store.add(Macro(name="One", steps=[Step(name="s", template_file="a.png")]))
    (store.templates_dir / "a.png").write_bytes(b"x")
    store.settings.active_macro_id = macro.id
    store.save_settings()

    again = MacroStore(tmp_path)
    assert [m.name for m in again.macros] == ["One"]
    assert again.settings.active_macro_id == macro.id

    again.delete(macro.id)
    assert again.macros == [] and not (again.templates_dir / "a.png").exists()
    assert again.settings.active_macro_id is None


def test_store_survives_corrupt_files(tmp_path):
    (tmp_path / "macros.json").write_text("not json")
    (tmp_path / "settings.json").write_text("{")
    store = MacroStore(tmp_path)
    assert store.macros == [] and store.settings.check_updates is True


def test_store_notifies_listeners(tmp_path):
    store = MacroStore(tmp_path)
    seen = []
    store.subscribe(lambda: seen.append(1))
    store.add(Macro())
    store.save()
    assert len(seen) >= 2


def test_version_comparison():
    assert is_newer("v0.1.1", "0.1.0") and is_newer("v0.10.0", "0.9.9")
    assert not is_newer("v1.0", "1.0.0") and not is_newer("v0.1.0", "0.1.1")
    assert not is_newer("latest", "0.1.0")
