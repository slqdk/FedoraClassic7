"""Classic 7 Update window, laid out like Windows 7's Windows Update page."""
from __future__ import annotations

import subprocess
import sys
import time

from PySide6.QtCore import QObject, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QTextBrowser, QToolButton, QVBoxLayout, QWidget)

import update_core as core

APP = "Classic 7 Update"

STATES = {
    # key: (strip colour, shield colour, heading)
    "checking": ("#3C78B4", "#3C78B4", "Checking for updates…"),
    "uptodate": ("#3C9A3C", "#2E8B2E", "Classic 7 is up to date"),
    "available": ("#E8B800", "#E8B800", "Updates are available for your computer"),
    "installing": ("#3C78B4", "#3C78B4", "Installing updates…"),
    "restart": ("#E8B800", "#E8B800", "Restart your computer to finish installing updates"),
    "error": ("#C03030", "#C03030", "Classic 7 could not finish"),
}


def shield(color: str, size: int = 48) -> QPixmap:
    """The Windows Update shield, drawn: a coloured shield with a white mark."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 48
    pts = [QPointF(24 * s, 3 * s), QPointF(42 * s, 9 * s), QPointF(40 * s, 28 * s),
           QPointF(24 * s, 45 * s), QPointF(8 * s, 28 * s), QPointF(6 * s, 9 * s)]
    p.setPen(QColor("#404040"))
    p.setBrush(QColor(color))
    p.drawPolygon(QPolygonF(pts))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawPolygon(QPolygonF([pts[0], pts[1], QPointF(41 * s, 18 * s), QPointF(24 * s, 18 * s)]))
    p.setBrush(QColor("#FFFFFF"))
    f = QFont("DejaVu Sans")
    f.setBold(True)
    f.setPixelSize(int(22 * s))
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    mark = "✓" if color in ("#2E8B2E",) else "!" if color in ("#E8B800", "#C03030") else "↻"
    p.drawText(pm.rect().adjusted(0, int(-2 * s), 0, 0), Qt.AlignCenter, mark)
    p.end()
    return pm


class Worker(QThread):
    line = Signal(str)
    status = Signal(str)
    done = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            res = self.fn(self.line.emit)
        except Exception as e:  # noqa: BLE001 - shown in the window
            self.line.emit(f"Error: {e}")
            res = e
        self.done.emit(res)


class LinkButton(QToolButton):
    def __init__(self, text, slot):
        super().__init__()
        self.setText(text)
        self.setAutoRaise(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("QToolButton { color: #0000CC; border: none; text-align: left; padding: 2px; }"
                           "QToolButton:hover { text-decoration: underline; color: #3333FF; }")
        self.clicked.connect(slot)


class UpdateWindow(QMainWindow):
    def __init__(self, auto_check=True, auto_install=False):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon.fromTheme("system-software-update", QIcon(shield("#3C78B4", 32))))
        self.state = core.UpdateState.load()
        self.worker: Worker | None = None
        self.pending: dict = {}          # what the last check found

        root = QWidget()
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # left task pane
        side = QFrame()
        side.setObjectName("side")
        side.setFixedWidth(225)
        side.setStyleSheet("#side { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #FFFFFF, stop:1 #DCE6F4);"
                           " border-right: 1px solid #A0A0A0; }")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 14, 6, 10)
        sv.setSpacing(4)
        t = QLabel("Control Panel Home")
        t.setStyleSheet("color: #1E395B;")
        sv.addWidget(t)
        sv.addSpacing(8)
        self.link_check = LinkButton("Check for updates", self.check)
        sv.addWidget(self.link_check)
        sv.addWidget(LinkButton("View update history", self.history))
        sv.addWidget(LinkButton("Restore Classic 7 settings", self.settings_only))
        sv.addWidget(LinkButton("Go back to previous version", self.rollback))
        sv.addStretch(1)
        see = QLabel("See also")
        see.setStyleSheet("color: #1E395B;")
        sv.addWidget(see)
        sv.addWidget(LinkButton("Appearance", lambda: subprocess.Popen(["classic7-appearance"])))
        sv.addWidget(LinkButton("Software (Bazaar)", self.open_store))
        h.addWidget(side)

        # main area
        main = QWidget()
        mv = QVBoxLayout(main)
        mv.setContentsMargins(22, 16, 22, 14)
        mv.setSpacing(10)
        title = QLabel("Classic 7 Update")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        title.setFont(f)
        title.setStyleSheet("color: #1E395B;")
        mv.addWidget(title)

        # status box: coloured strip at the left, shield, heading, text, button
        self.box = QFrame()
        self.box.setObjectName("box")
        bh = QHBoxLayout(self.box)
        bh.setContentsMargins(0, 0, 10, 0)
        self.strip = QFrame()
        self.strip.setFixedWidth(8)
        bh.addWidget(self.strip)
        self.shield = QLabel()
        self.shield.setFixedSize(56, 56)
        self.shield.setAlignment(Qt.AlignCenter)
        bh.addWidget(self.shield, 0, Qt.AlignTop)
        tv = QVBoxLayout()
        tv.setContentsMargins(4, 10, 4, 10)
        self.heading = QLabel()
        hf = self.heading.font()
        hf.setPointSizeF(hf.pointSizeF() * 1.25)
        self.heading.setFont(hf)
        self.heading.setWordWrap(True)
        tv.addWidget(self.heading)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        tv.addWidget(self.text)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(16)
        tv.addWidget(self.progress)
        brow = QHBoxLayout()
        brow.addStretch(1)
        self.button = QPushButton()
        self.button.setMinimumWidth(130)
        self.button.clicked.connect(self._button)
        brow.addWidget(self.button)
        tv.addLayout(brow)
        bh.addLayout(tv, 1)
        mv.addWidget(self.box)

        # facts
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        self.facts = {}
        for i, key in enumerate(("Most recent check for updates:", "Updates were installed:",
                                 "Classic 7 version:", "You receive updates:")):
            k = QLabel(key)
            v = QLabel()
            v.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(k, i, 0)
            grid.addWidget(v, i, 1)
            self.facts[key] = v
        grid.setColumnStretch(1, 1)
        mv.addLayout(grid)

        # details
        drow = QHBoxLayout()
        self.details_btn = LinkButton("Show details", self.toggle_details)
        drow.addWidget(self.details_btn)
        drow.addStretch(1)
        mv.addLayout(drow)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        mono = QFont("DejaVu Sans Mono")
        mono.setPointSizeF(max(7.5, self.font().pointSizeF() - 1))
        self.log.setFont(mono)
        self.log.setVisible(False)
        mv.addWidget(self.log, 1)
        self.spacer = QWidget()
        self.spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        mv.addWidget(self.spacer, 1)
        h.addWidget(main, 1)

        self.resize(760, 500)
        self._facts()
        self.mode = ""
        if auto_install:
            QTimer.singleShot(200, self.install)
        elif auto_check:
            QTimer.singleShot(200, self.check)
        else:
            self.set_state("uptodate", "Click Check for updates to look for a newer Classic 7.", "Check for updates")

    # ---- display ------------------------------------------------------------------------------
    def set_state(self, key: str, text: str, button: str | None, busy: bool = False):
        strip, color, heading = STATES[key]
        self.mode = key
        self.strip.setStyleSheet(f"background: {strip};")
        self.box.setStyleSheet("#box { border: 1px solid #A0A0A0; background: #FFFFFF; }")
        self.shield.setPixmap(shield(color))
        self.heading.setText(heading)
        self.text.setText(text)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        self.button.setVisible(button is not None)
        if button:
            self.button.setText(button)
        self.link_check.setEnabled(not busy)

    def _facts(self):
        def when(ts):
            if not ts:
                return "Never"
            return time.strftime("%d-%m-%Y at %H:%M", time.localtime(ts))
        st = core.UpdateState.load()
        self.facts["Most recent check for updates:"].setText(when(st.last_check))
        self.facts["Updates were installed:"].setText(when(st.last_install))
        info = core.build_info()
        base = info.get("base", "")
        self.facts["Classic 7 version:"].setText(core.pretty_build(core.current_build())
                                                 + (f"  (based on Bazzite {base})" if base else ""))
        self.facts["You receive updates:"].setText("Automatically in the background, or now with Install updates")

    def add_log(self, line: str):
        self.log.appendPlainText(line)

    def toggle_details(self):
        show = not self.log.isVisible()
        self.log.setVisible(show)
        self.spacer.setVisible(not show)
        self.details_btn.setText("Hide details" if show else "Show details")

    def busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _start(self, fn, done):
        self.worker = Worker(fn, self)
        self.worker.line.connect(self.add_log)
        self.worker.status.connect(self.text.setText)
        self.worker.done.connect(done)
        self.worker.start()

    def _button(self):
        {"available": self.install, "restart": self.restart, "error": self.check,
         "uptodate": self.check}.get(self.mode, lambda: None)()

    # ---- check ---------------------------------------------------------------------------------
    def check(self):
        if self.busy():
            return
        self.set_state("checking", "Looking for a newer Classic 7, app updates and new settings.", None, busy=True)
        self.add_log("== Checking for updates")

        def work(log):
            res = {"system": core.check(log)}
            res["apps"] = core.app_updates()
            log(f"App updates: {len(res['apps'])}")
            res["settings"] = core.needs_refresh()
            return res
        self._start(work, self._checked)

    def _checked(self, res):
        st = core.UpdateState.load()
        st.last_check = time.time()
        st.save()
        self._facts()
        if isinstance(res, Exception):
            self.set_state("error", f"The check failed: {res}", "Try again")
            return
        self.pending = res
        items = []
        if res["system"] == core.CHECK_AVAILABLE:
            items.append("a new version of Classic 7")
        if res["apps"]:
            items.append(f"{len(res['apps'])} app update{'s' if len(res['apps']) != 1 else ''}")
        if res["settings"]:
            items.append("new Classic 7 settings for your account")
        if res["system"] == core.CHECK_ERROR:
            self.set_state("error", "Classic 7 could not reach the update server. Check the network connection "
                           "and try again. <i>Show details</i> has the message.", "Try again")
        elif items:
            extra = (" A new Classic 7 is already downloaded and starts at the next restart."
                     if res["system"] == core.CHECK_STAGED else "")
            self.set_state("available", "<b>Ready to install:</b> " + ", ".join(items) + "." + extra,
                           "Install updates")
        elif res["system"] == core.CHECK_STAGED:
            self.set_state("restart", "A new version of Classic 7 is downloaded. It starts when you restart.",
                           "Restart now")
        else:
            self.set_state("uptodate", "No new updates are available. Apps and your settings are up to date too.",
                           None)

    # ---- install everything ------------------------------------------------------------------
    def install(self):
        if self.busy():
            return
        self.set_state("installing", "Step 1 of 3: downloading the newest Classic 7…", None, busy=True)
        self.add_log("== Installing updates")
        steps = {"system": None, "apps": None, "settings": None}

        def work(log):
            def step(n, text):
                self.worker.status.emit(f"Step {n} of 3: {text}")
            step(1, "downloading the newest Classic 7 (this can take a few minutes)…")
            log("-- System image")
            steps["system"] = core.upgrade_system(log)
            step(2, "updating apps…")
            log("-- Apps (Flatpak)")
            steps["apps"] = core.update_apps(log)
            step(3, "applying Classic 7 settings to your account…")
            log("-- Classic 7 settings for this account")
            steps["settings"] = not core.refresh_account(log)
            steps["restart"] = core.restart_needed()
            return steps
        self._start(work, self._installed)

    def _installed(self, res):
        st = core.UpdateState.load()
        st.last_install = time.time()
        failed = [] if isinstance(res, Exception) else [k for k in ("system", "apps", "settings") if res[k] is False]
        st.last_result = "failed: " + ", ".join(failed) if failed else "ok"
        st.save()
        self._facts()
        names = {"system": "the Classic 7 system update", "apps": "the app updates", "settings": "your settings"}
        if isinstance(res, Exception):
            self.set_state("error", f"Updating stopped: {res}", "Try again")
        elif res.get("restart"):
            extra = (" (" + ", ".join(names[k] for k in failed) + " did not finish: see details)") if failed else ""
            self.set_state("restart", "The new version of Classic 7 is ready. Restart to start using it; "
                           "your settings are brought up to date at the next login." + extra, "Restart now")
        elif failed:
            self.set_state("error", "Not everything could be installed: " + ", ".join(names[k] for k in failed)
                           + ". <i>Show details</i> has the messages.", "Try again")
            if not self.log.isVisible():
                self.toggle_details()
        else:
            self.set_state("uptodate", "All updates are installed. Classic 7, your apps and your settings are "
                           "up to date.", None)

    # ---- other actions ----------------------------------------------------------------------
    def settings_only(self):
        if self.busy():
            return
        self.set_state("installing", "Applying the Classic 7 settings to your account…", None, busy=True)
        self.add_log("== Restoring Classic 7 settings")
        self._start(lambda log: not core.refresh_account(log),
                    lambda ok: self.set_state("uptodate" if ok is True else "error",
                                              "Your Classic 7 settings are up to date." if ok is True else
                                              "Some settings could not be applied. See details.", None))

    def restart(self):
        if QMessageBox.question(self, APP, "Restart the computer now? Save your work first.",
                                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            subprocess.Popen(["systemctl", "reboot"])

    def rollback(self):
        if QMessageBox.question(
                self, APP, "Go back to the previous version of Classic 7?\n\nIt starts at the next restart. "
                "This asks for your password in a Command Prompt window.",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            subprocess.Popen(["classic7-prompt", "--hold", "-e", "classic7-update", "--rollback"])

    def open_store(self):
        for cmd in (["bazaar"], ["flatpak", "run", "io.github.kolunmi.Bazaar"], ["plasma-discover"]):
            if core.shutil.which(cmd[0]):
                try:
                    subprocess.Popen(cmd)
                    return
                except OSError:
                    continue

    def history(self):
        HistoryDialog(self).exec()

    def closeEvent(self, ev):
        if self.busy():
            if QMessageBox.question(self, APP, "Updates are being installed. Stop and close anyway?",
                                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                ev.ignore()
                return
            self.worker.terminate()
        ev.accept()


class HistoryDialog(QDialog):
    def __init__(self, parent=None, since: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Update history" if since is None else "What's new in Classic 7")
        v = QVBoxLayout(self)
        intro = QLabel("Changes in Classic 7, newest first." if since is None else
                       "Classic 7 was updated. New since your last version:")
        v.addWidget(intro)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        entries = core.changes() if since is None else core.changes_since(since)
        html = []
        for c in entries:
            d = "-".join(reversed(c.date.split("-")))
            html.append(f"<p><b>{d} &nbsp; {c.title}</b></p><ul>"
                        + "".join(f"<li>{_esc(i)}</li>" for i in c.items) + "</ul>")
        view.setHtml("".join(html) or "<p>No history available.</p>")
        v.addWidget(view, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)
        self.resize(620, 460)


def _esc(s: str) -> str:
    import html
    import re
    out = html.escape(s)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out))


def main(auto_check=True, auto_install=False, history_since: str | None = None, history=False) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-update")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-update")
    if history or history_since is not None:
        HistoryDialog(None, history_since).exec()
        return 0
    w = UpdateWindow(auto_check, auto_install)
    w.show()
    return app.exec()
