# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Saves macros, cropped images and settings in the user's data folder."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .model import Macro


@dataclass
class Settings:
    check_updates: bool = True
    start_stop_hotkey: str = "f8"
    record_hotkey: str = "f9"
    active_macro_id: str | None = None
    #: Which monitor image and text steps watch (1, 2, ...).
    monitor: int = 1
    #: Discord webhook that steps and rules marked "send a screenshot to Discord" post to. It is a secret, so it
    #: stays in this file and is never put in a macro or a shared rule pack.
    webhook_url: str = ""
    #: Not used for anything yet; keeps unknown keys from older/newer versions when saving.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = dict(self.extra)
        data.update(
            check_updates=self.check_updates,
            start_stop_hotkey=self.start_stop_hotkey,
            record_hotkey=self.record_hotkey,
            active_macro_id=self.active_macro_id,
            monitor=self.monitor,
            webhook_url=self.webhook_url,
        )
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {"check_updates", "start_stop_hotkey", "record_hotkey", "active_macro_id", "monitor", "webhook_url"}
        s = cls()
        s.check_updates = bool(data.get("check_updates", s.check_updates))
        s.start_stop_hotkey = str(data.get("start_stop_hotkey", s.start_stop_hotkey))
        s.record_hotkey = str(data.get("record_hotkey", s.record_hotkey))
        s.active_macro_id = data.get("active_macro_id")
        try:
            s.monitor = max(int(data.get("monitor", s.monitor)), 1)
        except (TypeError, ValueError):
            pass
        url = data.get("webhook_url")
        s.webhook_url = url.strip() if isinstance(url, str) else ""
        s.extra = {k: v for k, v in data.items() if k not in known}
        return s


class MacroStore:
    """All macros plus settings. Every change is written to disk straight away."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.templates_dir = self.folder / "templates"
        self.templates_dir.mkdir(exist_ok=True)
        #: Where shared rule packs are saved and opened from (the Rules tab's Share menu).
        self.rule_packs_dir = self.folder / "Rule packs"
        self.rule_packs_dir.mkdir(exist_ok=True)
        self._macros_file = self.folder / "macros.json"
        self._settings_file = self.folder / "settings.json"
        self._lock = threading.RLock()
        self._listeners: list[Callable[[], None]] = []
        #: Told when a change can't be written to disk (the interface shows it). Without one the error is raised.
        self.on_save_error: Callable[[str], None] | None = None
        self.macros: list[Macro] = self._load_macros()
        self.settings: Settings = self._load_settings()

    # -- change notification (the interface listens so it can refresh)
    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    # -- macros
    def get(self, macro_id: str | None) -> Macro | None:
        with self._lock:
            return next((m for m in self.macros if m.id == macro_id), None)

    def add(self, macro: Macro) -> Macro:
        with self._lock:
            self.macros.append(macro)
            self.save()
        self._changed()
        return macro

    def delete(self, macro_id: str) -> None:
        with self._lock:
            macro = self.get(macro_id)
            if macro is not None:
                for step in [*macro.steps, *macro.rules]:
                    if step.template_file:
                        self.delete_template(step.template_file)
            self.macros = [m for m in self.macros if m.id != macro_id]
            if self.settings.active_macro_id == macro_id:
                self.settings.active_macro_id = None
                self.save_settings()
            self.save()
        self._changed()

    def save(self) -> None:
        """Write macros to disk. Call after changing a macro or its steps."""
        with self._lock:
            self._write_or_report(self._macros_file, [m.to_dict() for m in self.macros], "your macros")
        self._changed()

    def save_settings(self) -> None:
        with self._lock:
            self._write_or_report(self._settings_file, self.settings.to_dict(), "your settings")

    def _write_or_report(self, path: Path, payload, what: str) -> None:
        try:
            self._write(path, payload)
        except OSError as e:
            if self.on_save_error is None:
                raise
            self.on_save_error(f"Ultrebo couldn't save {what}: {e}\n\nFolder: {self.folder}")

    # -- cropped images
    def template_path(self, name: str) -> Path:
        return self.templates_dir / name

    def new_template_name(self) -> str:
        return f"{uuid.uuid4().hex}.png"

    def save_template_bytes(self, png: bytes) -> str:
        name = self.new_template_name()
        self.template_path(name).write_bytes(png)
        return name

    def delete_template(self, name: str) -> None:
        try:
            self.template_path(name).unlink()
        except OSError:
            pass

    # -- disk
    def _load_macros(self) -> list[Macro]:
        try:
            data = json.loads(self._macros_file.read_text(encoding="utf-8"))
            return [Macro.from_dict(m) for m in data]
        except (OSError, ValueError, TypeError, AttributeError):
            return []

    def _load_settings(self) -> Settings:
        try:
            return Settings.from_dict(json.loads(self._settings_file.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, AttributeError):
            return Settings()

    @staticmethod
    def _write(path: Path, payload, attempts: int = 8) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        for attempt in range(attempts):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                # On Windows another program (antivirus, a sync or search tool) can hold the file for a moment.
                if attempt == attempts - 1:
                    raise
                time.sleep(0.05 * (attempt + 1))
