# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Shared objects for the interface, plus the "pick something on the screen" helper."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from ..runner import Runner
from ..screen import ScreenSource
from ..store import MacroStore
from .monitor_view import qt_screen_for
from .picker import PickerOverlay


@dataclass
class AppContext:
    store: MacroStore
    screen: ScreenSource
    runner: Runner
    _overlays: list = field(default_factory=list)

    # -- monitor
    def apply_monitor(self, number: int) -> None:
        """Make image/text steps (and the picker) use monitor `number`, if the screen source supports choosing."""
        if hasattr(self.screen, "set_monitor"):
            self.screen.set_monitor(number)

    # -- templates
    def save_template(self, frame: np.ndarray, x: int, y: int, w: int, h: int) -> str | None:
        """Crop the box out of `frame` (screenshot pixels), save it, and return its file name."""
        h_img, w_img = frame.shape[:2]
        x0, y0 = max(x, 0), max(y, 0)
        x1, y1 = min(x + w, w_img), min(y + h, h_img)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return None
        ok, encoded = cv2.imencode(".png", frame[y0:y1, x0:x1])
        if not ok:
            return None
        name = self.store.new_template_name()
        self.store.template_path(name).write_bytes(encoded.tobytes())
        return name

    # -- picking on screen
    def pick(
        self,
        hide: list[QWidget],
        mode: str,
        on_box: Callable[[np.ndarray, int, int, int, int], None] | None = None,
        on_point: Callable[[int, int], None] | None = None,
        hint: str = "",
    ) -> None:
        """Hide our windows, show a screenshot overlay, and report what the user picked.

        `on_box` gets (frame, x, y, w, h) in screenshot pixels; `on_point` gets input coordinates.
        """
        visible = [w for w in hide if w.isVisible()]
        for w in visible:
            if hasattr(w, "picking"):
                w.picking = True  # a dialog waiting for an answer (see StepDialog.exec) must wait for the pick, not give up
            w.hide()

        def restore() -> None:
            for w in visible:
                w.show()
                w.raise_()

        def done() -> None:
            for w in visible:
                if hasattr(w, "picking"):
                    w.picking = False
                    w.pick_finished.emit()

        def start() -> None:
            try:
                frame = self.screen.grab()
            except Exception:  # noqa: BLE001
                restore()
                done()
                return
            overlay = PickerOverlay(frame, mode, hint)
            self._overlays.append(overlay)

            def finish(callback: Callable[[], None] | None) -> None:
                restore()
                if overlay in self._overlays:
                    self._overlays.remove(overlay)
                try:
                    if callback:
                        callback()
                finally:
                    done()

            overlay.box_picked.connect(
                lambda x, y, w, h: finish(lambda: on_box and on_box(frame, x, y, w, h))
            )
            overlay.point_picked.connect(
                lambda px, py: finish(lambda: on_point and on_point(*self.screen.to_input(px, py)))
            )
            overlay.cancelled.connect(lambda: finish(None))
            if hasattr(self.screen, "list_monitors"):
                target = qt_screen_for(self.screen.list_monitors(), self.screen.monitor_index)
                if target is not None:
                    overlay.setScreen(target)
                    overlay.setGeometry(target.geometry())
            overlay.showFullScreen()
            overlay.activateWindow()
            overlay.raise_()

        QTimer.singleShot(300, start)  # give the windows time to disappear
