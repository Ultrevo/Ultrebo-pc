# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Starts the application: wires the real screen, input and text reader to the window."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, updater
from .hotkeys import HotkeyManager
from .ocr import RapidOcrEngine
from .paths import data_dir
from .runner import Runner
from .screen import MssScreen
from .store import MacroStore
from .ui.context import AppContext
from .ui.main_window import Bridge, MainWindow
from .ui.theme import apply_theme


def asset_path(name: str) -> Path:
    """Locate a bundled file, both when running from source and when frozen by PyInstaller."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    for candidate in (base / "assets" / name, base / "ultrebo" / "assets" / name, Path(__file__).parent / "assets" / name):
        if candidate.exists():
            return candidate
    return Path(__file__).parent / "assets" / name


def build_window(store: MacroStore, screen, input_backend, ocr, hotkeys: HotkeyManager | None) -> tuple[MainWindow, Bridge]:
    bridge = Bridge()
    runner = Runner(
        input_backend, screen, ocr, store.templates_dir,
        on_status=bridge.status.emit, on_state=bridge.state.emit, on_error=bridge.error.emit,
    )
    ctx = AppContext(store=store, screen=screen, runner=runner)
    window = MainWindow(ctx, bridge, hotkeys)
    return window, bridge


def selftest() -> int:
    """`Ultrebo --selftest`: checks the bundled libraries work (used by the build to verify each package)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)  # noqa: F841 - Qt needs it to draw text
    import cv2
    import numpy as np
    from PySide6.QtGui import QColor, QFont, QImage, QPainter

    from . import textmatch
    from .imagematch import find_template, to_gray

    image = QImage(640, 220, QImage.Format.Format_RGB888)
    image.fill(QColor(40, 170, 80))
    painter = QPainter(image)
    painter.setPen(QColor("white"))
    font = QFont()
    font.setPixelSize(64)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(image.rect(), 0x84, "I'm here")  # centred
    painter.end()
    w, h = image.width(), image.height()
    rgb = np.frombuffer(image.constBits(), np.uint8).reshape(h, image.bytesPerLine())[:, : w * 3].reshape(h, w, 3)
    bgr = np.ascontiguousarray(rgb[:, :, ::-1])

    lines = RapidOcrEngine().read(bgr)
    text_ok = textmatch.find(lines, "I'm here", 0.7) is not None
    patch = bgr[60:160, 150:450].copy()
    image_ok = find_template(to_gray(bgr), to_gray(patch), 0.9) is not None
    print(f"selftest: text={'ok' if text_ok else 'FAILED'} image={'ok' if image_ok else 'FAILED'} cv2={cv2.__version__}")
    return 0 if (text_ok and image_ok) else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    app = QApplication(sys.argv)
    app.setApplicationName("Ultrebo")
    app.setApplicationVersion(__version__)
    icon = asset_path("icon.png")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    apply_theme(app)

    try:
        from .inputs import PynputInput

        input_backend = PynputInput()
    except Exception as e:  # noqa: BLE001
        QMessageBox.critical(
            None, "Ultrebo",
            f"Ultrebo could not get access to the mouse and keyboard:\n\n{e}\n\n"
            "On a Mac, switch on Accessibility and Input Monitoring for Ultrebo in System Settings > Privacy & Security.\n"
            "On Linux, Ultrebo needs an X11 session (Wayland is not supported).",
        )
        return 1

    store = MacroStore(data_dir())
    window, bridge = build_window(store, MssScreen(), input_backend, RapidOcrEngine(), HotkeyManager())
    window.show()

    if store.settings.check_updates:
        def look() -> None:
            update = updater.check(__version__)
            if update is not None:
                bridge.update_found.emit(update)

        threading.Thread(target=look, daemon=True, name="ultrebo-update-check").start()

    return app.exec()
