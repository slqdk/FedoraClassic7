"""Resource Monitor, as in Windows 7 (resmon): the processor, memory, disks and network, with a
table per kind of use and a minute of graphs on the right.

    classic7-resmon [--tab overview|cpu|memory|disk|network]

Overview: CPU, Disk, Network and Memory sections, each with its processes. CPU: every process
with threads, CPU now and over the last minute, and the files a process has open (Associated
Handles). Memory: what each process uses and the Physical Memory bar. Disk: the processes reading
and writing, and each drive's active time and space. Network: the processes with connections, the
traffic of each adapter, TCP connections and listening ports.

Linux keeps some numbers to the owner of a process (disk use, open files, connections): processes
of other accounts show what can be read."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import psutil
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QPushButton, QScrollArea, QSplitter, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

APP = "Resource Monitor"
HISTORY = 60
GREEN, BLUE = QColor("#00c000"), QColor("#2a70e0")


# ---- names --------------------------------------------------------------------------------------
_descriptions: dict[str, str] | None = None


def description(name: str, exe: str) -> str:
    """The program's name from its desktop file (firefox -> Firefox), else the executable's name."""
    global _descriptions
    if _descriptions is None:
        _descriptions = {}
        for d in [Path.home() / ".local/share/applications", Path("/usr/share/applications"),
                  Path("/var/lib/flatpak/exports/share/applications")]:
            for f in d.glob("*.desktop") if d.is_dir() else []:
                try:
                    text = f.read_text(errors="replace")
                except OSError:
                    continue
                name_v = exec_v = ""
                in_entry = False
                for line in text.splitlines():
                    if line.startswith("["):
                        in_entry = line.strip() == "[Desktop Entry]"
                    elif in_entry and line.startswith("Name=") and not name_v:
                        name_v = line[5:].strip()
                    elif in_entry and line.startswith("Exec=") and not exec_v:
                        exec_v = line[5:].strip()
                if name_v and exec_v:
                    first = os.path.basename(exec_v.split()[0].strip('"'))
                    _descriptions.setdefault(first, name_v)
    base = os.path.basename(exe) if exe else name
    return _descriptions.get(base) or _descriptions.get(name) or base


def kb(n: float) -> str:
    return f"{int(n / 1024):,}"


def rate(n: float) -> str:
    return f"{int(n):,}"


# ---- graphs -------------------------------------------------------------------------------------
class Graph(QWidget):
    """A black graph with a green grid: one minute of values, newest on the right."""

    def __init__(self, title: str, scale_text: str, maximum: float | None = 100.0, height: int = 100):
        super().__init__()
        self.title = title
        self.scale_text = scale_text
        self.maximum = maximum
        self.series: list[tuple[deque, QColor]] = []
        self.setFixedHeight(height)
        self.setMinimumWidth(200)
        self.offset = 0

    def add_series(self, color: QColor) -> deque:
        d = deque([0.0] * HISTORY, maxlen=HISTORY)
        self.series.append((d, color))
        return d

    def push(self):
        self.offset = (self.offset + 1) % 10
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0, 16, -1, -1)
        p.fillRect(self.rect(), QColor("#ececec"))
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
        p.setFont(f)
        p.setPen(QColor("#222"))
        p.drawText(QRectF(2, 0, self.width() - 4, 15), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        p.drawText(QRectF(2, 0, self.width() - 4, 15), Qt.AlignRight | Qt.AlignVCenter, self.scale_text)
        p.fillRect(r, QColor("black"))
        p.setPen(QPen(QColor("#005000"), 1))
        step = r.width() / 10
        for i in range(11):
            x = r.left() + ((i * step + (10 - self.offset) * step / 10) % (r.width() + 0.001))
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        for i in range(1, 10):
            y = r.top() + i * r.height() / 10
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        top = self.maximum
        if top is None:
            top = max([max(d) for d, _c in self.series] + [1.0]) * 1.1
        for d, color in self.series:
            pts = QPolygonF()
            n = len(d)
            for i, v in enumerate(d):
                x = r.left() + r.width() * i / max(1, n - 1)
                y = r.bottom() - r.height() * min(1.0, max(0.0, v / top))
                pts.append(QPointF(x, y))
            p.setPen(QPen(color, 1.5))
            p.drawPolyline(pts)
        p.setPen(QColor("#888"))
        p.drawRect(r)


class GraphPane(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setFixedWidth(300)
        w = QWidget()
        self.lay = QVBoxLayout(w)
        self.lay.setContentsMargins(6, 6, 6, 6)
        self.lay.setSpacing(8)
        self.lay.addStretch(1)
        self.setWidget(w)

    def add(self, g: Graph) -> Graph:
        self.lay.insertWidget(self.lay.count() - 1, g)
        return g


# ---- collapsible sections -----------------------------------------------------------------------
class HeaderBar(QFrame):
    """The light blue bar of a section; a click folds the section."""

    def __init__(self, on_click):
        super().__init__()
        self.on_click = on_click
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("HeaderBar { border: 1px solid #b6c6dc; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                           " stop:0 #f6f9fd, stop:1 #dbe5f2); }")
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 3, 6, 3)
        self.label = QLabel()
        self.label.setTextFormat(Qt.RichText)
        h.addWidget(self.label, 1)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.on_click()


def square(color: str) -> str:
    return f"<span style='color:{color}; font-size:large'>\u25a0</span>"


class Section(QWidget):
    """A title bar ("CPU  ■ 3% CPU Usage  ■ 100% Maximum Frequency") over a table; click to fold."""

    def __init__(self, title: str, headers: list[str], widths: list[int], sort_col: int = 0,
                 order: Qt.SortOrder = Qt.AscendingOrder):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.open = True
        self.bar = HeaderBar(self.toggle)
        v.addWidget(self.bar)
        self.title = title
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAlternatingRowColors(True)
        self.table.setHeaderLabels(headers)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(sort_col, order)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(150)
        for i, w in enumerate(widths):
            self.table.header().resizeSection(i, w)
        self.table.header().setSectionResizeMode(QHeaderView.Interactive)
        v.addWidget(self.table, 1)
        self.rows: dict[str, QTreeWidgetItem] = {}
        self.set_summary("")

    def toggle(self):
        self.open = not self.open
        self.table.setVisible(self.open)
        self.set_summary(self._summary)

    def set_summary(self, html: str):
        self._summary = html
        arrow = "\u25be" if self.open else "\u25b8"
        self.bar.label.setText(f"<b>{arrow}&nbsp;&nbsp;{self.title}</b>&nbsp;&nbsp;&nbsp;&nbsp;{html}")

    def update_rows(self, rows: list[tuple[str, list, list]]):
        """rows: (key, display texts, sort values). Rows are updated in place, so the selection stays."""
        if not self.open and self.rows:
            return
        sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        seen = set()
        for key, texts, values in rows:
            seen.add(key)
            it = self.rows.get(key)
            if it is None:
                it = SortItem(texts)
                self.table.addTopLevelItem(it)
                self.rows[key] = it
            for c, t in enumerate(texts):
                if it.text(c) != t:
                    it.setText(c, t)
                it.setData(c, Qt.UserRole, values[c] if c < len(values) else None)
        for key in list(self.rows):
            if key not in seen:
                it = self.rows.pop(key)
                self.table.takeTopLevelItem(self.table.indexOfTopLevelItem(it))
        self.table.setSortingEnabled(sorting)


class SortItem(QTreeWidgetItem):
    def __lt__(self, other):
        tree = self.treeWidget()
        c = tree.sortColumn() if tree else 0
        a, b = self.data(c, Qt.UserRole), other.data(c, Qt.UserRole)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a < b
        return self.text(c).lower() < other.text(c).lower()


# ---- sampling --------------------------------------------------------------------------------------
class Sampler:
    """One second's worth of numbers for every table and graph."""

    def __init__(self):
        self.prev_time = time.monotonic()
        self.cpu_hist: dict[int, deque] = {}
        self.io_prev: dict[int, tuple[int, int]] = {}
        self.faults_prev: dict[int, int] = {}
        self.disk_prev = psutil.disk_io_counters(perdisk=True) or {}
        self.net_prev = psutil.net_io_counters(pernic=True) or {}
        self.procs: dict[int, psutil.Process] = {}
        psutil.cpu_percent(percpu=True)
        self.total_faults_prev = self._total_faults()
        self.data: dict = {}

    @staticmethod
    def _total_faults() -> int:
        try:
            for line in Path("/proc/vmstat").read_text().splitlines():
                if line.startswith("pgmajfault "):
                    return int(line.split()[1])
        except OSError:
            pass
        return 0

    @staticmethod
    def _majflt(pid: int) -> int:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            return int(stat.rsplit(")", 1)[1].split()[9])
        except (OSError, IndexError, ValueError):
            return 0

    def sample(self) -> dict:
        now = time.monotonic()
        dt = max(0.2, now - self.prev_time)
        self.prev_time = now
        ncpu = psutil.cpu_count() or 1
        percpu = psutil.cpu_percent(percpu=True)
        total = sum(percpu) / max(1, len(percpu))
        try:
            fr = psutil.cpu_freq()
            freq = (fr.current / fr.max * 100) if fr and fr.max else 100.0
        except (OSError, AttributeError, NotImplementedError):
            freq = 100.0
        procs = []
        alive = set()
        for p in psutil.process_iter(["pid", "name", "exe", "status", "num_threads", "memory_info", "username"]):
            info = p.info
            pid = info["pid"]
            alive.add(pid)
            if pid not in self.procs:
                self.procs[pid] = p
                try:
                    p.cpu_percent(None)
                except psutil.Error:
                    pass
                cpu = 0.0
            else:
                try:
                    cpu = self.procs[pid].cpu_percent(None) / ncpu
                except psutil.Error:
                    cpu = 0.0
            hist = self.cpu_hist.setdefault(pid, deque(maxlen=60))
            hist.append(cpu)
            mem = info.get("memory_info")
            rd = wr = 0.0
            try:
                io = self.procs[pid].io_counters()
                prev = self.io_prev.get(pid)
                if prev:
                    rd, wr = max(0, io.read_bytes - prev[0]) / dt, max(0, io.write_bytes - prev[1]) / dt
                self.io_prev[pid] = (io.read_bytes, io.write_bytes)
            except (psutil.Error, AttributeError, OSError):
                pass
            majflt = self._majflt(pid)
            faults = max(0, majflt - self.faults_prev.get(pid, majflt)) / dt
            self.faults_prev[pid] = majflt
            procs.append({"pid": pid, "name": info.get("name") or "?", "exe": info.get("exe") or "",
                          "status": "Suspended" if info.get("status") == psutil.STATUS_STOPPED else "Running",
                          "threads": info.get("num_threads") or 0, "cpu": cpu, "avg": sum(hist) / len(hist),
                          "rss": mem.rss if mem else 0, "shared": getattr(mem, "shared", 0) if mem else 0,
                          "commit": getattr(mem, "data", 0) if mem else 0, "read": rd, "write": wr,
                          "faults": faults, "user": info.get("username") or ""})
        for gone in set(self.procs) - alive:
            self.procs.pop(gone, None)
            self.cpu_hist.pop(gone, None)
            self.io_prev.pop(gone, None)
            self.faults_prev.pop(gone, None)
        vm = psutil.virtual_memory()
        tf = self._total_faults()
        hard_faults = max(0, tf - self.total_faults_prev) / dt
        self.total_faults_prev = tf
        disks = psutil.disk_io_counters(perdisk=True) or {}
        disk_rates, active = {}, {}
        for name, c in disks.items():
            prev = self.disk_prev.get(name)
            if prev:
                disk_rates[name] = (max(0, c.read_bytes - prev.read_bytes) / dt, max(0, c.write_bytes - prev.write_bytes) / dt)
                busy = getattr(c, "busy_time", 0) - getattr(prev, "busy_time", 0)
                active[name] = min(100.0, max(0.0, busy / (dt * 1000) * 100))
        self.disk_prev = disks
        nets = psutil.net_io_counters(pernic=True) or {}
        net_rates = {}
        for name, c in nets.items():
            prev = self.net_prev.get(name)
            if prev and name != "lo":
                net_rates[name] = (max(0, c.bytes_sent - prev.bytes_sent) / dt, max(0, c.bytes_recv - prev.bytes_recv) / dt)
        self.net_prev = nets
        self.data = {"cpu": total, "percpu": percpu, "freq": freq, "procs": procs, "mem": vm, "hard_faults": hard_faults,
                     "disk_rates": disk_rates, "active": active, "net_rates": net_rates}
        return self.data


def connections() -> list:
    try:
        return psutil.net_connections(kind="inet")
    except (psutil.Error, OSError):
        return []


def installed_memory() -> int:
    base = Path("/sys/devices/system/memory")
    try:
        size = int((base / "block_size_bytes").read_text().strip(), 16)
        blocks = sum(1 for d in base.glob("memory*") if (d / "online").exists() and (d / "online").read_text().strip() == "1")
        return size * blocks
    except (OSError, ValueError):
        return psutil.virtual_memory().total


def meminfo() -> dict[str, int]:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            out[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        pass
    return out


# ---- the physical memory bar ------------------------------------------------------------------------
class MemoryBar(QWidget):
    PARTS = [("Hardware Reserved", QColor("#909090")), ("In Use", QColor("#00a000")), ("Modified", QColor("#ff8c00")),
             ("Standby", QColor("#3070d0")), ("Free", QColor("#a8c8f0"))]

    def __init__(self):
        super().__init__()
        self.values = [0, 0, 0, 0, 0]
        self.setFixedHeight(64)

    def paintEvent(self, _):
        p = QPainter(self)
        total = sum(self.values) or 1
        r = QRectF(4, 4, self.width() - 8, 26)
        x = r.left()
        for (name, color), v in zip(self.PARTS, self.values):
            w = r.width() * v / total
            p.fillRect(QRectF(x, r.top(), w, r.height()), color)
            x += w
        p.setPen(QColor("#666"))
        p.drawRect(r)
        f = p.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() * 0.85))
        p.setFont(f)
        x = 4
        for (name, color), v in zip(self.PARTS, self.values):
            p.fillRect(QRectF(x, 38, 10, 10), color)
            p.setPen(QColor("#222"))
            text = f"{name} {v // (1024 * 1024):,} MB"
            p.drawText(QPointF(x + 14, 47), text)
            x += p.fontMetrics().horizontalAdvance(text) + 30


# ---- tabs -------------------------------------------------------------------------------------------
PROC_HEADERS = (["Image", "PID", "Description", "Status", "Threads", "CPU", "Average CPU"], [150, 60, 170, 80, 60, 50, 80])
MEM_HEADERS = (["Image", "PID", "Hard Faults/sec", "Commit (KB)", "Working Set (KB)", "Shareable (KB)", "Private (KB)"],
               [150, 60, 100, 90, 110, 100, 90])
DISK_HEADERS = (["Image", "PID", "Read (B/sec)", "Write (B/sec)", "Total (B/sec)"], [150, 60, 110, 110, 110])
NET_HEADERS = (["Image", "PID", "Address", "Connections"], [150, 60, 260, 90])


def proc_rows(procs) -> list:
    return [(str(p["pid"]), [p["name"], str(p["pid"]), description(p["name"], p["exe"]), p["status"], str(p["threads"]),
                             f"{round(p['cpu'])}", f"{p['avg']:.2f}"],
             [p["name"].lower(), p["pid"], "", "", p["threads"], p["cpu"], p["avg"]]) for p in procs]


def mem_rows(procs) -> list:
    out = []
    for p in procs:
        if not p["rss"]:
            continue
        private = max(0, p["rss"] - p["shared"])
        out.append((str(p["pid"]), [p["name"], str(p["pid"]), rate(p["faults"]), kb(p["commit"]), kb(p["rss"]),
                                    kb(p["shared"]), kb(private)],
                    [p["name"].lower(), p["pid"], p["faults"], p["commit"], p["rss"], p["shared"], private]))
    return out


def disk_rows(procs) -> list:
    return [(str(p["pid"]), [p["name"], str(p["pid"]), rate(p["read"]), rate(p["write"]), rate(p["read"] + p["write"])],
             [p["name"].lower(), p["pid"], p["read"], p["write"], p["read"] + p["write"]])
            for p in procs if p["read"] or p["write"]]


def net_rows(procs, conns) -> list:
    by_pid: dict[int, list] = {}
    for c in conns:
        if c.pid and c.raddr:
            by_pid.setdefault(c.pid, []).append(c)
    names = {p["pid"]: p["name"] for p in procs}
    out = []
    for pid, cs in by_pid.items():
        addr = cs[0].raddr.ip
        out.append((str(pid), [names.get(pid, "?"), str(pid), addr, str(len(cs))],
                    [names.get(pid, "?").lower(), pid, addr, len(cs)]))
    return out


def cpu_summary(d: dict) -> str:
    return (f"{square(GREEN.name())} {round(d['cpu'])}% CPU Usage&nbsp;&nbsp;&nbsp;"
            f"{square(BLUE.name())} {round(d['freq'])}% Maximum Frequency")


class Tab(QWidget):
    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        split = QSplitter(Qt.Horizontal)
        left = QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.sections = QVBoxLayout(inner)
        self.sections.setContentsMargins(4, 4, 4, 4)
        self.sections.setSpacing(4)
        left.setWidget(inner)
        split.addWidget(left)
        self.graphs = GraphPane()
        split.addWidget(self.graphs)
        split.setStretchFactor(0, 1)
        h.addWidget(split)

    def section(self, s: Section) -> Section:
        self.sections.addWidget(s, 1)
        return s


class ResourceMonitor(QMainWindow):
    def __init__(self, tab: str = ""):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon.fromTheme("utilities-system-monitor"))
        self.sampler = Sampler()
        self.firewall: tuple[bool, set[str], set[str]] | None = None
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._menu()
        self._overview()
        self._cpu()
        self._memory()
        self._disk()
        self._network()
        idx = {"overview": 0, "cpu": 1, "memory": 2, "disk": 3, "network": 4}.get(tab, 0)
        self.tabs.setCurrentIndex(idx)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.slow = 0
        self.resize(1100, 720)
        QTimer.singleShot(300, self.tick)

    def _menu(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        f.addAction("E&xit", self.close)
        m = mb.addMenu("&Monitor")
        self.stop_act = QAction("Stop Monitoring", self)
        self.stop_act.triggered.connect(lambda: self.timer.stop())
        self.start_act = QAction("Start Monitoring", self)
        self.start_act.triggered.connect(lambda: self.timer.start(1000))
        m.addAction(self.stop_act)
        m.addAction(self.start_act)
        h = mb.addMenu("&Help")
        h.addAction("About Resource Monitor", lambda: None)

    # -- tabs ----------------------------------------------------------------------------------------
    def _overview(self):
        t = Tab()
        self.ov_cpu = t.section(Section("CPU", *PROC_HEADERS, 5, Qt.DescendingOrder))
        self.ov_disk = t.section(Section("Disk", *DISK_HEADERS, 4, Qt.DescendingOrder))
        self.ov_net = t.section(Section("Network", *NET_HEADERS, 3, Qt.DescendingOrder))
        self.ov_mem = t.section(Section("Memory", *MEM_HEADERS, 4, Qt.DescendingOrder))
        self.g_cpu = t.graphs.add(Graph("CPU", "100%"))
        self.h_cpu = self.g_cpu.add_series(GREEN)
        self.h_freq = self.g_cpu.add_series(BLUE)
        self.g_disk = t.graphs.add(Graph("Disk", "", None))
        self.h_disk = self.g_disk.add_series(GREEN)
        self.g_net = t.graphs.add(Graph("Network", "", None))
        self.h_net = self.g_net.add_series(GREEN)
        self.g_mem = t.graphs.add(Graph("Memory", "100%"))
        self.h_mem = self.g_mem.add_series(GREEN)
        self.h_faults_ov = self.g_mem.add_series(BLUE)
        self.tabs.addTab(t, "Overview")

    def _cpu(self):
        t = Tab()
        self.cpu_procs = t.section(Section("Processes", *PROC_HEADERS, 5, Qt.DescendingOrder))
        handles = QWidget()
        hv = QVBoxLayout(handles)
        hv.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.handle_search = QLineEdit()
        self.handle_search.setPlaceholderText("Search Handles (a file or folder name)")
        self.handle_search.returnPressed.connect(self.search_handles)
        row.addWidget(self.handle_search, 1)
        go = QPushButton("Search")
        go.clicked.connect(self.search_handles)
        row.addWidget(go)
        hv.addLayout(row)
        self.handles = Section("Associated Handles", ["Image", "PID", "Handle Type", "Handle Name"], [150, 60, 90, 400])
        hv.addWidget(self.handles, 1)
        t.sections.addWidget(handles, 1)
        self.g_cpu_total = t.graphs.add(Graph("CPU - Total", "100%"))
        self.h_cpu_total = self.g_cpu_total.add_series(GREEN)
        self.h_cpu_freq = self.g_cpu_total.add_series(BLUE)
        self.core_graphs = []
        for i in range(psutil.cpu_count() or 1):
            g = t.graphs.add(Graph(f"CPU {i}", "100%", height=64))
            self.core_graphs.append((g, g.add_series(GREEN)))
        self.tabs.addTab(t, "CPU")

    def _memory(self):
        t = Tab()
        self.mem_procs = t.section(Section("Processes", *MEM_HEADERS, 4, Qt.DescendingOrder))
        phys = QWidget()
        pv = QVBoxLayout(phys)
        pv.setContentsMargins(0, 0, 0, 0)
        head = QLabel("  Physical Memory")
        head.setStyleSheet("padding: 3px; border: 1px solid #b6c6dc; background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                           " stop:0 #f6f9fd, stop:1 #dbe5f2);")
        pv.addWidget(head)
        self.mem_bar = MemoryBar()
        pv.addWidget(self.mem_bar)
        self.mem_text = QLabel()
        self.mem_text.setStyleSheet("padding-left: 6px;")
        pv.addWidget(self.mem_text)
        t.sections.addWidget(phys)
        self.g_used = t.graphs.add(Graph("Used Physical Memory", "100%"))
        self.h_used = self.g_used.add_series(GREEN)
        self.g_commit = t.graphs.add(Graph("Commit Charge", "100%"))
        self.h_commit = self.g_commit.add_series(GREEN)
        self.g_faults = t.graphs.add(Graph("Hard Faults/sec", "", None))
        self.h_faults = self.g_faults.add_series(GREEN)
        self.tabs.addTab(t, "Memory")

    def _disk(self):
        t = Tab()
        self.disk_procs = t.section(Section("Processes with Disk Activity", *DISK_HEADERS, 4, Qt.DescendingOrder))
        self.storage = t.section(Section("Storage", ["Logical Disk", "Physical Disk", "Active Time (%)",
                                                     "Available Space (MB)", "Total Space (MB)"], [180, 120, 110, 140, 120]))
        self.g_disk2 = t.graphs.add(Graph("Disk", "", None))
        self.h_disk2 = self.g_disk2.add_series(GREEN)
        self.disk_graphs: dict[str, tuple[Graph, deque]] = {}
        self.disk_tab = t
        self.tabs.addTab(t, "Disk")

    def _network(self):
        t = Tab()
        self.net_procs = t.section(Section("Processes with Network Activity", *NET_HEADERS))
        self.net_act = t.section(Section("Network Activity", ["Adapter", "Send (B/sec)", "Receive (B/sec)",
                                                              "Total (B/sec)"], [180, 120, 120, 120]))
        self.tcp = t.section(Section("TCP Connections", ["Image", "PID", "Local Address", "Local Port", "Remote Address",
                                                         "Remote Port", "State"], [140, 60, 140, 80, 160, 90, 100]))
        self.listen = t.section(Section("Listening Ports", ["Image", "PID", "Address", "Port", "Protocol",
                                                            "Firewall Status"], [140, 60, 160, 70, 80, 220]))
        self.g_net2 = t.graphs.add(Graph("Network", "", None))
        self.h_net2 = self.g_net2.add_series(GREEN)
        self.g_tcp = t.graphs.add(Graph("TCP Connections", "", None))
        self.h_tcp = self.g_tcp.add_series(GREEN)
        self.tabs.addTab(t, "Network")

    # -- updates --------------------------------------------------------------------------------------
    def tick(self):
        d = self.sampler.sample()
        procs = d["procs"]
        cur = self.tabs.currentIndex()
        vm = d["mem"]
        disk_total = sum(r + w for r, w in d["disk_rates"].values())
        net_total = sum(s + r for s, r in d["net_rates"].values())
        top_active = max(d["active"].values(), default=0.0)
        # graphs keep running on every tab
        self.h_cpu.append(d["cpu"])
        self.h_freq.append(d["freq"])
        self.h_disk.append(disk_total)
        self.h_net.append(net_total * 8)
        self.h_mem.append(vm.percent)
        self.h_faults_ov.append(min(100.0, d["hard_faults"]))
        self.h_cpu_total.append(d["cpu"])
        self.h_cpu_freq.append(d["freq"])
        for (g, h), v in zip(self.core_graphs, d["percpu"]):
            h.append(v)
        self.h_used.append(vm.percent)
        swap = psutil.swap_memory()
        commit_limit = vm.total + swap.total
        committed = (vm.total - vm.available) + swap.used
        self.h_commit.append(committed / commit_limit * 100 if commit_limit else 0)
        self.h_faults.append(d["hard_faults"])
        self.h_disk2.append(disk_total)
        self.h_net2.append(net_total * 8)
        conns = connections() if cur in (0, 4) or self.slow % 5 == 0 else None
        if conns is not None:
            self.h_tcp.append(sum(1 for c in conns if c.type == socket.SOCK_STREAM and c.status == "ESTABLISHED"))
        for g in (self.g_cpu, self.g_disk, self.g_net, self.g_mem, self.g_cpu_total, self.g_used, self.g_commit,
                  self.g_faults, self.g_disk2, self.g_net2, self.g_tcp, *[g for g, _h in self.core_graphs]):
            g.push()
        self.g_disk.scale_text = f"{max(self.h_disk) / 1048576:.0f} MB/sec" if max(self.h_disk) >= 1048576 else "1 MB/sec"
        self.g_net.scale_text = f"{max(self.h_net) / 1e6:.0f} Mbps" if max(self.h_net) >= 1e6 else "1 Mbps"
        self.g_disk2.scale_text = self.g_disk.scale_text
        self.g_net2.scale_text = self.g_net.scale_text
        # the visible tab's tables
        if cur == 0:
            self.ov_cpu.set_summary(cpu_summary(d))
            self.ov_cpu.update_rows(proc_rows(procs))
            self.ov_disk.set_summary(f"{square(GREEN.name())} {int(disk_total / 1024):,} KB/sec Disk I/O&nbsp;&nbsp;&nbsp;"
                                     f"{square(BLUE.name())} {round(top_active)}% Highest Active Time")
            self.ov_disk.update_rows(disk_rows(procs))
            self.ov_net.set_summary(f"{square(GREEN.name())} {int(net_total * 8 / 1000):,} Kbps Network I/O")
            if conns is not None:
                self.ov_net.update_rows(net_rows(procs, conns))
            self.ov_mem.set_summary(f"{square(BLUE.name())} {round(d['hard_faults'])} Hard Faults/sec&nbsp;&nbsp;&nbsp;"
                                    f"{square(GREEN.name())} {round(vm.percent)}% Used Physical Memory")
            self.ov_mem.update_rows(mem_rows(procs))
        elif cur == 1:
            self.cpu_procs.set_summary(cpu_summary(d))
            self.cpu_procs.update_rows(proc_rows(procs))
        elif cur == 2:
            self.mem_procs.set_summary(f"{square(GREEN.name())} {round(vm.percent)}% Used Physical Memory")
            self.mem_procs.update_rows(mem_rows(procs))
            mi = meminfo()
            installed = installed_memory()
            dirty = mi.get("Dirty", 0)
            standby = max(0, mi.get("Cached", 0) + mi.get("Buffers", 0) - dirty)
            free = vm.free
            in_use = max(0, vm.total - free - standby - dirty)
            self.mem_bar.values = [max(0, installed - vm.total), in_use, dirty, standby, free]
            self.mem_bar.update()
            self.mem_text.setText(f"Available {vm.available // 1048576:,} MB     Cached {standby // 1048576:,} MB     "
                                  f"Total {vm.total // 1048576:,} MB     Installed {installed // 1048576:,} MB")
        elif cur == 3:
            self.disk_procs.set_summary(f"{square(GREEN.name())} {int(disk_total / 1024):,} KB/sec Disk I/O")
            self.disk_procs.update_rows(disk_rows(procs))
            self._storage(d)
        elif cur == 4:
            self.net_procs.set_summary(f"{square(GREEN.name())} {int(net_total * 8 / 1000):,} Kbps Network I/O")
            if conns is not None:
                self.net_procs.update_rows(net_rows(procs, conns))
                self._tcp(procs, conns)
            self.net_act.update_rows([(n, [n, rate(s), rate(r), rate(s + r)], [n, s, r, s + r])
                                      for n, (s, r) in d["net_rates"].items()])
        self.slow += 1

    def _storage(self, d: dict):
        rows = []
        dev_of: dict[str, str] = {}
        for part in psutil.disk_partitions(all=False):
            if part.mountpoint.startswith(("/sysroot", "/boot", "/var/lib/containers", "/run/")) or \
                    part.fstype in ("squashfs", "overlay", "composefs", "erofs"):
                continue
            base = os.path.basename(part.device)
            disk = base.rstrip("0123456789")
            if disk.startswith("nvme") and "p" in base:
                disk = base.rsplit("p", 1)[0]
            if base in dev_of:
                continue
            dev_of[base] = part.mountpoint
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            act = d["active"].get(base, d["active"].get(disk, 0.0))
            rows.append((base, [f"{part.mountpoint} ({part.fstype})", disk, f"{act:.2f}", f"{u.free // 1048576:,}",
                                f"{u.total // 1048576:,}"], [part.mountpoint, disk, act, u.free, u.total]))
        self.storage.update_rows(rows)

    def _tcp(self, procs, conns):
        names = {p["pid"]: p["name"] for p in procs}
        tcp, listen = [], []
        if self.firewall is None:
            self.firewall = firewall_ports()
        for c in conns:
            name = names.get(c.pid, "System") if c.pid else "-"
            pid = str(c.pid) if c.pid else "-"
            proto = "TCP" if c.type == socket.SOCK_STREAM else "UDP"
            if c.status == "LISTEN" or (proto == "UDP" and not c.raddr):
                key = f"{proto}:{c.laddr.ip}:{c.laddr.port}"
                listen.append((key, [name, pid, c.laddr.ip, str(c.laddr.port), proto,
                                     firewall_status(self.firewall, c.laddr.port, proto, c.laddr.ip)],
                               [name.lower(), c.pid or 0, c.laddr.ip, c.laddr.port, proto, ""]))
            elif proto == "TCP" and c.raddr:
                key = f"{c.laddr.ip}:{c.laddr.port}-{c.raddr.ip}:{c.raddr.port}"
                tcp.append((key, [name, pid, c.laddr.ip, str(c.laddr.port), c.raddr.ip, str(c.raddr.port),
                                  c.status.title().replace("_", " ")],
                            [name.lower(), c.pid or 0, c.laddr.ip, c.laddr.port, c.raddr.ip, c.raddr.port, c.status]))
        self.tcp.update_rows(tcp)
        self.listen.update_rows(listen)

    def search_handles(self):
        text = self.handle_search.text().strip().lower()
        rows = []
        if text:
            for p in psutil.process_iter(["pid", "name"]):
                try:
                    files = p.open_files()
                except psutil.Error:
                    continue
                for f in files:
                    if text in f.path.lower():
                        rows.append((f"{p.pid}:{f.fd}", [p.info["name"], str(p.pid), "File", f.path],
                                     [p.info["name"].lower(), p.pid, "File", f.path]))
                try:
                    cwd = p.cwd()
                    if text in cwd.lower():
                        rows.append((f"{p.pid}:cwd", [p.info["name"], str(p.pid), "Folder", cwd],
                                     [p.info["name"].lower(), p.pid, "Folder", cwd]))
                except psutil.Error:
                    pass
        self.handles.set_summary(f"{len(rows)} found" if text else "")
        self.handles.update_rows(rows)


# ---- firewall status of listening ports --------------------------------------------------------------
def firewall_ports() -> tuple[bool, set[str], set[str]]:
    """(firewall running, open ports like '22/tcp', open service names) of the default zone."""
    try:
        state = subprocess.run(["firewall-cmd", "--state"], capture_output=True, text=True, timeout=5)
        if state.returncode != 0:
            return False, set(), set()
        ports = subprocess.run(["firewall-cmd", "--list-ports"], capture_output=True, text=True, timeout=5).stdout.split()
        services = subprocess.run(["firewall-cmd", "--list-services"], capture_output=True, text=True,
                                  timeout=5).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return False, set(), set()
    open_ports = set()
    for p in ports:
        if "-" in p.split("/")[0]:
            lo, hi = p.split("/")[0].split("-")
            proto = p.split("/")[1]
            open_ports.add(f"{lo}-{hi}/{proto}")
        else:
            open_ports.add(p)
    svc_ports = set()
    for s in services:
        try:
            out = subprocess.run(["firewall-cmd", f"--info-service={s}"], capture_output=True, text=True,
                                 timeout=5).stdout
            for line in out.splitlines():
                if line.strip().startswith("ports:"):
                    svc_ports.update(line.split(":", 1)[1].split())
        except (OSError, subprocess.SubprocessError):
            continue
    return True, open_ports | svc_ports, set(services)


def firewall_status(fw: tuple[bool, set[str], set[str]], port: int, proto: str, ip: str) -> str:
    running, ports, _services = fw
    if ip.startswith(("127.", "::1")):
        return "Not applicable (this computer only)"
    if not running:
        return "Not restricted (firewall off)"
    p = proto.lower()
    for entry in ports:
        num, _, pr = entry.partition("/")
        if pr != p:
            continue
        if "-" in num:
            lo, hi = num.split("-")
            if int(lo) <= port <= int(hi):
                return "Allowed, not restricted"
        elif num.isdigit() and int(num) == port:
            return "Allowed, not restricted"
    return "Not allowed"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1].strip())
        return 0
    tab = argv[argv.index("--tab") + 1] if "--tab" in argv and argv.index("--tab") + 1 < len(argv) else ""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-resmon")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-resmon")
    w = ResourceMonitor(tab)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
