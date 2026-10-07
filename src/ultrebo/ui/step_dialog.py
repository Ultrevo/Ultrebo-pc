# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Dialog for creating or editing one step."""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..inputs import validate_key_spec
from ..model import Step, StepType, WatchAction
from .context import AppContext

KINDS = [
    (StepType.CLICK, "Click"),
    (StepType.DRAG, "Drag"),
    (StepType.SCROLL, "Scroll"),
    (StepType.KEY, "Key press"),
    (StepType.IMAGE, "Find image"),
    (StepType.TEXT, "Find text"),
]
DESCRIPTIONS = {
    StepType.CLICK: "Clicks one fixed spot on the screen.",
    StepType.DRAG: "Presses the mouse button at one spot, drags to another and lets go.",
    StepType.SCROLL: "Turns the mouse wheel.",
    StepType.KEY: "Presses a key or a combination such as ctrl+c.",
    StepType.IMAGE: "Looks for a picture you choose, wherever it appears on the screen.",
    StepType.TEXT: "Looks for words you type, wherever they appear on the screen.",
}
BUTTONS = ["left", "right", "middle"]


def spin(low: int, high: int, value: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
    return box


def muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("muted", True)
    return label


class StepDialog(QDialog):
    def __init__(
        self, ctx: AppContext, step: Step, parent: QWidget | None = None, is_new: bool = False, rule: bool = False,
        groups: list | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.rule = rule
        self._groups = groups or []
        noun = "rule" if rule else "step"
        self.setWindowTitle(f"New {noun}" if is_new else f"Edit {noun}")
        self.setMinimumWidth(560)
        self._step = copy.deepcopy(step)
        self._template = step.template_file
        self._region: list[int] | None = list(step.region) if step.region else None

        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        root.addWidget(scroll)

        # -- name and kind
        self.name = QLineEdit(step.name)
        self.name.setPlaceholderText("Name (optional)")
        layout.addWidget(self.name)

        layout.addWidget(self._heading("What it looks for" if rule else "What it does"))
        kinds = QHBoxLayout()
        self.kind_group = QButtonGroup(self)
        self.kind_group.setExclusive(True)
        self._kind_buttons: dict[StepType, QPushButton] = {}
        for i, (kind, label) in enumerate(KINDS):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("kind", True)
            self.kind_group.addButton(b, i)
            self._kind_buttons[kind] = b
            kinds.addWidget(b)
        layout.addLayout(kinds)
        if rule:  # a rule only ever watches for an image or text
            for kind, button in self._kind_buttons.items():
                button.setVisible(kind in (StepType.IMAGE, StepType.TEXT))
        self.description = muted("")
        layout.addWidget(self.description)

        # -- pages
        self.pages = QStackedWidget()
        self.pages.addWidget(self._click_page())
        self.pages.addWidget(self._drag_page())
        self.pages.addWidget(self._scroll_page())
        self.pages.addWidget(self._key_page())
        self.pages.addWidget(self._image_page())
        self.pages.addWidget(self._text_page())
        layout.addWidget(self.pages)

        # -- options for image/text
        self.finder_box = QWidget()
        fl = QVBoxLayout(self.finder_box)
        fl.setContentsMargins(0, 0, 0, 0)
        self.click_found = QCheckBox("Click it when found")
        fl.addWidget(self.click_found)
        self.notify = QCheckBox("Send a screenshot to Discord when found")
        self.notify.setToolTip(
            "Posts a screenshot of the watched monitor to your Discord webhook (set in Settings), at most once every "
            "few seconds for this step."
        )
        fl.addWidget(self.notify)
        self.restart_after = QCheckBox("Then start the macro over from the first step")
        self.restart_after.setToolTip(
            "When this is found (and clicked, if you left that on), the macro goes back to step 1 instead of carrying on "
            "to the next step. Only used in Sequence mode."
        )
        fl.addWidget(self.restart_after)
        form = QFormLayout()
        self.f_button = QComboBox()
        self.f_button.addItems(BUTTONS)
        self.f_double = QCheckBox("Double-click")
        form.addRow("Mouse button", self.f_button)
        form.addRow("", self.f_double)
        fl.addLayout(form)

        area = QHBoxLayout()
        self.region_label = QLabel()
        area.addWidget(self.region_label, 1)
        pick_area = QPushButton("Pick search area")
        pick_area.clicked.connect(self._pick_region)
        clear_area = QPushButton("Whole screen")
        clear_area.clicked.connect(self._clear_region)
        area.addWidget(pick_area)
        area.addWidget(clear_area)
        fl.addWidget(QLabel("Search area"))
        fl.addLayout(area)

        self.watch_group = QGroupBox("When it appears")
        wl = QVBoxLayout(self.watch_group)
        self.watch = QCheckBox("Always watching")  # on for rules; a plain step never watches
        self.watch.setChecked(rule)
        self.watch.setVisible(False)
        wl.addWidget(self.watch)
        wl.addWidget(muted(
            "Checked in the background for the whole run, even while the steps are running. If two rules "
            "are on screen at once, the one higher in the Rules list goes first."
        ))
        self.watch_options = QWidget()
        wo = QFormLayout(self.watch_options)
        wo.setContentsMargins(0, 0, 0, 0)
        self.on_seen = QComboBox()
        for action in WatchAction:
            self.on_seen.addItem(action.label, action.value)
        wo.addRow("Then", self.on_seen)
        self.nudge = QCheckBox("Move the mouse a little before clicking")
        self.nudge.setToolTip(
            "Glides the mouse to the target and wiggles it slightly first. Some games, such as Roblox, "
            "only notice the mouse when it moves."
        )
        wo.addRow("", self.nudge)
        self.group_box = QComboBox()
        self.group_box.addItem("(no group)", "")
        for g in self._groups:
            self.group_box.addItem(g.name, g.id)
        self.group_box.setToolTip("When one rule in a group is found, the whole group stops being checked.")
        wo.addRow("Group", self.group_box)
        wl.addWidget(self.watch_options)
        fl.addWidget(self.watch_group)
        self.watch_group.setVisible(rule)
        self.restart_after.setVisible(not rule)  # a rule has its own, richer choice: "Then" in the box above
        layout.addWidget(self.finder_box)

        # -- timing
        timing = QFormLayout()
        self.delay = spin(0, 3_600_000, step.delay_after_ms, " ms")
        self.delay_label = QLabel("Wait afterwards")
        timing.addRow(self.delay_label, self.delay)
        layout.addLayout(timing)

        # -- advanced
        self.adv_toggle = QPushButton("Advanced options  \u25b8")
        self.adv_toggle.setFlat(True)
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.setStyleSheet("text-align: left; border: none; background: transparent; padding: 6px 0; color: #4fc3f7;")
        layout.addWidget(self.adv_toggle)
        self.adv_body = QWidget()
        self.adv_form = QFormLayout(self.adv_body)
        self.adv_form.setContentsMargins(0, 0, 0, 0)
        self.repeat = spin(1, 10000, step.repeat)
        self.timeout = spin(0, 3_600_000, step.timeout_ms, " ms")
        self.adv_form.addRow("Repeat", self.repeat)
        self.adv_form.addRow("Look for up to (sequence mode)", self.timeout)
        layout.addWidget(self.adv_body)
        self.adv_body.setVisible(False)
        self.adv_toggle.toggled.connect(self._advanced_toggled)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.kind_group.idClicked.connect(self._kind_changed)
        self._load(step)
        self.resize(600, 700)

    # ------------------------------------------------------------------ pages

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("subheading", True)
        return label

    def _click_page(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.c_button = QComboBox()
        self.c_button.addItems(BUTTONS)
        self.c_double = QCheckBox("Double-click")
        self.c_x, self.c_y = spin(-10000, 100000, 0), spin(-10000, 100000, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel("X"))
        row.addWidget(self.c_x)
        row.addWidget(QLabel("Y"))
        row.addWidget(self.c_y)
        pick = QPushButton("Pick on screen")
        pick.clicked.connect(lambda: self._pick_point(self.c_x, self.c_y))
        row.addWidget(pick)
        self.c_hold = spin(1, 5000, 60, " ms")
        f.addRow("Mouse button", self.c_button)
        f.addRow("", self.c_double)
        f.addRow("Position", row)
        f.addRow("Press time", self.c_hold)
        return w

    def _drag_page(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.d_button = QComboBox()
        self.d_button.addItems(BUTTONS)
        self.d_x, self.d_y = spin(-10000, 100000, 0), spin(-10000, 100000, 0)
        self.d_x2, self.d_y2 = spin(-10000, 100000, 0), spin(-10000, 100000, 0)
        start = QHBoxLayout()
        for label, box in (("X", self.d_x), ("Y", self.d_y)):
            start.addWidget(QLabel(label))
            start.addWidget(box)
        pick1 = QPushButton("Pick")
        pick1.clicked.connect(lambda: self._pick_point(self.d_x, self.d_y))
        start.addWidget(pick1)
        end = QHBoxLayout()
        for label, box in (("X", self.d_x2), ("Y", self.d_y2)):
            end.addWidget(QLabel(label))
            end.addWidget(box)
        pick2 = QPushButton("Pick")
        pick2.clicked.connect(lambda: self._pick_point(self.d_x2, self.d_y2))
        end.addWidget(pick2)
        self.d_time = spin(1, 60000, 300, " ms")
        f.addRow("Mouse button", self.d_button)
        f.addRow("From", start)
        f.addRow("To", end)
        f.addRow("Drag time", self.d_time)
        return w

    def _scroll_page(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.s_dy = spin(-1000, 1000, -3)
        self.s_dx = spin(-1000, 1000, 0)
        self.s_x, self.s_y = spin(0, 100000, 0), spin(0, 100000, 0)
        f.addRow("Vertical amount", self.s_dy)
        f.addRow(muted("Positive scrolls up, negative scrolls down (one step per wheel notch)."))
        f.addRow("Horizontal amount", self.s_dx)
        row = QHBoxLayout()
        row.addWidget(QLabel("X"))
        row.addWidget(self.s_x)
        row.addWidget(QLabel("Y"))
        row.addWidget(self.s_y)
        pick = QPushButton("Pick on screen")
        pick.clicked.connect(lambda: self._pick_point(self.s_x, self.s_y))
        row.addWidget(pick)
        f.addRow("Scroll at", row)
        f.addRow(muted("Leave X and Y at 0 to scroll wherever the mouse already is."))
        return w

    def _key_page(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        self.k_keys = QLineEdit()
        self.k_keys.setPlaceholderText("a, enter, f5, ctrl+shift+s")
        self.k_hold = spin(1, 60000, 60, " ms")
        self.k_status = muted("")
        f.addRow("Key or combination", self.k_keys)
        f.addRow(self.k_status)
        f.addRow("Hold for", self.k_hold)
        f.addRow(muted(
            "Modifiers: ctrl, shift, alt, cmd (the Windows key on Windows). Named keys: enter, esc, tab, space, "
            "backspace, delete, insert, up, down, left, right, home, end, pageup, pagedown, f1 to f24, menu, pause, "
            "print_screen, num_lock, scroll_lock, caps_lock."
        ))
        self.k_keys.textChanged.connect(self._key_changed)
        return w

    def _image_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.pick_image = QPushButton("Pick image from screen")
        self.pick_image.clicked.connect(self._pick_image)
        v.addWidget(self.pick_image)
        v.addWidget(muted(
            "Ultrebo hides its window and shows your screen. Drag a box around the button or icon to look for. "
            "Crop tightly around something distinctive."
        ))
        self.thumb = QLabel("No image picked yet")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setMinimumHeight(90)
        self.thumb.setProperty("card", True)
        v.addWidget(self.thumb)
        f = QFormLayout()
        self.i_threshold = QDoubleSpinBox()
        self.i_threshold.setRange(0.1, 1.0)
        self.i_threshold.setSingleStep(0.05)
        self.i_threshold.setDecimals(2)
        self.i_threshold.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        f.addRow("Match threshold", self.i_threshold)
        v.addLayout(f)
        return w

    def _text_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.t_text = QLineEdit()
        self.t_text.setPlaceholderText("Text to look for, for example: I'm here")
        v.addWidget(self.t_text)
        v.addWidget(muted(
            "Capital letters, spaces and punctuation are ignored. Reads Latin letters and numbers "
            "(English and similar). Pick a distinctive word or phrase."
        ))
        f = QFormLayout()
        self.t_threshold = QDoubleSpinBox()
        self.t_threshold.setRange(0.1, 1.0)
        self.t_threshold.setSingleStep(0.05)
        self.t_threshold.setDecimals(2)
        self.t_threshold.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        f.addRow("Match strictness", self.t_threshold)
        v.addLayout(f)
        v.addWidget(muted("Lower forgives more misread letters (0.8 allows about one wrong letter in six)."))
        return w

    # --------------------------------------------------------------- behaviour

    def _kind(self) -> StepType:
        return KINDS[max(self.kind_group.checkedId(), 0)][0]

    def _kind_changed(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self._refresh()

    def _advanced_toggled(self, on: bool) -> None:
        self.adv_toggle.setText("Advanced options  \u25be" if on else "Advanced options  \u25b8")
        self.adv_body.setVisible(on)
        self._refresh()

    def _refresh(self) -> None:
        kind = self._kind()
        finder = kind in (StepType.IMAGE, StepType.TEXT)
        watcher = finder and self.rule
        self.description.setText(DESCRIPTIONS[kind])
        self.finder_box.setVisible(finder)
        self.watch_options.setVisible(watcher)
        self.delay_label.setText(
            "Wait after it appears, before the macro continues or restarts" if watcher else "Wait afterwards"
        )
        # Let the stacked pages shrink to the page being shown instead of the tallest one.
        current = self.pages.currentWidget()
        for i in range(self.pages.count()):
            page = self.pages.widget(i)
            policy = QSizePolicy.Policy.Preferred if page is current else QSizePolicy.Policy.Ignored
            page.setSizePolicy(policy, policy)
        self.pages.adjustSize()
        self._update_region_label()
        self._update_thumb()
        self._set_row_visible(self.timeout, finder and not watcher)
        self._set_row_visible(self.repeat, not watcher)
        # A rule has no repeat or look-for-up-to time, so there is nothing left to hide behind "Advanced".
        self.adv_toggle.setVisible(not self.rule)
        self.adv_body.setVisible(self.adv_toggle.isChecked() and not self.rule)

    def _set_row_visible(self, widget: QWidget, visible: bool) -> None:
        label = self.adv_form.labelForField(widget)
        widget.setVisible(visible)
        if label is not None:
            label.setVisible(visible)

    def _key_changed(self, text: str) -> None:
        error = validate_key_spec(text) if text.strip() else None
        self.k_status.setText(error or "")

    def _update_region_label(self) -> None:
        if self._region:
            x, y, w, h = self._region
            self.region_label.setText(f"x {x}, y {y}, {w} x {h}")
        else:
            self.region_label.setText("Whole screen")

    def _update_thumb(self) -> None:
        if self._template:
            pix = QPixmap(str(self.ctx.store.template_path(self._template)))
            if not pix.isNull():
                self.thumb.setPixmap(pix.scaled(280, 110, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                self.pick_image.setText("Re-pick image from screen")
                return
        self.thumb.setPixmap(QPixmap())
        self.thumb.setText("No image picked yet")
        self.pick_image.setText("Pick image from screen")

    # -- picking
    def _pick_point(self, x_box: QSpinBox, y_box: QSpinBox) -> None:
        def got(x: int, y: int) -> None:
            x_box.setValue(x)
            y_box.setValue(y)

        self.ctx.pick([self, self.parent()] if self.parent() else [self], "point", on_point=got)

    def _pick_image(self) -> None:
        def got(frame, x: int, y: int, w: int, h: int) -> None:
            name = self.ctx.save_template(frame, x, y, w, h)
            if name is None:
                QMessageBox.warning(self, "Ultrebo", "That box was too small. Try a bigger one.")
                return
            if self._template and self._template != self._step.template_file:
                self.ctx.store.delete_template(self._template)  # replaced before saving
            self._template = name
            self._update_thumb()

        self.ctx.pick([self, self.parent()] if self.parent() else [self], "box", on_box=got)

    def _pick_region(self) -> None:
        def got(frame, x: int, y: int, w: int, h: int) -> None:
            x1, y1 = self.ctx.screen.to_input(x, y)
            x2, y2 = self.ctx.screen.to_input(x + w, y + h)
            self._region = [x1, y1, max(x2 - x1, 1), max(y2 - y1, 1)]
            self._update_region_label()

        self.ctx.pick(
            [self, self.parent()] if self.parent() else [self], "box", on_box=got,
            hint="Drag a box around the part of the screen to search. Esc to cancel.",
        )

    def _clear_region(self) -> None:
        self._region = None
        self._update_region_label()

    # -- loading and saving
    def _load(self, s: Step) -> None:
        kind = s.type if (not self.rule or s.is_finder) else StepType.IMAGE
        index = [k for k, _ in KINDS].index(kind)
        self.kind_group.button(index).setChecked(True)
        self.pages.setCurrentIndex(index)
        # click
        self.c_button.setCurrentText(s.button if s.button in BUTTONS else "left")
        self.c_double.setChecked(s.clicks == 2)
        self.c_x.setValue(s.x)
        self.c_y.setValue(s.y)
        self.c_hold.setValue(max(s.hold_ms, 1))
        # drag
        self.d_button.setCurrentText(s.button if s.button in BUTTONS else "left")
        self.d_x.setValue(s.x)
        self.d_y.setValue(s.y)
        self.d_x2.setValue(s.x2)
        self.d_y2.setValue(s.y2)
        self.d_time.setValue(max(s.hold_ms, 1) if s.type is StepType.DRAG else 300)
        # scroll
        self.s_dy.setValue(s.scroll_dy if s.type is StepType.SCROLL else -3)
        self.s_dx.setValue(s.scroll_dx)
        self.s_x.setValue(max(s.x, 0) if s.type is StepType.SCROLL else 0)
        self.s_y.setValue(max(s.y, 0) if s.type is StepType.SCROLL else 0)
        # key
        self.k_keys.setText(s.keys)
        self.k_hold.setValue(max(s.hold_ms, 1) if s.type is StepType.KEY else 60)
        # finders
        self.i_threshold.setValue(s.threshold)
        self.t_threshold.setValue(s.threshold)
        self.t_text.setText(s.text)
        self.click_found.setChecked(s.click_on_found)
        self.notify.setChecked(s.notify)
        self.restart_after.setChecked(s.on_seen is WatchAction.RESTART and not self.rule)
        self.f_button.setCurrentText(s.button if s.button in BUTTONS else "left")
        self.f_double.setChecked(s.clicks == 2)
        self.on_seen.setCurrentIndex(self.on_seen.findData(s.on_seen.value))
        self.nudge.setChecked(s.nudge)
        at = self.group_box.findData(s.group_id or "")
        self.group_box.setCurrentIndex(max(at, 0))
        self._refresh()

    def result_step(self) -> Step:
        return self._step

    def _accept(self) -> None:
        kind = self._kind()
        s = self._step
        s.name = self.name.text().strip()
        s.type = kind
        s.delay_after_ms = self.delay.value()
        s.repeat = self.repeat.value()
        s.timeout_ms = self.timeout.value()

        if kind is StepType.CLICK:
            s.button = self.c_button.currentText()
            s.clicks = 2 if self.c_double.isChecked() else 1
            s.x, s.y = self.c_x.value(), self.c_y.value()
            s.hold_ms = self.c_hold.value()
        elif kind is StepType.DRAG:
            s.button = self.d_button.currentText()
            s.x, s.y, s.x2, s.y2 = self.d_x.value(), self.d_y.value(), self.d_x2.value(), self.d_y2.value()
            s.hold_ms = self.d_time.value()
        elif kind is StepType.SCROLL:
            s.scroll_dy, s.scroll_dx = self.s_dy.value(), self.s_dx.value()
            s.x, s.y = self.s_x.value(), self.s_y.value()
        elif kind is StepType.KEY:
            error = validate_key_spec(self.k_keys.text())
            if error:
                QMessageBox.warning(self, "Ultrebo", f"The key isn't valid: {error}")
                return
            s.keys = self.k_keys.text().strip()
            s.hold_ms = self.k_hold.value()
        else:
            if kind is StepType.IMAGE:
                if not self._template:
                    QMessageBox.warning(self, "Ultrebo", "Pick an image from the screen first.")
                    return
                s.template_file = self._template
                s.threshold = round(self.i_threshold.value(), 2)
            else:
                if not self.t_text.text().strip():
                    QMessageBox.warning(self, "Ultrebo", "Type the text to look for first.")
                    return
                s.text = self.t_text.text().strip()
                s.threshold = round(self.t_threshold.value(), 2)
            s.click_on_found = self.click_found.isChecked()
            s.notify = self.notify.isChecked()
            if not self.rule:
                s.on_seen = WatchAction.RESTART if self.restart_after.isChecked() else WatchAction.CONTINUE
            s.button = self.f_button.currentText()
            s.clicks = 2 if self.f_double.isChecked() else 1
            s.watch = self.rule
            if self.rule:
                s.on_seen = WatchAction(self.on_seen.currentData())
                s.nudge = self.nudge.isChecked()
                s.group_id = self.group_box.currentData() or None
                s.repeat = 1
            s.region = list(self._region) if self._region else None
        self.accept()

    def reject(self) -> None:
        # An image picked in this dialog but never saved should not stay on disk.
        if self._template and self._template != self._step.template_file:
            self.ctx.store.delete_template(self._template)
        super().reject()
