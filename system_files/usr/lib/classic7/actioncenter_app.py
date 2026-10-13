"""Action Center, as in Windows 7: "Review recent messages and resolve problems", with the
Security and Maintenance sections, a button to fix each problem, and archiving.

    classic7-actioncenter            the window
    classic7-actioncenter --json     the messages, for the flag in the notification area
    classic7-actioncenter --archived the archived messages
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import actioncenter_checks as checks
import control_items as ci
from control_panel import BLUE, Link
from cpl_page import PageWindow

APP = "Action Center"


class Loader(QThread):
    done = Signal(object)

    def run(self):
        self.done.emit(checks.collect())


class MessageBox(QFrame):
    """One message: a coloured bar (red: important, yellow: worth doing), title, text, the fix
    button and "Archive this message"."""

    def __init__(self, m: dict, on_archive, archived_view: bool):
        super().__init__()
        self.color = QColor("#d43f3a") if m["important"] else QColor("#f0b400")
        g = QGridLayout(self)
        g.setContentsMargins(16, 8, 10, 8)
        title = QLabel(f"<b>{m['title']}</b>" + ("  <span style='color:#a00'>(Important)</span>" if m["important"] else ""))
        g.addWidget(title, 0, 0)
        text = QLabel(m["text"])
        text.setWordWrap(True)
        g.addWidget(text, 1, 0)
        links = QHBoxLayout()
        arch = Link("Restore this message" if archived_view else "Archive this message", BLUE)
        arch.clicked.connect(lambda: on_archive(m["key"], not archived_view))
        links.addWidget(arch)
        links.addStretch(1)
        g.addLayout(links, 2, 0)
        if m.get("fix") and not archived_view:
            b = QPushButton(m["fix_text"])
            b.clicked.connect(lambda: ci.launch(m["fix"]))
            g.addWidget(b, 0, 1, 2, 1, Qt.AlignTop)
        g.setColumnStretch(0, 1)
        self.setStyleSheet("MessageBox { background: #fbfbfb; border: 1px solid #e3e3e3; }")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.fillRect(0, 0, 6, self.height(), self.color)


class Section(QWidget):
    def __init__(self, title: str):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        lab = QLabel(title)
        f = lab.font()
        f.setPointSizeF(f.pointSizeF() * 1.2)
        lab.setFont(f)
        lab.setStyleSheet("color: #1e3287;")
        head.addWidget(lab)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #c9d7e8;")
        head.addWidget(line, 1)
        v.addLayout(head)
        self.v = v


class ActionCenter(PageWindow):
    def __init__(self, archived_view: bool = False):
        super().__init__(APP, ["System and Security", "Action Center"], "flag")
        self.archived_view = archived_view
        self.nav_link("Change Action Center settings", lambda: ci.launch(["kcmshell6", "kcm_notifications"]))
        self.nav_link("Change firewall settings", lambda: ci.launch(["classic7-firewall"]), "security-high")
        self.nav_link("View archived messages", lambda: self.show_view(True))
        self.nav_link("View problem reports", lambda: ci.launch(["classic7-eventvwr", "--problems"]))
        self.see_also_link("Classic 7 Update", lambda: ci.launch(["classic7-update", "--gui"]))
        self.see_also_link("Programs and Features", lambda: ci.launch(["classic7-programs"]))
        self.loader: Loader | None = None
        self.data: dict | None = None
        self.refresh()

    def show_view(self, archived: bool):
        self.archived_view = archived
        self.render()

    def refresh(self):
        if self.loader is not None and self.loader.isRunning():
            return
        self.clear_body()
        self.body.addWidget(self.heading("Review recent messages and resolve problems"))
        self.body.addWidget(QLabel("Please wait..."))
        self.body.addStretch(1)
        self.loader = Loader()
        self.loader.done.connect(self._loaded)
        self.loader.start()

    def _loaded(self, data: dict):
        self.data = data
        self.render()

    def _archive(self, key: str, on: bool):
        checks.archive(key, on)
        for m in (self.data or {}).get("messages", []):
            if m["key"] == key:
                m["archived"] = on
        self.render()

    def render(self):
        data = self.data or {"messages": []}
        self.clear_body()
        if self.archived_view:
            self.body.addWidget(self.heading("Review archived messages"))
            back = Link("Back to Action Center", BLUE)
            back.clicked.connect(lambda: self.show_view(False))
            self.body.addWidget(back)
            msgs = [m for m in data["messages"] if m.get("archived")]
            if not msgs:
                self.body.addWidget(QLabel("There are no archived messages."))
            for m in msgs:
                self.body.addWidget(MessageBox(m, self._archive, True))
            self.body.addStretch(1)
            return
        current = [m for m in data["messages"] if not m.get("archived")]
        self.body.addWidget(self.heading("Review recent messages and resolve problems"))
        self.body.addWidget(QLabel("Action Center has detected one or more issues for you to review." if current else
                                   "No issues have been detected by Action Center."))
        for name in ("Security", "Maintenance"):
            sec = Section(name)
            msgs = [m for m in current if m["section"] == name]
            for m in msgs:
                sec.v.addWidget(MessageBox(m, self._archive, False))
            grid = QGridLayout()
            grid.setContentsMargins(10, 2, 0, 0)
            grid.setHorizontalSpacing(16)
            rows = ([("Network firewall", data.get("firewall", "")), ("Classic 7 Update", data.get("updates", ""))]
                    if name == "Security" else
                    [("Problem reports", f"{data.get('crashes', 0)} in the last week" if data.get("crashes")
                      else "No problems reported"),
                     ("Disk space", "Low on a drive" if any(m["id"].startswith("space:") for m in data["messages"])
                      else "OK")])
            for r, (k, v) in enumerate(rows):
                lk = QLabel(k)
                lk.setStyleSheet("color: #555;")
                grid.addWidget(lk, r, 0)
                grid.addWidget(QLabel(v), r, 1)
            grid.setColumnStretch(2, 1)
            sec.v.addLayout(grid)
            self.body.addWidget(sec)
        self.body.addSpacing(12)
        self.body.addWidget(QLabel("If you don't see your problem listed, try one of these:"))
        row = QHBoxLayout()
        for title, text, cmd in (("Troubleshooting", "Find and fix problems", ["classic7-eventvwr"]),
                                 ("Recovery", "Restore your computer to an earlier time",
                                  ["classic7-system", "--properties", "3"])):
            box = QVBoxLayout()
            link = Link(title, BLUE, bold=True)
            link.clicked.connect(lambda c=cmd: ci.launch(c))
            box.addWidget(link)
            box.addWidget(QLabel(text))
            row.addLayout(box)
        row.addStretch(1)
        self.body.addLayout(row)
        self.body.addStretch(1)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-actioncenter")
    app.setDesktopFileName("classic7-actioncenter")
    w = ActionCenter("--archived" in argv)
    w.show()
    return app.exec()
