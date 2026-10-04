# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Qt side of choosing a monitor: find the Qt screen for a monitor number, and flash numbers to identify them."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QScreen
from PySide6.QtWidgets import QWidget

from ..monitors import QtScreenInfo, match_screens
from ..screen import MonitorInfo


def qt_screen_for(monitors: list[MonitorInfo], number: int) -> QScreen | None:
    screens = QGuiApplication.screens()
    infos = [
        QtScreenInfo(s.geometry().x(), s.geometry().y(), s.geometry().width(), s.geometry().height(), s.devicePixelRatio())
        for s in screens
    ]
    index = match_screens(monitors, infos).get(number)
    return screens[index] if index is not None else None


class _NumberBadge(QWidget):
    def __init__(self, number: int, screen: QScreen):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.number = number
        self.setScreen(screen)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        size = 220
        geo = screen.geometry()
        self.setGeometry(QRect(geo.x() + (geo.width() - size) // 2, geo.y() + (geo.height() - size) // 2, size, size))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(11, 18, 32, 230))
        p.setPen(QColor("#4fc3f7"))
        p.drawRoundedRect(self.rect().adjusted(3, 3, -3, -3), 24, 24)
        font = QFont()
        font.setPixelSize(130)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, str(self.number))


class MonitorIdentifier:
    """Shows a big number in the middle of every monitor for a couple of seconds."""

    def __init__(self) -> None:
        self._badges: list[_NumberBadge] = []

    def show(self, monitors: list[MonitorInfo], seconds: float = 2.5) -> None:
        self.clear()
        for mon in monitors:
            screen = qt_screen_for(monitors, mon.index)
            if screen is None:
                continue
            badge = _NumberBadge(mon.index, screen)
            badge.show()
            self._badges.append(badge)
        QTimer.singleShot(int(seconds * 1000), self.clear)

    def clear(self) -> None:
        for b in self._badges:
            b.close()
        self._badges = []
