"""Write: Ribbon widgets in the Office 2007 layout (tabs, groups, big and small buttons),
plus small pickers: colour palette, table grid, symbols."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF, QRadialGradient)
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
    scheme: dict | None = None          # set by apply_scheme(); None = Classic look

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
        self.label = QLabel(title)
        self.label.setObjectName("groupLabel")
        self.label.setAlignment(Qt.AlignCenter)
        f = self.label.font()
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        self.label.setFont(f)
        self.label.setStyleSheet("color: palette(dark);")
        outer.addWidget(self.label)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def set_scheme(self, scheme: dict | None):
        self.scheme = scheme
        self.setFrameShape(QFrame.NoFrame if scheme else QFrame.StyledPanel)
        self.label.setStyleSheet(f"color: {scheme['label']}; background: transparent;" if scheme
                                 else "color: palette(dark);")
        self.update()

    def paintEvent(self, e):
        sc = self.scheme
        if not sc:
            return super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -1.5, -1.5)
        body = QPainterPath()
        body.addRoundedRect(r, 3, 3)
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor(sc["g1"]))
        g.setColorAt(1, QColor(sc["g2"]))
        p.fillPath(body, g)
        # label strip along the bottom
        top = self.label.geometry().top() - 2
        p.save()
        p.setClipPath(body)
        sg = QLinearGradient(0, top, 0, r.bottom())
        sg.setColorAt(0, QColor(sc["strip1"]))
        sg.setColorAt(1, QColor(sc["strip2"]))
        p.fillRect(QRectF(r.left(), top, r.width(), r.bottom() - top + 1), sg)
        p.restore()
        # white inner highlight, then the outer border
        p.setPen(QPen(QColor(255, 255, 255, 170), 1))
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 2, 2)
        p.setPen(QPen(QColor(sc["border"]), 1))
        p.drawRoundedRect(r, 3, 3)
        p.end()

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
        self.setObjectName("ribbon")
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
    b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    if menu is not None:
        b.setMenu(menu)
        b.setPopupMode(QToolButton.MenuButtonPopup if action.isCheckable() or action.data() == "split"
                       else QToolButton.InstantPopup)
    b.setMinimumWidth(max(48, b.sizeHint().width()))      # never cut the label ("Pa...e")
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


# ---- Office 2007 colour schemes ------------------------------------------------------------------
SCHEMES = {
    "blue": dict(top="#BFDBFF", pane1="#E9F1FB", pane2="#C8DAF1", border="#8DB2E3",
                 g1="#F4F8FD", g2="#D6E4F5", strip1="#CADDF3", strip2="#B3CCEA", label="#3E6AAA",
                 tab="#15428B", tabsel1="#FFFFFF", tabsel2="#E9F1FB", field="#ABC1DE"),
    "silver": dict(top="#E3E6EB", pane1="#F7F8FA", pane2="#DFE2E7", border="#B4BAC3",
                   g1="#FCFCFD", g2="#E9EBEF", strip1="#E0E3E8", strip2="#CCD1D8", label="#4C535C",
                   tab="#3B3F45", tabsel1="#FFFFFF", tabsel2="#F7F8FA", field="#B4BAC3"),
}
SCHEME_NAMES = {"blue": "Blue", "silver": "Silver", "classic": "Classic"}


def _arrow_png(color: str) -> str:
    """A small down arrow for the combo boxes (style sheets need an image file)."""
    path = Path(tempfile.gettempdir()) / f"classic7-write-arrow-{color.strip('#')}.png"
    if not path.exists():
        pm = QPixmap(7, 4)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygonF([QPointF(0, 0), QPointF(7, 0), QPointF(3.5, 4)]))
        p.end()
        pm.save(str(path))
    return path.as_posix()


def stylesheet(sc: dict) -> str:
    arrow = _arrow_png("#3B3B3B")
    hover = ("border: 1px solid #DBCE99; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
             "stop:0 #FFFDE8, stop:0.4 #FFE9A8, stop:0.41 #FFD867, stop:1 #FFE79F);")
    down = ("border: 1px solid #C2762B; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            "stop:0 #FCD9A4, stop:0.4 #FBBA66, stop:0.41 #F9A03A, stop:1 #FCCD7C);")
    checked = ("border: 1px solid #C2A15A; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
               "stop:0 #FFE4B5, stop:0.4 #FFD38A, stop:0.41 #FFC15C, stop:1 #FFDA8E);")
    return f"""
#ribbonTop {{ background: {sc['top']}; }}
#ribbon::pane {{
    border: 1px solid {sc['border']}; border-radius: 3px; top: -1px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {sc['pane1']}, stop:1 {sc['pane2']});
}}
#ribbon QTabBar::tab {{
    color: {sc['tab']}; padding: 3px 13px 4px 13px; margin: 2px 1px 0 1px;
    border: 1px solid transparent; border-bottom: none;
    border-top-left-radius: 3px; border-top-right-radius: 3px; background: transparent;
}}
#ribbon QTabBar::tab:first {{ margin-left: 6px; }}
#ribbon QTabBar::tab:selected {{
    border-color: {sc['border']};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {sc['tabsel1']}, stop:1 {sc['tabsel2']});
}}
#ribbon QTabBar::tab:hover:!selected {{ background: rgba(255, 255, 255, 110); border-color: {sc['field']}; }}
#ribbonTop QToolButton {{ border: 1px solid transparent; border-radius: 3px; background: transparent;
                          color: #000000; padding: 1px 2px; }}
#ribbonTop QToolButton:hover {{ {hover} }}
#ribbonTop QToolButton:pressed {{ {down} }}
#ribbonTop QToolButton:checked {{ {checked} }}
#ribbonTop QToolButton:checked:hover {{ {down} }}
#ribbonTop QToolButton:disabled {{ color: #8D8D8D; }}
#ribbonTop QToolButton[popupMode="1"] {{ padding-right: 13px; }}
#ribbonTop QToolButton::menu-button {{ border: 1px solid transparent; width: 11px;
                                       border-top-right-radius: 3px; border-bottom-right-radius: 3px; }}
#ribbonTop QToolButton::menu-button:hover {{ {hover} }}
#ribbonTop QToolButton::menu-arrow {{ image: url({arrow}); width: 7px; height: 4px; }}
#ribbonTop QToolButton::menu-indicator {{ image: url({arrow}); width: 7px; height: 4px;
                                          subcontrol-origin: padding; subcontrol-position: bottom right; }}
#ribbonTop QComboBox {{ background: #FFFFFF; border: 1px solid {sc['field']}; border-radius: 2px;
                        padding: 1px 18px 1px 3px; min-height: 17px; color: #000000; }}
#ribbonTop QComboBox:hover, #ribbonTop QComboBox:focus {{ border-color: #DBCE99; }}
#ribbonTop QComboBox::drop-down {{ width: 15px; border: none; }}
#ribbonTop QComboBox::drop-down:hover {{ {hover} }}
#ribbonTop QComboBox::down-arrow {{ image: url({arrow}); width: 7px; height: 4px; }}
#ribbonTop QComboBox QAbstractItemView {{ background: #FFFFFF; border: 1px solid #868686;
                                         selection-background-color: #FFE69F; selection-color: #000000; }}
#ribbonTop QToolButton#orb, #ribbonTop QToolButton#orb:hover, #ribbonTop QToolButton#orb:pressed,
#ribbonTop QToolButton#orb:checked {{ border: none; background: transparent; padding: 0; }}
#ribbonTop QToolButton#orb::menu-indicator {{ image: none; width: 0; height: 0; }}
"""


def apply_scheme(top: QWidget, ribbon: QTabWidget, key: str):
    """Colour the ribbon area: "blue", "silver" or "classic" (the system look)."""
    sc = SCHEMES.get(key)
    top.setObjectName("ribbonTop")
    top.setAttribute(Qt.WA_StyledBackground, True)
    top.setStyleSheet(stylesheet(sc) if sc else
                      "#orb { border: none; padding: 0; } #orb::menu-indicator { image: none; width: 0; }")
    for g in ribbon.findChildren(RibbonGroup):
        g.set_scheme(sc)


def office_orb(size: int = 36) -> QIcon:
    """The round Office button: a glossy blue ball with a W (for Write)."""
    icon = QIcon()
    for state, (c1, c2) in ((QIcon.Normal, ("#7DB4F2", "#1A4F9C")), (QIcon.Active, ("#A5D0FF", "#2B69C4"))):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, size - 2, size - 2)
        g = QRadialGradient(QPointF(size * 0.5, size * 0.32), size * 0.7)
        g.setColorAt(0, QColor(c1))
        g.setColorAt(1, QColor(c2))
        p.setPen(QPen(QColor("#4F6584"), 1))
        p.setBrush(g)
        p.drawEllipse(r)
        gl = QLinearGradient(0, r.top(), 0, r.center().y())
        gl.setColorAt(0, QColor(255, 255, 255, 200))
        gl.setColorAt(1, QColor(255, 255, 255, 30))
        p.setPen(Qt.NoPen)
        p.setBrush(gl)
        p.drawEllipse(QRectF(r.left() + 4, r.top() + 2, r.width() - 8, r.height() * 0.48))
        f = QFont("DejaVu Serif")
        f.setBold(True)
        f.setPixelSize(int(size * 0.5))
        p.setFont(f)
        p.setPen(QColor(0, 0, 0, 100))
        p.drawText(r.translated(1, 2), Qt.AlignCenter, "W")
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r.translated(0, 1), Qt.AlignCenter, "W")
        p.end()
        icon.addPixmap(pm, state)
    return icon
