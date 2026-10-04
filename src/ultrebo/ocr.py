# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Offline text recognition (RapidOCR / ONNX Runtime). Nothing leaves the computer."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .textmatch import OcrWord


class OcrEngine(Protocol):
    def read(self, image_bgr: np.ndarray) -> list[list[OcrWord]]:
        """Words found in the image, grouped by line."""


def split_line(text: str, left: int, top: int, right: int, bottom: int) -> list[OcrWord]:
    """Split one recognised line into words, estimating each word's box by character position."""
    total = len(text)
    if total == 0:
        return []
    width = right - left
    words: list[OcrWord] = []
    index = 0
    for chunk in text.split():
        start = text.index(chunk, index)
        end = start + len(chunk)
        index = end
        words.append(
            OcrWord(
                chunk,
                left + int(width * start / total),
                top,
                left + int(width * end / total),
                bottom,
            )
        )
    return words


@dataclass
class _Row:
    top: int
    bottom: int
    right: int
    boxes: list


def group_into_lines(boxes: list[tuple[str, int, int, int, int]]) -> list[list[OcrWord]]:
    """Join recognised text boxes that sit side by side on the same row into one line of words.

    The recogniser often reports a spaced-out phrase such as a button's "I'm   here" as two boxes. Joining
    them lets a two-word target match. `boxes` are (text, left, top, right, bottom).
    """
    rows: list[_Row] = []
    for box in sorted(boxes, key=lambda b: b[1]):
        _text, left, top, right, bottom = box
        height = max(bottom - top, 1)
        for row in rows:
            overlap = min(bottom, row.bottom) - max(top, row.top)
            smaller = max(min(height, row.bottom - row.top), 1)
            gap = left - row.right
            if overlap >= 0.5 * smaller and -height <= gap <= 3 * max(height, row.bottom - row.top):
                row.boxes.append(box)
                row.top, row.bottom, row.right = min(row.top, top), max(row.bottom, bottom), max(row.right, right)
                break
        else:
            rows.append(_Row(top, bottom, right, [box]))
    lines: list[list[OcrWord]] = []
    for row in rows:
        words: list[OcrWord] = []
        for text, left, top, right, bottom in sorted(row.boxes, key=lambda b: b[1]):
            words.extend(split_line(text, left, top, right, bottom))
        if words:
            lines.append(words)
    return lines


class RapidOcrEngine:
    """Loads the recognition model on first use (about a second), then reuses it."""

    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.Lock()

    def read(self, image_bgr: np.ndarray) -> list[list[OcrWord]]:
        with self._lock:
            if self._engine is None:
                from rapidocr_onnxruntime import RapidOCR

                self._engine = RapidOCR()
            result, _ = self._engine(image_bgr)
        boxes: list[tuple[str, int, int, int, int]] = []
        for item in result or []:
            box, text = item[0], str(item[1])
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            boxes.append((text, int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))))
        return group_into_lines(boxes)
