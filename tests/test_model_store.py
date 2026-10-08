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
            Step(type=StepType.KEY, keys="ctrl+shift+s"),
            Step(type=StepType.DRAG, x=1, y=2, x2=3, y2=4),
        ],
        rules=[
            Step(type=StepType.IMAGE, template_file="x.png", threshold=0.9, watch=True,
                 on_seen=WatchAction.RESTART, region=[1, 2, 30, 40], priority=20),
            Step(type=StepType.TEXT, text="I'm here", watch=True, priority=10),
        ],
    )
    again = Macro.from_dict(json.loads(json.dumps(macro.to_dict())))
    assert again.to_dict() == macro.to_dict()
    assert again.rules[0].on_seen is WatchAction.RESTART
    assert [r.text for r in again.ordered_rules()][0] == "I'm here"  # priority 10 comes before 20


def test_old_always_watching_steps_become_rules():
    old = {
        "name": "Old",
        "steps": [
            {"type": "click", "x": 1, "y": 1, "priority": 5},
            {"type": "text", "text": "I'm here", "watch": True, "on_seen": "restart", "priority": 20},
            {"type": "image", "template_file": "a.png", "watch": True, "priority": 10},
        ],
    }
    macro = Macro.from_dict(old)
    assert [s.type for s in macro.steps] == [StepType.CLICK]
    assert [r.title() for r in macro.ordered_rules()] == ["Find image", "Find text"]
    assert all(r.watch for r in macro.rules)
    assert Macro.from_dict(macro.to_dict()).to_dict() == macro.to_dict()  # stable once migrated


def test_rule_priorities_and_summary():
    macro = Macro(rules=[Step(type=StepType.TEXT, text="a", priority=30), Step(type=StepType.TEXT, text="b", priority=5)])
    assert macro.next_rule_priority() == 40
    macro.renumber_rules(macro.ordered_rules())
    assert [(r.text, r.priority) for r in macro.rules] == [("b", 10), ("a", 20)]
    rule = Step(type=StepType.TEXT, text="I'm here", on_seen=WatchAction.RESTART)
    assert rule.rule_summary() == 'When "I\'m here" appears: click it, then ' + WatchAction.RESTART.label.lower()
    assert Step(type=StepType.IMAGE).rule_summary() == "no image picked"


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


# ------------------------------------------------------- a damaged file must never wipe out your macros

def _store_with_three(tmp_path):
    import json

    from ultrebo.model import Macro, Step, StepType
    from ultrebo.store import MacroStore

    store = MacroStore(tmp_path)
    for name in ("one", "two", "three"):
        store.add(Macro(name=name, steps=[Step(type=StepType.CLICK, x=1, y=2)]))
    return store, tmp_path / "macros.json", json.loads((tmp_path / "macros.json").read_text())


def test_one_bad_number_in_a_macro_does_not_hide_every_macro(tmp_path):
    import json

    from ultrebo.store import MacroStore

    _, path, data = _store_with_three(tmp_path)
    data[1]["loops"] = "lots"
    data[1]["steps"][0]["repeat"] = "many"
    data[1]["steps"][0]["x"] = None
    path.write_text(json.dumps(data))
    reopened = MacroStore(tmp_path)
    assert [m.name for m in reopened.macros] == ["one", "two", "three"]
    step = reopened.macros[1].steps[0]
    assert (reopened.macros[1].loops, step.repeat, step.x) == (0, 1, 0)  # sensible values instead
    assert reopened.load_notice is None


def test_a_cut_off_file_is_kept_aside_before_anything_new_is_saved(tmp_path):
    from ultrebo.model import Macro
    from ultrebo.store import MacroStore

    _, path, _ = _store_with_three(tmp_path)
    text = path.read_text()
    path.write_text(text[: len(text) // 2])
    reopened = MacroStore(tmp_path)
    assert reopened.macros == [] and "couldn't read" in reopened.load_notice
    reopened.add(Macro(name="new"))  # this overwrites macros.json ...
    kept = list(tmp_path.glob("macros.damaged-*.json"))
    assert len(kept) == 1 and kept[0].read_text() == text[: len(text) // 2]  # ... but the damaged copy is safe


def test_a_macro_that_cannot_be_read_is_skipped_and_the_file_kept(tmp_path):
    import json

    from ultrebo.store import MacroStore

    _, path, data = _store_with_three(tmp_path)
    data[1] = "not a macro"
    path.write_text(json.dumps(data))
    reopened = MacroStore(tmp_path)
    assert [m.name for m in reopened.macros] == ["one", "three"]
    assert reopened.load_notice and list(tmp_path.glob("macros.damaged-*.json"))


def test_a_missing_file_is_just_a_first_start(tmp_path):
    from ultrebo.store import MacroStore

    store = MacroStore(tmp_path)
    assert store.macros == [] and store.load_notice is None and not list(tmp_path.glob("*.damaged-*"))


def test_odd_values_in_a_step_become_sensible_ones():
    from ultrebo.model import Step

    step = Step.from_dict({"repeat": 0, "delay_after_ms": "soon", "enabled": "yes", "template_file": 5, "region": [1, 2, 3],
                           "threshold": "x", "hold_ms": 2.9, "text": None, "keys": 7})
    assert (step.repeat, step.delay_after_ms, step.enabled, step.template_file, step.region) == (1, 500, True, None, None)
    assert (step.threshold, step.hold_ms, step.text, step.keys) == (0.8, 2, "", "")


def test_the_cursor_move_time_defaults_to_50_and_is_kept_per_macro(tmp_path):
    from ultrebo.model import Macro
    from ultrebo.store import MacroStore

    assert Macro().move_ms == 50
    assert Macro.from_dict({"name": "old macro made before this setting"}).move_ms == 50
    store = MacroStore(tmp_path)
    store.add(Macro(name="slow", move_ms=250))
    store.add(Macro(name="instant", move_ms=0))
    reopened = MacroStore(tmp_path)
    assert [m.move_ms for m in reopened.macros] == [250, 0]


def test_a_silly_move_time_is_kept_in_range():
    from ultrebo.model import Macro

    assert Macro.from_dict({"move_ms": -40}).move_ms == 0
    assert Macro.from_dict({"move_ms": 10**9}).move_ms == 5000
    assert Macro.from_dict({"move_ms": "fast"}).move_ms == 50
