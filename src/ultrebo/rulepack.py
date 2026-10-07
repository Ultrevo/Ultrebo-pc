# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Shareable rule packs: a macro's rules (with their pictures) in one file other players can import.

A pack is a zip file with `rules.json` and the pictures in `images/`. Packs come from strangers, so
importing never extracts files to disk by name: it reads only the exact members it expects, checks
sizes, re-encodes every picture, and clamps every number.
"""
from __future__ import annotations

import json
import uuid
import zipfile
import zlib
from pathlib import Path
from typing import Callable, NamedTuple

import cv2
import numpy as np

from . import __version__
from .inputs import validate_key_spec
from .model import Macro, RuleGroup, Step, StepType, WatchAction

EXTENSION = ".ultrebo-rules"
FORMAT = 1
PLATFORM = "desktop"
MAX_RULES = 100
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 512 * 1024
MAX_IMAGE_SIDE = 4000
BUTTONS = {"left", "right", "middle"}


class Pack(NamedTuple):
    name: str
    rules: list[Step]
    groups: list[RuleGroup]  # new groups; each rule's group_id points at one of them


class RulePackError(Exception):
    """The file is not a usable rule pack; the message is safe to show to the user."""


def export_pack(macro: Macro, templates_dir: Path, path: Path, name: str | None = None) -> int:
    """Write the macro's rules to `path`. Returns how many rules were written."""
    rules = [r for r in macro.ordered_rules() if r.is_finder]
    if not rules:
        raise RulePackError("This macro has no rules to share yet.")
    entries: list[dict] = []
    images: dict[str, bytes] = {}
    for rule in rules:
        data = rule.to_dict()
        for key in ("id", "priority", "region", "template_file", "group_id", "notify"):
            data.pop(key, None)  # ids are new on import; the search area belongs to this screen only; Discord is your own
        if rule.group_id and macro.group_name(rule.group_id):
            data["group"] = macro.group_name(rule.group_id)
        if rule.is_image:
            if not rule.template_file:
                raise RulePackError(f'The rule "{rule.title()}" has no image picked.')
            try:
                png = (Path(templates_dir) / rule.template_file).read_bytes()
            except OSError as e:
                raise RulePackError(f'The picture for the rule "{rule.title()}" is missing: {e}') from e
            member = f"images/{len(images) + 1}.png"
            images[member] = png
            data["image"] = member
        entries.append(data)
    used = {r.group_id for r in rules if r.group_id}
    groups = [
        {"name": g.name, "pause_s": g.pause_s, "reset_on_restart": g.reset_on_restart}
        for g in macro.groups if g.id in used
    ]
    manifest = {
        "format": FORMAT, "platform": PLATFORM, "app_version": __version__, "name": name or macro.name,
        "groups": groups, "rules": entries,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("rules.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for member, png in images.items():
            z.writestr(member, png)
    return len(entries)


def _clamp(value, low, high, default):
    try:
        return min(max(type(default)(value), low), high)
    except (TypeError, ValueError):
        return default


def _read_member(z: zipfile.ZipFile, name: str, limit: int) -> bytes:
    try:
        info = z.getinfo(name)
    except KeyError as e:
        raise RulePackError(f"The file is missing {name}.") from e
    if info.file_size > limit:
        raise RulePackError(f"{name} is too large for a rule pack.")
    try:
        with z.open(info) as f:
            data = f.read(limit + 1)
    except OSError as e:  # a mangled entry inside the file (not a problem with the disk)
        raise RulePackError(f"{name} in this file is damaged.") from e
    if len(data) > limit:
        raise RulePackError(f"{name} is too large for a rule pack.")
    return data


def _clean_png(data: bytes) -> bytes:
    """Decode and re-encode a picture so only a real, reasonably sized image is ever saved."""
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RulePackError("One of the pictures in the file is not a valid image.")
    h, w = image.shape[:2]
    if h < 4 or w < 4 or h > MAX_IMAGE_SIDE or w > MAX_IMAGE_SIDE:
        raise RulePackError("One of the pictures in the file has an unusable size.")
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RulePackError("One of the pictures in the file could not be read.")
    return encoded.tobytes()


def read_pack(
    path: Path, save_template: Callable[[bytes], str], delete_template: Callable[[str], None]
) -> Pack:
    """Read a pack (see `_read_pack`). A cut-off or damaged file is reported as a RulePackError, never a crash."""
    try:
        return _read_pack(path, save_template, delete_template)
    except RulePackError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError, OverflowError, UnicodeError) as e:
        raise RulePackError("This rule pack is damaged or can't be read (maybe the download was cut short). Ask for it again.") from e


def _read_pack(
    path: Path, save_template: Callable[[bytes], str], delete_template: Callable[[str], None]
) -> Pack:
    """Read a pack. `save_template(png_bytes)` stores a picture and returns its file name.

    Returns the pack's name, rules and groups. Nothing is saved unless the whole pack is valid, and pictures saved
    before a failure are removed again with `delete_template`.
    """
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise RulePackError("This file isn't a rule pack.") from e
    with z:
        try:
            manifest = json.loads(_read_member(z, "rules.json", MAX_JSON_BYTES).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise RulePackError("This file isn't a rule pack.") from e
        if not isinstance(manifest, dict) or not isinstance(manifest.get("rules"), list):
            raise RulePackError("This file isn't a rule pack.")
        platform = manifest.get("platform")
        if platform not in (None, "", PLATFORM):
            raise RulePackError("This rule pack was made for the phone version of Ultrebo, so it can't be used on a computer.")
        if manifest.get("format") != FORMAT:
            raise RulePackError("This rule pack was made by a newer version of Ultrebo. Update Ultrebo and try again.")
        raw = manifest["rules"]
        if not raw:
            raise RulePackError("This rule pack has no rules in it.")
        if len(raw) > MAX_RULES:
            raise RulePackError(f"This rule pack has too many rules (the limit is {MAX_RULES}).")

        groups: dict[str, RuleGroup] = {}
        raw_groups = manifest.get("groups", [])
        for item in raw_groups if isinstance(raw_groups, list) else []:
            if isinstance(item, dict) and str(item.get("name") or "").strip():
                group = RuleGroup.from_dict({
                    "name": str(item["name"]).strip(), "pause_s": item.get("pause_s", 0),
                    "reset_on_restart": item.get("reset_on_restart") is True,
                })
                group.id = uuid.uuid4().hex
                groups.setdefault(group.name.lower(), group)
        rules: list[Step] = []
        pictures: list[bytes | None] = []
        for item in raw:
            if not isinstance(item, dict):
                raise RulePackError("This file isn't a rule pack.")
            kind = item.get("type")
            if kind not in (StepType.IMAGE.value, StepType.TEXT.value):
                raise RulePackError("Rule packs can only contain picture and text rules.")
            rule = Step.from_dict({k: v for k, v in item.items() if k not in ("id", "template_file", "region", "group_id")})
            rule.watch = True
            rule.notify = False  # a pack never switches on sending screenshots; that is each person's own choice
            rule.nudge = bool(rule.nudge)
            found = groups.get(str(item.get("group") or "").strip().lower()) if item.get("group") else None
            rule.group_id = found.id if found else None
            rule.name = str(rule.name)[:80]
            rule.text = str(rule.text).strip()[:200]
            rule.threshold = _clamp(rule.threshold, 0.1, 1.0, 0.8)
            rule.delay_after_ms = _clamp(rule.delay_after_ms, 0, 3_600_000, 500)
            rule.hold_ms = _clamp(rule.hold_ms, 1, 5000, 60)
            rule.clicks = 2 if rule.clicks == 2 else 1
            rule.repeat = 1
            rule.button = rule.button if rule.button in BUTTONS else "left"
            rule.press_key = str(rule.press_key).strip()[:40]
            if rule.press_key and validate_key_spec(rule.press_key):
                rule.press_key = ""  # not a key this app knows: drop it rather than refuse the whole pack
            rule.enabled = bool(rule.enabled)
            rule.click_on_found = bool(rule.click_on_found)
            if not isinstance(rule.on_seen, WatchAction):
                rule.on_seen = WatchAction.CONTINUE
            if rule.is_text and not rule.text:
                raise RulePackError("A text rule in this file has no text.")
            picture = None
            if rule.is_image:
                member = item.get("image")
                if not isinstance(member, str) or not (member.startswith("images/") and member.endswith(".png")):
                    raise RulePackError("A picture rule in this file has no picture.")
                picture = _clean_png(_read_member(z, member, MAX_IMAGE_BYTES))
            rules.append(rule)
            pictures.append(picture)

    saved: list[str] = []
    try:
        for rule, picture in zip(rules, pictures):
            if picture is not None:
                rule.template_file = save_template(picture)
                saved.append(rule.template_file)
    except Exception:
        for file in saved:
            delete_template(file)
        raise
    name = str(manifest.get("name") or "").strip()[:80]
    used = {r.group_id for r in rules if r.group_id}
    return Pack(name, rules, [g for g in groups.values() if g.id in used])
