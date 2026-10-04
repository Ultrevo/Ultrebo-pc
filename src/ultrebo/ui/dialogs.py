# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""About and Settings dialogs."""
from __future__ import annotations

import webbrowser

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .. import DISCORD, REPO, WEBSITE, __version__
from ..inputs import validate_key_spec
from ..store import Settings


def _label(text: str, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if muted:
        label.setProperty("muted", True)
    return label


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("About Ultrebo")
        self.setMinimumWidth(480)
        v = QVBoxLayout(self)
        title = QLabel(f"Ultrebo {__version__}")
        title.setProperty("heading", True)
        v.addWidget(title)
        v.addWidget(_label(
            "Records and replays mouse and keyboard input, and can react to images and text on screen. "
            "Your macros and screenshots never leave your computer."
        ))
        v.addWidget(_label(
            "The only network use is an optional check on GitHub for a newer version. Text recognition runs "
            "offline on your computer.", muted=True,
        ))
        v.addWidget(_label(
            "Recording captures every key you press and every click until you stop it, so don't type "
            "passwords while recording.", muted=True,
        ))
        v.addWidget(_label(
            "Responsible use: many games forbid automation in their terms of service and may suspend accounts "
            "that use it. You are responsible for how you use this app.", muted=True,
        ))
        row = QHBoxLayout()
        for text, url in (("Website", WEBSITE), ("Discord", DISCORD), ("Source code", f"https://github.com/{REPO}")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
            row.addWidget(b)
        v.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._settings = settings
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.start_key = QLineEdit(settings.start_stop_hotkey)
        self.record_key = QLineEdit(settings.record_hotkey)
        form.addRow("Start / stop macro", self.start_key)
        form.addRow("Start / stop recording", self.record_key)
        v.addLayout(form)
        v.addWidget(_label(
            "These hotkeys work even while a game has focus, and are not recorded. Examples: f8, ctrl+f9. "
            "Use keys the game doesn't need.", muted=True,
        ))
        self.updates = QCheckBox("Check for updates on launch")
        self.updates.setChecked(settings.check_updates)
        v.addWidget(self.updates)
        v.addWidget(_label("Sends only a request to GitHub to see whether a newer release exists.", muted=True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def _save(self) -> None:
        start, record = self.start_key.text().strip(), self.record_key.text().strip()
        for label, spec in (("Start / stop macro", start), ("Start / stop recording", record)):
            error = validate_key_spec(spec)
            if error:
                QMessageBox.warning(self, "Ultrebo", f"{label}: {error}")
                return
        if start.lower() == record.lower():
            QMessageBox.warning(self, "Ultrebo", "The two hotkeys must be different.")
            return
        self._settings.start_stop_hotkey = start.lower()
        self._settings.record_hotkey = record.lower()
        self._settings.check_updates = self.updates.isChecked()
        self.accept()
