"""Calculator, as in Windows 7: Standard (Alt+1), Scientific (Alt+2) and Programmer (Alt+3) views,
History (Ctrl+H), Digit grouping, memory, copy and paste, the same keyboard keys. The arithmetic
is in calc_engine.py."""
from __future__ import annotations

import sys

from PySide6.QtCore import QLocale, QSettings, QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QMainWindow, QPushButton, QRadioButton, QVBoxLayout, QWidget)

import accessories as acc
from calc_engine import Engine

APP = "Calculator"
ICON = ("accessories-calculator",)
BTN = QSize(36, 28)

STANDARD = [
    [("MC", "mc"), ("MR", "mr"), ("MS", "ms"), ("M+", "m+"), ("M-", "m-")],
    [("←", "bs"), ("CE", "ce"), ("C", "c"), ("±", "neg"), ("√", "sqrt")],
    [("7", "7"), ("8", "8"), ("9", "9"), ("/", "/"), ("%", "%")],
    [("4", "4"), ("5", "5"), ("6", "6"), ("*", "*"), ("1/x", "recip")],
    [("1", "1"), ("2", "2"), ("3", "3"), ("-", "-"), ("=", "=")],
    [("0", "0"), None, (".", "."), ("+", "+"), None],
]
SCIENTIFIC = [
    [None, ("Inv", "inv"), ("ln", "ln"), ("(", "("), (")", ")")],
    [("Int", "int"), ("sinh", "sinh"), ("sin", "sin"), ("x²", "sqr"), ("n!", "fact")],
    [("dms", "dms"), ("cosh", "cosh"), ("cos", "cos"), ("xʸ", "pow"), ("ʸ√x", "root")],
    [("π", "pi"), ("tanh", "tanh"), ("tan", "tan"), ("x³", "cube"), ("³√x", "cuberoot")],
    [("F-E", "fe"), ("Exp", "exp"), ("Mod", "mod"), ("log", "log"), ("10ˣ", "pow10")],
]
PROGRAMMER = [
    [None, ("Mod", "mod"), ("A", "A")],
    [("(", "("), (")", ")"), ("B", "B")],
    [("RoL", "rol"), ("RoR", "ror"), ("C", "C_hex")],
    [("Or", "or"), ("Xor", "xor"), ("D", "D")],
    [("Lsh", "lsh"), ("Rsh", "rsh"), ("E", "E")],
    [("Not", "not"), ("And", "and"), ("F", "F")],
]
INVERSES = {"ln": ("eˣ", "exp"), "sin": ("sin⁻¹", "asin"), "cos": ("cos⁻¹", "acos"),
            "tan": ("tan⁻¹", "atan"), "sinh": ("sinh⁻¹", "asinh"),
            "cosh": ("cosh⁻¹", "acosh"), "tanh": ("tanh⁻¹", "atanh"),
            "int": ("Frac", "frac"), "dms": ("deg", "deg"), "sqr": ("√x", "sqrt"),
            "cube": ("³√x", "cuberoot")}


class Display(QFrame):
    """The number box: history line, memory and parenthesis marks, the number."""

    def __init__(self):
        super().__init__()
        self.setFrameShape(QFrame.Box)
        self.setFrameShadow(QFrame.Sunken)
        self.setStyleSheet("Display { background: #fbfdff; border: 1px solid #8e9fb5; border-radius: 3px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 4)
        lay.setSpacing(0)
        self.expr = QLabel()
        self.expr.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.expr.setStyleSheet("color: #555; background: transparent;")
        lay.addWidget(self.expr)
        row = QHBoxLayout()
        self.marks = QLabel()
        self.marks.setStyleSheet("color: #333; background: transparent;")
        row.addWidget(self.marks, 0, Qt.AlignBottom)
        self.number = QLabel("0")
        self.number.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f = QFont(self.font())
        f.setPixelSize(24)
        self.number.setFont(f)
        self.number.setStyleSheet("background: transparent;")
        self.number.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(self.number, 1)
        lay.addLayout(row)
        self.base_font = f

    def set_number(self, text: str, width: int):
        f = QFont(self.base_font)
        self.number.setFont(f)
        # shrink long numbers to fit, like Windows 7 does
        while self.number.fontMetrics().horizontalAdvance(text) > width - 30 and f.pixelSize() > 11:
            f.setPixelSize(f.pixelSize() - 1)
            self.number.setFont(f)
        self.number.setText(text)


class BitPanel(QWidget):
    """Programmer view: the 64 bits, click one to flip it."""

    def __init__(self, win: "Calculator"):
        super().__init__()
        self.win = win
        grid = QGridLayout(self)
        grid.setContentsMargins(4, 2, 4, 2)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(0)
        self.bits: list[QLabel] = []
        f = QFont("monospace")
        f.setStyleHint(QFont.Monospace)
        f.setPixelSize(11)
        for half in range(2):
            for group in range(8):
                hi = 63 - half * 32 - group * 4
                lab = BitGroup(self, hi)
                lab.setFont(f)
                self.bits.append(lab)
                grid.addWidget(lab, half * 2, group)
                if group in (0, 4, 7):
                    num = QLabel(str(hi if group != 7 else hi - 3))
                    num.setFont(f)
                    num.setStyleSheet("color: #666;")
                    num.setAlignment(Qt.AlignLeft if group != 7 else Qt.AlignRight)
                    grid.addWidget(num, half * 2 + 1, group)

    def update_bits(self, value: int, word: int):
        u = value & ((1 << 64) - 1)
        for g in self.bits:
            g.show_bits(u, word)


class BitGroup(QLabel):
    def __init__(self, panel: BitPanel, hi: int):
        super().__init__("0000")
        self.panel = panel
        self.hi = hi
        self.setCursor(Qt.PointingHandCursor)

    def show_bits(self, u: int, word: int):
        text = "".join("1" if (u >> b) & 1 else "0" for b in range(self.hi, self.hi - 4, -1))
        self.setText(text)
        self.setEnabled(self.hi - 3 < word)

    def mousePressEvent(self, e):
        if not self.isEnabled():
            return
        cw = self.width() / 4
        idx = min(3, max(0, int(e.position().x() // cw)))
        self.panel.win.flip_bit(self.hi - idx)


class Calculator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Classic7", "Calculator")
        self.engine = Engine()
        self.setWindowTitle(APP)
        self.setWindowIcon(acc.icon(*ICON))
        self.loc = QLocale()
        self.grouping = self.settings.value("grouping", False, bool)
        self.show_history = False
        self.buttons: dict[str, QPushButton] = {}
        self._menus()
        self.set_mode(self.settings.value("mode", "standard"))

    # ---- menus ------------------------------------------------------------------------------
    def _menus(self):
        mb = self.menuBar()
        view = mb.addMenu("&View")
        grp = QActionGroup(self)
        self.mode_actions = {}
        for text, mode, key in (("&Standard", "standard", "Alt+1"), ("S&cientific", "scientific", "Alt+2"),
                                ("&Programmer", "programmer", "Alt+3")):
            a = QAction(text, self, checkable=True)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _c=False, m=mode: self.set_mode(m))
            grp.addAction(a)
            view.addAction(a)
            self.mode_actions[mode] = a
        view.addSeparator()
        self.a_history = QAction("&History", self, checkable=True)
        self.a_history.setShortcut(QKeySequence("Ctrl+H"))
        self.a_history.triggered.connect(self.toggle_history)
        view.addAction(self.a_history)
        self.a_group = QAction("&Digit grouping", self, checkable=True)
        self.a_group.setChecked(self.grouping)
        self.a_group.triggered.connect(self.toggle_grouping)
        view.addAction(self.a_group)
        edit = mb.addMenu("&Edit")
        a = QAction("&Copy", self)
        a.setShortcut(QKeySequence("Ctrl+C"))
        a.triggered.connect(self.copy)
        edit.addAction(a)
        a = QAction("&Paste", self)
        a.setShortcut(QKeySequence("Ctrl+V"))
        a.triggered.connect(self.paste)
        edit.addAction(a)
        edit.addSeparator()
        a = QAction("C&lear history", self)
        a.triggered.connect(self.clear_history)
        edit.addAction(a)
        helpm = mb.addMenu("&Help")
        a = QAction("&About Calculator", self)
        a.triggered.connect(lambda: acc.about(self, APP, ICON))
        helpm.addAction(a)

    # ---- layout -----------------------------------------------------------------------------
    def _button(self, text: str, key: str) -> QPushButton:
        b = QPushButton(text)
        b.setFixedSize(BTN)
        b.setFocusPolicy(Qt.NoFocus)
        b.setAutoDefault(False)
        b.clicked.connect(lambda _c=False, k=key: self.press(k))
        self.buttons[key] = b
        return b

    def _keypad(self, grid: QGridLayout, col0: int):
        for r, row in enumerate(STANDARD):
            for c, cell in enumerate(row):
                if cell is None:
                    continue
                text, key = cell
                b = self._button(text, key)
                if key == "0":
                    b.setFixedSize(BTN.width() * 2 + grid.horizontalSpacing(), BTN.height())
                    grid.addWidget(b, r, col0 + c, 1, 2)
                elif key == "=":
                    b.setFixedSize(BTN.width(), BTN.height() * 2 + grid.verticalSpacing())
                    grid.addWidget(b, r, col0 + c, 2, 1)
                else:
                    grid.addWidget(b, r, col0 + c)

    def set_mode(self, mode: str):
        if mode not in ("standard", "scientific", "programmer"):
            mode = "standard"
        self.engine.set_mode(mode)
        self.mode_actions[mode].setChecked(True)
        self.settings.setValue("mode", mode)
        self.buttons = {}
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(6)
        self.history_list = QListWidget()
        self.history_list.setFixedHeight(110)
        self.history_list.setVisible(self.show_history)
        self.history_list.itemClicked.connect(self._recall_history)
        outer.addWidget(self.history_list)
        self.display = Display()
        outer.addWidget(self.display)
        self.bit_panel = None
        if mode == "programmer":
            self.bit_panel = BitPanel(self)
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            fl = QVBoxLayout(frame)
            fl.setContentsMargins(0, 0, 0, 0)
            fl.addWidget(self.bit_panel)
            outer.addWidget(frame)
        body = QHBoxLayout()
        body.setSpacing(8)
        grid = QGridLayout()
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)
        if mode == "scientific":
            radio_box = QFrame()
            radio_box.setFrameShape(QFrame.StyledPanel)
            rl = QHBoxLayout(radio_box)
            rl.setContentsMargins(6, 0, 6, 0)
            self.angle_group = QButtonGroup(self)
            for text, angle in (("Degrees", "deg"), ("Radians", "rad"), ("Grads", "grad")):
                rb = QRadioButton(text)
                rb.setFocusPolicy(Qt.NoFocus)
                rb.setChecked(self.engine.angle == angle)
                rb.toggled.connect(lambda on, a=angle: on and self._set_angle(a))
                self.angle_group.addButton(rb)
                rl.addWidget(rb)
            radio_box.setFixedHeight(BTN.height())
            grid.addWidget(radio_box, 0, 0, 1, 5)
            for r, row in enumerate(SCIENTIFIC):
                for c, cell in enumerate(row):
                    if cell:
                        grid.addWidget(self._button(*cell), r + 1, c)
            spacer = QWidget()
            spacer.setFixedWidth(6)
            grid.addWidget(spacer, 0, 5)
            self._keypad(grid, 6)
            self.buttons["inv"].setCheckable(True)
            self.buttons["fe"].setCheckable(True)
            self.buttons["fe"].setChecked(self.engine.fe)
        elif mode == "programmer":
            side = QVBoxLayout()
            for title, items, attr in (("base", (("Hex", 16), ("Dec", 10), ("Oct", 8), ("Bin", 2)), "base"),
                                       ("word", (("Qword", 64), ("Dword", 32), ("Word", 16), ("Byte", 8)), "word")):
                box = QFrame()
                box.setFrameShape(QFrame.StyledPanel)
                bl = QVBoxLayout(box)
                bl.setContentsMargins(6, 3, 6, 3)
                bl.setSpacing(1)
                group = QButtonGroup(self)
                for text, val in items:
                    rb = QRadioButton(text)
                    rb.setFocusPolicy(Qt.NoFocus)
                    rb.setChecked(getattr(self.engine, attr) == val)
                    rb.toggled.connect(lambda on, a=attr, v=val: on and self._set_prog(a, v))
                    group.addButton(rb)
                    bl.addWidget(rb)
                setattr(self, f"{title}_group", group)
                side.addWidget(box)
            side.addStretch(1)
            body.addLayout(side)
            for r, row in enumerate(PROGRAMMER):
                for c, cell in enumerate(row):
                    if cell:
                        grid.addWidget(self._button(*cell), r, c)
            spacer = QWidget()
            spacer.setFixedWidth(6)
            grid.addWidget(spacer, 0, 3)
            self._keypad(grid, 4)
        else:
            self._keypad(grid, 0)
        body.addLayout(grid)
        outer.addLayout(body)
        self.setCentralWidget(central)
        self.refresh()
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

    def _set_angle(self, angle: str):
        self.engine.angle = angle

    def _set_prog(self, attr: str, val: int):
        if attr == "base":
            self.engine.set_base(val)
        else:
            self.engine.set_word(val)
        self.refresh()

    # ---- keys -------------------------------------------------------------------------------
    def press(self, key: str):
        e = self.engine
        inv = e.inv
        if key in "0123456789" or key == "." or (key in "ABCDEF" and len(key) == 1):
            e.digit(key)
        elif key == "C_hex":
            e.digit("C")
        elif key in ("+", "-", "*", "/", "mod", "pow", "root", "and", "or", "xor", "lsh", "rsh"):
            if key == "pow" and inv:
                key = "root"
            e.binary(key)
        elif key == "=":
            e.equals()
        elif key == "c":
            e.clear()
        elif key == "ce":
            e.clear_entry()
        elif key == "bs":
            e.backspace()
        elif key == "neg":
            e.negate()
        elif key == "%":
            e.percent()
        elif key in ("mc", "mr", "ms", "m+", "m-"):
            e.mem(key)
        elif key == "(":
            e.open_paren()
        elif key == ")":
            e.close_paren()
        elif key == "pi":
            e.constant("pi")
        elif key == "exp":
            e.exp()
        elif key == "fe":
            e.fe = not e.fe
        elif key == "inv":
            e.inv = not e.inv
            self._label_inverse()
            return
        else:
            fn = INVERSES[key][1] if inv and key in INVERSES else key
            e.unary(fn)
        self.refresh()

    def _label_inverse(self):
        inv = self.engine.inv
        if "inv" in self.buttons:
            self.buttons["inv"].setChecked(inv)
        for key, (alt, _fn) in INVERSES.items():
            b = self.buttons.get(key)
            if not b:
                continue
            normal = next((t for row in SCIENTIFIC for cell in row if cell and cell[1] == key for t in [cell[0]]), None)
            if normal:
                b.setText(alt if inv else normal)

    def keyPressEvent(self, ev):
        k = ev.key()
        text = ev.text()
        mods = ev.modifiers()
        mode = self.engine.mode
        ctrl = bool(mods & Qt.ControlModifier)
        if ctrl:
            mapping = {Qt.Key_L: "mc", Qt.Key_R: "mr", Qt.Key_M: "ms", Qt.Key_P: "m+", Qt.Key_Q: "m-"}
            if k in mapping:
                self.press(mapping[k])
                return
            super().keyPressEvent(ev)
            return
        if k in (Qt.Key_Return, Qt.Key_Enter) or text == "=":
            self.press("=")
        elif k == Qt.Key_Escape:
            self.press("c")
        elif k == Qt.Key_Delete:
            self.press("ce")
        elif k == Qt.Key_Backspace:
            self.press("bs")
        elif k == Qt.Key_F9:
            self.press("neg")
        elif mode == "programmer" and k in (Qt.Key_F5, Qt.Key_F6, Qt.Key_F7, Qt.Key_F8):
            self._radio("base", {Qt.Key_F5: 16, Qt.Key_F6: 10, Qt.Key_F7: 8, Qt.Key_F8: 2}[k])
        elif mode == "programmer" and k in (Qt.Key_F12, Qt.Key_F2, Qt.Key_F3, Qt.Key_F4):
            self._radio("word", {Qt.Key_F12: 64, Qt.Key_F2: 32, Qt.Key_F3: 16, Qt.Key_F4: 8}[k])
        elif mode == "scientific" and k in (Qt.Key_F3, Qt.Key_F4, Qt.Key_F5):
            idx = {Qt.Key_F3: 0, Qt.Key_F4: 1, Qt.Key_F5: 2}[k]
            self.angle_group.buttons()[idx].setChecked(True)
        elif text and text in "0123456789":
            self.press(text)
        elif text in (".", ","):
            self.press(".")
        elif text in ("+", "-", "*", "/"):
            self.press(text)
        elif text == "@":
            self.press("sqrt")
        elif text == "%":
            self.press("mod" if mode == "programmer" else "%")
        elif mode == "programmer" and text and text.upper() in "ABCDEF":
            self.press("C_hex" if text.upper() == "C" else text.upper())
        elif mode == "programmer" and text in ("&", "|", "^", "~", "<", ">"):
            self.press({"&": "and", "|": "or", "^": "xor", "~": "not", "<": "lsh", ">": "rsh"}[text])
        elif text in ("(", ")") and mode != "standard":
            self.press(text)
        elif mode != "programmer" and text in ("r", "R"):
            self.press("recip")
        elif mode == "scientific" and text:
            sci = {"n": "ln", "l": "log", "s": "sin", "o": "cos", "t": "tan", "q": "sqr", "y": "pow", "#": "cube",
                   "!": "fact", "p": "pi", "v": "fe", "x": "exp", "m": "dms", "i": "inv", ";": "int"}
            if text.lower() in sci:
                self.press(sci[text.lower()])
            else:
                super().keyPressEvent(ev)
        else:
            super().keyPressEvent(ev)

    def _radio(self, which: str, value: int):
        group = getattr(self, f"{which}_group", None)
        if not group:
            return
        for b in group.buttons():
            if (which == "base" and {"Hex": 16, "Dec": 10, "Oct": 8, "Bin": 2}[b.text()] == value) or \
                    (which == "word" and {"Qword": 64, "Dword": 32, "Word": 16, "Byte": 8}[b.text()] == value):
                b.setChecked(True)

    # ---- display ----------------------------------------------------------------------------
    def localize(self, text: str) -> str:
        e = self.engine
        if e.error or text in ("",):
            return text
        if e.mode == "programmer":
            if self.grouping:
                if e.base == 10:
                    neg = text.startswith("-")
                    digits = text.lstrip("-")
                    grouped = f"{int(digits):,}".replace(",", self.loc.groupSeparator())
                    return ("-" if neg else "") + grouped
                step = 4 if e.base in (16, 2) else 3
                t = text
                parts = []
                while t:
                    parts.insert(0, t[-step:])
                    t = t[:-step]
                return " ".join(parts)
            return text
        dec = self.loc.decimalPoint()
        mant, _sep, expo = text.partition("e")
        sign = "-" if mant.startswith("-") else ""
        mant = mant.lstrip("-")
        whole, dot, frac = mant.partition(".")
        if self.grouping and whole.isdigit():
            whole = f"{int(whole):,}".replace(",", self.loc.groupSeparator())
        out = sign + whole + (dec + frac if dot else "")
        if _sep:
            out += "e" + expo
        return out

    def refresh(self):
        e = self.engine
        text = self.localize(e.display())
        self.display.set_number(text, self.display.width() or 200)
        expr = e.expression()
        self.display.expr.setText(self.localize_expr(expr))
        marks = []
        if e.memory is not None:
            marks.append("M")
        if e.mode != "standard" and e.parens:
            marks.append(f"(={e.parens}")
        self.display.marks.setText("  ".join(marks))
        if self.bit_panel is not None:
            self.bit_panel.update_bits(e.current() if not e.error else 0, e.word)
        if e.mode == "programmer":
            allowed = {16: "0123456789ABCDEF", 10: "0123456789", 8: "01234567", 2: "01"}[e.base]
            for key, b in self.buttons.items():
                d = "C" if key == "C_hex" else key
                if len(d) == 1 and d in "0123456789ABCDEF":
                    b.setEnabled(d in allowed)
            for key in (".", "sqrt", "%", "recip"):
                if key in self.buttons:
                    self.buttons[key].setEnabled(False)
        # after an error only C, CE and digits work
        blocked = bool(e.error)
        for key, b in self.buttons.items():
            if key in ("c", "ce") or key in "0123456789" or (e.mode == "programmer" and len(key) == 1):
                continue
            if e.mode == "programmer" and key in (".", "sqrt", "%", "recip"):
                continue
            b.setEnabled(not blocked)
        if self.show_history:
            self._fill_history()

    def localize_expr(self, expr: str) -> str:
        if self.engine.mode == "programmer":
            return expr
        dec = self.loc.decimalPoint()
        return "".join(dec if ch == "." else ch for ch in expr)

    def flip_bit(self, bit: int):
        from calc_engine import to_signed
        e = self.engine
        if e.error or bit >= e.word:
            return
        cur = e.current()
        e.entry = None
        e.value = to_signed(cur ^ (1 << bit), e.word)
        e.unary_text = None
        self.refresh()

    # ---- history, copy/paste ---------------------------------------------------------------
    def toggle_history(self, on: bool):
        self.show_history = on
        self.history_list.setVisible(on)
        if on:
            self._fill_history()
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

    def _fill_history(self):
        self.history_list.clear()
        for expr, res in self.engine.history:
            self.history_list.addItem(f"{self.localize_expr(expr)} = {self.localize(res)}")
        self.history_list.scrollToBottom()

    def _recall_history(self, item):
        idx = self.history_list.row(item)
        if 0 <= idx < len(self.engine.history):
            self.engine.paste(self.engine.history[idx][1])
            self.refresh()

    def clear_history(self):
        self.engine.history.clear()
        if self.show_history:
            self._fill_history()

    def copy(self):
        QApplication.clipboard().setText(self.localize(self.engine.display()))

    def paste(self):
        t = QApplication.clipboard().text()
        if self.engine.mode != "programmer":
            t = t.replace(self.loc.groupSeparator(), "").replace(self.loc.decimalPoint(), ".")
        if self.engine.paste(t):
            self.refresh()

    def toggle_grouping(self, on: bool):
        self.grouping = on
        self.settings.setValue("grouping", on)
        self.refresh()


def main(argv=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-calc")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-calc")
    w = Calculator()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
