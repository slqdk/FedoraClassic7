"""Firewall, as in Windows 7 (firewall.cpl), over firewalld.

    classic7-firewall               the firewall's status for home or work and public networks
    classic7-firewall --allowed     "Allow programs to communicate through the firewall"
    classic7-firewall --onoff       "Customize settings for each type of network"

Home or work (private) networks are firewalld's default zone (FedoraWorkstation on this system),
public networks the "public" zone; a network connection belongs to the default zone unless it is
given another one. The list of allowed programs is firewalld's services (and open ports) in each
zone. Changes are made by /usr/libexec/classic7-firewall-helper through pkexec, which asks for an
administrator's password, as Windows asks before "Change settings"."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
                               QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import control_items as ci
from cpl_page import PageWindow

APP = "Firewall"
HELPER = "/usr/libexec/classic7-firewall-helper"
PUBLIC = "public"
BLOCKED = Path("/etc/classic7/firewall-blocked")
# services people look for, shown even when not allowed anywhere
COMMON = ["ssh", "samba-client", "samba", "mdns", "kdeconnect", "steam-streaming", "ipp", "ipp-client", "http",
          "https", "dhcpv6-client", "rdp", "vnc-server", "syncthing", "minecraft", "plex", "jellyfin", "transmission-client",
          "spotify-sync", "upnp-client", "llmnr"]


def fwcmd(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["firewall-cmd", *args], capture_output=True, text=True, timeout=15)
        return r.returncode, r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return -1, ""


@dataclass
class Zone:
    name: str
    target: str = "default"
    services: list[str] = field(default_factory=list)
    ports: list[str] = field(default_factory=list)
    blocked_all: bool = False

    @property
    def off(self) -> bool:
        return self.target.upper() == "ACCEPT"


@dataclass
class Connection:
    name: str
    uuid: str
    kind: str
    zone: str


@dataclass
class State:
    installed: bool
    running: bool
    default: str
    private: Zone
    public: Zone
    connections: list[Connection]


def zone_info(name: str) -> Zone:
    """The zone's saved settings (or, if they can't be read, the ones in use): one firewall-cmd
    (each run takes a tenth of a second or more)."""
    z = Zone(name)
    for perm in (["--permanent"], []):
        code, out = fwcmd(*perm, f"--zone={name}", "--list-all")
        if code == 0:
            for line in out.splitlines():
                key, _, value = line.strip().partition(":")
                if key == "target":
                    z.target = value.strip() or "default"
                elif key == "services":
                    z.services = value.split()
                elif key == "ports":
                    z.ports = value.split()
            break
    z.blocked_all = (BLOCKED / f"{name}.json").exists()
    return z


def connections(default: str) -> list[Connection]:
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "NAME,UUID,TYPE", "connection", "show", "--active"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    conns = []
    for line in out.splitlines():
        parts = line.replace("\\:", "\x00").split(":")
        if len(parts) < 3:
            continue
        name, uuid, kind = (p.replace("\x00", ":") for p in parts[:3])
        if kind in ("loopback", "bridge", "tun") or name == "lo":
            continue
        try:
            zone = subprocess.run(["nmcli", "-g", "connection.zone", "connection", "show", uuid], capture_output=True,
                                  text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            zone = ""
        conns.append(Connection(name, uuid, kind, zone or default))
    return conns


def read_state() -> State:
    """firewalld's state, the two zones and the network connections, asked side by side."""
    fallback = "FedoraWorkstation"
    if shutil.which("firewall-cmd") is None:
        return State(False, False, fallback, Zone(fallback), Zone(PUBLIC), [])
    with ThreadPoolExecutor(4) as pool:
        state = pool.submit(fwcmd, "--state")
        default_zone = pool.submit(fwcmd, "--get-default-zone")
        running = state.result()[0] == 0
        default = (default_zone.result()[1] if running else "") or fallback
        if not running:
            return State(True, False, default, Zone(default), Zone(PUBLIC), [])
        private = pool.submit(zone_info, default)
        public = pool.submit(zone_info, PUBLIC)
        conns = pool.submit(connections, default)
        return State(True, True, default, private.result(), public.result(), conns.result())


def catalog() -> dict[str, tuple[str, str, list[str]]]:
    """{service: (short name, description, ports)} from firewalld's service files."""
    out = {}
    for d in (Path("/usr/lib/firewalld/services"), Path("/etc/firewalld/services")):
        for f in sorted(d.glob("*.xml")) if d.is_dir() else []:
            try:
                root = ET.parse(f).getroot()
            except (ET.ParseError, OSError):
                continue
            short = (root.findtext("short") or f.stem).strip()
            desc = " ".join((root.findtext("description") or "").split())
            ports = [f"{p.get('port')}/{p.get('protocol')}" for p in root.findall("port")]
            out[f.stem] = (short, desc, ports)
    return out


def run_helper(parent: QWidget, ops: list[dict], done):
    """Run the changes as root; done(ok, message) when they are made (or refused)."""
    if not ops:
        done(True, "")
        return
    proc = QProcess(parent)
    proc.setProgram("pkexec")
    proc.setArguments([HELPER, json.dumps(ops)])

    def finished(code, _status):
        err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
        if code in (126, 127):
            done(False, "The change was not allowed.")
        else:
            done(code == 0, err)
        proc.deleteLater()
    proc.finished.connect(finished)
    proc.start()


class Shield(QLabel):
    def __init__(self, ok: bool):
        super().__init__()
        self.setPixmap(QIcon.fromTheme("security-high" if ok else "security-low",
                                       QIcon.fromTheme("dialog-error")).pixmap(32, 32))


class LocationBox(QFrame):
    """One network location: the coloured band, Connected / Not connected, and the details."""

    def __init__(self, title: str, subtitle: str, zone: Zone, running: bool, conns: list[Connection],
                 expanded: bool):
        super().__init__()
        on = running and not zone.off
        self.color = QColor("#3a9a3a") if on else QColor("#c0392b")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 6, 10, 8)
        head = QHBoxLayout()
        head.addWidget(Shield(on))
        t = QLabel(f"<b>{title}</b>")
        f = t.font()
        f.setPointSizeF(f.pointSizeF() * 1.1)
        t.setFont(f)
        head.addWidget(t, 1)
        head.addWidget(QLabel("Connected" if conns else "Not Connected"))
        self.toggle = QPushButton("▴" if expanded else "▾")
        self.toggle.setFlat(True)
        self.toggle.setFixedWidth(28)
        head.addWidget(self.toggle)
        v.addLayout(head)
        self.details = QWidget()
        g = QGridLayout(self.details)
        g.setContentsMargins(40, 2, 0, 2)
        g.setHorizontalSpacing(18)
        sub = QLabel(subtitle)
        sub.setStyleSheet("color: #555;")
        g.addWidget(sub, 0, 0, 1, 2)
        rows = [("Firewall state:", "On" if on else "Off"),
                ("Incoming connections:",
                 ("Block all connections, including those in the list of allowed programs" if zone.blocked_all else
                  "Block all connections to programs that are not on the list of allowed programs") if on else
                 "Allow all connections"),
                ("Active networks:", "\n".join(c.name for c in conns) or "None"),
                ("Notification state:", "The firewall doesn't notify about blocked programs")]
        for r, (k, val) in enumerate(rows, start=1):
            lk = QLabel(k)
            lk.setAlignment(Qt.AlignTop)
            g.addWidget(lk, r, 0)
            lv = QLabel(val)
            lv.setWordWrap(True)
            g.addWidget(lv, r, 1)
        g.setColumnStretch(1, 1)
        v.addWidget(self.details)
        self.details.setVisible(expanded)
        self.toggle.clicked.connect(self._toggle)
        self.setStyleSheet("LocationBox { background: #fbfbfb; border: 1px solid #dcdcdc; }")

    def _toggle(self):
        self.details.setVisible(not self.details.isVisible())
        self.toggle.setText("▴" if self.details.isVisible() else "▾")

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.fillRect(0, 0, 6, self.height(), self.color)


class AddDialog(QDialog):
    """Allow another program: a firewalld service, or a port."""

    def __init__(self, parent, cat: dict):
        super().__init__(parent)
        self.setWindowTitle("Add a Program")
        self.result_op: tuple[str, str] | None = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Select the program you want to add:"))
        self.list = QTreeWidget()
        self.list.setHeaderLabels(["Programs", "Ports"])
        self.list.setRootIsDecorated(False)
        self.list.header().resizeSection(0, 260)
        for name, (short, desc, ports) in sorted(cat.items(), key=lambda kv: kv[1][0].lower()):
            it = QTreeWidgetItem([short, ", ".join(ports)])
            it.setToolTip(0, desc)
            it.setData(0, Qt.UserRole, name)
            self.list.addTopLevelItem(it)
        self.list.itemDoubleClicked.connect(lambda *_: self.accept())
        v.addWidget(self.list, 1)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Search")
        self.filter.textChanged.connect(self._filter)
        v.insertWidget(1, self.filter)
        port_row = QHBoxLayout()
        self.use_port = QCheckBox("Or open a port:")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(8080)
        self.proto = QComboBox()
        self.proto.addItems(["tcp", "udp"])
        port_row.addWidget(self.use_port)
        port_row.addWidget(self.port)
        port_row.addWidget(self.proto)
        port_row.addStretch(1)
        v.addLayout(port_row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Add")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(520, 460)

    def _filter(self, text: str):
        t = text.lower()
        for i in range(self.list.topLevelItemCount()):
            it = self.list.topLevelItem(i)
            it.setHidden(bool(t) and t not in it.text(0).lower() and t not in (it.data(0, Qt.UserRole) or ""))

    def accept(self):
        if self.use_port.isChecked():
            self.result_op = ("port", f"{self.port.value()}/{self.proto.currentText()}")
        else:
            it = self.list.currentItem()
            if it is None:
                return
            self.result_op = ("service", it.data(0, Qt.UserRole))
        super().accept()


class Firewall(PageWindow):
    def __init__(self, page: str = "home"):
        super().__init__(APP, ["System and Security", "Firewall"], "security-high")
        self.nav_link("Allow a program or feature through the firewall", lambda: self.show_page("allowed"))
        self.nav_link("Turn the firewall on or off", lambda: self.show_page("onoff"), "security-medium")
        self.nav_link("Restore defaults", lambda: self.show_page("defaults"), "security-medium")
        self.nav_link("Advanced settings", self.advanced, "security-medium")
        self.nav_link("Troubleshoot my network", lambda: ci.launch(["classic7-network"]))
        self.see_also_link("Action Center", lambda: ci.launch(["classic7-actioncenter"]))
        self.see_also_link("Network Connections", lambda: ci.launch(["classic7-network"]))
        self.state: State | None = None
        self.cat: dict | None = None
        self.show_page(page)
        # firewall-cmd answers slowly: the window comes first, the settings a moment later
        result = {}
        worker = threading.Thread(target=lambda: result.update(state=read_state()), daemon=True)
        worker.start()
        self.setCursor(Qt.BusyCursor)

        def arrived():
            if worker.is_alive():
                return
            poll.stop()
            self.unsetCursor()
            self.state = result.get("state") or read_state()
            self.show_page(self.page)
        poll = QTimer(self, interval=30, timeout=arrived)
        poll.start()

    def refresh(self):
        self.state = read_state()
        self.show_page(self.page)

    def advanced(self):
        if not ci.launch(["firewall-config"]):
            ci.launch(["kcmshell6", "kcm_firewall"])

    def apply(self, ops: list[dict], then: str = "home"):
        self.setCursor(Qt.WaitCursor)

        def done(ok: bool, msg: str):
            self.unsetCursor()
            if not ok:
                QMessageBox.warning(self, APP, "The firewall settings could not be changed." + (f"\n\n{msg}" if msg else ""))
            self.state = read_state()
            self.show_page(then)
        run_helper(self, ops, done)

    # ---- pages --------------------------------------------------------------------------------
    def show_page(self, page: str):
        self.page = page
        self.clear_body()
        if self.state is None:
            wait = QLabel("Checking the firewall settings...")
            wait.setStyleSheet("color: #5A5A5A;")
            self.body.addWidget(wait)
        else:
            getattr(self, f"_page_{page}")()
        self.body.addStretch(1)

    def _page_home(self):
        s = self.state
        self.body.addWidget(self.heading("Help protect your computer with the firewall"))
        intro = QLabel("The firewall can help prevent hackers or malicious software from gaining access to your "
                       "computer through the Internet or a network.")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        if not s.installed:
            self.body.addWidget(QLabel("The firewall (firewalld) is not installed on this computer."))
            return
        if not s.running:
            warn = QLabel("<b style='color:#a00'>The firewall is turned off.</b> Programs on the network can reach this "
                          "computer freely.")
            warn.setWordWrap(True)
            self.body.addWidget(warn)
            b = QPushButton("Use recommended settings")
            b.setIcon(QIcon.fromTheme("security-high"))
            b.clicked.connect(lambda: self.apply([{"op": "firewalld", "on": True}]))
            self.body.addWidget(b, 0, Qt.AlignLeft)
        priv = [c for c in s.connections if c.zone == s.private.name]
        pub = [c for c in s.connections if c.zone == s.public.name]
        self.body.addWidget(LocationBox("Home or work (private) networks",
                                        "Networks at home or work where you know and trust the people and devices on "
                                        "the network", s.private, s.running, priv, bool(priv) or not pub))
        self.body.addWidget(LocationBox("Public networks", "Networks in public places such as airports or coffee shops",
                                        s.public, s.running, pub, bool(pub)))
        if s.connections:
            row = QHBoxLayout()
            row.addWidget(QLabel("Network location of"))
            self.conn_box = QComboBox()
            for c in s.connections:
                self.conn_box.addItem(c.name, c.uuid)
            row.addWidget(self.conn_box)
            row.addWidget(QLabel("is"))
            self.loc_box = QComboBox()
            self.loc_box.addItems(["Home or work (private)", "Public"])
            row.addWidget(self.loc_box)
            change = QPushButton("Change")
            change.clicked.connect(self._change_location)
            row.addWidget(change)
            row.addStretch(1)
            self.conn_box.currentIndexChanged.connect(self._sync_location)
            self._sync_location()
            self.body.addSpacing(8)
            self.body.addLayout(row)

    def _sync_location(self):
        uuid = self.conn_box.currentData()
        c = next((c for c in self.state.connections if c.uuid == uuid), None)
        self.loc_box.setCurrentIndex(1 if c and c.zone == self.state.public.name else 0)

    def _change_location(self):
        zone = self.state.public.name if self.loc_box.currentIndex() == 1 else self.state.private.name
        self.apply([{"op": "connection_zone", "uuid": self.conn_box.currentData(), "zone": zone}])

    def _page_allowed(self):
        s = self.state
        self.body.addWidget(self.heading("Allow programs to communicate through the firewall"))
        self.body.addWidget(QLabel("To add, change, or remove allowed programs and ports, click Change settings."))
        row = QHBoxLayout()
        row.addStretch(1)
        self.change_btn = QPushButton("Change settings")
        self.change_btn.setIcon(QIcon.fromTheme("security-medium"))
        row.addWidget(self.change_btn)
        self.body.addLayout(row)
        self.body.addWidget(QLabel("Allowed programs and features:"))
        if self.cat is None:
            self.cat = catalog()
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels(["Name", "Home/Work (Private)", "Public"])
        self.tree.header().resizeSection(0, 330)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Interactive)
        names = sorted(set(s.private.services) | set(s.public.services) | {c for c in COMMON if c in self.cat},
                       key=lambda n: self.cat.get(n, (n,))[0].lower())
        self.start: dict[tuple[str, str], tuple[bool, bool]] = {}
        for n in names:
            short, desc, ports = self.cat.get(n, (n, "", []))
            self._row(("service", n), short, desc + (f"\nPorts: {', '.join(ports)}" if ports else ""),
                      n in s.private.services, n in s.public.services)
        for p in sorted(set(s.private.ports) | set(s.public.ports)):
            self._row(("port", p), f"Port {p.replace('/', ' ').upper()}", "An open port", p in s.private.ports,
                      p in s.public.ports)
        self.tree.setEnabled(False)
        self.tree.setMinimumHeight(320)
        self.body.addWidget(self.tree, 1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        details = QPushButton("Details...")
        details.clicked.connect(self._details)
        btns.addWidget(details)
        self.add_btn = QPushButton("Allow another program...")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self._add)
        btns.addWidget(self.add_btn)
        self.body.addLayout(btns)
        ok_row = QHBoxLayout()
        ok_row.addStretch(1)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)
        self.ok_btn.clicked.connect(self._save_allowed)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.show_page("home"))
        ok_row.addWidget(self.ok_btn)
        ok_row.addWidget(cancel)
        self.body.addLayout(ok_row)
        self.change_btn.clicked.connect(self._unlock)
        if not s.running:
            self.change_btn.setEnabled(False)
            self.body.addWidget(QLabel("Turn the firewall on to choose what it lets through."))

    def _row(self, key: tuple[str, str], name: str, tip: str, priv: bool, pub: bool):
        it = QTreeWidgetItem([name, "", ""])
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Checked if (priv or pub) else Qt.Unchecked)
        it.setCheckState(1, Qt.Checked if priv else Qt.Unchecked)
        it.setCheckState(2, Qt.Checked if pub else Qt.Unchecked)
        it.setToolTip(0, tip)
        it.setData(0, Qt.UserRole, key)
        self.tree.addTopLevelItem(it)
        self.start[key] = (priv, pub)

    def _unlock(self):
        self.tree.setEnabled(True)
        self.add_btn.setEnabled(True)
        self.ok_btn.setEnabled(True)
        self.change_btn.setEnabled(False)

    def _details(self):
        it = self.tree.currentItem()
        if it is None:
            return
        QMessageBox.information(self, "Edit a Program", f"{it.text(0)}\n\n{it.toolTip(0)}")

    def _add(self):
        dlg = AddDialog(self, self.cat or {})
        if dlg.exec() == QDialog.Accepted and dlg.result_op:
            kind, name = dlg.result_op
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.data(0, Qt.UserRole) == (kind, name):
                    it.setCheckState(1, Qt.Checked)
                    self.tree.setCurrentItem(it)
                    return
            short = (self.cat or {}).get(name, (name,))[0] if kind == "service" else \
                f"Port {name.replace('/', ' ').upper()}"
            self._row((kind, name), short, "", False, False)
            it = self.tree.topLevelItem(self.tree.topLevelItemCount() - 1)
            it.setCheckState(1, Qt.Checked)
            self.tree.setCurrentItem(it)

    def _save_allowed(self):
        ops = []
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            kind, name = it.data(0, Qt.UserRole)
            enabled = it.checkState(0) == Qt.Checked
            priv = enabled and it.checkState(1) == Qt.Checked
            pub = enabled and it.checkState(2) == Qt.Checked
            was_priv, was_pub = self.start.get((kind, name), (False, False))
            for zone, now, was in ((self.state.private.name, priv, was_priv), (self.state.public.name, pub, was_pub)):
                if now != was:
                    op = {"op": kind, "zone": zone, "on": now}
                    op["name" if kind == "service" else "port"] = name
                    ops.append(op)
        if ops:
            self.apply(ops, "allowed")
        else:
            self.show_page("home")

    def _page_onoff(self):
        s = self.state
        self.body.addWidget(self.heading("Customize settings for each type of network"))
        self.body.addWidget(QLabel("You can modify the firewall settings for each type of network location that you use."))
        self.choices = {}
        for title, zone in (("Home or work (private) network location settings", s.private),
                            ("Public network location settings", s.public)):
            box = QFrame()
            v = QVBoxLayout(box)
            v.addWidget(QLabel(f"<b>{title}</b>"))
            on = QRadioButton("Turn on the firewall")
            block = QCheckBox("Block all incoming connections, including those in the list of allowed programs")
            notify = QCheckBox("Notify me when the firewall blocks a new program")
            notify.setEnabled(False)
            off = QRadioButton("Turn off the firewall (not recommended)")
            is_on = s.running and not zone.off
            on.setChecked(is_on)
            off.setChecked(not is_on)
            block.setChecked(zone.blocked_all)
            block.setEnabled(is_on)
            on.toggled.connect(block.setEnabled)
            v.addWidget(on)
            for w in (block, notify):
                r = QHBoxLayout()
                r.addSpacing(26)
                r.addWidget(w)
                r.addStretch(1)
                v.addLayout(r)
            v.addWidget(off)
            self.body.addWidget(box)
            self.choices[zone.name] = (on, block, zone)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton("OK")
        ok.clicked.connect(self._save_onoff)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.show_page("home"))
        row.addWidget(ok)
        row.addWidget(cancel)
        self.body.addLayout(row)

    def _save_onoff(self):
        s = self.state
        ops: list[dict] = []
        any_on = any(on.isChecked() for on, _b, _z in self.choices.values())
        if any_on and not s.running:
            ops.append({"op": "firewalld", "on": True})
        for name, (on, block, zone) in self.choices.items():
            want_off = not on.isChecked()
            if want_off != zone.off or (not s.running and any_on):
                ops.append({"op": "target", "zone": name, "off": want_off})
            want_block = on.isChecked() and block.isChecked()
            if want_block != zone.blocked_all:
                ops.append({"op": "block_all", "zone": name, "on": want_block})
        if not ops:
            self.show_page("home")
            return
        self.apply(ops)

    def _page_defaults(self):
        self.body.addWidget(self.heading("Restore default settings"))
        text = QLabel("Restoring the defaults removes all the firewall settings that you have made for all network "
                      "locations, and lets through what the system lets through when it is new. This might cause some "
                      "programs to stop working.")
        text.setWordWrap(True)
        self.body.addWidget(text)
        b = QPushButton("Restore defaults")
        b.setIcon(QIcon.fromTheme("security-medium"))
        b.clicked.connect(self._restore)
        row = QHBoxLayout()
        row.addWidget(b)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(lambda: self.show_page("home"))
        row.addWidget(cancel)
        row.addStretch(1)
        self.body.addLayout(row)

    def _restore(self):
        if QMessageBox.question(self, "Restore Defaults Confirmation",
                                "Are you sure you want to restore the default firewall settings?") != QMessageBox.Yes:
            return
        ops = []
        if not self.state.running:
            ops.append({"op": "firewalld", "on": True})
        ops.append({"op": "defaults", "zones": [self.state.private.name, self.state.public.name]})
        self.apply(ops)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1].strip())
        return 0
    page = "allowed" if "--allowed" in argv else ("onoff" if "--onoff" in argv else "home")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-firewall")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-firewall")
    w = Firewall(page)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
