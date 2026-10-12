"""Write: a word processor in the Word 2007 layout for Classic 7.

Opens .docx, .doc, .rtf, .txt and .html; saves .docx, .doc (as RTF, which Word opens),
.rtf, .odt, .pdf and .txt.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMimeData, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QImage,
                           QKeySequence, QPalette, QSyntaxHighlighter, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextDocumentWriter, QTextFormat, QTextImageFormat,
                           QTextLength, QTextListFormat, QTextOption, QTextTableFormat, QTextFrameFormat)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFontComboBox, QFormLayout, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox,
                               QStatusBar, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

import write_model as m
import write_ribbon as rb
from write_page import MARGINS, PAPER, PageEdit, PageSetup, print_document

APP = "Write"
OPEN_FILTER = ("All Word Documents (*.docx *.doc *.rtf);;Word Document (*.docx);;"
               "Word 97-2003 Document (*.doc);;Rich Text Format (*.rtf);;Text (*.txt);;"
               "Web Page (*.html *.htm);;All Files (*)")
SAVE_TYPES = [
    ("Word Document (*.docx)", ".docx"),
    ("Word 97-2003 Document (*.doc)", ".doc"),
    ("Rich Text Format (*.rtf)", ".rtf"),
    ("OpenDocument Text (*.odt)", ".odt"),
    ("PDF (*.pdf)", ".pdf"),
    ("Plain Text (*.txt)", ".txt"),
]
FONT_SIZES = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72]


# =============================================================================
# Spelling
# =============================================================================
class Speller(QSyntaxHighlighter):
    """Red wavy underline for unknown words (pyenchant; Danish and English dictionaries)."""

    WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)

    def __init__(self, doc):
        super().__init__(doc)
        self.dicts = []
        self.ignored = set()
        try:
            import enchant
            for tag in ("da_DK", "en_US", "en_GB"):
                try:
                    if enchant.dict_exists(tag):
                        self.dicts.append(enchant.Dict(tag))
                except Exception:   # noqa: BLE001
                    pass
        except ImportError:
            pass
        self.enabled = bool(self.dicts)
        self.fmt = QTextCharFormat()
        self.fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
        self.fmt.setUnderlineColor(QColor("#FF0000"))

    @property
    def available(self) -> bool:
        return bool(self.dicts)

    def ok(self, word: str) -> bool:
        if len(word) < 2 or word.lower() in self.ignored or word.isupper():
            return True
        return any(d.check(word) for d in self.dicts)

    def suggest(self, word: str) -> list[str]:
        out = []
        for d in self.dicts:
            for s in d.suggest(word)[:6]:
                if s not in out:
                    out.append(s)
        return out[:8]

    def add(self, word: str):
        if self.dicts:
            try:
                self.dicts[0].add(word)
            except Exception:   # noqa: BLE001
                self.ignored.add(word.lower())
        self.rehighlight()

    def highlightBlock(self, text: str):
        if not self.enabled or not self.dicts:
            return
        for mt in self.WORD.finditer(text):
            if not self.ok(mt.group()):
                self.setFormat(mt.start(), mt.end() - mt.start(), self.fmt)


# =============================================================================
# Editor with Word-like behaviour
# =============================================================================
class Editor(PageEdit):
    def __init__(self, window):
        super().__init__()
        self.win = window
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(window.context_menu)
        self.setMouseTracking(True)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData):
        if source.hasImage():
            self.win.insert_image(QImage(source.imageData()))
            return
        if source.hasUrls():
            imgs = [u.toLocalFile() for u in source.urls()
                    if u.isLocalFile() and Path(u.toLocalFile()).suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")]
            if imgs:
                for p in imgs:
                    self.win.insert_image(QImage(p))
                return
        super().insertFromMimeData(source)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.win._apply_painter()
        if e.modifiers() & Qt.ControlModifier:
            href = self.anchorAt(e.position().toPoint())
            if href:
                QDesktopServices.openUrl(QUrl(href))

    def keyPressEvent(self, e):
        # Tab in a list item indents it, like Word
        cur = self.textCursor()
        if e.key() in (Qt.Key_Tab, Qt.Key_Backtab) and cur.currentList() is not None and cur.atBlockStart():
            self.win.change_indent(+1 if e.key() == Qt.Key_Tab else -1)
            return
        super().keyPressEvent(e)


# =============================================================================
# Dialogs
# =============================================================================
class FindDialog(QDialog):
    def __init__(self, win, replace=False):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Find and Replace")
        form = QFormLayout()
        self.find = QLineEdit()
        self.repl = QLineEdit()
        self.case = QCheckBox("Match case")
        self.whole = QCheckBox("Find whole words only")
        form.addRow("Fi&nd what:", self.find)
        form.addRow("Replace w&ith:", self.repl)
        buttons = QHBoxLayout()
        self.b_next = QPushButton("&Find Next")
        self.b_repl = QPushButton("&Replace")
        self.b_all = QPushButton("Replace &All")
        close = QPushButton("Cancel")
        for b in (self.b_next, self.b_repl, self.b_all, close):
            buttons.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.case)
        lay.addWidget(self.whole)
        lay.addLayout(buttons)
        self.b_next.setDefault(True)
        self.b_next.clicked.connect(self.next)
        self.b_repl.clicked.connect(self.replace_one)
        self.b_all.clicked.connect(self.replace_all)
        close.clicked.connect(self.close)
        self.set_mode(replace)

    def set_mode(self, replace: bool):
        self.repl.setVisible(replace)
        self.layout().itemAt(0).layout().labelForField(self.repl).setVisible(replace)
        self.b_repl.setVisible(replace)
        self.b_all.setVisible(replace)

    def flags(self):
        f = QTextDocument.FindFlag(0)
        if self.case.isChecked():
            f |= QTextDocument.FindCaseSensitively
        if self.whole.isChecked():
            f |= QTextDocument.FindWholeWords
        return f

    def next(self) -> bool:
        ed = self.win.editor
        text = self.find.text()
        if not text:
            return False
        found = ed.document().find(text, ed.textCursor(), self.flags())
        if found.isNull():
            found = ed.document().find(text, 0, self.flags())
            if found.isNull():
                QMessageBox.information(self, APP, f"{APP} has finished searching the document. "
                                                   f"The search item was not found.")
                return False
        ed.setTextCursor(found)
        return True

    def replace_one(self):
        ed = self.win.editor
        c = ed.textCursor()
        sel = c.selectedText()
        same = sel == self.find.text() if self.case.isChecked() else sel.lower() == self.find.text().lower()
        if c.hasSelection() and same:
            c.insertText(self.repl.text())
        self.next()

    def replace_all(self):
        ed = self.win.editor
        text = self.find.text()
        if not text:
            return
        n = 0
        c = QTextCursor(ed.document())
        c.beginEditBlock()
        pos = ed.document().find(text, 0, self.flags())
        while not pos.isNull():
            pos.insertText(self.repl.text())
            n += 1
            pos = ed.document().find(text, pos, self.flags())
        c.endEditBlock()
        QMessageBox.information(self, APP, f"{APP} has completed its search of the document "
                                           f"and has made {n} replacement{'s' if n != 1 else ''}.")


class PageSetupDialog(QDialog):
    def __init__(self, setup: PageSetup, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Page Setup")
        self.s = PageSetup(**setup.__dict__)
        form = QFormLayout(self)
        self.spins = {}
        for key, label in (("top", "&Top:"), ("bottom", "&Bottom:"), ("left", "&Left:"), ("right", "&Right:")):
            sp = QDoubleSpinBox()
            sp.setRange(0, 120)
            sp.setDecimals(1)
            sp.setSuffix(" cm")
            sp.setSingleStep(0.1)
            sp.setValue(getattr(setup, key) / 10)
            form.addRow(label, sp)
            self.spins[key] = sp
        self.paper = QComboBox()
        self.paper.addItems(list(PAPER))
        self.paper.setCurrentText(setup.paper)
        form.addRow("Paper si&ze:", self.paper)
        self.orient = QComboBox()
        self.orient.addItems(["Portrait", "Landscape"])
        self.orient.setCurrentIndex(1 if setup.landscape else 0)
        form.addRow("&Orientation:", self.orient)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def result_setup(self) -> PageSetup:
        for k, sp in self.spins.items():
            setattr(self.s, k, sp.value() * 10)
        self.s.paper = self.paper.currentText()
        self.s.custom_size = None
        self.s.landscape = self.orient.currentIndex() == 1
        return self.s


# =============================================================================
# Main window
# =============================================================================
class WriteWindow(QMainWindow):
    untitled_counter = 0

    def __init__(self, path: str | None = None):
        super().__init__()
        self.path: str | None = None
        self.settings = QSettings("Classic7", "Write")
        WriteWindow.untitled_counter += 1
        self.untitled = f"Document{WriteWindow.untitled_counter}"
        self.painter_format: QTextCharFormat | None = None
        self.find_dialog: FindDialog | None = None
        self.setWindowIcon(rb.icon(["x-office-document", "accessories-text-editor"], "W", 32))

        self.editor = Editor(self)
        self.editor.setDocument(m.new_document())
        self.speller = Speller(self.editor.document())
        self.setCentralWidget(self.editor)

        self._actions()
        self._ribbon()
        self._status()
        self._connect_document()
        self.resize(1100, 820)
        if path:
            self.open_path(path)
        self._update_title()
        self.editor.setFocus()

    # ---- actions ----------------------------------------------------------------------------
    def act(self, text, slot=None, shortcut=None, icon=None, fallback="", checkable=False, tip=None, **kw):
        a = QAction(text, self)
        if icon is not None or fallback:
            a.setIcon(icon if isinstance(icon, QIcon) else rb.icon(icon or [], fallback or text[:1], **kw))
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, list) else [shortcut])])
        if slot:
            a.triggered.connect(slot)
        a.setCheckable(checkable)
        tip_text = (tip or text.replace("&", ""))
        if shortcut:
            first = shortcut[0] if isinstance(shortcut, list) else shortcut
            tip_text += f" ({QKeySequence(first).toString(QKeySequence.NativeText)})"
        a.setToolTip(tip_text)
        self.addAction(a)
        return a

    def _actions(self):
        e = self.editor
        A = self.act
        self.a_new = A("&New", self.file_new, "Ctrl+N", "document-new", "N")
        self.a_open = A("&Open...", self.file_open, "Ctrl+O", "document-open", "O")
        self.a_save = A("&Save", self.file_save, "Ctrl+S", "document-save", "S")
        self.a_saveas = A("Save &As...", self.file_save_as, "F12", "document-save-as", "A")
        self.a_print = A("&Print...", self.file_print, "Ctrl+P", "document-print", "P")
        self.a_preview = A("Print Pre&view", self.file_preview, "Ctrl+F2", "document-print-preview", "V")
        self.a_pdf = A("Save as &PDF...", lambda: self.file_save_as(".pdf"), None, "application-pdf", "PDF")
        self.a_close = A("&Close", self.close, "Ctrl+W", "document-close", "X")
        self.a_undo = A("&Undo", e.undo, "Ctrl+Z", "edit-undo", "↶")
        self.a_redo = A("&Redo", e.redo, ["Ctrl+Y", "Ctrl+Shift+Z"], "edit-redo", "↷")
        self.a_cut = A("Cu&t", e.cut, "Ctrl+X", "edit-cut", "✂")
        self.a_copy = A("&Copy", e.copy, "Ctrl+C", "edit-copy", "C")
        self.a_paste = A("&Paste", e.paste, "Ctrl+V", "edit-paste", "P", size=rb.BIG)
        self.a_paste_text = A("Paste as Unformatted &Text", self.paste_text, "Ctrl+Shift+V", "edit-paste", "T")
        self.a_painter = A("Format Painter", self.format_painter, "Ctrl+Shift+C", "format-stroke-color",
                           "🖌", checkable=True)
        self.a_select_all = A("Select &All", e.selectAll, "Ctrl+A", "edit-select-all", "A")
        self.a_find = A("&Find", lambda: self.show_find(False), "Ctrl+F", "edit-find", "F")
        self.a_replace = A("R&eplace", lambda: self.show_find(True), "Ctrl+H", "edit-find-replace", "R")

        self.a_bold = A("Bold", self.toggle_bold, "Ctrl+B", "format-text-bold", "B", checkable=True)
        self.a_italic = A("Italic", lambda on: self.merge(italic=on), "Ctrl+I", "format-text-italic", "I",
                          checkable=True, italic=True)
        self.a_underline = A("Underline", lambda on: self.merge(underline=on), "Ctrl+U", "format-text-underline",
                             "U", checkable=True, underline="#000000", bold=False)
        self.a_strike = A("Strikethrough", lambda on: self.merge(strike=on), None, "format-text-strikethrough",
                          "abc", checkable=True, strike=True, bold=False)
        self.a_sub = A("Subscript", lambda on: self.valign(QTextCharFormat.AlignSubScript if on else None),
                       "Ctrl+=", "format-text-subscript", "x₂", checkable=True, bold=False)
        self.a_sup = A("Superscript", lambda on: self.valign(QTextCharFormat.AlignSuperScript if on else None),
                       "Ctrl+Shift+=", "format-text-superscript", "x²", checkable=True, bold=False)
        self.a_grow = A("Grow Font", lambda: self.step_size(+1), ["Ctrl+Shift+>", "Ctrl+]"], "format-font-size-more", "A⁺")
        self.a_shrink = A("Shrink Font", lambda: self.step_size(-1), ["Ctrl+Shift+<", "Ctrl+["], "format-font-size-less", "A⁻")
        self.a_clear = A("Clear Formatting", self.clear_formatting, "Ctrl+Space", "edit-clear-all", "⌫")
        self.a_color = A("Font Color", self.apply_last_color, None, None, "A", underline="#C00000", bold=True)
        self.a_highlight = A("Text Highlight Color", self.apply_last_highlight, None, None, "ab",
                             underline="#FFFF00", bold=False)
        self.last_color = QColor("#C00000")
        self.last_highlight = QColor("#FFFF00")

        align = QActionGroup(self)
        self.a_left = A("Align Text Left", lambda: self.align(Qt.AlignLeft), "Ctrl+L", "format-justify-left", "≡", checkable=True)
        self.a_center = A("Center", lambda: self.align(Qt.AlignHCenter), "Ctrl+E", "format-justify-center", "≡", checkable=True)
        self.a_right = A("Align Text Right", lambda: self.align(Qt.AlignRight), "Ctrl+R", "format-justify-right", "≡", checkable=True)
        self.a_justify = A("Justify", lambda: self.align(Qt.AlignJustify), "Ctrl+J", "format-justify-fill", "≡", checkable=True)
        for a in (self.a_left, self.a_center, self.a_right, self.a_justify):
            align.addAction(a)
        self.a_bullets = A("Bullets", lambda on: self.toggle_list("bullet", on), None, "format-list-unordered", "•", checkable=True)
        self.a_numbering = A("Numbering", lambda on: self.toggle_list("decimal", on), None, "format-list-ordered", "1.", checkable=True)
        self.a_indent_less = A("Decrease Indent", lambda: self.change_indent(-1), None, "format-indent-less", "⇤")
        self.a_indent_more = A("Increase Indent", lambda: self.change_indent(+1), None, "format-indent-more", "⇥")
        self.a_marks = A("Show/Hide ¶", self.toggle_marks, "Ctrl+Shift+8", None, "¶", checkable=True)

        self.a_pagebreak = A("Page Break", self.insert_page_break, "Ctrl+Return", "insert-page-break", "⤓", size=rb.BIG)
        self.a_table = A("Table", self.table_dialog, None, ["insert-table", "table"], "▦", size=rb.BIG)
        self.a_picture = A("Picture", self.picture_dialog, None, ["insert-image", "image-x-generic"], "🖼", size=rb.BIG)
        self.a_link = A("Hyperlink", self.hyperlink_dialog, "Ctrl+K", ["insert-link", "link"], "🔗", size=rb.BIG)
        self.a_header = A("Header", lambda: self.edit_header_footer("header"), None, ["view-split-top-bottom", "go-top"], "▔", size=rb.BIG)
        self.a_footer = A("Footer", lambda: self.edit_header_footer("footer"), None, ["view-split-top-bottom", "go-bottom"], "▁", size=rb.BIG)
        self.a_pagenum = A("Page Number", self.page_numbers, None, ["format-number-percent", "view-list-text"], "#", size=rb.BIG)
        self.a_date = A("Date & Time", self.insert_date, "Alt+Shift+D", ["view-calendar", "x-office-calendar"], "📅", size=rb.BIG)
        self.a_hr = A("Horizontal Line", self.insert_hr, None, None, "—", size=rb.BIG)
        self.a_symbol = A("Symbol", None, None, None, "Ω", size=rb.BIG)

        self.a_margins = A("Margins", None, None, ["document-page-setup", "page-simple"], "▭", size=rb.BIG)
        self.a_orient = A("Orientation", None, None, ["object-rotate-right", "transform-rotate"], "⤾", size=rb.BIG)
        self.a_size = A("Size", None, None, ["document-properties", "zoom-fit-page"], "A4", size=rb.BIG)
        self.a_pagesetup = A("Page Setup...", self.page_setup_dialog, None, "document-page-setup", "⚙")

        self.a_spell = A("Spelling", self.toggle_spelling, "F7", ["tools-check-spelling", "spellcheck"], "ABC✓",
                         checkable=True, size=rb.BIG)
        self.a_count = A("Word Count", self.word_count, "Ctrl+Shift+G", ["accessories-calculator", "view-statistics"], "123", size=rb.BIG)

        views = QActionGroup(self)
        self.a_print_layout = A("Print Layout", lambda: self.set_draft(False), None, ["view-pages", "document-preview"], "▯", checkable=True, size=rb.BIG)
        self.a_draft = A("Draft", lambda: self.set_draft(True), None, ["view-list-text", "format-justify-left"], "≣", checkable=True, size=rb.BIG)
        views.addAction(self.a_print_layout)
        views.addAction(self.a_draft)
        self.a_print_layout.setChecked(True)

        styles = [("Normal", "Ctrl+Shift+N"), ("Heading 1", "Ctrl+Alt+1"), ("Heading 2", "Ctrl+Alt+2"),
                  ("Heading 3", "Ctrl+Alt+3")]
        for name, key in styles:
            A(f"Style {name}", lambda _=False, n=name: self.set_style(n), key)
        for key, val in (("Ctrl+1", 100), ("Ctrl+5", 150), ("Ctrl+2", 200)):
            A(f"Line spacing {val}", lambda _=False, v=val: self.line_spacing(v), key)

        e.undoAvailable.connect(self.a_undo.setEnabled)
        e.redoAvailable.connect(self.a_redo.setEnabled)
        e.copyAvailable.connect(self.a_cut.setEnabled)
        e.copyAvailable.connect(self.a_copy.setEnabled)
        self.a_undo.setEnabled(False)
        self.a_redo.setEnabled(False)
        self.a_cut.setEnabled(False)
        self.a_copy.setEnabled(False)

    # ---- ribbon -----------------------------------------------------------------------------
    def _ribbon(self):
        top, v = self._ribbon_top()
        r = rb.Ribbon()
        self.ribbon = r

        # Home
        home = r.add_tab("Home")
        self._group_clipboard(r, home)
        self._group_font(r, home)
        self._group_paragraph(r, home)
        self._group_styles(r, home)
        self._group_editing(r, home)

        # Insert
        ins = r.add_tab("Insert")
        g = r.group(ins, "Pages")
        g.add(rb.big_button(self.a_pagebreak))
        self._group_tables(r, ins)
        g = r.group(ins, "Illustrations")
        g.add(rb.big_button(self.a_picture))
        g = r.group(ins, "Links")
        g.add(rb.big_button(self.a_link))
        g = r.group(ins, "Header & Footer")
        for a in (self.a_header, self.a_footer, self.a_pagenum):
            g.add(rb.big_button(a))
        g = r.group(ins, "Text")
        g.add(rb.big_button(self.a_date))
        g.add(rb.big_button(self.a_hr))
        g = r.group(ins, "Symbols")
        g.add(rb.big_button(self.a_symbol, rb.symbol_menu(self, self.insert_text)))
        # Page Layout
        pl = r.add_tab("Page Layout")
        g = r.group(pl, "Page Setup")
        mm = QMenu(self)
        for name, vals in MARGINS.items():
            t_, b_, l_, r_ = vals
            mm.addAction(f"{name}   (Top {t_ / 10:.2f} cm, Left {l_ / 10:.2f} cm)",
                         lambda vals=vals: self.set_margins(*vals))
        mm.addSeparator()
        mm.addAction("Custom Margins...", self.page_setup_dialog)
        g.add(rb.big_button(self.a_margins, mm))
        om = QMenu(self)
        om.addAction("Portrait", lambda: self.set_orientation(False))
        om.addAction("Landscape", lambda: self.set_orientation(True))
        g.add(rb.big_button(self.a_orient, om))
        sm = QMenu(self)
        for name, (w, h) in PAPER.items():
            sm.addAction(f"{name}   {w / 10:.1f} cm x {h / 10:.1f} cm", lambda name=name: self.set_paper(name))
        g.add(rb.big_button(self.a_size, sm))
        bm = QMenu(self)
        bm.addAction(self.a_pagebreak)
        a_breaks = self.act("Breaks", None, None, "insert-page-break", "⤓", size=rb.BIG)
        g.add(rb.big_button(a_breaks, bm))
        g.add_column([rb.small_button(self.a_pagesetup, with_text=True)])

        # Review
        rv = r.add_tab("Review")
        self._group_proofing(r, rv)

        # View
        vw = r.add_tab("View")
        g = r.group(vw, "Document Views")
        g.add(rb.big_button(self.a_print_layout))
        g.add(rb.big_button(self.a_draft))
        g = r.group(vw, "Show/Hide")
        g.add_column([rb.small_button(self.a_marks, with_text=True)])

        self._ribbon_finish(top, v, r)

    def _ribbon_top(self):
        """The Office button and Quick Access Toolbar row; returns (widget, its layout)."""
        top = QWidget()
        v = QVBoxLayout(top)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        qat = QHBoxLayout()
        qat.setContentsMargins(4, 2, 4, 0)
        qat.setSpacing(1)
        self.office = QToolButton()
        self.office.setObjectName("orb")
        self.office.setIcon(rb.office_orb(36))
        self.office.setIconSize(QSize(36, 36))
        self.office.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.office.setPopupMode(QToolButton.InstantPopup)
        self.office.setToolTip("Office Button\nNew, Open, Save, Print, Close")
        self.office.setMenu(self._office_menu())
        self.office.setAutoRaise(True)
        qat.addWidget(self.office)
        qat.addSpacing(4)
        for a in self._qat_actions():
            qat.addWidget(rb.small_button(a))
        qat.addStretch(1)
        v.addLayout(qat)
        return top, v

    def _qat_actions(self):
        return [self.a_save, self.a_undo, self.a_redo]

    def _ribbon_finish(self, top, v, r):
        v.addWidget(r)
        self.ribbon_top = top
        rb.apply_scheme(top, r, self.settings.value("ribbon/scheme", "blue"))
        self.setMenuWidget(top)

    def _group_clipboard(self, r, tab):
        g = r.group(tab, "Clipboard")
        paste_menu = QMenu(self)
        paste_menu.addAction(self.a_paste)
        paste_menu.addAction(self.a_paste_text)
        self.a_paste.setData("split")
        g.add(rb.big_button(self.a_paste, paste_menu))
        g.add_column([rb.small_button(self.a_cut, with_text=True)], [rb.small_button(self.a_copy, with_text=True)],
                     [rb.small_button(self.a_painter, with_text=True)])
        return g

    def _group_font(self, r, tab):
        g = r.group(tab, "Font")
        self.font_box = QFontComboBox()
        self.font_box.setMaximumWidth(170)
        self.font_box.setMinimumWidth(120)
        self.font_box.textActivated.connect(self.set_family)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in FONT_SIZES])
        self.size_box.setMaximumWidth(60)
        self.size_box.setMinimumWidth(54)
        self.size_box.textActivated.connect(self.set_size)
        self.size_box.lineEdit().returnPressed.connect(lambda: self.set_size(self.size_box.currentText()))
        case_menu = QMenu(self)
        for label, mode in (("Sentence case.", "sentence"), ("lowercase", "lower"), ("UPPERCASE", "upper"),
                            ("Capitalize Each Word", "title"), ("tOGGLE cASE", "toggle")):
            case_menu.addAction(label, lambda mode=mode: self.change_case(mode))
        a_case = self.act("Change Case", None, "Shift+F3", None, "Aa", bold=False)
        a_case.triggered.connect(lambda: self.change_case("cycle"))
        color_menu = rb.color_menu(self, rb.WORD_COLORS, 10, self.set_color, "Automatic")
        hl_menu = rb.color_menu(self, rb.HIGHLIGHT_COLORS, 5, self.set_highlight, "No Color")
        g.add_column(
            [self.font_box, self.size_box, rb.small_button(self.a_grow), rb.small_button(self.a_shrink),
             rb.small_button(self.a_clear)],
            [rb.small_button(self.a_bold), rb.small_button(self.a_italic), rb.small_button(self.a_underline),
             rb.small_button(self.a_strike), rb.small_button(self.a_sub), rb.small_button(self.a_sup),
             rb.small_button(a_case, case_menu, split=True),
             rb.small_button(self.a_highlight, hl_menu, split=True),
             rb.small_button(self.a_color, color_menu, split=True)])
        return g

    def _group_paragraph(self, r, tab):
        g = r.group(tab, "Paragraph")
        spacing_menu = QMenu(self)
        for v_ in (100, 115, 150, 200, 250, 300):
            spacing_menu.addAction(f"{v_ / 100:.2g}".rstrip("0").rstrip(".") if v_ != 115 else "1.15",
                                   lambda v_=v_: self.line_spacing(v_))
        spacing_menu.addSeparator()
        spacing_menu.addAction("Add Space Before Paragraph", lambda: self.paragraph_space(before=12))
        spacing_menu.addAction("Remove Space After Paragraph", lambda: self.paragraph_space(after=0))
        a_spacing = self.act("Line Spacing", None, None, ["format-line-spacing-normal", "format-line-spacing-double"], "↕")
        num_menu = QMenu(self)
        for label, kind in (("1. 2. 3.", "decimal"), ("a. b. c.", "lower"), ("A. B. C.", "upper"), ("i. ii. iii.", "roman")):
            num_menu.addAction(label, lambda kind=kind: self.toggle_list(kind, True))
        bullet_menu = QMenu(self)
        for label, kind in (("• Round", "bullet"),):
            bullet_menu.addAction(label, lambda kind=kind: self.toggle_list(kind, True))
        g.add_column(
            [rb.small_button(self.a_bullets, bullet_menu, split=True), rb.small_button(self.a_numbering, num_menu, split=True),
             rb.small_button(self.a_indent_less), rb.small_button(self.a_indent_more), rb.small_button(self.a_marks)],
            [rb.small_button(self.a_left), rb.small_button(self.a_center), rb.small_button(self.a_right),
             rb.small_button(self.a_justify), rb.small_button(a_spacing, spacing_menu)])
        return g

    def _group_styles(self, r, tab):
        g = r.group(tab, "Styles")
        self.style_buttons = {}
        quick = ["Normal", "No Spacing", "Heading 1", "Heading 2", "Title", "Subtitle"]
        rows = [[], []]
        for i, name in enumerate(quick):
            st = m.STYLE_BY_NAME[name]
            b = QToolButton()
            b.setText(name)
            b.setCheckable(True)
            b.setAutoRaise(True)
            f = QFont(st.font)
            f.setPointSizeF(min(11.0, max(8.0, st.size * 0.75)))
            f.setBold(st.bold)
            f.setItalic(st.italic)
            b.setFont(f)
            b.setStyleSheet(f"QToolButton {{ color: {st.color}; padding: 2px 6px; }}")
            b.setMinimumWidth(78)
            b.clicked.connect(lambda _=False, n=name: self.set_style(n))
            self.style_buttons[name] = b
            rows[i // 3].append(b)
        more = QMenu(self)
        for st in m.STYLES:
            more.addAction(st.name, lambda n=st.name: self.set_style(n))
        mb = QToolButton()
        mb.setText("More")
        mb.setPopupMode(QToolButton.InstantPopup)
        mb.setMenu(more)
        mb.setAutoRaise(True)
        rows[0].append(mb)
        g.add_column(*rows)
        return g

    def _group_editing(self, r, tab):
        g = r.group(tab, "Editing")
        select_menu = QMenu(self)
        select_menu.addAction(self.a_select_all)
        a_select = self.act("Select", None, None, "edit-select", "⬚")
        g.add_column([rb.small_button(self.a_find, with_text=True)], [rb.small_button(self.a_replace, with_text=True)],
                     [rb.small_button(a_select, select_menu, with_text=True)])
        return g

    def _group_tables(self, r, tab):
        g = r.group(tab, "Tables")
        table_menu = QMenu(self)
        grid = rb.TableGrid()
        grid.picked.connect(lambda rr, cc: (table_menu.close(), self.insert_table(rr, cc)))
        ga = QWidgetAction(table_menu)
        ga.setDefaultWidget(grid)
        table_menu.addAction(ga)
        table_menu.addSeparator()
        table_menu.addAction("Insert Table...", self.table_dialog)
        g.add(rb.big_button(self.a_table, table_menu))
        return g

    def _group_proofing(self, r, tab):
        g = r.group(tab, "Proofing")
        g.add(rb.big_button(self.a_spell))
        g.add(rb.big_button(self.a_count))
        if not self.speller.available:
            self.a_spell.setToolTip("Spelling: no dictionaries installed")
        return g

    def _office_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self.a_new)
        menu.addAction(self.a_open)
        menu.addAction(self.a_save)
        save_as = menu.addMenu(rb.icon("document-save-as", "A"), "Save &As")
        for label, ext in SAVE_TYPES:
            save_as.addAction(label.split(" (")[0], lambda ext=ext: self.file_save_as(ext))
        menu.addSeparator()
        menu.addAction(self.a_print)
        menu.addAction(self.a_preview)
        send = menu.addMenu(rb.icon(["mail-send", "mail-message-new"], "@"), "Sen&d")
        send.addAction(rb.icon(["mail-message-new"], "@"), "&E-mail", lambda: self.send_by_mail(".docx"))
        send.addAction(rb.icon(["application-pdf"], "PDF"), "E-mail as &PDF Attachment",
                       lambda: self.send_by_mail(".pdf"))
        menu.addSeparator()
        self.recent_menu = menu.addMenu(rb.icon("document-open-recent", "R"), "&Recent Documents")
        self._fill_recent()
        menu.addSeparator()
        schemes = menu.addMenu(rb.icon("preferences-desktop-color", "C"), "Color &Scheme")
        group = QActionGroup(schemes)
        current = self.settings.value("ribbon/scheme", "blue")
        for key, label in rb.SCHEME_NAMES.items():
            a = schemes.addAction(label, lambda key=key: self.set_ribbon_scheme(key))
            a.setCheckable(True)
            a.setChecked(key == current)
            group.addAction(a)
        menu.addSeparator()
        menu.addAction(self.a_close)
        menu.addAction(rb.icon("application-exit", "X"), f"E&xit {APP}", QApplication.closeAllWindows)
        return menu

    def set_ribbon_scheme(self, key: str):
        self.settings.setValue("ribbon/scheme", key)
        for w in QApplication.topLevelWidgets():
            if isinstance(w, WriteWindow):
                rb.apply_scheme(w.ribbon_top, w.ribbon, key)

    def _fill_recent(self):
        self.recent_menu.clear()
        files = [f for f in self.settings.value("recent", [], list) or [] if os.path.exists(f)]
        for i, f in enumerate(files[:9]):
            self.recent_menu.addAction(f"&{i + 1} {Path(f).name}", lambda f=f: self.open_maybe_new(f))
        self.recent_menu.setEnabled(bool(files))

    def _add_recent(self, path: str):
        files = [path] + [f for f in (self.settings.value("recent", [], list) or []) if f != path]
        self.settings.setValue("recent", files[:9])
        self._fill_recent()

    def _status(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.lbl_page = QLabel()
        self.lbl_words = QLabel()
        self.lbl_info = QLabel()
        for w in (self.lbl_page, self.lbl_words):
            w.setFrameShape(QLabel.Panel)
            w.setFrameShadow(QLabel.Sunken)
            w.setContentsMargins(4, 0, 4, 0)
        sb.addWidget(self.lbl_page)
        sb.addWidget(self.lbl_words)
        sb.addWidget(self.lbl_info, 1)
        for a in (self.a_print_layout, self.a_draft):
            b = rb.small_button(a)
            b.setIconSize(QSize(16, 16))
            sb.addPermanentWidget(b)
        self.word_timer = QTimer(self, singleShot=True, interval=400, timeout=self._update_words)

    # ---- document wiring ----------------------------------------------------------------------
    def _connect_document(self):
        e = self.editor
        doc = e.document()
        e.currentCharFormatChanged.connect(self._char_changed)
        e.cursorPositionChanged.connect(self._cursor_changed)
        e.pageChanged.connect(lambda p, n: self.lbl_page.setText(f"Page: {p} of {n}"))
        doc.contentsChanged.connect(self.word_timer.start)
        doc.modificationChanged.connect(lambda _m: self._update_title())
        self._char_changed(e.currentCharFormat())
        self._cursor_changed()
        self._update_words()

    def set_document(self, doc: QTextDocument, setup: PageSetup):
        self.editor.setDocument(doc)
        self.editor.apply_setup(setup)
        doc.clearUndoRedoStacks()
        self.speller.setDocument(doc)
        self._connect_document()
        self._update_title()

    def _update_title(self):
        name = Path(self.path).name if self.path else self.untitled
        mod = " *" if self.editor.document().isModified() else ""
        self.setWindowTitle(f"{name}{mod} - {APP}")

    def _update_words(self):
        text = self.editor.toPlainText()
        words = len(re.findall(r"\S+", text))
        self.lbl_words.setText(f"Words: {words}")

    def _char_changed(self, cf: QTextCharFormat):
        fams = cf.fontFamilies()
        fam = fams[0] if fams else self.editor.document().defaultFont().family()
        self.font_box.blockSignals(True)
        self.font_box.setCurrentFont(QFont(fam))
        self.font_box.setEditText(fam)
        self.font_box.blockSignals(False)
        size = cf.fontPointSize() or self.editor.document().defaultFont().pointSizeF()
        self.size_box.blockSignals(True)
        self.size_box.setEditText(f"{size:g}")
        self.size_box.blockSignals(False)
        for a, on in ((self.a_bold, cf.fontWeight() >= QFont.DemiBold), (self.a_italic, cf.fontItalic()),
                      (self.a_underline, cf.fontUnderline()), (self.a_strike, cf.fontStrikeOut()),
                      (self.a_sub, cf.verticalAlignment() == QTextCharFormat.AlignSubScript),
                      (self.a_sup, cf.verticalAlignment() == QTextCharFormat.AlignSuperScript)):
            a.blockSignals(True)
            a.setChecked(bool(on))
            a.blockSignals(False)

    def _cursor_changed(self):
        c = self.editor.textCursor()
        al = c.blockFormat().alignment()
        target = (self.a_center if al & Qt.AlignHCenter else self.a_right if al & Qt.AlignRight
                  else self.a_justify if al & Qt.AlignJustify else self.a_left)
        target.setChecked(True)
        lst = c.currentList()
        self.a_bullets.blockSignals(True)
        self.a_numbering.blockSignals(True)
        self.a_bullets.setChecked(lst is not None and m.list_kind(lst.format()) == "bullet")
        self.a_numbering.setChecked(lst is not None and m.list_kind(lst.format()) != "bullet")
        self.a_bullets.blockSignals(False)
        self.a_numbering.blockSignals(False)
        style = m.block_style(c.block())
        for name, b in self.style_buttons.items():
            b.setChecked(name == style)

    # ---- formatting -------------------------------------------------------------------------
    def merge(self, cf: QTextCharFormat | None = None, **kw):
        cf = cf or QTextCharFormat()
        if "italic" in kw:
            cf.setFontItalic(kw["italic"])
        if "underline" in kw:
            cf.setFontUnderline(kw["underline"])
        if "strike" in kw:
            cf.setFontStrikeOut(kw["strike"])
        c = self.editor.textCursor()
        if not c.hasSelection():
            # Word formats the whole word under the cursor when nothing is selected
            probe = QTextCursor(c)
            probe.select(QTextCursor.WordUnderCursor)
            if probe.hasSelection() and probe.selectionStart() < c.position() < probe.selectionEnd():
                probe.mergeCharFormat(cf)
        c.mergeCharFormat(cf)
        self.editor.mergeCurrentCharFormat(cf)
        self.editor.setFocus()

    def toggle_bold(self, on):
        cf = QTextCharFormat()
        cf.setFontWeight(QFont.Bold if on else QFont.Normal)
        self.merge(cf)

    def valign(self, va):
        cf = QTextCharFormat()
        cf.setVerticalAlignment(va if va is not None else QTextCharFormat.AlignNormal)
        if va == QTextCharFormat.AlignSubScript:
            self.a_sup.setChecked(False)
        elif va == QTextCharFormat.AlignSuperScript:
            self.a_sub.setChecked(False)
        self.merge(cf)

    def set_family(self, fam: str):
        cf = QTextCharFormat()
        cf.setFontFamilies([fam])
        self.merge(cf)

    def set_size(self, text: str):
        try:
            size = float(str(text).replace(",", "."))
        except ValueError:
            return
        if 1 <= size <= 1638:
            cf = QTextCharFormat()
            cf.setFontPointSize(size)
            self.merge(cf)

    def step_size(self, direction: int):
        cur = self.editor.currentCharFormat().fontPointSize() or 11
        sizes = FONT_SIZES
        if direction > 0:
            new = next((s for s in sizes if s > cur), cur + 10)
        else:
            new = next((s for s in reversed(sizes) if s < cur), max(1, cur - 1))
        self.set_size(str(new))

    def clear_formatting(self):
        c = self.editor.textCursor()
        st = m.STYLE_BY_NAME.get(m.block_style(c.block()), m.STYLES[0])
        cf = m.style_char_format(st)
        cf.setFontUnderline(False)
        cf.setFontStrikeOut(False)
        cf.setVerticalAlignment(QTextCharFormat.AlignNormal)
        cf.clearBackground()
        if c.hasSelection():
            c.setCharFormat(cf)
        self.editor.setCurrentCharFormat(cf)

    def set_color(self, color: QColor):
        cf = QTextCharFormat()
        cf.setForeground(color if color.isValid() else QColor("#000000"))
        if color.isValid():
            self.last_color = color
            self.a_color.setIcon(rb.text_icon("A", underline=color.name()))
        self.merge(cf)

    def apply_last_color(self):
        self.set_color(self.last_color)

    def set_highlight(self, color: QColor):
        c = self.editor.textCursor()
        if not c.hasSelection():
            self.statusBar().showMessage("Select the text to highlight first.", 4000)
            if color.isValid():
                self.last_highlight = color
                self.a_highlight.setIcon(rb.text_icon("ab", underline=color.name(), bold=False))
            return
        cf = QTextCharFormat()
        if color.isValid():
            cf.setBackground(color)
            self.last_highlight = color
            self.a_highlight.setIcon(rb.text_icon("ab", underline=color.name(), bold=False))
            c.mergeCharFormat(cf)
        else:
            # remove highlight: rebuild the selection's formats without a background
            c.beginEditBlock()
            start, end = c.selectionStart(), c.selectionEnd()
            pos = start
            while pos < end:
                cc = QTextCursor(self.editor.document())
                cc.setPosition(pos)
                cc.setPosition(pos + 1, QTextCursor.KeepAnchor)
                f = cc.charFormat()
                f.clearBackground()
                cc.setCharFormat(f)
                pos += 1
            c.endEditBlock()

    def apply_last_highlight(self):
        self.set_highlight(self.last_highlight)

    def change_case(self, mode: str):
        c = self.editor.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.WordUnderCursor)
        text = c.selectedText()
        if not text:
            return
        if mode == "cycle":
            mode = "upper" if text.islower() else "title" if text.isupper() else "lower"
        new = {"lower": text.lower(), "upper": text.upper(), "title": text.title(),
               "toggle": text.swapcase(),
               "sentence": text[:1].upper() + text[1:].lower()}[mode]
        start = c.selectionStart()
        # keep formatting: replace character by character
        c.beginEditBlock()
        for i, ch in enumerate(new):
            cc = QTextCursor(self.editor.document())
            cc.setPosition(start + i)
            cc.setPosition(start + i + 1, QTextCursor.KeepAnchor)
            if cc.selectedText() != ch:
                cc.insertText(ch, cc.charFormat())
        c.endEditBlock()
        c.setPosition(start)
        c.setPosition(start + len(new), QTextCursor.KeepAnchor)
        self.editor.setTextCursor(c)

    def format_painter(self, on):
        if on:
            self.painter_format = self.editor.currentCharFormat()
            self.statusBar().showMessage("Format Painter: select the text to format.", 5000)
            self.editor.viewport().setCursor(Qt.PointingHandCursor)
        else:
            self.painter_format = None
            self.editor.viewport().setCursor(Qt.IBeamCursor)

    def _apply_painter(self):
        if self.painter_format is not None and self.editor.textCursor().hasSelection():
            self.editor.textCursor().mergeCharFormat(self.painter_format)
            self.a_painter.setChecked(False)
            self.format_painter(False)

    def align(self, al):
        self.editor.setAlignment(al)

    def set_style(self, name: str):
        m.apply_style(self.editor.textCursor(), name)
        self._cursor_changed()
        self._char_changed(self.editor.currentCharFormat())
        self.editor.setFocus()

    def line_spacing(self, pct: int):
        c = self.editor.textCursor()
        bf = QTextBlockFormat()
        bf.setLineHeight(pct, m.PROPORTIONAL)
        c.mergeBlockFormat(bf)

    def paragraph_space(self, before=None, after=None):
        bf = QTextBlockFormat()
        if before is not None:
            bf.setTopMargin(before * m.PT)
        if after is not None:
            bf.setBottomMargin(after * m.PT)
        self.editor.textCursor().mergeBlockFormat(bf)

    def toggle_list(self, kind: str, on: bool):
        c = self.editor.textCursor()
        c.beginEditBlock()
        lst = c.currentList()
        if not on or (lst is not None and m.list_kind(lst.format()) == kind and self.sender() in
                      (self.a_bullets, self.a_numbering)):
            if lst is not None:
                for blk in self._selected_blocks(c):
                    l2 = blk.textList()
                    if l2 is not None:
                        l2.remove(blk)
                        bf = blk.blockFormat()
                        bf.setIndent(0)
                        sbf = m.style_block_format(m.STYLE_BY_NAME.get(m.block_style(blk), m.STYLES[0]))
                        bf.setTopMargin(sbf.topMargin())
                        bf.setBottomMargin(sbf.bottomMargin())
                        QTextCursor(blk).setBlockFormat(bf)
        else:
            level = lst.format().indent() if lst is not None else 1
            c.createList(m.list_format(kind, level))
            m.tighten_lists(self.editor.document())
        c.endEditBlock()
        self._cursor_changed()

    def _selected_blocks(self, c: QTextCursor):
        doc = self.editor.document()
        b = doc.findBlock(c.selectionStart())
        end = doc.findBlock(c.selectionEnd())
        out = []
        while b.isValid():
            out.append(b)
            if b == end:
                break
            b = b.next()
        return out

    def change_indent(self, step: int):
        c = self.editor.textCursor()
        lst = c.currentList()
        c.beginEditBlock()
        if lst is not None:
            fmt = lst.format()
            level = max(1, fmt.indent() + step)
            kind = m.list_kind(fmt)
            for blk in self._selected_blocks(c):
                l2 = blk.textList()
                if l2 is not None:
                    l2.remove(blk)
                cb = QTextCursor(blk)
                # join a list of the same kind and level just above, if any
                prev = blk.previous()
                pl = prev.textList() if prev.isValid() else None
                if pl is not None and pl.format().indent() == level and m.list_kind(pl.format()) == kind:
                    pl.add(blk)
                else:
                    cb.createList(m.list_format(kind, level))
        else:
            for blk in self._selected_blocks(c):
                bf = blk.blockFormat()
                bf.setLeftMargin(max(0.0, bf.leftMargin() + step * 48))      # 1.27 cm, Word's step
                QTextCursor(blk).setBlockFormat(bf)
        c.endEditBlock()

    def toggle_marks(self, on: bool):
        doc = self.editor.document()
        opt = doc.defaultTextOption()
        flags = opt.flags()
        if on:
            flags |= QTextOption.ShowTabsAndSpaces | QTextOption.ShowLineAndParagraphSeparators
        else:
            flags &= ~(QTextOption.ShowTabsAndSpaces | QTextOption.ShowLineAndParagraphSeparators)
        opt.setFlags(flags)
        doc.setDefaultTextOption(opt)

    # ---- insert -------------------------------------------------------------------------------
    def insert_text(self, text: str):
        self.editor.textCursor().insertText(text)
        self.editor.setFocus()

    def insert_page_break(self):
        c = self.editor.textCursor()
        c.beginEditBlock()
        bf = QTextBlockFormat(c.blockFormat())
        bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
        c.insertBlock(bf)
        c.endEditBlock()
        self.editor.setTextCursor(c)

    def insert_table(self, rows: int, cols: int):
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
        fmt.setBorderBrush(QColor("#000000"))
        fmt.setCellPadding(4)
        fmt.setCellSpacing(0)
        fmt.setBorderCollapse(True)
        fmt.setWidth(QTextLength(QTextLength.PercentageLength, 100))
        table = self.editor.textCursor().insertTable(rows, cols, fmt)
        self.editor.setTextCursor(table.cellAt(0, 0).firstCursorPosition())
        self.editor.setFocus()

    def table_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Insert Table")
        form = QFormLayout(dlg)
        cols = QSpinBox()
        cols.setRange(1, 63)
        cols.setValue(5)
        rows = QSpinBox()
        rows.setRange(1, 999)
        rows.setValue(2)
        form.addRow("Number of &columns:", cols)
        form.addRow("Number of &rows:", rows)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            self.insert_table(rows.value(), cols.value())

    def picture_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Insert Picture", str(Path.home() / "Pictures"),
                                              "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg);;All Files (*)")
        if path:
            self.insert_image(QImage(path))

    def insert_image(self, img: QImage):
        if img.isNull():
            QMessageBox.warning(self, APP, "This picture could not be opened.")
            return
        doc = self.editor.document()
        n = 1
        while not isinstance(doc.resource(QTextDocument.ImageResource, QUrl(f"image-{n}")), type(None)):
            n += 1
        name = f"image-{n}"
        doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
        fmt = QTextImageFormat()
        fmt.setName(name)
        # fit to the text column, like Word
        s = self.editor.setup
        col = (self.editor.page_width() if self.editor.fit else s.size_px.width()) - (s.left + s.right) * 96 / 25.4
        w = min(img.width(), col)
        fmt.setWidth(w)
        fmt.setHeight(img.height() * w / max(1, img.width()))
        self.editor.textCursor().insertImage(fmt)

    def hyperlink_dialog(self):
        c = self.editor.textCursor()
        cf = c.charFormat()
        dlg = QDialog(self)
        dlg.setWindowTitle("Insert Hyperlink")
        form = QFormLayout(dlg)
        text = QLineEdit(c.selectedText())
        addr = QLineEdit(cf.anchorHref() if cf.isAnchor() else "https://")
        form.addRow("&Text to display:", text)
        form.addRow("Addr&ess:", addr)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        if dlg.exec() != QDialog.Accepted or not addr.text().strip():
            return
        link = QTextCharFormat(self.editor.currentCharFormat())
        link.setAnchor(True)
        link.setAnchorHref(addr.text().strip())
        link.setForeground(QColor("#0000FF"))
        link.setFontUnderline(True)
        c.insertText(text.text() or addr.text().strip(), link)
        plain = QTextCharFormat(link)
        plain.setAnchor(False)
        plain.setAnchorHref("")
        plain.setForeground(QColor("#000000"))
        plain.setFontUnderline(False)
        self.editor.setCurrentCharFormat(plain)

    def edit_header_footer(self, which: str):
        cur = getattr(self.editor.setup, which)
        text, ok = QInputDialog.getText(self, which.title(),
                                        f"{which.title()} text (use {{page}} and {{pages}} for page numbers):",
                                        text=cur)
        if ok:
            setattr(self.editor.setup, which, text)
            self.editor.document().setModified(True)
            self.editor.viewport().update()

    def page_numbers(self):
        menu = QMenu(self)
        for label, text, where in (("Bottom of Page: 1", "{page}", "footer"),
                                   ("Bottom of Page: Page 1 of 9", "Page {page} of {pages}", "footer"),
                                   ("Top of Page: 1", "{page}", "header"),
                                   ("Remove Page Numbers", "", "remove")):
            menu.addAction(label, lambda text=text, where=where: self._set_page_numbers(text, where))
        menu.exec(self.cursor().pos())

    def _set_page_numbers(self, text: str, where: str):
        s = self.editor.setup
        if where == "remove":
            for k in ("header", "footer"):
                setattr(s, k, re.sub(r"\s*(Page\s*)?\{page\}(\s*of\s*\{pages\})?\s*", "", getattr(s, k)).strip())
        else:
            setattr(s, where, text)
        self.editor.document().setModified(True)
        self.editor.viewport().update()

    def insert_date(self):
        now = datetime.now()
        formats = [now.strftime("%d-%m-%Y"), now.strftime("%d. %B %Y"), now.strftime("%A, %d. %B %Y"),
                   now.strftime("%Y-%m-%d"), now.strftime("%d-%m-%Y %H:%M"), now.strftime("%H:%M")]
        item, ok = QInputDialog.getItem(self, "Date and Time", "&Available formats:", formats, 0, False)
        if ok:
            self.insert_text(item)

    def insert_hr(self):
        c = self.editor.textCursor()
        c.insertHtml("<hr/>")

    # ---- page layout ----------------------------------------------------------------------
    def set_margins(self, top, bottom, left, right):
        s = self.editor.setup
        s.top, s.bottom, s.left, s.right = top, bottom, left, right
        self.editor.apply_setup()
        self.editor.document().setModified(True)

    def set_orientation(self, landscape: bool):
        self.editor.setup.landscape = landscape
        self.editor.apply_setup()
        self.editor.document().setModified(True)

    def set_paper(self, name: str):
        self.editor.setup.paper = name
        self.editor.setup.custom_size = None
        self.editor.apply_setup()
        self.editor.document().setModified(True)

    def page_setup_dialog(self):
        dlg = PageSetupDialog(self.editor.setup, self)
        if dlg.exec() == QDialog.Accepted:
            self.editor.apply_setup(dlg.result_setup())
            self.editor.document().setModified(True)

    def set_draft(self, draft: bool):
        self.editor.set_draft(draft)

    # ---- review -----------------------------------------------------------------------------
    def toggle_spelling(self, on: bool):
        if not self.speller.available:
            QMessageBox.information(self, APP, "No spelling dictionaries are installed "
                                               "(hunspell-da / hunspell-en with pyenchant).")
            self.a_spell.setChecked(False)
            return
        self.speller.enabled = on
        self.speller.rehighlight()

    def word_count(self):
        doc = self.editor.document()
        text = doc.toPlainText()
        c = self.editor.textCursor()
        sel = c.selectedText().replace(" ", "\n") if c.hasSelection() else None
        src = sel if sel is not None else text
        words = len(re.findall(r"\S+", src))
        chars = len(src.replace("\n", ""))
        chars_ns = len(re.sub(r"\s", "", src))
        paras = len([p for p in src.split("\n") if p.strip()])
        QMessageBox.information(self, "Word Count", (
            f"{'Selection' if sel is not None else 'Document'} statistics\n\n"
            f"Pages\t\t\t{self.editor.page_count()}\nWords\t\t\t{words}\n"
            f"Characters (no spaces)\t{chars_ns}\nCharacters (with spaces)\t{chars}\nParagraphs\t\t{paras}"))

    # ---- context menu ---------------------------------------------------------------------
    def context_menu(self, pos):
        e = self.editor
        c = e.cursorForPosition(pos)
        if not e.textCursor().hasSelection():
            e.setTextCursor(c)
        menu = QMenu(self)
        # spelling suggestions
        if self.speller.enabled and self.speller.available:
            wc = QTextCursor(c)
            wc.select(QTextCursor.WordUnderCursor)
            word = wc.selectedText()
            if word and not self.speller.ok(word):
                sugg = self.speller.suggest(word)
                for s in sugg:
                    a = menu.addAction(s)
                    f = a.font()
                    f.setBold(True)
                    a.setFont(f)
                    a.triggered.connect(lambda _=False, s=s, wc=wc: wc.insertText(s))
                if not sugg:
                    menu.addAction("(no spelling suggestions)").setEnabled(False)
                menu.addAction("Ignore All", lambda w=word: (self.speller.ignored.add(w.lower()),
                                                             self.speller.rehighlight()))
                menu.addAction("Add to Dictionary", lambda w=word: self.speller.add(w))
                menu.addSeparator()
        menu.addAction(self.a_cut)
        menu.addAction(self.a_copy)
        menu.addAction(self.a_paste)
        menu.addAction(self.a_paste_text)
        menu.addSeparator()
        table = e.textCursor().currentTable()
        if table is not None:
            tm = menu.addMenu("Insert")
            tm.addAction("Rows Above", lambda: self.table_op("row_above"))
            tm.addAction("Rows Below", lambda: self.table_op("row_below"))
            tm.addAction("Columns to the Left", lambda: self.table_op("col_left"))
            tm.addAction("Columns to the Right", lambda: self.table_op("col_right"))
            dm = menu.addMenu("Delete Cells")
            dm.addAction("Delete Entire Row", lambda: self.table_op("del_row"))
            dm.addAction("Delete Entire Column", lambda: self.table_op("del_col"))
            dm.addAction("Delete Table", lambda: self.table_op("del_table"))
            if e.textCursor().hasComplexSelection() or e.textCursor().hasSelection():
                menu.addAction("Merge Cells", lambda: self.table_op("merge"))
            menu.addAction("Split Cells", lambda: self.table_op("split"))
            menu.addSeparator()
        cf = c.charFormat()
        if cf.isImageFormat():
            menu.addAction("Size...", lambda: self.picture_size(c))
            menu.addSeparator()
        if cf.isAnchor() and cf.anchorHref():
            href = cf.anchorHref()
            menu.addAction("Open Hyperlink", lambda: QDesktopServices.openUrl(QUrl(href)))
            menu.addAction("Edit Hyperlink...", self.hyperlink_dialog)
            menu.addAction("Remove Hyperlink", lambda: self.remove_link(c))
            menu.addSeparator()
        else:
            menu.addAction(self.a_link)
        fm = menu.addMenu("Paragraph Style")
        for st in m.STYLES:
            fm.addAction(st.name, lambda n=st.name: self.set_style(n))
        menu.addAction(self.a_bullets)
        menu.addAction(self.a_numbering)
        menu.exec(e.viewport().mapToGlobal(pos))

    def table_op(self, op: str):
        c = self.editor.textCursor()
        t = c.currentTable()
        if t is None:
            return
        cell = t.cellAt(c)
        r, col = cell.row(), cell.column()
        if op == "row_above":
            t.insertRows(r, 1)
        elif op == "row_below":
            t.insertRows(r + cell.rowSpan(), 1)
        elif op == "col_left":
            t.insertColumns(col, 1)
        elif op == "col_right":
            t.insertColumns(col + cell.columnSpan(), 1)
        elif op == "del_row":
            if t.rows() == 1:
                self.table_op("del_table")
            else:
                t.removeRows(r, 1)
        elif op == "del_col":
            if t.columns() == 1:
                self.table_op("del_table")
            else:
                t.removeColumns(col, 1)
        elif op == "del_table":
            cc = QTextCursor(self.editor.document())
            cc.setPosition(t.firstPosition() - 1)
            cc.setPosition(t.lastPosition() + 1, QTextCursor.KeepAnchor)
            cc.removeSelectedText()
        elif op == "merge":
            t.mergeCells(c)
        elif op == "split":
            t.splitCell(r, col, 1, 1)

    def picture_size(self, cursor: QTextCursor):
        c = QTextCursor(cursor)
        if not c.charFormat().isImageFormat():
            c.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor)
            c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor)
        else:
            c.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor)
        fmt = c.charFormat().toImageFormat()
        if not fmt.isValid() or not fmt.name():
            return
        pct, ok = QInputDialog.getInt(self, "Size", "Scale (% of the current size):", 100, 5, 500, 5)
        if ok and pct != 100:
            fmt.setWidth(fmt.width() * pct / 100)
            fmt.setHeight(fmt.height() * pct / 100)
            c.setCharFormat(fmt)

    def remove_link(self, cursor: QTextCursor):
        c = QTextCursor(cursor)
        block = c.block()
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            it += 1
            if frag.contains(c.position()) or frag.position() + frag.length() == c.position():
                cc = QTextCursor(self.editor.document())
                cc.setPosition(frag.position())
                cc.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                f = frag.charFormat()
                f.setAnchor(False)
                f.setAnchorHref("")
                f.setForeground(QColor("#000000"))
                f.setFontUnderline(False)
                cc.setCharFormat(f)
                break

    def paste_text(self):
        self.editor.insertPlainText(QApplication.clipboard().text())

    def show_find(self, replace: bool):
        if self.find_dialog is None:
            self.find_dialog = FindDialog(self, replace)
        self.find_dialog.set_mode(replace)
        sel = self.editor.textCursor().selectedText()
        if sel and " " not in sel:
            self.find_dialog.find.setText(sel)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.find.setFocus()
        self.find_dialog.find.selectAll()

    # ---- files ------------------------------------------------------------------------------
    def maybe_save(self) -> bool:
        if not self.editor.document().isModified():
            return True
        name = Path(self.path).name if self.path else self.untitled
        r = QMessageBox.question(self, APP, f"Do you want to save the changes to {name}?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.file_save()
        return r == QMessageBox.Discard

    def file_new(self):
        w = WriteWindow()
        w.show()

    def file_open(self):
        start = str(Path(self.path).parent) if self.path else str(Path.home() / "Documents")
        path, _ = QFileDialog.getOpenFileName(self, "Open", start, OPEN_FILTER)
        if path:
            self.open_maybe_new(path)

    def open_maybe_new(self, path: str):
        empty = (not self.path and not self.editor.document().isModified()
                 and not self.editor.toPlainText().strip())
        if empty:
            self.open_path(path)
        else:
            w = WriteWindow(path)
            w.show()

    def open_path(self, path: str):
        ext = Path(path).suffix.lower()
        note = ""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if ext == ".docx":
                import write_docx
                doc, setup = write_docx.load_docx(path)
            elif ext == ".doc":
                import write_doc
                doc, setup, note = write_doc.load_doc(path)
            elif ext == ".rtf" or (ext not in (".txt", ".html", ".htm") and _is_rtf(path)):
                import write_rtf
                doc, setup = write_rtf.load_rtf(path)
            elif ext in (".html", ".htm"):
                doc = m.new_document()
                doc.setHtml(Path(path).read_text(errors="replace"))
                setup = PageSetup()
            else:
                doc = m.new_document()
                c = QTextCursor(doc)
                c.insertText(Path(path).read_text(errors="replace"))
                setup = PageSetup()
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP, f"{APP} cannot open \"{Path(path).name}\".\n\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        doc.setModified(False)
        self.set_document(doc, setup)
        self.path = path
        self._update_title()
        self._add_recent(path)
        if note:
            self.lbl_info.setText(note)
        return True

    def file_save(self) -> bool:
        if not self.path:
            return self.file_save_as()
        return self.write_to(self.path)

    def file_save_as(self, ext: str | None = None) -> bool:
        if not isinstance(ext, str):
            ext = Path(self.path).suffix.lower() if self.path else ".docx"
        types = [t for t in SAVE_TYPES]
        filters = ";;".join(t[0] for t in types)
        chosen = next((t[0] for t in types if t[1] == ext), types[0][0])
        base = Path(self.path).with_suffix(ext) if self.path else Path.home() / "Documents" / (self.untitled + ext)
        path, filt = QFileDialog.getSaveFileName(self, "Save As", str(base), filters, chosen)
        if not path:
            return False
        want = next((t[1] for t in types if t[0] == filt), ext)
        if not Path(path).suffix:
            path += want
        if Path(path).suffix.lower() == ".pdf":
            return self.export_pdf(path)
        if self.write_to(path):
            if Path(path).suffix.lower() in (".docx", ".doc", ".rtf"):
                self.path = path
                self._update_title()
            return True
        return False

    def write_to(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        doc = self.editor.document()
        setup = self.editor.setup
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if ext == ".docx":
                import write_docx
                write_docx.save_docx(doc, setup, path)
            elif ext in (".doc", ".rtf"):
                import write_rtf
                write_rtf.save_rtf(doc, setup, path)
                if ext == ".doc":
                    self.lbl_info.setText("Saved as a Word 97-2003 document in Rich Text Format; Word opens it normally.")
            elif ext == ".odt":
                w = QTextDocumentWriter(path, b"odf")
                if not w.write(doc):
                    raise OSError("could not write the file")
            elif ext == ".pdf":
                QApplication.restoreOverrideCursor()
                return self.export_pdf(path)
            else:
                Path(path).write_text(doc.toPlainText())
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, APP, f"The file could not be saved.\n\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        if ext in (".docx", ".doc", ".rtf"):
            doc.setModified(False)
            self._add_recent(path)
        self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        return True

    def _printer(self):
        from PySide6.QtPrintSupport import QPrinter
        return QPrinter(QPrinter.HighResolution)

    def export_pdf(self, path: str) -> bool:
        from PySide6.QtPrintSupport import QPrinter
        printer = self._printer()
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
        print_document(self.editor.document(), self.editor.setup, printer)
        self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        return True

    def file_print(self):
        from PySide6.QtPrintSupport import QPrintDialog
        printer = self._printer()
        dlg = QPrintDialog(printer, self)
        if dlg.exec() == QDialog.Accepted:
            print_document(self.editor.document(), self.editor.setup, printer)

    def file_preview(self):
        from PySide6.QtPrintSupport import QPrintPreviewDialog
        dlg = QPrintPreviewDialog(self._printer(), self)
        dlg.setWindowTitle("Print Preview")
        dlg.paintRequested.connect(lambda p: print_document(self.editor.document(), self.editor.setup, p))
        dlg.resize(1000, 800)
        dlg.exec()

    def send_by_mail(self, ext: str = ".docx"):
        """Office button > Send > E-mail: a new Mail message with this document attached."""
        import shutil
        import tempfile
        from PySide6.QtCore import QProcess
        name = Path(self.path).stem if self.path else self.untitled
        if ext == ".docx" and self.path and Path(self.path).suffix.lower() in (".docx", ".doc", ".rtf") \
                and not self.editor.document().isModified():
            target = self.path
        else:
            d = Path(tempfile.mkdtemp(prefix="classic7-send-"))
            target = str(d / f"{name}{ext}")
            if ext == ".pdf":
                self.export_pdf(target)
            else:
                import write_docx
                write_docx.save_docx(self.editor.document(), self.editor.setup, target)
        if not shutil.which("classic7-mail"):
            QMessageBox.information(self, APP, "Mail is not installed.")
            return
        QProcess.startDetached("classic7-mail", ["--compose", "--attach", target])

    def closeEvent(self, ev):
        if self.maybe_save():
            ev.accept()
        else:
            ev.ignore()


def _is_rtf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"{\\rtf"
    except OSError:
        return False


def main(argv=None) -> int:
    for fam, subs in m.FONT_SUBSTITUTES.items():
        QFont.insertSubstitutions(fam, subs)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-write")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-write")
    files = [a for a in (argv or []) if not a.startswith("-")]
    wins = [WriteWindow(f) for f in files] or [WriteWindow()]
    for w in wins:
        w.show()
    return app.exec()
