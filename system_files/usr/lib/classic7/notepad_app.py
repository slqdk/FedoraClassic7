"""Notepad, as in Windows 7: plain text with Word Wrap, Font, Find/Replace/Go To, Time/Date (F5),
the .LOG trick, ANSI/Unicode/UTF-8 files with Windows or Linux line ends, Page Setup with
header and footer (&f &p &d &t), printing and a status bar (Ln, Col)."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QDateTime, QLocale, QMarginsF, QRectF, QSettings, QSizeF, Qt, QTime, QDate
from PySide6.QtGui import (QAction, QFont, QFontDatabase, QFontMetricsF, QKeySequence, QPageLayout, QPageSize,
                           QPainter, QTextCursor, QTextDocument)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFontDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
                               QPushButton, QRadioButton, QStatusBar, QVBoxLayout)

import accessories as acc

APP = "Notepad"
ICON = ("accessories-text-editor", "text-x-generic")

# (label in the Save As dialog, codec, byte order mark)
ENCODINGS = [("ANSI", "cp1252", b""), ("Unicode", "utf-16-le", b"\xff\xfe"),
             ("Unicode big endian", "utf-16-be", b"\xfe\xff"), ("UTF-8", "utf-8", b""),
             ("UTF-8 with BOM", "utf-8", b"\xef\xbb\xbf")]
ENC_BY_LABEL = {e[0]: e for e in ENCODINGS}


def decode(data: bytes) -> tuple[str, str]:
    """(text, encoding label): byte order marks first, then UTF-8, then ANSI (Windows-1252)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace"), "UTF-8 with BOM"
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="replace"), "Unicode"
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="replace"), "Unicode big endian"
    try:
        return data.decode("utf-8"), "UTF-8"
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "ANSI"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "ANSI"


def encode(text: str, label: str) -> bytes:
    _name, codec, bom = ENC_BY_LABEL.get(label, ENC_BY_LABEL["UTF-8"])
    return bom + text.encode(codec)


def can_encode(text: str, label: str) -> bool:
    try:
        encode(text, label)
        return True
    except UnicodeEncodeError:
        return False


def expand_header(fmt: str, name: str, page: int) -> tuple[str, str, str]:
    """Notepad's header/footer codes: &f file, &p page, &d date, &t time, &l &c &r alignment, && &."""
    parts = {"l": "", "c": "", "r": ""}
    where = "c"
    i = 0
    loc = QLocale()
    while i < len(fmt):
        ch = fmt[i]
        if ch == "&" and i + 1 < len(fmt):
            code = fmt[i + 1].lower()
            i += 2
            if code in "lcr":
                where = code
            elif code == "f":
                parts[where] += name
            elif code == "p":
                parts[where] += str(page)
            elif code == "d":
                parts[where] += loc.toString(QDate.currentDate(), QLocale.ShortFormat)
            elif code == "t":
                parts[where] += loc.toString(QTime.currentTime(), QLocale.ShortFormat)
            elif code == "&":
                parts[where] += "&"
            continue
        parts[where] += ch
        i += 1
    return parts["l"], parts["c"], parts["r"]


class FindDialog(QDialog):
    """Find (and Replace): non-modal, like Notepad's."""

    def __init__(self, win: "Notepad", replace: bool):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Replace" if replace else "Find")
        grid = QGridLayout(self)
        grid.addWidget(QLabel("Fi&nd what:"), 0, 0)
        self.what = QLineEdit(win.last_find)
        grid.addWidget(self.what, 0, 1)
        self.with_ = QLineEdit(win.last_replace)
        if replace:
            grid.addWidget(QLabel("Re&place with:"), 1, 0)
            grid.addWidget(self.with_, 1, 1)
        self.case = QCheckBox("Match &case")
        self.case.setChecked(win.match_case)
        self.wrap = QCheckBox("W&rap around")
        self.wrap.setChecked(win.wrap_around)
        opts = QVBoxLayout()
        opts.addWidget(self.case)
        opts.addWidget(self.wrap)
        row = 2 if replace else 1
        grid.addLayout(opts, row, 0, 1, 1)
        if not replace:
            box = QGroupBox("Direction")
            bl = QHBoxLayout(box)
            self.up = QRadioButton("&Up")
            self.down = QRadioButton("&Down")
            (self.up if win.find_up else self.down).setChecked(True)
            bl.addWidget(self.up)
            bl.addWidget(self.down)
            grid.addWidget(box, row, 1)
        else:
            self.up = self.down = None
        buttons = QVBoxLayout()
        self.next_btn = QPushButton("&Find Next")
        self.next_btn.setDefault(True)
        self.next_btn.clicked.connect(self.find_next)
        buttons.addWidget(self.next_btn)
        if replace:
            rep = QPushButton("&Replace")
            rep.clicked.connect(self.replace_one)
            buttons.addWidget(rep)
            rep_all = QPushButton("Replace &All")
            rep_all.clicked.connect(self.replace_all)
            buttons.addWidget(rep_all)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        buttons.addWidget(cancel)
        buttons.addStretch(1)
        grid.addLayout(buttons, 0, 2, 3, 1)
        self.what.textChanged.connect(lambda t: self.next_btn.setEnabled(bool(t)))
        self.next_btn.setEnabled(bool(self.what.text()))
        self.what.selectAll()

    def _store(self):
        w = self.win
        w.last_find = self.what.text()
        w.last_replace = self.with_.text()
        w.match_case = self.case.isChecked()
        w.wrap_around = self.wrap.isChecked()
        if self.up is not None:
            w.find_up = self.up.isChecked()

    def find_next(self):
        self._store()
        self.win.find_next()

    def replace_one(self):
        self._store()
        w = self.win
        c = w.edit.textCursor()
        same = (c.selectedText() == w.last_find if w.match_case
                else c.selectedText().lower() == w.last_find.lower())
        if c.hasSelection() and same:
            c.insertText(w.last_replace)
        w.find_next(up=False)

    def replace_all(self):
        self._store()
        self.win.replace_all()


class PageSetup(QDialog):
    def __init__(self, win: "Notepad"):
        super().__init__(win)
        self.setWindowTitle("Page Setup")
        s = win.settings
        form = QFormLayout(self)
        self.paper = QComboBox()
        self.papers = [("A4", QPageSize.A4), ("A5", QPageSize.A5), ("A3", QPageSize.A3), ("Letter", QPageSize.Letter),
                       ("Legal", QPageSize.Legal)]
        self.paper.addItems([p[0] for p in self.papers])
        self.paper.setCurrentText(s.value("page/paper", "A4"))
        form.addRow("Si&ze:", self.paper)
        orient = QHBoxLayout()
        self.portrait = QRadioButton("P&ortrait")
        self.landscape = QRadioButton("L&andscape")
        (self.landscape if s.value("page/landscape", False, bool) else self.portrait).setChecked(True)
        orient.addWidget(self.portrait)
        orient.addWidget(self.landscape)
        form.addRow("Orientation:", orient)
        self.margins = []
        grid = QGridLayout()
        for i, (label, key, default) in enumerate((("&Left:", "left", 20.0), ("&Right:", "right", 20.0),
                                                   ("&Top:", "top", 25.0), ("&Bottom:", "bottom", 25.0))):
            sp = QDoubleSpinBox()
            sp.setRange(0, 100)
            sp.setDecimals(1)
            sp.setSuffix(" mm")
            sp.setValue(float(s.value(f"page/{key}", default)))
            self.margins.append((key, sp))
            grid.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            grid.addWidget(sp, i // 2, (i % 2) * 2 + 1)
        box = QGroupBox("Margins (millimeters)")
        box.setLayout(grid)
        form.addRow(box)
        self.header = QLineEdit(s.value("page/header", "&f"))
        self.footer = QLineEdit(s.value("page/footer", "Page &p"))
        form.addRow("&Header:", self.header)
        form.addRow("&Footer:", self.footer)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.win = win

    def accept(self):
        s = self.win.settings
        s.setValue("page/paper", self.paper.currentText())
        s.setValue("page/landscape", self.landscape.isChecked())
        for key, sp in self.margins:
            s.setValue(f"page/{key}", sp.value())
        s.setValue("page/header", self.header.text())
        s.setValue("page/footer", self.footer.text())
        super().accept()


class Notepad(QMainWindow):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.settings = QSettings("Classic7", "Notepad")
        self.setWindowIcon(acc.icon(*ICON))
        self.path: str | None = None
        self.encoding = "UTF-8"
        self.crlf = False
        self.last_find = ""
        self.last_replace = ""
        self.match_case = False
        self.wrap_around = False
        self.find_up = False
        self.find_dialog: FindDialog | None = None
        self.edit = QPlainTextEdit()
        self.edit.setFrameStyle(0)
        self.edit.setTabStopDistance(QFontMetricsF(self.edit.font()).horizontalAdvance(" ") * 8)
        self.setCentralWidget(self.edit)
        self.status = QStatusBar()
        self.pos_label = QLabel()
        self.pos_label.setMinimumWidth(140)
        self.status.addPermanentWidget(self.pos_label)
        self.setStatusBar(self.status)
        self._load_font()
        self._menus()
        self.edit.cursorPositionChanged.connect(self._update_pos)
        self.edit.document().modificationChanged.connect(lambda _m: self._update_title())
        self.edit.setLineWrapMode(QPlainTextEdit.WidgetWidth if self.settings.value("wordwrap", False, bool)
                                  else QPlainTextEdit.NoWrap)
        self.status.setVisible(self.settings.value("statusbar", True, bool))
        self.a_wrap.setChecked(self.edit.lineWrapMode() != QPlainTextEdit.NoWrap)
        self.a_status.setChecked(self.status.isVisible())
        self.resize(self.settings.value("size", None) or self.size().expandedTo(self.minimumSize()))
        if not self.settings.value("size"):
            self.resize(760, 560)
        self.setAcceptDrops(True)
        self.edit.setAcceptDrops(False)
        if path:
            self.open_path(path)
        self._update_title()
        self._update_pos()

    # ---- setup -------------------------------------------------------------------------------
    def _load_font(self):
        f = QFont()
        saved = self.settings.value("font", "")
        if not (saved and f.fromString(saved)):
            f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
            f.setPointSize(10)
        self.edit.setFont(f)
        self.edit.setTabStopDistance(QFontMetricsF(f).horizontalAdvance(" ") * 8)

    def _menus(self):
        mb = self.menuBar()

        def act(menu, text, slot, shortcut=None, checkable=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            a.triggered.connect(slot)
            menu.addAction(a)
            return a

        m = mb.addMenu("&File")
        act(m, "&New", self.new, "Ctrl+N")
        act(m, "&Open...", self.open_dialog, "Ctrl+O")
        act(m, "&Save", self.save, "Ctrl+S")
        act(m, "Save &As...", self.save_as)
        m.addSeparator()
        act(m, "Page Set&up...", lambda: PageSetup(self).exec())
        act(m, "&Print...", self.print_dialog, "Ctrl+P")
        m.addSeparator()
        act(m, "E&xit", self.close)
        m = mb.addMenu("&Edit")
        self.a_undo = act(m, "&Undo", self.edit.undo, "Ctrl+Z")
        m.addSeparator()
        self.a_cut = act(m, "Cu&t", self.edit.cut, "Ctrl+X")
        self.a_copy = act(m, "&Copy", self.edit.copy, "Ctrl+C")
        act(m, "&Paste", self.edit.paste, "Ctrl+V")
        self.a_delete = act(m, "De&lete", lambda: self.edit.textCursor().removeSelectedText(), "Del")
        m.addSeparator()
        act(m, "&Find...", lambda: self.show_find(False), "Ctrl+F")
        act(m, "Find &Next", lambda: self.find_next(), "F3")
        act(m, "&Replace...", lambda: self.show_find(True), "Ctrl+H")
        self.a_goto = act(m, "&Go To...", self.go_to, "Ctrl+G")
        m.addSeparator()
        act(m, "Select &All", self.edit.selectAll, "Ctrl+A")
        act(m, "Time/&Date", self.time_date, "F5")
        m.aboutToShow.connect(self._edit_menu_state)
        m = mb.addMenu("F&ormat")
        self.a_wrap = act(m, "&Word Wrap", self.toggle_wrap, checkable=True)
        act(m, "&Font...", self.choose_font)
        m = mb.addMenu("&View")
        self.a_status = act(m, "&Status Bar", self.toggle_status, checkable=True)
        m = mb.addMenu("&Help")
        act(m, "View &Help", self.help, "F1")
        m.addSeparator()
        act(m, "&About Notepad", lambda: acc.about(self, APP, ICON))
        # Delete must not steal the key from the editor when nothing is selected
        self.a_delete.setShortcutContext(Qt.WidgetShortcut)

    def _edit_menu_state(self):
        has = self.edit.textCursor().hasSelection()
        for a in (self.a_cut, self.a_copy, self.a_delete):
            a.setEnabled(has)
        self.a_undo.setEnabled(self.edit.document().isUndoAvailable())

    # ---- title and status -------------------------------------------------------------------
    def display_name(self) -> str:
        return Path(self.path).name if self.path else "Untitled"

    def _update_title(self):
        self.setWindowTitle(f"{self.display_name()} - {APP}")

    def _update_pos(self):
        c = self.edit.textCursor()
        block = c.block()
        line = block.blockNumber() + 1
        col = c.positionInBlock() + 1
        self.pos_label.setText(f"   Ln {line}, Col {col}")

    # ---- files -------------------------------------------------------------------------------
    def maybe_save(self) -> bool:
        if not self.edit.document().isModified():
            return True
        box = QMessageBox(QMessageBox.NoIcon, APP, f"Do you want to save changes to {self.path or 'Untitled'}?",
                          parent=self)
        save = box.addButton("&Save", QMessageBox.AcceptRole)
        box.addButton("Do&n't Save", QMessageBox.DestructiveRole)
        cancel = box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(save)
        box.exec()
        if box.clickedButton() is save:
            return self.save()
        return box.clickedButton() is not cancel

    def new(self):
        if not self.maybe_save():
            return
        self.edit.setPlainText("")
        self.path = None
        self.encoding = "UTF-8"
        self.crlf = False
        self.edit.document().setModified(False)
        self._update_title()

    def _dir(self) -> str:
        return self.settings.value("dir", acc.documents_dir())

    def open_dialog(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open", self._dir(),
                                              "Text Documents (*.txt);;All Files (*)")
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        p = Path(path)
        if not p.exists():
            r = QMessageBox.question(self, APP, f"Cannot find the {p.name} file.\n\nDo you want to create a new file?",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Yes:
                try:
                    p.touch()
                except OSError as e:
                    QMessageBox.warning(self, APP, str(e))
                    return False
            else:
                return False
        try:
            data = p.read_bytes()
        except OSError as e:
            QMessageBox.warning(self, APP, f"{p.name}\n\n{e.strerror or e}")
            return False
        text, self.encoding = decode(data)
        self.crlf = "\r\n" in text
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.edit.setPlainText(text)
        self.path = str(p.resolve())
        self.settings.setValue("dir", str(p.parent))
        self.edit.document().setModified(False)
        # the .LOG trick: a file that starts with .LOG gets the time and date added when opened
        if text.startswith(".LOG"):
            c = self.edit.textCursor()
            c.movePosition(QTextCursor.End)
            self.edit.setTextCursor(c)
            self.edit.insertPlainText("\n" + self._time_date_text() + "\n")
        else:
            self.edit.moveCursor(QTextCursor.Start)
        self._update_title()
        return True

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        return self._write(self.path, self.encoding)

    def save_as(self) -> bool:
        dlg = QFileDialog(self, "Save As", self._dir())
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setNameFilters(["Text Documents (*.txt)", "All Files (*)"])
        dlg.setDefaultSuffix("txt")
        dlg.setOption(QFileDialog.DontUseNativeDialog, True)
        dlg.selectFile(self.display_name() if self.path else "*.txt")
        enc = QComboBox()
        enc.addItems([e[0] for e in ENCODINGS])
        enc.setCurrentText(self.encoding)
        lay = dlg.layout()
        if isinstance(lay, QGridLayout):
            row = lay.rowCount()
            lay.addWidget(QLabel("&Encoding:"), row, 0)
            lay.addWidget(enc, row, 1)
        if not dlg.exec():
            return False
        path = dlg.selectedFiles()[0]
        if Path(path).name in ("*.txt", ""):
            return False
        label = enc.currentText()
        if not can_encode(self.edit.toPlainText(), label):
            r = QMessageBox.warning(
                self, APP, "This file contains characters in Unicode format which will be lost if you save this file"
                " as an ANSI encoded text file. To keep the Unicode information, click Cancel below and then select"
                " one of the Unicode options from the Encoding drop down list. Continue?",
                QMessageBox.Ok | QMessageBox.Cancel)
            if r != QMessageBox.Ok:
                return False
        if self._write(path, label):
            self.path = str(Path(path).resolve())
            self.settings.setValue("dir", str(Path(path).parent))
            self._update_title()
            return True
        return False

    def _write(self, path: str, label: str) -> bool:
        text = self.edit.toPlainText()
        if self.crlf:
            text = text.replace("\n", "\r\n")
        try:
            data = encode(text, label)
        except UnicodeEncodeError:
            _n, codec, bom = ENC_BY_LABEL[label]
            data = bom + text.encode(codec, errors="replace")
        try:
            tmp = Path(path).with_name("." + Path(path).name + ".notepad-tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        except OSError as e:
            QMessageBox.warning(self, APP, f"{Path(path).name}\n\n{e.strerror or e}")
            return False
        self.encoding = label
        self.edit.document().setModified(False)
        return True

    # ---- edit --------------------------------------------------------------------------------
    def _time_date_text(self) -> str:
        loc = QLocale()
        now = QDateTime.currentDateTime()
        return f"{loc.toString(now.time(), QLocale.ShortFormat)} {loc.toString(now.date(), QLocale.ShortFormat)}"

    def time_date(self):
        self.edit.insertPlainText(self._time_date_text())

    def show_find(self, replace: bool):
        sel = self.edit.textCursor().selectedText()
        if sel and " " not in sel:
            self.last_find = sel
        if self.find_dialog is not None:
            self.find_dialog.close()
        self.find_dialog = FindDialog(self, replace)
        self.find_dialog.show()

    def find_next(self, up: bool | None = None) -> bool:
        if not self.last_find:
            self.show_find(False)
            return False
        up = self.find_up if up is None else up
        flags = QTextDocument.FindFlag(0)
        if self.match_case:
            flags |= QTextDocument.FindCaseSensitively
        if up:
            flags |= QTextDocument.FindBackward
        if self.edit.find(self.last_find, flags):
            return True
        if self.wrap_around:
            c = self.edit.textCursor()
            c.movePosition(QTextCursor.End if up else QTextCursor.Start)
            self.edit.setTextCursor(c)
            if self.edit.find(self.last_find, flags):
                return True
        QMessageBox.information(self.find_dialog or self, APP, f'Cannot find "{self.last_find}"')
        return False

    def replace_all(self):
        doc = self.edit.document()
        flags = QTextDocument.FindCaseSensitively if self.match_case else QTextDocument.FindFlag(0)
        c = QTextCursor(doc)
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        n = 0
        while True:
            c = doc.find(self.last_find, c, flags)
            if c.isNull():
                break
            c.insertText(self.last_replace)
            n += 1
        edit.endEditBlock()
        if not n:
            QMessageBox.information(self.find_dialog or self, APP, f'Cannot find "{self.last_find}"')

    def go_to(self):
        total = self.edit.document().blockCount()
        current = self.edit.textCursor().blockNumber() + 1
        line, ok = QInputDialog.getInt(self, "Go To Line", "&Line number:", current, 1, 2 ** 31 - 1)
        if not ok:
            return
        if line > total:
            QMessageBox.information(self, f"{APP} - Goto Line", "The line number is beyond the total number of lines")
            return
        block = self.edit.document().findBlockByNumber(line - 1)
        c = self.edit.textCursor()
        c.setPosition(block.position())
        self.edit.setTextCursor(c)
        self.edit.centerCursor()

    # ---- format / view ----------------------------------------------------------------------
    def toggle_wrap(self, on: bool):
        self.edit.setLineWrapMode(QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap)
        self.settings.setValue("wordwrap", on)

    def toggle_status(self, on: bool):
        self.status.setVisible(on)
        self.settings.setValue("statusbar", on)

    def choose_font(self):
        font, ok = QFontDialog.getFont(self.edit.font(), self, "Font")
        if ok:
            self.edit.setFont(font)
            self.edit.setTabStopDistance(QFontMetricsF(font).horizontalAdvance(" ") * 8)
            self.settings.setValue("font", font.toString())

    def help(self):
        QMessageBox.information(
            self, f"{APP} Help",
            "Notepad edits plain text.\n\n"
            "F5 inserts the time and date. A file whose first line is .LOG gets the time and date added at the end "
            "each time it is opened.\n\nIn Page Setup, the header and footer can use &f (file name), &p (page number), "
            "&d (date), &t (time), and &l, &c, &r to align the text that follows left, centre or right.")

    # ---- printing ----------------------------------------------------------------------------
    def _printer(self) -> QPrinter:
        s = self.settings
        printer = QPrinter(QPrinter.HighResolution)
        paper = dict([("A4", QPageSize.A4), ("A5", QPageSize.A5), ("A3", QPageSize.A3), ("Letter", QPageSize.Letter),
                      ("Legal", QPageSize.Legal)]).get(s.value("page/paper", "A4"), QPageSize.A4)
        printer.setPageSize(QPageSize(paper))
        printer.setPageOrientation(QPageLayout.Landscape if s.value("page/landscape", False, bool)
                                   else QPageLayout.Portrait)
        printer.setPageMargins(QMarginsF(float(s.value("page/left", 20.0)), float(s.value("page/top", 25.0)),
                                         float(s.value("page/right", 20.0)), float(s.value("page/bottom", 25.0))),
                               QPageLayout.Millimeter)
        printer.setDocName(self.display_name())
        return printer

    def print_dialog(self):
        printer = self._printer()
        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QDialog.Accepted:
            self.print_to(printer)

    def print_to(self, printer: QPrinter) -> int:
        s = self.settings
        doc = QTextDocument()
        doc.setPlainText(self.edit.toPlainText())
        doc.setDefaultFont(self.edit.font())
        painter = QPainter()
        if not painter.begin(printer):
            return 0
        doc.documentLayout().setPaintDevice(printer)
        page = printer.pageLayout().paintRectPixels(printer.resolution())
        fm = QFontMetricsF(self.edit.font(), printer)
        band = fm.height() * 2
        body = QRectF(0, band, page.width(), page.height() - 2 * band)
        doc.setPageSize(QSizeF(body.width(), body.height()))
        option = doc.defaultTextOption()
        option.setWrapMode(option.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(option)
        pages = max(1, doc.pageCount())
        header_fmt, footer_fmt = s.value("page/header", "&f"), s.value("page/footer", "Page &p")
        painter.setFont(self.edit.font())
        for n in range(pages):
            if n:
                printer.newPage()
            for fmt, y in ((header_fmt, 0), (footer_fmt, page.height() - fm.height())):
                left, centre, right = expand_header(fmt, self.display_name(), n + 1)
                r = QRectF(0, y, page.width(), fm.height())
                painter.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, left)
                painter.drawText(r, Qt.AlignHCenter | Qt.AlignVCenter, centre)
                painter.drawText(r, Qt.AlignRight | Qt.AlignVCenter, right)
            painter.save()
            painter.translate(0, band - n * body.height())
            doc.drawContents(painter, QRectF(0, n * body.height(), body.width(), body.height()))
            painter.restore()
        painter.end()
        return pages

    # ---- window ------------------------------------------------------------------------------
    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("size", self.size())
        e.accept()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if urls and self.maybe_save():
            self.open_path(urls[0])


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-notepad")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-notepad")
    print_only = False
    if argv and argv[0].lower() in ("/p", "-p", "--print"):
        print_only = True
        argv = argv[1:]
    files = [a for a in argv if not a.startswith("-")]
    from PySide6.QtCore import QUrl
    files = [QUrl(f).toLocalFile() if f.startswith("file://") else f for f in files]
    w = Notepad(files[0] if files else None)
    if print_only and files:
        printer = w._printer()
        w.print_to(printer)
        return 0
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
