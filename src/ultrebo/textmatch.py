# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Finds typed text among OCR words.

Comparison ignores case, spaces and punctuation, and tolerates small OCR mistakes: `threshold`
is the minimum similarity (1.0 = identical).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OcrWord:
    text: str
    left: int
    top: int
    right: int
    bottom: int


@dataclass(frozen=True)
class TextMatch:
    x: int
    y: int
    score: float


def normalize(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[len(b)]


def similarity(a: str, b: str) -> float:
    longest = max(len(a), len(b))
    if longest == 0:
        return 1.0
    return 1.0 - _levenshtein(a, b) / longest


def find(lines: list[list[OcrWord]], target: str, threshold: float) -> TextMatch | None:
    """Best match across all lines of OCR words, as the centre of the matched words."""
    wanted = normalize(target)
    if not wanted:
        return None
    word_count = len(re.split(r"\s+", target.strip()))
    best: TextMatch | None = None
    for line in lines:
        # OCR sometimes splits or joins words, so also try windows one word shorter/longer.
        for size in range(max(1, word_count - 1), word_count + 2):
            if size > len(line):
                continue
            for start in range(0, len(line) - size + 1):
                window = line[start:start + size]
                score = similarity(wanted, normalize("".join(w.text for w in window)))
                if score >= threshold and (best is None or score > best.score):
                    left = min(w.left for w in window)
                    right = max(w.right for w in window)
                    top = min(w.top for w in window)
                    bottom = max(w.bottom for w in window)
                    best = TextMatch((left + right) // 2, (top + bottom) // 2, score)
    return best
