"""System Configuration, as in Windows 7 (msconfig).

    classic7-msconfig [--tab startup|services|general|boot|tools]

General: normal, diagnostic or selective startup (the programs that start when you log in).
Boot: the Classic 7 versions the computer can start, and the kernel's options.
Services: the system's and your own services (systemd), with their maker; tick to start them.
Startup: the programs that start when you log in (XDG autostart), with maker, command, location
and the date they were turned off. Tools: the system tools with a Launch button.

Turning off a startup program writes a copy of its .desktop file with Hidden=true into
~/.config/autostart, as KDE's own settings do. System services are changed in one go through
pkexec (systemctl enable/disable), after the password."""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton,
                               QRadioButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

APP = "System Configuration"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
USER_AUTOSTART = CONFIG / "autostart"
SYSTEM_AUTOSTART = [Path(d) / "autostart" for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
STATE = CONFIG / "classic7" / "msconfig.json"
# the desktop's own parts start this way too; turning them off breaks the desktop
CORE_PACKAGES = ("plasma-", "kf6-", "kwin", "polkit-kde", "xdg-desktop-portal", "kde-", "powerdevil", "kscreen",
                 "kded", "baloo", "kwallet", "kactivitymanagerd", "kaccounts", "kglobalacc", "xembed", "kgamma",
                 "kmenuedit", "spectacle", "kdeplasma", "ibus", "at-spi", "gnome-keyring", "pipewire", "wireplumber",
                 "xdg-user-dirs", "orca", "fcitx", "imsettings")


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1) + "\n")
    except OSError:
        pass


def read_desktop(path: Path) -> dict[str, str]:
    out, group = {}, None
    try:
        for line in path.read_text(errors="replace").splitlines():
            s = line.strip()
            if s.startswith("["):
                group = s
            elif group == "[Desktop Entry]" and "=" in s and not s.startswith("#"):
                k, v = s.split("=", 1)
                out.setdefault(k.strip(), v.strip())
    except OSError:
        pass
    return out


def owners(paths: list[str]) -> dict[str, tuple[str, str]]:
    """{path: (package, vendor)} from rpm, in one call."""
    if not paths or not shutil.which("rpm"):
        return {}
    try:
        r = subprocess.run(["rpm", "-qf", "--qf", "%{NAME}\t%{VENDOR}\n", *paths], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    lines = r.stdout.splitlines()
    out = {}
    # rpm prints one line per path, in order ("file ... is not owned by any package" goes to stdout too)
    for path, line in zip(paths, lines):
        if "\t" in line:
            name, vendor = line.split("\t", 1)
            out[path] = (name, "" if vendor == "(none)" else vendor)
    return out


def maker(path: str, own: dict[str, tuple[str, str]]) -> str:
    if path in own:
        name, vendor = own[path]
        if vendor:
            return vendor
        return name
    if "/classic7" in path or Path(path).name.startswith("classic7"):
        return "Classic 7"
    return "Unknown"


# ---- startup programs ---------------------------------------------------------------------------
@dataclass
class StartupItem:
    file: str                  # the .desktop file name
    name: str
    command: str
    location: str              # the folder it comes from
    path: str                  # the system file, or the user file if only that exists
    enabled: bool
    maker: str = ""
    core: bool = False
    disabled_at: float | None = None


def shows_in_kde(e: dict[str, str]) -> bool:
    only = [x for x in e.get("OnlyShowIn", "").split(";") if x]
    notin = [x for x in e.get("NotShowIn", "").split(";") if x]
    return (not only or "KDE" in only) and "KDE" not in notin


def startup_items() -> list[StartupItem]:
    state = load_state().get("startup_disabled", {})
    items: dict[str, StartupItem] = {}
    for d in reversed(SYSTEM_AUTOSTART):
        for f in sorted(d.glob("*.desktop")) if d.is_dir() else []:
            e = read_desktop(f)
            if not shows_in_kde(e) or e.get("Hidden") == "true":
                continue
            items[f.name] = StartupItem(f.name, e.get("Name", f.stem), e.get("Exec", ""), str(d), str(f), True)
    if USER_AUTOSTART.is_dir():
        for f in sorted(USER_AUTOSTART.glob("*.desktop")):
            e = read_desktop(f)
            if not shows_in_kde(e) and f.name not in items:
                continue
            hidden = e.get("Hidden") == "true" or e.get("X-GNOME-Autostart-enabled") == "false"
            if f.name in items:
                it = items[f.name]
                it.enabled = not hidden
                if e.get("Exec"):
                    it.command = e["Exec"]
            else:
                items[f.name] = StartupItem(f.name, e.get("Name", f.stem), e.get("Exec", ""), str(USER_AUTOSTART),
                                            str(f), not hidden)
    own = owners([it.path for it in items.values() if not it.path.startswith(str(USER_AUTOSTART))])
    for it in items.values():
        it.maker = maker(it.path, own)
        pkg = own.get(it.path, ("", ""))[0]
        it.core = bool(pkg) and pkg.startswith(CORE_PACKAGES)
        it.disabled_at = state.get(it.file)
    return sorted(items.values(), key=lambda i: i.name.lower())


def set_startup(it: StartupItem, on: bool) -> str | None:
    user = USER_AUTOSTART / it.file
    try:
        USER_AUTOSTART.mkdir(parents=True, exist_ok=True)
        if not user.exists():
            text = Path(it.path).read_text(errors="replace")
            user.write_text(text)
        lines = user.read_text(errors="replace").splitlines()
        out, group, done = [], None, False
        for ln in lines:
            s = ln.strip()
            if s.startswith("["):
                if group == "[Desktop Entry]" and not done:
                    out.append(f"Hidden={'false' if on else 'true'}")
                    done = True
                group = s
            elif group == "[Desktop Entry]" and s.startswith(("Hidden=", "X-GNOME-Autostart-enabled=")):
                if not done:
                    out.append(f"Hidden={'false' if on else 'true'}")
                    done = True
                continue
            out.append(ln)
        if not done:
            out.append(f"Hidden={'false' if on else 'true'}")
        user.write_text("\n".join(out) + "\n")
    except OSError as e:
        return f"{it.name}: {e.strerror or e}"
    state = load_state()
    dis = state.setdefault("startup_disabled", {})
    if on:
        dis.pop(it.file, None)
    else:
        dis[it.file] = time.time()
    save_state(state)
    return None


# ---- services -------------------------------------------------------------------------------------
@dataclass
class Service:
    unit: str
    user: bool                 # a service of this account (systemctl --user)
    state: str                 # enabled / disabled
    running: bool
    description: str = ""
    maker: str = ""
    path: str = ""
    disabled_at: float | None = None

    @property
    def enabled(self) -> bool:
        return self.state == "enabled"


UNIT_DIRS = {False: ["/etc/systemd/system", "/usr/lib/systemd/system", "/usr/local/lib/systemd/system"],
             True: [str(CONFIG / "systemd/user"), "/etc/systemd/user", "/usr/lib/systemd/user"]}


def _systemctl(user: bool, *args: str) -> str:
    try:
        return subprocess.run(["systemctl", *(["--user"] if user else []), "--no-legend", "--no-pager", *args],
                              capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def services() -> list[Service]:
    state = load_state().get("services_disabled", {})
    out: list[Service] = []
    for user in (False, True):
        running, desc = set(), {}
        for line in _systemctl(user, "list-units", "--type=service", "--all", "--plain").splitlines():
            f = line.split(None, 4)
            if len(f) >= 4:
                if f[3] == "running":
                    running.add(f[0])
                desc[f[0]] = f[4] if len(f) > 4 else ""
        for line in _systemctl(user, "list-unit-files", "--type=service").splitlines():
            f = line.split()
            if len(f) < 2 or f[1] not in ("enabled", "disabled") or "@" in f[0]:
                continue
            path = next((str(Path(d) / f[0]) for d in UNIT_DIRS[user] if (Path(d) / f[0]).exists()), "")
            out.append(Service(f[0], user, f[1], f[0] in running, desc.get(f[0], ""), path=path,
                               disabled_at=state.get(("user:" if user else "") + f[0])))
    own = owners([s.path for s in out if s.path.startswith("/usr")])
    for s in out:
        s.maker = maker(s.path, own) if s.path else "Unknown"
        if not s.description:
            s.description = s.unit.removesuffix(".service")
    return out


# ---- background loading -------------------------------------------------------------------------
class Loader(QThread):
    done = Signal(object, object)

    def run(self):
        self.done.emit(startup_items(), services())


def fmt_date(ts: float | None) -> str:
    return time.strftime("%d-%m-%Y %H:%M", time.localtime(ts)) if ts else ""


class CheckTree(QTreeWidget):
    """A list with a check box in the first column, sortable by any column."""

    def __init__(self, headers: list[str], widths: list[int]):
        super().__init__()
        self.setHeaderLabels(headers)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        for i, w in enumerate(widths):
            self.header().resizeSection(i, w)
        self.header().setSectionResizeMode(QHeaderView.Interactive)


class GeneralTab(QWidget):
    changed = Signal()

    def __init__(self, win: "MsConfig"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        box = QGroupBox("Startup selection")
        b = QVBoxLayout(box)
        self.normal = QRadioButton("Normal startup")
        b.addWidget(self.normal)
        b.addWidget(self._note("Load all startup programs and services"))
        self.diag = QRadioButton("Diagnostic startup")
        b.addWidget(self.diag)
        b.addWidget(self._note("Load basic services only: the programs that start when you log in are turned off"))
        self.sel = QRadioButton("Selective startup")
        b.addWidget(self.sel)
        self.load_services = QCheckBox("Load system services")
        self.load_services.setChecked(True)
        self.load_services.setEnabled(False)
        self.load_startup = QCheckBox("Load startup items")
        self.load_startup.setTristate(True)
        for w in (self.load_services, self.load_startup):
            row = QHBoxLayout()
            row.addSpacing(24)
            row.addWidget(w)
            row.addStretch(1)
            b.addLayout(row)
        v.addWidget(box)
        v.addStretch(1)
        self.normal.clicked.connect(lambda: self._pick(True))
        self.diag.clicked.connect(lambda: self._pick(False))
        self.load_startup.clicked.connect(lambda: self._pick(self.load_startup.checkState() != Qt.Unchecked))

    @staticmethod
    def _note(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("color: #555; margin-left: 24px;")
        return lab

    def _pick(self, on: bool):
        self.win.startup_tab.set_all(on)

    def sync(self, states: list[bool]):
        if all(states):
            self.normal.setChecked(True)
            self.load_startup.setCheckState(Qt.Checked)
        elif not any(states):
            self.diag.setChecked(True)
            self.load_startup.setCheckState(Qt.Unchecked)
        else:
            self.sel.setChecked(True)
            self.load_startup.setCheckState(Qt.PartiallyChecked)


class BootTab(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        self.list = QListWidget()
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        restore = QPushButton("Restore the previous version...")
        restore.clicked.connect(lambda: launch(["classic7-system", "--properties", "3"]))
        row.addWidget(restore)
        row.addStretch(1)
        v.addLayout(row)
        opts = QGroupBox("Boot options")
        ol = QVBoxLayout(opts)
        try:
            cmdline = Path("/proc/cmdline").read_text().strip()
        except OSError:
            cmdline = ""
        self.cmd = QLineEdit(cmdline)
        self.cmd.setReadOnly(True)
        ol.addWidget(QLabel("Kernel options of this start:"))
        ol.addWidget(self.cmd)
        for text in ("Safe boot", "No GUI boot", "Boot log", "Base video"):
            c = QCheckBox(text)
            c.setEnabled(False)
            ol.addWidget(c)
        note = QLabel("Classic 7 starts its versions through the boot menu; choose an earlier one there, or "
                      "restore the previous version to make it the default.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #555;")
        ol.addWidget(note)
        v.addWidget(opts)
        self.load()

    def load(self):
        self.list.clear()
        try:
            r = subprocess.run(["rpm-ostree", "status", "--json"], capture_output=True, text=True, timeout=20)
            deps = json.loads(r.stdout).get("deployments", [])
        except (OSError, subprocess.SubprocessError, ValueError):
            deps = []
        for d in deps:
            ver = d.get("version") or d.get("checksum", "")[:12]
            ts = d.get("timestamp")
            when = time.strftime(" (%d-%m-%Y)", time.localtime(ts)) if ts else ""
            tags = []
            if d.get("booted"):
                tags.append("Current OS")
            if d.get("staged"):
                tags.append("starts after the next restart")
            elif deps.index(d) == 0:
                tags.append("Default OS")
            self.list.addItem(f"Classic 7 {ver}{when}" + (" : " + "; ".join(tags) if tags else ""))
        if not deps:
            self.list.addItem("Classic 7 : Current OS; Default OS")


class StartupTab(QWidget):
    changed = Signal()

    def __init__(self, win: "MsConfig"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        self.tree = CheckTree(["Startup Item", "Manufacturer", "Command", "Location", "Date Disabled"],
                              [170, 130, 220, 150, 110])
        self.tree.itemChanged.connect(self._toggled)
        v.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.hide_core = QCheckBox("Hide the desktop's own startup items")
        self.hide_core.setChecked(True)
        self.hide_core.toggled.connect(lambda _on: self.fill(self.items))
        row.addWidget(self.hide_core)
        row.addStretch(1)
        en = QPushButton("Enable all")
        en.clicked.connect(lambda: self.set_all(True))
        dis = QPushButton("Disable all")
        dis.clicked.connect(lambda: self.set_all(False))
        row.addWidget(en)
        row.addWidget(dis)
        v.addLayout(row)
        self.items: list[StartupItem] = []
        self.pending: dict[str, bool] = {}

    def fill(self, items: list[StartupItem]):
        self.items = items
        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for it in items:
            if it.core and self.hide_core.isChecked():
                continue
            on = self.pending.get(it.file, it.enabled)
            row = QTreeWidgetItem([it.name, it.maker, it.command, it.location, fmt_date(it.disabled_at) if not on else ""])
            row.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
            row.setData(0, Qt.UserRole, it.file)
            row.setToolTip(2, it.command)
            self.tree.addTopLevelItem(row)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.blockSignals(False)
        self.win.general_tab.sync(self.states())

    def states(self) -> list[bool]:
        return [self.pending.get(it.file, it.enabled) for it in self.items if not it.core]

    def _toggled(self, row: QTreeWidgetItem, col: int):
        if col != 0:
            return
        f = row.data(0, Qt.UserRole)
        it = next((i for i in self.items if i.file == f), None)
        on = row.checkState(0) == Qt.Checked
        if it is not None:
            if on == it.enabled:
                self.pending.pop(f, None)
            else:
                self.pending[f] = on
        self.win.general_tab.sync(self.states())
        self.changed.emit()

    def set_all(self, on: bool):
        for it in self.items:
            if it.core:
                continue
            if on == it.enabled:
                self.pending.pop(it.file, None)
            else:
                self.pending[it.file] = on
        self.fill(self.items)
        self.changed.emit()

    def apply(self) -> list[str]:
        errors = []
        for it in self.items:
            if it.file in self.pending:
                e = set_startup(it, self.pending[it.file])
                if e:
                    errors.append(e)
        self.pending.clear()
        return errors


class ServicesTab(QWidget):
    changed = Signal()

    def __init__(self, win: "MsConfig"):
        super().__init__()
        self.win = win
        v = QVBoxLayout(self)
        self.tree = CheckTree(["Service", "Manufacturer", "Status", "Date Disabled"], [330, 160, 90, 110])
        self.tree.itemChanged.connect(self._toggled)
        v.addWidget(self.tree, 1)
        note = QLabel("Note that some secure system services may not be disabled.")
        note.setStyleSheet("color: #555;")
        v.addWidget(note)
        row = QHBoxLayout()
        self.hide_os = QCheckBox("Hide all Fedora and Universal Blue services")
        self.hide_os.toggled.connect(lambda _on: self.fill(self.items))
        row.addWidget(self.hide_os)
        row.addStretch(1)
        en = QPushButton("Enable all")
        en.clicked.connect(lambda: self.set_all(True))
        dis = QPushButton("Disable all")
        dis.clicked.connect(lambda: self.set_all(False))
        row.addWidget(en)
        row.addWidget(dis)
        v.addLayout(row)
        self.items: list[Service] = []
        self.pending: dict[str, bool] = {}

    @staticmethod
    def key(s: Service) -> str:
        return ("user:" if s.user else "") + s.unit

    def _visible(self, s: Service) -> bool:
        return not (self.hide_os.isChecked() and any(x in s.maker for x in ("Fedora", "Universal Blue", "ublue")))

    def fill(self, items: list[Service]):
        self.items = items
        self.tree.blockSignals(True)
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for s in items:
            if not self._visible(s):
                continue
            on = self.pending.get(self.key(s), s.enabled)
            name = s.description + ("  (yours)" if s.user else "")
            row = QTreeWidgetItem([name, s.maker, "Running" if s.running else "Stopped",
                                   fmt_date(s.disabled_at) if not on else ""])
            row.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
            row.setData(0, Qt.UserRole, self.key(s))
            row.setToolTip(0, s.unit)
            self.tree.addTopLevelItem(row)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.blockSignals(False)

    def _toggled(self, row: QTreeWidgetItem, col: int):
        if col != 0:
            return
        k = row.data(0, Qt.UserRole)
        s = next((x for x in self.items if self.key(x) == k), None)
        on = row.checkState(0) == Qt.Checked
        if s is not None:
            if on == s.enabled:
                self.pending.pop(k, None)
            else:
                self.pending[k] = on
        self.changed.emit()

    def set_all(self, on: bool):
        for s in self.items:
            if not self._visible(s):
                continue
            k = self.key(s)
            if on == s.enabled:
                self.pending.pop(k, None)
            else:
                self.pending[k] = on
        self.fill(self.items)
        self.changed.emit()

    def apply(self) -> tuple[list[str], bool]:
        """(errors, whether system services changed)."""
        if not self.pending:
            return [], False
        errors = []
        system_on = [k for k, on in self.pending.items() if on and not k.startswith("user:")]
        system_off = [k for k, on in self.pending.items() if not on and not k.startswith("user:")]
        if system_off:
            names = "\n".join(f"    {k}" for k in system_off[:15]) + ("\n    ..." if len(system_off) > 15 else "")
            if QMessageBox.warning(self, APP, "These system services will no longer start:\n\n" + names +
                                   "\n\nTurning off the wrong service can keep the computer from working properly. "
                                   "Continue?", QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return [], False
        changed_system = False
        if system_on or system_off:
            cmds = []
            if system_on:
                cmds.append("systemctl enable " + " ".join(shlex.quote(k) for k in system_on))
            if system_off:
                cmds.append("systemctl disable " + " ".join(shlex.quote(k) for k in system_off))
            r = subprocess.run(["pkexec", "/bin/sh", "-c", " && ".join(cmds)], capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(r.stderr.strip() or "The system services were not changed.")
            else:
                changed_system = True
        for k, on in self.pending.items():
            if k.startswith("user:"):
                r = subprocess.run(["systemctl", "--user", "enable" if on else "disable", k[5:]], capture_output=True,
                                   text=True)
                if r.returncode != 0:
                    errors.append(r.stderr.strip())
        state = load_state()
        dis = state.setdefault("services_disabled", {})
        for k, on in self.pending.items():
            if not k.startswith("user:") and not changed_system:
                continue
            if on:
                dis.pop(k, None)
            else:
                dis[k] = time.time()
        save_state(state)
        self.pending.clear()
        return errors, changed_system


TOOLS = [
    ("About Classic 7", "Display the version of Classic 7.", ["classic7-system"]),
    ("Action Center", "Review recent messages and resolve problems.", ["classic7-actioncenter"]),
    ("Computer Management", "Manage disks and drive letters.", ["classic7-diskmgmt"]),
    ("System Information", "View advanced information about hardware and software settings.", ["classic7-system"]),
    ("Event Viewer", "View monitoring and troubleshooting messages.", ["classic7-eventvwr"]),
    ("Programs", "Launch, add or remove programs.", ["classic7-programs"]),
    ("System Properties", "View basic information about your computer system settings.",
     ["classic7-system", "--properties"]),
    ("Internet Protocol Configuration", "View and configure network address settings.", ["classic7-network"]),
    ("Resource Monitor", "Monitor the use of processor, memory, disk and network.", ["classic7-resmon"]),
    ("Task Manager", "View details about programs and processes running on your computer.", ["classic7-taskmgr"]),
    ("Command Prompt", "Open a command prompt window.", ["classic7-prompt"]),
    ("Windows Firewall", "Turn the firewall on or off and choose what it lets through.", ["classic7-firewall"]),
    ("System Restore", "Restore your computer system to an earlier state.", ["classic7-system", "--properties", "3"]),
    ("Device Manager", "View the devices in the computer and their drivers.", ["classic7-devmgmt"]),
    ("Disk Management", "Format, check and name drives.", ["classic7-diskmgmt"]),
]


def launch(argv: list[str]) -> bool:
    if not shutil.which(argv[0]):
        return False
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return True


class ToolsTab(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Tool Name", "Description"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().resizeSection(0, 200)
        for name, desc, cmd in TOOLS:
            if not shutil.which(cmd[0]):
                continue
            it = QTreeWidgetItem([name, desc])
            it.setData(0, Qt.UserRole, cmd)
            self.tree.addTopLevelItem(it)
        self.tree.currentItemChanged.connect(self._sel)
        self.tree.itemDoubleClicked.connect(lambda *_: self._launch())
        v.addWidget(self.tree, 1)
        v.addWidget(QLabel("Selected command:"))
        self.cmd = QLineEdit()
        self.cmd.setReadOnly(True)
        v.addWidget(self.cmd)
        row = QHBoxLayout()
        row.addStretch(1)
        b = QPushButton("Launch")
        b.clicked.connect(self._launch)
        row.addWidget(b)
        v.addLayout(row)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _sel(self, it, _prev):
        self.cmd.setText(shlex.join(it.data(0, Qt.UserRole)) if it else "")

    def _launch(self):
        it = self.tree.currentItem()
        if it is not None:
            launch(it.data(0, Qt.UserRole))


class MsConfig(QDialog):
    def __init__(self, tab: str = ""):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon.fromTheme("preferences-system"))
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.general_tab = GeneralTab(self)
        self.boot_tab = BootTab()
        self.services_tab = ServicesTab(self)
        self.startup_tab = StartupTab(self)
        self.tools_tab = ToolsTab()
        for w, title in ((self.general_tab, "General"), (self.boot_tab, "Boot"), (self.services_tab, "Services"),
                         (self.startup_tab, "Startup"), (self.tools_tab, "Tools")):
            self.tabs.addTab(w, title)
        v.addWidget(self.tabs, 1)
        self.status = QLabel("Loading...")
        self.status.setStyleSheet("color: #555;")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        self.apply_btn = bb.button(QDialogButtonBox.Apply)
        self.apply_btn.setEnabled(False)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        self.apply_btn.clicked.connect(self._apply)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(bb)
        v.addLayout(row)
        for t in (self.startup_tab, self.services_tab):
            t.changed.connect(lambda: self.apply_btn.setEnabled(True))
        idx = {"general": 0, "boot": 1, "services": 2, "startup": 3, "tools": 4}.get(tab, 0)
        self.tabs.setCurrentIndex(idx)
        self.resize(820, 520)
        self.reload()

    def reload(self):
        self.loader = Loader()
        self.loader.done.connect(self._loaded)
        self.loader.start()

    def _loaded(self, items, svcs):
        self.startup_tab.fill(items)
        self.services_tab.fill(svcs)
        self.status.setText("")

    def _apply(self) -> bool:
        errors = self.startup_tab.apply()
        errs2, system_changed = self.services_tab.apply()
        errors += errs2
        self.apply_btn.setEnabled(False)
        if errors:
            QMessageBox.warning(self, APP, "\n".join(e for e in errors if e)[:2000])
        self.reload()
        self.system_changed = getattr(self, "system_changed", False) or system_changed
        return not errors

    def _ok(self):
        if self.apply_btn.isEnabled():
            self._apply()
        if getattr(self, "system_changed", False):
            box = QMessageBox(QMessageBox.Information, APP, "You may need to restart your computer to apply these "
                              "changes.\n\nBefore restarting, save any open files and close all programs.",
                              QMessageBox.NoButton, self)
            restart = box.addButton("Restart", QMessageBox.AcceptRole)
            box.addButton("Exit without restart", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is restart:
                import session_actions
                session_actions.restart()
        self.accept()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1].strip())
        return 0
    tab = argv[argv.index("--tab") + 1] if "--tab" in argv and argv.index("--tab") + 1 < len(argv) else ""
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-msconfig")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-msconfig")
    w = MsConfig(tab)
    w.show()
    w.finished.connect(app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
