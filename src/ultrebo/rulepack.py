# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Shareable rule packs: a macro's rules (with their pictures) in one file other players can import.

A pack is a zip file with `rules.json` and the pictures in `images/`. Packs come from strangers, so
importing never extracts files to disk by name: it reads only the exact members it expects, checks
sizes, re-encodes every picture, and clamps every number.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import __version__
from .model import Macro, Step, StepType, WatchAction

EXTENSION = ".ultrebo-rules"
FORMAT = 1
MAX_RULES = 100
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_JSON_BYTES = 512 * 1024
MAX_IMAGE_SIDE = 4000
BUTTONS = {"left", "right", "middle"}


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
        for key in ("id", "priority", "region", "template_file"):
            data.pop(key, None)  # ids are new on import; the search area belongs to this screen only
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
    manifest = {"format": FORMAT, "app_version": __version__, "name": name or macro.name, "rules": entries}
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
    with z.open(info) as f:
        data = f.read(limit + 1)
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
) -> tuple[str, list[Step]]:
    """Read a pack. `save_template(png_bytes)` stores a picture and returns its file name.

    Returns (pack name, rules). Nothing is saved unless the whole pack is valid, and pictures saved
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
        if manifest.get("format") != FORMAT:
            raise RulePackError("This rule pack was made by a newer version of Ultrebo. Update Ultrebo and try again.")
        raw = manifest["rules"]
        if not raw:
            raise RulePackError("This rule pack has no rules in it.")
        if len(raw) > MAX_RULES:
            raise RulePackError(f"This rule pack has too many rules (the limit is {MAX_RULES}).")

        rules: list[Step] = []
        pictures: list[bytes | None] = []
        for item in raw:
            if not isinstance(item, dict):
                raise RulePackError("This file isn't a rule pack.")
            kind = item.get("type")
            if kind not in (StepType.IMAGE.value, StepType.TEXT.value):
                raise RulePackError("Rule packs can only contain picture and text rules.")
            rule = Step.from_dict({k: v for k, v in item.items() if k not in ("id", "template_file", "region")})
            rule.watch = True
            rule.name = str(rule.name)[:80]
            rule.text = str(rule.text).strip()[:200]
            rule.threshold = _clamp(rule.threshold, 0.1, 1.0, 0.8)
            rule.delay_after_ms = _clamp(rule.delay_after_ms, 0, 3_600_000, 500)
            rule.hold_ms = _clamp(rule.hold_ms, 1, 5000, 60)
            rule.clicks = 2 if rule.clicks == 2 else 1
            rule.repeat = 1
            rule.button = rule.button if rule.button in BUTTONS else "left"
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
    return name, rules
