# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""The Rules tab: always-watching detections that react while the macro runs, top of the list first."""
from __future__ import annotations

import copy
import shutil
import uuid
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..model import Macro, Step, StepType
from .context import AppContext
from .step_dialog import StepDialog

COLUMNS = ["On", "Order", "Rule", "What it does", "Wait"]


class RulesTab(QWidget):
    def __init__(
        self,
        ctx: AppContext,
        get_macro: Callable[[], Macro | None],
        test_rule: Callable[[Step], None],
        on_changed: Callable[[], None],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.ctx = ctx
        self.store = ctx.store
        self._get_macro = get_macro
        self._test_rule = test_rule
        self._on_changed = on_changed
        self._loading = False

        v = QVBoxLayout(self)
        intro = QLabel(
            "Rules watch the screen the whole time the macro runs, even while your steps are busy. "
            "Use them for pop-ups such as \"I'm here\". If two rules are on screen at the same time, "
            "the one nearer the top is handled first."
        )
        intro.setWordWrap(True)
        intro.setProperty("muted", True)
        v.addWidget(intro)

        bar = QHBoxLayout()
        self.add_button = QPushButton("Add rule")
        self.add_button.setProperty("primary", True)
        menu = QMenu(self.add_button)
        for kind, label in ((StepType.IMAGE, "When an image appears..."), (StepType.TEXT, "When text appears...")):
            action = QAction(label, menu)
            action.triggered.connect(lambda _=False, k=kind: self.add_rule(k))
            menu.addAction(action)
        self.add_button.setMenu(menu)
        bar.addWidget(self.add_button)
        bar.addStretch(1)
        for text, slot in (
            ("Edit", self.edit_rule), ("Test", self.test_selected), ("Up", lambda: self.move_rule(-1)),
            ("Down", lambda: self.move_rule(1)), ("Duplicate", self.duplicate_rule), ("Delete", self.delete_rule),
        ):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        v.addLayout(bar)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        for col in (0, 1, 2, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_rule())
        v.addWidget(self.table, 1)
        self.hint = QLabel()
        self.hint.setProperty("muted", True)
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)

    # -- table
    def refresh(self, select_id: str | None = None) -> None:
        macro = self._get_macro()
        if macro is None:
            return
        previous = select_id or self._selected_id()
        self._loading = True
        ordered = macro.ordered_rules()
        self.table.setRowCount(len(ordered))
        for row, rule in enumerate(ordered):
            on = QTableWidgetItem()
            on.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            on.setCheckState(Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            on.setData(Qt.ItemDataRole.UserRole, rule.id)
            self.table.setItem(row, 0, on)
            for col, text in enumerate((str(row + 1), rule.title(), rule.rule_summary(), f"{rule.delay_after_ms} ms"), start=1):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if not rule.enabled:
                    item.setForeground(Qt.GlobalColor.gray)
                self.table.setItem(row, col, item)
            if previous == rule.id:
                self.table.selectRow(row)
        self._loading = False
        self.hint.setText(
            "The rule at the top wins when several match at once. Use Up and Down to change the order. Double-click a rule to edit it."
            if ordered else "No rules yet. Click Add rule to react to a pop-up or button whenever it appears."
        )

    def _selected_id(self) -> str | None:
        model = self.table.selectionModel()
        rows = model.selectedRows() if model else []
        item = self.table.item(rows[0].row(), 0) if rows else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected(self) -> Step | None:
        macro, rid = self._get_macro(), self._selected_id()
        if macro is None or rid is None:
            return None
        return next((r for r in macro.rules if r.id == rid), None)

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        macro = self._get_macro()
        rule = next((r for r in (macro.rules if macro else []) if r.id == item.data(Qt.ItemDataRole.UserRole)), None)
        if rule is not None:
            rule.enabled = item.checkState() == Qt.CheckState.Checked
            self._save()
            self.refresh()

    def _save(self) -> None:
        self.store.save()
        self._on_changed()

    # -- actions
    def add_rule(self, kind: StepType) -> None:
        macro = self._get_macro()
        if macro is None:
            return
        rule = Step(type=kind, priority=macro.next_rule_priority(), watch=True, delay_after_ms=500)
        self._edit(rule, is_new=True)

    def edit_rule(self) -> None:
        rule = self._selected()
        if rule is not None:
            self._edit(rule, is_new=False)

    def _edit(self, rule: Step, is_new: bool) -> None:
        macro = self._get_macro()
        if macro is None:
            return
        dialog = StepDialog(self.ctx, rule, self, is_new=is_new, rule=True)
        if dialog.exec() != StepDialog.DialogCode.Accepted:
            return
        updated = dialog.result_step()
        if is_new:
            macro.rules.append(updated)
        else:
            old_template = rule.template_file
            macro.rules = [updated if r.id == updated.id else r for r in macro.rules]
            if old_template and old_template != updated.template_file:
                self.store.delete_template(old_template)
        self._save()
        self.refresh(select_id=updated.id)

    def delete_rule(self) -> None:
        macro, rule = self._get_macro(), self._selected()
        if macro is None or rule is None:
            return
        if rule.template_file:
            self.store.delete_template(rule.template_file)
        macro.rules = [r for r in macro.rules if r.id != rule.id]
        self._save()
        self.refresh()

    def duplicate_rule(self) -> None:
        macro, rule = self._get_macro(), self._selected()
        if macro is None or rule is None:
            return
        clone = copy.deepcopy(rule)
        clone.id = uuid.uuid4().hex
        clone.priority = rule.priority + 1
        if rule.template_file:
            name = self.store.new_template_name()
            try:
                shutil.copyfile(self.store.template_path(rule.template_file), self.store.template_path(name))
                clone.template_file = name
            except OSError:
                clone.template_file = None
        macro.rules.append(clone)
        macro.renumber_rules(macro.ordered_rules())
        self._save()
        self.refresh(select_id=clone.id)

    def move_rule(self, delta: int) -> None:
        macro, rule = self._get_macro(), self._selected()
        if macro is None or rule is None:
            return
        ordered = macro.ordered_rules()
        i = next(k for k, r in enumerate(ordered) if r.id == rule.id)
        j = i + delta
        if j < 0 or j >= len(ordered):
            return
        ordered.insert(j, ordered.pop(i))
        macro.renumber_rules(ordered)
        self._save()
        self.refresh(select_id=rule.id)

    def test_selected(self) -> None:
        rule = self._selected()
        if rule is not None:
            self._test_rule(rule)
