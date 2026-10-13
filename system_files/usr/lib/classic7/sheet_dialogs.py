"""Dialogs of Sheet, in the Excel 2007 layout: Format Cells, Insert Function, Sort, Find and
Replace, Go To, Page Setup, Insert/Delete, row height and column width, conditional
formatting rules, data validation, names, hyperlinks, Paste Special, chart type."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFontComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTabWidget, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

import sheet_formula as F
import sheet_numfmt as NF
from sheet_model import Border, Style
from sheet_ref import parse_cell, parse_range, range_name

CATEGORIES = [
    ("General", ["General"]),
    ("Number", ["0", "0.00", "#,##0", "#,##0.00", "-#,##0.00;[Red]-#,##0.00", "#,##0.00;[Red]-#,##0.00"]),
    ("Currency", ['#,##0.00 "kr."', '#,##0.00 "kr.";[Red]-#,##0.00 "kr."', '"$"#,##0.00', '[$€-x-euro2] #,##0.00',
                  '#,##0.00 [$€-x-euro1]', '[$£-809]#,##0.00']),
    ("Accounting", ['_-* #,##0.00 "kr."_-;-* #,##0.00 "kr."_-;_-* "-"?? "kr."_-;_-@_-',
                    '_("$"* #,##0.00_);_("$"* (#,##0.00);_("$"* "-"??_);_(@_)']),
    ("Date", ["dd-mm-yyyy", "d-m-yyyy", "d. mmmm yyyy", "dddd d. mmmm yyyy", "d-mmm-yy", "mmm-yy", "yyyy-mm-dd",
              "m/d/yyyy", "dd-mm-yyyy h:mm"]),
    ("Time", ["h:mm", "h:mm:ss", "h:mm AM/PM", "h:mm:ss AM/PM", "[h]:mm:ss", "mm:ss.0"]),
    ("Percentage", ["0%", "0.0%", "0.00%"]),
    ("Fraction", ["# ?/?", "# ??/??", "# ?/4", "# ?/8", "# ?/10", "# ?/100"]),
    ("Scientific", ["0.00E+00", "0.0E+00", "##0.0E+0"]),
    ("Text", ["@"]),
    ("Special", ["0000", "00000", "+45 00 00 00 00", "000-00-0000"]),
    ("Custom", []),
]

PALETTE = ["#ffffff", "#000000", "#eeece1", "#1f497d", "#4f81bd", "#c0504d", "#9bbb59", "#8064a2", "#4bacc6",
           "#f79646", "#f2f2f2", "#7f7f7f", "#ddd9c3", "#c6d9f0", "#dbe5f1", "#f2dcdb", "#ebf1dd", "#e5e0ec",
           "#dbeef3", "#fdeada", "#d8d8d8", "#595959", "#c4bd97", "#8db3e2", "#b8cce4", "#e5b9b7", "#d7e3bc",
           "#ccc1d9", "#b7dde8", "#fbd5b5", "#bfbfbf", "#3f3f3f", "#938953", "#548dd4", "#95b3d7", "#d99694",
           "#c3d69b", "#b2a2c7", "#92cddc", "#fac08f", "#a5a5a5", "#262626", "#494429", "#17365d", "#366092",
           "#953734", "#76923c", "#5f497a", "#31859b", "#e36c09", "#7f7f7f", "#0c0c0c", "#1d1b10", "#0f243e",
           "#244061", "#632423", "#4f6128", "#3f3151", "#205867", "#974806",
           "#c00000", "#ff0000", "#ffc000", "#ffff00", "#92d050", "#00b050", "#00b0f0", "#0070c0", "#002060",
           "#7030a0"]


def buttons(dlg, ok=True, cancel=True):
    flags = (QDialogButtonBox.Ok if ok else QDialogButtonBox.NoButton) | (QDialogButtonBox.Cancel if cancel else QDialogButtonBox.NoButton)
    bb = QDialogButtonBox(flags)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class ColorButton(QToolButton):
    """A colour well with Office 2007's palette."""
    changed = Signal(object)

    def __init__(self, color: str | None, none_text: str = "No Color"):
        super().__init__()
        self.color = color
        self.none_text = none_text
        self.setFixedSize(70, 22)
        self.setPopupMode(QToolButton.InstantPopup)
        from PySide6.QtWidgets import QMenu, QWidgetAction
        menu = QMenu(self)
        if none_text:
            menu.addAction(none_text, lambda: self.set(None))
        grid = QWidget()
        g = QGridLayout(grid)
        g.setSpacing(2)
        g.setContentsMargins(4, 4, 4, 4)
        for i, c in enumerate(PALETTE):
            b = QToolButton()
            b.setFixedSize(16, 16)
            b.setStyleSheet(f"QToolButton {{ background: {c}; border: 1px solid #a0a0a0; }}"
                            f"QToolButton:hover {{ border: 1px solid #f29436; }}")
            b.clicked.connect(lambda _=False, c=c: (self.set(c), menu.close()))
            g.addWidget(b, i // 10, i % 10)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(grid)
        menu.addAction(wa)
        menu.addAction("More Colors...", self._more)
        self.setMenu(menu)
        self._paint()

    def _more(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self.color or "#ffffff"), self)
        if c.isValid():
            self.set(c.name())

    def set(self, color):
        self.color = color
        self._paint()
        self.changed.emit(color)

    def _paint(self):
        self.setStyleSheet(f"QToolButton {{ background: {self.color or '#ffffff'}; border: 1px solid #808080; }}")
        self.setText("" if self.color else ("Automatic" if self.none_text == "Automatic" else ""))


# ---- Format Cells -------------------------------------------------------------------------------------
class FormatCellsDialog(QDialog):
    def __init__(self, style: Style, sample, parent=None, tab: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Format Cells")
        self.resize(560, 470)
        self.style0 = style
        self.sample = sample
        self.tabs = QTabWidget()
        self.tabs.addTab(self._number(), "Number")
        self.tabs.addTab(self._alignment(), "Alignment")
        self.tabs.addTab(self._font(), "Font")
        self.tabs.addTab(self._border(), "Border")
        self.tabs.addTab(self._fill(), "Fill")
        self.tabs.addTab(self._protection(), "Protection")
        self.tabs.setCurrentIndex(tab)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(buttons(self))

    # number
    def _number(self):
        w = QWidget()
        h = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(QLabel("Category:"))
        self.cat = QListWidget()
        self.cat.addItems([c for c, _ in CATEGORIES])
        self.cat.setFixedWidth(120)
        left.addWidget(self.cat)
        h.addLayout(left)
        right = QVBoxLayout()
        box = QGroupBox("Sample")
        bl = QVBoxLayout(box)
        self.sample_label = QLabel()
        bl.addWidget(self.sample_label)
        right.addWidget(box)
        self.decimals_row = QHBoxLayout()
        self.decimals_row.addWidget(QLabel("Decimal places:"))
        self.decimals = QSpinBox()
        self.decimals.setRange(0, 30)
        self.decimals.setValue(2)
        self.decimals_row.addWidget(self.decimals)
        self.thousands = QCheckBox("Use 1000 Separator (,)")
        self.decimals_row.addWidget(self.thousands)
        self.decimals_row.addStretch(1)
        right.addLayout(self.decimals_row)
        right.addWidget(QLabel("Type:"))
        self.code = QLineEdit(self.style0.numfmt)
        right.addWidget(self.code)
        self.codes = QListWidget()
        right.addWidget(self.codes, 1)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #555;")
        right.addWidget(self.hint)
        h.addLayout(right, 1)
        self.cat.currentRowChanged.connect(self._cat_changed)
        self.codes.currentTextChanged.connect(lambda t: t and self.code.setText(t))
        self.code.textChanged.connect(self._update_sample)
        self.decimals.valueChanged.connect(self._number_parts)
        self.thousands.toggled.connect(self._number_parts)
        # start on the category of the current format
        fmt = self.style0.numfmt
        start = 0 if fmt == "General" else len(CATEGORIES) - 1
        for i, (name, codes) in enumerate(CATEGORIES):
            if fmt in codes:
                start = i
                break
        else:
            if NF.is_date_format(fmt):
                start = 4
            elif fmt.endswith("%"):
                start = 6
        self.cat.setCurrentRow(start)
        self.code.setText(fmt)
        return w

    def _cat_changed(self, i):
        name, codes = CATEGORIES[i]
        self.codes.clear()
        if name == "Custom":
            allc = [c for _, cs in CATEGORIES for c in cs]
            self.codes.addItems(allc)
        else:
            self.codes.addItems(codes)
        numeric = name in ("Number", "Currency", "Percentage", "Scientific", "Accounting")
        for k in range(self.decimals_row.count()):
            it = self.decimals_row.itemAt(k).widget()
            if it:
                it.setVisible(numeric)
        self.thousands.setVisible(name == "Number")
        hints = {"General": "General format cells have no specific number format.",
                 "Number": "Number is used for general display of numbers.",
                 "Currency": "Currency formats are used for general monetary values.",
                 "Accounting": "Accounting formats line up the currency symbols and decimal points in a column.",
                 "Date": "Date formats display date and time serial numbers as date values.",
                 "Time": "Time formats display date and time serial numbers as time values.",
                 "Percentage": "Percentage formats multiply the cell value by 100 and display the result with a percent symbol.",
                 "Text": "Text format cells are treated as text even when a number is in the cell.",
                 "Custom": "Type the number format code, using one of the existing codes as a starting point."}
        self.hint.setText(hints.get(name, ""))
        if codes and self.code.text() not in codes and name != "Custom":
            self.codes.setCurrentRow(0)

    def _number_parts(self):
        name = CATEGORIES[self.cat.currentRow()][0]
        d = self.decimals.value()
        dec = ("." + "0" * d) if d else ""
        if name == "Number":
            self.code.setText(("#,##0" if self.thousands.isChecked() else "0") + dec)
        elif name == "Percentage":
            self.code.setText("0" + dec + "%")
        elif name == "Currency":
            self.code.setText(f'#,##0{dec} "kr."')
        elif name == "Scientific":
            self.code.setText(f"0{dec}E+00")

    def _update_sample(self):
        v = self.sample if self.sample is not None else 1234.5678
        text, color = NF.format_value(v, self.code.text() or "General")
        self.sample_label.setText(text)
        self.sample_label.setStyleSheet(f"color: {color or '#000000'};")

    # alignment
    def _alignment(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        box = QGroupBox("Text alignment")
        f = QFormLayout(box)
        self.halign = QComboBox()
        for key, label in (("general", "General"), ("left", "Left (Indent)"), ("center", "Center"),
                           ("right", "Right (Indent)"), ("fill", "Fill"), ("justify", "Justify"),
                           ("centerContinuous", "Center Across Selection")):
            self.halign.addItem(label, key)
        self.halign.setCurrentIndex(max(0, self.halign.findData(self.style0.halign)))
        self.valign = QComboBox()
        for key, label in (("top", "Top"), ("center", "Center"), ("bottom", "Bottom")):
            self.valign.addItem(label, key)
        self.valign.setCurrentIndex(max(0, self.valign.findData(self.style0.valign)))
        self.indent = QSpinBox()
        self.indent.setRange(0, 15)
        self.indent.setValue(self.style0.indent)
        f.addRow("Horizontal:", self.halign)
        f.addRow("Indent:", self.indent)
        f.addRow("Vertical:", self.valign)
        lay.addWidget(box)
        box2 = QGroupBox("Text control")
        v = QVBoxLayout(box2)
        self.wrap = QCheckBox("Wrap text")
        self.wrap.setChecked(self.style0.wrap)
        self.shrink = QCheckBox("Shrink to fit")
        self.shrink.setChecked(self.style0.shrink)
        self.merge = QCheckBox("Merge cells")
        v.addWidget(self.wrap)
        v.addWidget(self.shrink)
        v.addWidget(self.merge)
        lay.addWidget(box2)
        box3 = QGroupBox("Orientation")
        o = QHBoxLayout(box3)
        o.addWidget(QLabel("Degrees:"))
        self.rotation = QSpinBox()
        self.rotation.setRange(-90, 90)
        rot = self.style0.rotation
        self.rotation.setValue(rot if rot <= 90 else -(rot - 90))
        o.addWidget(self.rotation)
        o.addStretch(1)
        lay.addWidget(box3)
        lay.addStretch(1)
        return w

    # font
    def _font(self):
        w = QWidget()
        g = QGridLayout(w)
        st = self.style0
        g.addWidget(QLabel("Font:"), 0, 0)
        self.font_box = QFontComboBox()
        self.font_box.setCurrentFont(QFont(st.font))
        g.addWidget(self.font_box, 1, 0)
        g.addWidget(QLabel("Font style:"), 0, 1)
        self.font_style = QComboBox()
        self.font_style.addItems(["Regular", "Italic", "Bold", "Bold Italic"])
        self.font_style.setCurrentIndex((2 if st.bold else 0) + (1 if st.italic else 0))
        g.addWidget(self.font_style, 1, 1)
        g.addWidget(QLabel("Size:"), 0, 2)
        self.size = QDoubleSpinBox()
        self.size.setRange(1, 409)
        self.size.setDecimals(1)
        self.size.setValue(st.size)
        g.addWidget(self.size, 1, 2)
        g.addWidget(QLabel("Underline:"), 2, 0)
        self.underline = QComboBox()
        self.underline.addItems(["None", "Single"])
        self.underline.setCurrentIndex(1 if st.underline else 0)
        g.addWidget(self.underline, 3, 0)
        g.addWidget(QLabel("Color:"), 2, 1)
        self.font_color = ColorButton(st.color, "Automatic")
        g.addWidget(self.font_color, 3, 1)
        box = QGroupBox("Effects")
        b = QVBoxLayout(box)
        self.strike = QCheckBox("Strikethrough")
        self.strike.setChecked(st.strike)
        b.addWidget(self.strike)
        g.addWidget(box, 4, 0)
        prev = QGroupBox("Preview")
        p = QVBoxLayout(prev)
        self.font_preview = QLabel("AaBbCcYyZz")
        self.font_preview.setAlignment(Qt.AlignCenter)
        self.font_preview.setMinimumHeight(60)
        p.addWidget(self.font_preview)
        g.addWidget(prev, 4, 1, 1, 2)
        g.setRowStretch(5, 1)
        for sig in (self.font_box.currentFontChanged, self.font_style.currentIndexChanged, self.size.valueChanged,
                    self.underline.currentIndexChanged, self.strike.toggled, self.font_color.changed):
            sig.connect(self._font_preview)
        self._font_preview()
        return w

    def _font_preview(self, *_):
        f = QFont(self.font_box.currentFont().family())
        f.setPointSizeF(min(self.size.value(), 28))
        f.setBold(self.font_style.currentIndex() >= 2)
        f.setItalic(self.font_style.currentIndex() in (1, 3))
        f.setUnderline(self.underline.currentIndex() == 1)
        f.setStrikeOut(self.strike.isChecked())
        self.font_preview.setFont(f)
        self.font_preview.setStyleSheet(f"color: {self.font_color.color or '#000000'};")

    # border
    def _border(self):
        w = QWidget()
        lay = QHBoxLayout(w)
        left = QVBoxLayout()
        box = QGroupBox("Line")
        b = QVBoxLayout(box)
        self.line_style = QListWidget()
        for key, label in (("thin", "Thin"), ("medium", "Medium"), ("thick", "Thick"), ("dashed", "Dashed"),
                           ("dotted", "Dotted"), ("double", "Double"), ("hair", "Hair")):
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, key)
            self.line_style.addItem(it)
        self.line_style.setCurrentRow(0)
        b.addWidget(self.line_style)
        b.addWidget(QLabel("Color:"))
        self.line_color = ColorButton("#000000", "Automatic")
        b.addWidget(self.line_color)
        left.addWidget(box)
        lay.addLayout(left)
        right = QVBoxLayout()
        presets = QGroupBox("Presets")
        pr = QHBoxLayout(presets)
        self.border_state = {s: getattr(self.style0, s) for s in ("left", "right", "top", "bottom")}
        self.outline_inside = None
        for text, kind in (("None", "none"), ("Outline", "outline"), ("Inside", "inside")):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, k=kind: self._border_preset(k))
            pr.addWidget(btn)
        right.addWidget(presets)
        sides = QGroupBox("Border")
        sl = QGridLayout(sides)
        self.side_buttons = {}
        for i, side in enumerate(("top", "bottom", "left", "right")):
            btn = QPushButton(side.title())
            btn.setCheckable(True)
            btn.setChecked(bool(self.border_state[side].style))
            btn.toggled.connect(lambda on, s=side: self._side(s, on))
            sl.addWidget(btn, i // 2, i % 2)
            self.side_buttons[side] = btn
        right.addWidget(sides)
        note = QLabel("Click a preset or the side buttons to apply borders. Outline and Inside apply to the "
                      "whole selection.")
        note.setWordWrap(True)
        right.addWidget(note)
        right.addStretch(1)
        lay.addLayout(right, 1)
        return w

    def _current_border(self) -> Border:
        return Border(self.line_style.currentItem().data(Qt.UserRole), self.line_color.color or "#000000")

    def _side(self, side, on):
        self.border_state[side] = self._current_border() if on else Border()

    def _border_preset(self, kind):
        self.outline_inside = kind
        for side, btn in self.side_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(kind != "none")
            btn.blockSignals(False)
            self.border_state[side] = self._current_border() if kind != "none" else Border()

    # fill
    def _fill(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Background Color:"))
        self.fill_color = ColorButton(self.style0.fill, "No Color")
        self.fill_color.setFixedSize(120, 26)
        lay.addWidget(self.fill_color)
        lay.addStretch(1)
        return w

    def _protection(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.locked = QCheckBox("Locked")
        self.locked.setChecked(self.style0.locked)
        lay.addWidget(self.locked)
        lab = QLabel("Locking cells has no effect until you protect the worksheet (Review tab, Protect Sheet).")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        lay.addStretch(1)
        return w

    def changes(self) -> dict:
        """The style properties the user changed (only those are applied to every cell)."""
        st = self.style0
        new = {
            "numfmt": self.code.text() or "General",
            "halign": self.halign.currentData(), "valign": self.valign.currentData(),
            "indent": self.indent.value(), "wrap": self.wrap.isChecked(), "shrink": self.shrink.isChecked(),
            "rotation": self.rotation.value() if self.rotation.value() >= 0 else 90 - self.rotation.value(),
            "font": self.font_box.currentFont().family(), "size": self.size.value(),
            "bold": self.font_style.currentIndex() >= 2, "italic": self.font_style.currentIndex() in (1, 3),
            "underline": self.underline.currentIndex() == 1, "strike": self.strike.isChecked(),
            "color": self.font_color.color or "#000000", "fill": self.fill_color.color,
            "locked": self.locked.isChecked(),
        }
        out = {k: v for k, v in new.items() if getattr(st, k) != v}
        if self.outline_inside is None:
            for side in ("left", "right", "top", "bottom"):
                if self.border_state[side] != getattr(st, side):
                    out[side] = self.border_state[side]
        return out


# ---- Insert Function --------------------------------------------------------------------------------
class InsertFunctionDialog(QDialog):
    def __init__(self, parent=None, category: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Insert Function")
        self.resize(460, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Search for a function:"))
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a brief description of what you want to do and then click Go")
        go = QPushButton("Go")
        row.addWidget(self.search, 1)
        row.addWidget(go)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Or select a category:"))
        self.cat = QComboBox()
        self.cat.addItems(["Most Recently Used", "All"] + sorted(F.CATEGORIES))
        row2.addWidget(self.cat, 1)
        lay.addLayout(row2)
        lay.addWidget(QLabel("Select a function:"))
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setMinimumHeight(48)
        lay.addWidget(self.desc)
        lay.addWidget(buttons(self))
        self.cat.currentTextChanged.connect(self._fill)
        go.clicked.connect(self._search)
        self.search.returnPressed.connect(self._search)
        self.list.currentTextChanged.connect(lambda n: self.desc.setText(F.describe(n) or f"{n}(...)"))
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        self.cat.setCurrentText(category or "Most Recently Used")
        self._fill(self.cat.currentText())

    RECENT = ["SUM", "AVERAGE", "IF", "COUNT", "MAX", "MIN", "VLOOKUP", "SUMIF", "ROUND", "TODAY"]

    def _fill(self, cat):
        self.list.clear()
        if cat == "Most Recently Used":
            names = self.RECENT
        elif cat == "All":
            names = F.all_function_names()
        else:
            names = sorted(set(F.CATEGORIES.get(cat, [])))
        self.list.addItems(names)
        if names:
            self.list.setCurrentRow(0)

    def _search(self):
        words = self.search.text().lower().split()
        names = [n for n in F.all_function_names()
                 if all(w in (n.lower() + " " + F.describe(n).lower()) for w in words)]
        self.list.clear()
        self.list.addItems(names)
        if names:
            self.list.setCurrentRow(0)

    def function(self) -> str | None:
        it = self.list.currentItem()
        return it.text() if it else None


# ---- Sort ----------------------------------------------------------------------------------------
class SortDialog(QDialog):
    def __init__(self, columns: list[tuple[int, str]], header: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sort")
        self.columns = columns
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        add = QPushButton("Add Level")
        delete = QPushButton("Delete Level")
        top.addWidget(add)
        top.addWidget(delete)
        top.addStretch(1)
        self.header = QCheckBox("My data has headers")
        self.header.setChecked(header)
        top.addWidget(self.header)
        lay.addLayout(top)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Column", "Sort On", "Order"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        lay.addWidget(buttons(self))
        add.clicked.connect(self.add_level)
        delete.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()) if self.table.rowCount() > 1 else None)
        self.add_level()
        self.resize(520, 260)

    def add_level(self):
        r = self.table.rowCount()
        self.table.insertRow(r)
        col = QComboBox()
        for idx, name in self.columns:
            col.addItem(name, idx)
        col.setCurrentIndex(min(r, col.count() - 1))
        self.table.setCellWidget(r, 0, col)
        on = QComboBox()
        on.addItem("Values")
        self.table.setCellWidget(r, 1, on)
        order = QComboBox()
        order.addItems(["A to Z / Smallest to Largest", "Z to A / Largest to Smallest"])
        self.table.setCellWidget(r, 2, order)

    def keys(self) -> list[tuple[int, bool]]:
        out = []
        for r in range(self.table.rowCount()):
            out.append((self.table.cellWidget(r, 0).currentData(), self.table.cellWidget(r, 2).currentIndex() == 0))
        return out


# ---- Find and Replace -------------------------------------------------------------------------------
class FindDialog(QDialog):
    find_next = Signal(str, dict)
    replace_one = Signal(str, str, dict)
    replace_all = Signal(str, str, dict)
    find_all = Signal(str, dict)

    def __init__(self, parent=None, replace_tab=False):
        super().__init__(parent)
        self.setWindowTitle("Find and Replace")
        self.setModal(False)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "Find")
        self.tabs.addTab(QWidget(), "Replace")
        lay.addWidget(self.tabs)
        form = QFormLayout()
        self.what = QLineEdit()
        self.with_ = QLineEdit()
        form.addRow("Find what:", self.what)
        self.with_label = QLabel("Replace with:")
        form.addRow(self.with_label, self.with_)
        lay.addLayout(form)
        opts = QHBoxLayout()
        self.within = QComboBox()
        self.within.addItems(["Sheet", "Workbook"])
        self.look_in = QComboBox()
        self.look_in.addItems(["Formulas", "Values"])
        self.case = QCheckBox("Match case")
        self.whole = QCheckBox("Match entire cell contents")
        opts.addWidget(QLabel("Within:"))
        opts.addWidget(self.within)
        opts.addWidget(QLabel("Look in:"))
        opts.addWidget(self.look_in)
        lay.addLayout(opts)
        opts2 = QHBoxLayout()
        opts2.addWidget(self.case)
        opts2.addWidget(self.whole)
        opts2.addStretch(1)
        lay.addLayout(opts2)
        row = QHBoxLayout()
        self.b_replace_all = QPushButton("Replace All")
        self.b_replace = QPushButton("Replace")
        b_all = QPushButton("Find All")
        b_next = QPushButton("Find Next")
        b_close = QPushButton("Close")
        for b in (self.b_replace_all, self.b_replace, b_all, b_next, b_close):
            row.addWidget(b)
        lay.addLayout(row)
        self.results = QListWidget()
        self.results.setVisible(False)
        lay.addWidget(self.results)
        b_next.setDefault(True)
        b_next.clicked.connect(lambda: self.find_next.emit(self.what.text(), self.options()))
        b_all.clicked.connect(lambda: self.find_all.emit(self.what.text(), self.options()))
        self.b_replace.clicked.connect(lambda: self.replace_one.emit(self.what.text(), self.with_.text(), self.options()))
        self.b_replace_all.clicked.connect(lambda: self.replace_all.emit(self.what.text(), self.with_.text(), self.options()))
        b_close.clicked.connect(self.close)
        self.tabs.currentChanged.connect(self._mode)
        self.tabs.setCurrentIndex(1 if replace_tab else 0)
        self._mode(self.tabs.currentIndex())

    def _mode(self, i):
        rep = i == 1
        for w in (self.with_, self.with_label, self.b_replace, self.b_replace_all):
            w.setVisible(rep)

    def options(self) -> dict:
        return {"case": self.case.isChecked(), "whole": self.whole.isChecked(),
                "workbook": self.within.currentIndex() == 1, "formulas": self.look_in.currentIndex() == 0}


class GoToDialog(QDialog):
    def __init__(self, names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go To")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Go to:"))
        self.list = QListWidget()
        self.list.addItems(names)
        lay.addWidget(self.list)
        lay.addWidget(QLabel("Reference:"))
        self.ref = QLineEdit()
        lay.addWidget(self.ref)
        self.list.currentTextChanged.connect(self.ref.setText)
        self.list.itemDoubleClicked.connect(lambda _: self.accept())
        lay.addWidget(buttons(self))


# ---- small dialogs ---------------------------------------------------------------------------------
class NumberDialog(QDialog):
    def __init__(self, title: str, label: str, value: float, lo: float, hi: float, decimals=2, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        f = QFormLayout(self)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(lo, hi)
        self.spin.setDecimals(decimals)
        self.spin.setValue(value)
        f.addRow(label, self.spin)
        f.addRow(buttons(self))

    def value(self):
        return self.spin.value()


class InsertDeleteDialog(QDialog):
    def __init__(self, delete=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Delete" if delete else "Insert")
        lay = QVBoxLayout(self)
        box = QGroupBox("Delete" if delete else "Insert")
        b = QVBoxLayout(box)
        self.choice = QButtonGroup(self)
        opts = (("Shift cells left", "left"), ("Shift cells up", "up"), ("Entire row", "row"), ("Entire column", "col")) \
            if delete else (("Shift cells right", "right"), ("Shift cells down", "down"), ("Entire row", "row"),
                            ("Entire column", "col"))
        for i, (text, key) in enumerate(opts):
            rb = QRadioButton(text)
            rb.setProperty("key", key)
            if i == 1:
                rb.setChecked(True)
            self.choice.addButton(rb)
            b.addWidget(rb)
        lay.addWidget(box)
        lay.addWidget(buttons(self))

    def key(self) -> str:
        return self.choice.checkedButton().property("key")


class PasteSpecialDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste Special")
        lay = QVBoxLayout(self)
        box = QGroupBox("Paste")
        b = QGridLayout(box)
        self.choice = QButtonGroup(self)
        for i, (text, key) in enumerate((("All", "all"), ("Formulas", "formulas"), ("Values", "values"),
                                         ("Formats", "formats"))):
            rb = QRadioButton(text)
            rb.setProperty("key", key)
            rb.setChecked(i == 0)
            self.choice.addButton(rb)
            b.addWidget(rb, i % 4, i // 4)
        lay.addWidget(box)
        self.skip = QCheckBox("Skip blanks")
        self.transpose = QCheckBox("Transpose")
        row = QHBoxLayout()
        row.addWidget(self.skip)
        row.addWidget(self.transpose)
        lay.addLayout(row)
        lay.addWidget(buttons(self))

    def key(self) -> str:
        return self.choice.checkedButton().property("key")


class HyperlinkDialog(QDialog):
    def __init__(self, text: str, url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Hyperlink")
        f = QFormLayout(self)
        self.text = QLineEdit(text)
        self.url = QLineEdit(url)
        self.url.setPlaceholderText("https://... or a file")
        f.addRow("Text to display:", self.text)
        f.addRow("Address:", self.url)
        f.addRow(buttons(self))


class CommentDialog(QDialog):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comment")
        lay = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setMinimumSize(300, 120)
        lay.addWidget(self.edit)
        lay.addWidget(buttons(self))


class DefineNameDialog(QDialog):
    def __init__(self, ref: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Name")
        f = QFormLayout(self)
        self.name = QLineEdit()
        self.ref = QLineEdit(ref)
        f.addRow("Name:", self.name)
        f.addRow("Refers to:", self.ref)
        f.addRow(buttons(self))


class NameManagerDialog(QDialog):
    def __init__(self, wb, parent=None):
        super().__init__(parent)
        self.wb = wb
        self.setWindowTitle("Name Manager")
        self.resize(520, 300)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        new = QPushButton("New...")
        delete = QPushButton("Delete")
        row.addWidget(new)
        row.addWidget(delete)
        row.addStretch(1)
        lay.addLayout(row)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Value", "Refers To"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        lay.addWidget(self.table)
        lay.addWidget(buttons(self, ok=False, cancel=True))
        new.clicked.connect(self._new)
        delete.clicked.connect(self._delete)
        self._fill()

    def _fill(self):
        self.table.setRowCount(0)
        for name, text in sorted(self.wb.names.items()):
            r = self.table.rowCount()
            self.table.insertRow(r)
            v = "?"
            try:
                tree = F.parse(text)
                res = F.evaluate(tree, F.Context(self.wb, self.wb.ws.name, 0, 0))
                v = ", ".join(F.to_text(x) for x in list(res)[:5]) if isinstance(res, (F.Range, F.Array)) else F.to_text(res)
            except Exception:  # noqa: BLE001
                pass
            for c, t in enumerate((name, str(v), text)):
                self.table.setItem(r, c, QTableWidgetItem(t))

    def _new(self):
        dlg = DefineNameDialog("=" + self.wb.ws.name + "!$A$1", self)
        if dlg.exec() == QDialog.Accepted and dlg.name.text().strip():
            name = dlg.name.text().strip()
            if not name.replace("_", "").replace(".", "").isalnum() or parse_cell(name):
                QMessageBox.warning(self, "Name Manager", "The name that you entered is not valid.")
                return
            self.wb.structural("Define Name", lambda: self.wb.names.__setitem__(name, dlg.ref.text()))
            self._fill()

    def _delete(self):
        r = self.table.currentRow()
        if r < 0:
            return
        name = self.table.item(r, 0).text()
        self.wb.structural("Delete Name", lambda: self.wb.names.pop(name, None))
        self._fill()


class PageSetupDialog(QDialog):
    def __init__(self, page, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Page Setup")
        self.page = page
        tabs = QTabWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        # page
        w = QWidget()
        f = QFormLayout(w)
        self.portrait = QRadioButton("Portrait")
        self.landscape = QRadioButton("Landscape")
        (self.landscape if page.orientation == "landscape" else self.portrait).setChecked(True)
        o = QHBoxLayout()
        o.addWidget(self.portrait)
        o.addWidget(self.landscape)
        o.addStretch(1)
        f.addRow("Orientation:", o)
        self.adjust = QRadioButton("Adjust to:")
        self.scale = QSpinBox()
        self.scale.setRange(10, 400)
        self.scale.setSuffix(" % normal size")
        self.scale.setValue(page.scale)
        self.fit = QRadioButton("Fit to:")
        self.fit_w = QSpinBox()
        self.fit_w.setRange(0, 100)
        self.fit_w.setValue(page.fit_width or 1)
        self.fit_h = QSpinBox()
        self.fit_h.setRange(0, 100)
        self.fit_h.setValue(page.fit_height or 0)
        (self.fit if (page.fit_width or page.fit_height) else self.adjust).setChecked(True)
        a = QHBoxLayout()
        a.addWidget(self.adjust)
        a.addWidget(self.scale)
        a.addStretch(1)
        f.addRow("Scaling:", a)
        b = QHBoxLayout()
        b.addWidget(self.fit)
        b.addWidget(self.fit_w)
        b.addWidget(QLabel("page(s) wide by"))
        b.addWidget(self.fit_h)
        b.addWidget(QLabel("tall (0 = automatic)"))
        f.addRow("", b)
        self.paper = QComboBox()
        self.paper.addItems(["A4", "A3", "A5", "Letter", "Legal"])
        self.paper.setCurrentText(page.paper)
        f.addRow("Paper size:", self.paper)
        tabs.addTab(w, "Page")
        # margins
        w2 = QWidget()
        f2 = QFormLayout(w2)
        self.margins = []
        for label, v in zip(("Left:", "Right:", "Top:", "Bottom:"), page.margins):
            s = QDoubleSpinBox()
            s.setRange(0, 10)
            s.setSuffix(" cm")
            s.setDecimals(1)
            s.setValue(v * 2.54)
            self.margins.append(s)
            f2.addRow(label, s)
        self.center_h = QCheckBox("Horizontally")
        self.center_h.setChecked(page.center_h)
        self.center_v = QCheckBox("Vertically")
        self.center_v.setChecked(page.center_v)
        c = QHBoxLayout()
        c.addWidget(self.center_h)
        c.addWidget(self.center_v)
        f2.addRow("Center on page:", c)
        tabs.addTab(w2, "Margins")
        # header/footer
        w3 = QWidget()
        f3 = QFormLayout(w3)
        self.header = QComboBox()
        self.header.setEditable(True)
        self.header.addItems(["", "&A", "&F", "Page &P", "Page &P of &N", "&D"])
        self.header.setCurrentText(page.header)
        self.footer = QComboBox()
        self.footer.setEditable(True)
        self.footer.addItems(["", "Page &P", "Page &P of &N", "&A", "&F", "&D"])
        self.footer.setCurrentText(page.footer)
        f3.addRow("Header:", self.header)
        f3.addRow("Footer:", self.footer)
        hint = QLabel("&P page number, &N number of pages, &A sheet name, &F file name, &D date")
        hint.setStyleSheet("color: #555;")
        f3.addRow(hint)
        tabs.addTab(w3, "Header/Footer")
        # sheet
        w4 = QWidget()
        f4 = QFormLayout(w4)
        self.area = QLineEdit(range_name(*page.print_area) if page.print_area else "")
        self.title_rows = QLineEdit(f"${page.title_rows[0] + 1}:${page.title_rows[1] + 1}" if page.title_rows else "")
        f4.addRow("Print area:", self.area)
        f4.addRow("Rows to repeat at top:", self.title_rows)
        self.gridlines = QCheckBox("Gridlines")
        self.gridlines.setChecked(page.gridlines)
        self.headings = QCheckBox("Row and column headings")
        self.headings.setChecked(page.headings)
        f4.addRow(self.gridlines)
        f4.addRow(self.headings)
        tabs.addTab(w4, "Sheet")
        lay.addWidget(buttons(self))

    def apply(self, page):
        page.orientation = "landscape" if self.landscape.isChecked() else "portrait"
        page.scale = self.scale.value()
        if self.fit.isChecked():
            page.fit_width, page.fit_height = self.fit_w.value(), self.fit_h.value()
        else:
            page.fit_width = page.fit_height = 0
        page.paper = self.paper.currentText()
        page.margins = tuple(s.value() / 2.54 for s in self.margins)
        page.center_h, page.center_v = self.center_h.isChecked(), self.center_v.isChecked()
        page.header, page.footer = self.header.currentText(), self.footer.currentText()
        page.print_area = parse_range(self.area.text()) if self.area.text().strip() else None
        t = self.title_rows.text().replace("$", "").strip()
        if t and ":" in t and all(x.isdigit() for x in t.split(":")):
            a, b = t.split(":")
            page.title_rows = (int(a) - 1, int(b) - 1)
        elif not t:
            page.title_rows = None
        page.gridlines, page.headings = self.gridlines.isChecked(), self.headings.isChecked()


class CondRuleDialog(QDialog):
    """Highlight Cells Rules / Top-Bottom: one simple rule with a preset format."""
    PRESETS = [("Light Red Fill with Dark Red Text", "#ffc7ce", "#9c0006"),
               ("Yellow Fill with Dark Yellow Text", "#ffeb9c", "#9c6500"),
               ("Green Fill with Dark Green Text", "#c6efce", "#006100"),
               ("Light Red Fill", "#ffc7ce", None), ("Red Text", None, "#ff0000"), ("Red Border", None, "#ff0000")]

    def __init__(self, title: str, prompt: str, two_values=False, value_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(prompt))
        row = QHBoxLayout()
        self.v1 = QLineEdit(value_text)
        row.addWidget(self.v1)
        self.v2 = None
        if two_values:
            row.addWidget(QLabel("and"))
            self.v2 = QLineEdit()
            row.addWidget(self.v2)
        row.addWidget(QLabel("with"))
        self.preset = QComboBox()
        for name, _, _ in self.PRESETS:
            self.preset.addItem(name)
        row.addWidget(self.preset)
        lay.addLayout(row)
        lay.addWidget(buttons(self))

    def style(self):
        _, fill, color = self.PRESETS[self.preset.currentIndex()]
        return fill, color


class ValidationDialog(QDialog):
    def __init__(self, v, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data Validation")
        f = QFormLayout(self)
        self.kind = QComboBox()
        for key, label in (("any", "Any value"), ("whole", "Whole number"), ("decimal", "Decimal"), ("list", "List"),
                           ("date", "Date"), ("textLength", "Text length")):
            self.kind.addItem(label, key)
        self.kind.setCurrentIndex(max(0, self.kind.findData(v.kind if v else "any")))
        self.op = QComboBox()
        for key, label in (("between", "between"), ("notBetween", "not between"), ("equal", "equal to"),
                           ("notEqual", "not equal to"), ("greaterThan", "greater than"), ("lessThan", "less than"),
                           ("greaterThanOrEqual", "greater than or equal to"),
                           ("lessThanOrEqual", "less than or equal to")):
            self.op.addItem(label, key)
        self.op.setCurrentIndex(max(0, self.op.findData(v.operator if v else "between")))
        self.f1 = QLineEdit(v.formula1 if v else "")
        self.f2 = QLineEdit(v.formula2 if v else "")
        self.f1.setPlaceholderText('List: "Yes,No,Maybe" or =$A$1:$A$5')
        self.error = QLineEdit(v.error if v else "")
        f.addRow("Allow:", self.kind)
        f.addRow("Data:", self.op)
        f.addRow("Source / Minimum:", self.f1)
        f.addRow("Maximum:", self.f2)
        f.addRow("Error message:", self.error)
        self.clear = QPushButton("Clear All")
        f.addRow(self.clear)
        self.cleared = False
        self.clear.clicked.connect(lambda: (setattr(self, "cleared", True), self.accept()))
        f.addRow(buttons(self))


class ChartTypeDialog(QDialog):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        import sheet_chart
        self.setWindowTitle("Change Chart Type")
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        for key, name in sheet_chart.KIND_NAMES:
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, key)
            self.list.addItem(it)
            if key == kind:
                self.list.setCurrentItem(it)
        lay.addWidget(self.list)
        self.stacked = QComboBox()
        self.stacked.addItems(["Clustered / Standard", "Stacked", "100% Stacked"])
        lay.addWidget(self.stacked)
        lay.addWidget(buttons(self))

    def kind(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else "col"

    def grouping(self, kind):
        i = self.stacked.currentIndex()
        if i == 1:
            return "stacked"
        if i == 2:
            return "percentStacked"
        return "clustered" if kind in ("col", "bar") else "standard"


class ChartOptionsDialog(QDialog):
    def __init__(self, chart, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Chart Layout")
        f = QFormLayout(self)
        self.title = QLineEdit(chart.title)
        self.legend = QComboBox()
        for key, label in (("r", "Right"), ("b", "Bottom"), ("t", "Top"), ("l", "Left"), ("", "None")):
            self.legend.addItem(label, key)
        self.legend.setCurrentIndex(max(0, self.legend.findData(chart.legend)))
        self.x = QLineEdit(chart.x_title)
        self.y = QLineEdit(chart.y_title)
        f.addRow("Chart title:", self.title)
        f.addRow("Legend:", self.legend)
        f.addRow("Horizontal axis title:", self.x)
        f.addRow("Vertical axis title:", self.y)
        self.series = QTableWidget(len(chart.series), 3)
        self.series.setHorizontalHeaderLabels(["Name", "Values", "Categories / X"])
        for i, s in enumerate(chart.series):
            for c, t in enumerate((s.name, s.values, s.categories)):
                self.series.setItem(i, c, QTableWidgetItem(t))
        self.series.horizontalHeader().setStretchLastSection(True)
        f.addRow(QLabel("Data series:"))
        f.addRow(self.series)
        f.addRow(buttons(self))
        self.resize(560, 380)

    def apply(self, chart):
        chart.title = self.title.text()
        chart.legend = self.legend.currentData()
        chart.x_title, chart.y_title = self.x.text(), self.y.text()
        for i, s in enumerate(chart.series):
            s.name = self.series.item(i, 0).text() if self.series.item(i, 0) else ""
            s.values = self.series.item(i, 1).text() if self.series.item(i, 1) else ""
            s.categories = self.series.item(i, 2).text() if self.series.item(i, 2) else ""


def frame_line() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line

