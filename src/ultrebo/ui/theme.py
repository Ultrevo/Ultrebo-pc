# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Dark theme that matches the phone app (blue crosshair on a dark background)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BACKGROUND = "#1e1e24"
SURFACE = "#26262e"
SURFACE_HIGH = "#30303a"
BORDER = "#3a3a46"
TEXT = "#eceff6"
MUTED = "#a2abbd"
ACCENT = "#4fc3f7"
ACCENT_TEXT = "#0b1220"
DANGER = "#ff5252"
OK = "#7bd88f"

STYLESHEET = f"""
QWidget {{ font-size: 13px; }}
QMainWindow, QDialog {{ background: {BACKGROUND}; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[heading="true"] {{ font-size: 18px; font-weight: 600; }}
QLabel[subheading="true"] {{ font-size: 14px; font-weight: 600; }}
QFrame[card="true"] {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton {{ background: {SURFACE_HIGH}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: #6b7385; }}
QPushButton:checked {{ background: #2f4b5a; border: 1px solid {ACCENT}; }}
QPushButton[kind="true"] {{ padding: 6px 4px; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: {ACCENT_TEXT}; border: none; font-weight: 600; padding: 8px 18px; }}
QPushButton[primary="true"]:hover {{ background: #7bd3f8; }}
QPushButton[danger="true"] {{ background: {DANGER}; color: white; border: none; font-weight: 600; padding: 8px 18px; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px; min-height: 20px; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QTableWidget, QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; outline: none; }}
QTableWidget::item, QListWidget::item {{ padding: 4px; }}
QTableWidget::item:selected, QListWidget::item:selected {{ background: #2f4b5a; color: {TEXT}; }}
QHeaderView::section {{ background: {SURFACE_HIGH}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 18px; color: {MUTED}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 10px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QStatusBar {{ background: {SURFACE}; }}
QToolTip {{ background: {SURFACE_HIGH}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_HIGH))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Button, QColor(SURFACE_HIGH))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#2f4b5a"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_HIGH))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Link, QColor(ACCENT))
    app.setPalette(p)
    app.setStyleSheet(STYLESHEET)
