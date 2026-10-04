# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Saves macros, cropped images and settings in the user's data folder."""
from __future__ import annotations

import json
import os
import threading
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
    #: Not used for anything yet; keeps unknown keys from older/newer versions when saving.
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = dict(self.extra)
        data.update(
            check_updates=self.check_updates,
            start_stop_hotkey=self.start_stop_hotkey,
            record_hotkey=self.record_hotkey,
            active_macro_id=self.active_macro_id,
        )
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        known = {"check_updates", "start_stop_hotkey", "record_hotkey", "active_macro_id"}
        s = cls()
        s.check_updates = bool(data.get("check_updates", s.check_updates))
        s.start_stop_hotkey = str(data.get("start_stop_hotkey", s.start_stop_hotkey))
        s.record_hotkey = str(data.get("record_hotkey", s.record_hotkey))
        s.active_macro_id = data.get("active_macro_id")
        s.extra = {k: v for k, v in data.items() if k not in known}
        return s


class MacroStore:
    """All macros plus settings. Every change is written to disk straight away."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.templates_dir = self.folder / "templates"
        self.templates_dir.mkdir(exist_ok=True)
        self._macros_file = self.folder / "macros.json"
        self._settings_file = self.folder / "settings.json"
        self._lock = threading.RLock()
        self._listeners: list[Callable[[], None]] = []
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
                for step in macro.steps:
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
            self._write(self._macros_file, [m.to_dict() for m in self.macros])
        self._changed()

    def save_settings(self) -> None:
        with self._lock:
            self._write(self._settings_file, self.settings.to_dict())

    # -- cropped images
    def template_path(self, name: str) -> Path:
        return self.templates_dir / name

    def new_template_name(self) -> str:
        return f"{uuid.uuid4().hex}.png"

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
    def _write(path: Path, payload) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
