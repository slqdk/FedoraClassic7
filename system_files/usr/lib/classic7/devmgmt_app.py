"""Device Manager, in the style of Windows 7: the computer's devices by type, each with
its driver and status."""
from __future__ import annotations

import platform
import socket
import sys

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMenu, QMessageBox,
                               QPlainTextEdit, QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

import sysinfo as si


def icon(name: str, fallback: str = "preferences-system") -> QIcon:
    ic = QIcon.fromTheme(name)
    return ic if not ic.isNull() else QIcon.fromTheme(fallback)


def with_warning(ic: QIcon) -> QIcon:
    """The device icon with Windows' little yellow warning sign in the corner."""
    pm = ic.pixmap(16, 16)
    if pm.isNull():
        pm = QPixmap(16, 16)
        pm.fill(Qt.transparent)
    p = QPainter(pm)
    icon("dialog-warning").paint(p, 6, 6, 10, 10)
    p.end()
    return QIcon(pm)


def device_icon(d: si.Device) -> QIcon:
    ic = icon(si.CATEGORIES.get(d.category, "preferences-system"))
    return with_warning(ic) if d.problem else ic


class DevicePropertiesDialog(QDialog):
    def __init__(self, d: si.Device, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{d.name} Properties")
        self.resize(420, 470)
        tabs = QTabWidget()
        tabs.addTab(self._general(d), "General")
        tabs.addTab(self._driver(d), "Driver")
        tabs.addTab(self._details(d), "Details")
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _head(self, d: si.Device) -> QHBoxLayout:
        row = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(device_icon(d).pixmap(32, 32))
        row.addWidget(ic)
        name = QLabel(d.name)
        name.setWordWrap(True)
        row.addWidget(name, 1)
        return row

    def _general(self, d: si.Device) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(self._head(d))
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        lay.addWidget(line)
        f = QFormLayout()
        f.addRow("Device type:", QLabel(d.category))
        f.addRow("Manufacturer:", QLabel(d.manufacturer or "(Standard system devices)"))
        f.addRow("Location:", QLabel(d.location or "Unknown"))
        if d.extra.get("interface"):
            f.addRow("Network name:", QLabel(d.extra["interface"]))
        lay.addLayout(f)
        box = QGroupBox("Device status")
        bl = QVBoxLayout(box)
        status = QPlainTextEdit(d.status + ("" if not d.problem else
                                            "\n\nClassic 7 gets its drivers with its updates. If this device "
                                            "should work, look for it on docs.bazzite.gg or ask in the "
                                            "Bazzite community."))
        status.setReadOnly(True)
        status.setMaximumHeight(110)
        bl.addWidget(status)
        lay.addWidget(box)
        lay.addStretch(1)
        return w

    def _driver(self, d: si.Device) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(self._head(d))
        info = si.driver_info(d.driver) if d.driver and d.driver not in ("processor", "hub") else {}
        f = QFormLayout()
        f.addRow("Driver Provider:", QLabel("Linux kernel" if d.driver else "(none)"))
        f.addRow("Driver:", QLabel(d.driver or "No driver is in use"))
        f.addRow("Driver Version:", QLabel(info.get("version") or platform.release()))
        f.addRow("Digital Signer:", QLabel("Fedora / Bazzite" if d.driver else ""))
        lay.addLayout(f)

        def row(text, help_text, enabled=False, fn=None):
            r = QHBoxLayout()
            b = QPushButton(text)
            b.setFixedWidth(140)
            b.setEnabled(enabled)
            if fn:
                b.clicked.connect(fn)
            r.addWidget(b)
            lab = QLabel(help_text)
            lab.setWordWrap(True)
            r.addWidget(lab, 1)
            lay.addLayout(r)

        row("Driver Details", "To view details about the driver files.", bool(info),
            lambda: QMessageBox.information(self, "Driver File Details",
                                            "\n".join(f"{k.title()}: {v}" for k, v in info.items())))
        row("Update Driver...", "Drivers are updated together with Classic 7 (Classic 7 Update).")
        row("Roll Back Driver", "Go back to the previous version of Classic 7 to roll back a driver.")
        row("Disable", "Disables the selected device.")
        row("Uninstall", "To uninstall the driver (Advanced).")
        lay.addStretch(1)
        return w

    def _details(self, d: si.Device) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addLayout(self._head(d))
        lay.addWidget(QLabel("Property"))
        combo = QComboBox()
        values = QListWidget()
        props = {
            "Device description": [d.name],
            "Hardware Ids": [i for i in d.ids if i] or ["(none)"],
            "Driver": [d.driver or "(none)"],
            "Location information": [d.location or "(unknown)"],
            "Device instance path (sysfs)": [d.sysfs or "(none)"],
        }
        for k, v in d.extra.items():
            props[k.title()] = [str(v)]
        combo.addItems(list(props))
        combo.currentTextChanged.connect(lambda k: (values.clear(), values.addItems(props.get(k, []))))
        lay.addWidget(combo)
        lay.addWidget(QLabel("Value"))
        lay.addWidget(values, 1)
        values.addItems(props["Device description"])
        return w


class DeviceManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Device Manager")
        self.setWindowIcon(icon("computer"))
        self.resize(560, 560)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._selection)
        self.setCentralWidget(self.tree)
        self._menus()
        self.refresh()

    def _menus(self):
        mb = self.menuBar()
        f = mb.addMenu("&File")
        f.addAction("E&xit", self.close, QKeySequence("Alt+F4"))
        self.action = mb.addMenu("&Action")
        self.action.aboutToShow.connect(self._fill_action)
        v = mb.addMenu("&View")
        a = v.addAction("Devices by &type")
        a.setCheckable(True)
        a.setChecked(True)
        h = mb.addMenu("&Help")
        h.addAction("&About Device Manager", lambda: QMessageBox.about(self, "About Device Manager",
                                                                         "Device Manager\nClassic 7"))
        tb = self.addToolBar("Standard")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.props_act = tb.addAction(icon("document-properties"), "Properties", self._properties)
        tb.addSeparator()
        tb.addAction(icon("view-refresh"), "Scan for hardware changes", self.refresh)

    def _fill_action(self):
        m = self.action
        m.clear()
        m.addAction("Scan for hardware changes", self.refresh)
        m.addSeparator()
        p = m.addAction("Properties", self._properties)
        p.setEnabled(self._device() is not None)
        m.addSeparator()
        m.addAction("Help", lambda: QMessageBox.information(
            self, "Device Manager Help", "Double-click a device to see its driver and status. A yellow sign "
            "marks a device without a driver. Drivers come with Classic 7 updates."))

    def refresh(self):
        QApplication.setOverrideCursor(Qt.BusyCursor)
        try:
            groups = si.all_devices()
        finally:
            QApplication.restoreOverrideCursor()
        expanded = {self.tree.topLevelItem(0).child(i).text(0) for i in range(self.tree.topLevelItem(0).childCount())
                    if self.tree.topLevelItem(0).child(i).isExpanded()} if self.tree.topLevelItemCount() else set()
        self.tree.clear()
        root = QTreeWidgetItem([socket.gethostname()])
        root.setIcon(0, icon("computer"))
        self.tree.addTopLevelItem(root)
        for cat, devs in groups.items():
            it = QTreeWidgetItem(root, [cat])
            problem = any(d.problem for d in devs)
            ic = icon(si.CATEGORIES.get(cat, "preferences-system"))
            it.setIcon(0, ic)
            for d in devs:
                c = QTreeWidgetItem(it, [d.name])
                c.setIcon(0, device_icon(d))
                c.setData(0, Qt.UserRole, d)
            it.setExpanded(problem or cat in expanded)
        root.setExpanded(True)
        self._selection()

    def _device(self) -> si.Device | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _selection(self):
        self.props_act.setEnabled(self._device() is not None)

    def _open(self, item, _col):
        if item.data(0, Qt.UserRole):
            self._properties()

    def _properties(self):
        d = self._device()
        if d:
            DevicePropertiesDialog(d, self).exec()

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it:
            return
        self.tree.setCurrentItem(it)
        m = QMenu(self)
        for text in ("Update Driver Software...", "Disable", "Uninstall"):
            m.addAction(text).setEnabled(False)
        m.addSeparator()
        m.addAction("Scan for hardware changes", self.refresh)
        if it.data(0, Qt.UserRole):
            m.addSeparator()
            bold = m.addAction("Properties", self._properties)
            f = bold.font()
            f.setBold(True)
            bold.setFont(f)
        m.exec(self.tree.viewport().mapToGlobal(pos))


def main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]] + argv)
    app.setApplicationName("Device Manager")
    app.setDesktopFileName("classic7-devmgmt")
    w = DeviceManager()
    w.show()
    return app.exec()
