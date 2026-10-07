# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import json
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import cv2
import numpy as np
import pytest

from ultrebo import rulepack
from ultrebo.model import Macro, Step, StepType, WatchAction
from ultrebo.rulepack import RulePackError
from ultrebo.store import MacroStore


def png(seed=1, shape=(40, 60, 3)):
    rng = np.random.default_rng(seed)
    ok, data = cv2.imencode(".png", rng.integers(0, 255, size=shape, dtype=np.uint8))
    return data.tobytes()


@pytest.fixture
def store(tmp_path):
    return MacroStore(tmp_path / "data")


@pytest.fixture
def other(tmp_path):
    return MacroStore(tmp_path / "friend")


def macro_with_rules(store):
    name = store.save_template_bytes(png(1))
    macro = Macro(name="Tower farm", rules=[
        Step(type=StepType.TEXT, text="I'm here", watch=True, priority=20, name="AFK", on_seen=WatchAction.RESTART,
             region=[1, 2, 30, 40], delay_after_ms=900, threshold=0.7),
        Step(type=StepType.IMAGE, template_file=name, watch=True, priority=10, name="Claim", click_on_found=False,
             region=[5, 5, 5, 5]),
    ])
    return macro


def read(path, store):
    return rulepack.read_pack(path, store.save_template_bytes, store.delete_template)


def test_export_then_import_keeps_everything_but_ids_and_search_area(store, other, tmp_path):
    macro = macro_with_rules(store)
    path = tmp_path / f"farm{rulepack.EXTENSION}"
    assert rulepack.export_pack(macro, store.templates_dir, path) == 2
    name, rules, groups = read(path, other)
    assert name == "Tower farm" and groups == []
    assert [r.name for r in rules] == ["Claim", "AFK"]  # exported in priority order
    claim, afk = rules
    assert (afk.text, afk.on_seen, afk.delay_after_ms, afk.threshold, afk.watch) == ("I'm here", WatchAction.RESTART, 900, 0.7, True)
    assert claim.click_on_found is False
    assert claim.region is None and afk.region is None  # a search area belongs to one screen
    assert claim.id != macro.rules[1].id
    pic = other.template_path(claim.template_file)
    assert pic.exists() and cv2.imread(str(pic)).shape == (40, 60, 3)
    assert len(list(other.templates_dir.iterdir())) == 1  # only the one picture rule


def test_nothing_to_share(store, tmp_path):
    with pytest.raises(RulePackError, match="no rules"):
        rulepack.export_pack(Macro(), store.templates_dir, tmp_path / "x.ultrebo-rules")


def make_pack(path, manifest, members=None, raw_json=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("rules.json", raw_json if raw_json is not None else json.dumps(manifest))
        for name, data in (members or {}).items():
            z.writestr(name, data)
    return path


def text_rule(**kw):
    return {"type": "text", "text": "hi", **kw}


def test_rejects_files_that_are_not_packs(other, tmp_path):
    junk = tmp_path / "junk.ultrebo-rules"
    junk.write_bytes(b"not a zip")
    for bad in (
        junk,
        make_pack(tmp_path / "a.zip", None, raw_json="{not json"),
        make_pack(tmp_path / "b.zip", {"format": 1, "rules": "nope"}),
        make_pack(tmp_path / "c.zip", {"format": 1, "rules": []}),
        make_pack(tmp_path / "d.zip", {"format": 2, "rules": [text_rule()]}),
        make_pack(tmp_path / "e.zip", {"format": 1, "rules": [{"type": "click", "x": 1}]}),
        make_pack(tmp_path / "f.zip", {"format": 1, "rules": [text_rule(text="  ")]}),
        make_pack(tmp_path / "g.zip", {"format": 1, "rules": [text_rule()] * (rulepack.MAX_RULES + 1)}),
    ):
        with pytest.raises(RulePackError):
            read(bad, other)
    assert list(other.templates_dir.iterdir()) == []


def test_picture_problems_save_nothing(other, tmp_path):
    good = {"type": "image", "image": "images/1.png"}
    cases = [
        ({"format": 1, "rules": [good]}, {}),  # picture missing from the zip
        ({"format": 1, "rules": [good]}, {"images/1.png": b"this is not a png"}),
        ({"format": 1, "rules": [{"type": "image", "image": "../../evil.png"}]}, {"../../evil.png": png()}),
        ({"format": 1, "rules": [{"type": "image"}]}, {}),
        ({"format": 1, "rules": [good, {"type": "image", "image": "images/2.png"}]}, {"images/1.png": png(), "images/2.png": b"bad"}),
        ({"format": 1, "rules": [good]}, {"images/1.png": png(shape=(2, 2, 3))}),
    ]
    for i, (manifest, members) in enumerate(cases):
        with pytest.raises(RulePackError):
            read(make_pack(tmp_path / f"p{i}.zip", manifest, members), other)
    assert list(other.templates_dir.iterdir()) == []  # including the picture saved before the second rule failed


def test_a_failure_while_saving_removes_pictures_already_saved(other, tmp_path):
    manifest = {"format": 1, "rules": [{"type": "image", "image": "images/1.png"}, {"type": "image", "image": "images/2.png"}]}
    path = make_pack(tmp_path / "p.zip", manifest, {"images/1.png": png(1), "images/2.png": png(2)})
    calls = []

    def flaky_save(data):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("disk full")
        return other.save_template_bytes(data)

    with pytest.raises(OSError):
        rulepack.read_pack(path, flaky_save, other.delete_template)
    assert list(other.templates_dir.iterdir()) == []


def test_oversized_pictures_are_refused(other, tmp_path, monkeypatch):
    monkeypatch.setattr(rulepack, "MAX_IMAGE_BYTES", 100)
    path = make_pack(tmp_path / "p.zip", {"format": 1, "rules": [{"type": "image", "image": "images/1.png"}]}, {"images/1.png": png()})
    with pytest.raises(RulePackError, match="too large"):
        read(path, other)


def test_hostile_numbers_and_fields_are_cleaned(other, tmp_path):
    rule = text_rule(
        threshold=99, delay_after_ms=-5, hold_ms=10**9, clicks=7, button="evil", repeat=500, enabled=False,
        on_seen="nonsense", id="steal-this", template_file="../../etc/passwd", region=[0, 0, 9, 9], name="x" * 500,
        watch=False,
    )
    path = make_pack(tmp_path / "p.zip", {"format": 1, "rules": [rule]})
    _, [r], _groups = read(path, other)
    assert (r.threshold, r.delay_after_ms, r.hold_ms, r.clicks, r.button, r.repeat) == (1.0, 0, 5000, 1, "left", 1)
    assert r.enabled is False and r.on_seen is WatchAction.CONTINUE and r.watch is True
    assert r.id != "steal-this" and r.template_file is None and r.region is None and len(r.name) == 80


def test_a_pack_made_on_a_phone_is_explained(other, tmp_path):
    path = make_pack(tmp_path / "p.zip", {"format": 1, "platform": "android", "rules": [text_rule()]})
    with pytest.raises(RulePackError, match="phone version"):
        read(path, other)
    # packs without a platform (older ones) and desktop packs are fine
    assert read(make_pack(tmp_path / "q.zip", {"format": 1, "rules": [text_rule()]}), other).rules
    assert read(make_pack(tmp_path / "r.zip", {"format": 1, "platform": "desktop", "rules": [text_rule()]}), other).rules


def test_exported_packs_say_where_they_came_from(store, tmp_path):
    path = tmp_path / "x.ultrebo-rules"
    rulepack.export_pack(macro_with_rules(store), store.templates_dir, path)
    with zipfile.ZipFile(path) as z:
        assert json.loads(z.read("rules.json"))["platform"] == "desktop"


def test_groups_travel_with_the_rules_and_merge_by_name(store, other, tmp_path):
    from ultrebo.model import RuleGroup

    pop = RuleGroup(name="Pop-ups", pause_s=30)
    unused = RuleGroup(name="Not used")
    macro = Macro(name="m", groups=[pop, unused], rules=[
        Step(type=StepType.TEXT, text="a", watch=True, priority=10, group_id=pop.id),
        Step(type=StepType.TEXT, text="b", watch=True, priority=20, group_id=pop.id),
        Step(type=StepType.TEXT, text="c", watch=True, priority=30),
    ])
    path = tmp_path / "g.ultrebo-rules"
    rulepack.export_pack(macro, store.templates_dir, path)
    with zipfile.ZipFile(path) as z:
        assert json.loads(z.read("rules.json"))["groups"] == [{"name": "Pop-ups", "pause_s": 30, "reset_on_restart": False}]  # only groups in use
    _, rules, groups = read(path, other)
    assert [g.name for g in groups] == ["Pop-ups"] and groups[0].pause_s == 30
    assert [r.group_id for r in rules] == [groups[0].id, groups[0].id, None]

    mine = Macro(groups=[RuleGroup(name="pop-ups", pause_s=5)])  # same name, different case: reused
    mine.add_groups(groups, rules)
    assert len(mine.groups) == 1 and mine.groups[0].pause_s == 5
    assert [r.group_id for r in rules] == [mine.groups[0].id, mine.groups[0].id, None]
    empty = Macro()
    _, rules2, groups2 = read(path, other)
    empty.add_groups(groups2, rules2)
    assert [g.name for g in empty.groups] == ["Pop-ups"] and rules2[0].group_id == empty.groups[0].id


def test_junk_groups_in_a_pack_are_ignored(other, tmp_path):
    manifest = {"format": 1, "groups": [{"name": "  "}, "x", {"name": "Real", "pause_s": -4}], "rules": [
        text_rule(group="Real"), text_rule(group="Missing"), text_rule()]}
    _, rules, groups = read(make_pack(tmp_path / "p.zip", manifest), other)
    assert [g.name for g in groups] == ["Real"] and groups[0].pause_s == 0
    assert [bool(r.group_id) for r in rules] == [True, False, False]


def test_a_damaged_pack_is_a_friendly_error_not_a_crash(store, other, tmp_path):
    import random

    path = tmp_path / f"p{rulepack.EXTENSION}"
    rulepack.export_pack(macro_with_rules(store), store.templates_dir, path)
    original = path.read_bytes()
    rng = random.Random(4)
    for _ in range(150):
        damaged = bytearray(original)
        for _ in range(rng.randint(1, 10)):
            damaged[rng.randrange(len(damaged))] = rng.randrange(256)
        path.write_bytes(bytes(damaged))
        try:
            read(path, other)
        except RulePackError:
            pass  # a clear message; anything else would fail the test
