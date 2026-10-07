# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Starts the application: wires the real screen, input and text reader to the window."""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, selfupdate, updater
from .hotkeys import HotkeyManager
from .notify import Notifier
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
    notifier = Notifier(lambda: store.settings.webhook_url, on_problem=lambda text: bridge.status.emit(f"Discord: {text}"))
    runner = Runner(
        input_backend, screen, ocr, store.templates_dir,
        on_status=bridge.status.emit, on_state=bridge.state.emit, on_error=bridge.error.emit, notifier=notifier,
    )
    ctx = AppContext(store=store, screen=screen, runner=runner)
    window = MainWindow(ctx, bridge, hotkeys)
    return window, bridge


def selftest(report: Path | None = None) -> int:
    """`Ultrebo --selftest [report-file]`: checks the bundled libraries work (used by the build to verify each package).

    The Windows app has no console, so the result (or the error) is also written to `report` when one is given.
    """
    import traceback

    def say(text: str) -> None:
        print(text)
        if report is not None:
            with open(report, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    try:
        return _selftest(say)
    except Exception:  # noqa: BLE001
        say("selftest: crashed\n" + traceback.format_exc())
        return 1


def _selftest(say) -> int:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)  # noqa: F841 - also checks Qt starts
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from . import textmatch
    from .imagematch import find_template, to_gray

    # Pillow's built-in font, so the check doesn't depend on fonts installed on the computer running it.
    picture = Image.new("RGB", (640, 220), (40, 170, 80))
    ImageDraw.Draw(picture).text((320, 110), "I'm here", fill=(255, 255, 255), font=ImageFont.load_default(size=72), anchor="mm")
    bgr = np.ascontiguousarray(np.asarray(picture)[:, :, ::-1])
    drawn = int((np.abs(bgr.astype(int) - bgr[0, 0].astype(int)).sum(axis=2) > 60).sum())

    lines = RapidOcrEngine().read(bgr)
    text_ok = textmatch.find(lines, "I'm here", 0.7) is not None
    patch = bgr[60:160, 150:450].copy()
    image_ok = find_template(to_gray(bgr), to_gray(patch), 0.9) is not None
    from . import winkeys, winmouse

    say(f"selftest: text={'ok' if text_ok else 'FAILED'} image={'ok' if image_ok else 'FAILED'} cv2={cv2.__version__} drawn={drawn} ocr={[[w.text for w in line] for line in lines]} mouse={winmouse.probe()} keys={winkeys.probe()}")
    return 0 if (text_ok and image_ok and drawn > 500) else 1


def check_update_cli(report: Path | None) -> int:
    """`Ultrebo --check-update [report-file]`: asks GitHub for the newest release the way the app does, so the build
    can prove the packaged app can reach GitHub and pick the right download. Pretends to be an ancient version."""
    def say(text: str) -> None:
        print(text)
        if report is not None:
            with open(report, "a", encoding="utf-8") as f:
                f.write(text + "\n")

    result = updater.check_detailed("0.0.1")
    if result.error:
        say(f"check-update: FAILED {result.error}")
        return 1
    if result.update is None:
        say(f"check-update: FAILED newest release {result.latest} was not seen as newer than 0.0.1")
        return 1
    # Releases before v0.1.3 have no checksum file next to the zip, so a missing download is reported, not a failure.
    asset = result.update.asset.name if result.update.asset else "none"
    say(f"check-update: ok latest={result.latest} download={asset}")
    return 0


def update_selftest_cli(args: list[str]) -> int:
    """`Ultrebo --update-selftest <installed folder> <staging folder>`: does what "Update now" does after the download.

    The staging folder holds a ready-to-install copy in `Ultrebo/`. This starts the helper that swaps it into the
    installed folder and reopens Ultrebo, then quits the way the real update does, so the build can prove the
    whole hand-over works on a real Windows machine. Only used by the build."""
    if len(args) != 2:
        print("usage: --update-selftest <installed folder> <staging folder>")
        return 2
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    installed, staging = Path(args[0]), Path(args[1])
    hotkeys = HotkeyManager()
    try:
        hotkeys.set_bindings({"f8": lambda: None})  # the real app has keyboard hooks running when it quits
    except Exception as e:  # noqa: BLE001
        print(f"update-selftest: hotkeys unavailable here ({e})")
    selfupdate.apply(selfupdate.PreparedUpdate("windows", staging / "Ultrebo", staging, installed))
    print("update-selftest: helper started, quitting")

    def finish() -> None:
        hotkeys.stop()
        app.quit()

    QTimer.singleShot(150, finish)
    code = app.exec()
    os._exit(code)  # like the real update: end at once, so nothing can keep the old files in use


def _log_update_check(result) -> None:
    """Keep the last automatic check in a small file, so a silent failure can be looked at afterwards."""
    try:
        import time

        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  you have {__version__}  newest {result.latest}  "
        line += f"error: {result.error}" if result.error else ("update available" if result.update else "up to date")
        (data_dir() / "update-check.log").write_text(line + "\n", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _install_error_log(bridge) -> None:
    """Write any error the program doesn't expect to `error.log` in the data folder and say so in the status bar.

    The Windows app has no console, so without this a failure inside a button or dialog would vanish without a trace.
    """
    def record(kind, error, trace) -> None:
        text = "".join(traceback.format_exception(kind, error, trace))
        try:
            with open(data_dir() / "error.log", "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')}  Ultrebo {__version__}\n{text}\n")
        except Exception:  # noqa: BLE001
            pass
        try:
            bridge.status.emit("Something went wrong - details are in error.log in the Ultrebo data folder")
        except Exception:  # noqa: BLE001
            pass
        try:
            sys.__excepthook__(kind, error, trace)
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = record
    threading.excepthook = lambda args: record(args.exc_type, args.exc_value, args.exc_traceback)


def main() -> int:
    if "--check-update" in sys.argv:
        rest = sys.argv[sys.argv.index("--check-update") + 1:]
        return check_update_cli(Path(rest[0]) if rest else None)
    if "--update-selftest" in sys.argv:
        return update_selftest_cli(sys.argv[sys.argv.index("--update-selftest") + 1:])
    if "--selftest" in sys.argv:
        rest = sys.argv[sys.argv.index("--selftest") + 1:]
        return selftest(Path(rest[0]) if rest else None)
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
    screen = MssScreen()
    screen.set_monitor(store.settings.monitor)
    window, bridge = build_window(store, screen, input_backend, RapidOcrEngine(), HotkeyManager())
    _install_error_log(bridge)
    window.show()

    problem = selfupdate.last_update_problem()
    if problem:
        QTimer.singleShot(600, lambda: QMessageBox.warning(window, "Ultrebo", problem))

    if store.settings.check_updates:
        def look() -> None:
            result = updater.check_detailed(__version__)
            _log_update_check(result)
            if result.update is not None:
                bridge.update_found.emit(result.update)

        threading.Thread(target=look, daemon=True, name="ultrebo-update-check").start()

    threading.Thread(target=selfupdate.clean_old_leftovers, daemon=True, name="ultrebo-clean-temp").start()

    code = app.exec()
    if window.updating:
        # The update helper is waiting for this program to end so it can replace its files. Ending the usual way
        # can hang on a background library, so end right now (everything is already saved).
        os._exit(code)
    return code
