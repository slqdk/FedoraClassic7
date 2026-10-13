"""Task Manager, in the style of Windows 7: Applications, Processes, Services, Performance,
Networking and Users. Ctrl+Shift+Esc opens it; only one runs at a time."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from collections import deque

from PySide6.QtCore import ClassInfo, QObject, QPoint, QRect, QSize, Qt, QTimer, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface
from PySide6.QtGui import QActionGroup, QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSizePolicy, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import session_actions as sa
import taskmgr_data as td

GRID = QColor(0, 128, 64)
LINE = QColor(0, 255, 0)
DIM = QColor(0, 56, 0)
SPEEDS = {"High": 500, "Normal": 1000, "Low": 4000, "Paused": 0}
SERVICE = "org.classic7.TaskManager"


def icon(name: str, fallback: str = "application-x-executable") -> QIcon:
    ic = QIcon.fromTheme(name) if name else QIcon()
    return ic if not ic.isNull() else QIcon.fromTheme(fallback)


# ---- graphs ---------------------------------------------------------------------------------
class Meter(QWidget):
    """The black box with green LED bars and the value under it (CPU Usage, Memory)."""

    def __init__(self):
        super().__init__()
        self.value = 0.0
        self.text = "0 %"
        self.setMinimumSize(QSize(70, 90))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setFixedWidth(84)

    def set(self, fraction: float, text: str):
        self.value = max(0.0, min(1.0, fraction))
        self.text = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(0, 0, 0))
        text_h = 18
        area = QRect(r.left() + 12, r.top() + 8, r.width() - 24, r.height() - text_h - 14)
        seg_h = 3
        gap = 1
        n = max(1, area.height() // (seg_h + gap))
        lit = round(self.value * n)
        col_w = (area.width() - 4) // 2
        for i in range(n):
            y = area.bottom() - (i + 1) * (seg_h + gap) + gap
            c = LINE if i < lit else DIM
            p.fillRect(area.left(), y, col_w, seg_h, c)
            p.fillRect(area.left() + col_w + 4, y, col_w, seg_h, c)
        p.setPen(LINE)
        p.drawText(QRect(r.left(), r.bottom() - text_h - 2, r.width(), text_h), Qt.AlignCenter, self.text)


class History(QWidget):
    """A scrolling green-on-black history graph with a grid."""
    STEP = 6

    def __init__(self, length: int = 120, color: QColor = LINE, autoscale: bool = False):
        super().__init__()
        self.autoscale = autoscale
        self.values: deque[float] = deque([0.0] * length, maxlen=length)
        self.offset = 0
        self.color = color
        self.second: deque[float] | None = None
        self.setMinimumSize(QSize(60, 60))

    def push(self, v: float, second: float | None = None):
        self.values.append(max(0.0, min(1.0, v)))
        if second is not None:
            if self.second is None:
                self.second = deque([0.0] * self.values.maxlen, maxlen=self.values.maxlen)
            self.second.append(max(0.0, min(1.0, second)))
        self.offset = (self.offset + self.STEP) % 12
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(0, 0, 0))
        p.setPen(GRID)
        cell = 12
        x = r.right() - self.offset
        while x > r.left():
            p.drawLine(x, r.top(), x, r.bottom())
            x -= cell
        y = r.bottom()
        while y > r.top():
            p.drawLine(r.left(), y, r.right(), y)
            y -= cell
        top = 1.0
        if self.autoscale:
            peak = max(self.values) if self.values else 0
            top = next((t for t in (0.01, 0.05, 0.1, 0.25, 0.5, 1.0) if peak <= t), 1.0)
            p.setPen(LINE)
            f = p.font()
            f.setPointSizeF(max(6.0, f.pointSizeF() - 1.5))
            p.setFont(f)
            for frac, align in ((1.0, Qt.AlignTop), (0.5, Qt.AlignVCenter), (0.0, Qt.AlignBottom)):
                text = f"{top * frac * 100:g} %"
                y = r.bottom() - frac * r.height()
                p.drawText(QRect(r.left() + 3, int(y) - 8, 60, 16), align | Qt.AlignLeft, text)
        p.setRenderHint(QPainter.Antialiasing)
        for vals, color in ((self.second, QColor(255, 0, 0)), (self.values, self.color)):
            if not vals:
                continue
            path = QPainterPath()
            n = len(vals)
            for i, v in enumerate(vals):
                px = r.right() - (n - 1 - i) * self.STEP
                py = r.bottom() - min(1.0, v / top) * (r.height() - 2)
                if i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            p.setPen(QPen(color, 1.2))
            p.drawPath(path)


def boxed(title: str, widget: QWidget) -> QGroupBox:
    g = QGroupBox(title)
    lay = QVBoxLayout(g)
    lay.setContentsMargins(6, 4, 6, 6)
    lay.addWidget(widget)
    return g


class NumItem(QTreeWidgetItem):
    """Sorts by the numbers kept in UserRole+1 for numeric columns."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a = self.data(col, Qt.UserRole + 1)
        b = other.data(col, Qt.UserRole + 1)
        if a is not None and b is not None:
            return a < b
        return (self.text(col) or "").lower() < (other.text(col) or "").lower()


# ---- the window ---------------------------------------------------------------------------
@ClassInfo({"D-Bus Interface": "org.classic7.TaskManager"})
class _Single(QObject):
    def __init__(self, win):
        super().__init__()
        self.win = win

    @Slot()
    def activate(self):
        self.win.showNormal()
        self.win.raise_()
        self.win.activateWindow()


class TaskManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Task Manager")
        self.setWindowIcon(icon("utilities-system-monitor"))
        self.resize(560, 600)
        self.sampler = td.Sampler()
        self.snap: td.Snapshot | None = None
        self.me = os.getuid()
        self.all_users = False
        self.proc_items: dict[int, NumItem] = {}
        self.cpu_graphs: list[History] = []
        self.per_cpu = True
        self.net_graphs: dict[str, History] = {}
        self.windows: list[dict] = []
        self.bridge = None
        try:
            import kwin_bridge
            self.bridge = kwin_bridge.KWinBridge("TaskManager", self)
            self.bridge.windowsChanged.connect(self._fill_apps)
        except Exception:  # noqa: BLE001 - the Applications tab just stays empty
            self.bridge = None

        self.tabs = QTabWidget()
        self.tabs.addTab(self._apps_tab(), "Applications")
        self.tabs.addTab(self._procs_tab(), "Processes")
        self.tabs.addTab(self._services_tab(), "Services")
        self.tabs.addTab(self._perf_tab(), "Performance")
        self.tabs.addTab(self._net_tab(), "Networking")
        self.tabs.addTab(self._users_tab(), "Users")
        self.tabs.currentChanged.connect(lambda _i: self.tick(force=True))
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(6, 6, 6, 4)
        lay.addWidget(self.tabs)
        self.setCentralWidget(central)
        self._menus()
        self._status()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.set_speed("Normal")
        self.services_timer = QTimer(self)
        self.services_timer.timeout.connect(self._fill_services_if_visible)
        self.services_timer.start(5000)
        QTimer.singleShot(0, lambda: self.tick(force=True))
        QShortcut(QKeySequence("F5"), self, lambda: self.tick(force=True))

    # ---- menus and status bar -------------------------------------------------------------
    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        f.addAction("&New Task (Run...)", sa.run_dialog)
        f.addSeparator()
        f.addAction("E&xit Task Manager", self.close)
        o = mb.addMenu("&Options")
        self.on_top = o.addAction("&Always On Top")
        self.on_top.setCheckable(True)
        self.on_top.toggled.connect(self._always_on_top)
        self.min_on_use = o.addAction("&Minimize On Use")
        self.min_on_use.setCheckable(True)
        self.show_all_act = o.addAction("Show processes from &all users")
        self.show_all_act.setCheckable(True)
        self.show_all_act.toggled.connect(self._show_all)
        v = mb.addMenu("&View")
        v.addAction("&Refresh Now", lambda: self.tick(force=True), QKeySequence("F5"))
        speed = v.addMenu("&Update Speed")
        grp = QActionGroup(self)
        for name in SPEEDS:
            a = speed.addAction(f"&{name}", lambda n=name: self.set_speed(n))
            a.setCheckable(True)
            a.setChecked(name == "Normal")
            grp.addAction(a)
        v.addSeparator()
        hist = v.addMenu("&CPU History")
        g2 = QActionGroup(self)
        for text, per in (("One Graph, &All CPUs", False), ("One Graph &Per CPU", True)):
            a = hist.addAction(text, lambda p=per: self._set_per_cpu(p))
            a.setCheckable(True)
            a.setChecked(per == self.per_cpu)
            g2.addAction(a)
        self.kernel_times = v.addAction("Show &Kernel Times")
        self.kernel_times.setCheckable(True)
        w = mb.addMenu("&Windows")
        w.addAction("&Minimize", lambda: self._window_act("minimize"))
        w.addAction("Ma&ximize", lambda: self._window_act("maximize"))
        w.addAction("&Bring To Front", lambda: self._window_act("activate"))
        s = mb.addMenu("Shut &Down")
        if sa.can_hibernate():
            s.addAction("&Hibernate", sa.hibernate)
        s.addAction("&Sleep", sa.sleep)
        s.addAction("T&urn Off", sa.shut_down)
        s.addAction("&Restart", sa.restart)
        s.addAction("&Log Off", sa.log_off)
        s.addAction("S&witch User", sa.switch_user)
        s.addAction("L&ock Computer", sa.lock)
        h = mb.addMenu("&Help")
        h.addAction("&About Task Manager", lambda: QMessageBox.about(self, "About Task Manager",
                                                                       "Task Manager\nClassic 7"))

    def _status(self):
        sb = self.statusBar()
        self.st_procs = QLabel()
        self.st_cpu = QLabel()
        self.st_mem = QLabel()
        for lab in (self.st_procs, self.st_cpu, self.st_mem):
            lab.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            lab.setContentsMargins(4, 0, 4, 0)
            sb.addWidget(lab, 1)

    def _always_on_top(self, on: bool):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()

    def set_speed(self, name: str):
        ms = SPEEDS[name]
        self.timer.stop()
        if ms:
            self.timer.start(ms)

    # ---- tabs ------------------------------------------------------------------------------
    def _buttons(self, *buttons) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        for b in buttons:
            row.addWidget(b)
        return row

    def _apps_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.apps = QTreeWidget()
        self.apps.setHeaderLabels(["Task", "Status"])
        self.apps.setRootIsDecorated(False)
        self.apps.setColumnWidth(0, 380)
        self.apps.setContextMenuPolicy(Qt.CustomContextMenu)
        self.apps.customContextMenuRequested.connect(self._apps_menu)
        self.apps.itemDoubleClicked.connect(lambda *_: self._window_act("activate"))
        lay.addWidget(self.apps)
        end = QPushButton("&End Task")
        end.clicked.connect(lambda: self._window_act("close"))
        sw = QPushButton("&Switch To")
        sw.clicked.connect(lambda: self._window_act("activate"))
        new = QPushButton("&New Task...")
        new.clicked.connect(sa.run_dialog)
        lay.addLayout(self._buttons(end, sw, new))
        return w

    def _procs_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.procs = QTreeWidget()
        self.procs.setHeaderLabels(["Image Name", "User Name", "CPU", "Memory (Private Working Set)", "Description"])
        self.procs.setRootIsDecorated(False)
        self.procs.setUniformRowHeights(True)
        self.procs.setSortingEnabled(True)
        self.procs.sortByColumn(0, Qt.AscendingOrder)
        for i, wd in enumerate((150, 80, 40, 150, 200)):
            self.procs.setColumnWidth(i, wd)
        self.procs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.procs.customContextMenuRequested.connect(self._procs_menu)
        lay.addWidget(self.procs)
        row = QHBoxLayout()
        self.all_box = QCheckBox("Show processes from all users")
        self.all_box.toggled.connect(self._show_all)
        row.addWidget(self.all_box)
        row.addStretch(1)
        end = QPushButton("&End Process")
        end.clicked.connect(self._end_process)
        row.addWidget(end)
        lay.addLayout(row)
        return w

    def _services_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.svcs = QTreeWidget()
        self.svcs.setHeaderLabels(["Name", "PID", "Description", "Status", "Group"])
        self.svcs.setRootIsDecorated(False)
        self.svcs.setUniformRowHeights(True)
        self.svcs.setSortingEnabled(True)
        self.svcs.sortByColumn(0, Qt.AscendingOrder)
        for i, wd in enumerate((170, 50, 200, 60, 60)):
            self.svcs.setColumnWidth(i, wd)
        self.svcs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.svcs.customContextMenuRequested.connect(self._svcs_menu)
        lay.addWidget(self.svcs)
        b = QPushButton("&Startup Programs...")
        b.clicked.connect(lambda: sa._run(["kcmshell6", "kcm_autostart"]))
        lay.addLayout(self._buttons(b))
        self._services_loaded = False
        return w

    def _perf_tab(self):
        w = QWidget()
        g = QGridLayout(w)
        g.setSpacing(8)
        self.cpu_meter = Meter()
        g.addWidget(boxed("CPU Usage", self.cpu_meter), 0, 0)
        self.cpu_hist_box = QGroupBox("CPU Usage History")
        self.cpu_hist_lay = QGridLayout(self.cpu_hist_box)
        self.cpu_hist_lay.setContentsMargins(6, 4, 6, 6)
        self.cpu_hist_lay.setSpacing(3)
        g.addWidget(self.cpu_hist_box, 0, 1)
        self.mem_meter = Meter()
        g.addWidget(boxed("Memory", self.mem_meter), 1, 0)
        self.mem_hist = History()
        g.addWidget(boxed("Physical Memory Usage History", self.mem_hist), 1, 1)
        g.setRowStretch(0, 1)
        g.setRowStretch(1, 1)
        g.setColumnStretch(1, 1)

        bottom = QGridLayout()
        self.lab = {}

        def group(title, keys):
            box = QGroupBox(title)
            f = QGridLayout(box)
            f.setContentsMargins(8, 4, 8, 6)
            f.setVerticalSpacing(1)
            for i, k in enumerate(keys):
                f.addWidget(QLabel(k), i, 0)
                v = QLabel("")
                v.setAlignment(Qt.AlignRight)
                f.addWidget(v, i, 1)
                self.lab[(title, k)] = v
            return box
        bottom.addWidget(group("Physical Memory (MB)", ["Total", "Cached", "Available", "Free"]), 0, 0)
        bottom.addWidget(group("Kernel Memory (MB)", ["Paged", "Nonpaged"]), 1, 0)
        bottom.addWidget(group("System", ["Handles", "Threads", "Processes", "Up Time", "Commit (MB)"]), 0, 1)
        rm = QPushButton("&Resource Monitor...")
        rm.clicked.connect(lambda: sa._run(["classic7-resmon"]) or sa._run(["plasma-systemmonitor"]))
        rm.setEnabled(bool(shutil.which("classic7-resmon") or shutil.which("plasma-systemmonitor")))
        bottom.addWidget(rm, 1, 1, Qt.AlignRight | Qt.AlignBottom)
        bottom.setColumnStretch(0, 1)
        bottom.setColumnStretch(1, 1)
        g.addLayout(bottom, 2, 0, 1, 2)
        self._build_cpu_graphs()
        return w

    def _build_cpu_graphs(self):
        while self.cpu_hist_lay.count():
            it = self.cpu_hist_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        n = self.sampler.ncpu if self.per_cpu else 1
        cols = n if n <= 4 else 4 if n <= 8 else 8 if n <= 32 else 16
        self.cpu_graphs = []
        for i in range(n):
            h = History(length=60 if n > 4 else 120)
            h.setMinimumSize(QSize(20, 30))
            self.cpu_hist_lay.addWidget(h, i // cols, i % cols)
            self.cpu_graphs.append(h)

    def _set_per_cpu(self, per: bool):
        self.per_cpu = per
        self._build_cpu_graphs()

    def _net_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.net_area = QWidget()
        self.net_lay = QVBoxLayout(self.net_area)
        self.net_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.net_area, 2)
        self.nets = QTreeWidget()
        self.nets.setHeaderLabels(["Adapter Name", "Network Utilization", "Link Speed", "State"])
        self.nets.setRootIsDecorated(False)
        for i, wd in enumerate((200, 120, 90, 90)):
            self.nets.setColumnWidth(i, wd)
        lay.addWidget(self.nets, 1)
        return w

    def _users_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.users = QTreeWidget()
        self.users.setHeaderLabels(["User", "ID", "Status", "Client Name", "Session"])
        self.users.setRootIsDecorated(False)
        lay.addWidget(self.users)
        disc = QPushButton("&Disconnect")
        disc.clicked.connect(self._lock_session)
        logoff = QPushButton("&Logoff")
        logoff.clicked.connect(self._logoff_session)
        msg = QPushButton("Send &Message...")
        msg.setEnabled(False)
        lay.addLayout(self._buttons(disc, logoff, msg))
        return w

    # ---- refreshing ------------------------------------------------------------------------
    def tick(self, force: bool = False):
        tab = self.tabs.currentIndex()
        snap = self.sampler.sample(with_procs=True)
        self.snap = snap
        self._fill_perf(snap)
        self._fill_net(snap)
        if tab == 1 or force:
            self._fill_procs(snap)
        if tab == 0 and self.bridge is not None:
            self.bridge.refresh()
        if tab == 2 and (force or not self._services_loaded):
            self._fill_services()
        if tab == 5:
            self._fill_users()
        self.st_procs.setText(f"Processes: {snap.system['processes']}")
        self.st_cpu.setText(f"CPU Usage: {round(snap.cpu_total)}%")
        self.st_mem.setText(f"Physical Memory: {round(snap.mem['percent'])}%")

    def _fill_apps(self, windows: list[dict]):
        self.windows = windows
        keep = self._current_window()
        self.apps.clear()
        for w in windows:
            it = QTreeWidgetItem([w.get("caption") or w.get("cls") or "", "Running"])
            name = w.get("desktopFile") or w.get("cls") or ""
            it.setIcon(0, icon(name, "application-x-executable"))
            it.setData(0, Qt.UserRole, w)
            self.apps.addTopLevelItem(it)
            if keep and w.get("id") == keep.get("id"):
                it.setSelected(True)
                self.apps.setCurrentItem(it)
        if not windows and (self.bridge is None or not self.bridge.available()):
            QTreeWidgetItem(self.apps, ["(The list of windows is not available)", ""])

    def _current_window(self) -> dict | None:
        it = self.apps.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _window_act(self, what: str):
        w = self._current_window()
        if w and self.bridge is not None:
            self.bridge.act(w["id"], what)
            if what == "activate" and self.min_on_use.isChecked():
                self.showMinimized()
            QTimer.singleShot(600, self.bridge.refresh)

    def _apps_menu(self, pos: QPoint):
        it = self.apps.itemAt(pos)
        if not it or not it.data(0, Qt.UserRole):
            return
        m = QMenu(self)
        m.addAction("&Switch To", lambda: self._window_act("activate"))
        m.addAction("&Bring To Front", lambda: self._window_act("activate"))
        m.addSeparator()
        m.addAction("Mi&nimize", lambda: self._window_act("minimize"))
        m.addAction("Ma&ximize", lambda: self._window_act("maximize"))
        m.addSeparator()
        m.addAction("&End Task", lambda: self._window_act("close"))
        m.addAction("&Go To Process", self._goto_process)
        m.exec(self.apps.viewport().mapToGlobal(pos))

    def _goto_process(self):
        w = self._current_window()
        if not w:
            return
        self.tabs.setCurrentIndex(1)
        self._fill_procs(self.snap)
        it = self.proc_items.get(int(w.get("pid") or 0))
        if it is None and int(w.get("pid") or 0):
            self.all_box.setChecked(True)
            it = self.proc_items.get(int(w["pid"]))
        if it:
            self.procs.setCurrentItem(it)
            self.procs.scrollToItem(it)

    def _show_all(self, on: bool):
        self.all_users = on
        for box in (self.all_box, self.show_all_act):
            if box.isChecked() != on:
                box.blockSignals(True)
                box.setChecked(on)
                box.blockSignals(False)
        if self.snap:
            self._fill_procs(self.snap)

    def _fill_procs(self, snap: td.Snapshot | None):
        if snap is None:
            return
        self.procs.setSortingEnabled(False)
        alive = set()
        for p in snap.procs:
            if not self.all_users and p.uid != self.me:
                continue
            if p.pid in (0, 2) or p.ppid == 2:      # kernel threads are not programs
                continue
            alive.add(p.pid)
            it = self.proc_items.get(p.pid)
            if it is None:
                it = NumItem(self.procs)
                it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
                it.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
                ic = self.sampler.desc.icon_for(p.name, p.exe)
                it.setIcon(0, icon(ic or "", "application-x-executable"))
                self.proc_items[p.pid] = it
            vals = [p.name, p.user, f"{round(p.cpu):02d}", td.fmt_k(p.private), p.description]
            for c, v in enumerate(vals):
                if it.text(c) != v:
                    it.setText(c, v)
            it.setData(2, Qt.UserRole + 1, p.cpu)
            it.setData(3, Qt.UserRole + 1, p.private)
            it.setData(0, Qt.UserRole, p.pid)
        for pid in list(self.proc_items):
            if pid not in alive:
                it = self.proc_items.pop(pid)
                idx = self.procs.indexOfTopLevelItem(it)
                if idx >= 0:
                    self.procs.takeTopLevelItem(idx)
        self.procs.setSortingEnabled(True)

    def _selected_proc(self) -> td.Proc | None:
        it = self.procs.currentItem()
        if not it or not self.snap:
            return None
        pid = it.data(0, Qt.UserRole)
        return next((p for p in self.snap.procs if p.pid == pid), None)

    def _end_process(self, tree: bool = False):
        p = self._selected_proc()
        if not p:
            return
        what = "process tree" if tree else "process"
        box = QMessageBox(QMessageBox.Warning, "Task Manager",
                          f"Do you want to end this {what}?\n\n{p.name}" + (f" ({p.description})" if p.description else ""),
                          parent=self)
        box.setInformativeText("If an open program is associated with this process, it will close and you will "
                               "lose any unsaved data. If you end a system process, it might result in system "
                               "instability. Are you sure you want to continue?")
        end = box.addButton(f"End {what}", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(end)
        box.exec()
        if box.clickedButton() is not end:
            return
        pids = [p.pid]
        if tree:
            try:
                import psutil
                pids += [c.pid for c in psutil.Process(p.pid).children(recursive=True)]
            except Exception:  # noqa: BLE001
                pass
        self._kill(pids, p.uid)

    def _kill(self, pids: list[int], uid: int):
        if uid != self.me:
            subprocess.Popen(["pkexec", "kill", "-TERM", *map(str, pids)], start_new_session=True)
            return
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                QMessageBox.warning(self, "Task Manager", "Access is denied.")
                return

        def force():
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
        QTimer.singleShot(3000, force)
        QTimer.singleShot(300, lambda: self.tick(force=True))

    def _procs_menu(self, pos: QPoint):
        it = self.procs.itemAt(pos)
        if not it:
            return
        p = self._selected_proc()
        if not p:
            return
        m = QMenu(self)
        m.addAction("&Open File Location", lambda: self._open_location(p))
        m.addSeparator()
        m.addAction("&End Process", self._end_process)
        m.addAction("End Process &Tree", lambda: self._end_process(tree=True))
        m.addSeparator()
        prio = m.addMenu("Set &Priority")
        for text, nice in (("&Realtime", -20), ("&High", -10), ("&AboveNormal", -5), ("&Normal", 0),
                           ("&BelowNormal", 5), ("&Low", 19)):
            a = prio.addAction(text, lambda n=nice: self._set_priority(p, n))
            a.setCheckable(True)
            a.setChecked(abs(p.nice - nice) <= 2 if nice not in (-20, 19) else p.nice == nice)
        m.addAction("Set &Affinity...", lambda: self._affinity(p))
        m.addSeparator()
        m.addAction("P&roperties", lambda: self._proc_props(p))
        m.addAction("&Go to Service(s)", lambda: self._goto_service(p))
        m.exec(self.procs.viewport().mapToGlobal(pos))

    def _open_location(self, p: td.Proc):
        if p.exe:
            sa._run(["dolphin", "--select", p.exe])

    def _set_priority(self, p: td.Proc, nice: int):
        try:
            os.setpriority(os.PRIO_PROCESS, p.pid, nice)
        except PermissionError:
            subprocess.Popen(["pkexec", "renice", "-n", str(nice), "-p", str(p.pid)], start_new_session=True)
        except ProcessLookupError:
            pass

    def _affinity(self, p: td.Proc):
        try:
            current = os.sched_getaffinity(p.pid)
        except OSError:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Processor Affinity")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Which processors are allowed to run this process?"))
        grid = QGridLayout()
        boxes = []
        for i in range(self.sampler.ncpu):
            b = QCheckBox(f"CPU {i}")
            b.setChecked(i in current)
            grid.addWidget(b, i // 4, i % 4)
            boxes.append(b)
        lay.addLayout(grid)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() == QDialog.Accepted:
            cpus = {i for i, b in enumerate(boxes) if b.isChecked()}
            if cpus:
                try:
                    os.sched_setaffinity(p.pid, cpus)
                except OSError as e:
                    QMessageBox.warning(self, "Task Manager", f"Access is denied.\n\n{e.strerror}")

    def _proc_props(self, p: td.Proc):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{p.name} Properties")
        f = QFormLayout(dlg)
        for k, v in (("Name:", p.name), ("Description:", p.description or ""), ("Location:", p.exe or ""),
                     ("Command line:", " ".join(p.cmdline)), ("Process ID:", str(p.pid)),
                     ("Parent process:", str(p.ppid)), ("User:", p.user), ("Threads:", str(p.threads)),
                     ("Memory:", td.fmt_k(p.private)), ("Priority (nice):", str(p.nice))):
            lab = QLabel(v)
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            f.addRow(k, lab)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(dlg.accept)
        f.addRow(bb)
        dlg.resize(460, 300)
        dlg.exec()

    def _goto_service(self, p: td.Proc):
        self.tabs.setCurrentIndex(2)
        self._fill_services()
        self.svcs.clearSelection()
        for i in range(self.svcs.topLevelItemCount()):
            it = self.svcs.topLevelItem(i)
            if it.data(1, Qt.UserRole + 1) == p.pid:
                it.setSelected(True)
                self.svcs.scrollToItem(it)

    # services
    def _fill_services_if_visible(self):
        if self.tabs.currentIndex() == 2:
            self._fill_services()

    def _fill_services(self):
        self._services_loaded = True
        rows = td.services(user=False) + td.services(user=True)
        sel = self.svcs.currentItem()
        keep = (sel.text(0), sel.text(4)) if sel else None
        self.svcs.setSortingEnabled(False)
        self.svcs.clear()
        for s in rows:
            it = NumItem([s.name, str(s.pid) if s.pid else "", s.description, s.status, s.group])
            it.setData(1, Qt.UserRole + 1, s.pid)
            self.svcs.addTopLevelItem(it)
            if keep == (s.name, s.group):
                self.svcs.setCurrentItem(it)
        self.svcs.setSortingEnabled(True)

    def _svcs_menu(self, pos: QPoint):
        it = self.svcs.itemAt(pos)
        if not it:
            return
        name, group, running = it.text(0), it.text(4), it.text(3) == "Running"
        m = QMenu(self)
        m.addAction("&Start Service", lambda: self._systemctl("start", name, group)).setEnabled(not running)
        m.addAction("S&top Service", lambda: self._systemctl("stop", name, group)).setEnabled(running)
        m.addAction("&Restart Service", lambda: self._systemctl("restart", name, group)).setEnabled(running)
        m.addSeparator()
        pid = it.data(1, Qt.UserRole + 1)
        go = m.addAction("&Go to Process", lambda: self._goto_pid(pid))
        go.setEnabled(bool(pid))
        m.exec(self.svcs.viewport().mapToGlobal(pos))

    def _systemctl(self, verb: str, name: str, group: str):
        if not td.safe_unit(name):
            return
        argv = ["systemctl"] + (["--user"] if group == "user" else []) + [verb, name + ".service"]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)

        def check():
            if proc.poll() is None:
                QTimer.singleShot(300, check)
                return
            if proc.returncode != 0:
                err = (proc.stderr.read() if proc.stderr else "").strip()
                QMessageBox.warning(self, "Task Manager", f"The service could not be changed.\n\n{err}")
            self._fill_services()
        QTimer.singleShot(300, check)

    def _goto_pid(self, pid: int):
        self.tabs.setCurrentIndex(1)
        it = self.proc_items.get(pid)
        if it is None:
            self.all_box.setChecked(True)
            self._fill_procs(self.snap)
            it = self.proc_items.get(pid)
        if it:
            self.procs.setCurrentItem(it)
            self.procs.scrollToItem(it)

    # performance
    def _fill_perf(self, s: td.Snapshot):
        mb = 1024 * 1024
        self.cpu_meter.set(s.cpu_total / 100, f"{round(s.cpu_total)} %")
        kern = self.kernel_times.isChecked()
        if self.per_cpu and len(self.cpu_graphs) == len(s.cpu_per):
            for i, (g, v) in enumerate(zip(self.cpu_graphs, s.cpu_per)):
                g.push(v / 100, s.kernel_per[i] / 100 if kern and i < len(s.kernel_per) else None)
        elif self.cpu_graphs:
            k = sum(s.kernel_per) / len(s.kernel_per) if s.kernel_per else 0
            self.cpu_graphs[0].push(s.cpu_total / 100, k / 100 if kern else None)
        used = s.mem["used"]
        gb = used / 1024 ** 3
        self.mem_meter.set(used / s.mem["total"] if s.mem["total"] else 0,
                           f"{gb:.2f} GB" if gb >= 1 else f"{used // mb} MB")
        self.mem_hist.push(used / s.mem["total"] if s.mem["total"] else 0)
        L = self.lab
        L[("Physical Memory (MB)", "Total")].setText(f"{s.mem['total'] // mb}")
        L[("Physical Memory (MB)", "Cached")].setText(f"{s.mem['cached'] // mb}")
        L[("Physical Memory (MB)", "Available")].setText(f"{s.mem['available'] // mb}")
        L[("Physical Memory (MB)", "Free")].setText(f"{s.mem['free'] // mb}")
        L[("Kernel Memory (MB)", "Paged")].setText(f"{s.mem['paged'] // mb}")
        L[("Kernel Memory (MB)", "Nonpaged")].setText(f"{s.mem['nonpaged'] // mb}")
        L[("System", "Handles")].setText(f"{s.system['handles']}")
        L[("System", "Threads")].setText(f"{s.system['threads']}")
        L[("System", "Processes")].setText(f"{s.system['processes']}")
        L[("System", "Up Time")].setText(td.fmt_uptime(s.system["uptime"]))
        L[("System", "Commit (MB)")].setText(f"{s.mem['commit'] // mb} / {s.mem['commit_limit'] // mb}")

    # networking
    def _fill_net(self, s: td.Snapshot):
        names = sorted(s.nets)
        if set(names) != set(self.net_graphs):
            while self.net_lay.count():
                it = self.net_lay.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            self.net_graphs = {}
            for n in names:
                h = History(autoscale=True)
                self.net_graphs[n] = h
                self.net_lay.addWidget(boxed(f"{td.adapter_name(n)} ({n})", h))
            if not names:
                self.net_lay.addWidget(QLabel("No network adapters are installed."))
        self.nets.clear()
        for n in names:
            rate, speed, up = s.nets[n]
            util = (rate * 8 / speed) if speed else 0.0
            self.net_graphs[n].push(util)
            speed_text = (f"{speed / 1e9:g} Gbps" if speed >= 1e9 else f"{speed / 1e6:g} Mbps") if speed else ""
            QTreeWidgetItem(self.nets, [f"{td.adapter_name(n)} ({n})", f"{util * 100:.2f} %", speed_text,
                                        "Connected" if up else "Disconnected"])

    # users
    def _fill_users(self):
        self.users.clear()
        for r in td.sessions():
            if r.get("class") not in ("user", ""):
                continue
            it = QTreeWidgetItem([r["user"], r["id"], "Active" if r["state"] == "active" else
                                  "Disconnected" if r["state"] in ("online", "closing") else r["state"].title(),
                                  r["tty"] or "", "Console" if r["seat"] else "Remote"])
            it.setIcon(0, icon("user-identity", "system-users"))
            it.setData(0, Qt.UserRole, r)
            self.users.addTopLevelItem(it)

    def _lock_session(self):
        it = self.users.currentItem()
        if it:
            sa._run(["loginctl", "lock-session", it.data(0, Qt.UserRole)["id"]])

    def _logoff_session(self):
        it = self.users.currentItem()
        if not it:
            return
        r = it.data(0, Qt.UserRole)
        if QMessageBox.question(self, "Task Manager", f"Do you want to log off {r['user']}? Any unsaved data "
                                                       "will be lost.") == QMessageBox.Yes:
            sa._run(["loginctl", "terminate-session", r["id"]])


def main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]] + argv)
    app.setApplicationName("Task Manager")
    app.setDesktopFileName("classic7-taskmgr")
    bus = QDBusConnection.sessionBus()
    if bus.isConnected() and not bus.registerService(SERVICE):
        QDBusInterface(SERVICE, "/", "org.classic7.TaskManager", bus).call("activate")
        return 0
    w = TaskManager()
    single = _Single(w)
    if bus.isConnected():
        bus.registerObject("/", single, QDBusConnection.ExportAllSlots)
    tab = {"--processes": 1, "--services": 2, "--performance": 3, "--networking": 4, "--users": 5}
    for a in argv:
        if a in tab:
            w.tabs.setCurrentIndex(tab[a])
    w.show()
    return app.exec()
