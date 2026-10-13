"""Date and Time, as in Windows 7 (timedate.cpl).

    classic7-timedate            the window
    classic7-timedate --zone     straight to "Change time zone"

Date and Time: the clock face, the date and time, the time zone and the next daylight-saving
change, with Change date and time... and Change time zone.... Internet Time: whether the clock
keeps itself right from the Internet, and the time servers. The changes go through timedatectl
(systemd's timedated), which asks for an administrator's password when needed."""
from __future__ import annotations

import datetime as dt
import math
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, available_timezones

from PySide6.QtCore import QDate, QDateTime, QLocale, QPointF, Qt, QTime, QTimer
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import (QApplication, QCalendarWidget, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTabWidget,
                               QTimeEdit, QVBoxLayout, QWidget)

APP = "Date and Time"


# ---- system state ---------------------------------------------------------------------------
def timedatectl_show() -> dict[str, str]:
    try:
        out = subprocess.run(["timedatectl", "show"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def local_zone() -> str:
    z = timedatectl_show().get("Timezone", "")
    if z:
        return z
    try:
        return str(Path("/etc/localtime").resolve()).split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return "UTC"


def time_servers() -> list[str]:
    servers = []
    for conf in (Path("/etc/chrony.conf"), Path("/etc/systemd/timesyncd.conf")):
        try:
            for line in conf.read_text().splitlines():
                f = line.split()
                if len(f) >= 2 and f[0] in ("server", "pool"):
                    servers.append(f[1])
                elif line.startswith("NTP=") and line[4:].strip():
                    servers += line[4:].split()
        except OSError:
            continue
    return servers


def utc_label(offset: dt.timedelta | None) -> str:
    mins = int((offset or dt.timedelta()).total_seconds() // 60)
    sign = "+" if mins >= 0 else "-"
    mins = abs(mins)
    return f"(UTC{sign}{mins // 60:02d}:{mins % 60:02d})"


def zone_label(name: str) -> str:
    try:
        off = dt.datetime.now(ZoneInfo(name)).utcoffset()
    except Exception:  # noqa: BLE001 - unknown zone name
        off = None
    place = name.split("/")[-1].replace("_", " ")
    region = name.split("/")[0] if "/" in name else ""
    return f"{utc_label(off)} {place}" + (f" ({region})" if region and region not in ("Etc",) else "")


def next_change(zone: str) -> tuple[dt.datetime, dt.timedelta, dt.timedelta] | None:
    """The next daylight-saving change within a year: (local time before it, old offset, new offset)."""
    try:
        tz = ZoneInfo(zone)
    except Exception:  # noqa: BLE001
        return None
    now = dt.datetime.now(dt.timezone.utc)
    step = dt.timedelta(days=1)
    t, off = now, now.astimezone(tz).utcoffset()
    for _ in range(370):
        nt = t + step
        noff = nt.astimezone(tz).utcoffset()
        if noff != off:
            lo, hi = t, nt
            while hi - lo > dt.timedelta(minutes=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == off:
                    lo = mid
                else:
                    hi = mid
            when = hi.replace(second=0, microsecond=0)
            return (when.astimezone(dt.timezone(off)).replace(tzinfo=None), off, noff)
        t = nt
    return None


def run_admin(args: list[str]) -> str | None:
    """timedatectl with interactive authorization (the desktop asks for the password)."""
    try:
        r = subprocess.run(["timedatectl", *args], capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)
    return None if r.returncode == 0 else (r.stderr.strip() or "The change was not allowed.")


# ---- the clock face -------------------------------------------------------------------------
class ClockFace(QWidget):
    def __init__(self, size: int = 150):
        super().__init__()
        self.setFixedSize(size, size)
        self.time = QTime.currentTime()

    def set_time(self, t: QTime):
        self.time = t
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = min(self.width(), self.height()) / 2 - 2
        p.translate(self.width() / 2, self.height() / 2)
        g = QLinearGradient(0, -r, 0, r)
        g.setColorAt(0, QColor("#9fb3c8"))
        g.setColorAt(1, QColor("#4a6178"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), r, r)
        rg = QRadialGradient(QPointF(-r * 0.3, -r * 0.4), r * 1.1)
        rg.setColorAt(0, QColor("#ffffff"))
        rg.setColorAt(1, QColor("#dfe7ef"))
        p.setBrush(rg)
        p.drawEllipse(QPointF(0, 0), r * 0.9, r * 0.9)
        for i in range(60):
            a = i * math.pi / 30
            big = i % 5 == 0
            p.setPen(QPen(QColor("#2b3a4a" if big else "#8696a6"), max(2.0, r * 0.04) if big else 1.0))
            r1 = r * (0.70 if big else 0.78)
            p.drawLine(QPointF(math.sin(a) * r1, -math.cos(a) * r1), QPointF(math.sin(a) * r * 0.84, -math.cos(a) * r * 0.84))
        t = self.time
        s = t.second()
        m = t.minute() + s / 60
        h = (t.hour() % 12) + m / 60

        def hand(angle, length, width, color):
            pen = QPen(QColor(color), width)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(-math.sin(angle) * length * 0.15, math.cos(angle) * length * 0.15),
                       QPointF(math.sin(angle) * length, -math.cos(angle) * length))
        hand(h * math.pi / 6, r * 0.48, max(3.0, r * 0.07), "#1d2833")
        hand(m * math.pi / 30, r * 0.70, max(2.0, r * 0.05), "#1d2833")
        hand(s * math.pi / 30, r * 0.76, 1.0, "#c42b1c")
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1d2833"))
        p.drawEllipse(QPointF(0, 0), max(2.0, r * 0.05), max(2.0, r * 0.05))


# ---- dialogs ----------------------------------------------------------------------------------
class SetTimeDialog(QDialog):
    """Date and Time Settings: a calendar and a clock with the time to set."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Date and Time Settings")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Set the date and time:"))
        row = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Date:"))
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(False)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        left.addWidget(self.cal)
        row.addLayout(left)
        right = QVBoxLayout()
        right.addWidget(QLabel("Time:"))
        self.face = ClockFace(140)
        right.addWidget(self.face, 0, Qt.AlignHCenter)
        self.edit = QTimeEdit(QTime.currentTime())
        self.edit.setDisplayFormat(QLocale().timeFormat(QLocale.LongFormat).replace(" t", "").replace("t", "").strip())
        self.edit.timeChanged.connect(self.face.set_time)
        right.addWidget(self.edit)
        right.addStretch(1)
        row.addLayout(right)
        v.addLayout(row)
        self.face.set_time(self.edit.time())
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        # the time keeps running until the user touches it, as in Windows
        self.touched = False
        self.edit.editingFinished.connect(lambda: setattr(self, "touched", True))
        self.edit.timeChanged.connect(lambda _t: setattr(self, "touched", self.touched or self.edit.hasFocus()))
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)
        self.tick.start(1000)

    def _tick(self):
        if not self.touched:
            self.edit.blockSignals(True)
            self.edit.setTime(QTime.currentTime())
            self.edit.blockSignals(False)
            self.face.set_time(self.edit.time())

    def value(self) -> str:
        d, t = self.cal.selectedDate(), self.edit.time()
        return f"{d.toString('yyyy-MM-dd')} {t.toString('HH:mm:ss')}"


class ZoneDialog(QDialog):
    def __init__(self, parent, current: str):
        super().__init__(parent)
        self.setWindowTitle("Time Zone Settings")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Set the time zone:"))
        v.addWidget(QLabel("Time zone:"))
        self.combo = QComboBox()
        zones = sorted(z for z in available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/", "posix/",
                                                                                            "right/")))
        now = dt.datetime.now(dt.timezone.utc)

        def offset(z):
            try:
                return now.astimezone(ZoneInfo(z)).utcoffset() or dt.timedelta()
            except Exception:  # noqa: BLE001
                return dt.timedelta()
        for z in sorted(zones, key=lambda z: (offset(z), z)):
            self.combo.addItem(zone_label(z), z)
        if "UTC" not in zones:
            self.combo.insertItem(0, "(UTC) Coordinated Universal Time", "UTC")
        i = self.combo.findData(current)
        if i >= 0:
            self.combo.setCurrentIndex(i)
        self.combo.setMaxVisibleItems(20)
        v.addWidget(self.combo)
        dst = QCheckBox("Automatically adjust clock for Daylight Saving Time")
        dst.setChecked(True)
        dst.setEnabled(False)
        v.addWidget(dst)
        self.info = QLabel()
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.combo.currentIndexChanged.connect(self._info)
        self._info()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(460, 200)

    def _info(self):
        z = self.combo.currentData()
        try:
            t = dt.datetime.now(ZoneInfo(z))
            self.info.setText(f"Current date and time: {QLocale().toString(QDateTime(QDate(t.year, t.month, t.day), QTime(t.hour, t.minute, t.second)), QLocale.LongFormat)}")
        except Exception:  # noqa: BLE001
            self.info.setText("")

    def zone(self) -> str:
        return self.combo.currentData()


class InternetDialog(QDialog):
    def __init__(self, parent, ntp: bool, servers: list[str]):
        super().__init__(parent)
        self.setWindowTitle("Internet Time Settings")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Configure Internet time settings:"))
        self.sync = QCheckBox("Synchronize with an Internet time server")
        self.sync.setChecked(ntp)
        v.addWidget(self.sync)
        row = QHBoxLayout()
        row.addWidget(QLabel("Server:"))
        server = QComboBox()
        server.addItems(servers or ["(the time servers of your network)"])
        server.setEnabled(False)
        row.addWidget(server, 1)
        v.addLayout(row)
        note = QLabel("The servers are set in /etc/chrony.conf.")
        note.setStyleSheet("color: #555;")
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


# ---- the window -------------------------------------------------------------------------------
def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


class DateTimePage(QWidget):
    def __init__(self, win: "DateTime"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        row = QHBoxLayout()
        self.face = ClockFace(120)
        row.addWidget(self.face, 0, Qt.AlignTop)
        col = QVBoxLayout()
        self.date = QLabel()
        self.time = QLabel()
        col.addWidget(self.date)
        col.addWidget(self.time)
        col.addStretch(1)
        b = QPushButton("Change date and time...")
        b.setIcon(QIcon.fromTheme("security-medium"))
        b.clicked.connect(self.change_time)
        col.addWidget(b, 0, Qt.AlignLeft)
        row.addSpacing(10)
        row.addLayout(col, 1)
        v.addLayout(row)
        v.addWidget(hline())
        g = QGroupBox("Time zone")
        gl = QVBoxLayout(g)
        self.zone = QLabel()
        gl.addWidget(self.zone)
        zb = QPushButton("Change time zone...")
        zb.clicked.connect(self.change_zone)
        gl.addWidget(zb, 0, Qt.AlignRight)
        v.addWidget(g)
        self.dst = QLabel()
        self.dst.setWordWrap(True)
        v.addWidget(self.dst)
        v.addStretch(1)
        self.load()
        self.tick()

    def load(self):
        z = local_zone()
        self.zone.setText(zone_label(z))
        ch = next_change(z)
        if ch:
            when, old, new = ch
            delta = int((new - old).total_seconds() // 60)
            loc = QLocale()
            d = loc.toString(QDate(when.year, when.month, when.day), QLocale.LongFormat)
            t = loc.toString(QTime(when.hour, when.minute), QLocale.ShortFormat)
            way = "forward" if delta > 0 else "back"
            amount = f"{abs(delta) // 60} hour" + ("s" if abs(delta) // 60 != 1 else "") if abs(delta) % 60 == 0 \
                else f"{abs(delta)} minutes"
            begins = "begins" if delta > 0 else "ends"
            self.dst.setText(f"Daylight Saving Time {begins} on {d} at {t}. The clock is set to go {way} {amount} at "
                             "that time.")
        else:
            self.dst.setText("This time zone doesn't change for Daylight Saving Time.")

    def tick(self):
        now = QDateTime.currentDateTime()
        loc = QLocale()
        self.face.set_time(now.time())
        self.date.setText(f"Date:\n{loc.toString(now.date(), QLocale.LongFormat)}")
        tf = loc.timeFormat(QLocale.LongFormat).replace(" t", "").replace("t", "").strip()
        self.time.setText(f"Time:\n{loc.toString(now.time(), tf)}")

    def change_time(self):
        dlg = SetTimeDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        if timedatectl_show().get("NTP") == "yes":
            if QMessageBox.question(self, APP, "The clock is set to keep itself right from the Internet. To set the time "
                                    "yourself, Internet time synchronization is turned off.\n\nContinue?") \
                    != QMessageBox.Yes:
                return
            err = run_admin(["set-ntp", "false"])
            if err:
                QMessageBox.warning(self, APP, err)
                return
        err = run_admin(["set-time", dlg.value()])
        if err:
            QMessageBox.warning(self, APP, f"The date and time could not be changed.\n\n{err}")
        self.win.refresh()

    def change_zone(self):
        dlg = ZoneDialog(self, local_zone())
        if dlg.exec() == QDialog.Accepted and dlg.zone() != local_zone():
            err = run_admin(["set-timezone", dlg.zone()])
            if err:
                QMessageBox.warning(self, APP, f"The time zone could not be changed.\n\n{err}")
        self.win.refresh()


class InternetPage(QWidget):
    def __init__(self, win: "DateTime"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 14)
        self.text = QLabel()
        self.text.setWordWrap(True)
        v.addWidget(self.text)
        b = QPushButton("Change settings...")
        b.setIcon(QIcon.fromTheme("security-medium"))
        b.clicked.connect(self.change)
        v.addWidget(b, 0, Qt.AlignRight)
        v.addStretch(1)
        self.load()

    def load(self):
        info = timedatectl_show()
        servers = time_servers()
        server = servers[0] if servers else "your network's time server"
        if info.get("NTP") == "yes":
            synced = info.get("NTPSynchronized") == "yes"
            self.text.setText(f"This computer is set to automatically synchronize with '{server}'.\n\n"
                              + ("The clock was synchronized successfully." if synced else
                                 "The clock has not been synchronized yet."))
        else:
            self.text.setText("This computer is not set to automatically synchronize.")

    def change(self):
        info = timedatectl_show()
        dlg = InternetDialog(self, info.get("NTP") == "yes", time_servers())
        if dlg.exec() == QDialog.Accepted and dlg.sync.isChecked() != (info.get("NTP") == "yes"):
            err = run_admin(["set-ntp", "true" if dlg.sync.isChecked() else "false"])
            if err:
                QMessageBox.warning(self, APP, err)
        self.win.refresh()


class DateTime(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon.fromTheme("preferences-system-time"))
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.page = DateTimePage(self)
        self.net = InternetPage(self)
        self.tabs.addTab(self.page, "Date and Time")
        self.tabs.addTab(self.net, "Internet Time")
        v.addWidget(self.tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.page.tick)
        self.timer.start(1000)
        self.setFixedSize(430, 440)

    def refresh(self):
        self.page.load()
        self.page.tick()
        self.net.load()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1].strip())
        return 0
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-timedate")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-timedate")
    w = DateTime()
    w.show()
    if "--zone" in argv:
        QTimer.singleShot(200, w.page.change_zone)
    w.finished.connect(app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
