# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Macro data model. Steps and macros are plain dataclasses saved as JSON."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any


class StepType(str, Enum):
    CLICK = "click"
    DRAG = "drag"
    SCROLL = "scroll"
    KEY = "key"
    IMAGE = "image"
    TEXT = "text"

    @property
    def label(self) -> str:
        return {
            StepType.CLICK: "Click",
            StepType.DRAG: "Drag",
            StepType.SCROLL: "Scroll",
            StepType.KEY: "Key press",
            StepType.IMAGE: "Find image",
            StepType.TEXT: "Find text",
        }[self]


class RunMode(str, Enum):
    SEQUENCE = "sequence"
    REACTIVE = "reactive"

    @property
    def label(self) -> str:
        return "Sequence" if self is RunMode.SEQUENCE else "Reactive"

    @property
    def help(self) -> str:
        if self is RunMode.SEQUENCE:
            return "Runs every step once per loop, from the top of the list to the bottom."
        return (
            "Each cycle, runs only the first step in the list whose condition is met, "
            "then starts over. Click, drag, scroll and key steps are always met, so put them "
            "at the bottom to act as a fallback. A \"Find\" step set to only wait holds back every "
            "step below it while its target is visible."
        )


class WatchAction(str, Enum):
    CONTINUE = "continue"
    RESTART = "restart"

    @property
    def label(self) -> str:
        return "Pause, then carry on" if self is WatchAction.CONTINUE else "Restart macro from the start"


def _coerce(value: Any, default: Any) -> Any:
    """`value` as the same kind of thing as `default`, or `default` when it can't be (a hand-edited or damaged file
    must never crash the app or the macro)."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        if isinstance(value, bool):
            return default
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default
    if isinstance(default, float):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if number == number and abs(number) != float("inf") else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return value


def _list_of_dicts(value: Any) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@dataclass
class RuleGroup:
    """Rules that share a group stop being checked together: once one of them is found, the rest rest too."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "Group"
    #: After one rule in the group is found, stop checking the whole group for this many seconds (0 = until the macro stops).
    pause_s: int = 0
    #: Start checking the group again whenever the macro restarts: it finishes a loop and starts over, or a rule restarts it.
    reset_on_restart: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "pause_s": self.pause_s, "reset_on_restart": self.reset_on_restart}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleGroup":
        try:
            pause = min(max(int(data.get("pause_s", 0)), 0), 86400)
        except (TypeError, ValueError):
            pause = 0
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex), name=str(data.get("name") or "Group")[:60], pause_s=pause,
            reset_on_restart=data.get("reset_on_restart") is True,
        )


@dataclass
class Step:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = ""
    type: StepType = StepType.CLICK
    enabled: bool = True
    #: Lower number runs first.
    priority: int = 0
    #: Pause after this step (after each repeat).
    delay_after_ms: int = 500
    repeat: int = 1

    # Positions are screen coordinates in the units the input backend uses.
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    button: str = "left"
    #: Press time for clicks and keys, travel time for drags.
    hold_ms: int = 60
    #: 1 = single click, 2 = double click.
    clicks: int = 1
    scroll_dx: int = 0
    scroll_dy: int = 0
    #: Key or combination such as "a", "enter", "f5", "ctrl+shift+s".
    keys: str = ""

    # Image and text steps.
    template_file: str | None = None
    text: str = ""
    threshold: float = 0.8
    #: Sequence mode: how long to keep looking. 0 = look once.
    timeout_ms: int = 5000
    #: Click the target when found (otherwise only wait for it).
    click_on_found: bool = True
    #: Watch the screen in the background for the whole run.
    watch: bool = False
    on_seen: WatchAction = WatchAction.CONTINUE
    #: Rules: glide the mouse to the target and wiggle it a little before clicking (some games need to see it move).
    nudge: bool = True
    #: Rules: which group the rule belongs to (a RuleGroup id), or None.
    group_id: str | None = None
    #: Rules: a key (or combination such as "ctrl+s") to press after the click when this is found. Empty = none.
    press_key: str = ""
    #: Send a screenshot to the Discord webhook (set in Settings) whenever this is found.
    notify: bool = False
    #: Optional search area [x, y, width, height]; None = whole screen.
    region: list[int] | None = None

    @property
    def is_image(self) -> bool:
        return self.type is StepType.IMAGE

    @property
    def is_text(self) -> bool:
        return self.type is StepType.TEXT

    @property
    def is_finder(self) -> bool:
        return self.type in (StepType.IMAGE, StepType.TEXT)

    def title(self) -> str:
        return self.name.strip() or self.type.label

    def summary(self) -> str:
        if self.type is StepType.CLICK:
            what = "Double-click" if self.clicks == 2 else "Click"
            return f"{what} {self.button} at ({self.x}, {self.y})"
        if self.type is StepType.DRAG:
            return f"Drag ({self.x}, {self.y}) to ({self.x2}, {self.y2})"
        if self.type is StepType.SCROLL:
            return f"Scroll {self.scroll_dy:+d} (horizontal {self.scroll_dx:+d})" if self.scroll_dx else f"Scroll {self.scroll_dy:+d}"
        if self.type is StepType.KEY:
            times = f" x{self.repeat}" if self.repeat > 1 else ""
            return f"Press {self.keys or '(no key)'}{times}"
        target = "image" if self.is_image else f'"{self.text}"'
        if self.is_image and not self.template_file:
            return "no image picked"
        if self.is_text and not self.text.strip():
            return "no text entered"
        verb = "click" if self.click_on_found else "wait for"
        over = " - then start the macro over" if self.on_seen is WatchAction.RESTART and not self.watch else ""
        return f"{verb} {target}{over}" + (" - screenshot to Discord" if self.notify else "")

    def rule_summary(self) -> str:
        """How a rule reads in the Rules list: what it looks for, then what it does."""
        target = "an image" if self.is_image else f'"{self.text}"'
        if self.is_image and not self.template_file:
            return "no image picked"
        if self.is_text and not self.text.strip():
            return "no text entered"
        click = "click it, then " if self.click_on_found else ""
        key = f"press {self.press_key.strip()}, then " if self.press_key.strip() else ""
        shot = "send a screenshot to Discord, then " if self.notify else ""
        return f"When {target} appears: {shot}{click}{key}{self.on_seen.label.lower()}"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            out[f.name] = value.value if isinstance(value, Enum) else value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in data:
                continue
            value = data[f.name]
            default = getattr(defaults, f.name)
            if isinstance(default, Enum):
                try:
                    value = type(default)(value)
                except ValueError:
                    value = default
            else:
                value = _coerce(value, default)
            kwargs[f.name] = value
        step = cls(**kwargs)
        for name in ("template_file", "group_id"):  # a text or nothing
            if not isinstance(getattr(step, name), str):
                setattr(step, name, None)
        region = step.region
        if region is not None and not (
            isinstance(region, list) and len(region) == 4 and all(isinstance(v, int) and not isinstance(v, bool) for v in region)
        ):
            step.region = None  # a search area is four whole numbers
        step.repeat = max(step.repeat, 1)
        return step


@dataclass
class Macro:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    name: str = "New macro"
    mode: RunMode = RunMode.SEQUENCE
    #: Loops (sequence) or cycles (reactive). 0 = run until stopped.
    loops: int = 0
    loop_delay_ms: int = 1000
    #: How often image/text steps look at the screen.
    scan_interval_ms: int = 1000
    #: How long the cursor takes to travel to each click, drag or scroll position (0 = jump straight there).
    move_ms: int = 50
    steps: list[Step] = field(default_factory=list)
    #: Always-watching detections. They run in the background for the whole run; when several are on
    #: screen at once the one with the lowest priority number is handled first.
    rules: list[Step] = field(default_factory=list)
    groups: list[RuleGroup] = field(default_factory=list)

    def group_name(self, group_id: str | None) -> str:
        group = next((g for g in self.groups if g.id == group_id), None)
        return group.name if group else ""

    def add_groups(self, groups: list[RuleGroup], rules: list[Step]) -> None:
        """Bring in groups that came with imported rules. A group with a name you already have is reused."""
        by_name = {g.name.lower(): g for g in self.groups}
        remap: dict[str, str] = {}
        for group in groups:
            existing = by_name.get(group.name.lower())
            if existing is None:
                self.groups.append(group)
                by_name[group.name.lower()] = group
                existing = group
            remap[group.id] = existing.id
        for rule in rules:
            rule.group_id = remap.get(rule.group_id) if rule.group_id else None

    def delete_group(self, group_id: str) -> None:
        self.groups = [g for g in self.groups if g.id != group_id]
        for rule in self.rules:
            if rule.group_id == group_id:
                rule.group_id = None

    def ordered(self) -> list[Step]:
        """Steps in execution order: priority ascending, ties keep list order."""
        indexed = sorted(enumerate(self.steps), key=lambda p: (p[1].priority, p[0]))
        return [s for _, s in indexed]

    def next_priority(self) -> int:
        return (max((s.priority for s in self.steps), default=0)) + 10

    def renumber(self, ordered: list[Step]) -> None:
        """Make the given order permanent: priorities 10, 20, 30, ..."""
        for i, step in enumerate(ordered):
            step.priority = (i + 1) * 10
        self.steps = list(ordered)

    def ordered_rules(self) -> list[Step]:
        """Rules in the order they win: priority ascending, ties keep list order."""
        indexed = sorted(enumerate(self.rules), key=lambda p: (p[1].priority, p[0]))
        return [r for _, r in indexed]

    def next_rule_priority(self) -> int:
        return (max((r.priority for r in self.rules), default=0)) + 10

    def renumber_rules(self, ordered: list[Step]) -> None:
        for i, rule in enumerate(ordered):
            rule.priority = (i + 1) * 10
        self.rules = list(ordered)

    def migrate_watchers(self) -> None:
        """Older macros marked image/text steps "always watching" inside the step list; those are rules now."""
        moved = [s for s in self.steps if s.watch and s.is_finder]
        if not moved:
            return
        self.steps = [s for s in self.steps if s not in moved]
        for rule in moved:
            rule.repeat = 1
            self.rules.append(rule)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode.value,
            "loops": self.loops,
            "loop_delay_ms": self.loop_delay_ms,
            "scan_interval_ms": self.scan_interval_ms,
            "move_ms": self.move_ms,
            "steps": [s.to_dict() for s in self.steps],
            "rules": [r.to_dict() for r in self.rules],
            "groups": [g.to_dict() for g in self.groups],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Macro":
        default = cls()
        try:
            mode = RunMode(data.get("mode", default.mode.value))
        except ValueError:
            mode = default.mode
        macro = cls(
            id=_coerce(data.get("id"), "") or uuid.uuid4().hex,
            name=_coerce(data.get("name"), default.name),
            mode=mode,
            loops=_coerce(data.get("loops"), default.loops),
            loop_delay_ms=_coerce(data.get("loop_delay_ms"), default.loop_delay_ms),
            scan_interval_ms=_coerce(data.get("scan_interval_ms"), default.scan_interval_ms),
            move_ms=min(max(_coerce(data.get("move_ms"), default.move_ms), 0), 5000),
            steps=[Step.from_dict(s) for s in _list_of_dicts(data.get("steps"))],
            rules=[Step.from_dict(r) for r in _list_of_dicts(data.get("rules"))],
            groups=[RuleGroup.from_dict(g) for g in _list_of_dicts(data.get("groups"))],
        )
        known = {g.id for g in macro.groups}
        for rule in macro.rules:
            rule.watch = True
            if rule.group_id not in known:
                rule.group_id = None
        macro.migrate_watchers()
        return macro
