"""System (Win+Pause) and System Properties (sysdm.cpl), in the style of Windows 7."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt
from PySide6.QtGui import QColor, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton,
                               QScrollArea, QTabWidget, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import sysinfo as si
from control_panel import BLUE, HEAD, Link, NavPane, icon

LABEL = QColor(0x55, 0x55, 0x55)
SECTION = QColor(0x1e, 0x39, 0x87)


def run_detached(argv: list[str]) -> bool:
    if not argv or not shutil.which(argv[0]):
        return False
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return True


def human_gb(n: int) -> str:
    return f"{n / 1024 ** 3:.1f} GB" if n else "?"


# ---- System Properties -------------------------------------------------------------------------
class ChangeNameDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Computer Name/Domain Changes")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("You can change the name of this computer. Changes might affect access to "
                             "network resources."))
        host, _pretty = si.computer_name()
        lay.addWidget(QLabel("Computer name:"))
        self.name = QLineEdit(host)
        lay.addWidget(self.name)
        lay.addWidget(QLabel(f"Full computer name:\n{host}"))
        box = QGroupBox("Member of")
        bl = QVBoxLayout(box)
        bl.addWidget(QLabel(f"Workgroup:  {si.workgroup()}"))
        lay.addWidget(box)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        name = self.name.text().strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", name):
            QMessageBox.warning(self, "Computer Name/Domain Changes",
                                "The new computer name may contain only letters (a-z), digits (0-9) and hyphens, "
                                "and can be at most 63 characters long.")
            return
        r = subprocess.run(["hostnamectl", "set-hostname", name], capture_output=True, text=True)
        if r.returncode != 0:
            QMessageBox.warning(self, "Computer Name/Domain Changes",
                                f"The computer name could not be changed.\n\n{r.stderr.strip()}")
            return
        QMessageBox.information(self, "Computer Name/Domain Changes",
                                "The computer name has been changed. Some programs see the new name after "
                                "you restart the computer.")
        self.accept()


class EnvironmentDialog(QDialog):
    """Environment Variables: your own (in ~/.config/environment.d) and the system's (read only)."""
    FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "environment.d" / "90-classic7.conf"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Environment Variables")
        self.resize(480, 460)
        lay = QVBoxLayout(self)
        user = QGroupBox(f"User variables for {os.environ.get('USER', '')}")
        ul = QVBoxLayout(user)
        self.user = QTreeWidget()
        self.user.setHeaderLabels(["Variable", "Value"])
        self.user.setRootIsDecorated(False)
        ul.addWidget(self.user)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, fn in (("New...", self._new), ("Edit...", self._edit), ("Delete", self._delete)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        ul.addLayout(row)
        lay.addWidget(user)
        system = QGroupBox("System variables")
        sl = QVBoxLayout(system)
        sysv = QTreeWidget()
        sysv.setHeaderLabels(["Variable", "Value"])
        sysv.setRootIsDecorated(False)
        for k in sorted(os.environ):
            if k in ("PATH", "LANG", "SHELL", "HOME", "USER", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "EDITOR",
                     "TERM", "QT_QPA_PLATFORM") or k.startswith(("LC_",)):
                QTreeWidgetItem(sysv, [k, os.environ[k]])
        sl.addWidget(sysv)
        lay.addWidget(system)
        note = QLabel("Your variables take effect the next time you log on.")
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._load()

    def _load(self):
        try:
            for line in self.FILE.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, _, v = line.partition("=")
                    QTreeWidgetItem(self.user, [k.strip(), v.strip()])
        except OSError:
            pass

    def _ask(self, title, name="", value=""):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        f = QFormLayout(dlg)
        n, v = QLineEdit(name), QLineEdit(value)
        v.setMinimumWidth(300)
        f.addRow("Variable name:", n)
        f.addRow("Variable value:", v)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", n.text().strip()):
            return n.text().strip(), v.text().replace("\n", " ")
        return None

    def _new(self):
        r = self._ask("New User Variable")
        if r:
            QTreeWidgetItem(self.user, list(r))

    def _edit(self):
        it = self.user.currentItem()
        if it:
            r = self._ask("Edit User Variable", it.text(0), it.text(1))
            if r:
                it.setText(0, r[0])
                it.setText(1, r[1])

    def _delete(self):
        it = self.user.currentItem()
        if it:
            self.user.takeTopLevelItem(self.user.indexOfTopLevelItem(it))

    def _save(self):
        lines = ["# Environment variables set in System Properties (Classic 7)"]
        for i in range(self.user.topLevelItemCount()):
            it = self.user.topLevelItem(i)
            lines.append(f"{it.text(0)}={it.text(1)}")
        try:
            self.FILE.parent.mkdir(parents=True, exist_ok=True)
            self.FILE.write_text("\n".join(lines) + "\n")
        except OSError as e:
            QMessageBox.warning(self, "Environment Variables", f"Could not save: {e}")
            return
        self.accept()


class SystemProperties(QDialog):
    def __init__(self, parent=None, tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("System Properties")
        self.resize(480, 500)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._name_tab(), "Computer Name")
        self.tabs.addTab(self._hardware_tab(), "Hardware")
        self.tabs.addTab(self._advanced_tab(), "Advanced")
        self.tabs.addTab(self._protection_tab(), "System Protection")
        self.tabs.addTab(self._remote_tab(), "Remote")
        self.tabs.setCurrentIndex(tab)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        lay.addWidget(bb)

    def _name_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(icon("computer").pixmap(32, 32))
        row.addWidget(ic, 0, Qt.AlignTop)
        t = QLabel("Classic 7 uses the following information to identify your computer on the network.")
        t.setWordWrap(True)
        row.addWidget(t, 1)
        lay.addLayout(row)
        host, pretty = si.computer_name()
        f = QFormLayout()
        self.desc = QLineEdit(pretty)
        self.desc.setPlaceholderText('For example: "Kitchen Computer" or "Mary\'s Computer".')
        f.addRow("Computer description:", self.desc)
        f.addRow("Full computer name:", QLabel(host))
        f.addRow("Workgroup:", QLabel(si.workgroup()))
        lay.addLayout(f)
        lay.addSpacing(10)
        row2 = QHBoxLayout()
        lab = QLabel("To rename this computer, click Change.")
        lab.setWordWrap(True)
        row2.addWidget(lab, 1)
        b = QPushButton("Change...")
        b.clicked.connect(lambda: ChangeNameDialog(self).exec())
        row2.addWidget(b)
        lay.addLayout(row2)
        lay.addStretch(1)
        return w

    def _hardware_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("Device Manager")
        bl = QHBoxLayout(box)
        ic = QLabel()
        ic.setPixmap(icon("computer").pixmap(32, 32))
        bl.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        t = QLabel("Device Manager lists all the hardware devices installed on your computer. Use Device "
                   "Manager to see the driver and status of any device.")
        t.setWordWrap(True)
        col.addWidget(t)
        b = QPushButton("Device Manager")
        b.clicked.connect(lambda: run_detached(["classic7-devmgmt"]))
        col.addWidget(b, 0, Qt.AlignRight)
        bl.addLayout(col, 1)
        lay.addWidget(box)
        box2 = QGroupBox("Device drivers")
        b2 = QVBoxLayout(box2)
        t2 = QLabel("Drivers come with Classic 7 and its updates, so there is nothing to install by hand.")
        t2.setWordWrap(True)
        b2.addWidget(t2)
        lay.addWidget(box2)
        lay.addStretch(1)
        return w

    def _advanced_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("You must be logged on as an Administrator to make most of these changes."))

        def group(title, text, button, fn):
            box = QGroupBox(title)
            bl = QVBoxLayout(box)
            lab = QLabel(text)
            lab.setWordWrap(True)
            bl.addWidget(lab)
            b = QPushButton(button)
            b.clicked.connect(fn)
            bl.addWidget(b, 0, Qt.AlignRight)
            lay.addWidget(box)
        group("Performance", "Visual effects and animation speed", "Settings...",
              lambda: run_detached(["kcmshell6", "kcm_animations"]))
        group("User Profiles", "Accounts on this computer", "Settings...",
              lambda: run_detached(["kcmshell6", "kcm_users"]))
        group("Startup and Recovery", "Programs that start with Classic 7, and going back to an earlier version",
              "Settings...", lambda: run_detached(["kcmshell6", "kcm_autostart"]))
        env = QPushButton("Environment Variables...")
        env.clicked.connect(lambda: EnvironmentDialog(self).exec())
        lay.addWidget(env, 0, Qt.AlignRight)
        lay.addStretch(1)
        return w

    def _protection_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        t = QLabel("Classic 7 keeps the previous version of the whole system after every update. If an update "
                   "causes problems, System Restore goes back to that version at the next restart. Your files "
                   "and settings are not changed.")
        t.setWordWrap(True)
        lay.addWidget(t)
        box = QGroupBox("System Restore")
        bl = QVBoxLayout(box)
        self.versions = QLabel("Reading the versions...")
        self.versions.setWordWrap(True)
        self.versions.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bl.addWidget(self.versions)
        b = QPushButton("System Restore...")
        b.clicked.connect(self._restore)
        bl.addWidget(b, 0, Qt.AlignRight)
        lay.addWidget(box)
        lay.addStretch(1)
        if shutil.which("classic7-update"):
            self._status = QProcess(self)
            self._status.finished.connect(lambda *_: self.versions.setText(
                bytes(self._status.readAllStandardOutput()).decode(errors="replace").strip()
                or "The versions could not be read."))
            self._status.start("classic7-update", ["--status"])
        else:
            self.versions.setText("")
        return w

    def _restore(self):
        if QMessageBox.question(self, "System Restore",
                                "Go back to the previous version of Classic 7 the next time the computer "
                                "starts?\n\nYour files and settings are not changed.") != QMessageBox.Yes:
            return
        r = subprocess.run(["classic7-update", "--rollback"], capture_output=True, text=True)
        QMessageBox.information(self, "System Restore", (r.stdout + r.stderr).strip()
                                or ("Done. Restart the computer to go back." if r.returncode == 0 else "It did not work."))

    def _remote_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("Remote Desktop")
        bl = QVBoxLayout(box)
        t = QLabel("Let other computers connect to this one with Remote Desktop (RDP).")
        t.setWordWrap(True)
        bl.addWidget(t)
        b = QPushButton("Remote Desktop settings...")
        b.clicked.connect(lambda: run_detached(["kcmshell6", "kcm_krdpserver"]))
        bl.addWidget(b, 0, Qt.AlignRight)
        lay.addWidget(box)
        lay.addStretch(1)
        return w

    def _apply(self):
        _host, pretty = si.computer_name()
        if self.desc.text().strip() != pretty:
            r = subprocess.run(["hostnamectl", "set-hostname", "--pretty", self.desc.text().strip()],
                               capture_output=True, text=True)
            if r.returncode != 0:
                QMessageBox.warning(self, "System Properties", f"The description could not be saved.\n\n{r.stderr}")
                return False
        return True

    def _ok(self):
        if self._apply():
            self.accept()


# ---- the System window -----------------------------------------------------------------------------
class SystemWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("System")
        self.setWindowIcon(icon("computer"))
        self.resize(860, 620)
        nav = QToolBar("Navigation")
        nav.setMovable(False)
        nav.setIconSize(QSize(22, 22))
        nav.addAction(icon("go-previous"), "Back").setEnabled(False)
        nav.addAction(icon("go-next"), "Forward").setEnabled(False)
        address = QLineEdit("  ▸ Control Panel ▸ System and Security ▸ System ▸")
        address.setReadOnly(True)
        address.addAction(icon("computer"), QLineEdit.LeadingPosition)
        nav.addWidget(address)
        search = QLineEdit()
        search.setPlaceholderText("Search Control Panel")
        search.setFixedWidth(220)
        search.returnPressed.connect(lambda: run_detached(["classic7-control"]))
        nav.addWidget(search)
        self.addToolBar(Qt.TopToolBarArea, nav)

        page = QWidget()
        page.setAutoFillBackground(True)
        pal = page.palette()
        pal.setColor(QPalette.Window, QColor(255, 255, 255))
        page.setPalette(pal)
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        side = NavPane()
        for text, argv in (("Control Panel Home", ["classic7-control"]), ("Device Manager", ["classic7-devmgmt"]),
                           ("Remote settings", None), ("System protection", None),
                           ("Advanced system settings", None)):
            ln = Link(text, BLUE)
            ln.setWordWrap(True)
            if argv:
                ln.clicked.connect(lambda a=argv: run_detached(a))
            else:
                tab = {"Remote settings": 4, "System protection": 3, "Advanced system settings": 2}[text]
                ln.clicked.connect(lambda t=tab: SystemProperties(self, t).exec())
            side.lay.addWidget(ln)
        side.lay.addStretch(1)
        see = QLabel("See also")
        see.setStyleSheet("color: #555;")
        side.lay.addWidget(see)
        for text, argv in (("Classic 7 Update", ["classic7-update", "--gui"]),
                           ("Performance Information and Tools", ["classic7-taskmgr", "--performance"])):
            ln = Link(text, BLUE)
            ln.setWordWrap(True)
            ln.clicked.connect(lambda a=argv: run_detached(a))
            side.lay.addWidget(ln)
        row.addWidget(side)

        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(26, 16, 26, 16)
        self.body.setSpacing(6)
        row.addWidget(body, 1)
        self._fill()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameStyle(QFrame.NoFrame)
        scroll.setWidget(page)
        self.setCentralWidget(scroll)
        QShortcut(QKeySequence("F5"), self, self._refresh)

    def _refresh(self):
        while self.body.count():
            it = self.body.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                _clear(it.layout())
        self._fill()

    def _section(self, title: str):
        lab = QLabel(title)
        f = lab.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        lab.setFont(f)
        lab.setStyleSheet(f"color: {SECTION.name()};")
        self.body.addSpacing(10)
        row = QHBoxLayout()
        row.addWidget(lab)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #d5dfe9;")
        row.addWidget(line, 1)
        self.body.addLayout(row)

    def _rows(self, rows: list[tuple[str, str]], right: QWidget | None = None):
        outer = QHBoxLayout()
        g = QGridLayout()
        g.setContentsMargins(24, 2, 0, 2)
        g.setHorizontalSpacing(18)
        g.setVerticalSpacing(6)
        g.setColumnMinimumWidth(0, 170)
        rows = [(k, v) for k, v in rows if v]
        for i, (k, v) in enumerate(rows):
            kl = QLabel(k)
            kl.setStyleSheet(f"color: {LABEL.name()};")
            vl = QLabel(v)
            vl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            vl.setWordWrap(True)
            g.addWidget(kl, i, 0, Qt.AlignTop)
            g.addWidget(vl, i, 1)
        g.setColumnStretch(1, 1)
        outer.addLayout(g, 1)
        if right is not None:
            outer.addWidget(right, 0, Qt.AlignTop)
        self.body.addLayout(outer)

    def _fill(self):
        h = QLabel("View basic information about your computer")
        f = h.font()
        f.setPointSizeF(f.pointSizeF() + 4)
        h.setFont(f)
        h.setStyleSheet(f"color: {HEAD.name()};")
        self.body.addWidget(h)

        rel = si.os_release()
        self._section("Classic 7 edition")
        logo = QLabel()
        logo.setPixmap(icon("start-here", "computer").pixmap(96, 96))
        build = si.classic7_version()
        base = rel.get("PRETTY_NAME") or "Fedora"
        self._rows([("Edition:", "Classic 7"), ("Based on:", base),
                    ("Version:", build.replace("T", " ").replace("Z", " UTC") if build else ""),
                    ("Licence:", "Free and open source software")], logo)

        self._section("System")
        cores, threads = si.cpu_count()
        installed, usable = si.memory()
        ghz = si.cpu_ghz()
        cpu = si.cpu_name()
        if ghz and ghz.split()[0] not in cpu:
            cpu = f"{cpu}   {ghz}"
        maker, model = si.manufacturer_model()
        rows = []
        if maker or model:
            rows += [("Manufacturer:", maker), ("Model:", model)]
        rows += [("Processor:", f"{cpu}\n{cores} cores, {threads} threads"),
                 ("Installed memory (RAM):", f"{human_gb(installed)} ({human_gb(usable)} usable)"),
                 ("Graphics:", "\n".join(si.graphics()) or "Unknown"),
                 ("System type:", si.system_type()),
                 ("Pen and Touch:", si.touch_input())]
        self._rows(rows)

        self._section("Computer name, domain, and workgroup settings")
        host, pretty = si.computer_name()
        change = Link("Change settings", BLUE)
        change.clicked.connect(lambda: SystemProperties(self, 0).exec())
        self._rows([("Computer name:", host), ("Full computer name:", host),
                    ("Computer description:", pretty), ("Workgroup:", si.workgroup())], change)

        self._section("Activation")
        self._rows([("", "Classic 7 is free software. There is nothing to activate.")])
        self.body.addStretch(1)


def _clear(layout):
    while layout.count():
        it = layout.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear(it.layout())


def main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]] + argv)
    app.setApplicationName("System")
    app.setDesktopFileName("classic7-system")
    if argv and argv[0] in ("--properties", "sysdm.cpl"):
        tab = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 0
        dlg = SystemProperties(None, tab)
        dlg.show()
        dlg.finished.connect(app.quit)
        return app.exec()
    w = SystemWindow()
    w.show()
    return app.exec()
