"""Performance Information and Tools, as in Windows 7: the Classic 7 Experience Index (rate this
computer), Advanced tools (the performance issues Classic 7 can see and the tools to look further),
and the system health report to save and send to whoever helps with a problem.

    classic7-perfinfo               the window
    classic7-perfinfo --advanced    Advanced tools
    classic7-perfinfo --report      the system health report
    classic7-perfinfo --rate        the window, and rate the computer at once
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, QRectF, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

import control_items as ci
import perfinfo_core as pc
from control_panel import BLUE, Link
from cpl_page import PageWindow

APP = "Performance Information and Tools"
LIB = Path(__file__).resolve().parent
ICONS = {"cpu": ("cpu", "computer"), "memory": ("media-memory", "memory", "computer"),
         "graphics": ("video-display", "preferences-desktop-display"),
         "gaming": ("applications-games", "input-gaming"), "disk": ("drive-harddisk",)}


def icon(*names: str) -> QIcon:
    for n in names:
        if QIcon.hasThemeIcon(n):
            return QIcon.fromTheme(n)
    return QIcon.fromTheme(names[-1])


def fmt_score(s) -> str:
    return f"{s:.1f}" if isinstance(s, (int, float)) else "-"


# ---- the base score badge ----------------------------------------------------------------------
class ScoreBadge(QWidget):
    """Windows 7's base score: the number in a glossy blue square."""

    def __init__(self, score: float | None, size: int = 74):
        super().__init__()
        self.score = score
        self.side = size
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.side - 2, self.side - 2)
        path = QPainterPath()
        path.addRoundedRect(r, self.side * 0.12, self.side * 0.12)
        g = QLinearGradient(0, 0, 0, self.side)
        if self.score is None:
            g.setColorAt(0, QColor("#c8ced6"))
            g.setColorAt(1, QColor("#8a949f"))
        else:
            g.setColorAt(0, QColor("#6f9fe0"))
            g.setColorAt(0.5, QColor("#2f68c2"))
            g.setColorAt(1, QColor("#1b4a9a"))
        p.fillPath(path, g)
        shine = QPainterPath()
        shine.addRoundedRect(QRectF(3, 3, self.side - 6, self.side * 0.45), self.side * 0.1, self.side * 0.1)
        sg = QLinearGradient(0, 0, 0, self.side * 0.5)
        sg.setColorAt(0, QColor(255, 255, 255, 120))
        sg.setColorAt(1, QColor(255, 255, 255, 25))
        p.fillPath(shine, sg)
        p.setPen(QPen(QColor("#163d80"), 1))
        p.drawPath(path)
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(int(self.side * 0.42))
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignCenter, fmt_score(self.score) if self.score is not None else "?")


# ---- work done away from the window ---------------------------------------------------------------
class FactsLoader(QThread):
    """Collects the facts, the performance issues and the report (a few seconds)."""
    step = Signal(str)
    done = Signal(object)

    def run(self):
        try:
            facts = pc.collect(lambda text: self.step.emit(text))
            scores = pc.load_scores()
            found = pc.issues(facts, scores)
            self.step.emit("Error messages")
            text = pc.report(facts, found, scores)
            self.done.emit({"facts": facts, "issues": found, "report": text, "error": ""})
        except Exception as e:  # noqa: BLE001 - shown in the window rather than lost
            self.done.emit({"facts": None, "issues": [], "report": "", "error": f"{type(e).__name__}: {e}"})


class AssessDialog(QDialog):
    """Runs the assessment (perfinfo_assess.py, in its own process) and shows how far it is."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Classic 7 Experience Index")
        self.setWindowIcon(icon("utilities-system-monitor"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        title = QLabel("Rating your computer...")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.3)
        title.setFont(f)
        title.setStyleSheet("color: #1e3987;")
        v.addWidget(title)
        note = QLabel("This takes about half a minute. Two windows open for a few seconds each while the "
                      "graphics are assessed: please don't use the computer until it has finished.")
        note.setWordWrap(True)
        v.addWidget(note)
        self.step = QLabel("Starting...")
        v.addWidget(self.step)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        v.addWidget(self.bar)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.buttons.rejected.connect(self.reject)
        v.addWidget(self.buttons)
        self.result_data: dict | None = None
        self._out = b""
        self._err = b""
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.readyReadStandardError.connect(lambda: setattr(self, "_err", (self._err + bytes(
            self.proc.readAllStandardError()))[-4000:]))
        self.proc.finished.connect(self._finished)
        QTimer.singleShot(0, self._start)

    def _start(self):
        self.proc.start(sys.executable, [str(LIB / "perfinfo_assess.py"), "--json"])

    def _read(self):
        self._out += bytes(self.proc.readAllStandardOutput())
        *lines, self._out = self._out.split(b"\n")
        for raw in lines:
            line = raw.decode(errors="replace").strip()
            if line.startswith("progress "):
                _, pct, *text = line.split(" ", 2)
                self.bar.setValue(int(pct) if pct.isdigit() else self.bar.value())
                self.step.setText(text[0] if text else "")
            elif line.startswith("result "):
                try:
                    self.result_data = json.loads(line[7:])
                except ValueError:
                    pass

    def _finished(self, *_a):
        self._read()
        if self.result_data is not None:
            self.accept()
            return
        self.step.setText("The assessment stopped before it had finished.\n"
                          + (self._err.decode(errors="replace").strip().splitlines() or [""])[-1][:300])
        self.buttons.setStandardButtons(QDialogButtonBox.Close)

    def reject(self):
        if self.proc.state() != QProcess.NotRunning:
            pid = self.proc.processId()
            try:
                os.killpg(pid, signal.SIGTERM)          # the tests in other processes too
            except OSError:
                pass
            self.proc.kill()
            self.proc.waitForFinished(2000)
        super().reject()


# ---- the window -----------------------------------------------------------------------------------
class PerfInfo(PageWindow):
    def __init__(self, page: str = "home"):
        super().__init__(APP, ["System and Security", APP], "utilities-system-monitor")
        self.resize(920, 660)
        self.page = page
        self.data: dict | None = None
        self.loader: FactsLoader | None = None
        self.loading_step = ""
        self.saved_to = ""
        self.nav_link("Adjust visual effects", lambda: ci.launch(["kcmshell6", "kcm_animations"]))
        self.nav_link("Adjust power settings", lambda: ci.launch(["kcmshell6", "kcm_powerdevilprofilesconfig"]))
        self.nav_link("Advanced tools", lambda: self.show_page("advanced"))
        self.nav_link("System health report", lambda: self.show_page("report"))
        self.see_also_link("Action Center", lambda: ci.launch(["classic7-actioncenter"]))
        self.see_also_link("System", lambda: ci.launch(["classic7-system"]))
        self.render()
        self.load()

    # -- data
    def load(self):
        if self.loader is not None and self.loader.isRunning():
            return
        self.data = None
        self.loading_step = ""
        self.loader = FactsLoader()
        self.loader.step.connect(self._step)
        self.loader.done.connect(self._loaded)
        self.loader.start()
        if self.page == "report":
            self.render()

    def _step(self, text: str):
        self.loading_step = text
        if self.page == "report" and hasattr(self, "_status"):
            self._status.setText(f"Collecting information: {text}...")

    def _loaded(self, data: dict):
        self.data = data
        self.render()

    def refresh(self):          # F5
        self.load()
        self.render()

    def show_page(self, page: str):
        self.page = page
        self.saved_to = ""
        self.render()

    # -- pages
    def render(self):
        self.clear_body()
        trail = {"home": [], "advanced": ["Advanced Tools"], "report": ["System health report"]}[self.page]
        self.address.setText("  ▸ " + " ▸ ".join(["Control Panel", "System and Security", APP, *trail]))
        {"home": self._home, "advanced": self._advanced, "report": self._report}[self.page]()

    def _home(self):
        scores = pc.load_scores()
        rated = bool(scores.get("scores"))
        self.body.addWidget(self.heading("Rate and improve your computer's performance"))
        intro = QLabel("The Classic 7 Experience Index assesses key system components on a scale of 1.0 to 7.9.")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self.body.addSpacing(6)

        table = QFrame()
        table.setObjectName("scores")
        table.setStyleSheet("#scores { border: 1px solid #c9d7e8; background: white; }")
        g = QGridLayout(table)
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(0)
        g.setVerticalSpacing(0)
        heads = ["Component", "What is rated", "Subscore", "Base score"]
        for c, text in enumerate(heads):
            h = QLabel(text)
            h.setStyleSheet("background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6f9fd, stop:1 #e4ecf7);"
                            " border-bottom: 1px solid #c9d7e8; padding: 5px 10px; color: #333;")
            h.setAlignment((Qt.AlignRight if c == 2 else Qt.AlignHCenter if c == 3 else Qt.AlignLeft) | Qt.AlignVCenter)
            g.addWidget(h, 0, c)
        for r, (key, name, what) in enumerate(pc.COMPONENTS, start=1):
            s = (scores.get("scores") or {}).get(key)
            detail = (scores.get("details") or {}).get(key, "")
            line = "border-bottom: 1px solid #e1e8f1;" if r < len(pc.COMPONENTS) else ""
            cell = QWidget()
            cell.setObjectName("cell")
            cell.setAttribute(Qt.WA_StyledBackground, True)
            cell.setStyleSheet(f"#cell {{ {line} }}")
            h = QHBoxLayout(cell)
            h.setContentsMargins(10, 7, 10, 7)
            pic = QLabel()
            pic.setPixmap(icon(*ICONS[key]).pixmap(20, 20))
            h.addWidget(pic)
            h.addWidget(QLabel(name), 1)
            w = QLabel(what)
            w.setStyleSheet(line + " padding: 7px 10px;")
            sub = QLabel(fmt_score(s))
            f = sub.font()
            f.setBold(True)
            sub.setFont(f)
            sub.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            sub.setStyleSheet(line + " padding: 7px 14px;")
            for wdg in (cell, w, sub):
                wdg.setToolTip(detail)
                g.addWidget(wdg, r, [cell, w, sub].index(wdg))
        badge_box = QWidget()
        bv = QVBoxLayout(badge_box)
        bv.setContentsMargins(18, 8, 18, 8)
        bv.setAlignment(Qt.AlignCenter)
        if rated:
            base = pc.base_score(scores)
            badge = ScoreBadge(base)
            bv.addWidget(badge, 0, Qt.AlignHCenter)
            cap = QLabel("Determined by\nlowest subscore")
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet("color: #555;")
            bv.addWidget(cap)
        else:
            lab = QLabel("Not rated")
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet("color: #555;")
            bv.addWidget(lab)
        badge_box.setObjectName("badgebox")
        badge_box.setAttribute(Qt.WA_StyledBackground, True)
        badge_box.setStyleSheet("#badgebox { border-left: 1px solid #eef2f7; }")
        g.addWidget(badge_box, 1, 3, len(pc.COMPONENTS), 1)
        g.setColumnStretch(1, 1)
        self.body.addWidget(table)

        # under the table: the links on the left, the date and Re-run on the right
        row = QHBoxLayout()
        left = QVBoxLayout()
        what = Link("What do these numbers mean?", BLUE)
        what.clicked.connect(self._explain)
        left.addWidget(what)
        details = Link("View and print detailed performance and system information", BLUE)
        details.clicked.connect(lambda: self.show_page("report"))
        left.addWidget(details)
        left.addStretch(1)
        row.addLayout(left, 1)
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignRight | Qt.AlignTop)
        if rated:
            current = scores.get("hardware") == pc.hardware_key()
            status = QLabel(("Your scores are current." if current else
                             "<span style='color:#a00'>The hardware changed since the last assessment.</span>")
                            + f"<br>Last update: {scores.get('date', '?')}")
            status.setAlignment(Qt.AlignRight)
            right.addWidget(status)
            again = Link("Re-run the assessment", BLUE)
            again.clicked.connect(self.rate)
            right.addWidget(again, 0, Qt.AlignRight)
        else:
            status = QLabel("Your computer hasn't been rated yet.")
            status.setAlignment(Qt.AlignRight)
            right.addWidget(status)
            b = QPushButton("Rate this computer")
            b.clicked.connect(self.rate)
            right.addWidget(b, 0, Qt.AlignRight)
        row.addLayout(right)
        self.body.addLayout(row)

        # what Classic 7 found, once the facts are in
        self.body.addSpacing(10)
        box = QFrame()
        box.setObjectName("help")
        box.setStyleSheet("#help { background: #f5f8fc; border: 1px solid #dde6f2; }")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 10, 12, 10)
        if self.data is None:
            bl.addWidget(QLabel("Looking for performance issues..."))
        elif self.data.get("error"):
            bl.addWidget(QLabel(f"Classic 7 couldn't look for performance issues: {self.data['error']}"))
        else:
            found = self.data["issues"]
            important = [i for i in found if i.important]
            if found:
                lab = QLabel(f"<b>Classic 7 found {len(found)} performance issue{'s' if len(found) != 1 else ''}</b>"
                             + (f" ({len(important)} important)" if important else "") + ":")
                bl.addWidget(lab)
                for i in found[:4]:
                    t = QLabel(("• " if not i.important else "• <span style='color:#a00'>") + i.title
                               + ("</span>" if i.important else ""))
                    t.setTextFormat(Qt.RichText)
                    bl.addWidget(t)
                more = Link("View the details in Advanced tools", BLUE)
                more.clicked.connect(lambda: self.show_page("advanced"))
                bl.addWidget(more)
            else:
                bl.addWidget(QLabel("Classic 7 found no performance issues."))
        bl.addSpacing(6)
        help_lab = QLabel("Need help with a problem? Save a system health report and send it to whoever helps you: "
                          "it describes this computer, its settings and what went wrong recently.")
        help_lab.setWordWrap(True)
        bl.addWidget(help_lab)
        rep = Link("Save a system health report", BLUE, bold=True)
        rep.clicked.connect(lambda: self.show_page("report"))
        bl.addWidget(rep)
        self.body.addWidget(box)
        self.body.addStretch(1)

    def _advanced(self):
        self.body.addWidget(self.heading("Advanced tools"))
        lab = QLabel("Performance issues:")
        lab.setStyleSheet("color: #1e3287;")
        self.body.addWidget(lab)
        if self.data is None:
            self.body.addWidget(QLabel("Looking for performance issues..."))
        elif self.data.get("error"):
            self.body.addWidget(QLabel(f"Classic 7 couldn't look for performance issues: {self.data['error']}"))
        elif not self.data["issues"]:
            self.body.addWidget(QLabel("No performance issues were found."))
        else:
            for i in self.data["issues"]:
                self.body.addWidget(IssueBox(i))
        self.body.addSpacing(8)
        clear = Link("Clear all Classic 7 Experience Index scores and re-rate the system", BLUE)
        clear.clicked.connect(self._clear_and_rate)
        self.body.addWidget(clear)
        self.body.addSpacing(10)
        tools = [
            ("View performance details in Event log", "Errors and warnings of programs and services",
             "text-x-log", ["classic7-eventvwr"]),
            ("View problem reports", "Programs that stopped working", "dialog-warning", ["classic7-eventvwr", "--problems"]),
            ("Open Resource Monitor", "Which programs use the processor, memory, disk and network",
             "utilities-system-monitor", ["classic7-resmon"]),
            ("Open Task Manager", "Running programs and how busy the computer is", "utilities-system-monitor",
             ["classic7-taskmgr"]),
            ("View advanced system details in System Information", "Hardware and drivers in detail", "hwinfo",
             ["kinfocenter"] if shutil.which("kinfocenter") else ["classic7-system"]),
            ("Adjust the appearance and performance of Classic 7", "Animations and visual effects",
             "preferences-desktop-theme", ["kcmshell6", "kcm_animations"]),
            ("Open System Configuration", "Programs and services that start with the computer",
             "preferences-system", ["classic7-msconfig"]),
            ("Open Device Manager", "Devices and their drivers", "computer", ["classic7-devmgmt"]),
        ]
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(7)
        for r, (title, text, icon_name, cmd) in enumerate(tools):
            pic = QLabel()
            pic.setPixmap(icon(icon_name, "preferences-system").pixmap(22, 22))
            grid.addWidget(pic, r, 0, Qt.AlignTop)
            link = Link(title, BLUE)
            link.clicked.connect(lambda c=cmd: ci.launch(c))
            grid.addWidget(link, r, 1)
            note = QLabel(text)
            note.setStyleSheet("color: #666;")
            note.setWordWrap(True)
            grid.addWidget(note, r, 2)
        r = len(tools)
        pic = QLabel()
        pic.setPixmap(icon("document-save", "text-x-generic").pixmap(22, 22))
        grid.addWidget(pic, r, 0)
        link = Link("Generate a system health report", BLUE)
        link.clicked.connect(lambda: self.show_page("report"))
        grid.addWidget(link, r, 1)
        note = QLabel("Everything someone helping you needs to know, in one file")
        note.setStyleSheet("color: #666;")
        note.setWordWrap(True)
        grid.addWidget(note, r, 2)
        grid.setColumnStretch(2, 1)
        self.body.addLayout(grid)
        self.body.addStretch(1)

    def _report(self):
        self.body.addWidget(self.heading("System health report"))
        intro = QLabel("Everything someone helping you with a problem needs to know about this computer: the "
                       "performance issues Classic 7 can see, the Experience Index, the hardware, the Classic 7 "
                       "version and settings, and this boot's error messages. It has no passwords, keys, serial "
                       "numbers or network hardware (MAC) addresses.")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        self._status = QLabel()
        self.body.addWidget(self._status)
        if self.data is None:
            self._status.setText(f"Collecting information{': ' + self.loading_step if self.loading_step else ''}...")
            bar = QProgressBar()
            bar.setRange(0, 0)
            bar.setMaximumWidth(300)
            self.body.addWidget(bar)
            self.body.addStretch(1)
            return
        if self.data.get("error"):
            self._status.setText(f"The report couldn't be made: {self.data['error']}")
            self.body.addStretch(1)
            return
        self._status.setText(f"Saved as {self.saved_to}" if self.saved_to else
                             "Save it as a file and send it, or copy it into a message.")
        text = QPlainTextEdit(self.data["report"])
        text.setReadOnly(True)
        text.setLineWrapMode(QPlainTextEdit.NoWrap)
        text.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        text.setMinimumHeight(380)
        self.body.addWidget(text, 1)
        row = QHBoxLayout()
        save = QPushButton(icon("document-save-as", "document-save"), "Save As...")
        save.clicked.connect(self._save)
        copy = QPushButton(icon("edit-copy"), "Copy")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(self.data["report"]),
                                      self._status.setText("The report is on the clipboard.")))
        again = QPushButton(icon("view-refresh"), "Refresh")
        again.clicked.connect(self.refresh)
        row.addWidget(save)
        row.addWidget(copy)
        row.addStretch(1)
        row.addWidget(again)
        self.body.addLayout(row)

    # -- actions
    def _save(self):
        docs = Path.home() / "Documents"
        folder = docs if docs.is_dir() else Path.home()
        name = folder / time.strftime("Classic7-report-%Y-%m-%d-%H%M.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save the system health report", str(name),
                                              "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            Path(path).write_text(self.data["report"])
        except OSError as e:
            QMessageBox.warning(self, APP, f"The report couldn't be saved:\n{e}")
            return
        self.saved_to = path
        self._status.setText(f"Saved as {path}")

    def _explain(self):
        QMessageBox.information(self, "What do these numbers mean?", (
            "The Classic 7 Experience Index rates five parts of the computer from 1.0 to 7.9; higher is faster. "
            "The base score is the lowest subscore: the part that holds the computer back the most.\n\n"
            "Processor: compressing text on one core and on all of them.\n"
            "Memory: how fast memory is copied (and how much there is).\n"
            "Graphics: a window redrawn for every picture the screen shows: does the desktop keep up?\n"
            "Gaming graphics: 3D pictures with many see-through layers, as fast as the graphics can draw.\n"
            "Primary hard disk: reading and writing a large file, and reading small pieces of it at random.\n\n"
            "About 2 means graphics drawn by the processor (no 3D driver), a very slow disk or processor. "
            "3 to 5 is fine for office work, the web and video. 6 and up is fast.\n\n"
            "The scores stay until you run the assessment again; they're marked old when the processor, "
            "memory or graphics change."))

    def rate(self):
        dlg = AssessDialog(self)
        if dlg.exec() == QDialog.Accepted:
            if self.data and self.data.get("facts") is not None:
                # the issues that depend on the scores, and the report with them
                scores = pc.load_scores()
                self.data["issues"] = pc.issues(self.data["facts"], scores)
                self.load()
            self.page = "home"
        self.render()

    def _clear_and_rate(self):
        if QMessageBox.question(self, APP, "Clear the Classic 7 Experience Index scores and rate the computer "
                                           "again?") != QMessageBox.Yes:
            return
        try:
            pc.SCORES.unlink()
        except OSError:
            pass
        self.page = "home"
        self.render()
        self.rate()


class IssueBox(QFrame):
    """One performance issue: a coloured bar (red: important, yellow: worth knowing), the text and,
    if Classic 7 knows one, the button that helps."""

    def __init__(self, issue: pc.Issue):
        super().__init__()
        self.color = QColor("#d43f3a") if issue.important else QColor("#f0b400")
        g = QGridLayout(self)
        g.setContentsMargins(16, 8, 10, 8)
        title = QLabel(f"<b>{issue.title}</b>")
        g.addWidget(title, 0, 0)
        text = QLabel(issue.text)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        g.addWidget(text, 1, 0)
        if issue.fix:
            b = QPushButton(issue.fix_text or "Fix")
            b.clicked.connect(lambda: ci.launch(issue.fix))
            g.addWidget(b, 0, 1, 2, 1, Qt.AlignTop)
        g.setColumnStretch(0, 1)
        self.setStyleSheet("IssueBox { background: #fbfbfb; border: 1px solid #e3e3e3; }")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.fillRect(0, 0, 6, self.height(), self.color)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-perfinfo")
    app.setDesktopFileName("classic7-perfinfo")
    page = "advanced" if "--advanced" in argv else "report" if "--report" in argv else "home"
    w = PerfInfo(page)
    w.show()
    if "--rate" in argv:
        QTimer.singleShot(300, w.rate)
    return app.exec()
