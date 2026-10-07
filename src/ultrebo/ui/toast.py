# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""A small notice that appears over everything for a moment, without taking the keyboard from the game.

The hotkeys (F8 to start and stop, F9 to record) are used while a game is in front, where Ultrebo's own window isn't
visible. Without this, pressing F8 and having it refuse to start looked exactly like the key not working at all.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel


class Toast(QLabel):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)
        self.setMaximumWidth(520)
        self.setStyleSheet(
            "QLabel { background: #1c2230; color: #f2f5fa; border: 1px solid #4cc2ff; border-radius: 10px; "
            "padding: 12px 18px; font-size: 14px; }"
        )
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, ms: int = 2800) -> None:
        self.setText(text)
        self.adjustSize()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.bottom() - self.height() - 60)
        self.show()
        self.raise_()
        self._timer.start(ms)
