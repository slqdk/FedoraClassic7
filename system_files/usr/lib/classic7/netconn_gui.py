"""Network Connections (ncpa.cpl): adapters, Status, Details, Properties and the
Internet Protocol Version 4 (TCP/IPv4) Properties dialog, like Windows 7."""
from __future__ import annotations

import sys
import time

from PySide6.QtCore import QObject, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QIntValidator, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox,
                               QFrame, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QRadioButton, QSizePolicy, QStyledItemDelegate, QTabWidget,
                               QTableWidget, QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

import netconf as nc

APP = "Network Connections"


def theme_icon(names, fallback="network-wired"):
    for n in ([names] if isinstance(names, str) else names) + [fallback]:
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return QIcon()


def _drawn_adapter(size: int, wifi: bool) -> QPixmap:
    """Fallback picture when the icon theme has no network icon: a small monitor with a cable
    (or radio waves for Wi-Fi)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 48
    p.setPen(QPen(QColor("#404040"), max(1, s)))
    p.setBrush(QColor("#D4D0C8"))
    p.drawRect(int(6 * s), int(6 * s), int(32 * s), int(24 * s))
    p.setBrush(QColor("#3A6EA5"))
    p.drawRect(int(9 * s), int(9 * s), int(26 * s), int(18 * s))
    p.setBrush(QColor("#A0A0A0"))
    p.drawRect(int(16 * s), int(30 * s), int(12 * s), int(4 * s))
    p.drawRect(int(10 * s), int(34 * s), int(24 * s), int(4 * s))
    if wifi:
        p.setBrush(Qt.NoBrush)
        for r in (6, 11, 16):
            p.drawArc(int((40 - r) * s), int((14 - r) * s), int(2 * r * s), int(2 * r * s), 30 * 16, 30 * 16)
    else:
        p.setPen(QPen(QColor("#2060C0"), max(2, 2 * s)))
        p.drawLine(int(38 * s), int(36 * s), int(46 * s), int(36 * s))
        p.drawLine(int(46 * s), int(36 * s), int(46 * s), int(46 * s))
    p.end()
    return pm


def adapter_icon(a: nc.Adapter, size: int = 48) -> QPixmap:
    base = theme_icon(["network-wireless", "network-wireless-connected-100"] if a.type == "wifi"
                      else ["network-wired", "network-card", "network-wired-activated"])
    pm = base.pixmap(size, size)
    if pm.isNull():
        pm = _drawn_adapter(size, a.type == "wifi")
    if not a.connected:
        # Windows draws a red X (cable unplugged) or greys the icon out (disabled)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r = size // 3
        rect = QRect(size - r - 1, size - r - 1, r, r)
        p.setBrush(QColor("#D02020"))
        p.setPen(QPen(QColor("#FFFFFF"), 1))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor("#FFFFFF"), max(2, size // 20)))
        m = r // 3
        p.drawLine(rect.left() + m, rect.top() + m, rect.right() - m, rect.bottom() - m)
        p.drawLine(rect.right() - m, rect.top() + m, rect.left() + m, rect.bottom() - m)
        p.end()
    return pm


def error(parent, text: str, title: str = APP):
    QMessageBox.warning(parent, title, text)


# =============================================================================
# The IP address box: four fields with dots, like Windows
# =============================================================================
class _Octet(QLineEdit):
    def __init__(self, box):
        super().__init__()
        self.box = box
        self.setMaxLength(3)
        self.setValidator(QIntValidator(0, 255, self))
        self.setAlignment(Qt.AlignCenter)
        self.setFrame(False)
        self.setFixedWidth(30)
        self.textEdited.connect(self._edited)

    def _edited(self, text):
        if text and int(text) > 255:
            # like Windows: out-of-range numbers become the highest allowed value
            self.setText("255")
            text = "255"
        if len(text) == 3 or (text and int(text) > 25):
            self.box.next_field(self)
        self.box.changed.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Period, Qt.Key_Comma, Qt.Key_Space):
            if self.text():
                self.box.next_field(self)
            return
        if e.key() == Qt.Key_Backspace and not self.text():
            self.box.prev_field(self, erase=True)
            return
        if e.key() == Qt.Key_Left and self.cursorPosition() == 0:
            self.box.prev_field(self)
            return
        if e.key() == Qt.Key_Right and self.cursorPosition() == len(self.text()):
            self.box.next_field(self)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.box.focused.emit()
        QTimer.singleShot(0, self.selectAll)


class IPEdit(QFrame):
    changed = Signal()
    focused = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Sunken)
        self.setAutoFillBackground(True)
        self.setBackgroundRole(self.palette().ColorRole.Base)
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 1, 2, 1)
        h.setSpacing(0)
        self.fields = []
        for i in range(4):
            f = _Octet(self)
            self.fields.append(f)
            h.addWidget(f)
            if i < 3:
                dot = QLabel(".")
                dot.setAlignment(Qt.AlignCenter)
                dot.setFixedWidth(6)
                h.addWidget(dot)
        self.setFixedWidth(4 * 30 + 3 * 6 + 8)

    def next_field(self, f):
        i = self.fields.index(f)
        if i < 3:
            self.fields[i + 1].setFocus()

    def prev_field(self, f, erase=False):
        i = self.fields.index(f)
        if i > 0:
            prev = self.fields[i - 1]
            prev.setFocus()
            if erase:
                prev.setText(prev.text()[:-1])
            prev.setCursorPosition(len(prev.text()))

    def text(self) -> str:
        parts = [f.text() for f in self.fields]
        return "" if not any(parts) else ".".join(p or "0" for p in parts)

    def setText(self, ip: str):
        parts = (ip or "").split(".")
        for i, f in enumerate(self.fields):
            f.setText(parts[i] if i < len(parts) and ip else "")

    def is_empty(self) -> bool:
        return not any(f.text() for f in self.fields)

    def setEnabled(self, on: bool):
        super().setEnabled(on)
        self.setBackgroundRole(self.palette().ColorRole.Base if on else self.palette().ColorRole.Window)


# =============================================================================
# Advanced TCP/IP Settings: several addresses on one adapter
# =============================================================================
class AddressDialog(QDialog):
    def __init__(self, parent, ip="", mask=""):
        super().__init__(parent)
        self.setWindowTitle("TCP/IP Address")
        g = QGridLayout(self)
        g.addWidget(QLabel("&IP address:"), 0, 0)
        self.ip = IPEdit()
        self.ip.setText(ip)
        g.addWidget(self.ip, 0, 1)
        g.addWidget(QLabel("S&ubnet mask:"), 1, 0)
        self.mask = IPEdit()
        self.mask.setText(mask)
        self.mask.focused.connect(lambda: self.mask.is_empty() and nc.valid_ip(self.ip.text())
                                  and self.mask.setText(nc.classful_mask(self.ip.text())))
        g.addWidget(self.mask, 1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        g.addWidget(bb, 2, 0, 1, 2)

    def _ok(self):
        if not nc.valid_ip(self.ip.text()):
            return error(self, "The IP address is not valid.", "TCP/IP Address")
        try:
            nc.mask_to_prefix(self.mask.text())
        except ValueError:
            return error(self, "The subnet mask is not valid.", "TCP/IP Address")
        self.accept()


class AdvancedDialog(QDialog):
    def __init__(self, parent, addresses: list[tuple[str, int]], gateway: str):
        super().__init__(parent)
        self.setWindowTitle("Advanced TCP/IP Settings")
        self.resize(420, 380)
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)
        page = QWidget()
        tabs.addTab(page, "IP Settings")
        pv = QVBoxLayout(page)
        g1 = QGroupBox("IP addresses")
        gl = QVBoxLayout(g1)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["IP address", "Subnet mask"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for ip, pre in addresses:
            self._add_row(ip, nc.prefix_to_mask(pre))
        gl.addWidget(self.table)
        row = QHBoxLayout()
        row.addStretch(1)
        for text, slot in (("A&dd...", self.add), ("&Edit...", self.edit), ("Remo&ve", self.remove)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        gl.addLayout(row)
        pv.addWidget(g1)
        g2 = QGroupBox("Default gateway")
        g2l = QHBoxLayout(g2)
        g2l.addWidget(QLabel("Gateway:"))
        self.gateway = IPEdit()
        self.gateway.setText(gateway)
        g2l.addWidget(self.gateway)
        g2l.addStretch(1)
        pv.addWidget(g2)
        note = QLabel("Extra addresses are useful to reach several machine networks over one cable.")
        note.setWordWrap(True)
        pv.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _add_row(self, ip, mask):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(ip))
        self.table.setItem(r, 1, QTableWidgetItem(mask))

    def add(self):
        d = AddressDialog(self)
        if d.exec() == QDialog.Accepted:
            self._add_row(d.ip.text(), d.mask.text())

    def edit(self):
        r = self.table.currentRow()
        if r < 0:
            return
        d = AddressDialog(self, self.table.item(r, 0).text(), self.table.item(r, 1).text())
        if d.exec() == QDialog.Accepted:
            self.table.item(r, 0).setText(d.ip.text())
            self.table.item(r, 1).setText(d.mask.text())

    def remove(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def addresses(self) -> list[tuple[str, int]]:
        return [(self.table.item(r, 0).text(), nc.mask_to_prefix(self.table.item(r, 1).text()))
                for r in range(self.table.rowCount())]

    def _ok(self):
        if not self.table.rowCount():
            return error(self, "Add at least one IP address, or use automatic (DHCP) settings.",
                         "Advanced TCP/IP Settings")
        gw = self.gateway.text()
        if gw and not nc.valid_ip(gw):
            return error(self, "The default gateway is not valid.", "Advanced TCP/IP Settings")
        self.accept()


# =============================================================================
# Internet Protocol Version 4 (TCP/IPv4) Properties
# =============================================================================
class IPv4Dialog(QDialog):
    def __init__(self, parent, settings: nc.IPv4Settings):
        super().__init__(parent)
        self.setWindowTitle("Internet Protocol Version 4 (TCP/IPv4) Properties")
        self.settings = settings
        self.extra: list[tuple[str, int]] = list(settings.addresses[1:])
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)
        page = QWidget()
        tabs.addTab(page, "General")
        pv = QVBoxLayout(page)
        intro = QLabel("You can get IP settings assigned automatically if your network supports this "
                       "capability. Otherwise, you need to ask your network administrator for the "
                       "appropriate IP settings.")
        intro.setWordWrap(True)
        pv.addWidget(intro)

        self.ip_auto = QRadioButton("&Obtain an IP address automatically")
        self.ip_manual = QRadioButton("U&se the following IP address:")
        pv.addWidget(self.ip_auto)
        box = QGroupBox()
        box.setFlat(False)
        g = QGridLayout(box)
        g.addWidget(self.ip_manual, 0, 0, 1, 2)
        self.ip = IPEdit()
        self.mask = IPEdit()
        self.gw = IPEdit()
        for r, (label, w) in enumerate((("&IP address:", self.ip), ("S&ubnet mask:", self.mask),
                                        ("&Default gateway:", self.gw)), start=1):
            lab = QLabel(label)
            lab.setBuddy(w.fields[0])
            g.addWidget(lab, r, 0)
            g.addWidget(w, r, 1, Qt.AlignRight)
        self.ip_labels = [g.itemAtPosition(r, 0).widget() for r in (1, 2, 3)]
        self.mask.focused.connect(self._auto_mask)
        pv.addWidget(box)

        self.dns_auto = QRadioButton("O&btain DNS server address automatically")
        self.dns_manual = QRadioButton("Us&e the following DNS server addresses:")
        pv.addWidget(self.dns_auto)
        box2 = QGroupBox()
        g2 = QGridLayout(box2)
        g2.addWidget(self.dns_manual, 0, 0, 1, 2)
        self.dns1 = IPEdit()
        self.dns2 = IPEdit()
        for r, (label, w) in enumerate((("&Preferred DNS server:", self.dns1),
                                        ("&Alternate DNS server:", self.dns2)), start=1):
            lab = QLabel(label)
            lab.setBuddy(w.fields[0])
            g2.addWidget(lab, r, 0)
            g2.addWidget(w, r, 1, Qt.AlignRight)
        self.dns_labels = [g2.itemAtPosition(r, 0).widget() for r in (1, 2)]
        pv.addWidget(box2)

        adv_row = QHBoxLayout()
        self.extra_label = QLabel()
        adv_row.addWidget(self.extra_label, 1)
        self.adv = QPushButton("Ad&vanced...")
        self.adv.clicked.connect(self.advanced)
        adv_row.addWidget(self.adv)
        pv.addLayout(adv_row)
        pv.addStretch(1)

        ipg = QButtonGroup(self)
        ipg.addButton(self.ip_auto)
        ipg.addButton(self.ip_manual)
        dnsg = QButtonGroup(self)
        dnsg.addButton(self.dns_auto)
        dnsg.addButton(self.dns_manual)
        for b in (self.ip_auto, self.ip_manual, self.dns_auto, self.dns_manual):
            b.toggled.connect(self._update)

        # fill
        if settings.method == "manual":
            self.ip_manual.setChecked(True)
            if settings.addresses:
                ip, pre = settings.addresses[0]
                self.ip.setText(ip)
                self.mask.setText(nc.prefix_to_mask(pre))
            self.gw.setText(settings.gateway)
        else:
            self.ip_auto.setChecked(True)
        if settings.manual_dns and settings.dns:
            self.dns_manual.setChecked(True)
        else:
            self.dns_auto.setChecked(True)
        self.dns1.setText(settings.dns[0] if settings.dns else "")
        self.dns2.setText(settings.dns[1] if len(settings.dns) > 1 else "")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._update()

    def _auto_mask(self):
        if self.mask.is_empty() and nc.valid_ip(self.ip.text()):
            self.mask.setText(nc.classful_mask(self.ip.text()))

    def _update(self):
        manual = self.ip_manual.isChecked()
        for w in [self.ip, self.mask, self.gw] + self.ip_labels:
            w.setEnabled(manual)
        if manual and not self.dns_manual.isChecked():
            self.dns_manual.setChecked(True)      # static IP needs static DNS, as on Windows
        self.dns_auto.setEnabled(not manual)
        dns = self.dns_manual.isChecked()
        for w in [self.dns1, self.dns2] + self.dns_labels:
            w.setEnabled(dns)
        self.adv.setEnabled(manual)
        self.extra_label.setText(f"+ {len(self.extra)} more address{'es' if len(self.extra) != 1 else ''}"
                                 if manual and self.extra else "")

    def advanced(self):
        first = []
        if nc.valid_ip(self.ip.text()):
            try:
                first = [(self.ip.text(), nc.mask_to_prefix(self.mask.text() or nc.classful_mask(self.ip.text())))]
            except ValueError:
                first = []
        d = AdvancedDialog(self, first + self.extra, self.gw.text())
        if d.exec() == QDialog.Accepted:
            addrs = d.addresses()
            ip, pre = addrs[0]
            self.ip.setText(ip)
            self.mask.setText(nc.prefix_to_mask(pre))
            self.extra = addrs[1:]
            self.gw.setText(d.gateway.text())
            self._update()

    def result_settings(self) -> nc.IPv4Settings:
        s = nc.IPv4Settings(ipv6_method=self.settings.ipv6_method)
        if self.ip_manual.isChecked():
            s.method = "manual"
            s.addresses = [(self.ip.text(), nc.mask_to_prefix(self.mask.text()))] + self.extra
            s.gateway = self.gw.text()
        else:
            s.method = "auto"
        if self.dns_manual.isChecked():
            s.dns = [d for d in (self.dns1.text(), self.dns2.text()) if d]
            s.ignore_auto_dns = True
        return s

    def _ok(self):
        title = self.windowTitle()
        if self.ip_manual.isChecked():
            if not nc.valid_ip(self.ip.text()):
                self.ip.fields[0].setFocus()
                return error(self, "The IP address is not valid. Enter four numbers from 0 to 255.", title)
            try:
                prefix = nc.mask_to_prefix(self.mask.text())
                if prefix == 0:
                    raise ValueError
            except ValueError:
                self.mask.fields[0].setFocus()
                return error(self, "The subnet mask is not valid.", title)
            gw = self.gw.text()
            if gw:
                if not nc.valid_ip(gw):
                    return error(self, "The default gateway is not valid.", title)
                if not nc.same_subnet(self.ip.text(), prefix, gw):
                    if QMessageBox.question(self, title, "The default gateway is not on the same network "
                                            "segment (subnet) that is defined by the IP address and subnet "
                                            "mask. Do you want to save this configuration?") != QMessageBox.Yes:
                        return
        if self.dns_manual.isChecked():
            for d in (self.dns1.text(), self.dns2.text()):
                if d and not nc.valid_ip(d):
                    return error(self, f"The DNS server address {d} is not valid.", title)
        self.accept()


# =============================================================================
# Local Area Connection Properties
# =============================================================================
class PropertiesDialog(QDialog):
    def __init__(self, parent, adapter: nc.Adapter, uuid: str):
        super().__init__(parent)
        self.adapter, self.uuid = adapter, uuid
        self.setWindowTitle(f"{adapter.title} Properties")
        self.settings = nc.read_ipv4(uuid)
        self.new_ipv4: nc.IPv4Settings | None = None
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)
        page = QWidget()
        tabs.addTab(page, "Networking")
        pv = QVBoxLayout(page)
        pv.addWidget(QLabel("Connect using:"))
        dev = QFrame()
        dev.setFrameShape(QFrame.StyledPanel)
        dev.setFrameShadow(QFrame.Sunken)
        dh = QHBoxLayout(dev)
        ic = QLabel()
        ic.setPixmap(adapter_icon(adapter, 16))
        dh.addWidget(ic)
        dh.addWidget(QLabel(f"{adapter.description}  ({adapter.device})"), 1)
        pv.addWidget(dev)
        pv.addWidget(QLabel("This connection uses the following items:"))
        self.items = QTreeWidget()
        self.items.setHeaderHidden(True)
        self.items.setRootIsDecorated(False)
        self.v6 = QTreeWidgetItem(["Internet Protocol Version 6 (TCP/IPv6)"])
        self.v6.setCheckState(0, Qt.Unchecked if self.settings.ipv6_method in ("disabled", "ignore") else Qt.Checked)
        self.v4 = QTreeWidgetItem(["Internet Protocol Version 4 (TCP/IPv4)"])
        self.v4.setCheckState(0, Qt.Checked)
        self.v4.setFlags(self.v4.flags() & ~Qt.ItemIsUserCheckable)
        for it in (self.v6, self.v4):
            it.setIcon(0, theme_icon(["network-connect", "preferences-system-network"]))
            self.items.addTopLevelItem(it)
        self.items.setCurrentItem(self.v4)
        self.items.itemDoubleClicked.connect(lambda it, _c: it is self.v4 and self.ipv4())
        self.items.currentItemChanged.connect(self._describe)
        pv.addWidget(self.items)
        row = QHBoxLayout()
        for text in ("I&nstall...", "&Uninstall"):
            b = QPushButton(text)
            b.setEnabled(False)
            row.addWidget(b)
        row.addStretch(1)
        self.props = QPushButton("P&roperties")
        self.props.clicked.connect(self.ipv4)
        row.addWidget(self.props)
        pv.addLayout(row)
        desc = QGroupBox("Description")
        dl = QVBoxLayout(desc)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        dl.addWidget(self.desc)
        pv.addWidget(desc)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._describe(self.v4)
        self.resize(400, 460)

    def _describe(self, it, *_):
        if it is self.v6:
            self.desc.setText("TCP/IPv6. The latest version of the internet protocol that provides "
                              "communication across diverse interconnected networks.")
            self.props.setEnabled(False)
        else:
            self.desc.setText("Transmission Control Protocol/Internet Protocol. The default wide area network "
                              "protocol that provides communication across diverse interconnected networks.")
            self.props.setEnabled(True)

    def ipv4(self):
        d = IPv4Dialog(self, self.new_ipv4 or self.settings)
        if d.exec() == QDialog.Accepted:
            self.new_ipv4 = d.result_settings()

    def _ok(self):
        v6_on = self.v6.checkState(0) == Qt.Checked
        v6_was = self.settings.ipv6_method not in ("disabled", "ignore")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if v6_on != v6_was:
                nc.set_ipv6_enabled(self.uuid, v6_on)
            if self.new_ipv4 is not None or v6_on != v6_was:
                nc.write_ipv4(self.uuid, self.new_ipv4 or self.settings, self.adapter.device)
        except nc.NetError as e:
            QApplication.restoreOverrideCursor()
            return error(self, f"The settings could not be saved:\n\n{e}", self.windowTitle())
        QApplication.restoreOverrideCursor()
        self.accept()


# =============================================================================
# Status and Details
# =============================================================================
class DetailsDialog(QDialog):
    def __init__(self, parent, a: nc.Adapter, dhcp_enabled: bool | None):
        super().__init__(parent)
        self.setWindowTitle("Network Connection Details")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Network Connection &Details:"))
        t = QTableWidget(0, 2)
        t.setHorizontalHeaderLabels(["Property", "Value"])
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.verticalHeader().hide()
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        rows = [
            ("Connection-specific DNS Suffix", a.domain),
            ("Description", a.description),
            ("Physical Address", a.mac.replace(":", "-")),
            ("DHCP Enabled", "" if dhcp_enabled is None else ("Yes" if dhcp_enabled else "No")),
        ]
        for i, (ip, pre) in enumerate(a.ipv4):
            rows.append(("IPv4 Address" if i == 0 else "", ip))
            rows.append(("IPv4 Subnet Mask" if i == 0 else "", nc.prefix_to_mask(pre)))
        if a.dhcp:
            lease = a.dhcp.get("dhcp_lease_time")
            expiry = a.dhcp.get("expiry")
            if expiry and expiry.isdigit():
                rows.append(("Lease Expires", time.strftime("%d-%m-%Y %H:%M:%S", time.localtime(int(expiry)))))
            elif lease:
                rows.append(("Lease Time", f"{lease} s"))
        rows.append(("IPv4 Default Gateway", a.gateway))
        if a.dhcp.get("dhcp_server_identifier"):
            rows.append(("IPv4 DHCP Server", a.dhcp["dhcp_server_identifier"]))
        for i, d in enumerate(a.dns):
            rows.append(("IPv4 DNS Servers" if i == 0 else "", d))
        for i, ip6 in enumerate(a.ipv6):
            rows.append(("IPv6 Address" if i == 0 else "", ip6))
        for k, val in rows:
            r = t.rowCount()
            t.insertRow(r)
            t.setItem(r, 0, QTableWidgetItem(k))
            t.setItem(r, 1, QTableWidgetItem(val))
        t.resizeRowsToContents()
        v.addWidget(t)
        self.rows = rows
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("&Copy", QDialogButtonBox.ActionRole)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(
            "\n".join(f"{k}: {val}" if k else f"    {val}" for k, val in rows)))
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(440, 420)


class StatusDialog(QDialog):
    def __init__(self, win, a: nc.Adapter):
        super().__init__(win)
        self.win, self.a = win, a
        self.setWindowTitle(f"{a.title} Status")
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        v.addWidget(tabs)
        page = QWidget()
        tabs.addTab(page, "General")
        pv = QVBoxLayout(page)
        conn = QGroupBox("Connection")
        g = QGridLayout(conn)
        self.vals = {}
        for r, key in enumerate(("IPv4 Connectivity:", "IPv4 Address:", "Media State:", "Speed:")):
            g.addWidget(QLabel(key), r, 0)
            lab = QLabel()
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            g.addWidget(lab, r, 1)
            self.vals[key] = lab
        det = QPushButton("D&etails...")
        det.clicked.connect(self.details)
        g.addWidget(det, 4, 0, Qt.AlignLeft)
        pv.addWidget(conn)
        act = QGroupBox("Activity")
        ag = QGridLayout(act)
        ag.addWidget(QLabel("Sent —"), 0, 0, Qt.AlignRight)
        icon = QLabel()
        icon.setPixmap(theme_icon(["network-transmit-receive", "network-wired"]).pixmap(32, 32))
        ag.addWidget(icon, 0, 1, 2, 1, Qt.AlignCenter)
        ag.addWidget(QLabel("— Received"), 0, 2, Qt.AlignLeft)
        ag.addWidget(QLabel("Bytes:"), 2, 0, Qt.AlignLeft)
        self.sent = QLabel()
        self.recv = QLabel()
        ag.addWidget(self.sent, 2, 0, Qt.AlignRight)
        ag.addWidget(self.recv, 2, 2, Qt.AlignRight)
        pv.addWidget(act)
        row = QHBoxLayout()
        props = QPushButton("&Properties")
        props.clicked.connect(lambda: self.win.properties(self.a, self))
        row.addWidget(props)
        self.toggle = QPushButton()
        self.toggle.clicked.connect(self._toggle)
        row.addWidget(self.toggle)
        row.addStretch(1)
        pv.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.started = time.time()
        self.conn_text = "…"
        QTimer.singleShot(0, self._connectivity)
        self.timer = QTimer(self, interval=1000, timeout=self.refresh)
        self.timer.start()
        self.refresh()
        self.resize(360, 400)

    def _connectivity(self):
        c = nc.connectivity()
        self.conn_text = {"full": "Internet", "limited": "No Internet access", "portal": "Sign-in required",
                          "none": "No network access"}.get(c, "Unknown")
        self.refresh()

    def refresh(self):
        a = self.a
        try:
            fresh = next((x for x in nc.adapters() if x.device == a.device), a)
            self.a = a = fresh
        except nc.NetError:
            pass
        self.vals["IPv4 Connectivity:"].setText(self.conn_text if a.connected else "No network access")
        self.vals["IPv4 Address:"].setText(", ".join(ip for ip, _ in a.ipv4) or "—")
        self.vals["Media State:"].setText("Enabled" if a.connected else a.status_text)
        self.vals["Speed:"].setText(nc.human_speed(a.speed_mbit))
        st = nc.statistics(a.device)
        self.sent.setText(f"{st['tx_bytes']:,}".replace(",", "."))
        self.recv.setText(f"{st['rx_bytes']:,}".replace(",", "."))
        self.toggle.setText("&Disable" if a.connected else "&Enable")

    def details(self):
        dhcp = None
        if self.a.uuid:
            try:
                dhcp = nc.read_ipv4(self.a.uuid).dhcp
            except nc.NetError:
                pass
        DetailsDialog(self, self.a, dhcp).exec()

    def _toggle(self):
        self.win.toggle(self.a)
        self.refresh()


# =============================================================================
# The window
# =============================================================================
class TileDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(300, 64)

    def paint(self, p, option, index):
        a: nc.Adapter = index.data(Qt.UserRole)
        r = option.rect.adjusted(2, 2, -2, -2)
        selected = option.state & option.state.State_Selected if hasattr(option.state, "State_Selected") else False
        from PySide6.QtWidgets import QStyle
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            p.fillRect(r, option.palette.highlight())
        p.drawPixmap(r.left() + 4, r.top() + 6, adapter_icon(a, 48))
        x = r.left() + 60
        fg = option.palette.highlightedText().color() if selected else option.palette.text().color()
        dim = fg if selected else option.palette.color(option.palette.ColorGroup.Disabled, option.palette.ColorRole.Text)
        f = QFont(option.font)
        p.setFont(f)
        p.setPen(fg)
        lh = option.fontMetrics.height()
        p.drawText(QRect(x, r.top() + 6, r.right() - x, lh), Qt.AlignLeft | Qt.AlignVCenter,
                   option.fontMetrics.elidedText(a.title, Qt.ElideRight, r.right() - x))
        p.setPen(dim)
        p.drawText(QRect(x, r.top() + 6 + lh, r.right() - x, lh), Qt.AlignLeft | Qt.AlignVCenter,
                   option.fontMetrics.elidedText(a.status_text, Qt.ElideRight, r.right() - x))
        p.drawText(QRect(x, r.top() + 6 + 2 * lh, r.right() - x, lh), Qt.AlignLeft | Qt.AlignVCenter,
                   option.fontMetrics.elidedText(a.description, Qt.ElideRight, r.right() - x))


class NetworkWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(theme_icon(["preferences-system-network", "network-wired"]))
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        # Explorer-style command bar
        bar = QFrame()
        bar.setObjectName("commandBar")
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(6, 3, 6, 3)
        self.cmd = {}
        for key, text in (("toggle", "Disable this network device"), ("status", "View status of this connection"),
                          ("rename", "Rename this connection"), ("props", "Change settings of this connection")):
            b = QToolButton()
            b.setText(text)
            b.setAutoRaise(True)
            b.clicked.connect(lambda _=False, k=key: self.command(k))
            bh.addWidget(b)
            self.cmd[key] = b
        bh.addStretch(1)
        refresh = QToolButton()
        refresh.setText("Refresh")
        refresh.setAutoRaise(True)
        refresh.clicked.connect(self.reload)
        bh.addWidget(refresh)
        v.addWidget(bar)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        v.addWidget(line)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setGridSize(QSize(310, 70))
        self.list.setItemDelegate(TileDelegate(self.list))
        self.list.setUniformItemSizes(True)
        self.list.itemDoubleClicked.connect(lambda it: self.status(it.data(Qt.UserRole)))
        self.list.currentItemChanged.connect(self._selection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context_menu)
        v.addWidget(self.list, 1)
        self.info = QLabel()
        self.statusBar().addWidget(self.info)
        QShortcut = __import__("PySide6.QtGui", fromlist=["QShortcut"]).QShortcut
        QShortcut(QKeySequence("F5"), self, activated=self.reload)
        QShortcut(QKeySequence(Qt.Key_Return), self.list, activated=lambda: self.current() and self.status(self.current()))
        self.resize(720, 420)
        self.adapters: list[nc.Adapter] = []
        QTimer.singleShot(0, self.reload)
        self.timer = QTimer(self, interval=5000, timeout=self.reload)
        self.timer.start()

    def current(self) -> nc.Adapter | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def reload(self):
        try:
            adapters = nc.adapters()
        except nc.NetError as e:
            self.info.setText(str(e))
            return
        sel = self.current().device if self.current() else None
        self.list.clear()
        self.adapters = adapters
        for a in adapters:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, a)
            it.setToolTip(f"{a.title}\n{a.status_text}\n{a.description} ({a.device})")
            self.list.addItem(it)
            if a.device == sel:
                self.list.setCurrentItem(it)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.info.setText(f"{len(adapters)} item{'s' if len(adapters) != 1 else ''}")
        self._selection()

    def _selection(self, *_):
        a = self.current()
        for b in self.cmd.values():
            b.setEnabled(a is not None)
        if a:
            self.cmd["toggle"].setText("Disable this network device" if a.connected else "Enable this network device")

    def command(self, key):
        a = self.current()
        if not a:
            return
        {"toggle": self.toggle, "status": self.status, "rename": self.rename,
         "props": lambda x: self.properties(x, self)}[key](a)

    def context_menu(self, pos):
        it = self.list.itemAt(pos)
        if not it:
            return
        self.list.setCurrentItem(it)
        a = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Disa&ble" if a.connected else "Ena&ble", lambda: self.toggle(a))
        st = m.addAction("Stat&us", lambda: self.status(a))
        f = st.font()
        f.setBold(True)
        st.setFont(f)
        m.addSeparator()
        m.addAction("Rena&me", lambda: self.rename(a))
        m.addAction("P&roperties", lambda: self.properties(a, self))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def toggle(self, a: nc.Adapter):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            nc.disable(a) if a.connected else nc.enable(a)
        except nc.NetError as e:
            QApplication.restoreOverrideCursor()
            return error(self, str(e))
        QApplication.restoreOverrideCursor()
        self.reload()

    def status(self, a: nc.Adapter):
        StatusDialog(self, a).exec()
        self.reload()

    def rename(self, a: nc.Adapter):
        try:
            uuid = nc.ensure_profile(a)
        except nc.NetError as e:
            return error(self, str(e))
        name, ok = QInputDialog.getText(self, "Rename", "New name for this connection:", text=a.title)
        if ok and name.strip():
            try:
                nc.rename(uuid, name.strip())
            except nc.NetError as e:
                error(self, str(e))
            self.reload()

    def properties(self, a: nc.Adapter, parent):
        try:
            uuid = nc.ensure_profile(a)
        except nc.NetError as e:
            return error(parent, str(e))
        PropertiesDialog(parent, a, uuid).exec()
        self.reload()


def main(argv=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-network")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-network")
    if not nc.available():
        QMessageBox.critical(None, APP, "NetworkManager's command-line tool (nmcli) is missing.")
        return 1
    args = argv or []
    w = NetworkWindow()
    w.show()
    if "--ipv4" in args:
        # straight to TCP/IPv4 Properties of a device (from the network popup)
        dev = args[args.index("--ipv4") + 1] if len(args) > args.index("--ipv4") + 1 else ""
        def open_ipv4():
            w.reload()
            a = next((x for x in w.adapters if x.device == dev), None) or w.current()
            if a:
                try:
                    uuid = nc.ensure_profile(a)
                except nc.NetError as e:
                    return error(w, str(e))
                pd = PropertiesDialog(w, a, uuid)
                pd.ipv4()
                if pd.new_ipv4 is not None:
                    pd._ok()
                w.reload()
        QTimer.singleShot(100, open_ipv4)
    elif "--status" in args:
        dev = args[args.index("--status") + 1] if len(args) > args.index("--status") + 1 else ""
        def open_status():
            w.reload()
            a = next((x for x in w.adapters if x.device == dev), None)
            if a:
                w.status(a)
        QTimer.singleShot(100, open_status)
    return app.exec()
