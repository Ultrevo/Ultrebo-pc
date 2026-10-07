# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Fill a Qt table with many rows quickly.

A table whose columns are sized to their contents works out the column widths again after every single cell that is
added, so filling it row by row gets slower and slower: a few hundred steps took 20 seconds. Switching the width
rules off while filling, and back on once at the end, makes it work out the widths a single time.
"""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtWidgets import QHeaderView, QTableWidget


@contextmanager
def fast_fill(table: QTableWidget):
    header = table.horizontalHeader()
    modes = [header.sectionResizeMode(i) for i in range(table.columnCount())]
    table.setUpdatesEnabled(False)
    was_blocked = table.blockSignals(True)
    for i in range(len(modes)):
        header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
    try:
        yield
    finally:
        for i, mode in enumerate(modes):
            header.setSectionResizeMode(i, mode)
        table.blockSignals(was_blocked)
        table.setUpdatesEnabled(True)
