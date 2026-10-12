"""Map Network Drive / Disconnect Network Drives dialogs, like Windows 7's."""
from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

import netdrive as nd

APP = "Map Network Drive"


def theme_icon(*names):
    for n in names:
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return QIcon()


def open_folder(path: str):
    try:
        subprocess.Popen(["xdg-open", path], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class Worker(QThread):
    done = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:  # noqa: BLE001 - handed to the GUI thread
            self.done.emit(e)


def busy_call(parent, fn, text="Connecting…"):
    """Run fn in a thread with a small wait note; returns its result or raises its error."""
    from PySide6.QtCore import QEventLoop
    box = QMessageBox(QMessageBox.Information, APP, text, QMessageBox.NoButton, parent)
    box.setStandardButtons(QMessageBox.NoButton)
    loop = QEventLoop()
    out = {}
    w = Worker(fn, parent)
    w.done.connect(lambda r: (out.__setitem__("r", r), loop.quit()))
    QApplication.setOverrideCursor(Qt.WaitCursor)
    box.show()
    w.start()
    loop.exec()
    w.wait()
    box.hide()
    box.deleteLater()
    QApplication.restoreOverrideCursor()
    r = out.get("r")
    if isinstance(r, Exception):
        raise r
    return r


class PasswordDialog(QDialog):
    """Windows Security: Enter Network Password."""

    def __init__(self, parent, server: str, user: str = "", domain: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Enter Network Password")
        v = QVBoxLayout(self)
        head = QLabel(f"<b>Enter your password to connect to: {server}</b>")
        v.addWidget(head)
        f = QFormLayout()
        self.user = QLineEdit(user)
        self.user.setPlaceholderText("User name (DOMAIN\\user or user)")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("Password")
        f.addRow("&User name:", self.user)
        f.addRow("&Password:", self.password)
        v.addLayout(f)
        if domain and user:
            self.user.setText(f"{domain}\\{user}")
        self.remember = QCheckBox("&Remember my credentials")
        self.remember.setChecked(True)
        v.addWidget(self.remember)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        (self.password if user else self.user).setFocus()

    def credentials(self) -> tuple[str, str, str]:
        """(user, domain, password)"""
        text = self.user.text().strip()
        domain = ""
        if "\\" in text:
            domain, text = text.split("\\", 1)
        elif "@" in text:
            text, domain = text.split("@", 1)
        return text, domain, self.password.text()


class BrowseDialog(QDialog):
    """Browse For Folder: the shares on a server."""

    def __init__(self, parent, server: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Browse For Folder")
        self.creds = ("", "", "")
        self.chosen = ""
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Select a shared network folder"))
        row = QHBoxLayout()
        row.addWidget(QLabel("&Server:"))
        self.server = QLineEdit(server)
        self.server.setPlaceholderText("Name or IP address, e.g. 30.11.0.2")
        self.server.returnPressed.connect(self.look)
        row.addWidget(self.server, 1)
        go = QPushButton("&Show shares")
        go.clicked.connect(self.look)
        row.addWidget(go)
        v.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Comment"])
        self.tree.setRootIsDecorated(True)
        self.tree.itemDoubleClicked.connect(lambda *_: self._ok())
        v.addWidget(self.tree, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(420, 420)
        if server:
            self.look()

    def look(self):
        server = self.server.text().strip().strip("\\/")
        if not server:
            return
        self.tree.clear()
        self.note.setText("")
        user, domain, pw = self.creds
        try:
            shares = busy_call(self, lambda: nd.list_shares(server, user, pw, domain), "Looking for shared folders…")
        except nd.DriveError as e:
            if str(e) == "access-denied":
                d = PasswordDialog(self, server)
                if d.exec() == QDialog.Accepted:
                    self.creds = d.credentials()
                    return self.look()
                return
            self.note.setText(str(e))
            return
        top = QTreeWidgetItem([f"\\\\{server}", ""])
        top.setIcon(0, theme_icon("network-server", "computer"))
        self.tree.addTopLevelItem(top)
        for name, comment in shares:
            it = QTreeWidgetItem([name, comment])
            it.setIcon(0, theme_icon("folder-network", "folder-remote", "folder"))
            it.setData(0, Qt.UserRole, f"\\\\{server}\\{name}")
            top.addChild(it)
        top.setExpanded(True)
        if shares:
            self.tree.setCurrentItem(top.child(0))
        else:
            self.note.setText("This server shares no folders (or none you may see).")

    def _ok(self):
        it = self.tree.currentItem()
        if it and it.data(0, Qt.UserRole):
            self.chosen = it.data(0, Qt.UserRole)
            self.accept()


class MapDialog(QDialog):
    def __init__(self, folder: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(APP)
        self.setWindowIcon(theme_icon("network-server", "folder-network"))
        self.settings = QSettings("Classic7", "NetDrive")
        self.result_mapping: nd.Mapping | None = None
        v = QVBoxLayout(self)
        title = QLabel("What network folder would you like to map?")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.3)
        title.setFont(f)
        title.setStyleSheet("color: #1E395B;")
        v.addWidget(title)
        v.addWidget(QLabel("Specify the drive letter for the connection and the folder that you want to connect to:"))
        form = QFormLayout()
        self.drive = QComboBox()
        maps = nd.load()
        for l in nd.free_letters(maps):
            self.drive.addItem(f"{l}:", l)
        self.drive.setFixedWidth(70)
        drow = QHBoxLayout()
        drow.addWidget(self.drive)
        drow.addStretch(1)
        dlab = QLabel("&Drive:")
        dlab.setBuddy(self.drive)
        form.addRow(dlab, drow)
        frow = QHBoxLayout()
        self.folder = QComboBox()
        self.folder.setEditable(True)
        self.folder.setMinimumWidth(280)
        history = self.settings.value("history", []) or []
        if isinstance(history, str):
            history = [history]
        self.folder.addItems(history)
        self.folder.setEditText(folder or "")
        self.folder.lineEdit().setPlaceholderText("\\\\server\\share")
        frow.addWidget(self.folder, 1)
        browse = QPushButton("B&rowse...")
        browse.clicked.connect(self.browse)
        frow.addWidget(browse)
        flab = QLabel("&Folder:")
        flab.setBuddy(self.folder)
        form.addRow(flab, frow)
        ex = QLabel("Example: \\\\30.11.0.2\\Data")
        ex.setStyleSheet("color: palette(dark);")
        form.addRow("", ex)
        v.addLayout(form)
        self.reconnect = QCheckBox("Reconnect at sign-&in")
        self.reconnect.setChecked(True)
        self.other = QCheckBox("Connect using different &credentials")
        v.addWidget(self.reconnect)
        v.addWidget(self.other)
        note = QLabel("The folder appears in Computer and in your Network folder "
                      "(e.g. Network/Z - Data (30.11.0.2)), and every program can open files there.")
        note.setWordWrap(True)
        v.addWidget(note)
        bb = QDialogButtonBox()
        self.finish = bb.addButton("&Finish", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self._finish)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if not self.drive.count():
            self.finish.setEnabled(False)
            note.setText("All drive letters are in use. Disconnect a network drive first.")
        self.folder.setFocus()

    def browse(self):
        text = self.folder.currentText().strip()
        server = ""
        if text:
            try:
                server = nd.split_unc(nd.to_unc(text))[0]
            except nd.DriveError:
                server = text.strip("\\/").split("\\")[0].split("/")[0]
        d = BrowseDialog(self, server)
        if d.exec() == QDialog.Accepted and d.chosen:
            self.folder.setEditText(d.chosen)

    def _finish(self):
        text = self.folder.currentText().strip()
        try:
            m = nd.new_mapping(text, self.drive.currentData(), self.reconnect.isChecked())
            server, _share = nd.split_unc(m.unc)
        except nd.DriveError as e:
            return QMessageBox.warning(self, APP, str(e))
        password = None
        if self.other.isChecked():
            d = PasswordDialog(self, server)
            if d.exec() != QDialog.Accepted:
                return
            m.user, m.domain, password = d.credentials()
        while True:
            try:
                busy_call(self, lambda: nd.add(m, password), f"Connecting to {nd.to_windows(m.unc)}…")
                break
            except nd.DriveError as e:
                if str(e) == "access-denied":
                    d = PasswordDialog(self, server, m.user, m.domain)
                    if d.exec() != QDialog.Accepted:
                        return
                    m.user, m.domain, password = d.credentials()
                    continue
                return QMessageBox.warning(self, APP, f"Classic 7 can't access {nd.to_windows(m.unc)}\n\n{e}")
        history = [text] + [h for h in (self.settings.value("history", []) or []) if h != text]
        self.settings.setValue("history", history[:10])
        self.result_mapping = m
        self.accept()
        open_folder(m.folder)


class DisconnectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Disconnect Network Drives")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Select the network drive(s) you want to disconnect, then click OK."))
        v.addWidget(QLabel("&Network Drives:"))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        for m in nd.load():
            state = "" if m.connected else "  (disconnected)"
            it = QListWidgetItem(theme_icon("folder-network", "network-server"),
                                 f"{m.letter}:    {nd.to_windows(m.unc)}{state}")
            it.setData(Qt.UserRole, m)
            self.list.addItem(it)
        v.addWidget(self.list, 1)
        if not self.list.count():
            v.addWidget(QLabel("There are no mapped network drives."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(420, 280)

    def _ok(self):
        for it in self.list.selectedItems():
            m = it.data(Qt.UserRole)
            try:
                nd.disconnect(m)
            except nd.DriveError as e:
                QMessageBox.warning(self, self.windowTitle(),
                                    f"{m.letter}: could not be disconnected:\n\n{e}\n\n"
                                    "Close programs that have files open there and try again.")
                return
        self.accept()


def main(argv=None) -> int:
    args = argv or []
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-netdrive")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-netdrive")
    if args[:1] == ["--disconnect"]:
        return 0 if DisconnectDialog().exec() == QDialog.Accepted else 1
    folder = next((a for a in args if not a.startswith("-")), "")
    return 0 if MapDialog(folder).exec() == QDialog.Accepted else 1
