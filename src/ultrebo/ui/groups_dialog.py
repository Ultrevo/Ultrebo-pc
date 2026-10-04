# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""Manage a macro's rule groups: when one rule in a group is found, the whole group stops being checked."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..model import Macro, RuleGroup


class GroupsDialog(QDialog):
    def __init__(self, macro: Macro, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Rule groups")
        self.setMinimumWidth(460)
        self._macro = macro
        self._loading = False
        v = QVBoxLayout(self)
        intro = QLabel(
            "Put rules in a group when only one of them needs to be found, for example three pictures of the same pop-up. "
            "As soon as one rule in the group is found, the whole group stops being checked. Choose a group for a rule in the rule's own window."
        )
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        v.addWidget(intro)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._selected)
        v.addWidget(self.list, 1)

        row = QHBoxLayout()
        for text, slot in (("New group", self._new), ("Rename", self._rename), ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)

        form = QFormLayout()
        self.pause = QSpinBox()
        self.pause.setRange(0, 86400)
        self.pause.setSuffix(" s")
        self.pause.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.pause.valueChanged.connect(self._pause_changed)
        form.addRow("Stop checking for", self.pause)
        v.addLayout(form)
        self.reset = QCheckBox("Start checking again when the macro restarts")
        self.reset.setToolTip("The macro restarts when it finishes a loop and starts over, or when a rule restarts it")
        self.reset.toggled.connect(self._reset_changed)
        v.addWidget(self.reset)
        self.pause_help = QLabel(
            "0 seconds means until the macro stops. Use a number of seconds for a pop-up that comes back now and then. "
            "A restart is a finished loop starting over (Sequence mode), or a rule set to restart the macro."
        )
        self.pause_help.setWordWrap(True)
        self.pause_help.setProperty("muted", True)
        v.addWidget(self.pause_help)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)
        self._fill()

    # -- list
    def _fill(self, select_id: str | None = None) -> None:
        self._loading = True
        self.list.clear()
        for g in self._macro.groups:
            count = sum(1 for r in self._macro.rules if r.group_id == g.id)
            item = QListWidgetItem(f"{g.name}  ({count} rule{'s' if count != 1 else ''})")
            item.setData(Qt.ItemDataRole.UserRole, g.id)
            self.list.addItem(item)
            if g.id == select_id:
                self.list.setCurrentItem(item)
        self._loading = False
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.pause.setEnabled(self.list.count() > 0)
        self._selected(self.list.currentItem())

    def _current(self) -> RuleGroup | None:
        item = self.list.currentItem()
        gid = item.data(Qt.ItemDataRole.UserRole) if item else None
        return next((g for g in self._macro.groups if g.id == gid), None)

    def _selected(self, *_args) -> None:
        group = self._current()
        self._loading = True
        self.pause.setValue(group.pause_s if group else 0)
        self.reset.setChecked(bool(group and group.reset_on_restart))
        self.reset.setEnabled(group is not None)
        self._loading = False

    def _pause_changed(self, value: int) -> None:
        group = self._current()
        if group is not None and not self._loading:
            group.pause_s = value

    def _reset_changed(self, on: bool) -> None:
        group = self._current()
        if group is not None and not self._loading:
            group.reset_on_restart = on

    # -- actions
    def _ask_name(self, title: str, start: str = "") -> str | None:
        text, ok = QInputDialog.getText(self, title, "Group name", text=start)
        text = text.strip()[:60]
        return text if ok and text else None

    def _taken(self, name: str, ignore: RuleGroup | None = None) -> bool:
        return any(g.name.lower() == name.lower() and g is not ignore for g in self._macro.groups)

    def _new(self) -> None:
        name = self._ask_name("New group")
        if name is None:
            return
        if self._taken(name):
            QMessageBox.warning(self, "Ultrebo", "There is already a group with that name.")
            return
        group = RuleGroup(name=name)
        self._macro.groups.append(group)
        self._fill(select_id=group.id)

    def _rename(self) -> None:
        group = self._current()
        if group is None:
            return
        name = self._ask_name("Rename group", group.name)
        if name is None:
            return
        if self._taken(name, ignore=group):
            QMessageBox.warning(self, "Ultrebo", "There is already a group with that name.")
            return
        group.name = name
        self._fill(select_id=group.id)

    def _delete(self) -> None:
        group = self._current()
        if group is None:
            return
        answer = QMessageBox.question(
            self, "Delete group", f'Delete the group "{group.name}"? Its rules are kept, they just stop being in a group.'
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._macro.delete_group(group.id)
            self._fill()
