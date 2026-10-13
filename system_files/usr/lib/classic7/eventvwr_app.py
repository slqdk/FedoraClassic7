"""Event Viewer, as in Windows 7, over the systemd journal.

    classic7-eventvwr              the window
    classic7-eventvwr --problems   straight to Problem Reports (programs that stopped working)

The tree: Custom Views (Administrative Events: critical, error and warning from everywhere;
Problem Reports: crashed programs from coredumpctl), Classic 7 Logs (Application: your own
programs; Security: sign-ins, sudo and polkit; Setup: system updates; System: the system's
services) and Applications and Services Logs (Kernel, and this start of the computer). The newest
events come first; Filter Current Log narrows by level, time and source."""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import pwd
import socket
import subprocess
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                               QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

APP = "Event Viewer"
LIMIT = 2000
LEVELS = {0: "Critical", 1: "Critical", 2: "Critical", 3: "Error", 4: "Warning", 5: "Information", 6: "Information",
          7: "Verbose"}
LEVEL_ICON = {"Critical": "dialog-error", "Error": "dialog-error", "Warning": "dialog-warning",
              "Information": "dialog-information", "Verbose": "dialog-information"}
HOST = socket.gethostname()

# log name -> (journalctl arguments, description)
LOGS = {
    "Application": (["--user"], "Messages from your own programs"),
    "Security": (["SYSLOG_FACILITY=4", "SYSLOG_FACILITY=10"], "Sign-ins, sudo, polkit and other security events"),
    "Setup": (["-u", "rpm-ostreed.service", "-u", "bootc-fetch-apply-updates.service",
               "-u", "rpm-ostree-countme.service", "-u", "flatpak-system-helper.service",
               "-u", "uupd.service"], "System updates and installed programs"),
    "System": (["--system"], "Messages from the system's services"),
    "Kernel": (["-k"], "Messages from the Linux kernel"),
    "This start": (["-b"], "Everything since the computer last started"),
}


@dataclass
class Event:
    when: dt.datetime
    level: str
    source: str
    event_id: str
    category: str
    message: str
    log: str
    user: str = ""
    fields: dict = field(default_factory=dict)


def _text(v) -> str:
    if isinstance(v, list):          # binary messages come as byte arrays
        try:
            return bytes(x for x in v if isinstance(x, int)).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return str(v)
    return "" if v is None else str(v)


def _user(uid: str) -> str:
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (ValueError, KeyError):
        return "N/A"


def to_event(d: dict, log: str) -> Event:
    try:
        when = dt.datetime.fromtimestamp(int(d.get("__REALTIME_TIMESTAMP", 0)) / 1_000_000)
    except (ValueError, TypeError, OSError):
        when = dt.datetime.fromtimestamp(0)
    try:
        pri = int(d.get("PRIORITY", 6))
    except (ValueError, TypeError):
        pri = 6
    source = _text(d.get("SYSLOG_IDENTIFIER") or d.get("_COMM") or d.get("_SYSTEMD_UNIT") or "kernel")
    mid = _text(d.get("MESSAGE_ID"))
    event_id = str(int(hashlib.sha1(mid.encode()).hexdigest()[:6], 16) % 10000) if mid else ""
    unit = _text(d.get("_SYSTEMD_USER_UNIT") or d.get("_SYSTEMD_UNIT") or "")
    return Event(when, LEVELS.get(pri, "Information"), source, event_id, unit or "None", _text(d.get("MESSAGE")),
                 log, _user(_text(d.get("_UID"))) if d.get("_UID") else "N/A",
                 {k: _text(v) for k, v in d.items() if not k.startswith("__")})


def journal(args: list[str], log: str, since: str = "", priority: str = "", limit: int = LIMIT) -> tuple[list[Event], str]:
    cmd = ["journalctl", "--no-pager", "-o", "json", "-r", "-n", str(limit), *args]
    if since:
        cmd += ["--since", since]
    if priority:
        cmd += ["-p", priority]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return [], str(e)
    events = []
    for line in r.stdout.splitlines():
        try:
            events.append(to_event(json.loads(line), log))
        except ValueError:
            continue
    note = ""
    if r.returncode != 0 and not events:
        note = r.stderr.strip().splitlines()[0] if r.stderr.strip() else "The log could not be read."
    elif "--system" in args or "-k" in args:
        if "not seeing messages from other users and the system" in r.stderr:
            note = "Only some events are shown: your account may not read the whole system log."
    return events, note


def problem_reports(since: str = "") -> tuple[list[Event], str]:
    cmd = ["coredumpctl", "--no-pager", "--json=short", "list"]
    if since:
        cmd += ["--since", since]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        rows = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return [], "Problem reports could not be read."
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        exe = row.get("exe") or "?"
        try:
            when = dt.datetime.fromtimestamp(int(row.get("time", 0)) / 1_000_000)
        except (ValueError, TypeError, OSError):
            when = dt.datetime.fromtimestamp(0)
        sig = row.get("sig")
        names = {6: "SIGABRT (aborted)", 11: "SIGSEGV (memory access fault)", 7: "SIGBUS", 4: "SIGILL", 8: "SIGFPE",
                 5: "SIGTRAP"}
        msg = (f"Faulting application name: {os.path.basename(exe)}\nFaulting application path: {exe}\n"
               f"Process id: {row.get('pid')}\nSignal: {names.get(sig, sig)}\n"
               f"Problem report: {'stored' if row.get('present') else 'not stored'}"
               + (f" ({row.get('corefile')})" if row.get("corefile") else ""))
        out.append(Event(when, "Error", "Application Error", "1000", "(100)", msg, "Problem Reports",
                         _user(str(row.get("uid", ""))), {k: str(v) for k, v in row.items()}))
    out.sort(key=lambda e: e.when, reverse=True)
    return out, "" if out or r.returncode == 0 else "No problem reports."


class Loader(QThread):
    done = Signal(object, str)

    def __init__(self, view: str, since: str, priority: str):
        super().__init__()
        self.view, self.since, self.priority = view, since, priority

    def run(self):
        if self.view == "Problem Reports":
            self.done.emit(*problem_reports(self.since))
            return
        if self.view == "Administrative Events":
            a, n1 = journal(["--system"], "System", self.since, self.priority or "0..4")
            b, _n2 = journal(["--user"], "Application", self.since, self.priority or "0..4")
            ev = sorted(a + b, key=lambda e: e.when, reverse=True)[:LIMIT]
            self.done.emit(ev, n1)
            return
        args = LOGS.get(self.view, (["--system"], ""))[0]
        self.done.emit(*journal(args, self.view, self.since, self.priority))


class FilterDialog(QDialog):
    TIMES = [("Any time", ""), ("Last hour", "-1h"), ("Last 12 hours", "-12h"), ("Last 24 hours", "-24h"),
             ("Last 7 days", "-7d"), ("Last 30 days", "-30d")]

    def __init__(self, parent, current: dict):
        super().__init__(parent)
        self.setWindowTitle("Filter Current Log")
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.when = QComboBox()
        for text, val in self.TIMES:
            self.when.addItem(text, val)
        self.when.setCurrentIndex(max(0, self.when.findData(current.get("since", ""))))
        form.addRow("Logged:", self.when)
        levels = QWidget()
        lg = QGridLayout(levels)
        lg.setContentsMargins(0, 0, 0, 0)
        self.boxes = {}
        for i, name in enumerate(["Critical", "Warning", "Verbose", "Error", "Information"]):
            b = QCheckBox(name)
            b.setChecked(name in current.get("levels", set()))
            lg.addWidget(b, i % 3, i // 3)
            self.boxes[name] = b
        form.addRow("Event level:", levels)
        self.source = QLineEdit(", ".join(current.get("sources", [])))
        self.source.setPlaceholderText("All sources (or names separated by commas)")
        form.addRow("Event sources:", self.source)
        self.text = QLineEdit(current.get("text", ""))
        self.text.setPlaceholderText("Words in the message")
        form.addRow("Includes:", self.text)
        v.addLayout(form)
        row = QHBoxLayout()
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        row.addStretch(1)
        row.addWidget(clear)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(460, 260)

    def _clear(self):
        self.when.setCurrentIndex(0)
        for b in self.boxes.values():
            b.setChecked(False)
        self.source.clear()
        self.text.clear()

    def value(self) -> dict:
        return {"since": self.when.currentData(), "levels": {n for n, b in self.boxes.items() if b.isChecked()},
                "sources": [s.strip() for s in self.source.text().split(",") if s.strip()],
                "text": self.text.text().strip()}


class EventDetails(QTabWidget):
    """The General and Details tabs under the list (and in Event Properties)."""

    def __init__(self):
        super().__init__()
        gen = QWidget()
        g = QVBoxLayout(gen)
        self.message = QPlainTextEdit()
        self.message.setReadOnly(True)
        self.message.setMaximumHeight(110)
        g.addWidget(self.message)
        grid = QGridLayout()
        self.fields = {}
        names = [("Log Name:", 0, 0), ("Source:", 1, 0), ("Event ID:", 2, 0), ("Level:", 3, 0), ("User:", 4, 0),
                 ("OpCode:", 5, 0), ("Logged:", 1, 2), ("Task Category:", 2, 2), ("Keywords:", 3, 2),
                 ("Computer:", 4, 2)]
        for name, r, c in names:
            grid.addWidget(QLabel(name), r, c)
            val = QLabel()
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(val, r, c + 1)
            self.fields[name] = val
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        g.addLayout(grid)
        g.addStretch(1)
        self.addTab(gen, "General")
        self.raw = QTreeWidget()
        self.raw.setHeaderLabels(["Field", "Value"])
        self.raw.setRootIsDecorated(False)
        self.raw.header().resizeSection(0, 200)
        self.addTab(self.raw, "Details")

    def show_event(self, e: Event | None):
        if e is None:
            self.message.clear()
            for v in self.fields.values():
                v.clear()
            self.raw.clear()
            return
        self.message.setPlainText(e.message)
        vals = {"Log Name:": e.log, "Source:": e.source, "Event ID:": e.event_id, "Level:": e.level,
                "User:": e.user, "OpCode:": "Info", "Logged:": e.when.strftime("%d-%m-%Y %H:%M:%S"),
                "Task Category:": e.category, "Keywords:": "Classic", "Computer:": e.fields.get("_HOSTNAME", HOST)}
        for k, v in vals.items():
            self.fields[k].setText(v)
        self.raw.clear()
        for k in sorted(e.fields):
            it = QTreeWidgetItem([k, e.fields[k]])
            it.setToolTip(1, e.fields[k])
            self.raw.addTopLevelItem(it)


class EventProperties(QDialog):
    def __init__(self, viewer: "EventViewer", row: int):
        super().__init__(viewer)
        self.viewer = viewer
        self.row = row
        self.setWindowTitle("Event Properties")
        v = QVBoxLayout(self)
        self.details = EventDetails()
        self.details.message.setMaximumHeight(16777215)
        v.addWidget(self.details, 1)
        row_l = QHBoxLayout()
        copy = QPushButton("Copy")
        copy.clicked.connect(self._copy)
        up = QPushButton("▲")
        up.setToolTip("Previous event")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("▼")
        down.setToolTip("Next event")
        down.clicked.connect(lambda: self._move(1))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row_l.addWidget(copy)
        row_l.addStretch(1)
        row_l.addWidget(up)
        row_l.addWidget(down)
        row_l.addWidget(close)
        v.addLayout(row_l)
        self.resize(640, 480)
        self._show()

    def _show(self):
        self.details.show_event(self.viewer.event_at(self.row))

    def _move(self, step: int):
        n = self.viewer.list.topLevelItemCount()
        if 0 <= self.row + step < n:
            self.row += step
            self.viewer.list.setCurrentItem(self.viewer.list.topLevelItem(self.row))
            self._show()

    def _copy(self):
        e = self.viewer.event_at(self.row)
        if e:
            QApplication.clipboard().setText(self.viewer.event_text(e))


class EventViewer(QMainWindow):
    def __init__(self, start: str = "Administrative Events"):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon.fromTheme("utilities-log-viewer", QIcon.fromTheme("text-x-log")))
        self.events: list[Event] = []
        self.shown: list[Event] = []
        self.loader: Loader | None = None
        self.filters: dict[str, dict] = {}
        self._menus()
        tb = QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        tb.addAction(self.refresh_act)
        tb.addAction(self.filter_act)
        tb.addAction(self.find_act)
        tb.addAction(self.props_act)
        self.addToolBar(tb)
        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        root = QTreeWidgetItem(["Event Viewer (Local)"])
        root.setIcon(0, QIcon.fromTheme("utilities-log-viewer", QIcon.fromTheme("computer")))
        self.tree.addTopLevelItem(root)
        self.nodes: dict[str, QTreeWidgetItem] = {}

        def folder(parent, name):
            it = QTreeWidgetItem([name])
            it.setIcon(0, QIcon.fromTheme("folder"))
            parent.addChild(it)
            return it

        def leaf(parent, name, icon="text-x-log"):
            it = QTreeWidgetItem([name])
            it.setIcon(0, QIcon.fromTheme(icon))
            it.setData(0, Qt.UserRole, name)
            parent.addChild(it)
            self.nodes[name] = it
            return it
        cv = folder(root, "Custom Views")
        leaf(cv, "Administrative Events", "view-filter")
        leaf(cv, "Problem Reports", "tools-report-bug")
        wl = folder(root, "Classic 7 Logs")
        for name in ("Application", "Security", "Setup", "System"):
            leaf(wl, name)
        asl = folder(root, "Applications and Services Logs")
        leaf(asl, "Kernel")
        leaf(asl, "This start")
        self.tree.expandAll()
        self.tree.currentItemChanged.connect(self._node)
        split.addWidget(self.tree)
        mid = QSplitter(Qt.Vertical)
        top = QWidget()
        tl = QVBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.header = QLabel()
        self.header.setStyleSheet("background: #e8eef7; padding: 4px; border-bottom: 1px solid #c5d3e8;")
        tl.addWidget(self.header)
        self.list = QTreeWidget()
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setHeaderLabels(["Level", "Date and Time", "Source", "Event ID", "Task Category"])
        for i, w in enumerate((110, 150, 170, 70, 200)):
            self.list.header().resizeSection(i, w)
        self.list.header().setSectionResizeMode(QHeaderView.Interactive)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.currentItemChanged.connect(self._selected)
        self.list.itemDoubleClicked.connect(lambda *_: self.properties())
        tl.addWidget(self.list, 1)
        mid.addWidget(top)
        self.details = EventDetails()
        mid.addWidget(self.details)
        mid.setStretchFactor(0, 3)
        mid.setStretchFactor(1, 2)
        split.addWidget(mid)
        split.addWidget(self._actions_pane())
        split.setSizes([200, 720, 190])
        self.setCentralWidget(split)
        self.status = self.statusBar()
        self.resize(1180, 720)
        self.tree.setCurrentItem(self.nodes.get(start, self.nodes["Administrative Events"]))

    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self.save_act = QAction(QIcon.fromTheme("document-save-as"), "Save All Events As...", self)
        self.save_act.triggered.connect(self.save_all)
        f.addAction(self.save_act)
        f.addSeparator()
        f.addAction("E&xit", self.close)
        a = mb.addMenu("&Action")
        self.refresh_act = QAction(QIcon.fromTheme("view-refresh"), "Refresh", self)
        self.refresh_act.setShortcut(QKeySequence("F5"))
        self.refresh_act.triggered.connect(self.load)
        self.filter_act = QAction(QIcon.fromTheme("view-filter"), "Filter Current Log...", self)
        self.filter_act.triggered.connect(self.filter)
        self.find_act = QAction(QIcon.fromTheme("edit-find"), "Find...", self)
        self.find_act.setShortcut(QKeySequence("Ctrl+F"))
        self.find_act.triggered.connect(self.find)
        self.props_act = QAction(QIcon.fromTheme("document-properties"), "Event Properties", self)
        self.props_act.triggered.connect(self.properties)
        self.copy_act = QAction(QIcon.fromTheme("edit-copy"), "Copy Details as Text", self)
        self.copy_act.setShortcut(QKeySequence("Ctrl+C"))
        self.copy_act.triggered.connect(self.copy)
        for act in (self.refresh_act, self.filter_act, self.find_act, self.save_act, None, self.props_act,
                    self.copy_act):
            a.addSeparator() if act is None else a.addAction(act)
        v = mb.addMenu("&View")
        tree_act = v.addAction("Console Tree")
        tree_act.setCheckable(True)
        tree_act.setChecked(True)
        tree_act.toggled.connect(lambda on: self.tree.setVisible(on))
        h = mb.addMenu("&Help")
        h.addAction("About Event Viewer", lambda: QMessageBox.about(
            self, APP, "Event Viewer\n\nShows the messages that programs and the system write to the journal "
            "(systemd), and the reports of programs that stopped working."))

    def _actions_pane(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        head = QLabel("Actions")
        head.setStyleSheet("background: #dbe6f4; padding: 3px; font-weight: bold;")
        v.addWidget(head)
        self.act_title = QLabel()
        self.act_title.setStyleSheet("background: #eef3fa; padding: 3px; font-weight: bold;")
        v.addWidget(self.act_title)
        for act in (self.filter_act, self.find_act, self.save_act, self.refresh_act):
            v.addWidget(self._action_button(act))
        clear = QPushButton("Clear Filter")
        clear.setFlat(True)
        clear.setStyleSheet("text-align: left;")
        clear.clicked.connect(self.clear_filter)
        v.addWidget(clear)
        self.ev_title = QLabel("Event")
        self.ev_title.setStyleSheet("background: #eef3fa; padding: 3px; font-weight: bold;")
        v.addWidget(self.ev_title)
        for act in (self.props_act, self.copy_act):
            v.addWidget(self._action_button(act))
        v.addStretch(1)
        return w

    @staticmethod
    def _action_button(act: QAction) -> QPushButton:
        b = QPushButton(act.icon(), act.text())
        b.setFlat(True)
        b.setStyleSheet("text-align: left;")
        b.clicked.connect(act.trigger)
        return b

    # ---- loading ---------------------------------------------------------------------------------
    def current_view(self) -> str:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it is not None and it.data(0, Qt.UserRole) else ""

    def _node(self, it, _prev):
        if it is not None and it.data(0, Qt.UserRole):
            self.load()

    def load(self):
        view = self.current_view()
        if not view:
            return
        flt = self.filters.get(view, {})
        prio = ""
        levels = flt.get("levels") or set()
        if levels:
            nums = sorted(p for p, name in LEVELS.items() if name in levels)
            prio = f"{nums[0]}..{nums[-1]}"
        self.act_title.setText(view)
        self.header.setText(f"<b>{view}</b>   Loading...")
        self.status.showMessage("Loading events...")
        if self.loader is not None and self.loader.isRunning():
            self.loader.wait()
        self.loader = Loader(view, flt.get("since", ""), prio)
        self.loader.done.connect(lambda ev, note, v=view: self._loaded(v, ev, note))
        self.loader.start()

    def _loaded(self, view: str, events: list, note: str):
        if view != self.current_view():
            return
        self.events = events
        flt = self.filters.get(view, {})
        levels, sources, text = flt.get("levels") or set(), flt.get("sources") or [], flt.get("text", "").lower()
        self.shown = [e for e in events if (not levels or e.level in levels)
                      and (not sources or any(s.lower() in e.source.lower() for s in sources))
                      and (not text or text in e.message.lower())]
        self.list.clear()
        items = []
        for e in self.shown:
            it = QTreeWidgetItem([e.level, e.when.strftime("%d-%m-%Y %H:%M:%S"), e.source, e.event_id, e.category])
            it.setIcon(0, QIcon.fromTheme(LEVEL_ICON.get(e.level, "dialog-information")))
            items.append(it)
        self.list.addTopLevelItems(items)
        filt = "  Filtered: " if flt else "  "
        count = f"Number of events: {len(self.shown):,}" if not flt else f"Showing {len(self.shown):,} of {len(events):,}"
        self.header.setText(f"<b>{view}</b>{filt}{count}" + (f"   <span style='color:#a00'>{note}</span>" if note else ""))
        self.status.showMessage(f"{view}: {len(self.shown):,} events" + (" (the newest)" if len(events) >= LIMIT else ""))
        if items:
            self.list.setCurrentItem(items[0])
        else:
            self.details.show_event(None)

    def event_at(self, row: int) -> Event | None:
        return self.shown[row] if 0 <= row < len(self.shown) else None

    def _selected(self, it, _prev):
        row = self.list.indexOfTopLevelItem(it) if it is not None else -1
        e = self.event_at(row)
        self.details.show_event(e)
        self.ev_title.setText(f"Event {e.event_id}, {e.source}" if e and e.event_id else
                              (f"Event, {e.source}" if e else "Event"))

    # ---- actions ---------------------------------------------------------------------------------
    def filter(self):
        view = self.current_view()
        dlg = FilterDialog(self, self.filters.get(view, {}))
        if dlg.exec() == QDialog.Accepted:
            val = dlg.value()
            if not val["since"] and not val["levels"] and not val["sources"] and not val["text"]:
                self.filters.pop(view, None)
            else:
                self.filters[view] = val
            self.load()

    def clear_filter(self):
        self.filters.pop(self.current_view(), None)
        self.load()

    def find(self):
        text, ok = QInputDialog.getText(self, "Find", "Find what:")
        if not ok or not text:
            return
        start = self.list.indexOfTopLevelItem(self.list.currentItem()) + 1
        t = text.lower()
        for i in list(range(start, len(self.shown))) + list(range(0, start)):
            e = self.shown[i]
            if t in e.message.lower() or t in e.source.lower():
                self.list.setCurrentItem(self.list.topLevelItem(i))
                return
        QMessageBox.information(self, APP, f"\"{text}\" was not found.")

    def properties(self):
        row = self.list.indexOfTopLevelItem(self.list.currentItem())
        if row >= 0:
            EventProperties(self, row).exec()

    @staticmethod
    def event_text(e: Event) -> str:
        return (f"Log Name:      {e.log}\nSource:        {e.source}\nDate:          {e.when:%d-%m-%Y %H:%M:%S}\n"
                f"Event ID:      {e.event_id}\nTask Category: {e.category}\nLevel:         {e.level}\n"
                f"User:          {e.user}\nComputer:      {e.fields.get('_HOSTNAME', HOST)}\nDescription:\n{e.message}\n")

    def copy(self):
        rows = sorted(self.list.indexOfTopLevelItem(it) for it in self.list.selectedItems())
        QApplication.clipboard().setText("\n".join(self.event_text(self.shown[r]) for r in rows if r < len(self.shown)))

    def save_all(self):
        fn, flt = QFileDialog.getSaveFileName(self, "Save As", os.path.expanduser(f"~/{self.current_view() or 'events'}.csv"),
                                              "CSV (Comma Separated) (*.csv);;Text (Tab delimited) (*.txt)")
        if not fn:
            return
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f, delimiter="\t" if fn.endswith(".txt") else ",")
                w.writerow(["Level", "Date and Time", "Source", "Event ID", "Task Category", "Message"])
                for e in self.shown:
                    w.writerow([e.level, e.when.strftime("%d-%m-%Y %H:%M:%S"), e.source, e.event_id, e.category,
                                e.message])
        except OSError as e:
            QMessageBox.warning(self, APP, f"The events could not be saved: {e.strerror or e}")

    def closeEvent(self, e):
        if self.loader is not None:
            self.loader.wait(3000)
        super().closeEvent(e)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1].strip())
        return 0
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-eventvwr")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-eventvwr")
    w = EventViewer("Problem Reports" if "--problems" in argv else "Administrative Events")
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
