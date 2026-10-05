# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Sends a screenshot to a Discord webhook when a step or rule that asked for it finds its image or text.

The webhook address is a secret (anyone who has it can post in the channel), so it lives only in this
computer's settings file: it is never saved in a macro or a shared rule pack. Sending happens on a
background thread, so a slow or unreachable Discord never holds up the macro, and each step may send at
most once every few seconds so a rule that keeps matching can't flood the channel.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Callable

import cv2
import numpy as np

from . import REPO, __version__

WEBHOOK_PATTERN = re.compile(
    r"https://(?:(?:ptb|canary)\.)?(?:discord|discordapp)\.com/api(?:/v\d+)?/webhooks/\d{5,25}/[A-Za-z0-9_\-]{20,200}"
)
#: One step sends at most one screenshot per this many seconds.
MIN_GAP_S = 5.0
#: Pictures waiting to be sent; more than this are dropped rather than piling up.
MAX_WAITING = 4
MAX_SIDE = 2560
USER_AGENT = f"DiscordBot (https://github.com/{REPO}, {__version__})"

Sender = Callable[[str, str, "bytes | None"], "str | None"]


def is_valid_webhook(url: str) -> bool:
    """True for an address that looks like a Discord webhook. Anything else is refused, so the app never
    posts a screenshot to some other website because of a mistyped or pasted-in address."""
    return bool(WEBHOOK_PATTERN.fullmatch((url or "").strip()))


def clean_text(text: str, limit: int = 200) -> str:
    """Make step and macro names safe to put in a message: one line, no odd characters, not too long."""
    flat = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text)).strip()
    return flat[:limit]


def encode_screenshot(image: np.ndarray) -> bytes:
    """A JPEG of the screen, shrunk if it is very large, so it is small enough for Discord and quick to send."""
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("could not encode the screenshot")
    return encoded.tobytes()


def build_body(message: str, jpeg: bytes | None) -> tuple[bytes, str]:
    """The request body (multipart/form-data) and its Content-Type header."""
    boundary = "ultrebo" + uuid.uuid4().hex
    # allowed_mentions with no parse list means a name like "@everyone" in a step title can't ping anyone.
    payload = json.dumps({"content": clean_text(message, 1900), "allowed_mentions": {"parse": []}})
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n{payload}\r\n".encode("utf-8")
    ]
    if jpeg is not None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="screenshot.jpg"\r\n'
            "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + jpeg + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post(url: str, message: str, jpeg: bytes | None, timeout: float = 20.0) -> str | None:
    """Send one message (with a screenshot when `jpeg` is given). Returns None on success, or what went wrong."""
    if not is_valid_webhook(url):
        return "That isn't a Discord webhook address."
    from .updater import ssl_context

    body, content_type = build_body(message, jpeg)
    request = urllib.request.Request(
        url.strip(), data=body, method="POST", headers={"Content-Type": content_type, "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            response.read(1024)
        return None
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            return "Discord says this webhook doesn't exist any more. Make a new one and paste it in Settings."
        if e.code == 429:
            return "Discord asked Ultrebo to slow down, so a screenshot was skipped."
        if e.code == 413:
            return "The screenshot was too big for Discord."
        return f"Discord answered with error {e.code}."
    except Exception as e:  # noqa: BLE001 - offline, timeouts, certificates, ...
        return f"Couldn't reach Discord ({type(e).__name__})."


class Notifier:
    """Queues screenshots and sends them one at a time on a background thread."""

    def __init__(
        self,
        get_url: Callable[[], str],
        on_problem: Callable[[str], None] | None = None,
        sender: Sender = post,
        clock: Callable[[], float] = time.monotonic,
        min_gap_s: float = MIN_GAP_S,
        pause_s: float = 1.0,
    ):
        self._get_url = get_url
        self._on_problem = on_problem or (lambda text: None)
        self._sender = sender
        self._clock = clock
        self._min_gap_s = min_gap_s
        self._pause_s = pause_s
        self._last: dict[str, float] = {}
        self._queue: queue.Queue = queue.Queue(maxsize=MAX_WAITING)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def configured(self) -> bool:
        return is_valid_webhook(self._get_url())

    def send(self, key: str, message: str, image: np.ndarray | None) -> bool:
        """Queue a screenshot. `key` says which step it is for, so one step can't send too often.
        Returns False when nothing was queued (no webhook, too soon after the last one, or the queue is full)."""
        url = self._get_url().strip()
        if not is_valid_webhook(url):
            return False
        now = self._clock()
        with self._lock:
            if now - self._last.get(key, -1e9) < self._min_gap_s:
                return False
            try:
                self._queue.put_nowait((url, message, image))
            except queue.Full:
                return False
            self._last[key] = now
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True, name="ultrebo-discord")
                self._worker.start()
        return True

    def wait_until_sent(self, timeout: float = 5.0) -> bool:
        """For tests: True once everything queued has been handled."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._queue.unfinished_tasks == 0:
                return True
            time.sleep(0.01)
        return False

    def _run(self) -> None:
        while True:
            try:
                url, message, image = self._queue.get(timeout=30)
            except queue.Empty:
                with self._lock:
                    if self._queue.empty():
                        self._worker = None  # idle: the next send starts a new thread
                        return
                continue
            try:
                jpeg = encode_screenshot(image) if image is not None else None
                problem = self._sender(url, message, jpeg)
                if problem:
                    self._on_problem(problem)
            except Exception as e:  # noqa: BLE001 - never let a bad send stop later ones
                self._on_problem(f"Couldn't send to Discord ({type(e).__name__}).")
            finally:
                self._queue.task_done()
            time.sleep(self._pause_s)  # Discord allows only a few messages every few seconds
