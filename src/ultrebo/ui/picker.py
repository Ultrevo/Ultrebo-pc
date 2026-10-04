# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Full-screen overlay for picking a box (a picture to look for) or a single point on the screen.

The overlay shows a screenshot taken a moment earlier, so it never appears in the picture and the
game does not need to stay in front.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget


def ndarray_to_pixmap(frame_bgr: np.ndarray) -> QPixmap:
    h, w = frame_bgr.shape[:2]
    rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
    image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(image)


class PickerOverlay(QWidget):
    """mode "box": drag a rectangle. mode "point": click once. Esc cancels."""

    box_picked = Signal(int, int, int, int)  # x, y, width, height in screenshot pixels
    point_picked = Signal(int, int)  # x, y in screenshot pixels
    cancelled = Signal()

    def __init__(self, frame_bgr: np.ndarray, mode: str = "box", hint: str = ""):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.mode = mode
        self._frame_w, self._frame_h = frame_bgr.shape[1], frame_bgr.shape[0]
        self._pixmap = ndarray_to_pixmap(frame_bgr)
        self._hint = hint or ("Drag a box around what to look for. Esc to cancel." if mode == "box" else "Click the spot. Esc to cancel.")
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    # -- helpers
    def _to_pixels(self, p: QPoint) -> tuple[int, int]:
        sx = self._frame_w / max(self.width(), 1)
        sy = self._frame_h / max(self.height(), 1)
        return int(p.x() * sx), int(p.y() * sy)

    def _rect(self) -> QRect | None:
        if self._start is None or self._current is None:
            return None
        return QRect(self._start, self._current).normalized()

    # -- events
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        shade = QColor(0, 0, 0, 120)
        rect = self._rect()
        if rect is None:
            painter.fillRect(self.rect(), shade)
        else:
            path_regions = [
                QRect(0, 0, self.width(), rect.top()),
                QRect(0, rect.bottom() + 1, self.width(), self.height() - rect.bottom() - 1),
                QRect(0, rect.top(), rect.left(), rect.height()),
                QRect(rect.right() + 1, rect.top(), self.width() - rect.right() - 1, rect.height()),
            ]
            for r in path_regions:
                painter.fillRect(r, shade)
            painter.setPen(QPen(QColor("#4fc3f7"), 2))
            painter.drawRect(rect)
        painter.setPen(QColor("white"))
        painter.fillRect(QRect(0, 0, self.width(), 34), QColor(0, 0, 0, 170))
        painter.drawText(QRect(12, 0, self.width() - 24, 34), Qt.AlignmentFlag.AlignVCenter, self._hint)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._start = self._current = event.position().toPoint()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._start is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._current = event.position().toPoint()
        if self.mode == "point":
            x, y = self._to_pixels(self._current)
            self.close()
            self.point_picked.emit(x, y)
            return
        rect = self._rect()
        self.close()
        if rect is None or rect.width() < 6 or rect.height() < 6:
            self.cancelled.emit()  # a tap instead of a drag
            return
        x1, y1 = self._to_pixels(rect.topLeft())
        x2, y2 = self._to_pixels(rect.bottomRight())
        self.box_picked.emit(x1, y1, max(x2 - x1, 1), max(y2 - y1, 1))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()
