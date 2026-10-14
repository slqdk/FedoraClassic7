"""Properties, as in Windows 7.

    classic7-properties PATH...

A file gets General, Security and Details; a folder General, Security and Customize; a shortcut
(.desktop) General, Shortcut, Security and Details; a drive (the top folder of a mounted disk)
General, Tools and Security; an item in the Recycle Bin shows where it came from and when it was
deleted. Several items at once share one General tab. The desktop's Computer icon opens the
System window instead, as in Windows 7.

Explorer (Dolphin), the desktop and other KDE programs open this window instead of KDE's own
Properties for one item on this computer, through the plugin in build_files/native/properties.cpp.

Linux has no Windows attributes, so: Read-only is the owner's write permission, Hidden is a name
in the folder's .hidden file (Explorer and the desktop hide those), and the Security tab shows the
owner, the group and everyone else with the Windows permission names."""
from __future__ import annotations

import grp
import os
import pwd
import shlex
import socket
import stat
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDateTime, QFileInfo, QLocale, QMimeDatabase, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

APP = "Properties"
LABEL_W = 88            # the label column of the General tab
_mimedb: QMimeDatabase | None = None


def mimedb() -> QMimeDatabase:
    global _mimedb
    if _mimedb is None:
        _mimedb = QMimeDatabase()
    return _mimedb


def themed(*names: str) -> QIcon:
    for n in names:
        if n:
            ic = QIcon.fromTheme(n) if not n.startswith("/") else QIcon(n)
            if not ic.isNull():
                return ic
    return QIcon.fromTheme("unknown")


# ---- text the Windows way -------------------------------------------------------------------
def short_size(n: int) -> str:
    """Explorer's short form: three significant digits, cut off rather than rounded."""
    if n < 1024:
        return f"{n:,} bytes"
    units = ["KB", "MB", "GB", "TB", "PB"]
    v, i = n / 1024, 0
    while v >= 1000 and i < len(units) - 1:
        v /= 1024
        i += 1
    if v >= 100:
        s = f"{int(v)}"
    elif v >= 10:
        s = f"{int(v * 10) / 10:.1f}"
    else:
        s = f"{int(v * 100) / 100:.2f}"
    return f"{s} {units[i]}"


def size_text(n: int) -> str:
    """'1.25 KB (1,285 bytes)', as the General tab shows sizes."""
    return f"{short_size(n)} ({n:,} bytes)"


def date_text(ts: float | None) -> str:
    if ts is None:
        return ""
    loc = QLocale()
    d = QDateTime.fromSecsSinceEpoch(int(ts))
    tf = loc.timeFormat(QLocale.LongFormat).replace(" t", "").replace("t", "").strip()
    return f"{loc.toString(d.date(), QLocale.LongFormat)}, {loc.toString(d.time(), tf)}"


def date_short(ts: float | None) -> str:
    """The Details tab's short form, as Explorer's columns show dates."""
    if ts is None:
        return ""
    return QLocale().toString(QDateTime.fromSecsSinceEpoch(int(ts)), QLocale.ShortFormat)


def birth_time(path: str) -> float | None:
    bt = QFileInfo(path).birthTime()
    return bt.toSecsSinceEpoch() if bt.isValid() else None


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def user_name(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def group_name(gid: int) -> str:
    try:
        return grp.getgrgid(gid).gr_name
    except KeyError:
        return str(gid)


def full_name(uid: int) -> str:
    try:
        g = pwd.getpwuid(uid).pw_gecos.split(",")[0].strip()
        return g
    except KeyError:
        return ""


# ---- desktop files and default programs ---------------------------------------------------
def read_desktop(path: str | Path) -> dict[str, dict[str, str]]:
    """A .desktop file as {group: {key: value}} (no locale handling beyond plain keys)."""
    groups: dict[str, dict[str, str]] = {}
    cur = None
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return groups
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            cur = groups.setdefault(line[1:-1], {})
        elif cur is not None and "=" in line:
            k, v = line.split("=", 1)
            cur.setdefault(k.strip(), v.strip())
    return groups


def write_desktop_keys(path: Path, changes: dict[str, str | None], group: str = "Desktop Entry"):
    """Set (or with None remove) keys in one group of a .desktop file, keeping everything else."""
    lines = path.read_text(errors="replace").splitlines()
    out, cur, done = [], None, set()
    start = end = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            if cur == group:
                end = len(out)
            cur = s[1:-1]
            if cur == group:
                start = len(out) + 1
            out.append(line)
            continue
        if cur == group and "=" in s and not s.startswith("#"):
            k = s.split("=", 1)[0].strip()
            if k in changes:
                done.add(k)
                if changes[k] is not None:
                    out.append(f"{k}={changes[k]}")
                continue
        out.append(line)
    if cur == group and end is None:
        end = len(out)
    if start is None:
        out = [f"[{group}]"] + out
        end = 1
    # new keys at the end of the group (before blank lines that separate groups)
    while end > 0 and not out[end - 1].strip():
        end -= 1
    new = [f"{k}={v}" for k, v in changes.items() if k not in done and v is not None]
    out[end:end] = new
    mode = path.stat().st_mode
    tmp = path.with_name(f".{path.name}.c7tmp")
    tmp.write_text("\n".join(out) + "\n")
    os.chmod(tmp, stat.S_IMODE(mode))
    tmp.replace(path)


def data_dirs() -> list[Path]:
    home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    dirs = [home] + [Path(d) for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    for extra in (Path.home() / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share")):
        if extra not in dirs:
            dirs.append(extra)
    return dirs


def find_desktop_file(desktop_id: str) -> Path | None:
    for d in data_dirs():
        p = d / "applications" / desktop_id
        if p.is_file():
            return p
        # vendor-prefixed ids map to subfolders (kde-foo.desktop -> kde/foo.desktop)
        if "-" in desktop_id:
            q = d / "applications" / desktop_id.replace("-", "/", 1)
            if q.is_file():
                return q
    return None


def mimeapps_files() -> list[Path]:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    files = [cfg / "kde-mimeapps.list", cfg / "mimeapps.list"]
    files += [Path(d) / "mimeapps.list" for d in (os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":") if d]
    files += [d / "applications" / "mimeapps.list" for d in data_dirs()]
    return files


def _list_value(text: str, group: str, key: str) -> list[str]:
    cur = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
        elif cur == group and s.startswith(key + "="):
            return [x for x in s.split("=", 1)[1].split(";") if x]
    return []


@dataclass
class App:
    desktop_id: str
    name: str
    icon: str
    exec_: str
    path: Path


def app_info(desktop_id: str) -> App | None:
    p = find_desktop_file(desktop_id)
    if p is None:
        return None
    e = read_desktop(p).get("Desktop Entry", {})
    if e.get("Type", "Application") != "Application":
        return None
    return App(desktop_id, e.get("Name", desktop_id.removesuffix(".desktop")), e.get("Icon", ""), e.get("Exec", ""), p)


def default_app(mime: str) -> App | None:
    """The program that opens this type (mimeapps.list in the XDG order, then the parent types,
    then the first program that says it can)."""
    m = mimedb().mimeTypeForName(mime)
    texts = []
    for f in mimeapps_files():
        try:
            texts.append(f.read_text(errors="replace"))
        except OSError:
            continue

    def chosen(t: str) -> App | None:
        for text in texts:
            for did in _list_value(text, "Default Applications", t):
                a = app_info(did)
                if a:
                    return a
        return None
    # the type's own default, a program made for the type, then the same for the types it is a kind of
    a = chosen(mime) or next(iter(apps_for(mime)), None)
    if a:
        return a
    for t in (list(m.allAncestors()) if m.isValid() else []):
        a = chosen(t) or next(iter(apps_for(t)), None)
        if a:
            return a
    return None


_all_apps: list[App] | None = None


def all_apps() -> list[App]:
    global _all_apps
    if _all_apps is not None:
        return _all_apps
    seen: dict[str, App] = {}
    for d in data_dirs():
        base = d / "applications"
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.desktop")):
            did = str(p.relative_to(base)).replace("/", "-")
            if did in seen:
                continue
            e = read_desktop(p).get("Desktop Entry", {})
            seen[did] = None  # type: ignore[assignment] - placeholder so later dirs don't override
            if e.get("Type") != "Application" or e.get("Hidden") == "true" or not e.get("Exec"):
                continue
            a = App(did, e.get("Name", did), e.get("Icon", ""), e.get("Exec", ""), p)
            a.mimes = [x for x in e.get("MimeType", "").split(";") if x]  # type: ignore[attr-defined]
            a.nodisplay = e.get("NoDisplay") == "true"  # type: ignore[attr-defined]
            seen[did] = a
    _all_apps = sorted((a for a in seen.values() if a), key=lambda a: a.name.lower())
    return _all_apps


def apps_for(mime: str) -> list[App]:
    return [a for a in all_apps() if mime in getattr(a, "mimes", [])]


def set_default_app(mime: str, desktop_id: str) -> str | None:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = cfg / "mimeapps.list"
    try:
        text = path.read_text(errors="replace") if path.exists() else ""
    except OSError as e:
        return str(e)
    lines = text.splitlines()

    def put(group: str, value_fn):
        nonlocal lines
        gi = next((i for i, ln in enumerate(lines) if ln.strip() == f"[{group}]"), None)
        if gi is None:
            if lines and lines[-1].strip():
                lines.append("")
            lines += [f"[{group}]", f"{mime}={value_fn([])}"]
            return
        end = next((i for i in range(gi + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        for i in range(gi + 1, end):
            if lines[i].strip().startswith(mime + "="):
                old = [x for x in lines[i].split("=", 1)[1].split(";") if x]
                lines[i] = f"{mime}={value_fn(old)}"
                return
        ins = end
        while ins > gi + 1 and not lines[ins - 1].strip():
            ins -= 1
        lines.insert(ins, f"{mime}={value_fn([])}")

    put("Default Applications", lambda _old: desktop_id + ";")
    put("Added Associations", lambda old: ";".join([desktop_id] + [x for x in old if x != desktop_id]) + ";")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".c7tmp")
        tmp.write_text("\n".join(lines) + "\n")
        tmp.replace(path)
    except OSError as e:
        return str(e)
    return None


# ---- attributes -----------------------------------------------------------------------------
def hidden_list(folder: Path) -> list[str]:
    try:
        return [ln for ln in (folder / ".hidden").read_text(errors="replace").splitlines() if ln]
    except OSError:
        return []


def is_hidden(p: Path) -> bool:
    return p.name.startswith(".") or p.name in hidden_list(p.parent)


def set_hidden(p: Path, on: bool) -> str | None:
    if p.name.startswith("."):
        return None if on else f"{p.name} starts with a dot, so it stays hidden. Rename it to show it."
    names = hidden_list(p.parent)
    if on and p.name not in names:
        names.append(p.name)
    elif not on:
        names = [n for n in names if n != p.name]
    hf = p.parent / ".hidden"
    try:
        if names:
            hf.write_text("\n".join(names) + "\n")
        elif hf.exists():
            hf.unlink()
    except OSError as e:
        return f"Unable to change the Hidden attribute of {p.name}: {e.strerror or e}"
    return None


def is_read_only(p: Path) -> bool:
    try:
        st = p.stat()
    except OSError:
        return False
    if st.st_uid == os.getuid():
        return not st.st_mode & stat.S_IWUSR
    return not os.access(p, os.W_OK)


def set_read_only(p: Path, on: bool) -> str | None:
    try:
        mode = stat.S_IMODE(p.stat().st_mode)
        new = mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) if on else mode | stat.S_IWUSR
        if new != mode:
            os.chmod(p, new)
    except OSError as e:
        return f"Unable to change the attributes of {p.name}. {e.strerror or e}"
    return None


# ---- what is being looked at ----------------------------------------------------------------
@dataclass
class TrashInfo:
    original: Path
    deleted: float | None


def trash_info(p: Path) -> TrashInfo | None:
    """For a file inside a Recycle Bin folder (…/Trash/files/NAME): where it came from, and when."""
    if p.parent.name != "files" or not p.parent.parent.name.startswith((".Trash", "Trash")):
        return None
    info = p.parent.parent / "info" / f"{p.name}.trashinfo"
    try:
        text = info.read_text(errors="replace")
    except OSError:
        return None
    orig, deleted = None, None
    for line in text.splitlines():
        if line.startswith("Path="):
            orig = urllib.parse.unquote(line[5:])
        elif line.startswith("DeletionDate="):
            try:
                deleted = time.mktime(time.strptime(line[13:].strip()[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                deleted = None
    if not orig:
        return None
    op = Path(orig)
    if not op.is_absolute():       # relative to the top of the drive the trash folder is on
        top = p.parent.parent.parent if p.parent.parent.name.startswith(".Trash-") else p.parent.parent.parent.parent
        op = top / op
    return TrashInfo(op, deleted)


def is_drive(p: Path) -> bool:
    try:
        return p.is_dir() and not p.is_symlink() and os.path.ismount(p)
    except OSError:
        return False


def kind_of(p: Path) -> str:
    if trash_info(p) is not None:
        return "trash"
    if p.is_symlink() and not p.exists():
        return "file"
    if p.suffix == ".desktop" and p.is_file():
        t = read_desktop(p).get("Desktop Entry", {}).get("Type", "")
        if t in ("Application", "Link"):
            return "shortcut"
    if is_drive(p):
        return "drive"
    if p.is_dir():
        return "folder"
    return "file"


def icon_for(p: Path) -> QIcon:
    if p.suffix == ".desktop" and p.is_file():
        e = read_desktop(p).get("Desktop Entry", {})
        if e.get("Icon"):
            return themed(e["Icon"], "application-x-executable")
    if p.is_dir() and not p.is_symlink():
        d = read_desktop(p / ".directory").get("Desktop Entry", {})
        if d.get("Icon"):
            return themed(d["Icon"], "folder")
        if is_drive(p):
            return themed("drive-harddisk")
        home = Path.home()
        special = {home: "user-home", home / "Desktop": "user-desktop", home / "Documents": "folder-documents",
                   home / "Downloads": "folder-download", home / "Music": "folder-music",
                   home / "Pictures": "folder-pictures", home / "Videos": "folder-videos"}
        return themed(special.get(p, "folder"), "folder")
    m = mimedb().mimeTypeForFile(str(p))
    return themed(m.iconName(), m.genericIconName(), "text-x-generic")


def type_text(p: Path) -> str:
    if p.is_dir() and not p.is_symlink():
        return "File folder"
    m = mimedb().mimeTypeForFile(str(p))
    comment = m.comment() or m.name()
    if p.suffix == ".desktop":
        return "Shortcut (.desktop)"
    suffix = mimedb().suffixForFileName(str(p)) or (p.suffix[1:] if p.suffix else "")
    return f"{comment} (.{suffix})" if suffix else comment


# ---- folder sizes in the background ---------------------------------------------------------
class SizeCounter(QThread):
    progress = Signal(object)          # (size, size on disk, files, folders, done)

    def __init__(self, paths: list[Path], count_roots: bool):
        super().__init__()
        self.paths = paths
        self.count_roots = count_roots

    def run(self):
        size = disk = files = folders = 0
        seen: set[tuple[int, int]] = set()
        roots = {str(p) for p in self.paths}
        stack = [str(p) for p in self.paths]
        last = time.monotonic()
        while stack:
            if self.isInterruptionRequested():
                return
            path = stack.pop()
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if stat.S_ISDIR(st.st_mode):
                if path not in roots or self.count_roots:
                    folders += 1
                try:
                    with os.scandir(path) as it:
                        stack.extend(e.path for e in it)
                except OSError:
                    pass
            else:
                files += 1
                if st.st_nlink > 1:
                    key = (st.st_dev, st.st_ino)
                    if key in seen:
                        continue
                    seen.add(key)
                size += st.st_size
                disk += st.st_blocks * 512
            now = time.monotonic()
            if now - last > 0.15:
                last = now
                self.progress.emit((size, disk, files, folders, False))
        self.progress.emit((size, disk, files, folders, True))


# ---- small widgets --------------------------------------------------------------------------
def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def value_label(text: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    lab.setWordWrap(False)
    lab.setMinimumWidth(10)
    return lab


class Page(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.dirty = False

    def mark(self, *_):
        self.dirty = True
        self.changed.emit()

    def apply(self) -> str | None:     # an error message, or None
        self.dirty = False
        return None

    def stop(self):
        pass


class Grid:
    """The General tab's two-column rows with separator lines between groups."""

    def __init__(self, layout: QVBoxLayout):
        self.outer = layout
        self.grid: QGridLayout | None = None
        self.row = 0

    def _ensure(self):
        if self.grid is None:
            self.grid = QGridLayout()
            self.grid.setHorizontalSpacing(8)
            self.grid.setVerticalSpacing(7)
            self.grid.setColumnMinimumWidth(0, LABEL_W)
            self.grid.setColumnStretch(1, 1)
            self.outer.addLayout(self.grid)
            self.row = 0

    def add(self, label: str | QWidget, widget: QWidget | str) -> QWidget:
        self._ensure()
        w = value_label(widget) if isinstance(widget, str) else widget
        if isinstance(label, str):
            lab = QLabel(label)
            lab.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        else:
            lab = label
        self.grid.addWidget(lab, self.row, 0)
        self.grid.addWidget(w, self.row, 1)
        self.row += 1
        return w

    def sep(self):
        self.grid = None
        self.outer.addSpacing(2)
        self.outer.addWidget(hline())
        self.outer.addSpacing(2)


def name_row(icon: QIcon, text: str, editable: bool) -> tuple[QHBoxLayout, QLineEdit]:
    row = QHBoxLayout()
    pic = QLabel()
    pic.setPixmap(icon.pixmap(32, 32))
    pic.setFixedSize(LABEL_W, 36)
    row.addWidget(pic)
    edit = QLineEdit(text)
    edit.setReadOnly(not editable)
    row.addWidget(edit, 1)
    return row, edit


# ---- General -------------------------------------------------------------------------------
class GeneralPage(Page):
    """One file, folder, shortcut or Recycle Bin item."""

    def __init__(self, path: Path, kind: str):
        super().__init__()
        self.path = path
        self.kind = kind
        self.counter: SizeCounter | None = None
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        trash = trash_info(path) if kind == "trash" else None
        display = trash.original.name if trash else path.name or str(path)
        row, self.name = name_row(icon_for(path), display, kind not in ("trash",) and bool(path.name))
        self.name.textEdited.connect(self.mark)
        v.addLayout(row)
        g = Grid(v)
        g.sep()
        try:
            st = path.lstat()
        except OSError:
            st = None
        is_dir = path.is_dir() and not path.is_symlink()
        if trash:
            g.add("Origin:", str(trash.original.parent))
            g.add("Type:", type_text(path))
        elif is_dir:
            g.add("Type:", "File folder")
            g.add("Location:", str(path.parent))
        else:
            g.add("Type of file:", type_text(path))
            if kind == "shortcut":
                e = read_desktop(path).get("Desktop Entry", {})
                g.add("Description:", e.get("Comment") or e.get("Name", ""))
            else:
                self._opens_with(g)
            if path.is_symlink():
                try:
                    g.add("Target:", os.readlink(path))
                except OSError:
                    pass
            g.sep()
            g.add("Location:", str(path.parent))
        self.size = g.add("Size:", "")
        self.disk = g.add("Size on disk:", "")
        if is_dir:
            self.contains = g.add("Contains:", "")
        g.sep()
        if st is not None:
            g.add("Created:", date_text(birth_time(str(path))) or "Unknown")
            if not is_dir or trash:
                g.add("Modified:", date_text(st.st_mtime))
                g.add("Accessed:", date_text(st.st_atime))
        if trash:
            g.add("Deleted:", date_text(trash.deleted) or "Unknown")
        if not trash:
            g.sep()
            attrs = QWidget()
            al = QGridLayout(attrs)
            al.setContentsMargins(0, 0, 0, 0)
            al.setHorizontalSpacing(14)
            self.ro = QCheckBox("Read-only (Only applies to files in folder)" if is_dir else "Read-only")
            self.hid = QCheckBox("Hidden")
            self.ro.setChecked(is_read_only(path))
            self.hid.setChecked(is_hidden(path))
            self.hid.setEnabled(not path.name.startswith(".") and bool(path.name))
            self.ro_start, self.hid_start = self.ro.isChecked(), self.hid.isChecked()
            self.ro.toggled.connect(self.mark)
            self.hid.toggled.connect(self.mark)
            if is_dir:
                al.addWidget(self.ro, 0, 0)
                al.addWidget(self.hid, 1, 0)
            else:
                al.addWidget(self.ro, 0, 0)
                al.addWidget(self.hid, 0, 1)
                al.setColumnStretch(2, 1)
            g.add("Attributes:", attrs)
        v.addStretch(1)
        if is_dir:
            self.size.setText("Calculating...")
            self.counter = SizeCounter([path], False)
            self.counter.progress.connect(self._counted)
            self.counter.start()
        elif st is not None:
            self.size.setText(size_text(st.st_size))
            self.disk.setText(size_text(st.st_blocks * 512))

    def _opens_with(self, g: Grid):
        mime = mimedb().mimeTypeForFile(str(self.path)).name()
        self.mime = mime
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        self.app_icon = QLabel()
        self.app_name = QLabel()
        h.addWidget(self.app_icon)
        h.addWidget(self.app_name, 1)
        change = QPushButton("Change...")
        change.clicked.connect(self._change_app)
        h.addWidget(change)
        g.add("Opens with:", w)
        self._show_app(default_app(mime))

    def _show_app(self, a: App | None):
        if a is None:
            self.app_icon.clear()
            self.app_name.setText("Unknown application")
            return
        self.app_icon.setPixmap(themed(a.icon, "application-x-executable").pixmap(16, 16))
        self.app_name.setText(self.app_name.fontMetrics().elidedText(a.name, Qt.ElideRight, 170))
        self.app_name.setToolTip(a.name)

    def _change_app(self):
        dlg = OpenWithDialog(self, self.path, self.mime)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            err = set_default_app(self.mime, dlg.chosen.desktop_id)
            if err:
                QMessageBox.warning(self, APP, f"The program could not be set as the default: {err}")
            self._show_app(dlg.chosen)

    def _counted(self, r):
        size, disk, files, folders, _done = r
        self.size.setText(size_text(size))
        self.disk.setText(size_text(disk))
        self.contains.setText(f"{files:,} Files, {folders:,} Folders")

    def stop(self):
        if self.counter is not None:
            self.counter.requestInterruption()
            self.counter.wait(2000)

    def apply(self) -> str | None:
        errors = []
        if hasattr(self, "ro") and self.ro.isChecked() != self.ro_start:
            err = self._apply_read_only(self.ro.isChecked())
            if err:
                errors.append(err)
            else:
                self.ro_start = self.ro.isChecked()
        if hasattr(self, "hid") and self.hid.isChecked() != self.hid_start:
            err = set_hidden(self.path, self.hid.isChecked())
            if err:
                errors.append(err)
            else:
                self.hid_start = self.hid.isChecked()
        new = self.name.text().strip()
        if not self.name.isReadOnly() and new and new != self.path.name:
            err = self._rename(new)
            if err:
                errors.append(err)
        self.dirty = False
        return "\n\n".join(errors) or None

    def _apply_read_only(self, on: bool) -> str | None:
        if not (self.path.is_dir() and not self.path.is_symlink()):
            return set_read_only(self.path, on)
        box = QMessageBox(QMessageBox.Question, "Confirm Attribute Changes",
                          "You have chosen to make the following attribute change(s):\n\n"
                          f"    {'set' if on else 'clear'} read-only\n\n"
                          "Do you want to apply this change to this folder only, or do you want to apply it to "
                          "all subfolders and files as well?", QMessageBox.NoButton, self)
        only = box.addButton("Apply changes to this folder only", QMessageBox.AcceptRole)
        allb = box.addButton("Apply changes to this folder, subfolders and files", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is only:
            return set_read_only(self.path, on)
        if box.clickedButton() is allb:
            errors = []
            for root, dirs, files in os.walk(self.path):
                for name in files:
                    p = Path(root) / name
                    if not p.is_symlink():
                        e = set_read_only(p, on)
                        if e:
                            errors.append(e)
                if not on:
                    for name in dirs:
                        e = set_read_only(Path(root) / name, False)
                        if e:
                            errors.append(e)
            e = set_read_only(self.path, on)
            if e:
                errors.append(e)
            return "\n".join(errors[:8]) or None
        self.ro.setChecked(self.ro_start)
        return None

    def _rename(self, new: str) -> str | None:
        if "/" in new or new in (".", ".."):
            return "A file name can't contain a slash (/)."
        dest = self.path.with_name(new)
        if dest.exists():
            return f"There is already a file with the same name in this location: {new}"
        try:
            os.rename(self.path, dest)
        except OSError as e:
            return f"Unable to rename {self.path.name}: {e.strerror or e}"
        self.path = dest
        win = self.window()
        if isinstance(win, PropertiesDialog):
            win.renamed(dest)
        return None


class MultiPage(Page):
    """Several selected items: counts, common type and folder, total size, shared attributes."""

    def __init__(self, paths: list[Path]):
        super().__init__()
        self.paths = paths
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        nfiles = sum(1 for p in paths if not (p.is_dir() and not p.is_symlink()))
        nfolders = len(paths) - nfiles
        parts = []
        if nfiles:
            parts.append(f"{nfiles:,} File{'s' if nfiles != 1 else ''}")
        if nfolders:
            parts.append(f"{nfolders:,} Folder{'s' if nfolders != 1 else ''}")
        row, _edit = name_row(themed("document-multiple", "edit-copy"), ", ".join(parts), False)
        v.addLayout(row)
        g = Grid(v)
        g.sep()
        types = {type_text(p) for p in paths}
        g.add("Type:", f"All of type {next(iter(types))}" if len(types) == 1 else "Multiple Types")
        parents = {str(p.parent) for p in paths}
        g.add("Location:", f"All in {next(iter(parents))}" if len(parents) == 1 else "Multiple Folders")
        self.size = g.add("Size:", "Calculating...")
        self.disk = g.add("Size on disk:", "")
        g.sep()
        attrs = QWidget()
        al = QHBoxLayout(attrs)
        al.setContentsMargins(0, 0, 0, 0)
        self.ro = QCheckBox("Read-only")
        self.hid = QCheckBox("Hidden")
        for box, states in ((self.ro, [is_read_only(p) for p in paths]), (self.hid, [is_hidden(p) for p in paths])):
            if all(states):
                box.setCheckState(Qt.Checked)
            elif any(states):
                box.setTristate(True)
                box.setCheckState(Qt.PartiallyChecked)
            box.stateChanged.connect(self.mark)
            al.addWidget(box)
        al.addStretch(1)
        self.ro_start, self.hid_start = self.ro.checkState(), self.hid.checkState()
        g.add("Attributes:", attrs)
        v.addStretch(1)
        self.counter = SizeCounter(paths, True)
        self.counter.progress.connect(self._counted)
        self.counter.start()

    def _counted(self, r):
        size, disk, _files, _folders, _done = r
        self.size.setText(size_text(size))
        self.disk.setText(size_text(disk))

    def stop(self):
        self.counter.requestInterruption()
        self.counter.wait(2000)

    def apply(self) -> str | None:
        errors = []
        if self.ro.checkState() != self.ro_start and self.ro.checkState() != Qt.PartiallyChecked:
            for p in self.paths:
                e = set_read_only(p, self.ro.checkState() == Qt.Checked)
                if e:
                    errors.append(e)
            self.ro_start = self.ro.checkState()
        if self.hid.checkState() != self.hid_start and self.hid.checkState() != Qt.PartiallyChecked:
            for p in self.paths:
                e = set_hidden(p, self.hid.checkState() == Qt.Checked)
                if e:
                    errors.append(e)
            self.hid_start = self.hid.checkState()
        self.dirty = False
        return "\n".join(errors[:8]) or None


class DrivePage(Page):
    """General tab of a drive: type, file system, used and free space and the pie."""

    def __init__(self, path: Path):
        super().__init__()
        from computer import PieChart     # the Computer window's two-colour pie
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        info = drive_info(path)
        row, _edit = name_row(themed(info["icon"], "drive-harddisk"), info["label"], False)
        v.addLayout(row)
        g = Grid(v)
        g.sep()
        g.add("Type:", info["kind"])
        g.add("File system:", info["fstype"] or "Unknown")
        if info["device"]:
            g.add("Device:", info["device"])
        g.add("Location:", str(path))
        g.sep()
        total, free = info["total"], info["free"]
        used = max(0, total - free)
        g.add(self._swatch(PieChart.USED, "Used space:"), self._bytes(used))
        g.add(self._swatch(PieChart.FREE, "Free space:"), self._bytes(free))
        g.sep()
        g.add("Capacity:", self._bytes(total))
        pie = PieChart(used / total if total else 0)
        v.addWidget(pie, 0, Qt.AlignHCenter)
        cap = QLabel(info["title"])
        cap.setAlignment(Qt.AlignHCenter)
        v.addWidget(cap)
        v.addStretch(1)

    @staticmethod
    def _bytes(n: int) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(value_label(f"{n:,} bytes"), 1)
        h.addWidget(value_label(short_size(n)))
        return w

    @staticmethod
    def _swatch(color: QColor, text: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        sq = QLabel()
        sq.setFixedSize(14, 14)
        sq.setStyleSheet(f"background:{color.name()}; border:1px solid black;")
        h.addWidget(sq)
        h.addWidget(QLabel(text))
        h.addStretch(1)
        return w


def drive_info(path: Path) -> dict:
    out = {"label": path.name or str(path), "kind": "Local Disk", "fstype": "", "device": "", "icon": "drive-harddisk",
           "total": 0, "free": 0, "title": path.name or str(path), "region": None}
    try:
        sv = os.statvfs(path)
        out["total"], out["free"] = sv.f_blocks * sv.f_frsize, sv.f_bavail * sv.f_frsize
    except OSError:
        pass
    try:
        import drives as dr
        real = os.path.realpath(path)
        for d in dr.list_drives():
            if d.mountpoint and os.path.realpath(d.mountpoint) == real:
                out.update(label=d.label or d.name, kind=d.kind, fstype=d.fstype or "", device=d.device or "",
                           icon=d.icon or "drive-harddisk",
                           title=f"Drive {d.letter}:" if d.letter else (d.name or out["title"]))
                if d.total:
                    out["total"], out["free"] = d.total, d.free or 0
                break
    except Exception:  # noqa: BLE001 - the drive list is a nicety; statvfs is enough
        pass
    if not out["fstype"]:
        try:
            for line in Path("/proc/self/mountinfo").read_text().splitlines():
                left, _, right = line.partition(" - ")
                f = left.split()
                if len(f) > 4 and f[4] == str(path):
                    r = right.split()
                    out["fstype"], out["device"] = r[0], (r[1] if len(r) > 1 and r[1].startswith("/dev") else "")
        except OSError:
            pass
    return out


class ToolsPage(Page):
    def __init__(self, path: Path):
        super().__init__()
        self.device = drive_info(path)["device"]
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        for title, text, button, slot, ok in (
                ("Error-checking", "This option will check the drive for errors.", "Check now...", self._check,
                 bool(self.device)),
                ("Defragmentation", "This drive's file system keeps files in one piece by itself, so it doesn't need "
                 "defragmenting.", "Defragment now...", None, False),
                ("Backup", "This option will back up files on the drive.", "Back up now...", None, False)):
            box = QFrame()
            box.setFrameShape(QFrame.StyledPanel)
            bl = QGridLayout(box)
            head = QLabel(f"<b>{title}</b>")
            bl.addWidget(head, 0, 0, 1, 2)
            lab = QLabel(text)
            lab.setWordWrap(True)
            bl.addWidget(lab, 1, 0)
            b = QPushButton(button)
            b.setEnabled(ok)
            if slot:
                b.clicked.connect(slot)
            bl.addWidget(b, 2, 1)
            bl.setColumnStretch(0, 1)
            v.addWidget(box)
        v.addStretch(1)

    def _check(self):
        subprocess.Popen(["classic7-diskmgmt", "--check", self.device], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---- Shortcut (.desktop) ---------------------------------------------------------------------
class ShortcutPage(Page):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.entry = read_desktop(path).get("Desktop Entry", {})
        e = self.entry
        self.icon_name = e.get("Icon", "")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        row, self.title = name_row(themed(self.icon_name, "application-x-executable"), e.get("Name", path.stem), True)
        self.title_start = self.title.text()
        self.title.textEdited.connect(self.mark)
        self.pic = row.itemAt(0).widget()
        v.addLayout(row)
        g = Grid(v)
        g.sep()
        self.is_link = e.get("Type") == "Link"
        if self.is_link:
            url = e.get("URL", "")
            g.add("Target type:", "Folder" if url.startswith(("file:", "/")) else "Internet shortcut")
            self.target = QLineEdit(url)
            g.add("Target:", self.target)
        else:
            exec_ = e.get("Exec", "")
            try:
                prog = shlex.split(exec_)[0] if exec_ else ""
            except ValueError:
                prog = exec_.split(" ")[0]
            if prog and not prog.startswith("/"):
                import shutil
                prog = shutil.which(prog) or prog
            g.add("Target type:", "Application")
            g.add("Target location:", str(Path(prog).parent) if prog.startswith("/") else "")
            self.target = QLineEdit(exec_)
            g.add("Target:", self.target)
        self.target_start = self.target.text()
        self.target.textEdited.connect(self.mark)
        g.sep()
        self.start_in = QLineEdit(e.get("Path", ""))
        self.start_in.textEdited.connect(self.mark)
        if not self.is_link:
            g.add("Start in:", self.start_in)
        keys = QLineEdit("None")
        keys.setEnabled(False)
        g.add("Shortcut key:", keys)
        run = QComboBox()
        run.addItems(["Normal window"])
        run.setEnabled(False)
        g.add("Run:", run)
        self.comment = QLineEdit(e.get("Comment", ""))
        self.comment.textEdited.connect(self.mark)
        g.add("Comment:", self.comment)
        btns = QHBoxLayout()
        loc = QPushButton("Open File Location")
        loc.clicked.connect(self._open_location)
        loc.setEnabled(not self.is_link)
        ch = QPushButton("Change Icon...")
        ch.clicked.connect(self._change_icon)
        adv = QPushButton("Advanced...")
        adv.clicked.connect(self._advanced)
        adv.setEnabled(not self.is_link)
        self.terminal = e.get("Terminal", "false") == "true"
        self.terminal_start = self.terminal
        for b in (loc, ch, adv):
            btns.addWidget(b)
        v.addSpacing(6)
        v.addLayout(btns)
        v.addStretch(1)

    def _open_location(self):
        exec_ = self.target.text()
        try:
            prog = shlex.split(exec_)[0]
        except (ValueError, IndexError):
            return
        import shutil
        prog = prog if prog.startswith("/") else (shutil.which(prog) or "")
        if prog:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(prog).parent)))

    def _change_icon(self):
        dlg = IconDialog(self, f"Change Icon for {self.title.text()}", self.icon_name,
                         ["applications-", "utilities-", "preferences-", "internet-", "folder", "user-", "system-",
                          "accessories-", "multimedia-", "office-", "network-", "games-", "computer", "drive-"])
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            self.icon_name = dlg.chosen
            self.pic.setPixmap(themed(self.icon_name).pixmap(32, 32))
            self.mark()

    def _advanced(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Advanced Properties")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Choose the advanced properties you want for this shortcut."))
        term = QCheckBox("Run in a terminal window")
        term.setChecked(self.terminal)
        v.addWidget(term)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() == QDialog.Accepted and term.isChecked() != self.terminal:
            self.terminal = term.isChecked()
            self.mark()

    def apply(self) -> str | None:
        changes: dict[str, str | None] = {}
        if self.title.text() != self.title_start:
            changes["Name"] = self.title.text()
        if self.target.text() != self.target_start:
            changes["URL" if self.is_link else "Exec"] = self.target.text()
        if self.start_in.text() != self.entry.get("Path", ""):
            changes["Path"] = self.start_in.text() or None
        if self.comment.text() != self.entry.get("Comment", ""):
            changes["Comment"] = self.comment.text() or None
        if self.icon_name != self.entry.get("Icon", ""):
            changes["Icon"] = self.icon_name
        if self.terminal != self.terminal_start:
            changes["Terminal"] = "true" if self.terminal else None
        self.dirty = False
        if not changes:
            return None
        try:
            write_desktop_keys(self.path, changes)
        except OSError as e:
            return f"Unable to save the changes to {self.path.name}: {e.strerror or e}"
        self.entry = read_desktop(self.path).get("Desktop Entry", {})
        self.title_start, self.target_start, self.terminal_start = self.title.text(), self.target.text(), self.terminal
        return None


# ---- Security ------------------------------------------------------------------------------
# Windows permission names over the owner / group / everyone read, write and execute bits
R, W, X = 4, 2, 1
PERMS = [("Full control", R | W | X, R | W | X), ("Modify", R | W, R | W | X), ("Read & execute", R | X, R | X),
         ("List folder contents", None, R | X), ("Read", R, R), ("Write", W, W)]


def perm_rows(is_dir: bool) -> list[tuple[str, int]]:
    return [(name, d if is_dir else f) for name, f, d in PERMS if (d if is_dir else f) is not None]


def principal_bits(mode: int, which: int) -> int:
    return (mode >> (6 - 3 * which)) & 7


class SecurityPage(Page):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.addWidget(QLabel(f"Object name:   {path}"))
        v.addWidget(QLabel("Group or user names:"))
        self.who = QTreeWidget()
        self.who.setHeaderHidden(True)
        self.who.setRootIsDecorated(False)
        self.who.setFixedHeight(84)
        v.addWidget(self.who)
        row = QHBoxLayout()
        row.addWidget(QLabel("To change permissions, click Edit."), 1)
        edit = QPushButton("Edit...")
        edit.clicked.connect(self._edit)
        row.addWidget(edit)
        v.addLayout(row)
        self.perm_title = QLabel()
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setHeaderLabels(["", "Allow", "Deny"])
        self.table.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.header().setSectionResizeMode(1, QHeaderView.Fixed)
        self.table.header().setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.header().resizeSection(1, 56)
        self.table.header().resizeSection(2, 56)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        v.addWidget(self.table, 1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("For special permissions or advanced settings,\nclick Advanced."), 1)
        adv = QPushButton("Advanced")
        adv.clicked.connect(self._advanced)
        row2.addWidget(adv)
        v.addLayout(row2)
        self.who.currentItemChanged.connect(lambda *_: self._show())
        self._load()

    def _load(self):
        try:
            self.st = self.path.stat()
        except OSError:
            self.st = self.path.lstat()
        self.is_dir = stat.S_ISDIR(self.st.st_mode)
        u, g = user_name(self.st.st_uid), group_name(self.st.st_gid)
        fn = full_name(self.st.st_uid)
        cur = self.who.currentIndex().row() if self.who.topLevelItemCount() else 0
        self.who.clear()
        for text, icon in ((f"{fn} ({u})" if fn and fn != u else u, "user-identity"),
                           (f"{g} (group)", "system-users"), ("Everyone", "system-users")):
            it = QTreeWidgetItem([text])
            it.setIcon(0, themed(icon, "user"))
            self.who.addTopLevelItem(it)
        self.who.setCurrentItem(self.who.topLevelItem(max(0, cur)))
        self._show()

    def _show(self):
        i = max(0, self.who.indexOfTopLevelItem(self.who.currentItem()))
        name = self.who.currentItem().text(0) if self.who.currentItem() else ""
        self.table.headerItem().setText(0, f"Permissions for {name.split(' (')[0]}")
        bits = principal_bits(self.st.st_mode, i)
        special = (i == 0 and self.st.st_mode & stat.S_ISUID) or (i == 1 and self.st.st_mode & stat.S_ISGID) or (
            i == 2 and self.st.st_mode & stat.S_ISVTX)
        self.table.clear()
        for label, need in perm_rows(self.is_dir) + [("Special permissions", -1)]:
            on = bool(special) if need == -1 else (bits & need) == need
            it = QTreeWidgetItem([label, "✔" if on else "", ""])
            it.setTextAlignment(1, Qt.AlignCenter)
            self.table.addTopLevelItem(it)

    def _edit(self):
        dlg = PermissionsDialog(self, self.path, self.st, self.who.indexOfTopLevelItem(self.who.currentItem()))
        if dlg.exec() == QDialog.Accepted:
            self._load()

    def _advanced(self):
        mode = self.st.st_mode
        lines = [f"Owner:  {user_name(self.st.st_uid)}", f"Group:  {group_name(self.st.st_gid)}",
                 f"Permissions:  {stat.filemode(mode)}  ({stat.S_IMODE(mode):04o})"]
        if mode & stat.S_ISUID:
            lines.append("Runs as its owner (setuid)")
        if mode & stat.S_ISGID:
            lines.append("Runs with its group / new files get its group (setgid)")
        if mode & stat.S_ISVTX:
            lines.append("Only owners can delete or rename items in it (sticky)")
        try:
            r = subprocess.run(["getfacl", "--omit-header", "--absolute-names", str(self.path)], capture_output=True,
                               text=True, timeout=5)
            extra = [ln for ln in r.stdout.splitlines() if ln and not ln.startswith(("user::", "group::", "other::"))]
            if extra:
                lines += ["", "Extra permission entries:"] + [f"    {ln}" for ln in extra]
        except (OSError, subprocess.SubprocessError):     # getfacl is optional
            pass
        QMessageBox.information(self, f"Advanced Security Settings for {self.path.name or self.path}",
                                "\n".join(lines))


class PermissionsDialog(QDialog):
    """Edit: tick Allow boxes; ticking one ticks what it includes, clearing one clears what includes it."""

    def __init__(self, parent, path: Path, st: os.stat_result, which: int):
        super().__init__(parent)
        self.path = path
        self.mode = stat.S_IMODE(st.st_mode)
        self.is_dir = stat.S_ISDIR(st.st_mode)
        self.setWindowTitle(f"Permissions for {path.name or path}")
        self.bits = [principal_bits(self.mode, i) for i in range(3)]
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Security"))
        v.addWidget(QLabel(f"Object name:   {path}"))
        v.addWidget(QLabel("Group or user names:"))
        self.who = QListWidget()
        self.who.setFixedHeight(76)
        names = [user_name(st.st_uid), f"{group_name(st.st_gid)} (group)", "Everyone"]
        for n, ic in zip(names, ("user-identity", "system-users", "system-users")):
            QListWidgetItem(themed(ic, "user"), n, self.who)
        v.addWidget(self.who)
        self.title = QLabel()
        v.addWidget(self.title)
        grid = QGridLayout()
        grid.addWidget(QLabel("Allow"), 0, 1, Qt.AlignHCenter)
        grid.addWidget(QLabel("Deny"), 0, 2, Qt.AlignHCenter)
        self.rows = perm_rows(self.is_dir)
        self.boxes: list[QCheckBox] = []
        for r, (label, _need) in enumerate(self.rows, start=1):
            grid.addWidget(QLabel(label), r, 0)
            b = QCheckBox()
            b.clicked.connect(lambda on, k=r - 1: self._toggled(k, on))
            grid.addWidget(b, r, 1, Qt.AlignHCenter)
            d = QCheckBox()
            d.setEnabled(False)
            grid.addWidget(d, r, 2, Qt.AlignHCenter)
            self.boxes.append(b)
        grid.setColumnStretch(0, 1)
        v.addLayout(grid)
        note = QLabel("Linux has no Deny entries: what isn't allowed is denied.")
        note.setStyleSheet("color: #555;")
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        v.addWidget(bb)
        self.who.currentRowChanged.connect(lambda _r: self._show())
        self.who.setCurrentRow(max(0, which))
        self.resize(360, 420)

    def _show(self):
        i = max(0, self.who.currentRow())
        self.title.setText(f"Permissions for {self.who.currentItem().text().split(' (')[0]}")
        for b, (_label, need) in zip(self.boxes, self.rows):
            b.setChecked((self.bits[i] & need) == need)

    def _toggled(self, k: int, on: bool):
        """Ticking adds the permission's bits; clearing takes away the one bit that makes it what it
        is (Full control without execute is Modify, and so on), which also clears what includes it."""
        i = max(0, self.who.currentRow())
        label, need = self.rows[k]
        if on:
            self.bits[i] |= need
        else:
            remove = {"Full control": W if self.is_dir else X, "Modify": W, "Read & execute": X,
                      "List folder contents": X, "Read": R, "Write": W}[label]
            self.bits[i] &= ~remove
        self._show()

    def _apply(self) -> bool:
        mode = (self.mode & ~0o777) | (self.bits[0] << 6) | (self.bits[1] << 3) | self.bits[2]
        if mode == self.mode:
            return True
        try:
            os.chmod(self.path, mode)
        except OSError as e:
            QMessageBox.warning(self, "Windows Security",
                                f"Unable to save permission changes on {self.path.name or self.path}.\n\n"
                                f"{'Access is denied.' if e.errno in (1, 13) else (e.strerror or str(e))}")
            return False
        self.mode = mode
        return True

    def _ok(self):
        if self._apply():
            self.accept()


# ---- Details --------------------------------------------------------------------------------
def image_details(path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    try:
        from PIL import ExifTags, Image
    except ImportError:
        return []
    try:
        with Image.open(path) as im:
            w, h = im.size
            dpi = im.info.get("dpi")
            bands = len(im.getbands())
            depth = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32, "CMYK": 32, "I;16": 16, "I": 32, "F": 32}.get(
                im.mode, 8 * bands)
            exif = im.getexif()
    except Exception:  # noqa: BLE001 - not a picture PIL knows
        return []
    img = [("Dimensions", f"{w} x {h}"), ("Width", f"{w} pixels"), ("Height", f"{h} pixels")]
    if dpi:
        img += [("Horizontal resolution", f"{round(float(dpi[0]))} dpi"),
                ("Vertical resolution", f"{round(float(dpi[1]))} dpi")]
    img.append(("Bit depth", str(depth)))
    out = [("Image", img)]
    if exif:
        tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
        try:
            tags.update({ExifTags.TAGS.get(k, str(k)): v for k, v in exif.get_ifd(0x8769).items()})
        except Exception:  # noqa: BLE001
            pass

        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError, ZeroDivisionError):
                return None
        cam = []
        for key, label in (("Make", "Camera maker"), ("Model", "Camera model")):
            if tags.get(key):
                cam.append((label, str(tags[key]).strip("\x00 ")))
        if num(tags.get("FNumber")):
            cam.append(("F-stop", f"f/{num(tags['FNumber']):g}"))
        et = num(tags.get("ExposureTime"))
        if et:
            cam.append(("Exposure time", f"1/{round(1 / et)} sec." if et < 1 else f"{et:g} sec."))
        if tags.get("ISOSpeedRatings"):
            cam.append(("ISO speed", f"ISO-{tags['ISOSpeedRatings']}"))
        if num(tags.get("ExposureBiasValue")) is not None:
            cam.append(("Exposure bias", f"{num(tags['ExposureBiasValue']):g} step"))
        if num(tags.get("FocalLength")):
            cam.append(("Focal length", f"{num(tags['FocalLength']):g} mm"))
        if tags.get("Flash") is not None:
            cam.append(("Flash mode", "Flash" if int(tags["Flash"]) & 1 else "No flash"))
        if cam:
            out.append(("Camera", cam))
        org = []
        for key, label in (("DateTimeOriginal", "Date taken"), ("Software", "Program name"), ("Artist", "Authors"),
                           ("Copyright", "Copyright")):
            if tags.get(key):
                org.append((label, str(tags[key]).strip("\x00 ")))
        if org:
            out.append(("Origin", org))
    return out


def office_details(path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    import re
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            core = z.read("docProps/core.xml").decode("utf-8", "replace") if "docProps/core.xml" in z.namelist() else ""
            app = z.read("docProps/app.xml").decode("utf-8", "replace") if "docProps/app.xml" in z.namelist() else ""
    except (OSError, zipfile.BadZipFile, KeyError):
        return []

    def tag(xml, name):
        m = re.search(rf"<(?:\w+:)?{name}[^>]*>([^<]*)</", xml)
        return m.group(1).strip() if m else ""
    desc = [(lab, tag(core, t)) for lab, t in (("Title", "title"), ("Subject", "subject"), ("Tags", "keywords"),
                                               ("Comments", "description"))]
    origin = [(lab, tag(core, t)) for lab, t in (("Authors", "creator"), ("Last saved by", "lastModifiedBy"),
                                                 ("Revision number", "revision"))]
    origin += [(lab, tag(app, t)) for lab, t in (("Program name", "Application"), ("Company", "Company"))]
    content = [(lab, tag(app, t)) for lab, t in (("Pages", "Pages"), ("Word count", "Words"),
                                                 ("Slides", "Slides"), ("Total editing time", "TotalTime"))]
    content = [(a, b + (" minutes" if a == "Total editing time" and b else "")) for a, b in content]
    out = []
    for title, rows in (("Description", desc), ("Origin", origin), ("Content", content)):
        rows = [(a, b) for a, b in rows if b]
        if rows:
            out.append((title, rows))
    return out


def media_details(path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    """Length, size and rate of audio and video through GStreamer's discoverer, when it's there."""
    try:
        import gi
        gi.require_version("Gst", "1.0")
        gi.require_version("GstPbutils", "1.0")
        from gi.repository import Gst, GstPbutils
        Gst.init(None)
        info = GstPbutils.Discoverer.new(3 * Gst.SECOND).discover_uri(QUrl.fromLocalFile(str(path)).toString())
    except Exception:  # noqa: BLE001 - no GStreamer, or not a media file
        return []
    out = []
    secs = info.get_duration() / Gst.SECOND
    if secs > 0:
        out.append(("Media", [("Length", time.strftime("%H:%M:%S", time.gmtime(secs)))]))
    for v in info.get_video_streams():
        rows = [("Frame width", str(v.get_width())), ("Frame height", str(v.get_height()))]
        if v.get_framerate_denom():
            rows.append(("Frame rate", f"{v.get_framerate_num() / v.get_framerate_denom():.2f} frames/second"))
        if v.get_bitrate():
            rows.append(("Data rate", f"{v.get_bitrate() // 1000}kbps"))
        out.append(("Video", rows))
        break
    for a in info.get_audio_streams():
        rows = []
        if a.get_bitrate():
            rows.append(("Bit rate", f"{a.get_bitrate() // 1000}kbps"))
        rows.append(("Channels", {1: "1 (mono)", 2: "2 (stereo)"}.get(a.get_channels(), str(a.get_channels()))))
        rows.append(("Audio sample rate", f"{a.get_sample_rate() / 1000:g} kHz"))
        out.append(("Audio", rows))
        break
    return out


def details(p: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    mime = mimedb().mimeTypeForFile(str(p))
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    name = mime.name()
    if name.startswith("image/"):
        sections += image_details(p)
    elif p.suffix.lower() in (".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"):
        sections += office_details(p)
    elif name.startswith(("audio/", "video/")):
        sections += media_details(p)
    try:
        st = p.lstat()
    except OSError:
        st = None
    rows = [("Name", p.name), ("Item type", type_text(p)), ("Folder path", str(p.parent))]
    if st is not None:
        bt = birth_time(str(p))
        if bt:
            rows.append(("Date created", date_short(bt)))
        rows.append(("Date modified", date_short(st.st_mtime)))
        rows.append(("Size", short_size(st.st_size)))
        rows.append(("Attributes", ("R" if is_read_only(p) else "") + ("H" if is_hidden(p) else "")))
        rows.append(("Owner", f"{socket.gethostname()}\\{user_name(st.st_uid)}"))
    rows.append(("Computer", f"{socket.gethostname()} (this computer)"))
    sections.append(("File", rows))
    return sections


class _DetailsReader(QThread):
    done = Signal(object)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            self.done.emit(details(self.path))
        except Exception:  # noqa: BLE001 - a file that can't be read just shows the File section
            self.done.emit([])


class DetailsPage(Page):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Property", "Value"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().resizeSection(0, 150)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        v.addWidget(self.tree, 1)
        self.reader = _DetailsReader(path)
        self.reader.done.connect(self._fill)
        self.reader.start()

    def _section(self, title: str, rows: list[tuple[str, str]]):
        head = QTreeWidgetItem([title, ""])
        f = head.font(0)
        f.setBold(True)
        head.setFont(0, f)
        head.setFlags(Qt.ItemIsEnabled)
        self.tree.addTopLevelItem(head)
        head.setFirstColumnSpanned(True)
        for k, val in rows:
            it = QTreeWidgetItem([f"  {k}", val])
            it.setToolTip(1, val)
            self.tree.addTopLevelItem(it)

    def _fill(self, sections):
        self.tree.clear()
        for title, rs in sections:
            self._section(title, rs)

    def stop(self):
        self.reader.wait(3000)


# ---- Customize (folders) ------------------------------------------------------------------
class IconDialog(QDialog):
    """Change Icon: a grid of icons from the icon theme."""

    def __init__(self, parent, title: str, current: str, prefixes: list[str]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.chosen: str | None = None
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Select an icon from the list below:"))
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(32, 32))
        self.list.setGridSize(QSize(76, 64))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setWordWrap(True)
        for name in self._names(prefixes, current):
            it = QListWidgetItem(QIcon.fromTheme(name), "", self.list)
            it.setData(Qt.UserRole, name)
            it.setToolTip(name)
            if name == current:
                self.list.setCurrentItem(it)
        self.list.itemDoubleClicked.connect(lambda *_: self._ok())
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        row.addStretch(1)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(460, 380)

    @staticmethod
    def _names(prefixes: list[str], current: str) -> list[str]:
        names: set[str] = set()
        theme = QIcon.themeName()
        bases = [Path(d) for d in QIcon.themeSearchPaths()]
        themes = [theme, "breeze", "hicolor"]
        for b in bases:
            for t in themes:
                root = b / t
                if not root.is_dir():
                    continue
                for sub in ("places", "apps", "devices", "categories", "mimetypes", "actions", "status"):
                    for size in ("32", "48", "64", "scalable", "32x32", "48x48", "64x64"):
                        d = root / sub / size if not size.endswith(("x32", "x48", "x64")) else root / size / sub
                        if not d.is_dir():
                            continue
                        for f in d.iterdir():
                            n = f.stem
                            if any(n.startswith(px) for px in prefixes) and not n.endswith("-symbolic"):
                                names.add(n)
        if current:
            names.add(current)
        return sorted(names)[:600]

    def _browse(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Browse", str(Path.home()), "Icons (*.png *.svg *.svgz *.xpm *.ico)")
        if fn:
            self.chosen = fn
            self.accept()

    def _ok(self):
        it = self.list.currentItem()
        if it is not None:
            self.chosen = it.data(Qt.UserRole)
            self.accept()


class CustomizePage(Page):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        self.dotdir = path / ".directory"
        self.icon_name = read_desktop(self.dotdir).get("Desktop Entry", {}).get("Icon", "")
        self.start = self.icon_name
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        head = QLabel("<b>Folder icons</b>")
        v.addWidget(head)
        text = QLabel("You can change the icon of this folder. Explorer and the desktop show it instead of the "
                      "plain folder.")
        text.setWordWrap(True)
        v.addWidget(text)
        row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedSize(52, 52)
        self.preview.setFrameShape(QFrame.StyledPanel)
        self.preview.setAlignment(Qt.AlignCenter)
        row.addWidget(self.preview)
        col = QVBoxLayout()
        ch = QPushButton("Change Icon...")
        ch.clicked.connect(self._change)
        rs = QPushButton("Restore Default")
        rs.clicked.connect(self._restore)
        col.addWidget(ch)
        col.addWidget(rs)
        col.addStretch(1)
        row.addLayout(col)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        self._preview()

    def _preview(self):
        self.preview.setPixmap(themed(self.icon_name or "folder", "folder").pixmap(32, 32))

    def _change(self):
        dlg = IconDialog(self, f"Change Icon for {self.path.name} Folder", self.icon_name or "folder",
                         ["folder", "user-", "network-", "drive-", "media-", "applications-", "emblem-"])
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            self.icon_name = dlg.chosen
            self._preview()
            self.mark()

    def _restore(self):
        if self.icon_name:
            self.icon_name = ""
            self._preview()
            self.mark()

    def apply(self) -> str | None:
        self.dirty = False
        if self.icon_name == self.start:
            return None
        try:
            if self.dotdir.exists():
                write_desktop_keys(self.dotdir, {"Icon": self.icon_name or None})
            elif self.icon_name:
                self.dotdir.write_text(f"[Desktop Entry]\nIcon={self.icon_name}\n")
        except OSError as e:
            return f"Unable to change the icon of {self.path.name}: {e.strerror or e}"
        self.start = self.icon_name
        return None


# ---- Open with ------------------------------------------------------------------------------
class OpenWithDialog(QDialog):
    def __init__(self, parent, path: Path, mime: str):
        super().__init__(parent)
        self.setWindowTitle("Open with")
        self.chosen: App | None = None
        v = QVBoxLayout(self)
        intro = QLabel("Choose the program you want to use to open this file:")
        v.addWidget(intro)
        file_row = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(icon_for(path).pixmap(32, 32))
        file_row.addWidget(pic)
        file_row.addWidget(QLabel(f"File:  {path.name}"), 1)
        v.addLayout(file_row)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIconSize(QSize(24, 24))
        rec = QTreeWidgetItem(["Recommended Programs"])
        other = QTreeWidgetItem(["Other Programs"])
        for head in (rec, other):
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(head)
        m = mimedb().mimeTypeForName(mime)
        types = {mime} | (set(m.allAncestors()) if m.isValid() else set())
        current = default_app(mime)
        for a in all_apps():
            if getattr(a, "nodisplay", False) and a.desktop_id != (current.desktop_id if current else ""):
                continue
            recommended = bool(types & set(getattr(a, "mimes", [])))
            it = QTreeWidgetItem([a.name])
            it.setIcon(0, themed(a.icon, "application-x-executable"))
            it.setData(0, Qt.UserRole, a.desktop_id)
            (rec if recommended else other).addChild(it)
            if current and a.desktop_id == current.desktop_id:
                self.tree.setCurrentItem(it)
        self._apps = {a.desktop_id: a for a in all_apps()}
        rec.setExpanded(True)
        other.setExpanded(rec.childCount() == 0)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self._ok() if it.data(0, Qt.UserRole) else None)
        v.addWidget(self.tree, 1)
        always = QCheckBox("Always use the selected program to open this kind of file")
        always.setChecked(True)
        always.setEnabled(False)
        v.addWidget(always)
        row = QHBoxLayout()
        row.addStretch(1)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.mime = mime
        self.resize(440, 480)

    def _browse(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Open with...", "/usr/bin")
        if not fn:
            return
        # a program without a desktop file gets one, as Windows registers a program it is pointed at
        name = Path(fn).name
        apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications"
        did = f"classic7-openwith-{name}.desktop"
        try:
            apps.mkdir(parents=True, exist_ok=True)
            (apps / did).write_text(f"[Desktop Entry]\nType=Application\nName={name}\nExec={shlex.quote(fn)} %f\n"
                                    f"NoDisplay=true\nMimeType={self.mime};\n")
        except OSError:
            return
        self.chosen = App(did, name, "application-x-executable", fn, apps / did)
        self.accept()

    def _ok(self):
        it = self.tree.currentItem()
        did = it.data(0, Qt.UserRole) if it else None
        if did:
            self.chosen = self._apps.get(did)
            self.accept()


# ---- the dialog -----------------------------------------------------------------------------
class PropertiesDialog(QDialog):
    def __init__(self, paths: list[Path], parent=None):
        super().__init__(parent)
        self.paths = paths
        self.pages: list[Page] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        self.apply_btn = bb.button(QDialogButtonBox.Apply)
        self.apply_btn.setEnabled(False)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        self.apply_btn.clicked.connect(self._apply)
        v.addWidget(bb)
        if len(paths) == 1:
            p = paths[0]
            kind = kind_of(p)
            trash = trash_info(p) if kind == "trash" else None
            title = trash.original.name if trash else (p.name or str(p))
            self.setWindowTitle(f"{title} Properties")
            self.setWindowIcon(icon_for(p))
            if kind == "drive":
                self._add(DrivePage(p), "General")
                self._add(ToolsPage(p), "Tools")
                self._add(SecurityPage(p), "Security")
            elif kind == "shortcut":
                self._add(GeneralPage(p, kind), "General")
                self._add(ShortcutPage(p), "Shortcut")
                self._add(SecurityPage(p), "Security")
                self._add(DetailsPage(p), "Details")
            elif kind == "folder":
                self._add(GeneralPage(p, kind), "General")
                self._add(SecurityPage(p), "Security")
                self._add(CustomizePage(p), "Customize")
            elif kind == "trash":
                self._add(GeneralPage(p, kind), "General")
                self._add(DetailsPage(p), "Details")
            else:
                self._add(GeneralPage(p, kind), "General")
                self._add(SecurityPage(p), "Security")
                self._add(DetailsPage(p), "Details")
        else:
            self.setWindowTitle(f"{paths[0].name}, ... Properties")
            self.setWindowIcon(themed("document-multiple", "edit-copy"))
            self._add(MultiPage(paths), "General")
        # a property sheet doesn't change size (and so gets no maximize button)
        self.setFixedSize(404, 530)

    def _add(self, page: Page, title: str):
        page.changed.connect(lambda: self.apply_btn.setEnabled(True))
        self.pages.append(page)
        self.tabs.addTab(page, title)

    def renamed(self, new: Path):
        self.paths = [new]
        self.setWindowTitle(f"{new.name} Properties")
        for p in self.pages:
            if hasattr(p, "path"):
                p.path = new

    def _apply(self) -> bool:
        errors = []
        for p in reversed(self.pages):
            if p.dirty:
                e = p.apply()
                if e:
                    errors.append(e)
        self.apply_btn.setEnabled(False)
        if errors:
            QMessageBox.warning(self, self.windowTitle(), "\n\n".join(errors))
            return False
        return True

    def _ok(self):
        self._apply()
        self.accept()

    def done(self, r):
        for p in self.pages:
            p.stop()
        super().done(r)


def to_path(arg: str) -> Path:
    if arg.startswith("file://"):
        return Path(urllib.parse.unquote(urllib.parse.urlparse(arg).path))
    return Path(arg).expanduser().absolute()


def is_computer_icon(p: Path) -> bool:
    """The desktop's Computer icon (a shortcut to classic7-computer). Older copies on the
    desktop lack the X-Classic7-Computer key, so the command counts too."""
    if p.suffix != ".desktop" or not p.is_file():
        return False
    e = read_desktop(p).get("Desktop Entry", {})
    if e.get("X-Classic7-Computer", "").lower() == "true":
        return True
    try:
        cmd = shlex.split(e.get("Exec", ""))
    except ValueError:
        return False
    return bool(cmd) and os.path.basename(cmd[0]) == "classic7-computer"


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.split("\n\n")[1].strip())
        return 0 if argv else 2
    paths = [to_path(a) for a in argv if a and not a.startswith("--")]
    paths = [p for p in paths if p.exists() or p.is_symlink()]
    if not paths:
        print("classic7-properties: nothing to show", file=sys.stderr)
        return 1
    if len(paths) == 1 and is_computer_icon(paths[0]) and trash_info(paths[0]) is None:
        # as in Windows 7: Computer > Properties is the System window, not the shortcut's
        # details (the activation token in the environment goes along, so it gets the focus)
        try:
            os.execvp("classic7-system", ["classic7-system"])
        except OSError as e:
            print(f"classic7-properties: classic7-system: {e}", file=sys.stderr)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-properties")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-properties")
    dlg = PropertiesDialog(paths)
    dlg.show()
    dlg.finished.connect(app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
