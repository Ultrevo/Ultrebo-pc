# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from ultrebo.monitors import QtScreenInfo, match_screens
from ultrebo.screen import MonitorInfo, MssScreen
from ultrebo.store import Settings
from ultrebo.ui.dialogs import SettingsDialog


def test_match_windows_scaled_monitor():
    mons = [MonitorInfo(1, 0, 0, 2560, 1440), MonitorInfo(2, 2560, 0, 1920, 1080)]
    screens = [QtScreenInfo(0, 0, 1707, 960, 1.5), QtScreenInfo(1707, 0, 1920, 1080, 1.0)]
    assert match_screens(mons, screens) == {1: 0, 2: 1}


def test_match_mac_points():
    mons = [MonitorInfo(1, 0, 0, 1440, 900), MonitorInfo(2, 1440, 0, 1920, 1080)]
    screens = [QtScreenInfo(1440, 0, 1920, 1080, 1.0), QtScreenInfo(0, 0, 1440, 900, 2.0)]
    assert match_screens(mons, screens) == {1: 1, 2: 0}


def test_identical_monitors_use_position():
    mons = [MonitorInfo(1, 0, 0, 1920, 1080), MonitorInfo(2, 1920, 0, 1920, 1080)]
    screens = [QtScreenInfo(1920, 0, 1920, 1080, 1.0), QtScreenInfo(0, 0, 1920, 1080, 1.0)]
    assert match_screens(mons, screens) == {1: 1, 2: 0}


def test_unmatched_monitor_is_left_out():
    assert match_screens([MonitorInfo(1, 0, 0, 800, 600)], [QtScreenInfo(0, 0, 1920, 1080, 1.0)]) == {}


class FakeSct:
    monitors = [
        {"left": 0, "top": 0, "width": 4480, "height": 1440},
        {"left": 0, "top": 0, "width": 2560, "height": 1440},
        {"left": 2560, "top": 0, "width": 1920, "height": 1080},
    ]


def _screen():
    s = MssScreen()
    s._local.sct = FakeSct()
    return s


def test_list_and_choose_monitor():
    s = _screen()
    assert [m.index for m in s.list_monitors()] == [1, 2]
    s.set_monitor(2)
    assert s.monitor_index == 2
    s.set_monitor(7)  # unplugged
    assert s.monitor_index == 1
    s.set_monitor(0)
    assert s.monitor_index == 1


def test_settings_remember_monitor_and_ignore_junk():
    s = Settings()
    s.monitor = 2
    assert Settings.from_dict(s.to_dict()).monitor == 2
    assert Settings.from_dict({"monitor": "abc"}).monitor == 1
    assert Settings.from_dict({"monitor": -3}).monitor == 1
    assert Settings.from_dict({}).monitor == 1


def test_settings_dialog_saves_monitor(qapp):
    settings = Settings()
    dialog = SettingsDialog(settings, None, _screen())
    assert dialog.monitor_box.count() == 2
    dialog.monitor_box.setCurrentIndex(1)
    dialog._save()
    assert settings.monitor == 2
    dialog.deleteLater()


def test_settings_dialog_without_monitors(qapp):
    class Plain:  # a screen source that can't choose
        pass

    settings = Settings()
    dialog = SettingsDialog(settings, None, Plain())
    assert dialog.monitor_box is None
    dialog._save()
    assert settings.monitor == 1
