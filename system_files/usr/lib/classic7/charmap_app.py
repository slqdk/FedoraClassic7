"""Character Map, as in Windows 7: pick a font, see every character it has, enlarge one by
holding the mouse on it, collect characters to copy. Advanced view: group by Unicode subrange,
search by name, go to a code point."""
from __future__ import annotations

import sys
import unicodedata

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRawFont
from PySide6.QtWidgets import (QAbstractScrollArea, QApplication, QCheckBox, QComboBox, QFontComboBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
                               QPushButton, QStatusBar, QVBoxLayout, QWidget)

import accessories as acc

APP = "Character Map"
ICON = ("accessories-character-map",)
COLS = 20
CELL = 22

BLOCKS = [
    (0x0020, 0x007F, "Basic Latin"), (0x00A0, 0x00FF, "Latin-1 Supplement"), (0x0100, 0x017F, "Latin Extended-A"),
    (0x0180, 0x024F, "Latin Extended-B"), (0x0250, 0x02AF, "IPA Extensions"),
    (0x02B0, 0x02FF, "Spacing Modifier Letters"), (0x0300, 0x036F, "Combining Diacritical Marks"),
    (0x0370, 0x03FF, "Greek and Coptic"), (0x0400, 0x04FF, "Cyrillic"), (0x0500, 0x052F, "Cyrillic Supplement"),
    (0x0530, 0x058F, "Armenian"), (0x0590, 0x05FF, "Hebrew"), (0x0600, 0x06FF, "Arabic"),
    (0x0900, 0x097F, "Devanagari"), (0x0E00, 0x0E7F, "Thai"), (0x10A0, 0x10FF, "Georgian"),
    (0x1E00, 0x1EFF, "Latin Extended Additional"), (0x1F00, 0x1FFF, "Greek Extended"),
    (0x2000, 0x206F, "General Punctuation"), (0x2070, 0x209F, "Superscripts and Subscripts"),
    (0x20A0, 0x20CF, "Currency Symbols"), (0x2100, 0x214F, "Letterlike Symbols"), (0x2150, 0x218F, "Number Forms"),
    (0x2190, 0x21FF, "Arrows"), (0x2200, 0x22FF, "Mathematical Operators"),
    (0x2300, 0x23FF, "Miscellaneous Technical"), (0x2400, 0x243F, "Control Pictures"),
    (0x2460, 0x24FF, "Enclosed Alphanumerics"), (0x2500, 0x257F, "Box Drawing"), (0x2580, 0x259F, "Block Elements"),
    (0x25A0, 0x25FF, "Geometric Shapes"), (0x2600, 0x26FF, "Miscellaneous Symbols"), (0x2700, 0x27BF, "Dingbats"),
    (0x27C0, 0x27EF, "Miscellaneous Mathematical Symbols-A"), (0x27F0, 0x27FF, "Supplemental Arrows-A"),
    (0x2800, 0x28FF, "Braille Patterns"), (0x2900, 0x297F, "Supplemental Arrows-B"),
    (0x2A00, 0x2AFF, "Supplemental Mathematical Operators"), (0x2B00, 0x2BFF, "Miscellaneous Symbols and Arrows"),
    (0x2C60, 0x2C7F, "Latin Extended-C"), (0x2E00, 0x2E7F, "Supplemental Punctuation"),
    (0x3000, 0x303F, "CJK Symbols and Punctuation"), (0x3040, 0x309F, "Hiragana"), (0x30A0, 0x30FF, "Katakana"),
    (0x4E00, 0x9FFF, "CJK Unified Ideographs"), (0xAC00, 0xD7AF, "Hangul Syllables"),
    (0xE000, 0xF8FF, "Private Use Area"), (0xFB00, 0xFB4F, "Alphabetic Presentation Forms"),
    (0xFE30, 0xFE4F, "CJK Compatibility Forms"), (0xFF00, 0xFFEF, "Halfwidth and Fullwidth Forms"),
    (0xFFF0, 0xFFFF, "Specials"), (0x1D400, 0x1D7FF, "Mathematical Alphanumeric Symbols"),
    (0x1F000, 0x1F02F, "Mahjong Tiles"), (0x1F0A0, 0x1F0FF, "Playing Cards"),
    (0x1F300, 0x1F5FF, "Miscellaneous Symbols and Pictographs"), (0x1F600, 0x1F64F, "Emoticons"),
    (0x1F680, 0x1F6FF, "Transport and Map Symbols"), (0x1F900, 0x1F9FF, "Supplemental Symbols and Pictographs"),
]

_cache: dict[str, list[int]] = {}


def char_name(cp: int) -> str:
    try:
        return unicodedata.name(chr(cp)).title()
    except ValueError:
        if 0xE000 <= cp <= 0xF8FF:
            return "Private Use Character"
        if 0x4E00 <= cp <= 0x9FFF:
            return "CJK Unified Ideograph"
        return ""


def font_chars(family: str) -> list[int]:
    """The code points this font has a picture for (no control characters or unassigned ones)."""
    if family in _cache:
        return _cache[family]
    f = QFont(family)
    f.setPixelSize(16)
    raw = QRawFont.fromFont(f)
    out = []
    ranges = [(0x20, 0x7E), (0xA0, 0x2FFFF)]
    for lo, hi in ranges:
        for cp in range(lo, hi + 1):
            if 0xD800 <= cp <= 0xDFFF:
                continue
            if not raw.supportsCharacter(cp):
                continue
            cat = unicodedata.category(chr(cp))
            if cat in ("Cc", "Cs") or (cat == "Cn" and not 0xE000 <= cp <= 0xF8FF):
                continue
            out.append(cp)
    _cache[family] = out
    return out


class Grid(QAbstractScrollArea):
    """The character table: 20 per row, the chosen one framed, enlarged while the mouse is down."""
    chosen = Signal(int)
    picked = Signal(int)            # double-click: add to "Characters to copy"

    def __init__(self):
        super().__init__()
        self.chars: list[int] = []
        self.family = ""
        self.current = 0
        self.zoom_cp: int | None = None
        self.setFixedWidth(COLS * CELL + 2 + self.verticalScrollBar().sizeHint().width())
        self.viewport().setMouseTracking(False)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_chars(self, family: str, chars: list[int]):
        self.family = family
        self.chars = chars
        self.current = 0
        rows = (len(chars) + COLS - 1) // COLS
        visible = max(1, self.viewport().height() // CELL)
        self.verticalScrollBar().setRange(0, max(0, rows - visible))
        self.verticalScrollBar().setPageStep(visible)
        self.verticalScrollBar().setValue(0)
        self.viewport().update()
        if chars:
            self.chosen.emit(chars[0])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        rows = (len(self.chars) + COLS - 1) // COLS
        visible = max(1, self.viewport().height() // CELL)
        self.verticalScrollBar().setRange(0, max(0, rows - visible))
        self.verticalScrollBar().setPageStep(visible)

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()

    def _font(self, size: int) -> QFont:
        f = QFont(self.family)
        f.setPixelSize(size)
        f.setStyleStrategy(QFont.NoFontMerging)
        return f

    def paintEvent(self, _):
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), QColor("white"))
        first_row = self.verticalScrollBar().value()
        rows = self.viewport().height() // CELL + 1
        p.setFont(self._font(15))
        p.setPen(QColor("#c0c0c0"))
        for r in range(rows + 1):
            p.drawLine(0, r * CELL, COLS * CELL, r * CELL)
        for c in range(COLS + 1):
            p.drawLine(c * CELL, 0, c * CELL, rows * CELL)
        for r in range(rows):
            for c in range(COLS):
                i = (first_row + r) * COLS + c
                if i >= len(self.chars):
                    break
                rect = QRect(c * CELL, r * CELL, CELL, CELL)
                if i == self.current:
                    p.setPen(QPen(QColor("black"), 2))
                    p.drawRect(rect.adjusted(1, 1, -1, -1))
                p.setPen(QColor("black"))
                p.drawText(rect, Qt.AlignCenter, chr(self.chars[i]))
        if self.zoom_cp is not None:
            idx = self.chars.index(self.zoom_cp)
            r, c = divmod(idx, COLS)
            r -= first_row
            big = QRect(0, 0, CELL * 3, CELL * 3)
            big.moveCenter(QRect(c * CELL, r * CELL, CELL, CELL).center())
            big.moveLeft(max(0, min(big.left(), COLS * CELL - big.width())))
            big.moveTop(max(0, min(big.top(), self.viewport().height() - big.height())))
            p.fillRect(big, QColor("white"))
            p.setPen(QPen(QColor("black"), 1))
            p.drawRect(big.adjusted(0, 0, -1, -1))
            p.setFont(self._font(40))
            p.drawText(big, Qt.AlignCenter, chr(self.zoom_cp))

    def _index_at(self, pos: QPoint) -> int:
        c = pos.x() // CELL
        r = pos.y() // CELL + self.verticalScrollBar().value()
        if c >= COLS:
            return -1
        i = r * COLS + c
        return i if 0 <= i < len(self.chars) else -1

    def select(self, i: int):
        if not 0 <= i < len(self.chars):
            return
        self.current = i
        row = i // COLS
        sb = self.verticalScrollBar()
        visible = max(1, self.viewport().height() // CELL)
        if row < sb.value():
            sb.setValue(row)
        elif row >= sb.value() + visible:
            sb.setValue(row - visible + 1)
        self.chosen.emit(self.chars[i])
        self.viewport().update()

    def mousePressEvent(self, e):
        i = self._index_at(e.position().toPoint())
        if i >= 0 and e.button() == Qt.LeftButton:
            self.select(i)
            self.zoom_cp = self.chars[i]
            self.viewport().update()

    def mouseMoveEvent(self, e):
        if self.zoom_cp is None:
            return
        i = self._index_at(e.position().toPoint())
        if i >= 0 and self.chars[i] != self.zoom_cp:
            self.select(i)
            self.zoom_cp = self.chars[i]
            self.viewport().update()

    def mouseReleaseEvent(self, _e):
        self.zoom_cp = None
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        i = self._index_at(e.position().toPoint())
        if i >= 0:
            self.picked.emit(self.chars[i])

    def keyPressEvent(self, e):
        k = e.key()
        step = {Qt.Key_Left: -1, Qt.Key_Right: 1, Qt.Key_Up: -COLS, Qt.Key_Down: COLS,
                Qt.Key_PageUp: -COLS * 8, Qt.Key_PageDown: COLS * 8}.get(k)
        if step:
            self.select(max(0, min(len(self.chars) - 1, self.current + step)))
        elif k == Qt.Key_Home:
            self.select(0)
        elif k == Qt.Key_End:
            self.select(len(self.chars) - 1)
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            if self.chars:
                self.picked.emit(self.chars[self.current])
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() - e.angleDelta().y() // 40)


class CharMap(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(acc.icon(*ICON))
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(8, 8, 8, 4)
        top = QHBoxLayout()
        font_label = QLabel("&Font:")
        top.addWidget(font_label)
        self.font_box = QFontComboBox()
        font_label.setBuddy(self.font_box)
        self.font_box.currentFontChanged.connect(lambda _f: self.reload())
        top.addWidget(self.font_box, 1)
        helpb = QPushButton("&Help")
        helpb.clicked.connect(lambda: acc.about(self, APP, ICON,
                                                "Click a character to see it larger; double-click or Select puts it "
                                                "in Characters to copy. Copy puts them on the clipboard."))
        top.addWidget(helpb)
        lay.addLayout(top)
        self.grid = Grid()
        self.grid.setMinimumHeight(CELL * 10 + 4)
        self.grid.chosen.connect(self._chosen)
        self.grid.picked.connect(self._append)
        lay.addWidget(self.grid, 1, Qt.AlignHCenter)
        row = QHBoxLayout()
        row.addWidget(QLabel("Characters to copy :"))
        self.to_copy = QLineEdit()
        row.addWidget(self.to_copy, 1)
        sel = QPushButton("&Select")
        sel.clicked.connect(lambda: self.grid.chars and self._append(self.grid.chars[self.grid.current]))
        row.addWidget(sel)
        copy = QPushButton("&Copy")
        copy.clicked.connect(self.copy)
        row.addWidget(copy)
        lay.addLayout(row)
        self.advanced = QCheckBox("Ad&vanced view")
        self.advanced.toggled.connect(self._advanced)
        lay.addWidget(self.advanced)
        self.adv = QFrame()
        al = QGridLayout(self.adv)
        al.setContentsMargins(0, 0, 0, 0)
        al.addWidget(QLabel("Character set :"), 0, 0)
        cs = QComboBox()
        cs.addItem("Unicode")
        cs.setEnabled(False)
        al.addWidget(cs, 0, 1)
        al.addWidget(QLabel("Group by :"), 0, 2)
        self.group_by = QComboBox()
        self.group_by.addItems(["All", "Unicode Subrange"])
        self.group_by.currentIndexChanged.connect(self._group_changed)
        al.addWidget(self.group_by, 0, 3)
        al.addWidget(QLabel("Search for :"), 1, 0)
        self.search = QLineEdit()
        self.search.returnPressed.connect(self.do_search)
        al.addWidget(self.search, 1, 1, 1, 2)
        sb = QPushButton("Sea&rch")
        sb.clicked.connect(self.do_search)
        al.addWidget(sb, 1, 3)
        al.addWidget(QLabel("Go to Unicode :"), 2, 0)
        self.goto = QLineEdit()
        self.goto.setPlaceholderText("e.g. 00E6")
        self.goto.setMaxLength(6)
        self.goto.returnPressed.connect(self.do_goto)
        al.addWidget(self.goto, 2, 1)
        self.blocks = QListWidget()
        self.blocks.addItems([b[2] for b in BLOCKS])
        self.blocks.setVisible(False)
        self.blocks.setMaximumHeight(120)
        self.blocks.currentRowChanged.connect(lambda _r: self.reload())
        al.addWidget(self.blocks, 3, 0, 1, 4)
        self.adv.setVisible(False)
        lay.addWidget(self.adv)
        self.setCentralWidget(central)
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.filter_name = ""
        default = "Liberation Sans"
        if default in QFont().families() or True:
            self.font_box.setCurrentFont(QFont(default))
        self.reload()
        self.resize(self.sizeHint().width(), 470)

    def _advanced(self, on: bool):
        self.adv.setVisible(on)
        if not on:
            self.filter_name = ""
            self.group_by.setCurrentIndex(0)
            self.reload()
        self.adjustSize()

    def _group_changed(self, idx: int):
        self.blocks.setVisible(idx == 1)
        if idx == 1 and self.blocks.currentRow() < 0:
            self.blocks.setCurrentRow(0)
        self.reload()

    def reload(self):
        family = self.font_box.currentFont().family()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            chars = font_chars(family)
        finally:
            QApplication.restoreOverrideCursor()
        if self.advanced.isChecked() and self.group_by.currentIndex() == 1 and self.blocks.currentRow() >= 0:
            lo, hi, _n = BLOCKS[self.blocks.currentRow()]
            chars = [c for c in chars if lo <= c <= hi]
        if self.filter_name:
            words = self.filter_name.upper().split()
            chars = [c for c in chars if all(w in (char_name(c).upper()) for w in words)]
        self.grid.set_chars(family, chars)
        if not chars:
            self.status.showMessage("No characters" if not self.filter_name else
                                    f'No characters match "{self.filter_name}"')

    def do_search(self):
        self.filter_name = self.search.text().strip()
        self.reload()

    def do_goto(self):
        t = self.goto.text().strip().upper().removeprefix("U+")
        try:
            cp = int(t, 16)
        except ValueError:
            return
        if cp in self.grid.chars:
            self.grid.select(self.grid.chars.index(cp))
        else:
            self.status.showMessage(f"U+{cp:04X} is not in {self.grid.family}")

    def _chosen(self, cp: int):
        name = char_name(cp)
        extra = ""
        if 0xA0 <= cp <= 0xFF:
            extra = f"        Keystroke: Alt+0{cp}"
        self.status.showMessage(f"U+{cp:04X}: {name}{extra}")

    def _append(self, cp: int):
        self.to_copy.insert(chr(cp))

    def copy(self):
        text = self.to_copy.text()
        if text:
            QApplication.clipboard().setText(text)


def main(argv=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-charmap")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-charmap")
    w = CharMap()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
