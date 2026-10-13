"""Disk Management, in the style of Windows 7 (diskmgmt.msc).

Volume list on top, the disks drawn as bars below. Drive letters, formatting, new and deleted
partitions go through the root helper (classic7-disk-helper, via pkexec). A volume with a
drive letter is opened at /var/mnt/<letter> at every start-up, so Steam libraries on extra
drives are there before Steam starts.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys

from PySide6.QtCore import QPoint, QProcess, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QIcon, QKeySequence, QPainter,
                           QPalette, QPen)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox, QPushButton,
                               QRadioButton, QScrollArea, QSpinBox, QSplitter, QStatusBar,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QWizard,
                               QWizardPage)

import disks as dk

HELPER = "/usr/libexec/classic7-disk-helper"

PRIMARY = QColor(0, 0, 160)          # dark blue bar: primary partition
LOGICAL = QColor(80, 140, 230)       # light blue: logical drive
UNALLOC = QColor(0, 0, 0)            # black: unallocated
FREE = QColor(0, 160, 0)             # green: free space in an extended partition
EXTENDED = QColor(0, 160, 0)
REMOVABLE = QColor(0, 0, 160)
CDROM = QColor(0, 0, 160)


def icon(name: str, fallback: str = "drive-harddisk") -> QIcon:
    ic = QIcon.fromTheme(name)
    return ic if not ic.isNull() else QIcon.fromTheme(fallback)


def helper_argv(args: list[str]) -> list[str]:
    override = os.environ.get("CLASSIC7_DISK_HELPER")
    if override:
        return shlex.split(override) + args
    return ["pkexec", HELPER] + args


def bar_color(r: dk.Region) -> QColor:
    if r.kind == "free":
        return FREE if r.in_extended else UNALLOC
    if r.disk.kind == "rom":
        return CDROM
    if "logical" in r.flags:
        return LOGICAL
    if "extended" in r.flags:
        return EXTENDED
    return PRIMARY


def launch(argv: list[str]):
    try:
        subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def explore(path: str):
    launch(["dolphin", "--new-window", path] if shutil.which("dolphin") else ["xdg-open", path])


# ---- the graphical view --------------------------------------------------------------------
class DiskMap(QWidget):
    """One row per disk: the grey label box, then a box per partition with a coloured bar."""
    selected = Signal(object)          # Region, Disk or None
    menu = Signal(object, QPoint)
    activated = Signal(object)

    ROW_H = 78
    LABEL_W = 132
    MIN_W = 104
    GAP = 8

    def __init__(self):
        super().__init__()
        self.disks: list[dk.Disk] = []
        self.current = None
        self.boxes: list[tuple[QRect, object]] = []
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(255, 255, 255))
        self.setPalette(pal)

    def set_disks(self, disks: list[dk.Disk]):
        self.disks = disks
        self.updateGeometry()
        self._layout()
        self.update()

    def sizeHint(self):
        return QSize(self.LABEL_W + 4 * self.MIN_W, max(1, len(self.disks)) * (self.ROW_H + self.GAP) + self.GAP)

    def minimumSizeHint(self):
        most = max((len(d.regions) or 1 for d in self.disks), default=1)
        return QSize(self.LABEL_W + most * self.MIN_W + 12, len(self.disks) * (self.ROW_H + self.GAP) + self.GAP)

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _layout(self):
        self.boxes = []
        y = self.GAP
        width = max(self.width(), self.minimumSizeHint().width()) - 8
        for d in self.disks:
            self.boxes.append((QRect(4, y, self.LABEL_W, self.ROW_H), d))
            x0 = 4 + self.LABEL_W + 2
            avail = width - x0
            regs = [r for r in d.regions if not ({"extended", "msr", "biosboot"} & r.flags)]
            if not regs:
                self.boxes.append((QRect(x0, y, avail, self.ROW_H), ("empty", d)))
            else:
                n = len(regs)
                extra = max(0, avail - n * self.MIN_W)
                total = sum(max(r.sectors, 1) for r in regs) or 1
                x = x0
                for i, r in enumerate(regs):
                    w = self.MIN_W + int(extra * max(r.sectors, 1) / total)
                    if i == n - 1:
                        w = x0 + avail - x
                    self.boxes.append((QRect(x, y, w, self.ROW_H), r))
                    x += w
            y += self.ROW_H + self.GAP
        self.setMinimumHeight(y)

    def item_at(self, pos):
        for rect, obj in self.boxes:
            if rect.contains(pos):
                return obj[1] if isinstance(obj, tuple) else obj
        return None

    def select(self, obj):
        self.current = obj
        self.update()

    def mousePressEvent(self, e):
        obj = self.item_at(e.position().toPoint())
        self.current = obj
        self.update()
        self.selected.emit(obj)
        if e.button() == Qt.RightButton and obj is not None:
            self.menu.emit(obj, e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        obj = self.item_at(e.position().toPoint())
        if obj is not None:
            self.activated.emit(obj)

    def keyPressEvent(self, e):
        order = [o[1] if isinstance(o, tuple) else o for _, o in self.boxes]
        if e.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and order:
            try:
                i = order.index(self.current)
            except ValueError:
                i = -1
            step = 1 if e.key() in (Qt.Key_Right, Qt.Key_Down) else -1
            i = max(0, min(len(order) - 1, i + step))
            self.select(order[i])
            self.selected.emit(order[i])
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and self.current is not None:
            self.activated.emit(self.current)
            return
        if e.key() == Qt.Key_Menu and self.current is not None:
            for rect, o in self.boxes:
                if (o[1] if isinstance(o, tuple) else o) is self.current:
                    self.menu.emit(self.current, self.mapToGlobal(rect.center()))
                    return
        super().keyPressEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255))
        f = self.font()
        bold = QFont(f)
        bold.setBold(True)
        fm = QFontMetrics(f)
        for rect, obj in self.boxes:
            if isinstance(obj, dk.Disk):
                self._paint_label(p, rect, obj, f, bold)
            elif isinstance(obj, tuple):
                self._paint_empty(p, rect, obj[1], f)
            else:
                self._paint_region(p, rect, obj, f, bold, fm)
        p.end()

    def _paint_label(self, p, rect, d: dk.Disk, f, bold):
        sel = self.current is d
        p.fillRect(rect, QColor(225, 233, 245) if not sel else QColor(196, 214, 238))
        p.setPen(QColor(150, 160, 175))
        p.drawRect(rect.adjusted(0, 0, -1, -1))
        ic = icon("media-optical" if d.kind == "rom" else
                  "drive-removable-media-usb" if d.removable else "drive-harddisk")
        ic.paint(p, QRect(rect.left() + 5, rect.top() + 6, 20, 20))
        p.setPen(QColor(0, 0, 0))
        p.setFont(bold)
        x = rect.left() + 30
        p.drawText(QRect(x, rect.top() + 5, rect.width() - 34, 18), Qt.AlignLeft | Qt.AlignVCenter, d.title)
        p.setFont(f)
        if d.kind == "rom":
            lines = ["DVD", "No Media" if not d.size else dk.human(d.size), "Online" if d.size else ""]
        elif not d.initialized:
            lines = ["Unknown", dk.human(d.size), "Not Initialized"]
        else:
            lines = [d.layout(), dk.human(d.size), "Online" if not d.readonly else "Read Only"]
        for i, t in enumerate(lines):
            p.drawText(QRect(x, rect.top() + 23 + i * 16, rect.width() - 34, 16), Qt.AlignLeft | Qt.AlignVCenter, t)
        if sel and self.hasFocus():
            p.setPen(QPen(QColor(0, 0, 0), 1, Qt.DotLine))
            p.drawRect(rect.adjusted(2, 2, -3, -3))

    def _paint_empty(self, p, rect, d: dk.Disk, f):
        p.setPen(QColor(150, 160, 175))
        p.drawRect(rect.adjusted(0, 0, -1, -1))
        p.setPen(QColor(0, 0, 0))
        p.setFont(f)
        text = "No Media" if d.kind == "rom" else ""
        p.drawText(rect.adjusted(8, 14, -4, -4), Qt.AlignLeft | Qt.AlignTop, text)

    def _paint_region(self, p, rect, r: dk.Region, f, bold, fm):
        sel = self.current is r
        outer = rect.adjusted(1, 0, -1, 0)
        p.setPen(QColor(150, 160, 175))
        p.setBrush(Qt.NoBrush)
        p.drawRect(outer.adjusted(0, 0, -1, -1))
        bar = QRect(outer.left() + 1, outer.top() + 1, outer.width() - 2, 9)
        p.fillRect(bar, bar_color(r))
        body = QRect(outer.left() + 3, bar.bottom() + 3, outer.width() - 6, outer.bottom() - bar.bottom() - 5)
        if sel:
            p.fillRect(body, QColor(255, 255, 255))
            p.fillRect(body, QBrush(QColor(170, 170, 170), Qt.BDiagPattern))
        p.setPen(QColor(0, 0, 0))
        if r.kind == "free":
            lines = [(dk.human(r.size), False), ("Free space" if r.in_extended else "Unallocated", False)]
        else:
            first = r.name() or ""
            lines = []
            if first:
                lines.append((first, True))
            fs = r.fs_name()
            lines.append((f"{dk.human(r.size)} {fs}".strip(), False))
            lines.append((r.status(), False))
        y = body.top() + 2
        for text, is_bold in lines:
            p.setFont(bold if is_bold else f)
            avail = body.width() - 6
            shown = QFontMetrics(p.font()).elidedText(text, Qt.ElideRight, avail)
            p.drawText(QRect(body.left() + 3, y, avail, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, shown)
            y += fm.height() + 1
        if sel and self.hasFocus():
            p.setPen(QPen(QColor(0, 0, 0), 1, Qt.DotLine))
            p.drawRect(body.adjusted(0, 0, -1, -1))


class Legend(QWidget):
    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)
        self.items = {}
        for key, color, text in (("unalloc", UNALLOC, "Unallocated"), ("primary", PRIMARY, "Primary partition"),
                                 ("extended", EXTENDED, "Extended partition"), ("free", FREE, "Free space"),
                                 ("logical", LOGICAL, "Logical drive")):
            sw = QLabel()
            sw.setFixedSize(10, 10)
            sw.setStyleSheet(f"background: {color.name()}; border: 1px solid #808080;")
            lab = QLabel(text)
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 8, 0)
            bl.setSpacing(4)
            bl.addWidget(sw)
            bl.addWidget(lab)
            lay.addWidget(box)
            self.items[key] = box
        lay.addStretch(1)

    def show_for(self, disks: list[dk.Disk]):
        regs = dk.all_regions(disks)
        has = {"unalloc": any(r.kind == "free" and not r.in_extended for r in regs) or True,
               "primary": True,
               "extended": any("extended" in r.flags for r in regs),
               "free": any(r.kind == "free" and r.in_extended for r in regs),
               "logical": any("logical" in r.flags for r in regs)}
        for k, w in self.items.items():
            w.setVisible(has[k])


# ---- dialogs --------------------------------------------------------------------------------
def confirm(parent, title: str, text: str, default_no: bool = True) -> bool:
    box = QMessageBox(QMessageBox.Warning, title, text, QMessageBox.Yes | QMessageBox.No, parent)
    box.setDefaultButton(QMessageBox.No if default_no else QMessageBox.Yes)
    return box.exec() == QMessageBox.Yes


class LetterPicker(QDialog):
    """Add Drive Letter or Path / Change Drive Letter or Path."""

    def __init__(self, title: str, letters: list[str], current: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Add a new drive letter or path for this volume." if not current else
                             "Enter a new drive letter or path for this volume."))
        row = QHBoxLayout()
        self.assign = QRadioButton("Assign the following drive letter:")
        self.assign.setChecked(True)
        self.combo = QComboBox()
        self.combo.addItems(letters)
        if current and current in letters:
            self.combo.setCurrentText(current)
        row.addWidget(self.assign)
        row.addStretch(1)
        row.addWidget(self.combo)
        lay.addLayout(row)
        folder = QRadioButton("Mount in the following empty NTFS folder:")
        folder.setEnabled(False)
        lay.addWidget(folder)
        lay.addSpacing(6)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        if not letters:
            bb.button(QDialogButtonBox.Ok).setEnabled(False)

    def letter(self) -> str:
        return self.combo.currentText()


class LettersDialog(QDialog):
    """Change Drive Letter and Paths for D: (Games)."""

    def __init__(self, win: "DiskManagement", r: dk.Region):
        super().__init__(win)
        self.win, self.r = win, r
        self.setWindowTitle(f"Change Drive Letter and Paths for {r.name() or 'the volume'}")
        self.resize(400, 260)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Allow access to this volume by using the following drive letter and paths:"))
        self.list = QListWidget()
        if r.letter:
            self.list.addItem(f"{r.letter}:")
        for m in r.mounts:
            if not dk.letter_of_mount(m) and "system" not in r.flags:
                self.list.addItem(m)
        if self.list.count():
            self.list.setCurrentRow(0)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Add...")
        self.change_btn = QPushButton("Change...")
        self.remove_btn = QPushButton("Remove")
        for b in (self.add_btn, self.change_btn, self.remove_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.add_btn.setEnabled(not r.letter)
        self.change_btn.setEnabled(bool(r.letter))
        self.remove_btn.setEnabled(bool(r.letter))
        self.add_btn.clicked.connect(lambda: self._pick(None))
        self.change_btn.clicked.connect(lambda: self._pick(r.letter))
        self.remove_btn.clicked.connect(self._remove)

    def _pick(self, current):
        letters = dk.free_letters(self.win.disks, keep=current)
        dlg = LetterPicker("Change Drive Letter or Path" if current else "Add Drive Letter or Path",
                           letters, current, self)
        if dlg.exec() != QDialog.Accepted:
            return
        new = dlg.letter()
        if current and new == current:
            return
        if current and not confirm(self, "Disk Management",
                                   "Some programs that rely on drive letters might not run correctly. "
                                   "Do you want to continue?"):
            return
        self.accept()
        self.win.assign_letter(self.r, new)

    def _remove(self):
        if not confirm(self, "Disk Management", "Some programs that rely on drive letters might not run "
                                                "correctly. Are you sure you want to remove this drive letter?"):
            return
        self.accept()
        self.win.run_helper(["unletter", self.r.path], f"Removing drive letter {self.r.letter}:")


class FormatDialog(QDialog):
    def __init__(self, r: dk.Region, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Format {r.letter + ':' if r.letter else r.name() or r.path}")
        lay = QFormLayout(self)
        self.label = QLineEdit(r.label or "New Volume")
        self.fs = QComboBox()
        for name, fs in dk.available_formats():
            self.fs.addItem(name, fs)
        cur = r.fstype if r.fstype != "ntfs3" else "ntfs"
        i = self.fs.findData(cur)
        self.fs.setCurrentIndex(i if i >= 0 else 0)
        alloc = QComboBox()
        alloc.addItem("Default")
        alloc.setEnabled(False)
        lay.addRow("Volume label:", self.label)
        lay.addRow("File system:", self.fs)
        lay.addRow("Allocation unit size:", alloc)
        quick = QCheckBox("Perform a quick format")
        quick.setChecked(True)
        quick.setEnabled(False)
        compress = QCheckBox("Enable file and folder compression")
        compress.setEnabled(False)
        lay.addRow(quick)
        lay.addRow(compress)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #555;")
        lay.addRow(self.note)
        self.fs.currentIndexChanged.connect(self._note)
        self._note()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)

    def _note(self):
        self.note.setText(fs_hint(self.fs.currentData()))


def fs_hint(fs: str | None) -> str:
    return {
        "ntfs": "NTFS: Windows can use this drive too. Windows games through Proton can have trouble on it.",
        "exfat": "exFAT: for USB sticks and cards that Windows, Mac and Linux all use. Not for Steam games.",
        "vfat": "FAT32: the most compatible, but no file can be larger than 4 GB.",
        "ext4": "ext4: the best choice for a drive only this computer uses, including Steam games.",
        "btrfs": "Btrfs: like ext4, with compression; good for a drive only this computer uses.",
    }.get(fs or "", "")


class InitDialog(QDialog):
    def __init__(self, ds: list[dk.Disk], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Initialize Disk")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("You must initialize a disk before Logical Disk Manager can access it."))
        lay.addWidget(QLabel("Select disks:"))
        self.list = QListWidget()
        for d in ds:
            it = self.list.addItem(f"{d.title}  ({dk.human(d.size)}{', ' + d.model if d.model else ''})")
            it = self.list.item(self.list.count() - 1)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            it.setData(Qt.UserRole, d)
        lay.addWidget(self.list)
        lay.addWidget(QLabel("Use the following partition style for the selected disks:"))
        self.mbr = QRadioButton("MBR (Master Boot Record)")
        self.gpt = QRadioButton("GPT (GUID Partition Table)")
        self.gpt.setChecked(True)
        lay.addWidget(self.mbr)
        lay.addWidget(self.gpt)
        note = QLabel("Note: GPT works with disks larger than 2 TB and with every current computer. "
                      "Choose MBR only for a disk that must work in a very old computer.")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def chosen(self) -> list[dk.Disk]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def style(self) -> str:
        return "gpt" if self.gpt.isChecked() else "dos"


class NewVolumeWizard(QWizard):
    def __init__(self, win: "DiskManagement", r: dk.Region):
        super().__init__(win)
        self.win, self.r = win, r
        self.setWindowTitle("New Simple Volume Wizard")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.resize(560, 420)
        max_mb = r.size // dk.MIB

        welcome = QWizardPage()
        welcome.setTitle("Welcome to the New Simple Volume Wizard")
        wl = QVBoxLayout(welcome)
        for t in ("This wizard helps you create a simple volume on a disk.",
                  "A simple volume can only be on a single disk.", "To continue, click Next."):
            lab = QLabel(t)
            lab.setWordWrap(True)
            wl.addWidget(lab)
        wl.addStretch(1)
        self.addPage(welcome)

        size = QWizardPage()
        size.setTitle("Specify Volume Size")
        size.setSubTitle("Choose a volume size that is between the maximum and minimum sizes.")
        g = QGridLayout(size)
        g.addWidget(QLabel("Maximum disk space in MB:"), 0, 0)
        g.addWidget(QLabel(str(max_mb)), 0, 1)
        g.addWidget(QLabel("Minimum disk space in MB:"), 1, 0)
        g.addWidget(QLabel("8"), 1, 1)
        g.addWidget(QLabel("Simple volume size in MB:"), 2, 0)
        self.size = QSpinBox()
        self.size.setRange(min(8, max_mb), max_mb)
        self.size.setValue(max_mb)
        g.addWidget(self.size, 2, 1)
        g.setColumnStretch(2, 1)
        g.setRowStretch(3, 1)
        self.addPage(size)

        letter = QWizardPage()
        letter.setTitle("Assign Drive Letter or Path")
        letter.setSubTitle("For easier access, you can assign a drive letter or drive path to your partition.")
        ll = QGridLayout(letter)
        self.use_letter = QRadioButton("Assign the following drive letter:")
        self.no_letter = QRadioButton("Do not assign a drive letter or drive path")
        self.letter = QComboBox()
        self.letter.addItems(dk.free_letters(win.disks))
        self.use_letter.setChecked(self.letter.count() > 0)
        self.no_letter.setChecked(self.letter.count() == 0)
        ll.addWidget(self.use_letter, 0, 0)
        ll.addWidget(self.letter, 0, 1)
        ll.addWidget(self.no_letter, 1, 0, 1, 2)
        hint = QLabel("A drive with a letter is opened at every start-up, so Steam and other programs "
                      "always find it in the same place.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555;")
        ll.addWidget(hint, 2, 0, 1, 3)
        ll.setColumnStretch(2, 1)
        ll.setRowStretch(3, 1)
        self.use_letter.toggled.connect(self.letter.setEnabled)
        self.addPage(letter)

        fmt = QWizardPage()
        fmt.setTitle("Format Partition")
        fmt.setSubTitle("To store data on this partition, you must format it first.")
        fl = QVBoxLayout(fmt)
        dont = QRadioButton("Do not format this volume")
        dont.setEnabled(False)
        do = QRadioButton("Format this volume with the following settings:")
        do.setChecked(True)
        fl.addWidget(dont)
        fl.addWidget(do)
        form = QFormLayout()
        form.setContentsMargins(24, 0, 0, 0)
        self.fs = QComboBox()
        for name, fs in dk.available_formats():
            self.fs.addItem(name, fs)
        i = self.fs.findData("ext4" if not r.disk.removable else "exfat")
        self.fs.setCurrentIndex(max(0, i))
        alloc = QComboBox()
        alloc.addItem("Default")
        alloc.setEnabled(False)
        self.label = QLineEdit("New Volume")
        form.addRow("File system:", self.fs)
        form.addRow("Allocation unit size:", alloc)
        form.addRow("Volume label:", self.label)
        quick = QCheckBox("Perform a quick format")
        quick.setChecked(True)
        quick.setEnabled(False)
        form.addRow(quick)
        fl.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #555;")
        fl.addWidget(self.note)
        fl.addStretch(1)
        self.fs.currentIndexChanged.connect(lambda: self.note.setText(fs_hint(self.fs.currentData())))
        self.note.setText(fs_hint(self.fs.currentData()))
        self.addPage(fmt)

        done = QWizardPage()
        done.setTitle("Completing the New Simple Volume Wizard")
        dl = QVBoxLayout(done)
        dl.addWidget(QLabel("You have successfully completed the New Simple Volume Wizard."))
        dl.addWidget(QLabel("You selected the following settings:"))
        self.summary = QLabel()
        self.summary.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        self.summary.setAutoFillBackground(True)
        self.summary.setBackgroundRole(QPalette.Base)
        self.summary.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.summary.setMargin(6)
        dl.addWidget(self.summary, 1)
        dl.addWidget(QLabel("To close this wizard, click Finish."))
        done.initializePage = self._summary
        self.addPage(done)

    def _summary(self):
        self.summary.setText("\n".join([
            "Volume type: Simple Volume",
            f"Disk selected: {self.r.disk.title}",
            f"Volume size: {self.size.value()} MB",
            f"Drive letter or path: {self.letter.currentText() + ':' if self.use_letter.isChecked() else 'None'}",
            f"File system: {self.fs.currentText()}",
            "Allocation unit size: Default",
            f"Volume label: {self.label.text()}",
            "Quick format: Yes"]))

    def args(self) -> list[str]:
        sectors = min(self.r.sectors, self.size.value() * dk.MIB // dk.SECTOR) // dk.ALIGN * dk.ALIGN
        out = ["create", self.r.disk.path, str(self.r.start), str(sectors), self.fs.currentData(), self.label.text()]
        if self.use_letter.isChecked() and self.letter.currentText():
            out.append(self.letter.currentText())
        return out


class PropertiesDialog(QDialog):
    def __init__(self, win: "DiskManagement", obj):
        super().__init__(win)
        self.win = win
        tabs = QTabWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.resize(400, 440)
        if isinstance(obj, dk.Disk):
            self.setWindowTitle(f"{obj.model or obj.title} Properties")
            tabs.addTab(self._disk_tab(obj), "General")
            tabs.addTab(self._volumes_tab(obj), "Volumes")
            return
        r: dk.Region = obj
        self.setWindowTitle(f"{r.name() or 'Volume'} Properties")
        tabs.addTab(self._general(r), "General")
        if r.kind != "free":
            tabs.addTab(self._tools(r), "Tools")
            tabs.addTab(self._games(r), "Games")

    def _rows(self, rows):
        w = QWidget()
        f = QFormLayout(w)
        for k, v in rows:
            lab = QLabel(v)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            f.addRow(k, lab)
        return w, f

    def _disk_tab(self, d: dk.Disk):
        w, f = self._rows([("Device:", d.path), ("Model:", d.model or "Unknown"),
                           ("Type:", "Removable" if d.removable else "Basic"),
                           ("Connection:", (d.tran or "").upper() or "Internal"),
                           ("Capacity:", f"{dk.human(d.size)}  ({d.size:,} bytes)"),
                           ("Partition style:", d.partition_style()),
                           ("Status:", "Read Only" if d.readonly else "Online")])
        return w

    def _volumes_tab(self, d: dk.Disk):
        t = QTreeWidget()
        t.setHeaderLabels(["Volume", "Capacity"])
        t.setRootIsDecorated(False)
        for r in d.regions:
            if r.kind != "free":
                QTreeWidgetItem(t, [r.name() or r.path or "", dk.human(r.size)])
        return t

    def _general(self, r: dk.Region):
        from computer import PieChart
        w = QWidget()
        v = QVBoxLayout(w)
        top, f = self._rows([("Type:", "Unallocated" if r.kind == "free" else
                              "Removable Disk" if r.disk.removable else "Local Disk"),
                             ("File system:", r.fs_name() or "RAW"),
                             ("Device:", r.path or ""),
                             ("Opened at:", r.open_path or "Not opened")])
        v.addWidget(top)
        if r.fssize and r.fsavail is not None:
            used = r.fssize - r.fsavail
            g = QFormLayout()
            g.addRow("Used space:", QLabel(f"{used:,} bytes   {dk.human(used)}"))
            g.addRow("Free space:", QLabel(f"{r.fsavail:,} bytes   {dk.human(r.fsavail)}"))
            g.addRow("Capacity:", QLabel(f"{r.fssize:,} bytes   {dk.human(r.fssize)}"))
            v.addLayout(g)
            pie = PieChart(used / r.fssize if r.fssize else 0)
            v.addWidget(pie, 0, Qt.AlignHCenter)
        else:
            g = QFormLayout()
            g.addRow("Capacity:", QLabel(f"{r.size:,} bytes   {dk.human(r.size)}"))
            v.addLayout(g)
        v.addStretch(1)
        return w

    def _tools(self, r: dk.Region):
        w = QWidget()
        v = QVBoxLayout(w)
        box = QGroupBox("Error-checking")
        bl = QVBoxLayout(box)
        bl.addWidget(QLabel("This option will check the volume for errors."))
        b = QPushButton("Check now...")
        b.setEnabled(self.win.can_check(r))
        b.clicked.connect(lambda: (self.accept(), self.win.check(r)))
        bl.addWidget(b, 0, Qt.AlignRight)
        v.addWidget(box)
        v.addStretch(1)
        return w

    def _games(self, r: dk.Region):
        w = QWidget()
        v = QVBoxLayout(w)
        box = QGroupBox("Steam library")
        bl = QVBoxLayout(box)
        path = r.open_path
        lib = os.path.join(path, "SteamLibrary") if path else None
        if lib and os.path.isdir(os.path.join(lib, "steamapps")):
            known = dk.steam_knows(lib)
            text = f"This drive has a Steam library: {lib}"
            if not known:
                text += "\n\nTo use it, open Steam, choose Steam ▸ Settings ▸ Storage, open the " \
                        f"drive list and choose Add Drive, then pick {lib}."
        elif path:
            text = "Install games from Steam on this drive."
        else:
            text = "Give the drive a letter first, so it is opened at every start-up."
        lab = QLabel(text)
        lab.setWordWrap(True)
        bl.addWidget(lab)
        b = QPushButton("Set up a Steam library here...")
        b.setEnabled(bool(path) and "system" not in r.flags)
        b.clicked.connect(lambda: (self.accept(), self.win.steam_setup(r)))
        bl.addWidget(b, 0, Qt.AlignRight)
        v.addWidget(box)
        if dk.proton_risky(r.fstype):
            warn = QLabel(dk.PROTON_NOTE.format(fs=r.fs_name(), name=r.name() or "this drive"))
            warn.setWordWrap(True)
            v.addWidget(warn)
        v.addStretch(1)
        return w


# ---- the window -----------------------------------------------------------------------------
class DiskManagement(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Disk Management")
        self.setWindowIcon(icon("drive-harddisk"))
        self.resize(820, 600)
        self.disks: list[dk.Disk] = []
        self.snapshot = None
        self.proc: QProcess | None = None
        self.asked_init: set[str] = set()

        self._menus()
        split = QSplitter(Qt.Vertical)
        self.table = QTreeWidget()
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setAllColumnsShowFocus(True)
        self.table.setHeaderLabels(["Volume", "Layout", "Type", "File System", "Status", "Capacity",
                                    "Free Space", "% Free"])
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.itemSelectionChanged.connect(self._table_selected)
        self.table.itemDoubleClicked.connect(lambda it, _c: self._activate(it.data(0, Qt.UserRole)))
        hdr = self.table.header()
        hdr.setStretchLastSection(False)
        widths = [150, 70, 60, 80, 260, 80, 80, 60]
        for i, w in enumerate(widths):
            self.table.setColumnWidth(i, w)
        split.addWidget(self.table)

        self.map = DiskMap()
        self.map.selected.connect(self._map_selected)
        self.map.menu.connect(self._menu_for)
        self.map.activated.connect(self._activate)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.map)
        scroll.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        split.addWidget(scroll)
        split.setSizes([200, 360])
        self.setCentralWidget(split)

        sb = QStatusBar()
        self.legend = Legend()
        sb.addWidget(self.legend, 1)
        self.busy = QLabel()
        sb.addPermanentWidget(self.busy)
        self.setStatusBar(sb)

        self.refresh(force=True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(3000)
        QTimer.singleShot(400, self._offer_init)

    # menus and toolbar
    def _menus(self):
        mb = self.menuBar()
        fm = mb.addMenu("&File")
        fm.addAction("E&xit", self.close, QKeySequence("Alt+F4"))
        self.action_menu = mb.addMenu("&Action")
        self.action_menu.aboutToShow.connect(self._fill_action_menu)
        vm = mb.addMenu("&View")
        top = vm.addMenu("&Top")
        self.top_volumes = top.addAction("&Volume List")
        self.top_volumes.setCheckable(True)
        self.top_volumes.setChecked(True)
        self.top_volumes.toggled.connect(lambda on: self.table.setVisible(on))
        vm.addSeparator()
        vm.addAction("&Refresh", lambda: self.refresh(force=True), QKeySequence("F5"))
        hm = mb.addMenu("&Help")
        hm.addAction("&Help Topics", self._help, QKeySequence("F1"))
        hm.addSeparator()
        hm.addAction("&About Disk Management", self._about)
        tb = self.addToolBar("Standard")
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        tb.addAction(icon("view-refresh"), "Refresh", lambda: self.refresh(force=True))
        tb.addSeparator()
        self.props_act = tb.addAction(icon("document-properties"), "Properties", self._properties)
        tb.addAction(icon("help-contents"), "Help", self._help)

    def _fill_action_menu(self):
        m = self.action_menu
        m.clear()
        m.addAction("Refresh", lambda: self.refresh(force=True))
        m.addAction("Rescan Disks", self._rescan)
        cur = self.current()
        if cur is not None:
            m.addSeparator()
            sub = m.addMenu("All Tasks")
            self._fill_menu(sub, cur)
        m.addSeparator()
        m.addAction("Help", self._help)

    # data
    def refresh(self, force: bool = False):
        try:
            disks = dk.list_disks()
        except Exception as e:  # noqa: BLE001 - keep the window up even if lsblk misbehaves
            self.busy.setText(f"Could not read the disks: {e}")
            return
        snap = [(d.path, d.size, d.pttype, [(r.key, r.kind, r.sectors, r.fstype, r.label, tuple(r.mounts),
                                              r.letter, r.fsavail) for r in d.regions]) for d in disks]
        if snap == self.snapshot and not force:
            return
        self.snapshot = snap
        keep = self.current()
        keep_key = keep.key if isinstance(keep, dk.Region) else keep.path if isinstance(keep, dk.Disk) else None
        self.disks = disks
        self.map.set_disks(disks)
        self.legend.show_for(disks)
        self._fill_table()
        if keep_key:
            for r in dk.all_regions(disks):
                if r.key == keep_key:
                    self._select(r)
                    break
            else:
                for d in disks:
                    if d.path == keep_key:
                        self._select(d)

    def _fill_table(self):
        self.table.blockSignals(True)
        self.table.clear()
        for r in dk.volumes(self.disks):
            name = r.name()
            if not name:
                name = f"({r.disk.title} partition {r.number})" if r.number else f"({r.disk.title})"
            free = r.fsavail
            pct = f"{round(100 * free / r.fssize)} %" if free is not None and r.fssize else ""
            it = QTreeWidgetItem([name, "Simple", "Basic" if not r.disk.removable else "Removable", r.fs_name(),
                                  r.status(), dk.human(r.size), dk.human(free) if free is not None else "", pct])
            it.setIcon(0, icon("drive-harddisk-system" if "system" in r.flags else
                               "drive-removable-media-usb" if r.disk.removable else
                               "media-optical" if r.disk.kind == "rom" else "drive-harddisk"))
            for c in (5, 6, 7):
                it.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
            it.setData(0, Qt.UserRole, r)
            self.table.addTopLevelItem(it)
        self.table.blockSignals(False)

    def current(self):
        return self.map.current

    def _select(self, obj):
        self.map.select(obj)
        self.table.blockSignals(True)
        self.table.clearSelection()
        for i in range(self.table.topLevelItemCount()):
            it = self.table.topLevelItem(i)
            if it.data(0, Qt.UserRole) is obj:
                it.setSelected(True)
                self.table.setCurrentItem(it)
        self.table.blockSignals(False)

    def _table_selected(self):
        items = self.table.selectedItems()
        self.map.select(items[0].data(0, Qt.UserRole) if items else None)

    def _map_selected(self, obj):
        self._select(obj)

    def _table_menu(self, pos):
        it = self.table.itemAt(pos)
        if it:
            self._menu_for(it.data(0, Qt.UserRole), self.table.viewport().mapToGlobal(pos))

    # menus
    def _menu_for(self, obj, pos):
        self._select(obj)
        m = QMenu(self)
        self._fill_menu(m, obj)
        m.exec(pos)

    def _fill_menu(self, m: QMenu, obj):
        def add(text, fn, enabled=True, bold=False):
            a = m.addAction(text, fn)
            a.setEnabled(enabled)
            if bold:
                f = a.font()
                f.setBold(True)
                a.setFont(f)
            return a

        if isinstance(obj, dk.Disk):
            d = obj
            if d.kind != "rom" and not d.initialized:
                add("Initialize Disk", lambda: self.initialize([d]))
                m.addSeparator()
            add("New Spanned Volume...", None, False)
            add("New Striped Volume...", None, False)
            add("Convert to Dynamic Disk...", None, False)
            add("Convert to GPT Disk", None, False)
            m.addSeparator()
            if d.removable and d.kind != "rom":
                add("Eject", lambda: self.eject(d), not d.system)
            m.addSeparator()
            add("Properties", lambda: PropertiesDialog(self, d).exec())
            m.addSeparator()
            add("Help", self._help)
            return
        r: dk.Region = obj
        if r.kind == "free":
            ok, _why = dk.can_create_in(r)
            add("New Simple Volume...", lambda: self.new_volume(r), ok)
            add("New Spanned Volume...", None, False)
            add("New Striped Volume...", None, False)
            add("New Mirrored Volume...", None, False)
            add("New RAID-5 Volume...", None, False)
            m.addSeparator()
            add("Properties", lambda: PropertiesDialog(self, r).exec())
            m.addSeparator()
            add("Help", self._help)
            return
        can_open = bool(r.open_path) or bool(r.letter) or r.fstype in dk.FS_NAMES
        add("Open", lambda: self._activate(r), can_open and r.disk.kind != "rom" or bool(r.open_path), bold=True)
        add("Explore", lambda: self._activate(r), can_open)
        m.addSeparator()
        add("Mark Partition as Active", None, False)
        add("Change Drive Letter and Paths...", lambda: LettersDialog(self, r).exec(), self.can_letter(r))
        add("Format...", lambda: self.format(r), self.can_format(r))
        m.addSeparator()
        add("Extend Volume...", None, False)
        add("Shrink Volume...", None, False)
        add("Add Mirror...", None, False)
        add("Delete Volume...", lambda: self.delete(r), self.can_delete(r))
        m.addSeparator()
        add("Check for Errors...", lambda: self.check(r), self.can_check(r))
        add("Use for Steam Games...", lambda: self.steam_setup(r),
            bool(r.open_path or r.letter) and "system" not in r.flags and r.disk.kind != "rom")
        m.addSeparator()
        add("Properties", lambda: PropertiesDialog(self, r).exec())
        m.addSeparator()
        add("Help", self._help)

    # what is allowed (the helper checks all of it again)
    def can_letter(self, r: dk.Region) -> bool:
        return (r.kind in ("partition", "volume") and r.disk.kind != "rom" and not r.protected
                and (r.fstype or "") in {"ntfs", "ntfs3", "vfat", "exfat", "ext2", "ext3", "ext4", "btrfs",
                                         "xfs", "f2fs"} and "layered" not in r.flags and not r.disk.readonly)

    def can_format(self, r: dk.Region) -> bool:
        return (r.kind in ("partition", "volume") and r.disk.kind != "rom" and not r.protected
                and "layered" not in r.flags and not r.disk.readonly
                and "recovery" not in r.flags and not (r.mounted and not r.letter))

    def can_delete(self, r: dk.Region) -> bool:
        return (r.kind == "partition" and not r.protected and "layered" not in r.flags
                and not r.disk.readonly and not (r.mounted and not r.letter))

    def can_check(self, r: dk.Region) -> bool:
        return (r.kind in ("partition", "volume") and not r.protected and r.disk.kind != "rom"
                and (r.fstype or "") in {"ntfs", "vfat", "exfat", "ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs"}
                and not (r.mounted and not r.letter))

    # actions
    def _activate(self, obj):
        if isinstance(obj, dk.Disk):
            PropertiesDialog(self, obj).exec()
            return
        r: dk.Region = obj
        if r.kind == "free":
            if dk.can_create_in(r)[0]:
                self.new_volume(r)
            return
        if r.open_path:
            explore(r.open_path)
        elif r.letter and r.fstab:
            self.run_helper(["mount", r.path], f"Opening {r.letter}:", then=lambda: self._open_after(r.key))
        elif r.path and r.fstype:
            res = subprocess.run(["udisksctl", "mount", "-b", r.path], capture_output=True, text=True)
            if res.returncode != 0:
                QMessageBox.warning(self, "Disk Management", (res.stderr or res.stdout).strip() or
                                    "The volume could not be opened.")
                return
            self.refresh(force=True)
            self._open_after(r.key)

    def _open_after(self, key):
        self.refresh(force=True)
        for r in dk.all_regions(self.disks):
            if r.key == key and r.open_path:
                explore(r.open_path)

    def assign_letter(self, r: dk.Region, letter: str):
        def after():
            if dk.proton_risky(r.fstype) and shutil.which("steam"):
                box = QMessageBox(QMessageBox.Information, "Disk Management",
                                  f"{letter}: is ready and opens at every start-up.\n\n" +
                                  dk.PROTON_NOTE.format(fs=r.fs_name(), name=f"{letter}:"), parent=self)
                setup = box.addButton("Set up a Steam library...", QMessageBox.AcceptRole)
                box.addButton("Not now", QMessageBox.RejectRole)
                box.exec()
                if box.clickedButton() is setup:
                    for x in dk.all_regions(self.disks):
                        if x.key == r.key:
                            self.steam_setup(x)
        self.run_helper(["letter", r.path, letter], f"Assigning drive letter {letter}:", then=after)

    def format(self, r: dk.Region):
        dlg = FormatDialog(r, self)
        if dlg.exec() != QDialog.Accepted:
            return
        if not confirm(self, f"Format {r.name() or r.path}",
                       "Formatting this volume will erase all data on it. Back up any data you want to keep "
                       "before formatting. Do you want to continue?"):
            return
        self.run_helper(["format", r.path, dlg.fs.currentData(), dlg.label.text()], f"Formatting {r.name() or r.path}")

    def delete(self, r: dk.Region):
        if not confirm(self, "Delete simple volume",
                       "Deleting this volume will erase all data on it. Back up any data you want to keep before "
                       "deleting. Do you want to continue?"):
            return
        self.run_helper(["delete", r.path], f"Deleting {r.name() or r.path}")

    def new_volume(self, r: dk.Region):
        ok, why = dk.can_create_in(r)
        if not ok:
            QMessageBox.information(self, "Disk Management", why)
            return
        wiz = NewVolumeWizard(self, r)
        if wiz.exec() != QDialog.Accepted:
            return
        self.run_helper(wiz.args(), "Formatting the new volume")

    def initialize(self, ds: list[dk.Disk]):
        dlg = InitDialog(ds, self)
        if dlg.exec() != QDialog.Accepted:
            return
        todo = list(dlg.chosen())
        style = dlg.style()

        def step():
            if todo:
                d = todo.pop(0)
                self.run_helper(["init", d.path, style], f"Initializing {d.title}", then=step)
        step()

    def _offer_init(self):
        new = [d for d in self.disks if d.kind == "disk" and not d.initialized and d.path not in self.asked_init]
        self.asked_init |= {d.path for d in new}
        if new and not os.environ.get("CLASSIC7_DISK_NO_INIT_PROMPT"):
            self.initialize(new)

    def check(self, r: dk.Region):
        self.run_helper(["check", r.path], f"Checking {r.name() or r.path}", show_output=True)

    def eject(self, d: dk.Disk):
        for r in d.regions:
            if r.mounted and r.path:
                subprocess.run(["udisksctl", "unmount", "-b", r.path], capture_output=True)
        res = subprocess.run(["udisksctl", "power-off", "-b", d.path], capture_output=True, text=True)
        if res.returncode != 0:
            QMessageBox.warning(self, "Disk Management", (res.stderr or res.stdout).strip())
        self.refresh(force=True)

    def steam_setup(self, r: dk.Region):
        path = r.open_path
        if not path:
            QMessageBox.information(self, "Use for Steam Games",
                                    "Give the drive a letter first (Change Drive Letter and Paths), "
                                    "so it is opened at every start-up.")
            return
        try:
            lib, notes = dk.setup_steam_library(path, r.fstype)
        except OSError as e:
            QMessageBox.warning(self, "Use for Steam Games", f"The Steam library could not be made:\n{e}")
            return
        text = [f"The Steam library folder is ready:\n{lib}"]
        text += notes
        if not dk.steam_knows(lib):
            text.append("Now open Steam, choose Steam ▸ Settings ▸ Storage, open the drive list and "
                        f"choose Add Drive, then pick {lib}. New games can then be installed on "
                        f"{r.letter + ':' if r.letter else 'this drive'}.")
        else:
            text.append("Steam already uses this library.")
        QMessageBox.information(self, "Use for Steam Games", "\n\n".join(text))

    def _rescan(self):
        self.busy.setText("Rescanning disks...")
        QTimer.singleShot(50, lambda: (self.refresh(force=True), self.busy.setText("")))

    def _properties(self):
        cur = self.current()
        if cur is not None:
            PropertiesDialog(self, cur).exec()

    def _help(self):
        QMessageBox.information(
            self, "Disk Management Help",
            "Right-click a volume or an unallocated area to change it.\n\n"
            "• Change Drive Letter and Paths gives a drive a letter. It is then opened at every start-up "
            "(at /var/mnt/<letter>), ready for Steam and other programs.\n"
            "• New Simple Volume makes a partition in unallocated space and formats it.\n"
            "• Format erases a volume. Delete Volume removes it.\n"
            "• Use for Steam Games prepares a Steam library on the drive.\n\n"
            "The volume that holds Classic 7 itself (C:) can't be changed here.")

    def _about(self):
        QMessageBox.about(self, "About Disk Management", "Disk Management\nClassic 7")

    # running the helper
    def run_helper(self, args: list[str], text: str, then=None, show_output: bool = False):
        if self.proc is not None:
            QMessageBox.information(self, "Disk Management", "Please wait until the current task is finished.")
            return
        self.busy.setText(text + "...")
        QApplication.setOverrideCursor(Qt.BusyCursor)
        proc = QProcess(self)
        argv = helper_argv(args)
        proc.setProgram(argv[0])
        proc.setArguments(argv[1:])
        self.proc = proc

        def done(code, _status):
            QApplication.restoreOverrideCursor()
            out = bytes(proc.readAllStandardOutput()).decode(errors="replace").strip()
            err = bytes(proc.readAllStandardError()).decode(errors="replace").strip()
            self.proc = None
            self.busy.setText("")
            self.refresh(force=True)
            if code in (126, 127) and argv[0] == "pkexec":
                return    # the password prompt was cancelled
            if code != 0:
                QMessageBox.warning(self, "Disk Management", err or out or "The operation failed.")
            elif show_output:
                QMessageBox.information(self, "Check Disk", out or "No problems were found.")
            if code == 0 and then:
                then()
        proc.finished.connect(done)
        proc.errorOccurred.connect(lambda _e: done(-1, None) if self.proc is proc else None)
        proc.start()


def main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]] + argv)
    app.setApplicationName("Disk Management")
    app.setDesktopFileName("classic7-diskmgmt")
    w = DiskManagement()
    w.show()
    if len(argv) >= 2 and argv[0] in ("--letter", "--format"):
        def open_dialog(action=argv[0], dev=os.path.realpath(argv[1])):
            r = next((x for x in dk.all_regions(w.disks) if x.path and os.path.realpath(x.path) == dev), None)
            if r is None:
                return
            w._select(r)
            if action == "--letter" and w.can_letter(r):
                LettersDialog(w, r).exec()
            elif action == "--format" and w.can_format(r):
                w.format(r)
        QTimer.singleShot(200, open_dialog)
    return app.exec()
