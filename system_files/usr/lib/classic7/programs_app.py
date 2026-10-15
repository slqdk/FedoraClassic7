"""Programs and Features (appwiz.cpl), in the style of Windows 7: "Uninstall or change a program"
with the list of installed programs (app store apps, Steam games, packages added to the system),
Uninstall/Change, and the details bar at the bottom."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QLinearGradient, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
                               QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import control_items as ci
import programs_data as pd
from control_panel import BLUE, HEAD, AddressBar, Link, NavPane, open_place, page_address

TITLE = "Programs and Features"


def icon_for(p: pd.Program) -> QIcon:
    if p.icon and Path(p.icon).is_file():
        ic = QIcon(p.icon)
        if not ic.isNull():
            return ic
    for name in (p.icon, p.ident, "steam" if p.kind == "steam" else "", "application-x-executable"):
        if name:
            ic = QIcon.fromTheme(name)
            if not ic.isNull():
                return ic
    return QIcon()


class Loader(QThread):
    done = Signal(list)

    def run(self):
        try:
            self.done.emit(pd.all_programs())
        except Exception:  # noqa: BLE001 - an empty list beats a crash
            self.done.emit([])


class CommandBar(QFrame):
    """The light blue bar with Organize, Uninstall, Change (Windows 7's command bar)."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 2, 8, 2)
        self.lay.setSpacing(2)

    def button(self, text: str, slot=None, menu: QMenu | None = None) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setAutoRaise(True)
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.InstantPopup)
        if slot:
            b.clicked.connect(slot)
        self.lay.addWidget(b)
        return b

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(0xf5, 0xf9, 0xfd))
        g.setColorAt(1, QColor(0xdc, 0xe6, 0xf4))
        p.fillRect(self.rect(), g)
        p.setPen(QColor(0xa0, 0xaf, 0xc3))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class DetailsBar(QFrame):
    """The bottom pane: totals, or the selected program's publisher, version and size."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 8)
        self.icon = QLabel()
        self.icon.setFixedSize(48, 48)
        lay.addWidget(self.icon)
        self.text = QLabel()
        self.text.setTextFormat(Qt.RichText)
        lay.addWidget(self.text, 1)

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(0xf0, 0xf5, 0xfb))
        g.setColorAt(1, QColor(0xdc, 0xe7, 0xf5))
        p.fillRect(self.rect(), g)
        p.setPen(QColor(0xb8, 0xc6, 0xd8))
        p.drawLine(0, 0, self.width(), 0)

    def show_totals(self, progs: list[pd.Program]):
        self.icon.setPixmap(QIcon.fromTheme("system-software-install").pixmap(48, 48))
        total = sum(p.size for p in progs)
        self.text.setText(f"<span style='color:#1e3987'>Currently installed programs</span>&nbsp;&nbsp;"
                          f"<span style='color:#555'>Total size:</span> {pd.fmt_size(total) or '0 KB'}<br>"
                          f"{len(progs)} programs installed")

    def show_program(self, p: pd.Program):
        self.icon.setPixmap(icon_for(p).pixmap(48, 48))
        rows = [f"<b>{_esc(p.publisher) or _esc(p.name)}</b>&nbsp;&nbsp;<span style='color:#555'>Product version:</span> "
                f"{_esc(p.version)}" + (f"&nbsp;&nbsp;<span style='color:#555'>Size:</span> {pd.fmt_size(p.size)}"
                                        if p.size else ""),
                f"<span style='color:#555'>Installed from:</span> {_esc(p.source)}"
                + (f"&nbsp;&nbsp;<span style='color:#555'>Install date:</span> {pd.fmt_date(p.installed)}"
                   if p.installed else "")]
        if p.extra.get("removing"):
            rows.append("<span style='color:#a00000'>Removed when you restart the computer.</span>")
        self.text.setText("<br>".join(rows))


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class RunDialog(QDialog):
    """Progress while a program is removed; the command's output under "Show details"."""

    def __init__(self, parent, title: str, argv: list[str]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        self.label = QLabel(f"Please wait while {title.removeprefix('Uninstall ')} is uninstalled...")
        self.label.setWordWrap(True)
        lay.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.log.setMinimumHeight(140)
        row = QHBoxLayout()
        self.details = QPushButton("Show details")
        self.details.clicked.connect(lambda: (self.log.setVisible(not self.log.isVisible()),
                                              self.details.setText("Hide details" if self.log.isVisible()
                                                                   else "Show details")))
        row.addWidget(self.details)
        row.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        row.addWidget(self.close_btn)
        lay.addWidget(self.log)
        lay.addLayout(row)
        self.ok = False
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(
            lambda: self.log.appendPlainText(bytes(self.proc.readAllStandardOutput()).decode(errors="replace").rstrip()))
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(lambda _e: self._finished(-1, None))
        self.proc.start(argv[0], argv[1:])

    def _finished(self, code, _status):
        if self.close_btn.isEnabled():
            return
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.ok = code == 0
        self.label.setText("The program was uninstalled." if self.ok else
                           "The program could not be uninstalled. Click Show details to see why.")
        self.close_btn.setEnabled(True)
        if not self.ok:
            self.log.setVisible(True)

    def reject(self):
        if self.close_btn.isEnabled():
            super().reject()


class ProgramsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(TITLE)
        self.setWindowIcon(QIcon.fromTheme("system-software-install"))
        self.resize(980, 640)
        self.programs: list[pd.Program] = []
        self.loader: Loader | None = None
        self._toolbar()
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        nav = NavPane()
        home = Link("Control Panel Home", BLUE)
        home.clicked.connect(lambda: ci.launch(["classic7-control"]))
        nav.lay.addWidget(home)
        nav.lay.addSpacing(10)
        updates = Link("View installed updates", BLUE)
        updates.clicked.connect(lambda: ci.launch(["classic7-update", "--history"]))
        nav.lay.addWidget(updates)
        store = Link("Get new programs", BLUE)
        store.clicked.connect(self.open_store)
        store.setVisible(bool(pd.store_command()))
        nav.lay.addWidget(store)
        steam = Link("Manage Steam games", BLUE)
        steam.clicked.connect(lambda: ci.launch(["steam", "steam://open/games"]))
        nav.lay.addWidget(steam)
        nav.lay.addStretch(1)
        outer.addWidget(nav)

        main = QWidget()
        main.setAutoFillBackground(True)
        pal = main.palette()
        pal.setColor(main.backgroundRole(), QColor("white"))
        main.setPalette(pal)
        v = QVBoxLayout(main)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(20, 14, 20, 10)
        title = QLabel("Uninstall or change a program")
        f = title.font()
        f.setPointSizeF(f.pointSizeF() * 1.45)
        title.setFont(f)
        title.setStyleSheet(f"color: {HEAD.name()};")
        hl.addWidget(title)
        hl.addWidget(QLabel("To uninstall a program, select it from the list and then click Uninstall or Change."))
        v.addWidget(head)
        self.bar = CommandBar()
        org = QMenu(self)
        org.addAction("Refresh", self.refresh, QKeySequence("F5"))
        org.addSeparator()
        org.addAction("Close", self.close)
        self.bar.button("Organize", menu=org)
        self.uninstall_btn = self.bar.button("Uninstall", self.uninstall)
        self.change_btn = self.bar.button("Change", self.change)
        self.bar.lay.addStretch(1)
        v.addWidget(self.bar)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setHeaderLabels(["Name", "Publisher", "Installed On", "Size", "Version"])
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.setFrameStyle(QFrame.NoFrame)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemSelectionChanged.connect(self._selected)
        self.tree.itemDoubleClicked.connect(lambda *_: self.uninstall())
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, w in ((1, 190), (2, 90), (3, 80), (4, 130)):
            h.resizeSection(col, w)
        v.addWidget(self.tree, 1)
        self.status = QLabel("  Please wait while the list is populated...")
        self.status.setStyleSheet("color: #555; padding: 6px;")
        v.addWidget(self.status)
        self.details = DetailsBar()
        v.addWidget(self.details)
        outer.addWidget(main, 1)
        self.setCentralWidget(central)
        QShortcut(QKeySequence("F5"), self, self.refresh)
        QShortcut(QKeySequence("Delete"), self, self.uninstall)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.search.setFocus())
        self._selected()
        QTimer.singleShot(0, self.refresh)

    def _go(self, target):
        if open_place(target):
            self.close()            # Windows 7 shows the new place in the same window

    def _toolbar(self):
        nav = QToolBar("Navigation")
        nav.setMovable(False)
        nav.setIconSize(QSize(22, 22))
        back = nav.addAction(QIcon.fromTheme("go-previous"), "Back",
                             lambda: self._go(page_address("programs", [])[-1][1]))
        back.setToolTip("Back")
        self.address = AddressBar("system-software-install", self._go)
        self.address.set_parts(page_address("programs", ["Programs and Features"]))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Programs and Features")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._filter)
        nav.addWidget(self.address)
        nav.addWidget(self.search)
        self.addToolBar(Qt.TopToolBarArea, nav)

    # ---- data ------------------------------------------------------------------------------
    def refresh(self):
        if self.loader is not None and self.loader.isRunning():
            return
        self.status.setText("  Please wait while the list is populated...")
        self.status.show()
        self.loader = Loader(self)
        self.loader.done.connect(self._loaded)
        self.loader.start()

    def _loaded(self, progs: list):
        self.programs = progs
        keep = self.current().ident if self.current() else None
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for p in progs:
            it = SortItem([p.name, p.publisher, pd.fmt_date(p.installed), pd.fmt_size(p.size), p.version])
            it.setIcon(0, icon_for(p))
            it.setData(0, Qt.UserRole, p)
            it.setData(2, Qt.UserRole, p.installed.toordinal() if p.installed else 0)
            it.setData(3, Qt.UserRole, p.size)
            it.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
            if p.extra.get("removing"):
                it.setForeground(0, QColor("#888888"))
            self.tree.addTopLevelItem(it)
            if p.ident == keep:
                it.setSelected(True)
        self.tree.setSortingEnabled(True)
        self.status.setVisible(not progs)
        self.status.setText("  No programs were found that can be uninstalled." if not progs else "")
        self._filter(self.search.text())
        self._selected()

    def _filter(self, text: str):
        t = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            p = it.data(0, Qt.UserRole)
            it.setHidden(bool(t) and t not in f"{p.name} {p.publisher} {p.ident}".lower())

    def current(self) -> pd.Program | None:
        items = self.tree.selectedItems() if hasattr(self, "tree") else []
        return items[0].data(0, Qt.UserRole) if items else None

    def _selected(self):
        p = self.current()
        self.uninstall_btn.setVisible(p is not None)
        self.change_btn.setVisible(p is not None and bool(p.change_argv()))
        if p:
            self.details.show_program(p)
        else:
            self.details.show_totals(self.programs)

    def _menu(self, pos):
        p = self.current()
        if not p:
            return
        m = QMenu(self)
        m.addAction("Uninstall", self.uninstall)
        if p.change_argv():
            m.addAction("Change", self.change)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    # ---- actions ------------------------------------------------------------------------------
    def open_store(self):
        ci.launch(pd.store_command())

    def change(self):
        p = self.current()
        if p and p.change_argv():
            ci.launch(p.change_argv())

    def uninstall(self):
        p = self.current()
        if not p:
            return
        if p.extra.get("removing"):
            QMessageBox.information(self, TITLE, f"{p.name} is removed when you restart the computer.")
            return
        if p.kind == "steam":
            # Steam asks itself and removes the game files
            if not ci.launch(p.uninstall_argv()):
                QMessageBox.warning(self, TITLE, "Steam is not available.")
            QTimer.singleShot(15000, self.refresh)
            return
        text = f"Are you sure you want to uninstall {p.name}?"
        if p.kind == "rpm":
            text += "\n\nIt was added to the system image. It is removed when you restart the computer."
        if QMessageBox.question(self, TITLE, text, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        dlg = RunDialog(self, f"Uninstall {p.name}", p.uninstall_argv())
        dlg.exec()
        if dlg.ok and p.kind == "rpm":
            QMessageBox.information(self, TITLE, f"You must restart your computer to finish removing {p.name}.")
        self.refresh()


class SortItem(QTreeWidgetItem):
    """Dates and sizes sort by value, not by text."""

    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        if col in (2, 3):
            return (self.data(col, Qt.UserRole) or 0) < (other.data(col, Qt.UserRole) or 0)
        return self.text(col).lower() < other.text(col).lower()


def main(argv=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-programs")
    app.setApplicationDisplayName(TITLE)
    app.setDesktopFileName("classic7-programs")
    w = ProgramsWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
