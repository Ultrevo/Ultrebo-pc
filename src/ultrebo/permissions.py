# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""macOS asks for three permissions before an app may control or watch the computer.

Windows needs none (the setup guide only explains how to run Ultrebo as administrator if a game
ignores its input). Checks here never raise: an unknown answer is None.
"""
from __future__ import annotations

import ctypes
import subprocess
import sys

IS_MAC = sys.platform == "darwin"

PANES = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
}


def _lib(path: str):
    return ctypes.cdll.LoadLibrary(path)


def _accessibility() -> bool | None:
    try:
        lib = _lib("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except Exception:  # noqa: BLE001
        return None


def _screen_recording() -> bool | None:
    try:
        lib = _lib("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        lib.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        return bool(lib.CGPreflightScreenCaptureAccess())
    except Exception:  # noqa: BLE001
        return None


def _input_monitoring() -> bool | None:
    try:
        lib = _lib("/System/Library/Frameworks/IOKit.framework/IOKit")
        lib.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        lib.IOHIDCheckAccess.restype = ctypes.c_uint32
        status = lib.IOHIDCheckAccess(1)  # kIOHIDRequestTypeListenEvent
        if status == 0:
            return True
        if status == 1:
            return False
        return None
    except Exception:  # noqa: BLE001
        return None


def check_permissions() -> dict[str, bool | None]:
    """Empty on Windows and Linux; on a Mac, {name: granted (True), denied (False) or unknown (None)}."""
    if not IS_MAC:
        return {}
    return {
        "accessibility": _accessibility(),
        "input_monitoring": _input_monitoring(),
        "screen_recording": _screen_recording(),
    }


def open_pane(name: str) -> None:
    if IS_MAC and name in PANES:
        subprocess.run(["open", PANES[name]], check=False)
