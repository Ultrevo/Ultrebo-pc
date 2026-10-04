# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Global hotkeys (work even while a game has focus)."""
from __future__ import annotations

from typing import Callable

from .inputs import parse_key_spec


def to_pynput_format(spec: str) -> str:
    """"ctrl+f8" -> "<ctrl>+<f8>", "f8" -> "<f8>", "s" -> "s"."""
    mods, key = parse_key_spec(spec)
    parts = [f"<{m}>" for m in mods] + [key if len(key) == 1 else f"<{key}>"]
    return "+".join(parts)


class HotkeyManager:
    def __init__(self) -> None:
        self._listener = None

    def set_bindings(self, bindings: dict[str, Callable[[], None]]) -> None:
        """Replace all hotkeys. `bindings` maps a key spec such as "f8" to what to call."""
        from pynput import keyboard

        self.stop()
        mapping = {to_pynput_format(spec): cb for spec, cb in bindings.items() if spec}
        if not mapping:
            return
        self._listener = keyboard.GlobalHotKeys(mapping)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
