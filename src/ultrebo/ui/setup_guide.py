# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""First-run guide. On a Mac it walks through the three permissions and hides itself when done."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import permissions

LABELS = {
    "accessibility": (
        "Accessibility",
        "Lets Ultrebo click and press keys for you.",
    ),
    "input_monitoring": (
        "Input Monitoring",
        "Lets Ultrebo record your clicks and keys, and hear the F8 / F9 hotkeys.",
    ),
    "screen_recording": (
        "Screen Recording",
        "Lets Ultrebo look at the screen to find images and text. Optional if you only use clicks and keys.",
    ),
}
OPTIONAL = {"screen_recording"}


class SetupCard(QFrame):
    """Shows what still needs switching on, or a short "Ready" note."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("card", True)
        self._layout = QVBoxLayout(self)
        self._rows: dict[str, tuple[QLabel, QPushButton, QWidget]] = {}
        self._title = QLabel()
        self._title.setProperty("subheading", True)
        self._layout.addWidget(self._title)
        self._note = QLabel()
        self._note.setWordWrap(True)
        self._note.setProperty("muted", True)
        self._layout.addWidget(self._note)

        for key, (name, why) in LABELS.items():
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 2, 0, 2)
            text = QLabel()
            text.setWordWrap(True)
            button = QPushButton("Open settings")
            button.clicked.connect(lambda _=False, k=key: permissions.open_pane(k))
            h.addWidget(text, 1)
            h.addWidget(button)
            self._layout.addWidget(row)
            self._rows[key] = (text, button, row)
            row.setVisible(False)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1500)
        self.refresh()

    def refresh(self) -> None:
        status = permissions.check_permissions()
        if not status:  # Windows / Linux
            self._title.setText("Ready")
            self._note.setText(
                "Nothing to set up. If a game ignores Ultrebo's clicks, right-click Ultrebo and choose "
                "Run as administrator: Windows blocks input into programs running at a higher level."
            )
            return
        missing = [k for k, v in status.items() if v is False]
        required_missing = [k for k in missing if k not in OPTIONAL]
        if not missing:
            self._title.setText("Ready")
            self._note.setText("All the permissions Ultrebo needs are on.")
        else:
            self._title.setText("Get started" if required_missing else "Almost ready")
            self._note.setText(
                "macOS asks for these before an app may control or watch your computer. Click Open settings, "
                "switch Ultrebo on in the list, then come back (you may need to restart Ultrebo). This card "
                "goes away once they are on."
            )
        for key, (text, _button, row) in self._rows.items():
            name, why = LABELS[key]
            state = status.get(key)
            row.setVisible(state is False)
            text.setText(f"<b>{name}</b>{' (optional)' if key in OPTIONAL else ''}<br>{why}")
