"""Taskbar and Start Menu Properties (PySide6), as in Windows 7: the Taskbar, Start Menu and
Toolbars tabs, Customize Start Menu, and Notification Area Icons."""
from __future__ import annotations

import copy
import sys

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
    QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import taskbar_props as tp

HEAD = "#1E3987"
BLUE = "#1F4E9C"
PAGES = ("taskbar", "startmenu", "toolbars")


def link(text: str, slot) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(f"QToolButton {{ color: {BLUE}; border: none; padding: 1px; }}"
                    "QToolButton:hover { text-decoration: underline; }")
    b.clicked.connect(slot)
    return b


def wrapped(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    return lab


def combo(pairs, current: str) -> QComboBox:
    box = QComboBox()
    for key, label in pairs:
        box.addItem(label, key)
    idx = box.findData(current)
    box.setCurrentIndex(idx if idx >= 0 else 0)
    return box


# =============================================================================
# Notification area icons
# =============================================================================
def status_notifier_items() -> list[tuple[str, str, str]]:
    """(id, title, icon name) of the programs' tray icons that are there now."""
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
    except ImportError:
        return []
    bus = QDBusConnection.sessionBus()

    def get(service, path, iface, prop):
        msg = QDBusMessage.createMethodCall(service, path, "org.freedesktop.DBus.Properties", "Get")
        msg.setArguments([iface, prop])
        reply = bus.call(msg, timeout=1500)
        args = reply.arguments() if reply.type() == QDBusMessage.ReplyMessage else []
        if not args:
            return None
        v = args[0]
        return v.variant() if hasattr(v, "variant") else v

    items = get("org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                "RegisteredStatusNotifierItems") or []
    out = []
    for entry in items:
        entry = str(entry)
        service, _, path = entry.partition("/")
        path = "/" + path if path else "/StatusNotifierItem"
        sid = get(service, path, "org.kde.StatusNotifierItem", "Id")
        if not sid:
            continue
        title = get(service, path, "org.kde.StatusNotifierItem", "Title") or sid
        icon = get(service, path, "org.kde.StatusNotifierItem", "IconName") or ""
        if all(sid != o[0] for o in out):
            out.append((str(sid), str(title), str(icon)))
    return out


def nice_name(name: str) -> str:
    return name.replace(" (Classic 7)", "")


class SystemIconsDialog(QDialog):
    """Turn system icons on or off: the notification area's own icons (plasmoids)."""

    def __init__(self, tray: tp.Tray, parent=None):
        super().__init__(parent)
        self.setWindowTitle("System Icons")
        self.tray = copy.deepcopy(tray)
        lay = QVBoxLayout(self)
        head = QLabel("Turn system icons on or off")
        head.setStyleSheet(f"color: {HEAD}; font-size: 12pt;")
        lay.addWidget(head)
        lay.addWidget(wrapped("Turning an icon off removes it from the notification area."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["System Icons", "Behaviors"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(24, 24))
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.boxes: dict[str, QComboBox] = {}
        plugins = list(dict.fromkeys(tp.tray_plasmoids() + self.tray.known + self.tray.extra))
        rows = []
        for plugin in plugins:
            info = tp.plasmoid_info(plugin)
            if info is None:
                continue
            rows.append((nice_name(info[0]), info[1], plugin))
        for name, icon, plugin in sorted(rows, key=lambda r: r[0].lower()):
            it = QTreeWidgetItem([name, ""])
            it.setIcon(0, QIcon.fromTheme(icon))
            self.tree.addTopLevelItem(it)
            box = combo([("on", "On"), ("off", "Off")], "on" if plugin in self.tray.extra else "off")
            self.tree.setItemWidget(it, 1, box)
            self.boxes[plugin] = box
        self.tree.setColumnWidth(1, 120)
        lay.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(460, 420)

    def result_tray(self) -> tp.Tray:
        extra = [p for p in self.tray.extra if p not in self.boxes or self.boxes[p].currentData() == "on"]
        extra += [p for p, b in self.boxes.items() if b.currentData() == "on" and p not in extra]
        return tp.Tray(self.tray.shown, self.tray.hidden, extra, list(dict.fromkeys(self.tray.known + extra)),
                       self.tray.show_all)


class NotificationIconsDialog(QDialog):
    def __init__(self, tray: tp.Tray, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Notification Area Icons")
        self.setWindowIcon(QIcon.fromTheme("preferences-desktop-notification"))
        self.tray = copy.deepcopy(tray)
        lay = QVBoxLayout(self)
        head = QLabel("Select which icons and notifications appear on the taskbar")
        head.setStyleSheet(f"color: {HEAD}; font-size: 12pt;")
        lay.addWidget(head)
        lay.addWidget(wrapped("If you choose to hide icons and notifications, you won't be notified about changes or "
                              "updates. To view hidden icons at any time, click the arrow next to the notification "
                              "area on the taskbar."))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Icons", "Behaviors"])
        self.tree.setRootIsDecorated(False)
        self.tree.setIconSize(QSize(24, 24))
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        row.addWidget(link("Turn system icons on or off", self._system_icons))
        row.addStretch(1)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(link("Restore default icon behaviors", self._restore))
        row2.addStretch(1)
        lay.addLayout(row2)
        self.show_all = QCheckBox("Al&ways show all icons and notifications on the taskbar")
        self.show_all.setChecked(self.tray.show_all)
        self.show_all.toggled.connect(lambda on: self.tree.setEnabled(not on))
        lay.addWidget(self.show_all)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.boxes: dict[str, QComboBox] = {}
        self._fill()
        self.tree.setEnabled(not self.tray.show_all)
        self.resize(560, 470)

    def _fill(self):
        self.tree.clear()
        self.boxes = {}
        rows: list[tuple[str, str, str]] = []
        for plugin in self.tray.extra:
            info = tp.plasmoid_info(plugin)
            if info:
                rows.append((plugin, nice_name(info[0]), info[1]))
        for sid, title, icon in status_notifier_items():
            rows.append((sid, title, icon or "application-x-executable"))
        seen = {r[0] for r in rows}
        for sid in self.tray.shown + self.tray.hidden:      # programs that aren't running now
            if sid not in seen:
                info = tp.plasmoid_info(sid)
                rows.append((sid, nice_name(info[0]) if info else sid, info[1] if info else "application-x-executable"))
                seen.add(sid)
        for item, name, icon in rows:
            it = QTreeWidgetItem([name, ""])
            it.setIcon(0, QIcon.fromTheme(icon, QIcon.fromTheme("application-x-executable")))
            it.setToolTip(0, item)
            self.tree.addTopLevelItem(it)
            box = combo(tp.BEHAVIORS, tp.behavior_of(self.tray, item))
            self.tree.setItemWidget(it, 1, box)
            self.boxes[item] = box
        self.tree.setColumnWidth(1, 230)

    def _restore(self):
        for box in self.boxes.values():
            box.setCurrentIndex(box.findData(tp.AUTO))
        self.show_all.setChecked(False)

    def _system_icons(self):
        dlg = SystemIconsDialog(self.result_tray(), self)
        if dlg.exec() == QDialog.Accepted:
            self.tray = dlg.result_tray()
            self._fill()

    def result_tray(self) -> tp.Tray:
        tray = copy.deepcopy(self.tray)
        for item, box in self.boxes.items():
            tray = tp.with_behavior(tray, item, box.currentData())
        tray.show_all = self.show_all.isChecked()
        return tray


# =============================================================================
# Customize Start Menu
# =============================================================================
class CustomizeStartDialog(QDialog):
    def __init__(self, start: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Start Menu")
        self.start = dict(start)
        lay = QVBoxLayout(self)
        lay.addWidget(wrapped("You can customize how links, icons, and menus look and behave on the Start menu."))
        self.list = QListWidget()
        for key, label, _ in tp.START_ITEMS:
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if self.start.get(key, True) else Qt.Unchecked)
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        size = QGroupBox("Start menu size")
        g = QGridLayout(size)
        self.recent = QSpinBox()
        self.recent.setRange(0, 30)
        self.recent.setValue(int(self.start.get("recentCount", tp.RECENT_DEFAULT)))
        lab = QLabel("Number of recent &programs to display:")
        lab.setBuddy(self.recent)
        g.addWidget(lab, 0, 0)
        g.addWidget(self.recent, 0, 1)
        g.setColumnStretch(0, 1)
        lay.addWidget(size)
        row = QHBoxLayout()
        defaults = QPushButton("&Use Default Settings")
        defaults.clicked.connect(self._defaults)
        row.addWidget(defaults)
        row.addStretch(1)
        lay.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.resize(400, 500)

    def _defaults(self):
        for i in range(self.list.count()):
            it = self.list.item(i)
            key = it.data(Qt.UserRole)
            default = next(d for k, _, d in tp.START_ITEMS if k == key)
            it.setCheckState(Qt.Checked if default else Qt.Unchecked)
        self.recent.setValue(tp.RECENT_DEFAULT)

    def result_start(self) -> dict:
        out = dict(self.start)
        for i in range(self.list.count()):
            it = self.list.item(i)
            out[it.data(Qt.UserRole)] = it.checkState() == Qt.Checked
        out["recentCount"] = self.recent.value()
        return out


# =============================================================================
# The dialog
# =============================================================================
class TaskbarPropertiesDialog(QDialog):
    def __init__(self, page: str = "taskbar"):
        super().__init__()
        self.setWindowTitle("Taskbar and Start Menu Properties")
        self.setWindowIcon(QIcon.fromTheme("preferences-desktop"))
        self.look = tp.look()
        self.current = tp.read()
        self.pending = copy.deepcopy(self.current)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._taskbar_tab(), "Taskbar")
        self.tabs.addTab(self._start_tab(), "Start Menu")
        self.tabs.addTab(self._toolbars_tab(), "Toolbars")
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(self.status)
        lay.addWidget(self.buttons)
        self._load(self.current)
        if not self.current.found:
            self.tabs.setEnabled(False)
            self.buttons.button(QDialogButtonBox.Apply).setEnabled(False)
            self.status.setText("The taskbar can't be read: is the desktop (Plasma) running?")
        self.tabs.setCurrentIndex(PAGES.index(page) if page in PAGES else 0)

    # --- tabs ------------------------------------------------------------------------
    def _taskbar_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("Taskbar appearance")
        g = QGridLayout(box)
        self.lock = QCheckBox("&Lock the taskbar")
        self.autohide = QCheckBox("A&uto-hide the taskbar")
        self.small = QCheckBox("Use s&mall icons")
        if self.look == "classic":
            self.small.setToolTip("The Classic taskbar always has small icons.")
        self.location = combo(tp.LOCATIONS, "bottom")
        self.taskbuttons = combo(tp.BUTTONS, "full")
        g.addWidget(self.lock, 0, 0, 1, 2)
        g.addWidget(self.autohide, 1, 0, 1, 2)
        g.addWidget(self.small, 2, 0, 1, 2)
        loc = QLabel("Taskbar location on &screen:")
        loc.setBuddy(self.location)
        g.addWidget(loc, 3, 0)
        g.addWidget(self.location, 3, 1)
        tb = QLabel("Taskbar &buttons:")
        tb.setBuddy(self.taskbuttons)
        g.addWidget(tb, 4, 0)
        g.addWidget(self.taskbuttons, 4, 1)
        g.setColumnStretch(0, 1)
        lay.addWidget(box)

        area = QGroupBox("Notification area")
        h = QHBoxLayout(area)
        h.addWidget(wrapped("Customize which icons and notifications appear in the notification area."), 1)
        self.customize_tray = QPushButton("&Customize...")
        self.customize_tray.clicked.connect(self._customize_tray)
        h.addWidget(self.customize_tray, 0, Qt.AlignTop)
        lay.addWidget(area)

        peek = QGroupBox("Preview desktop with Aero Peek")
        v = QVBoxLayout(peek)
        v.addWidget(wrapped("Temporarily view the desktop when you move your mouse to the Show desktop button at "
                            "end of the taskbar."))
        self.peek = QCheckBox("Use &Aero Peek to preview the desktop")
        v.addWidget(self.peek)
        lay.addWidget(peek)
        lay.addStretch(1)
        for wdg in (self.lock, self.autohide, self.small, self.peek):
            wdg.toggled.connect(self._changed)
        for wdg in (self.location, self.taskbuttons):
            wdg.currentIndexChanged.connect(self._changed)
        return w

    def _start_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(wrapped("To customize how links, icons, and menus look and behave in the Start menu, click "
                              "Customize."), 1)
        self.customize_start = QPushButton("&Customize...")
        self.customize_start.clicked.connect(self._customize_start)
        row.addWidget(self.customize_start, 0, Qt.AlignTop)
        lay.addLayout(row)
        prow = QHBoxLayout()
        self.power = combo(tp.POWER, "shutdown")
        pl = QLabel("&Power button action:")
        pl.setBuddy(self.power)
        prow.addWidget(pl)
        prow.addWidget(self.power)
        prow.addStretch(1)
        lay.addLayout(prow)
        privacy = QGroupBox("Privacy")
        v = QVBoxLayout(privacy)
        self.recent_programs = QCheckBox("Store and display recently opened &programs in the Start menu")
        self.recent_items = QCheckBox("Store and display recently opened &items in the Start menu and the taskbar")
        v.addWidget(self.recent_programs)
        v.addWidget(self.recent_items)
        lay.addWidget(privacy)
        lay.addStretch(1)
        self.power.currentIndexChanged.connect(self._changed)
        self.recent_programs.toggled.connect(self._changed)
        self.recent_items.toggled.connect(self._changed)
        return w

    def _toolbars_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Select which toolbars to add to the taskbar."))
        self.toolbars = QListWidget()
        self.quicklaunch_item = QListWidgetItem("Quick Launch")
        self.quicklaunch_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        self.quicklaunch_item.setCheckState(Qt.Unchecked)
        self.toolbars.addItem(self.quicklaunch_item)
        self.toolbars.itemChanged.connect(lambda _it: self._changed())
        lay.addWidget(self.toolbars, 1)
        return w

    # --- state <-> controls ------------------------------------------------------------
    def _load(self, s: tp.Taskbar):
        self._loading = True
        self.lock.setChecked(s.locked)
        self.autohide.setChecked(s.hiding == "autohide")
        self._loaded_small = self.look == "classic" or s.height < 40
        self.small.setChecked(self._loaded_small)
        self.small.setEnabled(self.look != "classic")
        self.location.setCurrentIndex(max(0, self.location.findData(s.location)))
        self.taskbuttons.setCurrentIndex(max(0, self.taskbuttons.findData(s.buttons)))
        self.peek.setChecked(s.peek)
        self.peek.setEnabled(s.has_showdesktop)
        self.customize_tray.setEnabled(s.tray is not None)
        self.power.setCurrentIndex(max(0, self.power.findData(s.start.get("powerAction", "shutdown"))))
        self.recent_programs.setChecked(bool(s.start.get("showRecentPrograms", True)))
        self.recent_items.setChecked(bool(s.start.get("showJumpLists", True)))
        for wdg in (self.customize_start, self.power, self.recent_programs, self.recent_items):
            wdg.setEnabled(s.has_startmenu)
        self.quicklaunch_item.setCheckState(Qt.Checked if s.quicklaunch else Qt.Unchecked)
        if not s.can_quicklaunch:
            self.quicklaunch_item.setFlags(Qt.ItemIsUserCheckable)
        self._loading = False

    def _changed(self, *_):
        if getattr(self, "_loading", False):
            return
        p = self.pending
        p.locked = self.lock.isChecked()
        p.hiding = "autohide" if self.autohide.isChecked() else "none"
        # the height changes only with the check box (a taskbar made thicker by hand stays so)
        p.height = (self.current.height if self.small.isChecked() == self._loaded_small
                    else tp.taskbar_height(self.look, self.small.isChecked()))
        p.location = self.location.currentData()
        p.buttons = self.taskbuttons.currentData()
        p.peek = self.peek.isChecked()
        p.start = {**p.start, "powerAction": self.power.currentData(),
                   "showRecentPrograms": self.recent_programs.isChecked(),
                   "showJumpLists": self.recent_items.isChecked()}
        p.quicklaunch = self.quicklaunch_item.checkState() == Qt.Checked
        self.status.clear()

    def _customize_tray(self):
        dlg = NotificationIconsDialog(self.pending.tray or tp.Tray(), self)
        if dlg.exec() == QDialog.Accepted:
            self.pending.tray = dlg.result_tray()
            self.status.clear()

    def _customize_start(self):
        dlg = CustomizeStartDialog(self.pending.start, self)
        if dlg.exec() == QDialog.Accepted:
            self.pending.start = dlg.result_start()
            self.status.clear()

    # --- apply -------------------------------------------------------------------------
    def _apply(self) -> bool:
        if not self.current.found:
            return False
        self._changed()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = tp.apply(self.current, self.pending)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            self.status.setText("The taskbar could not be changed: is the desktop (Plasma) running?")
            return False
        self.current = copy.deepcopy(self.pending)
        return True

    def _ok(self):
        if self._apply() or not self.current.found:
            self.accept()


def tray_main(argv=None):
    """Control Panel > Notification Area Icons: that window on its own."""
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("classic7-taskbar-properties")
    app.setDesktopFileName("classic7-taskbar-properties")
    cur = tp.read()
    if not cur.found or cur.tray is None:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(None, "Notification Area Icons",
                            "The notification area can't be read: is the desktop (Plasma) running?")
        return 1
    dlg = NotificationIconsDialog(cur.tray)
    if dlg.exec() != QDialog.Accepted:
        return 0
    new = copy.deepcopy(cur)
    new.tray = dlg.result_tray()
    return 0 if tp.apply(cur, new) else 1


def main(argv=None, page: str = "taskbar"):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("classic7-taskbar-properties")
    app.setDesktopFileName("classic7-taskbar-properties")
    dlg = TaskbarPropertiesDialog(page)
    dlg.show()
    return app.exec()
