"""Classic 7 "Computer" window: drives as tiles with capacity bars, like the classic Computer page."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QPoint, QProcess, QRect, QSize, QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLayout,
    QLineEdit, QMainWindow, QMenu, QMessageBox, QScrollArea, QSplitter, QToolBar,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QWidgetItem,
)

import drives as dr

TILE_W, TILE_H = 268, 64
BAR_W, BAR_H = 176, 14
WARN_FRACTION = 0.9


def themed_icon(name: str, fallback: str = "drive-harddisk") -> QIcon:
    icon = QIcon.fromTheme(name)
    return icon if not icon.isNull() else QIcon.fromTheme(fallback)


def launch(program: str, args: list[str]) -> bool:
    if shutil.which(program) is None:
        return False
    try:
        subprocess.Popen([program, *args], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def open_in_explorer(url: str) -> bool:
    return launch("dolphin", ["--new-window", url])


# =============================================================================
# Flow layout (tiles wrap like an icon view)
# =============================================================================
class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        for item in self._items:
            if item.widget() and item.widget().isHidden():
                continue
            hint = item.sizeHint()
            if x + hint.width() > r.right() and line_h > 0:
                x = r.x()
                y += line_h + self.spacing()
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + m.bottom()


# =============================================================================
# Painting helpers (classic 3D edges from the palette)
# =============================================================================
def sunken_frame(p: QPainter, r: QRect, pal: QPalette):
    """Two-pixel sunken edge, like a classic progress bar well."""
    light, mid, dark, shadow = (pal.color(QPalette.Light), pal.color(QPalette.Midlight),
                                pal.color(QPalette.Dark), pal.color(QPalette.Shadow))
    x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
    for (ax, ay, bx, by), c in (((x0, y0, x1 - 1, y0), dark), ((x0, y0, x0, y1 - 1), dark),
                               ((x0, y1, x1, y1), light), ((x1, y0, x1, y1), light),
                               ((x0 + 1, y0 + 1, x1 - 2, y0 + 1), shadow), ((x0 + 1, y0 + 1, x0 + 1, y1 - 2), shadow),
                               ((x0 + 1, y1 - 1, x1 - 1, y1 - 1), mid), ((x1 - 1, y0 + 1, x1 - 1, y1 - 1), mid)):
        p.setPen(QPen(c, 1))
        p.drawLine(ax, ay, bx, by)


def capacity_bar(p: QPainter, r: QRect, fraction: float | None, pal: QPalette):
    """Classic segmented progress bar; turns red when the drive is almost full."""
    p.fillRect(r, pal.color(QPalette.Base))
    sunken_frame(p, r, pal)
    if fraction is None:
        return
    inner = r.adjusted(3, 3, -3, -3)
    fill_w = int(inner.width() * fraction)
    color = QColor("#C42B1C") if fraction >= WARN_FRACTION else pal.color(QPalette.Highlight)
    seg, gap = 6, 2
    x = inner.left()
    while x < inner.left() + fill_w:
        w = min(seg, inner.left() + fill_w - x)
        p.fillRect(QRect(x, inner.top(), w, inner.height()), color)
        x += seg + gap


# =============================================================================
# Widgets
# =============================================================================
class GroupHeader(QWidget):
    toggled = Signal(bool)

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.count = 0
        self.expanded = True
        self.setFixedHeight(24)
        self.setCursor(Qt.PointingHandCursor)

    def set_count(self, n: int):
        self.count = n
        self.update()

    def mousePressEvent(self, e):
        self.expanded = not self.expanded
        self.toggled.emit(self.expanded)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        pal = self.palette()
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(pal.color(QPalette.WindowText))
        arrow = "▼" if self.expanded else "►"
        text = f"{arrow}  {self.title} ({self.count})"
        tw = p.fontMetrics().horizontalAdvance(text)
        p.drawText(QRect(4, 0, tw + 4, self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        y = self.height() // 2 + 1
        x = tw + 14
        p.setPen(pal.color(QPalette.Dark))
        p.drawLine(x, y, self.width() - 8, y)
        p.setPen(pal.color(QPalette.Light))
        p.drawLine(x, y + 1, self.width() - 8, y + 1)


class DriveTile(QWidget):
    activated = Signal(object)
    selected = Signal(object)
    menu_requested = Signal(object, QPoint)

    def __init__(self, drive: dr.Drive):
        super().__init__()
        self.drive = drive
        self.is_selected = False
        self.setFixedSize(TILE_W, TILE_H)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip(self._tooltip())

    def _tooltip(self) -> str:
        d = self.drive
        lines = [d.name]
        if d.mounted and d.total:
            lines += [f"Free space: {dr.human(d.free)}", f"Total size: {dr.human(d.total)}"]
        if d.fstype:
            lines.append(f"File system: {d.fstype}")
        return "\n".join(lines)

    def set_selected(self, on: bool):
        self.is_selected = on
        self.update()

    def mousePressEvent(self, e):
        self.setFocus()
        self.selected.emit(self)
        if e.button() == Qt.RightButton:
            self.menu_requested.emit(self, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit(self)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.activated.emit(self)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        pal = self.palette()
        d = self.drive
        icon = themed_icon(d.icon)
        icon.paint(p, QRect(6, 8, 48, 48))

        text_x = 62
        fm = p.fontMetrics()
        name_rect = QRect(text_x, 4, TILE_W - text_x - 4, fm.height() + 2)
        name = fm.elidedText(d.name, Qt.ElideRight, name_rect.width() - 4)
        if self.is_selected:
            hl = QRect(text_x - 2, name_rect.top(), fm.horizontalAdvance(name) + 6, name_rect.height())
            p.fillRect(hl, pal.color(QPalette.Highlight))
            p.setPen(pal.color(QPalette.HighlightedText))
            if self.hasFocus():
                pen = QPen(pal.color(QPalette.HighlightedText), 1, Qt.DotLine)
                p.save()
                p.setPen(pen)
                p.drawRect(hl.adjusted(0, 0, -1, -1))
                p.restore()
        else:
            p.setPen(pal.color(QPalette.WindowText))
        p.drawText(name_rect.adjusted(1, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, name)

        bar = QRect(text_x, name_rect.bottom() + 4, BAR_W, BAR_H)
        if d.mounted and d.total:
            capacity_bar(p, bar, d.used_fraction, pal)
            ty = bar.bottom() + 2
        else:
            ty = name_rect.bottom() + 3
        p.setPen(pal.color(QPalette.Dark) if not pal.color(QPalette.Window).lightness() < 110
                 else pal.color(QPalette.Midlight))
        p.drawText(QRect(text_x, ty, TILE_W - text_x - 4, fm.height() + 2), Qt.AlignLeft | Qt.AlignVCenter,
                   dr.free_text(d))


class PieChart(QWidget):
    """The classic two-colour disk pie, with a little depth."""

    USED, FREE = QColor("#0000FF"), QColor("#FF00FF")

    def __init__(self, fraction: float):
        super().__init__()
        self.fraction = fraction
        self.setFixedSize(150, 96)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRect(10, 6, 130, 70)
        depth = 12
        start = 0
        span_used = int(-self.fraction * 360 * 16)
        for off in range(depth, 0, -1):
            rr = r.translated(0, off)
            p.setPen(Qt.NoPen)
            p.setBrush(self.FREE.darker(160))
            p.drawPie(rr, start + span_used, -(360 * 16 + span_used))
            p.setBrush(self.USED.darker(160))
            p.drawPie(rr, start, span_used)
        p.setPen(QPen(QColor("#000000"), 1))
        p.setBrush(self.FREE)
        p.drawPie(r, start + span_used, -(360 * 16 + span_used))
        p.setBrush(self.USED)
        p.drawPie(r, start, span_used)


class PropertiesDialog(QDialog):
    def __init__(self, drive: dr.Drive, parent=None):
        super().__init__(parent)
        d = drive
        self.setWindowTitle(f"{d.name} Properties")
        top = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(themed_icon(d.icon).pixmap(32, 32))
        name = QLineEdit(d.label or d.name)
        name.setReadOnly(True)
        top.addWidget(icon)
        top.addWidget(name, 1)

        form = QFormLayout()
        form.addRow("Type:", QLabel(d.kind))
        form.addRow("File system:", QLabel(d.fstype or "—"))
        form.addRow("Location:", QLabel(d.mountpoint or "Not opened yet"))
        if d.device:
            form.addRow("Device:", QLabel(d.device))

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self._line())
        lay.addLayout(form)
        lay.addWidget(self._line())
        if d.mounted and d.total:
            used = d.total - (d.free or 0)
            space = QFormLayout()
            space.addRow(self._swatch(PieChart.USED, "Used space:"), QLabel(f"{used:,} bytes   {dr.human(used)}"))
            space.addRow(self._swatch(PieChart.FREE, "Free space:"), QLabel(f"{d.free or 0:,} bytes   {dr.human(d.free)}"))
            lay.addLayout(space)
            lay.addWidget(self._line())
            lay.addWidget(QLabel(f"Capacity:   {d.total:,} bytes   {dr.human(d.total)}"))
            lay.addWidget(PieChart(d.used_fraction or 0), 0, Qt.AlignHCenter)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)
        self.setMinimumWidth(360)

    @staticmethod
    def _line() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setFrameShadow(QFrame.Sunken)
        return f

    @staticmethod
    def _swatch(color: QColor, text: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        sq = QLabel()
        sq.setFixedSize(14, 14)
        sq.setStyleSheet(f"background:{color.name()}; border:1px solid black;")
        h.addWidget(sq)
        h.addWidget(QLabel(text))
        return w


class DetailsPane(QFrame):
    """Bottom pane: computer summary, or details of the selected drive."""

    def __init__(self):
        super().__init__()
        self.setFrameStyle(QFrame.StyledPanel | QFrame.Raised)
        self.setFixedHeight(70)
        self.icon = QLabel()
        self.title = QLabel()
        f = self.title.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() * 1.15)
        self.title.setFont(f)
        self.line1 = QLabel()
        self.line2 = QLabel()
        text = QVBoxLayout()
        text.setSpacing(1)
        for w in (self.title, self.line1, self.line2):
            text.addWidget(w)
        lay = QHBoxLayout(self)
        lay.addWidget(self.icon)
        lay.addLayout(text, 1)
        self.summary = dr.system_summary()
        self.show_computer()

    def show_computer(self):
        self.icon.setPixmap(themed_icon("computer", "computer-laptop").pixmap(48, 48))
        self.title.setText(self.summary["name"])
        self.line1.setText(f"Processor:  {self.summary['cpu'] or 'unknown'}")
        self.line2.setText(f"Memory:  {self.summary['memory'] or 'unknown'}")

    def show_drive(self, d: dr.Drive):
        self.icon.setPixmap(themed_icon(d.icon).pixmap(48, 48))
        self.title.setText(f"{d.name}   <span style='font-weight:normal'>{d.kind}</span>")
        self.title.setTextFormat(Qt.RichText)
        if d.mounted and d.total:
            self.line1.setText(f"Space free:  {dr.human(d.free)}      Total size:  {dr.human(d.total)}")
        else:
            self.line1.setText("Not opened yet. Double-click to open it.")
        self.line2.setText(f"File system:  {d.fstype or '—'}")


# =============================================================================
# Main window
# =============================================================================
class ComputerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Computer")
        self.setWindowIcon(themed_icon("computer", "computer-laptop"))
        self.resize(900, 600)
        self.tiles: list[DriveTile] = []
        self.current: DriveTile | None = None
        self.snapshot = None
        self.store = self._find_store()

        self._build_toolbars()
        self._build_body()
        self.refresh()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        refresh = QAction(self)
        refresh.setShortcut(QKeySequence(Qt.Key_F5))
        refresh.triggered.connect(lambda: self.refresh(force=True))
        self.addAction(refresh)

    # --- layout ----------------------------------------------------------------
    def _build_toolbars(self):
        nav = QToolBar("Navigation")
        nav.setMovable(False)
        nav.setIconSize(QSize(22, 22))
        back = nav.addAction(themed_icon("go-previous"), "Back")
        fwd = nav.addAction(themed_icon("go-next"), "Forward")
        back.setEnabled(False)
        fwd.setEnabled(False)
        self.address = QLineEdit("  \u25b8 Computer \u25b8")
        self.address.setReadOnly(True)
        self.address.addAction(themed_icon("computer", "computer-laptop"), QLineEdit.LeadingPosition)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Computer")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(self._filter)
        nav.addWidget(self.address)
        nav.addWidget(self.search)
        self.addToolBar(Qt.TopToolBarArea, nav)
        self.addToolBarBreak()

        cmd = QToolBar("Command Bar")
        cmd.setMovable(False)
        cmd.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.props_action = cmd.addAction("Properties", self._properties)
        self.props_action.setEnabled(False)
        self.eject_action = cmd.addAction("Eject", self._eject)
        self.eject_action.setEnabled(False)
        cmd.addSeparator()
        if shutil.which("classic7-system"):
            cmd.addAction("System properties", lambda: launch("classic7-system", []))
        elif shutil.which("kinfocenter"):
            cmd.addAction("System properties", lambda: launch("kinfocenter", []))
        if self.store:
            cmd.addAction("Uninstall or change a program", lambda: launch(*self.store))
        cmd.addAction("Map network drive", lambda: self._netdrive([]))
        if shutil.which("classic7-diskmgmt"):
            cmd.addAction("Manage drives", lambda: launch("classic7-diskmgmt", []))
        cmd.addAction("Disconnect network drive", lambda: self._netdrive(["--disconnect"]))
        if shutil.which("classic7-control"):
            cmd.addAction("Open Control Panel", lambda: launch("classic7-control", []))
        elif shutil.which("systemsettings"):
            cmd.addAction("Open Control Panel", lambda: launch("systemsettings", []))
        self.addToolBar(Qt.TopToolBarArea, cmd)

    def _build_body(self):
        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(14)
        self.nav.setMinimumWidth(170)
        self.nav.itemClicked.connect(self._nav_clicked)

        self.content = QWidget()
        self.content.setAutoFillBackground(True)
        self.content.setBackgroundRole(QPalette.Base)
        self.content_lay = QVBoxLayout(self.content)
        self.content_lay.setContentsMargins(10, 6, 10, 10)
        self.content_lay.setSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.content)
        scroll.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)

        split = QSplitter()
        split.addWidget(self.nav)
        split.addWidget(scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([200, 700])

        self.details = DetailsPane()
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        lay.addWidget(split, 1)
        lay.addWidget(self.details)
        self.setCentralWidget(central)
        self.content.mousePressEvent = lambda e: self._select(None)

    def _find_store(self):
        import programs_data
        cmd = programs_data.store_command()
        return (cmd[0], cmd[1:]) if cmd else None

    # --- data -------------------------------------------------------------------
    def refresh(self, force: bool = False):
        drives = dr.list_drives()
        snap = [(d.key, d.name, d.mountpoint, d.total, (d.free or 0) // (1 << 24)) for d in drives]
        if snap == self.snapshot and not force:
            return
        self.snapshot = snap
        selected_key = self.current.drive.key if self.current else None
        self._rebuild(drives, selected_key)

    def _rebuild(self, drives: list[dr.Drive], selected_key: str | None):
        while self.content_lay.count():
            item = self.content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.tiles = []
        self.current = None
        for group in dr.GROUP_ORDER:
            members = [d for d in drives if d.group == group]
            if not members:
                continue
            header = GroupHeader(group)
            header.set_count(len(members))
            box = QWidget()
            flow = FlowLayout(box, spacing=8)
            flow.setContentsMargins(14, 2, 0, 8)
            for d in members:
                tile = DriveTile(d)
                tile.activated.connect(lambda t: self._open(t.drive))
                tile.selected.connect(self._select)
                tile.menu_requested.connect(self._menu)
                flow.addWidget(tile)
                self.tiles.append(tile)
            header.toggled.connect(box.setVisible)
            self.content_lay.addWidget(header)
            self.content_lay.addWidget(box)
        self.content_lay.addStretch(1)
        self._fill_nav(drives)
        self.statusBar().showMessage(f"{len(drives)} items")
        for t in self.tiles:
            if t.drive.key == selected_key:
                self._select(t)
        if not self.current:
            self._select(None)
        self._filter(self.search.text())

    def _fill_nav(self, drives):
        self.nav.clear()
        home = os.path.expanduser("~")

        def loc(kind, fallback):
            p = QStandardPaths.writableLocation(kind)
            return p if p and os.path.isdir(p) else fallback

        groups = [
            ("Favorites", "user-bookmarks", [
                ("Desktop", "user-desktop", loc(QStandardPaths.DesktopLocation, home)),
                ("Downloads", "folder-downloads", loc(QStandardPaths.DownloadLocation, home)),
                ("Recent Places", "document-open-recent", "recentlyused:/"),
            ]),
            ("Libraries", "folder-documents", [
                ("Documents", "folder-documents", loc(QStandardPaths.DocumentsLocation, home)),
                ("Music", "folder-music", loc(QStandardPaths.MusicLocation, home)),
                ("Pictures", "folder-pictures", loc(QStandardPaths.PicturesLocation, home)),
                ("Videos", "folder-videos", loc(QStandardPaths.MoviesLocation, home)),
            ]),
        ]
        for title, icon, children in groups:
            top = QTreeWidgetItem([title])
            top.setIcon(0, themed_icon(icon, "folder"))
            for name, ic, url in children:
                it = QTreeWidgetItem([name])
                it.setIcon(0, themed_icon(ic, "folder"))
                it.setData(0, Qt.UserRole, ("url", url))
                top.addChild(it)
            self.nav.addTopLevelItem(top)
            top.setExpanded(True)

        comp = QTreeWidgetItem(["Computer"])
        comp.setIcon(0, themed_icon("computer", "computer-laptop"))
        f = comp.font(0)
        f.setBold(True)
        comp.setFont(0, f)
        for d in drives:
            it = QTreeWidgetItem([d.name])
            it.setIcon(0, themed_icon(d.icon))
            it.setData(0, Qt.UserRole, ("drive", d.key))
            comp.addChild(it)
        self.nav.addTopLevelItem(comp)
        comp.setExpanded(True)
        self.nav.setCurrentItem(comp)

        net = QTreeWidgetItem(["Network"])
        net.setIcon(0, themed_icon("network-workgroup", "folder-network"))
        net.setData(0, Qt.UserRole, ("url", "remote:/"))
        self.nav.addTopLevelItem(net)

    # --- interaction --------------------------------------------------------------
    def _filter(self, text: str):
        text = text.strip().lower()
        for t in self.tiles:
            t.setVisible(not text or text in t.drive.name.lower())
        for i in range(self.content_lay.count()):
            w = self.content_lay.itemAt(i).widget()
            if w and isinstance(w.layout(), FlowLayout):
                w.layout().invalidate()

    def _select(self, tile: DriveTile | None):
        for t in self.tiles:
            t.set_selected(t is tile)
        self.current = tile
        self.props_action.setEnabled(tile is not None)
        can_eject = bool(tile and (tile.drive.group in (dr.REMOVABLE, dr.NETWORK)))
        self.eject_action.setEnabled(can_eject)
        if tile:
            self.details.show_drive(tile.drive)
        else:
            self.details.show_computer()

    def _menu(self, tile: DriveTile, pos: QPoint):
        m = QMenu(self)
        f = m.font()
        f.setBold(True)
        open_act = m.addAction("Open", lambda: self._open(tile.drive))
        open_act.setFont(f)
        m.addAction("Open in new window", lambda: self._open(tile.drive, keep=True))
        if tile.drive.device and tile.drive.kind in ("Local Disk", "Removable Disk") and shutil.which("classic7-diskmgmt"):
            m.addSeparator()
            m.addAction("Format...", lambda: launch("classic7-diskmgmt", ["--format", tile.drive.device]))
            m.addAction("Change drive letter...", lambda: launch("classic7-diskmgmt", ["--letter", tile.drive.device]))
        if tile.drive.group in (dr.REMOVABLE, dr.NETWORK):
            m.addSeparator()
            m.addAction("Eject" if tile.drive.kind == "CD Drive" else
                        "Disconnect" if tile.drive.group == dr.NETWORK else "Safely Remove", self._eject)
        m.addSeparator()
        m.addAction("Properties", self._properties)
        m.exec(pos)

    def _nav_clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, value = data
        if kind == "url":
            self._go(value)
        elif kind == "drive":
            for t in self.tiles:
                if t.drive.key == value:
                    self._open(t.drive)

    def _go(self, url: str, keep: bool = False):
        if open_in_explorer(url):
            if not keep:
                self.close()
        else:
            QMessageBox.warning(self, "Computer", "The file manager (Dolphin) could not be started.")

    def _netdrive(self, args: list[str]):
        """Map / Disconnect Network Drive, then show the result here."""
        proc = QProcess(self)
        proc.finished.connect(lambda *_: self.refresh(force=True))
        proc.start("classic7-netdrive", args)

    def _reconnect(self, d: dr.Drive, keep: bool):
        m = dr.mapping_for(d)
        if m is None:
            return
        import netdrive
        QApplication.setOverrideCursor(Qt.BusyCursor)
        try:
            netdrive.connect(m)
        except netdrive.DriveError as e:
            QApplication.restoreOverrideCursor()
            if str(e) == "access-denied":
                self._netdrive([netdrive.to_windows(m.unc)])
                return
            QMessageBox.warning(self, d.name, f"{d.name} could not be reconnected.\n\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.refresh(force=True)
        self._go(m.folder, keep)

    def _open(self, d: dr.Drive, keep: bool = False):
        if d.mounted:
            self._go(d.mountpoint, keep)
            return
        if d.key.startswith("netdrive:"):
            self._reconnect(d, keep)
            return
        if not d.device:
            return
        QApplication.setOverrideCursor(Qt.BusyCursor)
        proc = QProcess(self)

        def done(code, _status):
            QApplication.restoreOverrideCursor()
            out = bytes(proc.readAllStandardOutput()).decode(errors="replace").strip()
            err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
            if code == 0 and " at " in out:
                self._go(out.split(" at ", 1)[1].rstrip("."), keep)
            elif code == 0:
                self.refresh(force=True)
            else:
                QMessageBox.warning(self, d.name, f"{d.name} could not be opened.\n\n{err or out}")

        proc.finished.connect(done)
        proc.start("udisksctl", ["mount", "-b", d.device])

    def _eject(self):
        if not self.current:
            return
        d = self.current.drive
        ok, msg = dr.eject(d)
        if ok:
            self.statusBar().showMessage(f"{d.name} can now be safely removed.", 6000)
        else:
            QMessageBox.warning(self, d.name, f"{d.name} could not be removed. Close any open files on it.\n\n{msg}")
        self.refresh(force=True)

    def _properties(self):
        if self.current:
            PropertiesDialog(self.current.drive, self).exec()


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("classic7-computer")
    app.setDesktopFileName("classic7-computer")
    w = ComputerWindow()
    w.show()
    return app.exec()
