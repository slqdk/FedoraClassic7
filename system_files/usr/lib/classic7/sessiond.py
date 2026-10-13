"""Classic 7 session helper (classic7-sessiond.service, started before Plasma's desktop).

 * The Windows 7 copy / move / delete progress window. KDE programs report file operations to the
   D-Bus service org.kde.kuiserver / org.kde.JobViewServer, which Plasma's desktop normally takes
   to show them as notifications. This helper takes those names first (its unit runs before the
   desktop), so the operations come here and get the Windows 7 window: "Copying 12 items (1.25 GB)
   from Downloads to Documents", time remaining, a progress bar, More details, Cancel. If the names
   are taken, Plasma keeps showing them as before. The window's taskbar button, and the button of
   the program that started the operation (Explorer), show the progress.
 * Keeps the desktop's Recycle Bin icon full or empty, whoever puts files in it or empties it.

/usr/libexec/classic7-sessiond takes the D-Bus names before anything slow is loaded, then calls
main() here."""
from __future__ import annotations

import os
import sys
import time
import urllib.parse
from collections import deque

import dbus
import dbus.service

from PySide6.QtCore import QFileSystemWatcher, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QToolButton, QVBoxLayout, QWidget)

ERR_USER_CANCELED = 1
SHOW_AFTER = 1.0            # seconds: quick operations never show a window, as in Windows
SERVER_PATH = "/JobViewServer"
PROGRESS_APP = "classic7-progress"


# ---- text -----------------------------------------------------------------------------------
def short_size(n: int) -> str:
    if n < 1024:
        return f"{n:,} bytes"
    units = ["KB", "MB", "GB", "TB"]
    v, i = n / 1024, 0
    while v >= 1000 and i < len(units) - 1:
        v /= 1024
        i += 1
    s = f"{int(v)}" if v >= 100 else (f"{int(v * 10) / 10:.1f}" if v >= 10 else f"{int(v * 100) / 100:.2f}")
    return f"{s} {units[i]}"


def remaining_text(secs: float | None) -> str:
    """Windows 7's wording: 'About 25 seconds', 'About 1 minute', 'About 1 hour and 5 minutes'."""
    if secs is None:
        return "Calculating..."
    secs = max(1, int(secs + 0.5))
    if secs < 50:
        n = max(5, -(-secs // 5) * 5) if secs < 20 else -(-secs // 10) * 10
        return f"About {n} seconds"
    mins = (secs + 30) // 60
    if mins < 60:
        return f"About {mins} minute{'s' if mins != 1 else ''}"
    h, m = divmod(mins, 60)
    hours = f"{h} hour{'s' if h != 1 else ''}"
    return f"About {hours} and {m} minute{'s' if m != 1 else ''}" if m else f"About {hours}"


def to_path(text: str) -> str:
    """A URL or path from KIO's descriptions, as a path when it is a local one."""
    if not text:
        return ""
    if text.startswith("file://"):
        return urllib.parse.unquote(urllib.parse.urlparse(text).path)
    return text


def folder_link(path: str) -> str:
    """'Downloads (/home/me/Downloads)' with the name as a link, as Windows shows source and target."""
    if not path:
        return ""
    if path.startswith("trash:"):
        return "Recycle Bin"
    p = path.rstrip("/") or "/"
    name = os.path.basename(p) or p
    esc = (lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    if p.startswith("/"):
        url = QUrl.fromLocalFile(p).toString()
        return f"<a href='{url}' style='color:#0645ad; text-decoration:none'>{esc(name)}</a> ({esc(p)})"
    return esc(p)


def parent_of(path: str) -> str:
    if not path or "..." in path or "…" in path:     # KIO squeezes long paths in the middle
        return ""
    if path.startswith("/"):
        return os.path.dirname(path.rstrip("/")) or "/"
    if "://" in path or path.startswith("trash:"):
        return path.rsplit("/", 1)[0] if path.count("/") > 2 else path
    return ""


# ---- one operation --------------------------------------------------------------------------
class Job:
    def __init__(self, view: "JobView", desktop_entry: str, capabilities: int, state: dict):
        self.view = view
        self.desktop_entry = desktop_entry
        self.can_cancel = bool(capabilities & 1)
        self.state: dict = {}
        self.started = time.monotonic()
        self.samples: deque = deque(maxlen=40)
        self.update(state)

    def update(self, d: dict):
        self.state.update(d)
        pb = self.state.get("processedBytes")
        if pb is not None:
            self.samples.append((time.monotonic(), int(pb)))

    def get(self, key, default=0):
        return self.state.get(key, default)

    @property
    def title(self) -> str:
        return str(self.get("title", "")) or str(self.get("infoMessage", "")) or "Working"

    def kind(self) -> str:
        t = self.title.lower()
        dest = str(self.get("descriptionValue2", "")) + str(self.get("destUrl", ""))
        if t.startswith("moving") and "trash:" in dest:
            return "trash"
        for k in ("copying", "moving", "deleting", "renaming", "transferring"):
            if t.startswith(k):
                return k
        return "other"

    def speed(self) -> float | None:
        s = int(self.get("speed", 0) or 0)
        if s > 0:
            return float(s)
        if len(self.samples) >= 2:
            (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
            if t1 - t0 > 0.5 and b1 > b0:
                return (b1 - b0) / (t1 - t0)
        return None

    def percent(self) -> int | None:
        if "percent" in self.state:
            return max(0, min(100, int(self.get("percent"))))
        tb, pb = int(self.get("totalBytes", 0)), int(self.get("processedBytes", 0))
        if tb > 0:
            return max(0, min(100, pb * 100 // tb))
        return None

    def remaining(self) -> float | None:
        tb, pb = int(self.get("totalBytes", 0)), int(self.get("processedBytes", 0))
        sp = self.speed()
        if tb <= 0 or not sp or time.monotonic() - self.started < 2:
            return None
        return max(0.0, (tb - pb) / sp)

    def items(self) -> tuple[int, int]:
        total = int(self.get("totalFiles", 0)) or int(self.get("totalItems", 0))
        done = int(self.get("processedFiles", 0)) or int(self.get("processedItems", 0))
        return total, done

    def source_dir(self) -> str:
        return parent_of(to_path(str(self.get("descriptionValue1", ""))))

    def dest_dir(self) -> str:
        dest = to_path(str(self.get("destUrl", "")))
        if dest:
            return dest
        return parent_of(to_path(str(self.get("descriptionValue2", ""))))

    def headline(self) -> str:
        kind = self.kind()
        verb = {"copying": "Copying", "moving": "Moving", "trash": "Moving", "deleting": "Deleting",
                "renaming": "Renaming", "transferring": "Transferring"}.get(kind, self.title)
        total, _done = self.items()
        tb = int(self.get("totalBytes", 0))
        if not total:
            return f"{verb}..."
        size = f" ({short_size(tb)})" if tb and kind != "deleting" else ""
        return f"{verb} {total:,} item{'s' if total != 1 else ''}{size}"

    def route(self) -> str:
        kind = self.kind()
        src, dst = self.source_dir(), self.dest_dir()
        if kind == "trash":
            return f"from {folder_link(src)} to Recycle Bin" if src else "to the Recycle Bin"
        if kind == "deleting":
            return f"from {folder_link(src)}" if src else ""
        if kind in ("copying", "moving", "transferring", "renaming"):
            parts = []
            if src:
                parts.append(f"from {folder_link(src)}")
            if dst:
                parts.append(f"to {folder_link(dst)}")
            return " ".join(parts)
        lines = []
        for i in (1, 2):
            lab, val = self.get(f"descriptionLabel{i}", ""), self.get(f"descriptionValue{i}", "")
            if val:
                lines.append(f"{lab}: {val}" if lab else str(val))
        return "<br>".join(lines)


# ---- the window -----------------------------------------------------------------------------
class JobPanel(QFrame):
    def __init__(self, job: Job, window: "JobsWindow"):
        super().__init__()
        self.job = job
        self.window_ = window
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 6)
        v.setSpacing(4)
        self.head = QLabel()
        f = self.head.font()
        f.setPointSizeF(f.pointSizeF() * 1.25)
        self.head.setFont(f)
        self.head.setStyleSheet("color: #1e3287;")
        v.addWidget(self.head)
        self.route = QLabel()
        self.route.setTextFormat(Qt.RichText)
        self.route.setWordWrap(True)
        self.route.setOpenExternalLinks(False)
        self.route.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
        v.addWidget(self.route)
        self.left = QLabel()
        f2 = self.left.font()
        f2.setPointSizeF(f2.pointSizeF() * 1.1)
        self.left.setFont(f2)
        v.addWidget(self.left)
        row = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(18)
        row.addWidget(self.bar, 1)
        self.stop = QToolButton()
        self.stop.setIcon(QIcon.fromTheme("process-stop", QIcon.fromTheme("dialog-cancel")))
        self.stop.setIconSize(QSize(16, 16))
        self.stop.setAutoRaise(True)
        self.stop.setToolTip("Cancel")
        self.stop.setEnabled(job.can_cancel)
        self.stop.clicked.connect(self.cancel)
        row.addWidget(self.stop)
        v.addLayout(row)
        self.details = QWidget()
        g = QGridLayout(self.details)
        g.setContentsMargins(0, 6, 0, 0)
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(3)
        self.fields = {}
        for r, name in enumerate(("Name:", "From:", "To:", "Time remaining:", "Items remaining:", "Speed:")):
            lab = QLabel(name)
            lab.setStyleSheet("color: #555;")
            val = QLabel()
            val.setTextFormat(Qt.RichText)
            val.linkActivated.connect(lambda url: QDesktopServices.openUrl(QUrl(url)))
            g.addWidget(lab, r, 0, Qt.AlignLeft | Qt.AlignTop)
            g.addWidget(val, r, 1)
            self.fields[name] = (lab, val)
        g.setColumnStretch(1, 1)
        v.addWidget(self.details)
        self.refresh()

    def cancel(self):
        self.stop.setEnabled(False)
        self.job.view.cancelRequested()

    def set_detailed(self, on: bool):
        self.details.setVisible(on)

    def refresh(self):
        j = self.job
        self.head.setText(j.headline())
        route = j.route()
        self.route.setText(route)
        self.route.setVisible(bool(route))
        pct = j.percent()
        if pct is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 100)
            self.bar.setValue(pct)
        rem = j.remaining()
        suspended = bool(j.get("suspended", False))
        if suspended:
            self.left.setText("Paused")
        elif rem is None:
            self.left.setText("Calculating...")
        else:
            self.left.setText(f"{remaining_text(rem)} remaining")
        name = os.path.basename(to_path(str(j.get("descriptionValue1", ""))).rstrip("/"))
        total, done = j.items()
        tb, pb = int(j.get("totalBytes", 0)), int(j.get("processedBytes", 0))
        sp = j.speed()
        values = {"Name:": name, "From:": folder_link(j.source_dir()),
                  "To:": "Recycle Bin" if j.kind() == "trash" else folder_link(j.dest_dir()),
                  "Time remaining:": remaining_text(rem) if rem is not None else "Calculating...",
                  "Items remaining:": (f"{max(0, total - done):,} ({short_size(max(0, tb - pb))})" if total else ""),
                  "Speed:": f"{short_size(int(sp))}/second" if sp else ""}
        for key, (lab, val) in self.fields.items():
            text = values.get(key, "")
            val.setText(text)
            lab.setVisible(bool(text))
            val.setVisible(bool(text))


class JobsWindow(QWidget):
    """One window for all running operations, as Windows 7 stacks them."""

    def __init__(self, ui: "JobsUI"):
        super().__init__()
        self.ui = ui
        self.setWindowIcon(QIcon.fromTheme("edit-copy", QIcon.fromTheme("document-save")))
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.detailed = False
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.body = QWidget()
        self.body.setAutoFillBackground(True)
        pal = self.body.palette()
        pal.setColor(self.body.backgroundRole(), Qt.white)
        self.body.setPalette(pal)
        self.panels_box = QVBoxLayout(self.body)
        self.panels_box.setContentsMargins(0, 0, 0, 8)
        self.panels_box.setSpacing(0)
        v.addWidget(self.body, 1)
        foot = QFrame()
        foot.setFrameShape(QFrame.NoFrame)
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(12, 8, 12, 10)
        self.more = QToolButton()
        self.more.setAutoRaise(True)
        self.more.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more.clicked.connect(self.toggle_details)
        fl.addWidget(self.more)
        fl.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_all)
        fl.addWidget(self.cancel_btn)
        v.addWidget(foot)
        self.panels: dict[str, JobPanel] = {}
        self.setFixedWidth(460)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, False)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        self._more_text()

    def _more_text(self):
        self.more.setText("Fewer details" if self.detailed else "More details")
        self.more.setIcon(QIcon.fromTheme("arrow-up" if self.detailed else "arrow-down",
                                          QIcon.fromTheme("go-up" if self.detailed else "go-down")))

    def toggle_details(self):
        self.detailed = not self.detailed
        for p in self.panels.values():
            p.set_detailed(self.detailed)
        self._more_text()
        self._fit()

    def add(self, key: str, job: Job):
        if key in self.panels:
            return
        if self.panels:
            line = QFrame()
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            line.setObjectName(f"line-{key}")
            self.panels_box.addWidget(line)
        p = JobPanel(job, self)
        p.set_detailed(self.detailed)
        self.panels[key] = p
        self.panels_box.addWidget(p)
        self._layout_mode()

    def remove(self, key: str):
        p = self.panels.pop(key, None)
        if p is None:
            return
        line = self.body.findChild(QFrame, f"line-{key}")
        if line is not None:
            line.deleteLater()
        p.hide()
        p.deleteLater()
        if not self.panels:
            self.hide()
            return
        self._layout_mode()

    def _layout_mode(self):
        single = len(self.panels) == 1
        for p in self.panels.values():
            p.stop.setVisible(not single)
        self.cancel_btn.setVisible(single)
        self.refresh()
        self._fit()

    def _fit(self):
        # fixed size, so the window has no maximize button, as in Windows
        QTimer.singleShot(0, lambda: self.setFixedSize(460, self.sizeHint().height()))

    def refresh(self):
        for p in self.panels.values():
            p.refresh()
        if len(self.panels) == 1:
            job = next(iter(self.panels.values())).job
            pct = job.percent()
            self.setWindowTitle(f"{pct}% complete" if pct is not None else job.headline())
            self.cancel_btn.setEnabled(job.can_cancel)
        elif self.panels:
            self.setWindowTitle(f"{len(self.panels)} Operations Running")

    def cancel_all(self):
        for p in list(self.panels.values()):
            if p.job.can_cancel:
                p.cancel()
        self.cancel_btn.setEnabled(False)

    def closeEvent(self, e):
        # closing the window cancels, as in Windows; what can't be cancelled just goes on unseen
        if any(p.job.can_cancel for p in self.panels.values()):
            self.cancel_all()
            e.ignore()
        else:
            e.accept()


class Launcher(dbus.service.Object):
    """Progress on taskbar buttons (Unity launcher API, which Plasma's task manager reads)."""

    def __init__(self, bus):
        super().__init__(bus, "/com/canonical/unity/launcherentry/classic7")

    @dbus.service.signal("com.canonical.Unity.LauncherEntry", signature="sa{sv}")
    def Update(self, app_uri, properties):  # noqa: N802 - D-Bus name
        pass

    def progress(self, desktop_id: str, value: float | None):
        props = {"progress-visible": dbus.Boolean(value is not None)}
        if value is not None:
            props["progress"] = dbus.Double(max(0.0, min(1.0, value)))
        self.Update(f"application://{desktop_id}.desktop", dbus.Dictionary(props, signature="sv"))


class JobsUI:
    def __init__(self, bus):
        self.window: JobsWindow | None = None
        self.jobs: dict[str, Job] = {}
        self.launcher = Launcher(bus)
        self.lit: set[str] = set()
        self.timer = QTimer()
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)

    def add(self, key: str, job: Job):
        self.jobs[key] = job
        self.timer.start()
        immediate = bool(job.state.get("immediate"))
        QTimer.singleShot(150 if immediate else int(SHOW_AFTER * 1000), lambda: self._show(key))

    def _show(self, key: str):
        job = self.jobs.get(key)
        if job is None:
            return
        if self.window is None:
            self.window = JobsWindow(self)
        self.window.add(key, job)
        if not self.window.isVisible():
            self.window.show()

    def changed(self, key: str):
        pass          # the timer redraws twice a second; KIO sends updates far more often

    def finish(self, key: str):
        self.jobs.pop(key, None)
        if self.window is not None:
            self.window.remove(key)
        if not self.jobs:
            self.timer.stop()
            self._taskbar()

    def tick(self):
        if self.window is not None and self.window.panels:
            self.window.refresh()
        self._taskbar()

    def _taskbar(self):
        shown = [j for k, j in self.jobs.items() if self.window is not None and k in self.window.panels]
        want: dict[str, list[float]] = {}
        for j in shown:
            pct = j.percent()
            if pct is None:
                continue
            want.setdefault(PROGRESS_APP, []).append(pct / 100)
            if j.desktop_entry and j.desktop_entry not in ("org.kde.plasmashell", PROGRESS_APP):
                want.setdefault(j.desktop_entry, []).append(pct / 100)
        for app, values in want.items():
            self.launcher.progress(app, sum(values) / len(values))
        for app in self.lit - set(want):
            self.launcher.progress(app, None)
        self.lit = set(want)


# ---- D-Bus: the job view server KIO talks to -------------------------------------------------
def plain(v):
    """dbus-python values as plain Python ones."""
    if isinstance(v, dbus.Boolean):
        return bool(v)
    if isinstance(v, (dbus.Int16, dbus.Int32, dbus.Int64, dbus.UInt16, dbus.UInt32, dbus.UInt64, dbus.Byte)):
        return int(v)
    if isinstance(v, dbus.Double):
        return float(v)
    if isinstance(v, (dbus.String, dbus.ObjectPath)):
        return str(v)
    if isinstance(v, dbus.Dictionary):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, dbus.Array):
        return [plain(x) for x in v]
    return v


class JobView(dbus.service.Object):
    def __init__(self, server: "JobViewServer", path: str, desktop_entry: str, capabilities: int, hints: dict):
        super().__init__(server.connection, path)
        self.server = server
        self.path = path
        self.job = Job(self, desktop_entry, capabilities, hints)
        self.done = False
        server.ui.add(path, self.job)
        if hints.get("terminated"):
            QTimer.singleShot(0, lambda: self._end())

    @dbus.service.method("org.kde.JobViewV3", in_signature="usa{sv}", out_signature="")
    def terminate(self, error_code, error_message, hints):
        self.job.update({"errorCode": int(error_code), "errorMessage": str(error_message)})
        self._end()

    @dbus.service.method("org.kde.JobViewV3", in_signature="a{sv}", out_signature="")
    def update(self, properties):
        d = plain(properties)
        self.job.update(d)
        if "destUrl" in d:
            self.server.urls_changed()
        if d.get("terminated"):
            self._end()
        else:
            self.server.ui.changed(self.path)

    @dbus.service.signal("org.kde.JobViewV3", signature="")
    def suspendRequested(self):  # noqa: N802
        pass

    @dbus.service.signal("org.kde.JobViewV3", signature="")
    def resumeRequested(self):  # noqa: N802
        pass

    @dbus.service.signal("org.kde.JobViewV3", signature="")
    def cancelRequested(self):  # noqa: N802
        pass

    def _end(self):
        if self.done:
            return
        self.done = True
        self.server.ui.finish(self.path)
        self.server.views.pop(self.path, None)
        self.server.urls_changed()
        # keep the object a moment: KIO may still send its last update
        QTimer.singleShot(5000, self._unexport)

    def _unexport(self):
        try:
            self.remove_from_connection()
        except (LookupError, KeyError):
            pass


class JobViewServer(dbus.service.Object):
    def __init__(self, bus, ui: JobsUI):
        super().__init__(bus, SERVER_PATH)
        self.ui = ui
        self.views: dict[str, JobView] = {}
        self.count = 0
        self._last_urls: list[str] = []

    # org.kde.JobViewServerV2 (KDE Frameworks 6)
    @dbus.service.method("org.kde.JobViewServerV2", in_signature="sia{sv}", out_signature="o")
    def requestView(self, desktop_entry, capabilities, hints):  # noqa: N802
        self.count += 1
        path = f"/org/classic7/jobs/JobView_{self.count}"
        self.views[path] = JobView(self, path, str(desktop_entry), int(capabilities), plain(hints))
        return dbus.ObjectPath(path)

    # org.kde.kuiserver
    @dbus.service.method("org.kde.kuiserver", in_signature="", out_signature="b")
    def requiresJobTracker(self):  # noqa: N802
        return False

    @dbus.service.method("org.kde.kuiserver", in_signature="ss", out_signature="")
    def registerService(self, service, object_path):  # noqa: N802
        pass

    @dbus.service.method("org.kde.kuiserver", in_signature="", out_signature="")
    def emitJobUrlsChanged(self):  # noqa: N802
        self.jobUrlsChanged(dbus.Array(self._urls(), signature="s"))

    @dbus.service.signal("org.kde.kuiserver", signature="as")
    def jobUrlsChanged(self, urls):  # noqa: N802
        pass

    @dbus.service.signal("org.kde.kuiserver", signature="b")
    def requiresJobTrackerChanged(self, value):  # noqa: N802
        pass

    def _urls(self) -> list[str]:
        return sorted({str(v.job.state.get("destUrl")) for v in self.views.values() if v.job.state.get("destUrl")})

    def urls_changed(self):
        urls = self._urls()
        if urls != self._last_urls:
            self._last_urls = urls
            self.jobUrlsChanged(dbus.Array(urls, signature="s"))


# ---- the Recycle Bin icon -------------------------------------------------------------------
class TrashWatcher:
    """Watches the Recycle Bin folders and brings the desktop icon (and KDE's own trash state) up
    to date after any change, also those made by programs that don't go through KDE."""

    def __init__(self):
        import recyclebin_app as rb
        self.rb = rb
        self.watcher = QFileSystemWatcher()
        self.watcher.directoryChanged.connect(lambda _p: self.debounce.start())
        self.debounce = QTimer()
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(600)
        self.debounce.timeout.connect(self.sync)
        self.rescan = QTimer()
        self.rescan.setInterval(30000)
        self.rescan.timeout.connect(self.watch)
        self.rescan.start()
        home_info = rb.home_trash() / "info"
        try:
            home_info.mkdir(parents=True, exist_ok=True, mode=0o700)
            (rb.home_trash() / "files").mkdir(parents=True, exist_ok=True, mode=0o700)
        except OSError:
            pass
        self.empty: bool | None = None
        self.watch()
        self.sync()

    def watch(self):
        want = {str(t / "info") for t, _top in self.rb.trash_dirs() if (t / "info").is_dir()}
        have = set(self.watcher.directories())
        for d in have - want:
            self.watcher.removePath(d)
        for d in want - have:
            self.watcher.addPath(d)
        if want != have:
            self.debounce.start()

    def sync(self):
        empty = self.rb.trash_is_empty()
        self.rb.sync_state(notify=empty != self.empty)
        self.empty = empty


def main(bus, have_jobs: bool) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-sessiond")
    app.setDesktopFileName(PROGRESS_APP)
    app.setQuitOnLastWindowClosed(False)
    ui = JobsUI(bus)
    server = JobViewServer(bus, ui) if have_jobs else None
    try:
        trash = TrashWatcher()
    except Exception as e:  # noqa: BLE001 - the progress windows matter more than the icon
        print(f"classic7-sessiond: Recycle Bin watcher off: {e}", file=sys.stderr)
        trash = None
    _keep.extend([ui, server, trash])
    return app.exec()


_keep: list = []
