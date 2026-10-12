"""Show: dialogs (Page Setup, Header and Footer, Set Up Show, Print, Format Background, ...)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QRadioButton, QSlider, QSpinBox, QToolButton, QVBoxLayout)

import show_model as sm
import show_widgets as sw


def metric() -> bool:
    return QLocale().measurementSystem() == QLocale.MetricSystem


def unit_name() -> str:
    return "cm" if metric() else '"'


def emu_to_unit(v: int) -> float:
    return v / 360000.0 if metric() else v / 914400.0


def unit_to_emu(v: float) -> int:
    return int(round(v * 360000)) if metric() else int(round(v * 914400))


def unit_spin(value_emu: int, maximum: float = 142.0) -> QDoubleSpinBox:
    sp = QDoubleSpinBox()
    sp.setDecimals(2)
    sp.setRange(0.01, maximum if metric() else maximum / 2.54)
    sp.setSingleStep(0.1 if metric() else 0.05)
    sp.setSuffix(" " + unit_name())
    sp.setValue(emu_to_unit(value_emu))
    return sp


def _buttons(dlg, ok_text="OK"):
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.button(QDialogButtonBox.Ok).setText(ok_text)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    return bb


class PageSetupDialog(QDialog):
    def __init__(self, pres: sm.Presentation, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Page Setup")
        lay = QHBoxLayout(self)
        left = QFormLayout()
        self.combo = QComboBox()
        for name in sm.SLIDE_SIZES:
            self.combo.addItem(name)
        self.combo.addItem("Custom")
        self.w = unit_spin(pres.width)
        self.h = unit_spin(pres.height)
        cur = next((n for n, (w, h) in sm.SLIDE_SIZES.items() if (w, h) == (pres.width, pres.height)
                    or (h, w) == (pres.width, pres.height)), "Custom")
        self.combo.setCurrentText(cur)
        self.combo.currentTextChanged.connect(self._preset)
        left.addRow("Slides sized for:", self.combo)
        left.addRow("Width:", self.w)
        left.addRow("Height:", self.h)
        lay.addLayout(left)
        box = QGroupBox("Orientation")
        v = QVBoxLayout(box)
        self.portrait = QRadioButton("Portrait")
        self.landscape = QRadioButton("Landscape")
        (self.portrait if pres.height > pres.width else self.landscape).setChecked(True)
        v.addWidget(QLabel("Slides"))
        v.addWidget(self.portrait)
        v.addWidget(self.landscape)
        self.portrait.toggled.connect(self._orient)
        right = QVBoxLayout()
        right.addWidget(box)
        right.addStretch(1)
        right.addWidget(_buttons(self))
        lay.addLayout(right)

    def _preset(self, name):
        if name in sm.SLIDE_SIZES:
            w, h = sm.SLIDE_SIZES[name]
            if self.portrait.isChecked():
                w, h = h, w
            self.w.setValue(emu_to_unit(w))
            self.h.setValue(emu_to_unit(h))

    def _orient(self, portrait):
        w, h = self.w.value(), self.h.value()
        if (portrait and w > h) or (not portrait and h > w):
            self.w.setValue(h)
            self.h.setValue(w)

    def size(self) -> tuple[int, int]:
        return unit_to_emu(self.w.value()), unit_to_emu(self.h.value())


class HeaderFooterDialog(QDialog):
    def __init__(self, pres: sm.Presentation, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Header and Footer")
        f = pres.footer
        lay = QVBoxLayout(self)
        box = QGroupBox("Include on slide")
        v = QVBoxLayout(box)
        self.date = QCheckBox("Date and time")
        self.date.setChecked(f.get("date", False))
        v.addWidget(self.date)
        self.auto = QRadioButton("Update automatically")
        self.fixed = QRadioButton("Fixed")
        self.auto.setChecked(f.get("date_auto", True))
        self.fixed.setChecked(not f.get("date_auto", True))
        self.auto_fmt = QComboBox()
        today = date.today()
        for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d", "%d %B %Y", "%A, %d %B %Y", "%m/%d/%Y", "%B %d, %Y"):
            self.auto_fmt.addItem(today.strftime(fmt), fmt)
        self.fixed_text = QLineEdit(f.get("date_text", ""))
        g = QGridLayout()
        g.addWidget(self.auto, 0, 0)
        g.addWidget(self.auto_fmt, 0, 1)
        g.addWidget(self.fixed, 1, 0)
        g.addWidget(self.fixed_text, 1, 1)
        g.setContentsMargins(20, 0, 0, 0)
        v.addLayout(g)
        self.number = QCheckBox("Slide number")
        self.number.setChecked(f.get("number", False))
        v.addWidget(self.number)
        self.footer = QCheckBox("Footer")
        self.footer.setChecked(f.get("footer", False))
        v.addWidget(self.footer)
        self.footer_text = QLineEdit(f.get("footer_text", ""))
        ft = QHBoxLayout()
        ft.setContentsMargins(20, 0, 0, 0)
        ft.addWidget(self.footer_text)
        v.addLayout(ft)
        self.not_title = QCheckBox("Don't show on title slide")
        self.not_title.setChecked(f.get("not_on_title", False))
        lay.addWidget(box)
        lay.addWidget(self.not_title)
        bb = QDialogButtonBox()
        self.apply_all = bb.addButton("Apply to All", QDialogButtonBox.AcceptRole)
        self.apply_one = bb.addButton("Apply", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        self.all = True
        self.apply_all.clicked.connect(lambda: self._done(True))
        self.apply_one.clicked.connect(lambda: self._done(False))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _done(self, all_):
        self.all = all_
        self.accept()

    def values(self) -> dict:
        return {"date": self.date.isChecked(), "date_auto": self.auto.isChecked(),
                "date_text": self.fixed_text.text() if self.fixed.isChecked()
                else date.today().strftime(self.auto_fmt.currentData()),
                "date_format": self.auto_fmt.currentData(),
                "number": self.number.isChecked(), "footer": self.footer.isChecked(),
                "footer_text": self.footer_text.text(), "not_on_title": self.not_title.isChecked()}


class SetUpShowDialog(QDialog):
    def __init__(self, pres: sm.Presentation, opts: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Up Show")
        lay = QGridLayout(self)
        so = QGroupBox("Show options")
        v = QVBoxLayout(so)
        self.loop = QCheckBox("Loop continuously until 'Esc'")
        self.loop.setChecked(pres.show_loop)
        v.addWidget(self.loop)
        lay.addWidget(so, 0, 0)
        ss = QGroupBox("Show slides")
        g = QGridLayout(ss)
        self.all = QRadioButton("All")
        self.some = QRadioButton("From:")
        n = max(1, len(pres.slides))
        self.first = QSpinBox()
        self.first.setRange(1, n)
        self.last = QSpinBox()
        self.last.setRange(1, n)
        self.first.setValue(opts.get("first", 1))
        self.last.setValue(min(n, opts.get("last", n)))
        (self.some if opts.get("range") else self.all).setChecked(True)
        g.addWidget(self.all, 0, 0, 1, 4)
        g.addWidget(self.some, 1, 0)
        g.addWidget(self.first, 1, 1)
        g.addWidget(QLabel("To:"), 1, 2)
        g.addWidget(self.last, 1, 3)
        lay.addWidget(ss, 0, 1)
        adv = QGroupBox("Advance slides")
        v2 = QVBoxLayout(adv)
        self.manual = QRadioButton("Manually")
        self.timings = QRadioButton("Using timings, if present")
        (self.timings if opts.get("timings", True) else self.manual).setChecked(True)
        v2.addWidget(self.manual)
        v2.addWidget(self.timings)
        lay.addWidget(adv, 1, 1)
        lay.addWidget(_buttons(self), 2, 0, 1, 2)

    def values(self) -> dict:
        return {"loop": self.loop.isChecked(), "range": self.some.isChecked(), "first": self.first.value(),
                "last": self.last.value(), "timings": self.timings.isChecked()}


class TableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Table")
        f = QFormLayout(self)
        self.cols = QSpinBox()
        self.cols.setRange(1, 75)
        self.cols.setValue(5)
        self.rows = QSpinBox()
        self.rows.setRange(1, 75)
        self.rows.setValue(2)
        f.addRow("Number of columns:", self.cols)
        f.addRow("Number of rows:", self.rows)
        f.addRow(_buttons(self))


class HyperlinkDialog(QDialog):
    def __init__(self, text: str, url: str, parent=None, text_editable=True):
        super().__init__(parent)
        self.setWindowTitle("Insert Hyperlink")
        f = QFormLayout(self)
        self.text = QLineEdit(text)
        self.text.setEnabled(text_editable)
        self.url = QLineEdit(url or "http://")
        f.addRow("Text to display:", self.text)
        f.addRow("Address:", self.url)
        bb = _buttons(self)
        self.remove = bb.addButton("Remove Link", QDialogButtonBox.DestructiveRole)
        self.removed = False
        self.remove.clicked.connect(self._remove)
        self.remove.setEnabled(bool(url))
        f.addRow(bb)
        self.setMinimumWidth(420)

    def _remove(self):
        self.removed = True
        self.accept()


class FindDialog(QDialog):
    def __init__(self, win, replace=False):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Replace" if replace else "Find")
        g = QGridLayout(self)
        self.what = QLineEdit()
        self.with_ = QLineEdit()
        g.addWidget(QLabel("Find what:"), 0, 0)
        g.addWidget(self.what, 0, 1)
        self.with_label = QLabel("Replace with:")
        g.addWidget(self.with_label, 1, 0)
        g.addWidget(self.with_, 1, 1)
        self.case = QCheckBox("Match case")
        self.whole = QCheckBox("Find whole words only")
        g.addWidget(self.case, 2, 0, 1, 2)
        g.addWidget(self.whole, 3, 0, 1, 2)
        col = QVBoxLayout()
        self.b_next = QPushButton("Find Next")
        self.b_next.setDefault(True)
        self.b_replace = QPushButton("Replace")
        self.b_all = QPushButton("Replace All")
        close = QPushButton("Close")
        for b in (self.b_next, self.b_replace, self.b_all, close):
            col.addWidget(b)
        col.addStretch(1)
        g.addLayout(col, 0, 2, 4, 1)
        self.b_next.clicked.connect(lambda: win.find_next(self))
        self.b_replace.clicked.connect(lambda: win.replace_one(self))
        self.b_all.clicked.connect(lambda: win.replace_all(self))
        close.clicked.connect(self.close)
        self.set_mode(replace)

    def set_mode(self, replace):
        self.setWindowTitle("Replace" if replace else "Find")
        for w in (self.with_label, self.with_, self.b_replace, self.b_all):
            w.setVisible(replace)


class ZoomDialog(QDialog):
    def __init__(self, current: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Zoom")
        v = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.fit = QRadioButton("Fit")
        v.addWidget(self.fit)
        self.group.addButton(self.fit, 0)
        for pct in (400, 200, 100, 66, 50, 33):
            r = QRadioButton(f"{pct}%")
            self.group.addButton(r, pct)
            v.addWidget(r)
        h = QHBoxLayout()
        h.addWidget(QLabel("Percent:"))
        self.pct = QSpinBox()
        self.pct.setRange(10, 400)
        self.pct.setSuffix("%")
        self.pct.setValue(current)
        h.addWidget(self.pct)
        v.addLayout(h)
        self.group.idClicked.connect(lambda i: self.pct.setValue(i) if i else None)
        v.addWidget(_buttons(self))


class PrintDialog(QDialog):
    """PowerPoint's own print choices; the printer itself is chosen in the next dialog."""

    def __init__(self, pres: sm.Presentation, current: int, parent=None, title="Print"):
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QGridLayout(self)
        rng = QGroupBox("Print range")
        g = QGridLayout(rng)
        self.r_all = QRadioButton("All")
        self.r_current = QRadioButton("Current slide")
        self.r_slides = QRadioButton("Slides:")
        self.slides = QLineEdit()
        self.slides.setPlaceholderText("e.g. 1,3,5-12")
        self.r_all.setChecked(True)
        g.addWidget(self.r_all, 0, 0)
        g.addWidget(self.r_current, 0, 1)
        g.addWidget(self.r_slides, 1, 0)
        g.addWidget(self.slides, 1, 1)
        lay.addWidget(rng, 0, 0, 1, 2)
        f = QFormLayout()
        self.what = QComboBox()
        self.what.addItems(["Slides", "Handouts", "Notes Pages", "Outline View"])
        f.addRow("Print what:", self.what)
        self.per_page = QComboBox()
        for n in (1, 2, 3, 4, 6, 9):
            self.per_page.addItem(str(n), n)
        self.per_page.setCurrentIndex(4)
        f.addRow("Slides per page:", self.per_page)
        self.color = QComboBox()
        self.color.addItems(["Color", "Grayscale", "Pure Black and White"])
        f.addRow("Color/grayscale:", self.color)
        lay.addLayout(f, 1, 0)
        opts = QVBoxLayout()
        self.frame = QCheckBox("Frame slides")
        self.hidden = QCheckBox("Print hidden slides")
        self.fit = QCheckBox("Scale to fit paper")
        self.fit.setChecked(True)
        for w in (self.frame, self.hidden, self.fit):
            opts.addWidget(w)
        opts.addStretch(1)
        lay.addLayout(opts, 1, 1)
        self.what.currentIndexChanged.connect(lambda i: self.per_page.setEnabled(i == 1))
        self.per_page.setEnabled(False)
        lay.addWidget(_buttons(self), 2, 0, 1, 2)
        self.n = len(pres.slides)
        self.current = current

    def indexes(self) -> list[int]:
        if self.r_current.isChecked():
            return [self.current]
        if self.r_slides.isChecked():
            out = []
            for part in self.slides.text().replace(" ", "").split(","):
                if not part:
                    continue
                if "-" in part:
                    a, _s, b = part.partition("-")
                    try:
                        out += list(range(int(a) - 1, int(b)))
                    except ValueError:
                        pass
                else:
                    try:
                        out.append(int(part) - 1)
                    except ValueError:
                        pass
            return [i for i in out if 0 <= i < self.n]
        return list(range(self.n))


class FormatBackgroundDialog(QDialog):
    """Fill: solid / gradient / picture, Hide background graphics, Apply to All, Reset."""

    def __init__(self, win, fill: dict | None, hide_graphics: bool, parent=None):
        super().__init__(parent or win)
        self.win = win
        self.setWindowTitle("Format Background")
        self.fill = fill
        self.reset = False
        self.all = False
        v = QVBoxLayout(self)
        self.solid = QRadioButton("Solid fill")
        self.grad = QRadioButton("Gradient fill")
        self.pic = QRadioButton("Picture or texture fill")
        for w in (self.solid, self.grad, self.pic):
            v.addWidget(w)
        t = (fill or {}).get("type")
        {"solid": self.solid, "grad": self.grad, "pic": self.pic}.get(t, self.solid).setChecked(True)
        h = QHBoxLayout()
        h.addWidget(QLabel("Color:"))
        self.color_btn = QToolButton()
        self.color_btn.setPopupMode(QToolButton.InstantPopup)
        self.color = (fill or {}).get("color") or ((fill or {}).get("stops") or [[0, sm.scheme("bg1")]])[-1][1]
        menu = sw.ThemeColorMenu(self, lambda: win.color_ctx())
        menu.picked.connect(self._color)
        self.color_btn.setMenu(menu)
        h.addWidget(self.color_btn)
        h.addSpacing(12)
        h.addWidget(QLabel("Transparency:"))
        self.alpha = QSlider(Qt.Horizontal)
        self.alpha.setRange(0, 100)
        h.addWidget(self.alpha)
        v.addLayout(h)
        h2 = QHBoxLayout()
        self.file_btn = QPushButton("File...")
        self.file_btn.clicked.connect(self._file)
        self.image_key = (fill or {}).get("image")
        h2.addWidget(QLabel("Insert from:"))
        h2.addWidget(self.file_btn)
        h2.addStretch(1)
        v.addLayout(h2)
        self.hide = QCheckBox("Hide background graphics")
        self.hide.setChecked(hide_graphics)
        v.addWidget(self.hide)
        bb = QDialogButtonBox()
        reset = bb.addButton("Reset Background", QDialogButtonBox.ResetRole)
        close = bb.addButton("Close", QDialogButtonBox.AcceptRole)
        apply_all = bb.addButton("Apply to All", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        reset.clicked.connect(self._reset)
        apply_all.clicked.connect(self._all)
        close.clicked.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._update_btn()

    def _update_btn(self):
        q = self.win.color_ctx().color(self.color)
        pm = QPixmap(28, 16)
        pm.fill(q)
        self.color_btn.setIcon(QIcon(pm))

    def _color(self, c):
        if c:
            self.color = c
            self._update_btn()

    def _file(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Insert Picture", "", "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff *.webp)")
        if fn:
            with open(fn, "rb") as f:
                self.image_key = self.win.pres.add_media(f.read(), fn.rsplit(".", 1)[-1])
            self.pic.setChecked(True)

    def _reset(self):
        self.reset = True
        self.accept()

    def _all(self):
        self.all = True
        self.accept()

    def result_fill(self) -> dict | None:
        c = dict(self.color)
        if self.alpha.value():
            c["mods"] = list(c.get("mods", [])) + [["alpha", (100 - self.alpha.value()) * 1000]]
        if self.pic.isChecked() and self.image_key:
            return {"type": "pic", "image": self.image_key}
        if self.grad.isChecked():
            light = dict(c)
            light["mods"] = list(c.get("mods", [])) + [["tint", 40000]]
            return {"type": "grad", "stops": [[0, light], [100000, c]], "angle": 90.0, "path": None}
        return {"type": "solid", "color": c}


def color_swatch(q: QColor, w=28, h=16) -> QIcon:
    pm = QPixmap(w, h)
    pm.fill(q)
    return QIcon(pm)
