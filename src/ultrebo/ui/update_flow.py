# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Runs the self-update download off the interface thread and reports back with signals."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from .. import selfupdate
from ..updater import Update


class UpdateJob(QObject):
    progress = Signal(int, int)  # bytes done, bytes total
    prepared = Signal(object)  # selfupdate.PreparedUpdate
    failed = Signal(str)

    def __init__(self, update: Update, parent: QObject | None = None):
        super().__init__(parent)
        self._update = update
        self._cancelled = False

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="ultrebo-self-update").start()

    def cancel(self) -> None:
        self._cancelled = True

    def _run(self) -> None:
        try:
            result = selfupdate.prepare(self._update, self.progress.emit, lambda: self._cancelled)
        except selfupdate.UpdateError as e:
            if not self._cancelled:
                self.failed.emit(str(e))
            return
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"The update failed: {e}")
            return
        if self._cancelled:
            import shutil

            shutil.rmtree(result.staging_dir, ignore_errors=True)
            return
        self.prepared.emit(result)
