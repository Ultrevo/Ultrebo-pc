# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Ultrevo. See LICENSE and NOTICE.
"""The main window: macro list on the left, steps and settings on the right."""
from __future__ import annotations

import copy
import shutil
import threading
import uuid
import webbrowser

from PySide6.QtCore import QItemSelectionModel, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressDialog, QPushButton, QSpinBox, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__, selfupdate, updater
from ..hotkeys import HotkeyManager
from ..model import Macro, RunMode, Step, StepType
from ..recorder import Recorder
from ..updater import Update
from .context import AppContext
from .dialogs import AboutDialog, SettingsDialog
from .rules_tab import RulesTab
from .tablefill import fast_fill
from .toast import Toast
from .setup_guide import SetupCard
from .step_dialog import StepDialog
from .update_flow import UpdateJob

START_DELAY_MS = 800  # time to get the game in front after pressing Start in the window


class Bridge(QObject):
    """Lets worker threads (runner, hotkeys, update check) talk to the interface safely."""

    status = Signal(str)
    state = Signal(bool)
    error = Signal(str)
    toggle_run = Signal()
    toggle_record = Signal()
    update_found = Signal(object)
    update_result = Signal(object)  # the answer to "Check for updates" in About


class MainWindow(QMainWindow):
    COLUMNS = ["On", "#", "Step", "Details", "Wait"]

    def __init__(self, ctx: AppContext, bridge: Bridge, hotkeys: HotkeyManager | None = None):
        super().__init__()
        self.ctx = ctx
        self.bridge = bridge
        self.hotkeys = hotkeys
        self.store = ctx.store
        self.store.on_save_error = self._on_save_error
        self.toast = Toast()  # shown over the game, which is where the hotkeys are used
        self.recorder: Recorder | None = None
        self._running = False
        self._current_id: str | None = None
        self._loading = False
        self.setWindowTitle(f"Ultrebo {__version__}")
        self.resize(1080, 720)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        main = QHBoxLayout()
        outer.addLayout(main, 1)

        main.addWidget(self._build_left(), 0)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_empty())
        self.stack.addWidget(self._build_editor())
        main.addWidget(self.stack, 1)
        outer.addWidget(self._build_bottom())

        bridge.status.connect(self._on_status)
        bridge.state.connect(self._on_state)
        bridge.error.connect(self._on_error)
        bridge.toggle_run.connect(self.toggle_run)
        bridge.toggle_record.connect(self.toggle_record)
        bridge.update_found.connect(self._on_update)
        bridge.update_result.connect(self._on_update_result)

        self._reload_macros()
        self._apply_hotkeys()

    # ------------------------------------------------------------------ layout

    def _build_left(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(280)
        v = QVBoxLayout(panel)
        v.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Ultrebo")
        title.setProperty("heading", True)
        v.addWidget(title)
        self.macro_list = QListWidget()
        self.macro_list.currentItemChanged.connect(self._macro_selected)
        v.addWidget(self.macro_list, 1)
        row = QHBoxLayout()
        for text, slot in (("New", self.new_macro), ("Duplicate", self.duplicate_macro), ("Delete", self.delete_macro)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        v.addLayout(row)
        self.setup_card = SetupCard()
        v.addWidget(self.setup_card)
        row2 = QHBoxLayout()
        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings)
        about = QPushButton("About")
        about.clicked.connect(lambda: AboutDialog(self, on_check=self.check_for_updates_now).exec())
        row2.addWidget(settings)
        row2.addWidget(about)
        v.addLayout(row2)
        return panel

    def _build_empty(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch(1)
        label = QLabel("Create a macro to get started")
        label.setProperty("heading", True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(label)
        hint = QLabel(
            "Click New, then record your inputs or add steps by hand.\n"
            f"Hotkeys work even while a game is in front: {self.store.settings.start_stop_hotkey.upper()} starts and stops, "
            f"{self.store.settings.record_hotkey.upper()} records."
        )
        hint.setProperty("muted", True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(hint)
        new = QPushButton("New macro")
        new.setProperty("primary", True)
        new.clicked.connect(self.new_macro)
        v.addWidget(new, 0, Qt.AlignmentFlag.AlignCenter)
        v.addStretch(1)
        return w

    def _build_editor(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.editor_title = QLabel()
        self.editor_title.setProperty("heading", True)
        v.addWidget(self.editor_title)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_steps_tab(), "Steps")
        self.rules_tab = RulesTab(
            self.ctx, self._macro, self._test_step_object, self._refresh_list_item, self
        )
        self.tabs.addTab(self.rules_tab, "Rules")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        return w

    def _build_steps_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.add_button = QPushButton("Add step")
        self.add_button.setProperty("primary", True)
        menu = QMenu(self.add_button)
        menu.addAction("Record inputs (F9)", self.toggle_record)
        menu.addSeparator()
        for kind, label in (
            (StepType.CLICK, "Click..."), (StepType.DRAG, "Drag..."), (StepType.SCROLL, "Scroll..."),
            (StepType.KEY, "Key press..."), (StepType.IMAGE, "Find image..."), (StepType.TEXT, "Find text..."),
        ):
            action = QAction(label, menu)
            action.triggered.connect(lambda _=False, k=kind: self.add_step(k))
            menu.addAction(action)
        self.add_button.setMenu(menu)
        bar.addWidget(self.add_button)
        self.record_button = QPushButton("Record (F9)")
        self.record_button.clicked.connect(self.toggle_record)
        bar.addWidget(self.record_button)
        bar.addStretch(1)
        for text, slot in (("Edit", self.edit_step), ("Test", self.test_step)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addWidget(QLabel("Move to #"))
        self.move_to = QSpinBox()
        self.move_to.setRange(1, 1)
        self.move_to.setToolTip("Type the position you want the selected step(s) to have, then press Enter or click Move.")
        self.move_to.setFixedWidth(70)
        bar.addWidget(self.move_to)
        self.move_button = QPushButton("Move")
        self.move_button.clicked.connect(self.move_selected_to_number)
        self.move_to.lineEdit().returnPressed.connect(self.move_selected_to_number)
        bar.addWidget(self.move_button)
        for text, slot in (("Duplicate", self.duplicate_step), ("Delete", self.delete_step)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bar.addWidget(b)
        v.addLayout(bar)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # Click and drag, or Shift-click / Ctrl-click, to select several steps; Ctrl+A selects them all.
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._item_changed)
        self.table.cellDoubleClicked.connect(lambda *_: self.edit_step())
        self.table.itemSelectionChanged.connect(self._selection_changed)
        delete_key = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self.table)
        delete_key.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_key.activated.connect(self.delete_step)
        v.addWidget(self.table, 1)
        self.steps_hint = QLabel("Runs top to bottom. Double-click a step to edit it.")
        self.steps_hint.setProperty("muted", True)
        v.addWidget(self.steps_hint)
        return w

    def _build_settings_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        form = QFormLayout()
        self.s_name = QLineEdit()
        self.s_name.textEdited.connect(self._settings_edited)
        self.s_mode = QComboBox()
        for mode in RunMode:
            self.s_mode.addItem(mode.label, mode.value)
        self.s_mode.currentIndexChanged.connect(self._settings_edited)
        self.s_loops = QSpinBox()
        self.s_loops.setRange(0, 1_000_000)
        self.s_loops.valueChanged.connect(self._settings_edited)
        self.s_pause = QSpinBox()
        self.s_pause.setRange(0, 3_600_000)
        self.s_pause.setSuffix(" ms")
        self.s_pause.valueChanged.connect(self._settings_edited)
        self.s_scan = QSpinBox()
        self.s_scan.setRange(100, 3_600_000)
        self.s_scan.setSuffix(" ms")
        self.s_scan.valueChanged.connect(self._settings_edited)
        for box in (self.s_loops, self.s_pause, self.s_scan):
            box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        form.addRow("Macro name", self.s_name)
        form.addRow("How it runs", self.s_mode)
        self.s_mode_help = QLabel()
        self.s_mode_help.setWordWrap(True)
        self.s_mode_help.setProperty("muted", True)
        form.addRow("", self.s_mode_help)
        form.addRow("Loops (0 = forever)", self.s_loops)
        form.addRow("Pause between loops", self.s_pause)
        form.addRow("Look at the screen every", self.s_scan)
        hint = QLabel(
            "How often image and text steps and rules check the screen. Higher is easier on the computer "
            "(10000 = every 10 seconds). Reactive mode and rules keep checking until stopped."
        )
        hint.setWordWrap(True)
        hint.setProperty("muted", True)
        form.addRow("", hint)
        v.addLayout(form)
        v.addStretch(1)
        return w

    def _build_bottom(self) -> QWidget:
        bar = QFrame()
        bar.setProperty("card", True)
        h = QHBoxLayout(bar)
        self.status_label = QLabel("Ready")
        h.addWidget(self.status_label, 1)
        self.start_button = QPushButton()
        self.start_button.setProperty("primary", True)
        self.start_button.clicked.connect(self.toggle_run_from_button)
        h.addWidget(self.start_button)
        self._refresh_start_button()
        return bar

    # -------------------------------------------------------------- macro list

    def _macro(self) -> Macro | None:
        return self.store.get(self._current_id)

    def _reload_macros(self, select: str | None = None) -> None:
        self._loading = True
        self.macro_list.clear()
        wanted = select or self.store.settings.active_macro_id
        row_to_select = 0
        for i, macro in enumerate(self.store.macros):
            item = QListWidgetItem(self._list_text(macro))
            item.setData(Qt.ItemDataRole.UserRole, macro.id)
            self.macro_list.addItem(item)
            if macro.id == wanted:
                row_to_select = i
        self._loading = False
        if self.store.macros:
            self.macro_list.setCurrentRow(row_to_select)
        else:
            self._current_id = None
            self.stack.setCurrentIndex(0)

    def _macro_selected(self, item: QListWidgetItem | None, _prev=None) -> None:
        if self._loading or item is None:
            return
        self._current_id = item.data(Qt.ItemDataRole.UserRole)
        self.store.settings.active_macro_id = self._current_id
        self.store.save_settings()
        self._load_editor()

    def new_macro(self) -> None:
        macro = self.store.add(Macro(name=f"Macro {len(self.store.macros) + 1}"))
        self._reload_macros(select=macro.id)

    def duplicate_macro(self) -> None:
        macro = self._macro()
        if macro is None:
            return
        clone = Macro.from_dict(copy.deepcopy(macro.to_dict()))
        clone.id = uuid.uuid4().hex
        clone.name = f"{macro.name} copy"
        for step in [*clone.steps, *clone.rules]:
            step.id = uuid.uuid4().hex
            if step.template_file:
                new_name = self.store.new_template_name()
                try:
                    shutil.copyfile(self.store.template_path(step.template_file), self.store.template_path(new_name))
                    step.template_file = new_name
                except OSError:
                    step.template_file = None
        self.store.add(clone)
        self._reload_macros(select=clone.id)

    def delete_macro(self) -> None:
        macro = self._macro()
        if macro is None:
            return
        answer = QMessageBox.question(
            self, "Delete macro", f'Delete "{macro.name}"? Its steps and saved images are removed. This cannot be undone.'
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete(macro.id)
            self._reload_macros()

    # ------------------------------------------------------------------ editor

    def _load_editor(self) -> None:
        macro = self._macro()
        if macro is None:
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self.editor_title.setText(macro.name)
        self._loading = True
        self.s_name.setText(macro.name)
        self.s_mode.setCurrentIndex(self.s_mode.findData(macro.mode.value))
        self.s_mode_help.setText(macro.mode.help)
        self.s_loops.setValue(macro.loops)
        self.s_pause.setValue(macro.loop_delay_ms)
        self.s_scan.setValue(macro.scan_interval_ms)
        self._loading = False
        self._fill_table()
        self.rules_tab.refresh()

    def _fill_table(self, select_id: str | None = None, select_ids: list[str] | None = None) -> None:
        macro = self._macro()
        if macro is None:
            return
        wanted = set(select_ids or ([select_id] if select_id else self._selected_step_ids()))
        self._loading = True
        ordered = macro.ordered()
        self.move_to.setRange(1, max(len(ordered), 1))
        self.table.clearSelection()
        with fast_fill(self.table):
            self.table.setRowCount(len(ordered))
            for row, step in enumerate(ordered):
                on = QTableWidgetItem()
                on.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                on.setCheckState(Qt.CheckState.Checked if step.enabled else Qt.CheckState.Unchecked)
                on.setData(Qt.ItemDataRole.UserRole, step.id)
                self.table.setItem(row, 0, on)
                for col, text in enumerate(
                    (str(row + 1), f"{step.title()}", step.summary(), f"{step.delay_after_ms} ms"), start=1
                ):
                    item = QTableWidgetItem(text)
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    if not step.enabled:
                        item.setForeground(Qt.GlobalColor.gray)
                    self.table.setItem(row, col, item)
                if step.id in wanted:
                    self.table.selectionModel().select(
                        self.table.model().index(row, 0),
                        QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                    )
        self._loading = False
        self._selection_changed()
        self.steps_hint.setText(
            "Runs top to bottom. Drag or Shift/Ctrl-click to select several steps, type a number in Move to # to reorder, "
            "double-click a step to edit it."
            if ordered else "No steps yet. Click Add step, or press Record and use your computer normally."
        )
        self._refresh_list_item()

    @staticmethod
    def _list_text(macro: Macro) -> str:
        rules = f", {len(macro.rules)} rule{'s' if len(macro.rules) != 1 else ''}" if macro.rules else ""
        steps = f"{len(macro.steps)} step{'s' if len(macro.steps) != 1 else ''}"
        return f"{macro.name}\n{steps}{rules} - {macro.mode.label}"

    def _refresh_list_item(self) -> None:
        macro = self._macro()
        item = self.macro_list.currentItem()
        if macro is not None and item is not None:
            item.setText(self._list_text(macro))

    def _selected_step_ids(self) -> list[str]:
        """Ids of every selected step, top to bottom."""
        model = self.table.selectionModel()
        rows = sorted(r.row() for r in model.selectedRows()) if model else []
        ids = []
        for row in rows:
            item = self.table.item(row, 0)
            if item is not None:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        return ids

    def _selected_step_id(self) -> str | None:
        ids = self._selected_step_ids()
        return ids[0] if ids else None

    def _selected_steps(self) -> list[Step]:
        macro = self._macro()
        if macro is None:
            return []
        by_id = {s.id: s for s in macro.steps}
        return [by_id[i] for i in self._selected_step_ids() if i in by_id]

    def _selected_step(self) -> Step | None:
        steps = self._selected_steps()
        return steps[0] if steps else None

    def _selection_changed(self) -> None:
        """Keep the "Move to #" box showing where the first selected step is now."""
        if self._loading:
            return
        macro = self._macro()
        first = self._selected_step_id()
        if macro is None or first is None:
            return
        position = next((i for i, s in enumerate(macro.ordered(), start=1) if s.id == first), None)
        if position is not None:
            self.move_to.setValue(position)

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        macro = self._macro()
        step = next((s for s in (macro.steps if macro else []) if s.id == item.data(Qt.ItemDataRole.UserRole)), None)
        if step is not None:
            step.enabled = item.checkState() == Qt.CheckState.Checked
            self.store.save()
            self._fill_table()

    def _settings_edited(self, *_args) -> None:
        macro = self._macro()
        if self._loading or macro is None:
            return
        macro.name = self.s_name.text() or "Macro"
        macro.mode = RunMode(self.s_mode.currentData())
        macro.loops = self.s_loops.value()
        macro.loop_delay_ms = self.s_pause.value()
        macro.scan_interval_ms = self.s_scan.value()
        self.s_mode_help.setText(macro.mode.help)
        self.editor_title.setText(macro.name)
        self.store.save()
        self._refresh_list_item()

    # -- step actions
    def add_step(self, kind: StepType) -> None:
        macro = self._macro()
        if macro is None:
            return
        step = Step(type=kind, priority=macro.next_priority())
        if kind in (StepType.IMAGE, StepType.TEXT):
            step.delay_after_ms = 500
        self._edit(step, is_new=True)

    def edit_step(self) -> None:
        steps = self._selected_steps()
        if len(steps) > 1:
            self.status_label.setText("Select just one step to edit it")
            return
        if steps:
            self._edit(steps[0], is_new=False)

    def _edit(self, step: Step, is_new: bool) -> None:
        macro = self._macro()
        if macro is None:
            return
        dialog = StepDialog(self.ctx, step, self, is_new=is_new)
        if dialog.exec() != StepDialog.DialogCode.Accepted:
            return
        updated = dialog.result_step()
        if is_new:
            macro.steps.append(updated)
        else:
            old_template = step.template_file
            macro.steps = [updated if s.id == updated.id else s for s in macro.steps]
            if old_template and old_template != updated.template_file:
                self.store.delete_template(old_template)
        self.store.save()
        self._fill_table(select_id=updated.id)

    def delete_step(self) -> None:
        """Delete every selected step (asks first when more than one)."""
        macro, steps = self._macro(), self._selected_steps()
        if macro is None or not steps:
            return
        if len(steps) > 1:
            answer = QMessageBox.question(
                self, "Delete steps", f"Delete these {len(steps)} steps? Their saved images are removed too. This cannot be undone.",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        gone = {s.id for s in steps}
        for step in steps:
            if step.template_file:
                self.store.delete_template(step.template_file)
        macro.steps = [s for s in macro.steps if s.id not in gone]
        self.store.save()
        self._fill_table()

    def _clone_of(self, step: Step) -> Step:
        clone = copy.deepcopy(step)
        clone.id = uuid.uuid4().hex
        if step.template_file:
            name = self.store.new_template_name()
            try:
                shutil.copyfile(self.store.template_path(step.template_file), self.store.template_path(name))
                clone.template_file = name
            except OSError:
                clone.template_file = None
        return clone

    def duplicate_step(self) -> None:
        """Copy every selected step; the copies go right after the last selected one, in the same order."""
        macro, steps = self._macro(), self._selected_steps()
        if macro is None or not steps:
            return
        clones = [self._clone_of(s) for s in steps]
        ordered = macro.ordered()
        last = max(i for i, s in enumerate(ordered) if s.id in {x.id for x in steps})
        ordered[last + 1:last + 1] = clones
        macro.renumber(ordered)
        self.store.save()
        self._fill_table(select_ids=[c.id for c in clones])

    def move_selected_to(self, position: int) -> None:
        """Move the selected steps (kept in their order) so the first one lands at `position` (1 = the top)."""
        macro, steps = self._macro(), self._selected_steps()
        if macro is None or not steps:
            return
        chosen = {s.id for s in steps}
        ordered = macro.ordered()
        rest = [s for s in ordered if s.id not in chosen]
        at = min(max(position, 1), len(rest) + 1) - 1
        moved = [s for s in ordered if s.id in chosen]
        rest[at:at] = moved
        macro.renumber(rest)
        self.store.save()
        self._fill_table(select_ids=[s.id for s in moved])

    def move_selected_to_number(self) -> None:
        self.move_selected_to(self.move_to.value())

    def move_step(self, delta: int) -> None:
        """One step up (-1) or down (+1). Not on a button any more, but handy for tests and scripts."""
        macro, step = self._macro(), self._selected_step()
        if macro is None or step is None:
            return
        position = next(i for i, s in enumerate(macro.ordered(), start=1) if s.id == step.id)
        self.move_selected_to(position + delta)

    def test_step(self) -> None:
        steps = self._selected_steps()
        if len(steps) > 1:
            self.status_label.setText("Select just one step to test it")
            return
        if steps:
            self._test_step_object(steps[0])

    def _test_step_object(self, step: Step) -> None:
        self._minimize_then(lambda: self._report(self.ctx.runner.test_step(step)))

    # --------------------------------------------------------- run and record

    def _report(self, error: str | None) -> None:
        if error:
            self._restore()
            QMessageBox.warning(self, "Ultrebo", error)

    def _minimize_then(self, action) -> None:
        self.showMinimized()
        QTimer.singleShot(START_DELAY_MS, action)

    def _restore(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def toggle_run_from_button(self) -> None:
        if self._running:
            self.ctx.runner.stop()
            return
        macro = self._macro()
        if macro is None:
            return
        error = self.ctx.runner.validate(macro)
        if error:
            QMessageBox.warning(self, "Ultrebo", error)
            return
        self._minimize_then(lambda: self._report(self.ctx.runner.start(macro)))

    def _tell(self, text: str, problem: bool = False) -> None:
        """Say something in the status bar and, where a game is in front, on a notice over the screen."""
        self.status_label.setText(text)
        self.toast.show_message(text)
        if problem:
            QApplication.beep()

    def toggle_run(self) -> None:
        """Start or stop from the global hotkey (no delay: the game is already in front)."""
        start_key = self.store.settings.start_stop_hotkey.upper()
        if self.recorder is not None and self.recorder.recording:
            self._tell(f"Recording is on: press {self.store.settings.record_hotkey.upper()} to stop it first", problem=True)
            return
        if self._running:
            self.ctx.runner.stop()
            return
        macro = self._macro()
        if macro is None:
            self._tell("Open or create a macro in Ultrebo first", problem=True)
            return
        error = self.ctx.runner.start(macro)
        if error:
            self._tell(f"Can't start: {error}", problem=True)
        else:
            self.toast.show_message(f"Running \"{macro.name}\" - press {start_key} to stop")

    def toggle_record(self) -> None:
        if self._running:
            self._tell(f"Stop the macro first ({self.store.settings.start_stop_hotkey.upper()})", problem=True)
            return
        if self.recorder is not None and self.recorder.recording:
            self._finish_recording()
            return
        macro = self._macro()
        if macro is None:
            self.new_macro()
            macro = self._macro()
        if macro is None:
            return
        keys = {self.store.settings.start_stop_hotkey, self.store.settings.record_hotkey}
        try:
            self.recorder = Recorder(ignore_keys={k.split("+")[-1] for k in keys})
            self.recorder.start()
        except Exception as e:  # noqa: BLE001
            self.recorder = None
            QMessageBox.warning(
                self, "Ultrebo",
                f"Recording could not start: {e}\n\nOn a Mac, switch on Input Monitoring for Ultrebo in System Settings.",
            )
            return
        self.record_button.setText("Stop recording")
        self.status_label.setText(f"Recording... press {self.store.settings.record_hotkey.upper()} to stop")
        self.toast.show_message(f"Recording - press {self.store.settings.record_hotkey.upper()} to stop")
        self.showMinimized()

    def _finish_recording(self) -> None:
        macro = self._macro()
        recorder, self.recorder = self.recorder, None
        self.record_button.setText(f"Record ({self.store.settings.record_hotkey.upper()})")
        if recorder is None or macro is None:
            return
        steps = recorder.stop(first_priority=macro.next_priority())
        macro.steps.extend(steps)
        self.store.save()
        self._load_editor()
        self._restore()
        self.status_label.setText(f"Recorded {len(steps)} step(s)")
        self.toast.show_message(f"Recorded {len(steps)} step(s)")

    # ----------------------------------------------------------------- signals

    def _refresh_start_button(self) -> None:
        key = self.store.settings.start_stop_hotkey.upper()
        self.start_button.setText(f"Stop ({key})" if self._running else f"Start ({key})")
        self.start_button.setProperty("danger", self._running)
        self.start_button.setProperty("primary", not self._running)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)

    def _on_state(self, running: bool) -> None:
        was_running = self._running
        self._running = running
        self._refresh_start_button()
        if not running:
            self.status_label.setText("Stopped")
            if was_running:
                self.toast.show_message("Stopped")

    def _on_status(self, text: str) -> None:
        if text:
            self.status_label.setText(f"Running: {text}" if self._running else text)

    def _on_save_error(self, message: str) -> None:
        """A change couldn't be written to disk: say so, instead of quietly losing it."""
        self.status_label.setText("Couldn't save")
        QMessageBox.warning(self, "Ultrebo", message)

    def _on_error(self, message: str) -> None:
        self._restore()
        QMessageBox.warning(
            self, "Ultrebo",
            f"The macro stopped because of an error:\n\n{message}\n\n"
            "On a Mac, check that Accessibility is switched on for Ultrebo in System Settings.",
        )

    def check_for_updates_now(self) -> None:
        """About > Check for updates: unlike the automatic check on launch, this one says what happened."""
        self.status_label.setText("Checking for updates...")

        def look() -> None:
            self.bridge.update_result.emit(updater.check_detailed(__version__))

        threading.Thread(target=look, daemon=True, name="ultrebo-update-check-now").start()

    def _on_update_result(self, result) -> None:
        self.status_label.setText("Ready")
        if result.error:
            QMessageBox.warning(
                self, "Ultrebo",
                f"Ultrebo couldn't check for updates:\n\n{result.error}\n\n"
                "You can look for a new version on the release page instead.",
            )
        elif result.update is not None:
            self._on_update(result.update)
        else:
            QMessageBox.information(self, "Ultrebo", f"You have the latest version ({__version__}).")

    def _on_update(self, update: Update) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"Ultrebo {update.version} is out (you have {__version__}).")
        update_now = None
        if selfupdate.can_update(update):
            box.setInformativeText(
                "Update now downloads it, closes Ultrebo and opens the new version. Your macros and settings are kept."
            )
            update_now = box.addButton("Update now", QMessageBox.ButtonRole.AcceptRole)
            page = box.addButton("Release page", QMessageBox.ButtonRole.ActionRole)
        else:
            box.setInformativeText("Download opens the release page in your browser.")
            page = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if update_now is not None and clicked is update_now:
            self._start_self_update(update)
        elif clicked is page:
            webbrowser.open(update.url)

    def _start_self_update(self, update: Update) -> None:
        if self._running:
            QMessageBox.information(self, "Ultrebo", "Stop the macro first, then update.")
            return
        progress = QProgressDialog(f"Downloading Ultrebo {update.version}...", "Cancel", 0, 100, self)
        progress.setWindowTitle("Updating Ultrebo")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        job = UpdateJob(update, self)
        self._update_job, self._update_progress = job, progress

        def on_progress(done: int, total: int) -> None:
            progress.setValue(min(int(100 * done / max(total, 1)), 99))

        def on_prepared(prepared) -> None:
            progress.setLabelText("Installing... Ultrebo will close and open again.")
            progress.setCancelButton(None)
            try:
                selfupdate.apply(prepared)
            except Exception as e:  # noqa: BLE001
                progress.close()
                self._update_failed(update, f"The update could not be started: {e}")
                return
            progress.close()
            self._quit_for_update()

        def on_failed(message: str) -> None:
            progress.close()
            self._update_failed(update, message)

        job.progress.connect(on_progress)
        job.prepared.connect(on_prepared)
        job.failed.connect(on_failed)
        progress.canceled.connect(job.cancel)
        progress.setValue(0)
        job.start()

    def _update_failed(self, update: Update, message: str) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Ultrebo")
        box.setText(message)
        box.setInformativeText("You can download the new version from the release page instead.")
        page = box.addButton("Open release page", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is page:
            webbrowser.open(update.url)

    def _quit_for_update(self) -> None:
        self.close()  # stops the macro and the hotkeys
        QTimer.singleShot(150, QApplication.quit)

    # ---------------------------------------------------------------- settings

    def _apply_hotkeys(self) -> None:
        self.record_button.setText(f"Record ({self.store.settings.record_hotkey.upper()})")
        self._refresh_start_button()
        if self.hotkeys is None:
            return
        try:
            self.hotkeys.set_bindings({
                self.store.settings.start_stop_hotkey: self.bridge.toggle_run.emit,
                self.store.settings.record_hotkey: self.bridge.toggle_record.emit,
            })
        except Exception as e:  # noqa: BLE001
            self._tell(f"Hotkeys unavailable: {e}", problem=True)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.store.settings, self, self.ctx.screen)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.store.save_settings()
            self._apply_hotkeys()
            self.ctx.apply_monitor(self.store.settings.monitor)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.ctx.runner.stop()
        if self.recorder is not None and self.recorder.recording:
            self.recorder.stop()
        if self.hotkeys is not None:
            self.hotkeys.stop()
        self.toast.hide()
        self.toast.deleteLater()
        super().closeEvent(event)
