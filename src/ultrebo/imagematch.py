# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Template matching (normalised cross-correlation) with OpenCV."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass(frozen=True)
class ImageMatch:
    #: Centre of the match, in the pixel coordinates of the frame that was searched.
    x: int
    y: int
    score: float


def to_gray(image_bgr: np.ndarray) -> np.ndarray:
    if image_bgr.ndim == 2:
        return image_bgr
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)


def find_template(frame_gray: np.ndarray, template_gray: np.ndarray, threshold: float) -> ImageMatch | None:
    """Best match of `template_gray` inside `frame_gray`, or None when below `threshold`."""
    th, tw = template_gray.shape[:2]
    fh, fw = frame_gray.shape[:2]
    if th > fh or tw > fw or th < 2 or tw < 2:
        return None

    scale = 1.0
    frame, template = frame_gray, template_gray
    if min(th, tw) >= 24:
        # Matching at half size is about four times faster and just as reliable for sizeable targets.
        scale = 0.5
        frame = cv2.resize(frame_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        template = cv2.resize(template_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if template.shape[0] > frame.shape[0] or template.shape[1] > frame.shape[1]:
            return None

    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    if not np.isfinite(max_val) or max_val < threshold:
        return None
    cx = int((max_loc[0] + template.shape[1] / 2.0) / scale)
    cy = int((max_loc[1] + template.shape[0] / 2.0) / scale)
    return ImageMatch(cx, cy, float(max_val))


class TemplateCache:
    """Loads template images from disk once and keeps them (reloading if the file changes)."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._cache: dict[tuple[str, float], np.ndarray] = {}

    def path(self, name: str) -> Path:
        return self.folder / name

    def load(self, name: str) -> np.ndarray | None:
        path = self.path(name)
        try:
            key = (str(path), path.stat().st_mtime)
        except OSError:
            return None
        if key not in self._cache:
            data = np.fromfile(str(path), dtype=np.uint8)  # also works for non-ASCII paths on Windows
            image = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if image is None:
                return None
            self._cache[key] = to_gray(image)
        return self._cache[key]
