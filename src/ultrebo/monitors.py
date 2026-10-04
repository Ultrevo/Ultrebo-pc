# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Matches the monitors the screen grabber numbers with the screens Qt knows about (to draw on the right one)."""
from __future__ import annotations

from typing import NamedTuple, Sequence

from .screen import MonitorInfo


class QtScreenInfo(NamedTuple):
    x: int
    y: int
    width: int
    height: int
    ratio: float  # device pixel ratio


def match_screens(monitors: Sequence[MonitorInfo], screens: Sequence[QtScreenInfo]) -> dict[int, int]:
    """Map each monitor's number to the index of the Qt screen showing it.

    The grabber measures in physical pixels on Windows and in points on a Mac, while Qt measures in
    points, so a screen matches when its size is the monitor's size either way. Position breaks ties
    (two identical monitors); otherwise the order is used.
    """
    result: dict[int, int] = {}
    used: set[int] = set()
    for mon in monitors:
        candidates = [
            i for i, s in enumerate(screens)
            if i not in used and (
                (s.width == mon.width and s.height == mon.height)
                or (round(s.width * s.ratio) == mon.width and round(s.height * s.ratio) == mon.height)
            )
        ]
        if not candidates:
            continue
        exact = [
            i for i in candidates
            if (screens[i].x, screens[i].y) == (mon.left, mon.top)
            or (round(screens[i].x * screens[i].ratio), round(screens[i].y * screens[i].ratio)) == (mon.left, mon.top)
        ]
        pick = (exact or candidates)[0]
        used.add(pick)
        result[mon.index] = pick
    return result
