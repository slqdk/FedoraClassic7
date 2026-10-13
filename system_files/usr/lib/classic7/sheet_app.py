"""Sheet: spreadsheets in the style of Excel 2007 (Office button, Ribbon, formula bar,
sheet tabs). Opens .xlsx/.xlsm/.xls/.csv, saves .xlsx, .csv and PDF."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, QSettings, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QFontComboBox, QHBoxLayout, QInputDialog,
                               QLabel, QMainWindow, QMenu, QMessageBox, QSlider, QStatusBar,
                               QTabBar, QToolButton, QVBoxLayout, QWidget)

import sheet_dialogs as D
import sheet_formula as F
import sheet_io as IO
import sheet_numfmt as NF
import sheet_ops as OPS
import write_ribbon as rb
from sheet_grid import RefLineEdit, SheetGrid
from sheet_model import Workbook, new_workbook
from sheet_ref import MAX_COLS, MAX_ROWS, cell_name, parse_cell, parse_range

APP = "Sheet"
OPEN_FILTER = ("All Excel Files (*.xlsx *.xlsm *.xltx *.xltm *.xls *.xlt *.csv);;Excel Workbook (*.xlsx);;"
               "Excel 97-2003 Workbook (*.xls);;CSV (Comma delimited) (*.csv);;Text (*.txt *.tsv);;All Files (*)")
SAVE_TYPES = [("Excel Workbook (*.xlsx)", ".xlsx"), ("Excel Macro-Free Template (*.xltx)", ".xltx"),
              ("CSV (Comma delimited) (*.csv)", ".csv"), ("Text (Tab delimited) (*.txt)", ".txt"),
              ("PDF (*.pdf)", ".pdf")]
FONT_SIZES = ["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28", "36", "48", "72"]
NUMBER_FORMATS = [("General", "General"), ("Number", "0.00"), ("Currency", '#,##0.00 "kr."'),
                  ("Accounting", '_-* #,##0.00 "kr."_-;-* #,##0.00 "kr."_-;_-* "-"?? "kr."_-;_-@_-'),
                  ("Short Date", "dd-mm-yyyy"), ("Long Date", "dddd d. mmmm yyyy"), ("Time", "h:mm:ss"),
                  ("Percentage", "0.00%"), ("Fraction", "# ?/?"), ("Scientific", "0.00E+00"), ("Text", "@")]
CELL_STYLES = [("Good", {"fill": "#c6efce", "color": "#006100"}), ("Bad", {"fill": "#ffc7ce", "color": "#9c0006"}),
               ("Neutral", {"fill": "#ffeb9c", "color": "#9c6500"}),
               ("Title", {"size": 18.0, "bold": True, "color": "#1f497d"}),
               ("Heading 1", {"size": 15.0, "bold": True, "color": "#1f497d"}),
               ("Heading 2", {"size": 13.0, "bold": True, "color": "#1f497d"}),
               ("Heading 3", {"size": 11.0, "bold": True, "color": "#1f497d"}),
               ("Total", {"bold": True}), ("Note", {"fill": "#ffffcc"}),
               ("Accent1", {"fill": "#4f81bd", "color": "#ffffff"}), ("Accent2", {"fill": "#c0504d", "color": "#ffffff"}),
               ("Accent3", {"fill": "#9bbb59", "color": "#ffffff"}), ("Normal", {})]
TABLE_STYLES = [("Light Blue", "#4f81bd", "#dbe5f1"), ("Light Red", "#c0504d", "#f2dcdb"),
                ("Light Green", "#9bbb59", "#ebf1dd"), ("Light Purple", "#8064a2", "#e5e0ec"),
                ("Light Aqua", "#4bacc6", "#dbeef3"), ("Light Orange", "#f79646", "#fdeada")]


class FormulaBar(QWidget):
    def __init__(self, win: "SheetWindow"):
        super().__init__()
        self.win = win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(3)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setFixedWidth(110)
        self.name.setInsertPolicy(QComboBox.NoInsert)
        self.name.lineEdit().returnPressed.connect(self._go)
        self.name.activated.connect(lambda _i: self._go())
        lay.addWidget(self.name)
        self.cancel = QToolButton()
        self.cancel.setText("✕")
        self.cancel.setToolTip("Cancel")
        self.ok = QToolButton()
        self.ok.setText("✓")
        self.ok.setToolTip("Enter")
        self.fx = QToolButton()
        self.fx.setText("fx")
        self.fx.setToolTip("Insert Function")
        f = self.fx.font()
        f.setItalic(True)
        f.setBold(True)
        self.fx.setFont(f)
        for b in (self.cancel, self.ok, self.fx):
            b.setAutoRaise(True)
            lay.addWidget(b)
        self.edit = RefLineEdit()
        lay.addWidget(self.edit, 1)
        self.cancel.clicked.connect(lambda: win.grid.cancel_edit())
        self.ok.clicked.connect(lambda: win.grid.commit_edit())
        self.fx.clicked.connect(win.insert_function)
        self.edit.textEdited.connect(self._typed)
        self.edit.returnPressed.connect(lambda: win.grid.commit_edit() and win.grid.move_active(1, 0))
        self.set_editing(False)

    def _typed(self, text):
        g = self.win.grid
        if not g.editing:
            g.start_edit(text, enter_mode=False)
            self.edit.setFocus()
        else:
            g.editor.setText(text)
            g._editor_changed(text)

    def set_editing(self, on: bool):
        self.cancel.setEnabled(on)
        self.ok.setEnabled(on)

    def _go(self):
        text = self.name.currentText().strip()
        win = self.win
        if not text:
            return
        target = text
        sheet = None
        if "!" in text:
            sheet, target = text.rsplit("!", 1)
            sheet = sheet.strip("'")
        if sheet is None and win.wb.defined_name(text, win.wb.ws.name) is not None:
            ref = win.wb.names.get(text) or ""
            if "!" in ref:
                sheet, target = ref.lstrip("=").rsplit("!", 1)
                sheet = sheet.strip("'")
        if sheet and win.wb.sheet(sheet):
            win.switch_sheet(win.wb.sheets.index(win.wb.sheet(sheet)))
        rng = parse_range(target)
        if rng is None:
            # a new name for the selection, like typing into Excel's name box
            if text.replace("_", "").isalnum() and not parse_cell(text):
                r = win.grid.selection_range()
                ref = f"={_quote(win.wb.ws.name)}!{_abs(r)}"
                win.wb.structural("Define Name", lambda: win.wb.names.__setitem__(text, ref))
                win.refresh_names()
            else:
                QMessageBox.warning(win, APP, "Reference isn't valid.")
            return
        win.grid.select_range(rng)
        win.grid.setFocus()


def _quote(name):
    from sheet_ref import quote_sheet
    return quote_sheet(name)


def _abs(rng):
    r1, c1, r2, c2 = rng
    a = cell_name(r1, c1, True, True)
    return a if (r1, c1) == (r2, c2) else f"{a}:{cell_name(r2, c2, True, True)}"


class SheetTabs(QWidget):
    """Sheet tabs with the navigation buttons and the Insert Worksheet tab."""

    def __init__(self, win: "SheetWindow"):
        super().__init__()
        self.win = win
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(0)
        for text, fn in (("⏮", lambda: self.tabs.setCurrentIndex(0)),
                         ("◂", lambda: self.tabs.setCurrentIndex(max(0, self.tabs.currentIndex() - 1))),
                         ("▸", lambda: self.tabs.setCurrentIndex(min(self.tabs.count() - 1, self.tabs.currentIndex() + 1))),
                         ("⏭", lambda: self.tabs.setCurrentIndex(self.tabs.count() - 1))):
            b = QToolButton()
            b.setText(text)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            lay.addWidget(b)
        self.tabs = QTabBar()
        self.tabs.setShape(QTabBar.RoundedSouth)
        self.tabs.setExpanding(False)
        self.tabs.setMovable(True)
        self.tabs.setDrawBase(False)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._menu)
        self.tabs.tabBarDoubleClicked.connect(lambda i: self.win.rename_sheet(i))
        self.tabs.currentChanged.connect(self._changed)
        self.tabs.tabMoved.connect(self._moved)
        lay.addWidget(self.tabs)
        add = QToolButton()
        add.setIcon(rb.icon(["tab-new", "list-add"], "+"))
        add.setToolTip("Insert Worksheet (Shift+F11)")
        add.setAutoRaise(True)
        add.clicked.connect(lambda: self.win.insert_sheet(end=True))
        lay.addWidget(add)
        lay.addStretch(1)
        self._block = False

    def refresh(self):
        self._block = True
        while self.tabs.count():
            self.tabs.removeTab(0)
        for ws in self.win.wb.sheets:
            i = self.tabs.addTab(ws.name)
            if ws.tab_color:
                self.tabs.setTabTextColor(i, QColor(ws.tab_color).darker(150))
            if ws.hidden:
                self.tabs.setTabVisible(i, False)
        self.tabs.setCurrentIndex(self.win.wb.active)
        self._block = False

    def _changed(self, i):
        if not self._block and i >= 0:
            self.win.switch_sheet(i)

    def _moved(self, a, b):
        if self._block:
            return
        wb = self.win.wb

        def do():
            ws = wb.sheets.pop(a)
            wb.sheets.insert(b, ws)
            wb.active = b
        wb.structural("Move Sheet", do)

    def _menu(self, pos):
        i = self.tabs.tabAt(pos)
        if i >= 0:
            self.tabs.setCurrentIndex(i)
        m = QMenu(self)
        m.addAction("Insert...", lambda: self.win.insert_sheet())
        m.addAction("Delete", self.win.delete_sheet)
        m.addAction("Rename", lambda: self.win.rename_sheet(self.tabs.currentIndex()))
        m.addAction("Move or Copy...", self.win.copy_sheet)
        colors = m.addMenu("Tab Color")
        colors.addAction("No Color", lambda: self.win.tab_color(None))
        for c in ("#c0504d", "#f79646", "#ffff00", "#9bbb59", "#4bacc6", "#4f81bd", "#8064a2", "#7f7f7f"):
            colors.addAction(rb.text_icon("■", color=c), c, lambda c=c: self.win.tab_color(c))
        m.addSeparator()
        m.addAction("Hide", self.win.hide_sheet)
        unhide = m.addAction("Unhide...", self.win.unhide_sheet)
        unhide.setEnabled(any(ws.hidden for ws in self.win.wb.sheets))
        m.exec(self.tabs.mapToGlobal(pos))


class SheetWindow(QMainWindow):
    untitled_counter = 0

    def __init__(self, path: str | None = None):
        super().__init__()
        self.settings = QSettings("Classic7", "Sheet")
        SheetWindow.untitled_counter += 1
        self.untitled = f"Book{SheetWindow.untitled_counter}"
        self.wb: Workbook = new_workbook()
        self.clip = None
        self.clip_owner = None
        self.find_dialog = None
        self.painter_style = None
        self.show_formulas = False
        self.setWindowIcon(rb.icon(["x-office-spreadsheet", "application-vnd.ms-excel"], "X", 32))
        self.grid = SheetGrid(self.wb)
        self._actions()
        self._ribbon()
        self._central()
        self._status()
        self.grid.selectionChanged.connect(self.selection_changed)
        self.grid.editTextChanged.connect(self._edit_text)
        self.grid.editingChanged.connect(self._editing)
        self.grid.contentChanged.connect(self.content_changed)
        self.grid.contextMenu.connect(self.context_menu)
        self.grid.objectActivated.connect(self.chart_options)
        self.grid.filterClicked.connect(self.filter_menu)
        self.grid.message.connect(lambda t: self.statusBar().showMessage(t, 5000))
        self.grid.zoomChanged.connect(self._zoom_changed)
        self.resize(1180, 800)
        self.load_workbook(self.wb)
        if path:
            QTimer.singleShot(0, lambda: self.open_path(path))
        self._update_title()

    # ==== actions =====================================================================================
    def act(self, text, slot=None, shortcut=None, icon=None, fallback="", checkable=False, tip=None, **kw):
        a = QAction(text, self)
        if icon is not None or fallback:
            a.setIcon(icon if isinstance(icon, QIcon) else rb.icon(icon or [], fallback or text[:1], **kw))
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, list) else [shortcut])])
            a.setShortcutContext(Qt.WindowShortcut)
        if slot:
            a.triggered.connect(lambda _c=False, f=slot: f() if not checkable else f(a.isChecked()))
        a.setCheckable(checkable)
        tip_text = tip or text.replace("&", "")
        if shortcut:
            first = shortcut[0] if isinstance(shortcut, list) else shortcut
            tip_text += f" ({QKeySequence(first).toString(QKeySequence.NativeText)})"
        a.setToolTip(tip_text)
        self.addAction(a)
        return a

    def _actions(self):
        A = self.act
        self.a_new = A("&New", self.file_new, "Ctrl+N", "document-new", "N")
        self.a_open = A("&Open...", self.file_open, "Ctrl+O", "document-open", "O")
        self.a_save = A("&Save", self.file_save, "Ctrl+S", "document-save", "S")
        self.a_saveas = A("Save &As...", self.file_save_as, "F12", "document-save-as", "A")
        self.a_print = A("&Print...", self.file_print, "Ctrl+P", "document-print", "P")
        self.a_preview = A("Print Pre&view", self.file_preview, None, "document-print-preview", "V")
        self.a_close = A("&Close", self.close, "Ctrl+W", "document-close", "X")
        self.a_undo = A("&Undo", self.undo, "Ctrl+Z", "edit-undo", "↶")
        self.a_redo = A("&Redo", self.redo, ["Ctrl+Y"], "edit-redo", "↷")
        self.a_cut = A("Cu&t", self.cut, "Ctrl+X", "edit-cut", "✂")
        self.a_copy = A("&Copy", self.copy, "Ctrl+C", "edit-copy", "C")
        self.a_paste = A("&Paste", self.paste, "Ctrl+V", "edit-paste", "P", size=rb.BIG)
        self.a_painter = A("Format Painter", self.format_painter, None, "format-stroke-color", "\U0001f58c",
                           checkable=True)
        self.a_bold = A("Bold", lambda on: self.style(bold=on), "Ctrl+B", "format-text-bold", "B", checkable=True)
        self.a_italic = A("Italic", lambda on: self.style(italic=on), "Ctrl+I", "format-text-italic", "I",
                          checkable=True, italic=True)
        self.a_underline = A("Underline", lambda on: self.style(underline=on), "Ctrl+U", "format-text-underline", "U",
                             checkable=True, underline="#000000", bold=False)
        self.a_grow = A("Increase Font Size", lambda: self.step_font(1), None, "format-font-size-more", "A⁺")
        self.a_shrink = A("Decrease Font Size", lambda: self.step_font(-1), None, "format-font-size-less", "A⁻")
        self.a_left = A("Align Text Left", lambda on: self.style(halign="left" if on else "general"), None, "format-justify-left", "≡",
                        checkable=True)
        self.a_center = A("Center", lambda on: self.style(halign="center" if on else "general"), None, "format-justify-center", "≡",
                          checkable=True)
        self.a_right = A("Align Text Right", lambda on: self.style(halign="right" if on else "general"), None, "format-justify-right", "≡",
                         checkable=True)
        self.a_top = A("Top Align", lambda on: self.style(valign="top" if on else "bottom"), None, "align-vertical-top", "⊤",
                       checkable=True)
        self.a_middle = A("Middle Align", lambda on: self.style(valign="center" if on else "bottom"), None, "align-vertical-center", "═",
                          checkable=True)
        self.a_bottom = A("Bottom Align", lambda on: self.style(valign="bottom" if on else "bottom"), None, "align-vertical-bottom", "⊥",
                          checkable=True)
        self.a_wrap = A("Wrap Text", lambda on: self.style(wrap=on), None, "format-text-wrap", "↵", checkable=True)
        self.a_merge = A("Merge && Center", lambda _on: self.merge_center(), None, ["merge", "format-table-merge-cells"], "↔",
                         checkable=True)
        self.a_indent = A("Increase Indent", lambda: self.indent(1), None, "format-indent-more", "⇥")
        self.a_outdent = A("Decrease Indent", lambda: self.indent(-1), None, "format-indent-less", "⇤")
        self.a_percent = A("Percent Style", lambda: self.style(numfmt="0%"), "Ctrl+Shift+%", None, "%")
        self.a_comma = A("Comma Style", lambda: self.style(numfmt="#,##0.00"), None, None, ",")
        self.a_currency = A("Accounting Number Format", lambda: self.style(numfmt=NUMBER_FORMATS[3][1]), None, None,
                            "kr")
        self.a_more_dec = A("Increase Decimal", lambda: self.decimals(True), None, None, ".0←")
        self.a_less_dec = A("Decrease Decimal", lambda: self.decimals(False), None, None, ".00→")
        self.a_format_cells = A("Format Cells...", lambda: self.format_cells(0), "Ctrl+1", "configure", "⚙")
        self.a_autosum = A("AutoSum", lambda: self.autosum("SUM"), "Alt+=", None, "Σ", size=rb.BIG)
        self.a_autosum.setData("split")
        self.a_fill_down = A("Down", lambda: self.fill_dir("down"), "Ctrl+D", "go-down", "↓")
        self.a_fill_right = A("Right", lambda: self.fill_dir("right"), "Ctrl+R", "go-next", "→")
        self.a_sort_az = A("Sort A to Z", lambda: self.sort(True), None, ["view-sort-ascending"], "A↓")
        self.a_sort_za = A("Sort Z to A", lambda: self.sort(False), None, ["view-sort-descending"], "Z↓")
        self.a_filter = A("Filter", self.toggle_filter, "Ctrl+Shift+L", ["view-filter", "filter"], "▽",
                          checkable=True)
        self.a_find = A("&Find...", lambda: self.show_find(False), "Ctrl+F", "edit-find", "F")
        self.a_replace = A("R&eplace...", lambda: self.show_find(True), "Ctrl+H", "edit-find-replace", "R")
        self.a_goto = A("&Go To...", self.go_to, ["Ctrl+G", "F5"], "go-jump", "→")
        self.a_select_all = A("Select All", self.select_all, "Ctrl+A", "edit-select-all", "A")
        self.a_insert_function = A("Insert Function", self.insert_function, "Shift+F3", None, "fx", size=rb.BIG,
                                   italic=True)
        self.a_calc = A("Calculate Now", self.calculate, "F9", "view-refresh", "↻")
        self.a_show_formulas = A("Show Formulas", self.toggle_formulas, "Ctrl+`", None, "fx", checkable=True)
        self.a_date = A("Insert Date", lambda: self.insert_now(False), "Ctrl+;")
        self.a_time = A("Insert Time", lambda: self.insert_now(True), "Ctrl+Shift+;")
        self.a_next_sheet = A("Next Sheet", lambda: self.step_sheet(1), "Ctrl+PgDown")
        self.a_prev_sheet = A("Previous Sheet", lambda: self.step_sheet(-1), "Ctrl+PgUp")
        self.a_new_sheet = A("Insert Worksheet", lambda: self.insert_sheet(end=False), "Shift+F11")
        self.a_comment = A("New Comment", self.edit_comment, "Shift+F2", ["edit-comment", "comment-new"], "✎")
        self.a_link = A("Hyperlink", self.hyperlink, "Ctrl+K", ["insert-link", "link"], "\U0001f517")
        self.a_picture = A("Picture", self.insert_picture, None, ["insert-image", "image-x-generic"], "\U0001f5bc",
                           size=rb.BIG)
        self.a_freeze = A("Freeze Panes", self.freeze, None, ["view-split-top-bottom"], "❄", size=rb.BIG)
        self.a_gridlines = A("Gridlines", self.toggle_grid, None, None, "#", checkable=True)
        self.a_headings = A("Headings", self.toggle_headings, None, None, "A", checkable=True)
        self.a_formula_bar = A("Formula Bar", self.toggle_formula_bar, None, None, "fx", checkable=True)
        self.a_zoom100 = A("100%", lambda: self.grid.set_zoom(100), None, ["zoom-original"], "1:1", size=rb.BIG)
        self.a_zoom_sel = A("Zoom to Selection", self.zoom_selection, None, ["zoom-fit-best", "zoom-select"], "⤢",
                            size=rb.BIG)
        self.a_zoom = A("Zoom...", self.zoom_dialog, None, ["zoom-in"], "\U0001f50d", size=rb.BIG)
        self.a_name_manager = A("Name Manager", self.name_manager, "Ctrl+F3", ["view-list-details"], "N", size=rb.BIG)
        self.a_define_name = A("Define Name", self.define_name, None, ["document-new"], "N")
        self.a_remove_dup = A("Remove Duplicates", self.remove_duplicates, None, ["edit-delete"], "✖", size=rb.BIG)
        self.a_validation = A("Data Validation...", self.data_validation, None, ["dialog-ok-apply"], "✓",
                              size=rb.BIG)
        self.a_text_columns = A("Text to Columns", self.text_to_columns, None, ["view-split-left-right"], "‖",
                                size=rb.BIG)
        self.a_page_setup = A("Page Setup...", self.page_setup, None, ["document-page-setup", "document-properties"],
                              "⚙")
        self.a_portrait = A("Portrait", lambda: self.set_orientation("portrait"), None, None, "▯")
        self.a_landscape = A("Landscape", lambda: self.set_orientation("landscape"), None, None, "▭")
        self.a_print_area = A("Set Print Area", self.set_print_area, None, ["document-print"], "▦")
        self.a_clear_print_area = A("Clear Print Area", self.clear_print_area)
        self.a_save_pdf = A("PDF or XPS", lambda: self.file_save_as(".pdf"), None, ["application-pdf"], "PDF")
        self.a_delete_rows = A("Delete Sheet Rows", lambda: self.insert_delete("row", -1))
        self.a_delete_cols = A("Delete Sheet Columns", lambda: self.insert_delete("col", -1))
        self.a_insert_rows = A("Insert Sheet Rows", lambda: self.insert_delete("row", 1), "Ctrl++")
        self.a_insert_cols = A("Insert Sheet Columns", lambda: self.insert_delete("col", 1))
        QShortcut(QKeySequence("Ctrl+-"), self, self.delete_cells_dialog)
        QShortcut(QKeySequence("Ctrl+Shift++"), self, self.insert_cells_dialog)
        QShortcut(QKeySequence("Ctrl+Shift+$"), self, lambda: self.style(numfmt='#,##0.00 "kr."'))
        QShortcut(QKeySequence("Ctrl+Shift+#"), self, lambda: self.style(numfmt="dd-mm-yyyy"))
        QShortcut(QKeySequence("Ctrl+Shift+!"), self, lambda: self.style(numfmt="#,##0.00"))
        QShortcut(QKeySequence("Ctrl+Shift+~"), self, lambda: self.style(numfmt="General"))
        QShortcut(QKeySequence("Ctrl+5"), self, lambda: self.style(strike=not self.cur_style().strike))
        QShortcut(QKeySequence("Ctrl+9"), self, lambda: self.hide_rows(True))
        QShortcut(QKeySequence("Ctrl+0"), self, lambda: self.hide_cols(True))

    # ==== ribbon =======================================================================================
    def _ribbon(self):
        top = QWidget()
        v = QVBoxLayout(top)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        qat = QHBoxLayout()
        qat.setContentsMargins(2, 2, 2, 0)
        self.office = QToolButton()
        self.office.setObjectName("orb")
        self.office.setIcon(rb.office_orb(36, "X"))
        self.office.setIconSize(QSize(36, 36))
        self.office.setPopupMode(QToolButton.InstantPopup)
        self.office.setToolTip("Office Button\nNew, Open, Save, Print, Close")
        self.office.setMenu(self._office_menu())
        self.office.setAutoRaise(True)
        qat.addWidget(self.office)
        qat.addSpacing(4)
        for a in (self.a_save, self.a_undo, self.a_redo):
            qat.addWidget(rb.small_button(a))
        qat.addStretch(1)
        v.addLayout(qat)
        r = rb.Ribbon()
        self.ribbon = r
        self._tab_home(r)
        self._tab_insert(r)
        self._tab_page(r)
        self._tab_formulas(r)
        self._tab_data(r)
        self._tab_review(r)
        self._tab_view(r)
        v.addWidget(r)
        self.ribbon_top = top
        rb.apply_scheme(top, r, self.settings.value("ribbon/scheme", "blue"))
        self.setMenuWidget(top)

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
        send.addAction(rb.icon(["mail-message-new"], "@"), "&E-mail", lambda: self.send_by_mail(".xlsx"))
        send.addAction(rb.icon(["application-pdf"], "PDF"), "E-mail as &PDF Attachment",
                       lambda: self.send_by_mail(".pdf"))
        menu.addSeparator()
        self.recent_menu = menu.addMenu(rb.icon("document-open-recent", "R"), "&Recent Documents")
        self._fill_recent()
        menu.addSeparator()
        schemes = menu.addMenu(rb.icon("preferences-desktop-color", "C"), "Color &Scheme")
        grp = QActionGroup(schemes)
        current = self.settings.value("ribbon/scheme", "blue")
        for key, label in rb.SCHEME_NAMES.items():
            a = schemes.addAction(label, lambda key=key: self.set_ribbon_scheme(key))
            a.setCheckable(True)
            a.setChecked(key == current)
            grp.addAction(a)
        menu.addSeparator()
        menu.addAction(self.a_close)
        menu.addAction(rb.icon("application-exit", "X"), f"E&xit {APP}", QApplication.closeAllWindows)
        return menu

    def set_ribbon_scheme(self, key):
        self.settings.setValue("ribbon/scheme", key)
        for w in QApplication.topLevelWidgets():
            if isinstance(w, SheetWindow):
                rb.apply_scheme(w.ribbon_top, w.ribbon, key)

    def _menu_button(self, text, icon_names, fallback, items, big=True, tip=None):
        a = QAction(rb.icon(icon_names, fallback, size=rb.BIG if big else rb.SMALL), text, self)
        if tip:
            a.setToolTip(tip)
        m = QMenu(self)
        self._fill_menu(m, items)
        return rb.big_button(a, m) if big else rb.small_button(a, m, with_text=True)

    def _fill_menu(self, m: QMenu, items):
        for it in items:
            if it is None:
                m.addSeparator()
            elif isinstance(it, QAction):
                m.addAction(it)
            elif isinstance(it[1], list):
                sub = m.addMenu(it[0])
                self._fill_menu(sub, it[1])
            else:
                m.addAction(it[0], it[1])

    def _tab_home(self, r):
        tab = r.add_tab("Home")
        g = r.group(tab, "Clipboard")
        paste_menu = QMenu(self)
        paste_menu.addAction(rb.icon("edit-paste", "P"), "Paste", self.paste)
        paste_menu.addAction("Formulas", lambda: self.paste("formulas"))
        paste_menu.addAction("Paste Values", lambda: self.paste("values"))
        paste_menu.addAction("Formatting", lambda: self.paste("formats"))
        paste_menu.addAction("Transpose", lambda: self.paste("all", transpose=True))
        paste_menu.addSeparator()
        paste_menu.addAction("Paste Special...", self.paste_special)
        self.a_paste.setData("split")
        g.add(rb.big_button(self.a_paste, paste_menu))
        g.add_column([rb.small_button(self.a_cut, with_text=True)], [rb.small_button(self.a_copy, with_text=True)],
                     [rb.small_button(self.a_painter, with_text=True)])
        g = r.group(tab, "Font")
        self.font_box = QFontComboBox()
        self.font_box.setMaximumWidth(170)
        self.font_box.setMinimumWidth(120)
        self.font_box.currentFontChanged.connect(lambda f: self.style(font=f.family()) if not self._updating else None)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems(FONT_SIZES)
        self.size_box.setFixedWidth(52)
        self.size_box.lineEdit().returnPressed.connect(self._size_entered)
        self.size_box.activated.connect(lambda _i: self._size_entered())
        borders = QMenu(self)
        for text, kind in (("Bottom Border", "bottom"), ("Top Border", "top"), ("Left Border", "left"),
                           ("Right Border", "right"), (None, None), ("No Border", "none"), ("All Borders", "all"),
                           ("Outside Borders", "outside"), ("Thick Box Border", "thick_box"), (None, None),
                           ("Bottom Double Border", "double_bottom"), ("Thick Bottom Border", "thick_bottom"),
                           ("Top and Bottom Border", "top_bottom")):
            if text is None:
                borders.addSeparator()
            else:
                borders.addAction(text, lambda k=kind: self.borders(k))
        borders.addSeparator()
        borders.addAction("More Borders...", lambda: self.format_cells(3))
        self.a_borders = QAction(rb.icon(["format-border-set-bottom", "draw-rectangle"], "□"), "Bottom Border", self)
        self.a_borders.triggered.connect(lambda: self.borders(self._last_border))
        self._last_border = "bottom"
        self.a_borders.setData("split")
        fill_menu = rb.color_menu(self, rb.WORD_COLORS, 10, lambda c: self.style(fill=c.name()), "No Fill")
        self.a_fill = QAction(rb.text_icon("▧", underline="#FFFF00", bold=False), "Fill Color", self)
        self.a_fill.triggered.connect(lambda: self.style(fill="#ffff00"))
        self.a_fill.setData("split")
        color_menu = rb.color_menu(self, rb.WORD_COLORS, 10, lambda c: self.style(color=c.name()), "Automatic")
        self.a_font_color = QAction(rb.text_icon("A", underline="#FF0000"), "Font Color", self)
        self.a_font_color.triggered.connect(lambda: self.style(color="#ff0000"))
        self.a_font_color.setData("split")
        g.add_column([self.font_box, self.size_box, rb.small_button(self.a_grow), rb.small_button(self.a_shrink)],
                     [rb.small_button(self.a_bold), rb.small_button(self.a_italic), rb.small_button(self.a_underline),
                      rb.small_button(self.a_borders, borders, split=True),
                      rb.small_button(self.a_fill, fill_menu, split=True),
                      rb.small_button(self.a_font_color, color_menu, split=True)])
        g = r.group(tab, "Alignment")
        self.align_group = QActionGroup(self)
        for a in (self.a_left, self.a_center, self.a_right):
            self.align_group.addAction(a)
        self.align_group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        self.valign_group = QActionGroup(self)
        for a in (self.a_top, self.a_middle, self.a_bottom):
            self.valign_group.addAction(a)
        merge_menu = QMenu(self)
        merge_menu.addAction("Merge && Center", self.merge_center)
        merge_menu.addAction("Merge Across", lambda: self.merge(center=False, across=True))
        merge_menu.addAction("Merge Cells", lambda: self.merge(center=False))
        merge_menu.addAction("Unmerge Cells", self.unmerge)
        g.add_column([rb.small_button(self.a_top), rb.small_button(self.a_middle), rb.small_button(self.a_bottom),
                      rb.small_button(self.a_wrap, with_text=True)],
                     [rb.small_button(self.a_left), rb.small_button(self.a_center), rb.small_button(self.a_right),
                      rb.small_button(self.a_outdent), rb.small_button(self.a_indent),
                      rb.small_button(self.a_merge, merge_menu, with_text=True, split=True)])
        g = r.group(tab, "Number")
        self.numfmt_box = QComboBox()
        self.numfmt_box.setFixedWidth(130)
        for label, code in NUMBER_FORMATS:
            self.numfmt_box.addItem(label, code)
        self.numfmt_box.addItem("More Number Formats...", None)
        self.numfmt_box.activated.connect(self._numfmt_chosen)
        g.add_column([self.numfmt_box],
                     [rb.small_button(self.a_currency), rb.small_button(self.a_percent), rb.small_button(self.a_comma),
                      rb.small_button(self.a_more_dec), rb.small_button(self.a_less_dec)])
        g = r.group(tab, "Styles")
        g.add(self._menu_button("Conditional\nFormatting", ["view-statistics", "format-fill-color"], "▤",
                                self._cond_items()))
        g.add(self._menu_button("Format\nas Table", ["view-table-of-contents-ltr", "table"], "▦",
                                [(name, lambda n=name: self.format_as_table(n)) for name, _, _ in TABLE_STYLES]))
        g.add(self._menu_button("Cell\nStyles", ["format-fill-color", "draw-brush"], "▣",
                                [(name, lambda kw=kw: self.cell_style(kw)) for name, kw in CELL_STYLES]))
        g = r.group(tab, "Cells")
        g.add(self._menu_button("Insert", ["insert-table-row", "list-add"], "+",
                                [("Insert Cells...", self.insert_cells_dialog), self.a_insert_rows, self.a_insert_cols,
                                 ("Insert Sheet", lambda: self.insert_sheet())]))
        g.add(self._menu_button("Delete", ["delete-table-row", "list-remove"], "−",
                                [("Delete Cells...", self.delete_cells_dialog), self.a_delete_rows, self.a_delete_cols,
                                 ("Delete Sheet", self.delete_sheet)]))
        g.add(self._menu_button("Format", ["configure", "document-properties"], "⚙", [
            ("Row Height...", self.row_height), ("AutoFit Row Height", lambda: self.grid.autofit_rows(self._sel_rows())),
            ("Column Width...", self.col_width),
            ("AutoFit Column Width", lambda: self.grid.autofit_columns(self._sel_cols())),
            ("Default Width...", self.default_width), None,
            ("Hide && Unhide", [("Hide Rows", lambda: self.hide_rows(True)), ("Hide Columns", lambda: self.hide_cols(True)),
                                ("Hide Sheet", self.hide_sheet), None, ("Unhide Rows", lambda: self.hide_rows(False)),
                                ("Unhide Columns", lambda: self.hide_cols(False)), ("Unhide Sheet...", self.unhide_sheet)]),
            None, ("Rename Sheet", lambda: self.rename_sheet(self.wb.active)), ("Move or Copy Sheet...", self.copy_sheet),
            None, self.a_format_cells]))
        g = r.group(tab, "Editing")
        sum_menu = QMenu(self)
        for name, fn in (("Sum", "SUM"), ("Average", "AVERAGE"), ("Count Numbers", "COUNT"), ("Max", "MAX"),
                         ("Min", "MIN")):
            sum_menu.addAction(name, lambda fn=fn: self.autosum(fn))
        sum_menu.addSeparator()
        sum_menu.addAction("More Functions...", self.insert_function)
        fill_menu2 = QMenu(self)
        fill_menu2.addAction(self.a_fill_down)
        fill_menu2.addAction(self.a_fill_right)
        fill_menu2.addAction(rb.icon("go-up", "↑"), "Up", lambda: self.fill_dir("up"))
        fill_menu2.addAction(rb.icon("go-previous", "←"), "Left", lambda: self.fill_dir("left"))
        clear_menu = QMenu(self)
        for text, what in (("Clear All", "all"), ("Clear Formats", "formats"), ("Clear Contents", "contents"),
                           ("Clear Comments", "comments"), ("Clear Hyperlinks", "links")):
            clear_menu.addAction(text, lambda w=what: self.clear(w))
        sort_menu = QMenu(self)
        sort_menu.addAction(self.a_sort_az)
        sort_menu.addAction(self.a_sort_za)
        sort_menu.addAction("Custom Sort...", self.custom_sort)
        sort_menu.addSeparator()
        sort_menu.addAction(self.a_filter)
        sort_menu.addAction("Clear", self.clear_filter)
        sort_menu.addAction("Reapply", self.reapply_filter)
        find_menu = QMenu(self)
        for a in (self.a_find, self.a_replace, self.a_goto):
            find_menu.addAction(a)
        g.add_column([rb.small_button(self.a_autosum, sum_menu, with_text=True, split=True)],
                     [rb.small_button(QAction(rb.icon(["go-down"], "↓"), "Fill", self), fill_menu2, with_text=True)],
                     [rb.small_button(QAction(rb.icon(["edit-clear"], "⌫"), "Clear", self), clear_menu, with_text=True)])
        g.add(self._menu_button("Sort &&\nFilter", ["view-sort-ascending"], "A↓", []))
        g.body.itemAt(g.body.count() - 1).widget().setMenu(sort_menu)
        g.add(self._menu_button("Find &&\nSelect", ["edit-find"], "\U0001f50d", []))
        g.body.itemAt(g.body.count() - 1).widget().setMenu(find_menu)

    def _cond_items(self):
        return [
            ("Highlight Cells Rules", [
                ("Greater Than...", lambda: self.cond_rule("greaterThan")),
                ("Less Than...", lambda: self.cond_rule("lessThan")),
                ("Between...", lambda: self.cond_rule("between")),
                ("Equal To...", lambda: self.cond_rule("equal")),
                ("Text that Contains...", lambda: self.cond_rule("containsText")),
                ("Duplicate Values...", lambda: self.cond_rule("duplicateValues"))]),
            ("Top/Bottom Rules", [
                ("Top 10 Items...", lambda: self.cond_rule("top10")),
                ("Bottom 10 Items...", lambda: self.cond_rule("bottom10")),
                ("Above Average...", lambda: self.cond_rule("aboveAverage")),
                ("Below Average...", lambda: self.cond_rule("belowAverage"))]),
            ("Data Bars", [(name, lambda c=c: self.cond_bar(c)) for name, c in
                           (("Blue Data Bar", "#638ec6"), ("Green Data Bar", "#63be7b"), ("Red Data Bar", "#f8696b"),
                            ("Orange Data Bar", "#ffb628"), ("Purple Data Bar", "#bc4bb4"))]),
            ("Color Scales", [(name, lambda cs=cs: self.cond_scale(cs)) for name, cs in
                              (("Green - Yellow - Red", ["#63be7b", "#ffeb84", "#f8696b"]),
                               ("Red - Yellow - Green", ["#f8696b", "#ffeb84", "#63be7b"]),
                               ("Green - White", ["#ffffff", "#63be7b"]), ("White - Red", ["#ffffff", "#f8696b"]),
                               ("Blue - White - Red", ["#5a8ac6", "#fcfcff", "#f8696b"]))]),
            None,
            ("Clear Rules", [("Clear Rules from Selected Cells", lambda: self.clear_rules(True)),
                             ("Clear Rules from Entire Sheet", lambda: self.clear_rules(False))]),
        ]

    def _tab_insert(self, r):
        tab = r.add_tab("Insert")
        g = r.group(tab, "Tables")
        g.add(self._menu_button("Table", ["view-table-of-contents-ltr", "table"], "▦",
                                [(name, lambda n=name: self.format_as_table(n)) for name, _, _ in TABLE_STYLES]))
        g = r.group(tab, "Illustrations")
        g.add(rb.big_button(self.a_picture))
        g = r.group(tab, "Charts")
        for key, name, icons in (("col", "Column", ["office-chart-bar", "view-statistics"]),
                                 ("line", "Line", ["office-chart-line"]), ("pie", "Pie", ["office-chart-pie"]),
                                 ("bar", "Bar", ["office-chart-bar"]), ("area", "Area", ["office-chart-area"]),
                                 ("scatter", "Scatter", ["office-chart-scatter", "office-chart-line"])):
            a = QAction(rb.icon(icons, name[0], size=rb.BIG), name, self)
            a.triggered.connect(lambda _=False, k=key: self.insert_chart(k))
            m = QMenu(self)
            if key in ("col", "bar", "line", "area"):
                for label, grouping in (("Clustered" if key in ("col", "bar") else "Standard",
                                         "clustered" if key in ("col", "bar") else "standard"),
                                        ("Stacked", "stacked"), ("100% Stacked", "percentStacked")):
                    m.addAction(f"{label} {name}", lambda k=key, gr=grouping: self.insert_chart(k, gr))
                g.add(rb.big_button(a, m))
            else:
                g.add(rb.big_button(a))
        other = QMenu(self)
        other.addAction("Doughnut", lambda: self.insert_chart("doughnut"))
        other.addAction("Radar", lambda: self.insert_chart("radar"))
        g.add(rb.big_button(QAction(rb.icon(["office-chart-ring", "office-chart-pie"], "O", size=rb.BIG),
                                    "Other Charts", self), other))
        g = r.group(tab, "Links")
        g.add(rb.big_button(self.a_link))
        g = r.group(tab, "Text")
        sym = QAction(rb.icon(["character-set"], "Ω", size=rb.BIG), "Symbol", self)
        g.add(rb.big_button(sym, rb.symbol_menu(self, self._insert_symbol)))

    def _tab_page(self, r):
        tab = r.add_tab("Page Layout")
        g = r.group(tab, "Page Setup")
        g.add(self._menu_button("Margins", ["document-page-setup"], "▢", [
            ("Normal", lambda: self.set_margins((0.7, 0.7, 0.75, 0.75))),
            ("Wide", lambda: self.set_margins((1, 1, 1, 1))),
            ("Narrow", lambda: self.set_margins((0.25, 0.25, 0.75, 0.75))), None,
            ("Custom Margins...", self.page_setup)]))
        g.add(self._menu_button("Orientation", ["object-rotate-right"], "↻", [self.a_portrait, self.a_landscape]))
        g.add(self._menu_button("Size", ["document-page-setup"], "A4", [
            (p, lambda p=p: self.set_paper(p)) for p in ("A4", "A3", "A5", "Letter", "Legal")]))
        g.add(self._menu_button("Print\nArea", ["document-print"], "▦", [self.a_print_area, self.a_clear_print_area]))
        g.add_column([rb.small_button(self.a_page_setup, with_text=True)])
        g = r.group(tab, "Scale to Fit")
        self.fit_width = QComboBox()
        self.fit_width.addItems(["Automatic", "1 page", "2 pages", "3 pages"])
        self.fit_height = QComboBox()
        self.fit_height.addItems(["Automatic", "1 page", "2 pages", "3 pages"])
        self.fit_width.activated.connect(self._fit_changed)
        self.fit_height.activated.connect(self._fit_changed)
        g.add_column([QLabel("Width:"), self.fit_width], [QLabel("Height:"), self.fit_height])
        g = r.group(tab, "Sheet Options")
        self.a_print_grid = self.act("Print Gridlines", lambda on: self._page_opt("gridlines", on), checkable=True)
        self.a_print_heads = self.act("Print Headings", lambda on: self._page_opt("headings", on), checkable=True)
        g.add_column([rb.small_button(self.a_gridlines, with_text=True)], [rb.small_button(self.a_print_grid, with_text=True)])
        g.add_column([rb.small_button(self.a_headings, with_text=True)], [rb.small_button(self.a_print_heads, with_text=True)])

    def _tab_formulas(self, r):
        tab = r.add_tab("Formulas")
        g = r.group(tab, "Function Library")
        g.add(rb.big_button(self.a_insert_function, text="Insert\nFunction"))
        g.add(self._menu_button("AutoSum", [], "Σ", [
            (n, lambda fn=fn: self.autosum(fn)) for n, fn in (("Sum", "SUM"), ("Average", "AVERAGE"),
                                                             ("Count Numbers", "COUNT"), ("Max", "MAX"), ("Min", "MIN"))]))
        for cat, label in (("Financial", "Financial"), ("Logical", "Logical"), ("Text", "Text"),
                           ("Date & Time", "Date &&\nTime"), ("Lookup & Reference", "Lookup &&\nReference"),
                           ("Math & Trig", "Math &&\nTrig"), ("Statistical", "More\nFunctions")):
            names = sorted(set(F.CATEGORIES.get(cat, [])))
            g.add(self._menu_button(label, [], label[0], [(n, lambda n=n: self.insert_function(n)) for n in names]))
        g = r.group(tab, "Defined Names")
        g.add(rb.big_button(self.a_name_manager, text="Name\nManager"))
        self.use_in_formula = QMenu(self)
        self.use_in_formula.aboutToShow.connect(self._fill_names_menu)
        g.add_column([rb.small_button(self.a_define_name, with_text=True)],
                     [rb.small_button(QAction("Use in Formula", self), self.use_in_formula, with_text=True)])
        g = r.group(tab, "Formula Auditing")
        g.add_column([rb.small_button(self.a_show_formulas, with_text=True)])
        g = r.group(tab, "Calculation")
        calc_menu = QMenu(self)
        grp = QActionGroup(self)
        for text, auto in (("Automatic", True), ("Manual", False)):
            a = calc_menu.addAction(text, lambda auto=auto: self.set_calc(auto))
            a.setCheckable(True)
            a.setChecked(auto)
            grp.addAction(a)
        g.add(rb.big_button(QAction(rb.icon(["configure"], "⚙", size=rb.BIG), "Calculation\nOptions", self),
                            calc_menu))
        g.add_column([rb.small_button(self.a_calc, with_text=True)])

    def _tab_data(self, r):
        tab = r.add_tab("Data")
        g = r.group(tab, "Get External Data")
        g.add(rb.big_button(QAction(rb.icon(["text-csv", "text-x-generic"], "T", size=rb.BIG), "From Text", self,
                                    triggered=self.import_text)))
        g = r.group(tab, "Sort & Filter")
        g.add_column([rb.small_button(self.a_sort_az)], [rb.small_button(self.a_sort_za)])
        g.add(rb.big_button(QAction(rb.icon(["view-sort-ascending"], "⇅", size=rb.BIG), "Sort", self,
                                    triggered=self.custom_sort)))
        g.add(rb.big_button(self.a_filter))
        g.add_column([rb.small_button(QAction("Clear", self, triggered=self.clear_filter), with_text=True)],
                     [rb.small_button(QAction("Reapply", self, triggered=self.reapply_filter), with_text=True)])
        g = r.group(tab, "Data Tools")
        g.add(rb.big_button(self.a_text_columns))
        g.add(rb.big_button(self.a_remove_dup))
        g.add(rb.big_button(self.a_validation))

    def _tab_review(self, r):
        tab = r.add_tab("Review")
        g = r.group(tab, "Comments")
        g.add(rb.big_button(self.a_comment))
        g.add_column([rb.small_button(QAction(rb.icon("edit-delete", "✕"), "Delete", self,
                                              triggered=self.delete_comment), with_text=True)])

    def _tab_view(self, r):
        tab = r.add_tab("View")
        g = r.group(tab, "Workbook Views")
        g.add(rb.big_button(QAction(rb.icon(["view-grid", "view-list-details"], "N", size=rb.BIG), "Normal", self)))
        g.add(rb.big_button(QAction(rb.icon(["document-print-preview"], "P", size=rb.BIG), "Print\nPreview", self,
                                    triggered=self.file_preview)))
        g = r.group(tab, "Show/Hide")
        g.add_column([rb.small_button(self.a_gridlines, with_text=True)],
                     [rb.small_button(self.a_formula_bar, with_text=True)],
                     [rb.small_button(self.a_headings, with_text=True)])
        g = r.group(tab, "Zoom")
        g.add(rb.big_button(self.a_zoom))
        g.add(rb.big_button(self.a_zoom100))
        g.add(rb.big_button(self.a_zoom_sel))
        g = r.group(tab, "Window")
        fm = QMenu(self)
        fm.addAction("Freeze Panes", self.freeze)
        fm.addAction("Freeze Top Row", lambda: self.set_freeze((1, 0)))
        fm.addAction("Freeze First Column", lambda: self.set_freeze((0, 1)))
        fm.addAction("Unfreeze Panes", lambda: self.set_freeze(None))
        g.add(rb.big_button(self.a_freeze, fm))
        g.add(rb.big_button(QAction(rb.icon(["window-new"], "+", size=rb.BIG), "New\nWindow", self,
                                    triggered=self.file_new)))

    # ==== central area ================================================================================
    def _central(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.formula_bar = FormulaBar(self)
        lay.addWidget(self.formula_bar)
        lay.addWidget(self.grid, 1)
        self.tabs = SheetTabs(self)
        lay.addWidget(self.tabs)
        self.setCentralWidget(w)
        self.a_formula_bar.setChecked(True)

    def _status(self):
        sb = QStatusBar()
        self.mode_label = QLabel("Ready")
        sb.addWidget(self.mode_label)
        self.stats_label = QLabel()
        sb.addPermanentWidget(self.stats_label)
        self.zoom_label = QToolButton()
        self.zoom_label.setAutoRaise(True)
        self.zoom_label.clicked.connect(self.zoom_dialog)
        sb.addPermanentWidget(self.zoom_label)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 400)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.valueChanged.connect(lambda v: self.grid.set_zoom(v))
        sb.addPermanentWidget(self.zoom_slider)
        self.setStatusBar(sb)

    # ==== workbook ======================================================================================
    def load_workbook(self, wb: Workbook):
        self.wb = wb
        self.grid.wb = wb
        self.grid.invalidate()
        self.tabs.refresh()
        self.switch_sheet(wb.active, force=True)
        self.refresh_names()

    def switch_sheet(self, i: int, force=False):
        if self.grid.editing and not self.grid.commit_edit():
            return
        if i == self.wb.active and not force:
            return
        if 0 <= i < len(self.wb.sheets):
            self.wb.active = i
            self.grid.selected_object = None
            self.grid._axes = None
            hb, vb = self.grid.horizontalScrollBar(), self.grid.verticalScrollBar()
            vb.setValue(0)
            hb.setValue(0)
            self.grid.invalidate()
            self.grid.ensure_visible(*self.wb.ws.active)
            if self.tabs.tabs.currentIndex() != i:
                self.tabs._block = True
                self.tabs.tabs.setCurrentIndex(i)
                self.tabs._block = False
            self.selection_changed()
            self._zoom_changed(self.wb.ws.zoom)

    def step_sheet(self, d):
        i = self.wb.active + d
        while 0 <= i < len(self.wb.sheets) and self.wb.sheets[i].hidden:
            i += d
        if 0 <= i < len(self.wb.sheets):
            self.switch_sheet(i)

    _updating = False

    def cur_style(self):
        return self.wb.ws.style_of(*self.wb.ws.active)

    def selection_changed(self):
        ws = self.wb.ws
        r1, c1, r2, c2 = self.grid.selection_range()
        name = cell_name(*ws.active) if (r1, c1, r2, c2) == (*ws.active, *ws.active) or ws.merge_at(*ws.active) == (r1, c1, r2, c2) \
            else (f"{r2 - r1 + 1}R x {c2 - c1 + 1}C" if self.grid.drag else cell_name(*ws.active))
        for n, ref in self.wb.names.items():
            rng = ref.lstrip("=").split("!")[-1].replace("$", "")
            if parse_range(rng) == (r1, c1, r2, c2):
                name = n
        self.formula_bar.name.setEditText(name)
        if not self.grid.editing:
            self.formula_bar.edit.setText(self.grid.edit_text_for(*ws.active))
        st = self.cur_style()
        self._updating = True
        try:
            self.font_box.setCurrentFont(QFont(st.font))
            self.size_box.setEditText(f"{st.size:g}")
            self.a_bold.setChecked(st.bold)
            self.a_italic.setChecked(st.italic)
            self.a_underline.setChecked(st.underline)
            self.a_left.setChecked(st.halign == "left")
            self.a_center.setChecked(st.halign == "center")
            self.a_right.setChecked(st.halign == "right")
            self.a_top.setChecked(st.valign == "top")
            self.a_middle.setChecked(st.valign == "center")
            self.a_bottom.setChecked(st.valign == "bottom")
            self.a_wrap.setChecked(st.wrap)
            self.a_merge.setChecked(ws.merge_at(*ws.active) is not None)
            label = next((lbl for lbl, code in NUMBER_FORMATS if code == st.numfmt),
                         "Custom" if st.numfmt != "General" else "General")
            i = self.numfmt_box.findText(label)
            if i >= 0:
                self.numfmt_box.setCurrentIndex(i)
            else:
                self.numfmt_box.setEditText(label) if self.numfmt_box.isEditable() else None
            self.a_filter.setChecked(ws.autofilter is not None)
            self.a_gridlines.setChecked(ws.show_grid)
            self.a_headings.setChecked(ws.show_headers)
            self.a_print_grid.setChecked(ws.page.gridlines)
            self.a_print_heads.setChecked(ws.page.headings)
        finally:
            self._updating = False
        self._update_stats()
        if self.painter_style is not None and not self.grid.drag:
            self._apply_painter()

    def _update_stats(self):
        ws = self.wb.ws
        rngs = ws.selection
        if len(rngs) == 1 and rngs[0][:2] == rngs[0][2:]:
            self.stats_label.setText("")
            return
        s = OPS.selection_stats(self.wb, ws, rngs)
        parts = []
        if s["average"] is not None:
            parts.append(f"Average: {NF.general(s['average'])}")
        if s["count"] > 1:
            parts.append(f"Count: {s['count']}")
        if s["numbers"]:
            parts.append(f"Sum: {NF.general(s['sum'])}")
        self.stats_label.setText("    ".join(parts))

    def _edit_text(self, text):
        if self.formula_bar.edit.text() != text:
            self.formula_bar.edit.setText(text)

    def _editing(self, on):
        self.formula_bar.set_editing(on)
        self.mode_label.setText("Enter" if on and self.grid.editor.enter_mode else ("Edit" if on else "Ready"))

    def content_changed(self):
        self._update_title()
        self.selection_changed()
        self.grid.viewport().update()

    def _zoom_changed(self, z):
        self.zoom_label.setText(f"{z}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(z)
        self.zoom_slider.blockSignals(False)

    def refresh_names(self):
        box = self.formula_bar.name
        text = box.currentText()
        box.blockSignals(True)
        box.clear()
        box.addItems(sorted(self.wb.names))
        box.setEditText(text)
        box.blockSignals(False)

    def _update_title(self):
        name = Path(self.wb.path).name if self.wb.path else self.untitled
        self.setWindowTitle(f"{name}{' *' if self.wb.modified else ''} - {APP}")

    # ==== formatting ==================================================================================
    def ranges(self):
        return list(self.wb.ws.selection)

    def style(self, **changes):
        if self._updating:
            return
        if self.grid.editing:
            self.grid.commit_edit()
        if "halign" in changes and self.cur_style().halign == changes["halign"]:
            changes["halign"] = "general"
        OPS.apply_style(self.wb, self.wb.ws, self.ranges(), **changes)
        self.content_changed()

    def _size_entered(self):
        try:
            size = float(self.size_box.currentText().replace(",", "."))
        except ValueError:
            return
        if 1 <= size <= 409:
            self.style(size=size)

    def step_font(self, d):
        sizes = [float(s) for s in FONT_SIZES]
        cur = self.cur_style().size
        bigger = [s for s in sizes if s > cur]
        smaller = [s for s in sizes if s < cur]
        new = (bigger[0] if bigger else cur + 2) if d > 0 else (smaller[-1] if smaller else max(1, cur - 1))
        self.style(size=new)

    def indent(self, d):
        self.style(indent=max(0, self.cur_style().indent + d), halign="left" if d > 0 else self.cur_style().halign)

    def decimals(self, more):
        self.style(numfmt=OPS.number_format_step(self.cur_style().numfmt, more))

    def _numfmt_chosen(self, i):
        code = self.numfmt_box.itemData(i)
        if code is None:
            self.format_cells(0)
        else:
            self.style(numfmt=code)

    def borders(self, kind):
        self._last_border = kind
        for rng in self.ranges():
            OPS.set_borders(self.wb, self.wb.ws, self._clip_whole(rng), kind)
        self.content_changed()

    def _clip_whole(self, rng):
        r1, c1, r2, c2 = rng
        er, ec = self.wb.ws.extent()
        return r1, c1, min(r2, max(er, r1)), min(c2, max(ec, c1))

    def format_cells(self, tab=0):
        ws = self.wb.ws
        dlg = D.FormatCellsDialog(self.cur_style(), self.wb.value(ws.name, *ws.active), self, tab)
        if dlg.exec() != QDialog.Accepted:
            return
        changes = dlg.changes()
        if changes:
            OPS.apply_style(self.wb, ws, self.ranges(), **changes)
        if dlg.outline_inside in ("outline", "inside", "none"):
            kind = {"outline": "outside", "inside": "all", "none": "none"}[dlg.outline_inside]
            st = dlg._current_border()
            for rng in self.ranges():
                OPS.set_borders(self.wb, ws, self._clip_whole(rng), kind, st.style, st.color)
        if dlg.merge.isChecked():
            self.merge(center=False)
        self.content_changed()

    def merge_center(self):
        if self.wb.ws.merge_at(*self.wb.ws.active):
            self.unmerge()
        else:
            self.merge(center=True)

    def merge(self, center=True, across=False):
        rng = self.grid.selection_range()
        if rng[:2] == rng[2:]:
            return
        filled = [k for k, c in self.wb.ws.cells.items() if rng[0] <= k[0] <= rng[2] and rng[1] <= k[1] <= rng[3]
                  and not c.empty and k != (rng[0], rng[1])]
        if filled and not across:
            if QMessageBox.question(self, APP, "Merging cells only keeps the upper-left value and discards other "
                                               "values.") != QMessageBox.Yes:
                return
        OPS.merge(self.wb, self.wb.ws, rng, center=center, across=across)
        self.grid.select_range(rng)
        self.content_changed()

    def unmerge(self):
        OPS.unmerge(self.wb, self.wb.ws, self.grid.selection_range())
        self.content_changed()

    def cell_style(self, kw):
        base = {"fill": None, "color": "#000000", "bold": False, "size": 11.0}
        base.update(kw)
        self.style(**base)

    def format_as_table(self, name):
        ws = self.wb.ws
        r1, c1, r2, c2 = self.grid.selection_range()
        if (r1, c1) == (r2, c2):
            r1, c1, r2, c2 = OPS.current_region(ws, r1, c1)
        _, dark, light = next(t for t in TABLE_STYLES if t[0] == name)
        self.wb.begin("Format as Table")
        try:
            for c in range(c1, c2 + 1):
                self.wb.set_style(ws, r1, c, fill=dark, color="#ffffff", bold=True)
            for r in range(r1 + 1, r2 + 1):
                for c in range(c1, c2 + 1):
                    self.wb.set_style(ws, r, c, fill=light if (r - r1) % 2 == 1 else None)
        finally:
            self.wb.end()
        OPS.set_borders(self.wb, ws, (r1, c1, r2, c2), "outside", "thin", dark)
        if ws.autofilter is None:
            self.wb.structural("Filter", lambda: setattr(ws, "autofilter", (r1, c1, r2, c2)))
        self.content_changed()

    def format_painter(self, on=True):
        if on:
            self.painter_style = (self.cur_style(), self.grid.selection_range())
            self.statusBar().showMessage("Click a cell to paste the formatting.", 4000)
        else:
            self.painter_style = None

    def _apply_painter(self):
        st, src = self.painter_style
        self.painter_style = None
        self.a_painter.setChecked(False)
        changes = {k: getattr(st, k) for k in st.__dataclass_fields__}
        OPS.apply_style(self.wb, self.wb.ws, self.ranges(), **changes)
        self.content_changed()

    # ---- conditional formatting
    def cond_rule(self, kind):
        from sheet_model import CondRule
        ws = self.wb.ws
        rng = self._clip_whole(self.grid.selection_range())
        prompts = {"greaterThan": ("Greater Than", "Format cells that are GREATER THAN:"),
                   "lessThan": ("Less Than", "Format cells that are LESS THAN:"),
                   "between": ("Between", "Format cells that are BETWEEN:"),
                   "equal": ("Equal To", "Format cells that are EQUAL TO:"),
                   "containsText": ("Text That Contains", "Format cells that contain the text:"),
                   "duplicateValues": ("Duplicate Values", "Format cells that contain duplicate values:"),
                   "top10": ("Top 10 Items", "Format cells that rank in the TOP:"),
                   "bottom10": ("Bottom 10 Items", "Format cells that rank in the BOTTOM:"),
                   "aboveAverage": ("Above Average", "Format cells that are ABOVE AVERAGE:"),
                   "belowAverage": ("Below Average", "Format cells that are BELOW AVERAGE:")}
        title, prompt = prompts[kind]
        value = "10" if kind in ("top10", "bottom10") else ""
        dlg = D.CondRuleDialog(title, prompt, kind == "between", value, self)
        if kind in ("duplicateValues", "aboveAverage", "belowAverage"):
            dlg.v1.setVisible(False)
        if dlg.exec() != QDialog.Accepted:
            return
        fill, color = dlg.style()

        def lit(t):
            t = t.strip()
            n = F.to_number(t)
            return t if isinstance(n, float) or t.startswith("=") else '"' + t.replace('"', '""') + '"'
        if kind in ("greaterThan", "lessThan", "equal", "between"):
            formulas = [lit(dlg.v1.text())] + ([lit(dlg.v2.text())] if dlg.v2 else [])
            rule = CondRule([rng], "cellIs", kind, [f.lstrip("=") for f in formulas], fill, color)
        elif kind == "containsText":
            rule = CondRule([rng], "containsText", "containsText", [], fill, color, text=dlg.v1.text())
        elif kind in ("top10", "bottom10"):
            rule = CondRule([rng], "top10", "", [], fill, color, rank=int(F.to_number(dlg.v1.text()) or 10)
                            if isinstance(F.to_number(dlg.v1.text()), float) else 10, bottom=kind == "bottom10")
        else:
            rule = CondRule([rng], kind, "", [], fill, color)
        rule.priority = len(ws.cond) + 1
        self.wb.structural("Conditional Formatting", lambda: ws.cond.append(rule))
        self.content_changed()

    def cond_bar(self, color):
        from sheet_model import CondRule
        ws = self.wb.ws
        rule = CondRule([self._clip_whole(self.grid.selection_range())], "dataBar", colors=[color])
        self.wb.structural("Data Bars", lambda: ws.cond.append(rule))
        self.content_changed()

    def cond_scale(self, colors):
        from sheet_model import CondRule
        ws = self.wb.ws
        rule = CondRule([self._clip_whole(self.grid.selection_range())], "colorScale", colors=list(colors))
        self.wb.structural("Color Scale", lambda: ws.cond.append(rule))
        self.content_changed()

    def clear_rules(self, selected):
        ws = self.wb.ws
        r1, c1, r2, c2 = self.grid.selection_range()

        def do():
            if not selected:
                ws.cond.clear()
                return
            ws.cond[:] = [rule for rule in ws.cond if not any(
                a[0] <= r2 and a[2] >= r1 and a[1] <= c2 and a[3] >= c1 for a in rule.ranges)]
        self.wb.structural("Clear Rules", do)
        self.content_changed()

    # ==== editing ========================================================================================
    def undo(self):
        if self.grid.editing:
            self.grid.cancel_edit()
            return
        label = self.wb.undo()
        if label:
            self.grid.invalidate()
            self.tabs.refresh()
            self.content_changed()

    def redo(self):
        label = self.wb.redo()
        if label:
            self.grid.invalidate()
            self.tabs.refresh()
            self.content_changed()

    def copy(self, cut=False):
        if self.grid.editing:
            self.grid.editor.cut() if cut else self.grid.editor.copy()
            return
        if self.grid.selected_object is not None:
            return
        ws = self.wb.ws
        rng = self._clip_whole(self.grid.selection_range())
        self.clip = OPS.copy_range(self.wb, ws, *rng, cut=cut)
        self.clip_owner = ws
        md = QMimeData()
        md.setText(OPS.as_text(self.wb, ws, *rng))
        md.setHtml(OPS.as_html(self.wb, ws, *rng))
        md.setData("application/x-classic7-sheet", str(id(self.clip)).encode())
        QApplication.clipboard().setMimeData(md)
        self.grid.show_copy(rng)

    def cut(self):
        self.copy(cut=True)

    def paste(self, what="all", transpose=False):
        if self.grid.editing:
            self.grid.editor.paste()
            return
        ws = self.wb.ws
        md = QApplication.clipboard().mimeData()
        r1, c1, r2, c2 = self.grid.selection_range()
        ours = self.clip is not None and md is not None and md.hasFormat("application/x-classic7-sheet") and \
            bytes(md.data("application/x-classic7-sheet")).decode() == str(id(self.clip))
        if ours:
            OPS.paste(self.wb, ws, self.clip, r1, c1, what, target=(r1, c1, r2, c2), transpose=transpose,
                      src_ws=self.clip_owner)
            rows, cols = (self.clip.cols, self.clip.rows) if transpose else (self.clip.rows, self.clip.cols)
            if self.clip.cut:
                self.clip = None
                self.grid.copy_range = None
            if (r1, c1) == (r2, c2):
                self.grid.select_range((r1, c1, r1 + rows - 1, c1 + cols - 1))
        elif md is not None and md.hasImage() and not md.hasText():
            self._paste_image(md.imageData())
        elif md is not None and md.hasText():
            rows, cols = OPS.paste_text(self.wb, ws, md.text(), r1, c1)
            self.grid.select_range((r1, c1, r1 + rows - 1, c1 + cols - 1))
        self.content_changed()

    def paste_special(self):
        dlg = D.PasteSpecialDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.paste(dlg.key(), transpose=dlg.transpose.isChecked())

    def _paste_image(self, img):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        ws = self.wb.ws
        im = {"data": bytes(ba), "anchor": ws.active, "size": (img.width(), img.height())}
        self.wb.structural("Paste Picture", lambda: ws.images.append(im))

    def clear(self, what):
        for rng in self.ranges():
            OPS.clear(self.wb, self.wb.ws, *self._clip_whole(rng), what=what)
        self.content_changed()

    def select_all(self):
        if self.grid.editing:
            self.grid.editor.selectAll()
            return
        self.grid.select_range((0, 0, MAX_ROWS - 1, MAX_COLS - 1), active=self.wb.ws.active)

    def fill_dir(self, d):
        r1, c1, r2, c2 = self.grid.selection_range()
        ws = self.wb.ws
        if d == "down" and r2 > r1:
            OPS.fill(self.wb, ws, (r1, c1, r1, c2), (r1, c1, r2, c2), copy_only=True)
        elif d == "right" and c2 > c1:
            OPS.fill(self.wb, ws, (r1, c1, r2, c1), (r1, c1, r2, c2), copy_only=True)
        elif d == "up" and r2 > r1:
            OPS.fill(self.wb, ws, (r2, c1, r2, c2), (r1, c1, r2, c2), copy_only=True)
        elif d == "left" and c2 > c1:
            OPS.fill(self.wb, ws, (r1, c2, r2, c2), (r1, c1, r2, c2), copy_only=True)
        elif d == "down" and r1 > 0:
            OPS.fill(self.wb, ws, (r1 - 1, c1, r1 - 1, c2), (r1 - 1, c1, r2, c2), copy_only=True)
        elif d == "right" and c1 > 0:
            OPS.fill(self.wb, ws, (r1, c1 - 1, r2, c1 - 1), (r1, c1 - 1, r2, c2), copy_only=True)
        self.content_changed()

    def autosum(self, fn="SUM"):
        ws = self.wb.ws
        r1, c1, r2, c2 = self.grid.selection_range()
        if (r1, c1) != (r2, c2):
            # a block: totals under each column
            self.wb.begin("AutoSum")
            try:
                for c in range(c1, c2 + 1):
                    target = r2 + 1 if any(isinstance(self.wb.value(ws.name, r, c), float) for r in range(r1, r2 + 1)) else None
                    if target is not None:
                        self.wb.set_input(ws, target, c, f"={fn}({cell_name(r1, c)}:{cell_name(r2, c)})")
            finally:
                self.wb.end()
            self.content_changed()
            return
        rng = OPS.autosum_range(self.wb, ws, r1, c1) or ""
        self.grid.start_edit(f"={fn}({rng})", enter_mode=False)
        if rng:
            self.grid.editor.setSelection(len(fn) + 2, len(rng))

    def insert_function(self, name=None):
        if not name:
            dlg = D.InsertFunctionDialog(self)
            if dlg.exec() != QDialog.Accepted or not dlg.function():
                return
            name = dlg.function()
        g = self.grid
        if g.editing and g.editor.text().startswith("="):
            g.editor.insert(f"{name}()")
            g.editor.cursorBackward(False)
            g._editor_changed(g.editor.text())
        else:
            g.start_edit(f"={name}()", enter_mode=False)
            g.editor.setCursorPosition(len(name) + 2)
        hint = F.describe(name)
        if hint:
            self.statusBar().showMessage(hint, 10000)

    def insert_now(self, time):
        import datetime as dt
        now = dt.datetime.now()
        text = now.strftime("%H:%M") if time else now.strftime("%d-%m-%Y")
        if self.grid.editing:
            self.grid.editor.insert(text)
        else:
            self.wb.set_input(self.wb.ws, *self.wb.ws.active, text)
            self.content_changed()

    def _insert_symbol(self, ch):
        if self.grid.editing:
            self.grid.editor.insert(ch)
        else:
            self.grid.start_edit(self.grid.edit_text_for(*self.wb.ws.active) + ch, enter_mode=False)

    # ---- rows, columns, cells
    def _sel_rows(self):
        r1, _, r2, _ = self.grid.selection_range()
        return list(range(r1, min(r2, r1 + 5000) + 1))

    def _sel_cols(self):
        _, c1, _, c2 = self.grid.selection_range()
        return list(range(c1, min(c2, c1 + 1000) + 1))

    def insert_delete(self, axis, sign):
        r1, c1, r2, c2 = self.grid.selection_range()
        at, n = (r1, r2 - r1 + 1) if axis == "row" else (c1, c2 - c1 + 1)
        n = min(n, 5000)
        label = ("Insert " if sign > 0 else "Delete ") + ("Rows" if axis == "row" else "Columns")
        self.wb.structural(label, lambda: self.wb.insert(self.wb.ws, axis, at, n * sign))
        self.grid.invalidate()
        self.content_changed()

    def insert_cells_dialog(self):
        rng = self.grid.selection_range()
        if rng[0] == 0 and rng[2] >= MAX_ROWS - 1:
            return self.insert_delete("col", 1)
        if rng[1] == 0 and rng[3] >= MAX_COLS - 1:
            return self.insert_delete("row", 1)
        dlg = D.InsertDeleteDialog(False, self)
        if dlg.exec() == QDialog.Accepted:
            self._shift_cells(dlg.key(), 1)

    def delete_cells_dialog(self):
        rng = self.grid.selection_range()
        if rng[0] == 0 and rng[2] >= MAX_ROWS - 1:
            return self.insert_delete("col", -1)
        if rng[1] == 0 and rng[3] >= MAX_COLS - 1:
            return self.insert_delete("row", -1)
        dlg = D.InsertDeleteDialog(True, self)
        if dlg.exec() == QDialog.Accepted:
            self._shift_cells(dlg.key(), -1)

    def _shift_cells(self, key, sign):
        if key in ("row", "col"):
            return self.insert_delete(key, sign)
        ws = self.wb.ws
        r1, c1, r2, c2 = self.grid.selection_range()
        h, w = r2 - r1 + 1, c2 - c1 + 1

        def do():
            cells = ws.cells
            moved = {}
            for (r, c), cell in list(cells.items()):
                if key in ("down", "up") and c1 <= c <= c2 and r >= r1:
                    if key == "down":
                        moved[(r + h, c)] = cell
                    elif r > r2:
                        moved[(r - h, c)] = cell
                    del cells[(r, c)]
                elif key in ("right", "left") and r1 <= r <= r2 and c >= c1:
                    if key == "right":
                        moved[(r, c + w)] = cell
                    elif c > c2:
                        moved[(r, c - w)] = cell
                    del cells[(r, c)]
            cells.update(moved)
            ws.shrank()
        self.wb.structural("Insert Cells" if sign > 0 else "Delete Cells", do)
        self.content_changed()

    def row_height(self):
        ws = self.wb.ws
        rows = self._sel_rows()
        dlg = D.NumberDialog("Row Height", "Row height:", ws.row_height(rows[0]) or ws.default_height, 0, 409, 2, self)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.value()
            self.wb.structural("Row Height", lambda: ws.row_heights.update({r: v for r in rows}))
            self.grid.invalidate()

    def col_width(self):
        ws = self.wb.ws
        cols = self._sel_cols()
        dlg = D.NumberDialog("Column Width", "Column width:", ws.col_width(cols[0]) or ws.default_width, 0, 255, 2, self)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.value()
            self.wb.structural("Column Width", lambda: ws.col_widths.update({c: v for c in cols}))
            self.grid.invalidate()

    def default_width(self):
        ws = self.wb.ws
        dlg = D.NumberDialog("Standard Width", "Standard column width:", ws.default_width, 0, 255, 2, self)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.value()
            self.wb.structural("Standard Width", lambda: setattr(ws, "default_width", v))
            self.grid.invalidate()

    def hide_rows(self, hide):
        ws = self.wb.ws
        rows = self._sel_rows()
        if hide:
            self.wb.structural("Hide Rows", lambda: ws.hidden_rows.update(rows))
        else:
            r1, _, r2, _ = self.grid.selection_range()
            self.wb.structural("Unhide Rows", lambda: ws.hidden_rows.difference_update(
                {r for r in ws.hidden_rows if r1 - 1 <= r <= r2 + 1}))
        self.grid.invalidate()

    def hide_cols(self, hide):
        ws = self.wb.ws
        cols = self._sel_cols()
        if hide:
            self.wb.structural("Hide Columns", lambda: ws.hidden_cols.update(cols))
        else:
            _, c1, _, c2 = self.grid.selection_range()
            self.wb.structural("Unhide Columns", lambda: ws.hidden_cols.difference_update(
                {c for c in ws.hidden_cols if c1 - 1 <= c <= c2 + 1}))
        self.grid.invalidate()

    # ---- sheets
    def insert_sheet(self, end=False):
        wb = self.wb
        at = len(wb.sheets) if end else wb.active

        def do():
            ws = wb.add_sheet(None, at)
            wb.active = wb.sheets.index(ws)
        wb.structural("Insert Sheet", do)
        self.tabs.refresh()
        self.switch_sheet(self.wb.active, force=True)

    def delete_sheet(self):
        wb = self.wb
        if len([s for s in wb.sheets if not s.hidden]) <= 1:
            QMessageBox.warning(self, APP, "A workbook must contain at least one visible worksheet.")
            return
        ws = wb.ws
        if ws.cells and QMessageBox.question(self, APP, f"Data may exist in the sheet \"{ws.name}\". To permanently "
                                                         "delete the data, click Delete.") != QMessageBox.Yes:
            return

        def do():
            wb.sheets.remove(ws)
            wb.reindex()
            wb.active = max(0, min(wb.active, len(wb.sheets) - 1))
        wb.structural("Delete Sheet", do)
        self.tabs.refresh()
        self.switch_sheet(wb.active, force=True)

    def rename_sheet(self, i):
        if i < 0:
            return
        ws = self.wb.sheets[i]
        name, ok = QInputDialog.getText(self, "Rename Sheet", "Sheet name:", text=ws.name)
        name = name.strip()
        if not ok or not name or name == ws.name:
            return
        if len(name) > 31 or any(ch in name for ch in "[]:*?/\\") or (self.wb.sheet(name) and self.wb.sheet(name) is not ws):
            QMessageBox.warning(self, APP, "That sheet name is not valid or is already taken. Names can have up to 31 "
                                           "characters and can't contain : \\ / ? * [ ]")
            return
        self.wb.structural("Rename Sheet", lambda: self.wb.rename_sheet(ws, name))
        self.tabs.refresh()

    def copy_sheet(self):
        import copy as cp
        wb = self.wb
        ws = wb.ws
        names = [s.name for s in wb.sheets] + ["(move to end)"]
        item, ok = QInputDialog.getItem(self, "Move or Copy", "Before sheet (a copy is made):", names, 0, False)
        if not ok:
            return
        at = names.index(item)

        def do():
            new = wb.add_sheet(_copy_name(wb, ws.name), at)
            for attr in ("cells", "col_widths", "row_heights", "hidden_rows", "hidden_cols", "col_styles",
                         "row_styles", "merges", "freeze", "autofilter", "comments", "links", "tab_color",
                         "show_grid", "zoom", "default_width", "default_height"):
                v = getattr(ws, attr)
                setattr(new, attr, cp.copy(v) if isinstance(v, (dict, list, set)) else v)
            new.charts = cp.deepcopy(ws.charts)
            new.cond = cp.deepcopy(ws.cond)
            new.page = cp.deepcopy(ws.page)
            wb.active = wb.sheets.index(new)
        wb.structural("Copy Sheet", do)
        self.tabs.refresh()
        self.switch_sheet(wb.active, force=True)

    def tab_color(self, color):
        ws = self.wb.ws
        self.wb.structural("Tab Color", lambda: setattr(ws, "tab_color", color))
        self.tabs.refresh()

    def hide_sheet(self):
        wb = self.wb
        if len([s for s in wb.sheets if not s.hidden]) <= 1:
            QMessageBox.warning(self, APP, "A workbook must contain at least one visible worksheet.")
            return
        ws = wb.ws
        wb.structural("Hide Sheet", lambda: setattr(ws, "hidden", True))
        self.tabs.refresh()
        self.step_sheet(1 if wb.active < len(wb.sheets) - 1 else -1)

    def unhide_sheet(self):
        hidden = [s.name for s in self.wb.sheets if s.hidden]
        if not hidden:
            return
        name, ok = QInputDialog.getItem(self, "Unhide", "Unhide sheet:", hidden, 0, False)
        if ok:
            ws = self.wb.sheet(name)
            self.wb.structural("Unhide Sheet", lambda: setattr(ws, "hidden", False))
            self.tabs.refresh()
            self.switch_sheet(self.wb.sheets.index(ws))

    # ---- sort and filter
    def _data_range(self):
        ws = self.wb.ws
        rng = self.grid.selection_range()
        if rng[:2] == rng[2:]:
            rng = OPS.current_region(ws, rng[0], rng[1])
        return self._clip_whole(rng)

    def _has_header(self, rng):
        ws = self.wb.ws
        r1, c1, r2, c2 = rng
        if r2 == r1:
            return False
        top = [self.wb.value(ws.name, r1, c) for c in range(c1, c2 + 1)]
        below = [self.wb.value(ws.name, r1 + 1, c) for c in range(c1, c2 + 1)]
        return all(isinstance(v, str) for v in top if v is not None) and any(not isinstance(v, str) for v in below
                                                                              if v is not None) or \
            self.wb.ws.style_of(r1, c1).bold != self.wb.ws.style_of(min(r1 + 1, r2), c1).bold

    def sort(self, ascending):
        ws = self.wb.ws
        rng = self._data_range()
        col = ws.active[1] if rng[1] <= ws.active[1] <= rng[3] else rng[1]
        OPS.sort_range(self.wb, ws, rng, [(col, ascending)], header=self._has_header(rng))
        self.content_changed()

    def custom_sort(self):
        ws = self.wb.ws
        rng = self._data_range()
        header = self._has_header(rng)
        cols = [(c, (F.to_text(self.wb.value(ws.name, rng[0], c)) if header else "") or f"Column {cell_name(0, c)[:-1]}")
                for c in range(rng[1], rng[3] + 1)]
        dlg = D.SortDialog(cols, header, self)
        if dlg.exec() == QDialog.Accepted:
            OPS.sort_range(self.wb, ws, rng, dlg.keys(), header=dlg.header.isChecked())
            self.content_changed()

    def toggle_filter(self, on=None):
        ws = self.wb.ws
        if ws.autofilter is not None:
            def off():
                ws.autofilter = None
                ws.filters.clear()
                ws.hidden_rows.clear()
            self.wb.structural("Filter", off)
        else:
            rng = self._data_range()
            self.wb.structural("Filter", lambda: setattr(ws, "autofilter", rng))
        self.grid.invalidate()
        self.selection_changed()

    def filter_menu(self, col, pos):
        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPushButton, QWidgetAction
        ws = self.wb.ws
        rng = ws.autofilter
        values = OPS.column_values(self.wb, ws, rng, col)
        allowed = ws.filters.get(col)
        m = QMenu(self)
        m.addAction(rb.icon("view-sort-ascending", "A"), "Sort A to Z", lambda: self._filter_sort(col, True))
        m.addAction(rb.icon("view-sort-descending", "Z"), "Sort Z to A", lambda: self._filter_sort(col, False))
        m.addSeparator()
        m.addAction(f"Clear Filter From \"{F.to_text(self.wb.value(ws.name, rng[0], col)) or cell_name(0, col)[:-1]}\"",
                    lambda: self._set_filter(col, None)).setEnabled(allowed is not None)
        box = QWidget()
        lay = QVBoxLayout(box)
        lst = QListWidget()
        lst.setMinimumSize(200, 180)
        all_item = QListWidgetItem("(Select All)")
        all_item.setFlags(all_item.flags() | Qt.ItemIsUserCheckable)
        all_item.setCheckState(Qt.Checked if allowed is None else Qt.Unchecked)
        lst.addItem(all_item)
        for v in values:
            it = QListWidgetItem(v if v else "(Blanks)")
            it.setData(Qt.UserRole, v)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if allowed is None or v in allowed else Qt.Unchecked)
            lst.addItem(it)

        def changed(item):
            if item is all_item:
                st = item.checkState()
                lst.blockSignals(True)
                for i in range(1, lst.count()):
                    lst.item(i).setCheckState(st)
                lst.blockSignals(False)
        lst.itemChanged.connect(changed)
        lay.addWidget(lst)
        ok = QPushButton("OK")
        lay.addWidget(ok)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(box)
        m.addAction(wa)

        def apply():
            chosen = {lst.item(i).data(Qt.UserRole) for i in range(1, lst.count())
                      if lst.item(i).checkState() == Qt.Checked}
            self._set_filter(col, None if len(chosen) == len(values) else chosen)
            m.close()
        ok.clicked.connect(apply)
        m.exec(pos)

    def _set_filter(self, col, allowed):
        ws = self.wb.ws

        def do():
            if allowed is None:
                ws.filters.pop(col, None)
            else:
                ws.filters[col] = set(allowed)
            OPS.apply_filter(self.wb, ws)
        self.wb.structural("Filter", do)
        self.grid.invalidate()
        self.content_changed()

    def _filter_sort(self, col, asc):
        ws = self.wb.ws
        OPS.sort_range(self.wb, ws, ws.autofilter, [(col, asc)], header=True)
        self.content_changed()

    def clear_filter(self):
        ws = self.wb.ws
        if ws.autofilter:
            def do():
                ws.filters.clear()
                OPS.apply_filter(self.wb, ws)
            self.wb.structural("Clear Filter", do)
            self.grid.invalidate()

    def reapply_filter(self):
        ws = self.wb.ws
        if ws.autofilter:
            self.wb.structural("Reapply", lambda: OPS.apply_filter(self.wb, ws))
            self.grid.invalidate()

    def remove_duplicates(self):
        ws = self.wb.ws
        rng = self._data_range()
        header = self._has_header(rng)
        n = OPS.remove_duplicates(self.wb, ws, rng, list(range(rng[1], rng[3] + 1)), header)
        QMessageBox.information(self, APP, f"{n} duplicate values found and removed; "
                                           f"{rng[2] - rng[0] + (0 if header else 1) - n} unique values remain." if n
                                else "No duplicate values found.")
        self.content_changed()

    def text_to_columns(self):
        ws = self.wb.ws
        r1, c1, r2, c2 = self._clip_whole(self.grid.selection_range())
        sep, ok = QInputDialog.getItem(self, "Convert Text to Columns", "Split the text at:",
                                       ["Comma", "Semicolon", "Tab", "Space", "Other..."], 0, False)
        if not ok:
            return
        ch = {"Comma": ",", "Semicolon": ";", "Tab": "\t", "Space": " "}.get(sep)
        if ch is None:
            ch, ok = QInputDialog.getText(self, "Convert Text to Columns", "Character:")
            if not ok or not ch:
                return
        self.wb.begin("Text to Columns")
        try:
            for r in range(r1, r2 + 1):
                v = self.wb.value(ws.name, r, c1)
                if not isinstance(v, str):
                    continue
                for j, part in enumerate(v.split(ch)):
                    self.wb.set_input(ws, r, c1 + j, part.strip())
        finally:
            self.wb.end()
        self.content_changed()

    def data_validation(self):
        from sheet_model import Validation
        ws = self.wb.ws
        rng = self._clip_whole(self.grid.selection_range())
        current = self.grid._validation_at(*ws.active)
        dlg = D.ValidationDialog(current, self)
        if dlg.exec() != QDialog.Accepted:
            return

        def do():
            ws.validations[:] = [v for v in ws.validations if v is not current]
            if not dlg.cleared and dlg.kind.currentData() != "any":
                ws.validations.append(Validation([rng], dlg.kind.currentData(), dlg.f1.text().strip(),
                                                 dlg.f2.text().strip(), dlg.op.currentData(), error=dlg.error.text()))
        self.wb.structural("Data Validation", do)
        self.grid.viewport().update()

    def import_text(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Import Text File", str(Path.home()), "Text Files (*.csv *.txt *.tsv);;All Files (*)")
        if not fn:
            return
        try:
            src = IO.read_csv(fn)
        except (OSError, IO.OpenError) as e:
            QMessageBox.warning(self, APP, str(e))
            return
        clip = OPS.copy_range(src, src.sheets[0], 0, 0, *src.sheets[0].extent())
        OPS.paste(self.wb, self.wb.ws, clip, *self.wb.ws.active, "values")
        self.content_changed()

    # ---- names, comments, links
    def define_name(self):
        r = self.grid.selection_range()
        dlg = D.DefineNameDialog(f"={_quote(self.wb.ws.name)}!{_abs(r)}", self)
        if dlg.exec() == QDialog.Accepted and dlg.name.text().strip():
            name = dlg.name.text().strip()
            self.wb.structural("Define Name", lambda: self.wb.names.__setitem__(name, dlg.ref.text()))
            self.wb.rebuild_dependencies()
            self.refresh_names()

    def name_manager(self):
        D.NameManagerDialog(self.wb, self).exec()
        self.wb.rebuild_dependencies()
        self.wb.recalc("all")
        self.refresh_names()
        self.grid.viewport().update()

    def _fill_names_menu(self):
        self.use_in_formula.clear()
        for n in sorted(self.wb.names):
            self.use_in_formula.addAction(n, lambda n=n: self._insert_text(n))
        if not self.wb.names:
            self.use_in_formula.addAction("(no names)").setEnabled(False)

    def _insert_text(self, t):
        if self.grid.editing:
            self.grid.editor.insert(t)
        else:
            self.grid.start_edit("=" + t, enter_mode=False)

    def edit_comment(self):
        ws = self.wb.ws
        key = ws.active
        dlg = D.CommentDialog(ws.comments.get(key, ""), self)
        if dlg.exec() == QDialog.Accepted:
            text = dlg.edit.toPlainText().strip()

            def do():
                if text:
                    ws.comments[key] = text
                else:
                    ws.comments.pop(key, None)
            self.wb.structural("Comment", do)
            self.grid.viewport().update()

    def delete_comment(self):
        ws = self.wb.ws
        r1, c1, r2, c2 = self.grid.selection_range()
        self.wb.structural("Delete Comment", lambda: [ws.comments.pop(k) for k in list(ws.comments)
                                                      if r1 <= k[0] <= r2 and c1 <= k[1] <= c2])
        self.grid.viewport().update()

    def hyperlink(self):
        ws = self.wb.ws
        key = ws.active
        text = self.wb.display(ws, *key)[0]
        dlg = D.HyperlinkDialog(text, ws.links.get(key, ""), self)
        if dlg.exec() != QDialog.Accepted:
            return
        url = dlg.url.text().strip()
        if url and "://" not in url and not url.startswith(("mailto:", "/")):
            url = "https://" + url

        def do():
            if url:
                ws.links[key] = url
            else:
                ws.links.pop(key, None)
        self.wb.structural("Hyperlink", do)
        if dlg.text.text() and dlg.text.text() != text:
            self.wb.set_input(ws, *key, dlg.text.text())
        if url:
            self.wb.set_style(ws, *key, color="#0000ff", underline=True)
        self.content_changed()

    # ---- charts and pictures
    def insert_chart(self, kind, grouping=None):
        import sheet_chart
        ws = self.wb.ws
        rng = self._data_range()
        if rng[:2] == rng[2:] and self.wb.value(ws.name, rng[0], rng[1]) is None:
            QMessageBox.information(self, APP, "Select the data for the chart first (for example the table with "
                                               "its headings), then choose a chart.")
            return
        ch = sheet_chart.from_selection(self.wb, ws, *rng, kind)
        if grouping:
            ch.grouping = grouping
        self.wb.structural("Insert Chart", lambda: ws.charts.append(ch))
        self.grid.selected_object = ch
        self.grid.viewport().update()
        self.content_changed()

    def chart_options(self, obj):
        if isinstance(obj, dict):
            return
        dlg = D.ChartOptionsDialog(obj, self)
        if dlg.exec() == QDialog.Accepted:
            self.wb.structural("Chart Layout", lambda: dlg.apply(obj))
            obj.raw = None
            self.grid.viewport().update()

    def change_chart_type(self, obj):
        dlg = D.ChartTypeDialog(obj.kind, self)
        if dlg.exec() == QDialog.Accepted:
            kind = dlg.kind()

            def do():
                obj.kind = kind
                obj.grouping = dlg.grouping(kind)
                obj.raw = None
            self.wb.structural("Change Chart Type", do)
            self.grid.viewport().update()

    def insert_picture(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Insert Picture", str(Path.home() / "Pictures"),
                                            "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.webp)")
        if not fn:
            return
        from PySide6.QtGui import QImage
        img = QImage(fn)
        if img.isNull():
            QMessageBox.warning(self, APP, "The picture could not be read.")
            return
        w, h = img.width(), img.height()
        if w > 640:
            h, w = int(h * 640 / w), 640
        ws = self.wb.ws
        im = {"data": Path(fn).read_bytes(), "anchor": ws.active, "size": (w, h)}
        self.wb.structural("Insert Picture", lambda: ws.images.append(im))
        self.grid.viewport().update()

    # ---- view
    def toggle_grid(self, on):
        self.wb.ws.show_grid = on
        self.grid.viewport().update()

    def toggle_headings(self, on):
        self.wb.ws.show_headers = on
        self.grid.invalidate()

    def toggle_formula_bar(self, on):
        self.formula_bar.setVisible(on)

    def toggle_formulas(self, on):
        self.show_formulas = on
        self.grid.show_formulas = on
        self.grid._axes = None
        self.grid.viewport().update()

    def freeze(self):
        ws = self.wb.ws
        if ws.freeze:
            self.set_freeze(None)
        else:
            r, c = ws.active
            self.set_freeze((r, c) if (r, c) != (0, 0) else None)

    def set_freeze(self, at):
        ws = self.wb.ws
        self.wb.structural("Freeze Panes", lambda: setattr(ws, "freeze", at))
        self.grid.invalidate()

    def zoom_dialog(self):
        v, ok = QInputDialog.getInt(self, "Zoom", "Magnification (%):", self.wb.ws.zoom, 10, 400, 10)
        if ok:
            self.grid.set_zoom(v)

    def zoom_selection(self):
        r1, c1, r2, c2 = self._clip_whole(self.grid.selection_range())
        ax, ay = self.grid.axes()
        w = (ax.pos(c2 + 1) - ax.pos(c1)) / self.grid.z
        h = (ay.pos(r2 + 1) - ay.pos(r1)) / self.grid.z
        vw = self.grid.viewport().width() - self.grid.header_w
        vh = self.grid.viewport().height() - self.grid.header_h
        z = int(min(vw / max(w, 1), vh / max(h, 1)) * 100)
        self.grid.set_zoom(max(10, min(400, z)))
        self.grid.ensure_visible(r1, c1)

    def calculate(self):
        self.wb.recalc("all")
        self.grid.viewport().update()
        if self.wb.circular:
            self.statusBar().showMessage("Circular References: " + ", ".join(
                cell_name(r, c) for _s, r, c in sorted(self.wb.circular)[:5]), 8000)

    def set_calc(self, auto):
        self.wb.calc_auto = auto
        if auto:
            self.calculate()

    # ---- page setup
    def page_setup(self):
        ws = self.wb.ws
        dlg = D.PageSetupDialog(ws.page, self)
        if dlg.exec() == QDialog.Accepted:
            import copy
            page = copy.deepcopy(ws.page)
            dlg.apply(page)
            self.wb.structural("Page Setup", lambda: setattr(ws, "page", page))
            self.selection_changed()

    def _page_change(self, label, **kw):
        ws = self.wb.ws
        import copy
        page = copy.deepcopy(ws.page)
        for k, v in kw.items():
            setattr(page, k, v)
        self.wb.structural(label, lambda: setattr(ws, "page", page))

    def set_margins(self, m):
        self._page_change("Margins", margins=m)

    def set_orientation(self, o):
        self._page_change("Orientation", orientation=o)

    def set_paper(self, p):
        self._page_change("Size", paper=p)

    def set_print_area(self):
        self._page_change("Set Print Area", print_area=self._clip_whole(self.grid.selection_range()))

    def clear_print_area(self):
        self._page_change("Clear Print Area", print_area=None)

    def _fit_changed(self):
        self._page_change("Scale to Fit", fit_width=self.fit_width.currentIndex(), fit_height=self.fit_height.currentIndex())

    def _page_opt(self, key, on):
        if not self._updating:
            self._page_change("Sheet Options", **{key: on})

    # ---- find, go to
    def show_find(self, replace_tab):
        if self.find_dialog is None:
            self.find_dialog = D.FindDialog(self, replace_tab)
            self.find_dialog.find_next.connect(self._find_next)
            self.find_dialog.find_all.connect(self._find_all)
            self.find_dialog.replace_one.connect(self._replace_one)
            self.find_dialog.replace_all.connect(self._replace_all)
        self.find_dialog.tabs.setCurrentIndex(1 if replace_tab else 0)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.what.setFocus()

    def _hits(self, text, opts):
        sheets = self.wb.sheets if opts["workbook"] else [self.wb.ws]
        return OPS.find_all(self.wb, sheets, text, opts["case"], opts["whole"], opts["formulas"])

    def _find_next(self, text, opts):
        hits = self._hits(text, opts)
        if not hits:
            QMessageBox.information(self.find_dialog, APP, "Sheet cannot find the data you're searching for.")
            return
        cur = (self.wb.active, *self.wb.ws.active)
        order = [(self.wb.sheets.index(ws), r, c, ws) for ws, r, c in hits]
        nxt = next((h for h in order if (h[0], h[1], h[2]) > cur), order[0])
        if nxt[0] != self.wb.active:
            self.switch_sheet(nxt[0])
        self.grid.select(nxt[1], nxt[2])

    def _find_all(self, text, opts):
        hits = self._hits(text, opts)
        lst = self.find_dialog.results
        lst.clear()
        lst.setVisible(True)
        for ws, r, c in hits:
            lst.addItem(f"{ws.name}!{cell_name(r, c)}   {self.wb.display(ws, r, c)[0]}")
        try:
            lst.itemDoubleClicked.disconnect()
        except (RuntimeError, TypeError):
            pass
        lst.itemDoubleClicked.connect(lambda it: self._goto_hit(hits[lst.row(it)]))

    def _goto_hit(self, hit):
        ws, r, c = hit
        self.switch_sheet(self.wb.sheets.index(ws))
        self.grid.select(r, c)

    def _replace_one(self, find, repl, opts):
        ws = self.wb.ws
        if OPS.replace_in(self.wb, ws, *ws.active, find, repl, opts["case"]):
            self.content_changed()
        self._find_next(find, opts)

    def _replace_all(self, find, repl, opts):
        n = 0
        self.wb.begin("Replace All")
        try:
            for ws, r, c in self._hits(find, {**opts, "formulas": True}):
                if OPS.replace_in(self.wb, ws, r, c, find, repl, opts["case"]):
                    n += 1
        finally:
            self.wb.end()
        self.content_changed()
        QMessageBox.information(self.find_dialog, APP, f"Sheet has completed its search and has made {n} replacements.")

    def go_to(self):
        dlg = D.GoToDialog(sorted(self.wb.names), self)
        if dlg.exec() == QDialog.Accepted and dlg.ref.text().strip():
            self.formula_bar.name.setEditText(dlg.ref.text().strip())
            self.formula_bar._go()

    # ==== context menus ===================================================================================
    def context_menu(self, pos, kind):
        m = QMenu(self)
        if kind == "object":
            obj = self.grid.selected_object
            if obj is not None and not isinstance(obj, dict):
                m.addAction("Change Chart Type...", lambda: self.change_chart_type(obj))
                m.addAction("Chart Layout...", lambda: self.chart_options(obj))
            m.addAction(rb.icon("edit-delete", "X"), "Delete", lambda: self.grid.keyPressEvent(
                _key(Qt.Key_Delete)))
            m.exec(pos)
            return
        m.addAction(self.a_cut)
        m.addAction(self.a_copy)
        m.addAction(self.a_paste)
        m.addAction("Paste Special...", self.paste_special)
        m.addSeparator()
        if kind == "rows":
            m.addAction("Insert", lambda: self.insert_delete("row", 1))
            m.addAction("Delete", lambda: self.insert_delete("row", -1))
        elif kind == "cols":
            m.addAction("Insert", lambda: self.insert_delete("col", 1))
            m.addAction("Delete", lambda: self.insert_delete("col", -1))
        else:
            m.addAction("Insert...", self.insert_cells_dialog)
            m.addAction("Delete...", self.delete_cells_dialog)
        m.addAction("Clear Contents", lambda: self.clear("contents"))
        m.addSeparator()
        if kind == "cells":
            filt = m.addMenu("Filter")
            filt.addAction(self.a_filter)
            sort = m.addMenu("Sort")
            sort.addAction(self.a_sort_az)
            sort.addAction(self.a_sort_za)
            sort.addAction("Custom Sort...", self.custom_sort)
            m.addSeparator()
            ws = self.wb.ws
            m.addAction("Edit Comment" if ws.active in ws.comments else "Insert Comment", self.edit_comment)
            if ws.active in ws.comments:
                m.addAction("Delete Comment", self.delete_comment)
        m.addAction(self.a_format_cells)
        if kind == "rows":
            m.addAction("Row Height...", self.row_height)
            m.addAction("Hide", lambda: self.hide_rows(True))
            m.addAction("Unhide", lambda: self.hide_rows(False))
        elif kind == "cols":
            m.addAction("Column Width...", self.col_width)
            m.addAction("Hide", lambda: self.hide_cols(True))
            m.addAction("Unhide", lambda: self.hide_cols(False))
        else:
            m.addAction("Name a Range...", self.define_name)
            m.addAction(self.a_link)
        m.exec(pos)

    # ==== files ============================================================================================
    def _fill_recent(self):
        self.recent_menu.clear()
        files = [f for f in self.settings.value("recent", [], list) or [] if os.path.exists(f)]
        for i, f in enumerate(files[:9]):
            self.recent_menu.addAction(f"&{i + 1} {Path(f).name}", lambda f=f: self.open_maybe_new(f))
        self.recent_menu.setEnabled(bool(files))

    def _add_recent(self, path):
        files = [path] + [f for f in (self.settings.value("recent", [], list) or []) if f != path]
        self.settings.setValue("recent", files[:9])
        self._fill_recent()

    def maybe_save(self) -> bool:
        if self.grid.editing:
            self.grid.commit_edit()
        if not self.wb.modified:
            return True
        name = Path(self.wb.path).name if self.wb.path else self.untitled
        ans = QMessageBox.question(self, APP, f"Do you want to save the changes you made to '{name}'?",
                                   QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if ans == QMessageBox.Yes:
            return self.file_save()
        return ans == QMessageBox.No

    def is_blank(self) -> bool:
        return not self.wb.modified and self.wb.path is None and all(not ws.cells for ws in self.wb.sheets)

    def file_new(self):
        w = SheetWindow()
        w.show()

    def file_open(self):
        start = str(Path(self.wb.path).parent) if self.wb.path else str(Path.home() / "Documents")
        fn, _ = QFileDialog.getOpenFileName(self, "Open", start, OPEN_FILTER)
        if fn:
            self.open_maybe_new(fn)

    def open_maybe_new(self, path):
        if self.is_blank():
            self.open_path(path)
        else:
            w = SheetWindow(path)
            w.show()

    def open_path(self, path: str):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            wb = IO.open_any(path)
        except IO.OpenError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP, f"{APP} can't open {Path(path).name}.\n\n{e}")
            return
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP, f"{APP} can't open {Path(path).name}.\n\n{e}")
            return
        QApplication.restoreOverrideCursor()
        ext = Path(path).suffix.lower()
        if ext in (".xls", ".xlt", ".csv", ".txt", ".tsv", ".xltx", ".xltm"):
            # old or plain formats are saved as .xlsx (like Show does with .ppt)
            self.untitled = Path(path).stem
            wb.path = None
            if ext in (".xls", ".xlt"):
                self.statusBar().showMessage("Opened an Excel 97-2003 workbook. It is saved as .xlsx.", 8000)
        if ext in (".xlsm", ".xltm"):
            self.statusBar().showMessage("Macros in this file are not run, and are not kept when you save.", 8000)
        self.load_workbook(wb)
        self._add_recent(path)
        self._update_title()

    def file_save(self) -> bool:
        if self.wb.path is None or Path(self.wb.path).suffix.lower() not in (".xlsx", ".xlsm", ".csv", ".txt"):
            return self.file_save_as()
        return self.write_to(self.wb.path)

    def file_save_as(self, ext: str | None = None) -> bool:
        if self.grid.editing:
            self.grid.commit_edit()
        start_dir = Path(self.wb.path).parent if self.wb.path else Path.home() / "Documents"
        stem = Path(self.wb.path).stem if self.wb.path else self.untitled
        filters = ";;".join(label for label, _ in SAVE_TYPES)
        chosen = next((label for label, e in SAVE_TYPES if e == (ext or ".xlsx")), SAVE_TYPES[0][0])
        fn, flt = QFileDialog.getSaveFileName(self, "Save As", str(start_dir / (stem + (ext or ".xlsx"))), filters,
                                              chosen)
        if not fn:
            return False
        want = next((e for label, e in SAVE_TYPES if label == flt), ext or ".xlsx")
        if not Path(fn).suffix:
            fn += want
        if Path(fn).suffix.lower() == ".pdf":
            n = self._export_pdf(fn)
            self.statusBar().showMessage(f"Saved {n} page(s) as PDF: {fn}", 6000)
            return False
        if Path(fn).suffix.lower() in (".csv", ".txt") and len(self.wb.sheets) > 1:
            QMessageBox.information(self, APP, "The selected file type does not support workbooks that contain "
                                               "multiple sheets. Only the active sheet is saved.")
        return self.write_to(fn)

    def write_to(self, path) -> bool:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            IO.save_any(self.wb, path)
        except Exception as e:  # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP, f"The file could not be saved.\n\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        if Path(path).suffix.lower() in (".xlsx", ".xlsm"):
            self.wb.path = path
            self.wb.modified = False
        elif Path(path).suffix.lower() in (".csv", ".txt"):
            self.wb.path = path
            self.wb.modified = False
        self._add_recent(path)
        self._update_title()
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def _export_pdf(self, path, sheets=None):
        import sheet_print
        return sheet_print.export_pdf(self.wb, path, sheets)

    def file_print(self):
        import sheet_print
        printer = QPrinter(QPrinter.HighResolution)
        sheet_print.setup_printer(printer, self.wb.ws)
        dlg = QPrintDialog(printer, self)
        dlg.setOption(QPrintDialog.PrintSelection, True)
        if dlg.exec() != QDialog.Accepted:
            return
        sel = self.grid.selection_range() if dlg.printRange() == QPrintDialog.Selection else None
        sheet_print.render(self.wb, printer, [self.wb.ws], sel, self.wb.path or "")

    def file_preview(self):
        import sheet_print
        printer = QPrinter(QPrinter.HighResolution)
        sheet_print.setup_printer(printer, self.wb.ws)
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle("Print Preview")
        dlg.paintRequested.connect(lambda p: sheet_print.render(self.wb, p, [self.wb.ws], None, self.wb.path or ""))
        dlg.resize(900, 700)
        dlg.exec()

    def send_by_mail(self, ext):
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="classic7-sheet-")) / ((Path(self.wb.path).stem if self.wb.path
                                                                   else self.untitled) + ext)
        if ext == ".pdf":
            self._export_pdf(str(tmp))
        else:
            IO.save_any(self.wb, str(tmp))
        import subprocess
        try:
            subprocess.Popen(["classic7-mail", "--compose", "--attach", str(tmp)], start_new_session=True)
        except OSError:
            QMessageBox.warning(self, APP, f"Mail isn't available. The file was saved as:\n{tmp}")

    def closeEvent(self, ev):
        if not self.maybe_save():
            ev.ignore()
            return
        ev.accept()

    # drag and drop files
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.open_maybe_new(u.toLocalFile())


def _copy_name(wb, name):
    i = 2
    while wb.sheet(f"{name} ({i})"):
        i += 1
    return f"{name} ({i})"[:31]


def _key(k):
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    return QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("classic7-sheet")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-sheet")
    from PySide6.QtCore import QLocale
    loc = QLocale()
    NF.set_locale(loc.decimalPoint(), loc.groupSeparator())
    try:
        from write_model import FONT_SUBSTITUTES
        for fam, subs in FONT_SUBSTITUTES.items():
            QFont.insertSubstitutions(fam, subs)
    except ImportError:
        pass
    files = [a for a in argv if not a.startswith("-")]
    files = [QUrl(f).toLocalFile() if f.startswith("file://") else f for f in files]
    windows = []
    for f in files or [None]:
        w = SheetWindow(f)
        w.setAcceptDrops(True)
        w.show()
        windows.append(w)
    return app.exec()

