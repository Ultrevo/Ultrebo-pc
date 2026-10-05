# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""About and Settings dialogs."""
from __future__ import annotations

import threading
import webbrowser

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from .. import DISCORD, DONATE_ETH, REPO, WEBSITE, __version__
from ..inputs import validate_key_spec
from ..notify import is_valid_webhook, post
from ..store import Settings
from .monitor_view import MonitorIdentifier


def _label(text: str, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    if muted:
        label.setProperty("muted", True)
    return label


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, on_check=None):
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
        v.addWidget(_label(
            "Ultrebo is free. If it helps you, you can optionally support it with crypto on the Ethereum network "
            "(ETH, or USDT/USDC on Ethereum):", muted=True,
        ))
        address = QLineEdit(DONATE_ETH)
        address.setReadOnly(True)
        v.addWidget(address)
        if on_check is not None:
            check = QPushButton("Check for updates now")
            check.clicked.connect(lambda: (self.accept(), on_check()))
            v.addWidget(check)
        row = QHBoxLayout()
        copy = QPushButton("Copy ETH address")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(DONATE_ETH), copy.setText("Copied")))
        row.addWidget(copy)
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
    _test_done = Signal(str)

    def __init__(self, settings: Settings, parent: QWidget | None = None, screen=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(460)
        self._settings = settings
        self._monitors = screen.list_monitors() if screen is not None and hasattr(screen, "list_monitors") else []
        self._identifier = MonitorIdentifier()
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
        if self._monitors:
            self.monitor_box = QComboBox()
            for m in self._monitors:
                self.monitor_box.addItem(f"Monitor {m.index}  ({m.width} x {m.height})", m.index)
            at = self.monitor_box.findData(settings.monitor)
            self.monitor_box.setCurrentIndex(at if at >= 0 else 0)
            row = QHBoxLayout()
            row.addWidget(self.monitor_box, 1)
            identify = QPushButton("Show numbers")
            identify.setToolTip("Shows each monitor's number on that monitor for a moment")
            identify.clicked.connect(lambda: self._identifier.show(self._monitors))
            row.addWidget(identify)
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            form.addRow("Monitor to watch", holder)
            v.addWidget(_label(
                "Image and text steps look for things on this monitor, and \"pick from screen\" shows it. "
                "Clicks use the screen position you recorded, so keep the game on this monitor.", muted=True,
            ))
        else:
            self.monitor_box = None
        self.webhook = QLineEdit(settings.webhook_url)
        self.webhook.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)  # it is a secret: hidden unless being typed
        self.webhook.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.webhook_test = QPushButton("Send test")
        self.webhook_test.clicked.connect(self._send_test)
        hook_row = QHBoxLayout()
        hook_row.setContentsMargins(0, 0, 0, 0)
        hook_row.addWidget(self.webhook, 1)
        hook_row.addWidget(self.webhook_test)
        hook_holder = QWidget()
        hook_holder.setLayout(hook_row)
        form.addRow("Discord webhook", hook_holder)
        v.addWidget(_label(
            "Steps and rules with \"Send a screenshot to Discord\" ticked post a screenshot of the watched monitor here "
            "when they are found. In Discord: channel settings > Integrations > Webhooks > New Webhook > Copy URL. "
            "Anyone who has this address can post in that channel, so keep it private. It is saved only on this computer "
            "and is never included in a shared rules file. Leave it empty to turn this off.", muted=True,
        ))
        self._test_done.connect(self._test_finished)
        self.updates = QCheckBox("Check for updates on launch")
        self.updates.setChecked(settings.check_updates)
        v.addWidget(self.updates)
        v.addWidget(_label("Sends only a request to GitHub to see whether a newer release exists.", muted=True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def done(self, result: int) -> None:
        self._identifier.clear()
        super().done(result)

    def _send_test(self) -> None:
        url = self.webhook.text().strip()
        if not is_valid_webhook(url):
            QMessageBox.warning(self, "Ultrebo", "That doesn't look like a Discord webhook address. It starts with https://discord.com/api/webhooks/")
            return
        self.webhook_test.setEnabled(False)
        self.webhook_test.setText("Sending...")
        threading.Thread(
            target=lambda: self._test_done.emit(post(url, "Ultrebo is connected. Screenshots will appear here.", None) or ""),
            daemon=True, name="ultrebo-discord-test",
        ).start()

    def _test_finished(self, problem: str) -> None:
        self.webhook_test.setEnabled(True)
        self.webhook_test.setText("Send test")
        if problem:
            QMessageBox.warning(self, "Ultrebo", problem)
        else:
            QMessageBox.information(self, "Ultrebo", "Sent. Check your Discord channel for the message.")

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
        hook = self.webhook.text().strip()
        if hook and not is_valid_webhook(hook):
            QMessageBox.warning(
                self, "Ultrebo",
                "The Discord webhook doesn't look right. It should start with https://discord.com/api/webhooks/ "
                "(or leave it empty).",
            )
            return
        self._settings.start_stop_hotkey = start.lower()
        self._settings.record_hotkey = record.lower()
        self._settings.webhook_url = hook
        self._settings.check_updates = self.updates.isChecked()
        if self.monitor_box is not None:
            self._settings.monitor = int(self.monitor_box.currentData())
        self._identifier.clear()
        self.accept()
