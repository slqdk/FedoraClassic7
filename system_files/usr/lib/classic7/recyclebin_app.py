"""Recycle Bin, as in Windows 7: the deleted files with Original Location and Date Deleted,
"Empty the Recycle Bin", "Restore all items" / "Restore this item", Delete for good, and the
details bar. It reads the freedesktop.org trash that Dolphin, the desktop and other programs use
(~/.local/share/Trash and the .Trash-<uid> folders on other drives).

    classic7-recyclebin            the window
    classic7-recyclebin FILE...    move files to the Recycle Bin (dropping files on the desktop icon)
    classic7-recyclebin --empty    empty it (asks first)
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QMimeDatabase, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QLinearGradient, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


APP = "Recycle Bin"
UID = os.getuid()
MARK = "X-Classic7-RecycleBin=true"       # Classic 7's Recycle Bin icon on the desktop
_mime = None


def home_trash() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "Trash"


def trash_dirs() -> list[tuple[Path, Path | None]]:
    """(trash folder, top of the drive for relative paths) for the home trash and other drives."""
    out = [(home_trash(), None)]
    seen = {home_trash().resolve() if home_trash().exists() else home_trash()}
    try:
        mounts = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        mounts = []
    for line in mounts:
        parts = line.split()
        if len(parts) < 5:
            continue
        top = Path(parts[4].replace("\\040", " "))
        if str(top).startswith(("/proc", "/sys", "/dev", "/run/user")):
            continue
        for cand in (top / ".Trash" / str(UID), top / f".Trash-{UID}"):
            try:
                if cand.is_dir() and (cand / "info").is_dir():
                    key = cand.resolve()
                    if key not in seen:
                        seen.add(key)
                        out.append((cand, top))
            except OSError:
                continue
    return out


@dataclass
class TrashItem:
    trash: Path
    top: Path | None
    name: str                 # name inside files/ and info/
    original: Path
    deleted: dt.datetime | None
    size: int = -1
    is_dir: bool = False

    @property
    def file(self) -> Path:
        return self.trash / "files" / self.name

    @property
    def info(self) -> Path:
        return self.trash / "info" / f"{self.name}.trashinfo"

    def type_name(self) -> str:
        global _mime
        if self.is_dir:
            return "File folder"
        _mime = _mime or QMimeDatabase()
        m = _mime.mimeTypeForFile(str(self.file))
        return m.comment() or m.name()

    def icon(self) -> QIcon:
        global _mime
        if self.is_dir:
            return QIcon.fromTheme("folder")
        _mime = _mime or QMimeDatabase()
        ic = QIcon.fromTheme(_mime.mimeTypeForFile(str(self.file)).iconName())
        return ic if not ic.isNull() else QIcon.fromTheme("text-x-generic")


def read_items() -> list[TrashItem]:
    items = []
    for trash, top in trash_dirs():
        info_dir = trash / "info"
        try:
            infos = list(info_dir.iterdir())
        except OSError:
            continue
        for info in infos:
            if info.suffix != ".trashinfo":
                continue
            name = info.name[: -len(".trashinfo")]
            path, date = None, None
            try:
                for line in info.read_text(errors="replace").splitlines():
                    if line.startswith("Path="):
                        path = urllib.parse.unquote(line[5:])
                    elif line.startswith("DeletionDate="):
                        try:
                            date = dt.datetime.fromisoformat(line[13:].strip())
                        except ValueError:
                            date = None
            except OSError:
                continue
            if path is None:
                continue
            original = Path(path)
            if not original.is_absolute() and top is not None:
                original = top / original
            f = trash / "files" / name
            if not f.exists() and not f.is_symlink():
                continue
            items.append(TrashItem(trash, top, name, original, date, -1, f.is_dir() and not f.is_symlink()))
    return items


def trash_is_empty() -> bool:
    """As KDE's trash decides it: nothing in any info folder."""
    for trash, _top in trash_dirs():
        try:
            with os.scandir(trash / "info") as it:
                for _entry in it:
                    return False
        except OSError:
            continue
    return True


def desktop_dir() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=3).stdout.strip()
        if out and Path(out) != Path.home():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def update_desktop_icon(empty: bool):
    """The desktop's Recycle Bin icon: full or empty."""
    want = "user-trash" if empty else "user-trash-full"
    try:
        files = list(desktop_dir().glob("*.desktop"))
    except OSError:
        return
    for f in files:
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if MARK not in text:
            continue
        lines, group, changed = text.splitlines(), None, False
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("[") and s.endswith("]"):
                group = s
            elif group == "[Desktop Entry]" and s.startswith("Icon=") and s != f"Icon={want}":
                lines[i] = f"Icon={want}"
                changed = True
        if changed:
            try:
                mode = f.stat().st_mode & 0o7777
                tmp = f.with_name(f".{f.name}.c7tmp")
                tmp.write_text("\n".join(lines) + "\n")
                os.chmod(tmp, mode)
                tmp.replace(f)
            except OSError:
                pass


def notify_kde():
    """Tell open trash:/ views (Explorer, the desktop) to look again, as KDE's own trash does."""
    try:
        import dbus
        import dbus.lowlevel
        bus = dbus.SessionBus()
        m = dbus.lowlevel.SignalMessage("/", "org.kde.KDirNotify", "FilesAdded")
        m.append("trash:/", signature="s")
        bus.send_message(m)
        m = dbus.lowlevel.SignalMessage("/", "org.kde.KDirNotify", "FilesChanged")
        m.append(["trash:/"], signature="as")
        bus.send_message(m)
    except Exception:  # noqa: BLE001 - no session bus: nothing to tell
        pass


def sync_state(notify: bool = True):
    """After a change: KDE's own record of whether the trash is empty (its icons read it), the
    desktop's Recycle Bin icon, and the open trash views."""
    empty = trash_is_empty()
    try:
        subprocess.run(["kwriteconfig6", "--file", "trashrc", "--group", "Status", "--key", "Empty",
                        "true" if empty else "false"], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass
    update_desktop_icon(empty)
    if notify:
        notify_kde()


def tree_size(p: Path) -> int:
    total = 0
    try:
        if p.is_symlink() or not p.is_dir():
            return p.lstat().st_size
        for root, _dirs, files in os.walk(p):
            for fn in files:
                try:
                    total += (Path(root) / fn).lstat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def fmt_size(n: int) -> str:
    if n < 0:
        return ""
    if n < 1024:
        return "1 KB" if n else "0 KB"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:,.0f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:,.1f} MB"
    return f"{mb / 1024:,.2f} GB"


def move_to_trash(paths: list[str]) -> list[str]:
    """Delete to the Recycle Bin (gio follows the same trash rules). Returns the ones that failed."""
    failed = []
    for p in paths:
        r = subprocess.run(["gio", "trash", "--", p], capture_output=True)
        if r.returncode != 0:
            failed.append(p)
    return failed


def restore(item: TrashItem, overwrite: bool = False) -> str | None:
    """Put an item back where it came from. Returns an error text, or None."""
    dest = item.original
    if dest.exists() or dest.is_symlink():
        if not overwrite:
            return "exists"
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.file), str(dest))
        item.info.unlink(missing_ok=True)
    except OSError as e:
        return e.strerror or str(e)
    _forget_size(item)
    return None


def delete_forever(item: TrashItem) -> str | None:
    try:
        if item.file.is_dir() and not item.file.is_symlink():
            shutil.rmtree(item.file)
        else:
            item.file.unlink(missing_ok=True)
        item.info.unlink(missing_ok=True)
    except OSError as e:
        return e.strerror or str(e)
    _forget_size(item)
    return None


def _forget_size(item: TrashItem):
    """Keep the trash's directorysizes cache in step (the spec's optional cache)."""
    cache = item.trash / "directorysizes"
    try:
        lines = cache.read_text().splitlines()
    except OSError:
        return
    enc = urllib.parse.quote(item.name)
    keep = [ln for ln in lines if ln.split(" ")[-1] != enc]
    if len(keep) != len(lines):
        try:
            cache.write_text("\n".join(keep) + ("\n" if keep else ""))
        except OSError:
            pass


class SizeWorker(QThread):
    sized = Signal(str, int)          # info path, size

    def __init__(self, items: list[TrashItem]):
        super().__init__()
        self.items = items

    def run(self):
        for it in self.items:
            if self.isInterruptionRequested():
                return
            self.sized.emit(str(it.info), tree_size(it.file))


class CommandBar(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(32)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(6, 2, 6, 2)
        self.lay.setSpacing(2)

    def button(self, text: str, slot=None, menu=None, icon_name="") -> QToolButton:
        b = QToolButton()
        b.setText(text)
        if icon_name:
            b.setIcon(QIcon.fromTheme(icon_name))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setAutoRaise(True)
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


class Details(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 14, 6)
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


class SortItem(QTreeWidgetItem):
    def __lt__(self, other):
        tree = self.treeWidget()
        col = tree.sortColumn() if tree else 0
        a, b = self.data(col, Qt.UserRole + 1), other.data(col, Qt.UserRole + 1)
        if a is not None and b is not None:
            return a < b
        return self.text(col).lower() < other.text(col).lower()


class RecycleBin(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon.fromTheme("user-trash-full"))
        self.resize(900, 560)
        self.items: list[TrashItem] = []
        self.sizer: SizeWorker | None = None
        nav = QToolBar("Navigation")
        nav.setMovable(False)
        nav.setIconSize(QSize(22, 22))
        nav.addAction(QIcon.fromTheme("go-previous"), "Back").setEnabled(False)
        nav.addAction(QIcon.fromTheme("go-next"), "Forward").setEnabled(False)
        self.address = QLineEdit("  ▸ Recycle Bin")
        self.address.setReadOnly(True)
        self.address.addAction(QIcon.fromTheme("user-trash-full"), QLineEdit.LeadingPosition)
        nav.addWidget(self.address)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Recycle Bin")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._filter)
        nav.addWidget(self.search)
        self.addToolBar(Qt.TopToolBarArea, nav)
        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.bar = CommandBar()
        org = QMenu(self)
        org.addAction("Select all", lambda: self.tree.selectAll(), QKeySequence("Ctrl+A"))
        org.addSeparator()
        org.addAction("Delete", self.delete_selected)
        org.addAction("Properties", self.properties)
        org.addSeparator()
        org.addAction("Close", self.close)
        self.bar.button("Organize ▾", menu=org)
        self.empty_btn = self.bar.button("Empty the Recycle Bin", self.empty, icon_name="trash-empty")
        self.restore_btn = self.bar.button("Restore all items", self.restore_clicked, icon_name="edit-undo")
        self.bar.lay.addStretch(1)
        v.addWidget(self.bar)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setHeaderLabels(["Name", "Original Location", "Date Deleted", "Size", "Item type",
                                   "Date modified"])
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(2, Qt.DescendingOrder)
        self.tree.setFrameStyle(QFrame.NoFrame)
        self.tree.setIconSize(QSize(16, 16))
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Interactive)
        for col, w in ((0, 220), (1, 230), (2, 130), (3, 80), (4, 140), (5, 130)):
            h.resizeSection(col, w)
        self.tree.itemSelectionChanged.connect(self._selection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.properties())
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.tree, 1)
        self.details = Details()
        v.addWidget(self.details)
        self.setCentralWidget(central)
        QShortcut(QKeySequence("Delete"), self, self.delete_selected)
        QShortcut(QKeySequence("F5"), self, self.refresh)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _p: self._debounce.start())
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self.refresh)
        self.setAcceptDrops(True)
        self.refresh()

    # ---- data -------------------------------------------------------------------------------
    def refresh(self):
        selected = {it.data(0, Qt.UserRole).name for it in self.tree.selectedItems()} if self.tree.topLevelItemCount() \
            else set()
        self.items = read_items()
        for d in self.watcher.directories():
            self.watcher.removePath(d)
        for trash, _top in trash_dirs():
            if (trash / "info").is_dir():
                self.watcher.addPath(str(trash / "info"))
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        for item in self.items:
            mod = None
            try:
                mod = dt.datetime.fromtimestamp(item.file.lstat().st_mtime)
            except OSError:
                pass
            row = SortItem([item.original.name, str(item.original.parent),
                            item.deleted.strftime("%d-%m-%Y %H:%M") if item.deleted else "", "",
                            item.type_name(), mod.strftime("%d-%m-%Y %H:%M") if mod else ""])
            row.setIcon(0, item.icon())
            row.setData(0, Qt.UserRole, item)
            row.setData(2, Qt.UserRole + 1, item.deleted.timestamp() if item.deleted else 0)
            row.setData(3, Qt.UserRole + 1, -1)
            row.setData(5, Qt.UserRole + 1, mod.timestamp() if mod else 0)
            row.setTextAlignment(3, Qt.AlignRight | Qt.AlignVCenter)
            self.tree.addTopLevelItem(row)
            if item.name in selected:
                row.setSelected(True)
        self.tree.setSortingEnabled(True)
        self._filter(self.search.text())
        self._selection()
        if self.sizer is not None:
            self.sizer.requestInterruption()
            self.sizer.wait(2000)
        self.sizer = SizeWorker(list(self.items))
        self.sizer.sized.connect(self._sized)
        self.sizer.start()

    def _sized(self, info: str, size: int):
        for i in range(self.tree.topLevelItemCount()):
            row = self.tree.topLevelItem(i)
            it = row.data(0, Qt.UserRole)
            if str(it.info) == info:
                it.size = size
                row.setText(3, fmt_size(size))
                row.setData(3, Qt.UserRole + 1, size)
                break
        self._selection()

    def _filter(self, text: str):
        t = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            row = self.tree.topLevelItem(i)
            row.setHidden(bool(t) and t not in row.text(0).lower())

    def selected(self) -> list[TrashItem]:
        return [r.data(0, Qt.UserRole) for r in self.tree.selectedItems()]

    def _selection(self):
        sel = self.selected()
        n = len(self.items)
        self.empty_btn.setEnabled(n > 0)
        self.restore_btn.setEnabled(n > 0)
        if not sel:
            self.restore_btn.setText("Restore all items")
            self.details.icon.setPixmap(QIcon.fromTheme("user-trash-full" if n else "user-trash").pixmap(48, 48))
            self.details.text.setText(f"<span style='font-size:13px'>{n} item{'s' if n != 1 else ''}</span>")
        elif len(sel) == 1:
            it = sel[0]
            self.restore_btn.setText("Restore this item")
            self.details.icon.setPixmap(it.icon().pixmap(48, 48))
            self.details.text.setText(
                f"<b>{_esc(it.original.name)}</b>&nbsp;&nbsp;<span style='color:#555'>{_esc(it.type_name())}</span><br>"
                f"<span style='color:#555'>Original location:</span> {_esc(str(it.original.parent))}&nbsp;&nbsp;"
                f"<span style='color:#555'>Size:</span> {fmt_size(it.size) or 'Calculating...'}")
        else:
            total = sum(max(0, it.size) for it in sel)
            self.restore_btn.setText("Restore the selected items")
            self.details.icon.setPixmap(QIcon.fromTheme("document-multiple").pixmap(48, 48))
            self.details.text.setText(f"{len(sel)} items selected<br><span style='color:#555'>Size:</span> "
                                      f"{fmt_size(total)}")

    # ---- actions -----------------------------------------------------------------------------
    def _menu(self, pos):
        if not self.selected():
            return
        m = QMenu(self)
        m.addAction("Restore", self.restore_clicked)
        m.addSeparator()
        m.addAction("Cut", self.restore_clicked).setEnabled(False)
        m.addAction("Delete", self.delete_selected)
        m.addSeparator()
        m.addAction("Properties", self.properties)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def restore_clicked(self):
        items = self.selected() or list(self.items)
        if not items:
            return
        replace_all = None
        errors = []
        for it in items:
            err = restore(it)
            if err == "exists":
                if replace_all is None:
                    box = QMessageBox(QMessageBox.Question, "Move File",
                                      f"There is already a file with the same name in this location:\n\n"
                                      f"{it.original}\n\nDo you want to replace it with the one from the Recycle Bin?",
                                      QMessageBox.Yes | QMessageBox.No, self)
                    if len(items) > 1:
                        box.addButton(QMessageBox.YesToAll)
                        box.addButton(QMessageBox.NoToAll)
                    r = box.exec()
                    if r == QMessageBox.YesToAll:
                        replace_all = True
                    elif r == QMessageBox.NoToAll:
                        replace_all = False
                    if r not in (QMessageBox.Yes, QMessageBox.YesToAll):
                        continue
                elif not replace_all:
                    continue
                err = restore(it, overwrite=True)
            if err and err != "exists":
                errors.append(f"{it.original.name}: {err}")
        if errors:
            QMessageBox.warning(self, APP, "Some items could not be restored:\n\n" + "\n".join(errors[:10]))
        sync_state()
        self.refresh()

    def delete_selected(self):
        items = self.selected()
        if not items:
            return
        if len(items) == 1:
            kind = "folder" if items[0].is_dir else "file"
            text = f"Are you sure you want to permanently delete this {kind}?\n\n{items[0].original.name}"
        else:
            text = f"Are you sure you want to permanently delete these {len(items)} items?"
        title = "Delete Folder" if len(items) == 1 and items[0].is_dir else (
            "Delete File" if len(items) == 1 else "Delete Multiple Items")
        if QMessageBox.warning(self, title, text, QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        errors = [f"{it.original.name}: {e}" for it in items if (e := delete_forever(it))]
        if errors:
            QMessageBox.warning(self, APP, "\n".join(errors[:10]))
        sync_state()
        self.refresh()

    def empty(self):
        n = len(self.items)
        if not n:
            return
        text = (f"Are you sure you want to permanently delete \"{self.items[0].original.name}\"?" if n == 1 else
                f"Are you sure you want to permanently delete these {n} items?")
        if QMessageBox.warning(self, "Delete Multiple Items" if n > 1 else "Delete File", text,
                               QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for it in list(self.items):
                delete_forever(it)
        finally:
            QApplication.restoreOverrideCursor()
        sync_state()
        self.refresh()

    def properties(self):
        items = self.selected()
        if len(items) != 1:
            return
        import properties_app
        dlg = properties_app.PropertiesDialog([items[0].file], self)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.show()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            move_to_trash(paths)
            sync_state()
            self.refresh()

    def closeEvent(self, e):
        if self.sizer is not None:
            self.sizer.requestInterruption()
            self.sizer.wait(2000)
        super().closeEvent(e)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n", 1)[1].strip())
        return 0
    files = [a for a in argv if not a.startswith("-")]
    if files:
        from urllib.parse import urlparse, unquote
        paths = [unquote(urlparse(f).path) if f.startswith("file://") else f for f in files]
        failed = move_to_trash(paths)
        sync_state()
        return 1 if failed else 0
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-recyclebin")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-recyclebin")
    w = RecycleBin()
    if "--empty" in argv:
        w.empty()
        if w.sizer is not None:
            w.sizer.requestInterruption()
            w.sizer.wait(3000)
        return 0
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
