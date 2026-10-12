"""Write: Ribbon widgets in the Office 2007 layout (tabs, groups, big and small buttons),
plus small pickers: colour palette, table grid, symbols."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QSizePolicy, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget, QWidgetAction)

BIG = 32
SMALL = 16


def text_icon(text: str, size: int = SMALL, color: str = "#000000", bold: bool = True,
              underline: str | None = None, italic: bool = False, strike: bool = False) -> QIcon:
    """A drawn icon for actions the icon theme has no picture for (letters like Word's)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    f = QFont("DejaVu Serif" if italic else "DejaVu Sans")
    f.setPixelSize(int(size * 0.72))
    f.setBold(bold)
    f.setItalic(italic)
    f.setStrikeOut(strike)
    p.setFont(f)
    p.setPen(QColor(color))
    p.drawText(QRect(0, 0, size, size - (3 if underline else 0)), Qt.AlignCenter, text)
    if underline:
        p.fillRect(QRect(1, size - 3, size - 2, 3), QColor(underline))
    p.end()
    return QIcon(pm)


def icon(names: str | list[str], fallback: str = "?", size: int = SMALL, **kw) -> QIcon:
    for n in [names] if isinstance(names, str) else names:
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return text_icon(fallback, size, **kw)


class RibbonGroup(QFrame):
    """A labelled box of controls, like "Clipboard" or "Font"."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Sunken)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(3, 2, 3, 1)
        outer.setSpacing(1)
        self.body = QHBoxLayout()
        self.body.setSpacing(2)
        outer.addLayout(self.body, 1)
        label = QLabel(title)
        label.setAlignment(Qt.AlignCenter)
        f = label.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        label.setFont(f)
        label.setStyleSheet("color: palette(dark);")
        outer.addWidget(label)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def add(self, w: QWidget):
        self.body.addWidget(w)
        return w

    def add_column(self, *rows: list[QWidget]) -> QWidget:
        """Stack rows of small controls (up to three), like Word's Font group."""
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        for row in rows:
            h = QHBoxLayout()
            h.setSpacing(1)
            for w in row:
                h.addWidget(w)
            h.addStretch(1)
            v.addLayout(h)
        v.addStretch(1)
        self.body.addWidget(col)
        return col


class Ribbon(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDocumentMode(False)
        self.setUsesScrollButtons(True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setFixedHeight(122)

    def add_tab(self, title: str) -> QHBoxLayout:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(3, 2, 3, 2)
        lay.setSpacing(3)
        self.addTab(page, title)
        lay.addStretch(1)
        return lay

    @staticmethod
    def group(tab: QHBoxLayout, title: str) -> RibbonGroup:
        g = RibbonGroup(title)
        tab.insertWidget(tab.count() - 1, g)
        return g


def big_button(action: QAction, menu: QMenu | None = None, text: str | None = None) -> QToolButton:
    b = QToolButton()
    b.setDefaultAction(action)
    if text:
        b.setText(text)
    b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    b.setIconSize(QSize(BIG, BIG))
    b.setAutoRaise(True)
    b.setMinimumWidth(48)
    b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    if menu is not None:
        b.setMenu(menu)
        b.setPopupMode(QToolButton.MenuButtonPopup if action.isCheckable() or action.data() == "split"
                       else QToolButton.InstantPopup)
    return b


def small_button(action: QAction, menu: QMenu | None = None, with_text: bool = False,
                 split: bool = False) -> QToolButton:
    b = QToolButton()
    b.setDefaultAction(action)
    b.setIconSize(QSize(SMALL, SMALL))
    b.setAutoRaise(True)
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if with_text else Qt.ToolButtonIconOnly)
    if menu is not None:
        b.setMenu(menu)
        b.setPopupMode(QToolButton.MenuButtonPopup if split else QToolButton.InstantPopup)
    return b


# ---- pickers -----------------------------------------------------------------------------------
WORD_COLORS = [
    # Office 2007 standard colours + a grey ramp
    "#C00000", "#FF0000", "#FFC000", "#FFFF00", "#92D050", "#00B050", "#00B0F0", "#0070C0", "#002060", "#7030A0",
    "#000000", "#404040", "#7F7F7F", "#A5A5A5", "#D8D8D8", "#FFFFFF", "#1F497D", "#4F81BD", "#C0504D", "#9BBB59",
]
HIGHLIGHT_COLORS = ["#FFFF00", "#00FF00", "#00FFFF", "#FF00FF", "#0000FF", "#FF0000", "#000080", "#008080",
                    "#008000", "#800080", "#800000", "#808000", "#808080", "#C0C0C0", "#000000"]


class ColorGrid(QWidget):
    picked = Signal(QColor)

    def __init__(self, colors: list[str], cols: int = 10, none_text: str | None = None):
        super().__init__()
        grid = QGridLayout(self)
        grid.setSpacing(2)
        grid.setContentsMargins(4, 4, 4, 4)
        for i, c in enumerate(colors):
            b = QToolButton()
            b.setFixedSize(18, 18)
            b.setStyleSheet(f"QToolButton {{ background: {c}; border: 1px solid #808080; }}"
                            "QToolButton:hover { border: 2px solid #000080; }")
            b.setToolTip(c)
            b.clicked.connect(lambda _=False, c=c: self.picked.emit(QColor(c)))
            grid.addWidget(b, i // cols, i % cols)
        if none_text:
            nb = QToolButton()
            nb.setText(none_text)
            nb.setAutoRaise(True)
            nb.clicked.connect(lambda: self.picked.emit(QColor()))
            grid.addWidget(nb, (len(colors) - 1) // cols + 1, 0, 1, cols)


def color_menu(parent, colors, cols, on_pick, none_text=None) -> QMenu:
    menu = QMenu(parent)
    grid = ColorGrid(colors, cols, none_text)
    act = QWidgetAction(menu)
    act.setDefaultWidget(grid)
    menu.addAction(act)
    grid.picked.connect(lambda c: (menu.close(), on_pick(c)))
    return menu


class TableGrid(QWidget):
    """Hover over a grid to choose rows x columns, like Word's Insert Table button."""
    picked = Signal(int, int)

    def __init__(self, rows: int = 8, cols: int = 10):
        super().__init__()
        self.rows, self.cols = rows, cols
        self.cell = 16
        self.hover = (0, 0)
        self.setMouseTracking(True)
        self.setFixedSize(cols * self.cell + 9, rows * self.cell + 30)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().window())
        r0, c0 = self.hover
        for r in range(self.rows):
            for c in range(self.cols):
                rect = QRect(4 + c * self.cell, 24 + r * self.cell, self.cell - 2, self.cell - 2)
                p.fillRect(rect, QColor("#FFD27A") if (r < r0 and c < c0) else QColor("#FFFFFF"))
                p.setPen(QPen(QColor("#808080")))
                p.drawRect(rect)
        p.setPen(self.palette().windowText().color())
        p.drawText(QRect(4, 2, self.width() - 8, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{c0}x{r0} Table" if r0 and c0 else "Insert Table")
        p.end()

    def _cell_at(self, pos: QPoint):
        c = (pos.x() - 4) // self.cell + 1
        r = (pos.y() - 24) // self.cell + 1
        if 1 <= r <= self.rows and 1 <= c <= self.cols:
            return r, c
        return 0, 0

    def mouseMoveEvent(self, e):
        self.hover = self._cell_at(e.position().toPoint())
        self.update()

    def mouseReleaseEvent(self, e):
        r, c = self._cell_at(e.position().toPoint())
        if r and c:
            self.picked.emit(r, c)


SYMBOLS = list("©®™€£¥$¢°±×÷½¼¾•–—…§¶«»„“”‘’≈≠≤≥∞√πΩµæøåÆØÅéèäöüß→←↑↓✓✔")


def symbol_menu(parent, on_pick) -> QMenu:
    menu = QMenu(parent)
    w = QWidget()
    grid = QGridLayout(w)
    grid.setSpacing(1)
    grid.setContentsMargins(4, 4, 4, 4)
    for i, ch in enumerate(SYMBOLS):
        b = QToolButton()
        b.setText(ch)
        b.setFixedSize(26, 26)
        b.setAutoRaise(True)
        b.clicked.connect(lambda _=False, ch=ch: (menu.close(), on_pick(ch)))
        grid.addWidget(b, i // 10, i % 10)
    act = QWidgetAction(menu)
    act.setDefaultWidget(w)
    menu.addAction(act)
    return menu
