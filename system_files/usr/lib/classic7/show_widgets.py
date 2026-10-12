"""Show: ribbon pickers (theme colours, galleries) and the slide thumbnail lists."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QColorDialog, QGridLayout, QLabel, QListWidget,
                               QMenu, QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget,
                               QWidgetAction)

import show_model as sm
import show_text as st

STANDARD = ["C00000", "FF0000", "FFC000", "FFFF00", "92D050", "00B050", "00B0F0", "0070C0", "002060", "7030A0"]
THEME_ORDER = ["bg1", "tx1", "bg2", "tx2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]


def _variations(key: str, rgb: str) -> list:
    """Office 2007's five lighter/darker variations under each theme colour."""
    r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    import colorsys
    lum = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[1]
    if lum < 0.04:
        mods = [(50000, 50000), (65000, 35000), (75000, 25000), (85000, 15000), (95000, 5000)]
        return [[["lumMod", m], ["lumOff", o]] for m, o in mods]
    if lum > 0.96:
        return [[["lumMod", m]] for m in (95000, 85000, 75000, 65000, 50000)]
    if lum < 0.2:
        return [[["lumMod", 10000], ["lumOff", 90000]], [["lumMod", 25000], ["lumOff", 75000]],
                [["lumMod", 50000], ["lumOff", 50000]], [["lumMod", 75000]], [["lumMod", 50000]]]
    if lum > 0.8:
        return [[["lumMod", 90000]], [["lumMod", 75000]], [["lumMod", 50000]], [["lumMod", 25000]], [["lumMod", 10000]]]
    return [[["lumMod", 20000], ["lumOff", 80000]], [["lumMod", 40000], ["lumOff", 60000]],
            [["lumMod", 60000], ["lumOff", 40000]], [["lumMod", 75000]], [["lumMod", 50000]]]


class Swatch(QToolButton):
    def __init__(self, color: QColor, tip: str, size=14):
        super().__init__()
        self.setFixedSize(size + 4, size + 4)
        self.setAutoRaise(True)
        self.setToolTip(tip)
        self.color = color
        self._hover = False

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect().adjusted(2, 2, -2, -2)
        p.fillRect(r, self.color)
        p.setPen(QPen(QColor("#E2A933") if self._hover else QColor(0, 0, 0, 60), 2 if self._hover else 1))
        p.drawRect(r.adjusted(0, 0, -1, -1) if not self._hover else r.adjusted(-1, -1, 0, 0))
        p.end()


class ThemeColorMenu(QMenu):
    """Theme Colors (with lighter/darker shades), Standard Colors, extra items, More Colors..."""
    picked = Signal(object)          # a colour dict, or None for "No Fill/No Outline/Automatic"

    def __init__(self, parent, ctx_provider, none_text: str | None = None, extra: list | None = None):
        super().__init__(parent)
        self.ctx_provider = ctx_provider
        self.none_text = none_text
        self.extra = extra or []
        self.aboutToShow.connect(self.build)
        self.build()

    def build(self):
        self.clear()
        ctx = self.ctx_provider()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)
        title = QLabel("Theme Colors")
        title.setStyleSheet("font-weight: bold; background: #DDE7F3; padding: 2px;")
        lay.addWidget(title)
        grid = QGridLayout()
        grid.setSpacing(1)
        for ci, key in enumerate(THEME_ORDER):
            base = sm.scheme(key)
            col = ctx.color(base) if ctx else QColor("#000000")
            b = Swatch(col, key)
            b.clicked.connect(lambda _=False, c=base: self._pick(c))
            grid.addWidget(b, 0, ci)
            hexv = "%02X%02X%02X" % (col.red(), col.green(), col.blue())
            for ri, mods in enumerate(_variations(key, hexv)):
                c = {"scheme": key, "mods": mods}
                b = Swatch(ctx.color(c) if ctx else QColor(), key)
                b.clicked.connect(lambda _=False, c=c: self._pick(c))
                grid.addWidget(b, 2 + ri, ci)
        grid.setRowMinimumHeight(1, 4)
        lay.addLayout(grid)
        title2 = QLabel("Standard Colors")
        title2.setStyleSheet("font-weight: bold; background: #DDE7F3; padding: 2px;")
        lay.addWidget(title2)
        row = QGridLayout()
        row.setSpacing(1)
        for i, hexv in enumerate(STANDARD):
            b = Swatch(QColor("#" + hexv), "#" + hexv)
            b.clicked.connect(lambda _=False, h=hexv: self._pick({"rgb": h}))
            row.addWidget(b, 0, i)
        lay.addLayout(row)
        act = QWidgetAction(self)
        act.setDefaultWidget(w)
        self.addAction(act)
        if self.none_text:
            self.addAction(self.none_text, lambda: self._pick(None))
        self.addAction("More Colors...", self._more)
        for item in self.extra:
            if item is None:
                self.addSeparator()
            elif isinstance(item, QMenu):
                self.addMenu(item)
            else:
                self.addAction(item)

    def _pick(self, c):
        self.close()
        self.picked.emit(c)

    def _more(self):
        col = QColorDialog.getColor(QColor("#4F81BD"), self.parentWidget(), "Colors")
        if col.isValid():
            self.picked.emit({"rgb": "%02X%02X%02X" % (col.red(), col.green(), col.blue())})


class GalleryMenu(QMenu):
    """A menu holding a grid of picture buttons (layouts, shapes, styles, backgrounds)."""
    picked = Signal(object)

    def __init__(self, parent, cols: int = 3, cell: QSize = QSize(96, 72), with_labels: bool = True):
        super().__init__(parent)
        self.cols = cols
        self.cell = cell
        self.with_labels = with_labels
        self.items: list = []           # (key, label, QPixmap|callable, section)
        self.aboutToShow.connect(self.build)

    def set_items(self, items):
        self.items = items

    def build(self):
        self.clear()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        section = object()
        grid = None
        n = 0
        for key, label, pm, sec in (self.items() if callable(self.items) else self.items):
            if sec != section:
                section = sec
                if sec:
                    t = QLabel(sec)
                    t.setStyleSheet("font-weight: bold; background: #DDE7F3; padding: 2px;")
                    lay.addWidget(t)
                grid = QGridLayout()
                grid.setSpacing(2)
                lay.addLayout(grid)
                n = 0
            if callable(pm):
                pm = pm()
            b = QToolButton()
            b.setAutoRaise(True)
            b.setIcon(QIcon(pm))
            b.setIconSize(pm.size() / max(1.0, pm.devicePixelRatio()) if isinstance(pm, QPixmap) else self.cell)
            b.setToolTip(label)
            if self.with_labels:
                b.setText(label)
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setFixedWidth(self.cell.width() + 14)
            b.clicked.connect(lambda _=False, k=key: (self.close(), self.picked.emit(k)))
            grid.addWidget(b, n // self.cols, n % self.cols)
            n += 1
        act = QWidgetAction(self)
        act.setDefaultWidget(w)
        self.addAction(act)
        for a in getattr(self, "extra_actions", []):
            if a is None:
                self.addSeparator()
            else:
                self.addAction(a)


def frame_pixmap(img: QImage, size: QSize | None = None) -> QPixmap:
    pm = QPixmap.fromImage(img)
    out = QPixmap(pm.width() + 2, pm.height() + 2)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap(1, 1, pm)
    p.setPen(QColor("#9AAFC9"))
    p.drawRect(0, 0, out.width() - 1, out.height() - 1)
    p.end()
    return out


# ---- slide thumbnails ----------------------------------------------------------------------------
class ThumbDelegate(QStyledItemDelegate):
    """Slide number on the left, the picture with an orange frame when selected (PowerPoint 2007)."""

    def __init__(self, owner, numbers_left=True):
        super().__init__(owner)
        self.owner = owner
        self.numbers_left = numbers_left

    def sizeHint(self, opt, idx):
        img = idx.data(Qt.DecorationRole)
        if isinstance(img, QPixmap):
            w, h = img.width() / img.devicePixelRatio(), img.height() / img.devicePixelRatio()
        else:
            w, h = self.owner.thumb_width, self.owner.thumb_width * 0.75
        return QSize(int(w + (26 if self.numbers_left else 16)), int(h + (14 if self.numbers_left else 34)))

    def paint(self, p, opt, idx):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = opt.rect
        img = idx.data(Qt.DecorationRole)
        sel = bool(opt.state & QStyle.State_Selected)
        hover = bool(opt.state & QStyle.State_MouseOver)
        num = idx.row() + 1
        hidden = bool(idx.data(Qt.UserRole + 2))
        if isinstance(img, QPixmap):
            w, h = img.width() / img.devicePixelRatio(), img.height() / img.devicePixelRatio()
        else:
            w, h = self.owner.thumb_width, self.owner.thumb_width * 0.75
        if self.numbers_left:
            x = r.left() + 20
            y = r.top() + 7
            f = QFont(p.font())
            f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
            p.setFont(f)
            p.setPen(QColor("#4D4D4D"))
            p.drawText(QRect(r.left(), y, 18, 16), Qt.AlignRight | Qt.AlignTop, str(num))
        else:
            x = r.left() + (r.width() - w) / 2
            y = r.top() + 6
        pic = QRectF(x, y, w, h)
        if sel or hover:
            p.setPen(QPen(QColor("#F29536") if sel else QColor("#FFD07A"), 3 if sel else 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(pic.adjusted(-3, -3, 3, 3))
        if isinstance(img, QPixmap):
            p.drawPixmap(pic.toRect(), img)
        p.setPen(QColor("#8C8C8C"))
        p.drawRect(pic.adjusted(-0.5, -0.5, 0.5, 0.5))
        if hidden:
            p.setPen(QPen(QColor(80, 80, 80, 200), 1.5))
            p.drawLine(pic.topLeft(), pic.bottomRight())
        if not self.numbers_left:
            f = QFont(p.font())
            p.setFont(f)
            p.setPen(QColor("#333333"))
            p.drawText(QRect(int(pic.left()), int(pic.bottom()) + 4, int(pic.width()), 18),
                       Qt.AlignLeft | Qt.AlignVCenter, (f"({num})" if hidden else str(num)))
            t = idx.data(Qt.UserRole + 3)
            if t:
                p.drawText(QRect(int(pic.left()), int(pic.bottom()) + 4, int(pic.width()), 18),
                           Qt.AlignRight | Qt.AlignVCenter, t)
        p.restore()


class SlideList(QListWidget):
    """The Slides tab (one column) and the Slide Sorter (a grid): drag to reorder."""
    moved = Signal(list)           # new order (list of old indexes)
    menuRequested = Signal(QPoint)

    def __init__(self, sorter: bool = False, parent=None):
        super().__init__(parent)
        self.sorter = sorter
        self.thumb_width = 150 if not sorter else 200
        self.setItemDelegate(ThumbDelegate(self, numbers_left=not sorter))
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setMouseTracking(True)
        self.setUniformItemSizes(True)
        if sorter:
            self.setViewMode(QListWidget.IconMode)
            self.setFlow(QListWidget.LeftToRight)
            self.setWrapping(True)
            self.setResizeMode(QListWidget.Adjust)
            self.setMovement(QListWidget.Snap)
            self.setSpacing(12)
            self.setStyleSheet("QListWidget { background: #FFFFFF; }")
        else:
            self.setStyleSheet("QListWidget { background: #F3F6FB; border: none; }")
            self.setSpacing(2)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.menuRequested.emit)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def dropEvent(self, e):
        before = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        super().dropEvent(e)
        after = [self.item(i).data(Qt.UserRole) for i in range(self.count())]
        if before != after:
            self.moved.emit(after)

    def mimeData(self, items):
        md = super().mimeData(items)
        return md if md is not None else QMimeData()


def color_icon(color: QColor, letter: str = "", size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    if letter:
        f = QFont("DejaVu Sans")
        f.setBold(True)
        f.setPixelSize(int(size * 0.62))
        p.setFont(f)
        p.setPen(QColor("#202020"))
        p.drawText(QRect(0, 0, size, size - 4), Qt.AlignCenter, letter)
        p.fillRect(QRect(1, size - 4, size - 2, 4), color)
    else:
        p.fillRect(QRect(2, 2, size - 4, size - 4), color)
        p.setPen(QColor("#707070"))
        p.drawRect(QRect(2, 2, size - 5, size - 5))
    p.end()
    return QIcon(pm)


def fill_icon(color: QColor | None, size: int = 16) -> QIcon:
    """A paint bucket over a colour bar (Shape Fill)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#505050"), 1))
    p.setBrush(QColor("#FFFFFF"))
    p.save()
    p.translate(size * 0.45, size * 0.1)
    p.rotate(45)
    p.drawRect(QRectF(0, 0, size * 0.42, size * 0.42))
    p.restore()
    p.fillRect(QRect(1, size - 4, size - 2, 4), color if color is not None else QColor("#FFFFFF"))
    p.end()
    return QIcon(pm)


def outline_icon(color: QColor | None, size: int = 16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#505050"), 1.2))
    p.drawLine(int(size * 0.2), int(size * 0.75), int(size * 0.75), int(size * 0.1))
    p.fillRect(QRect(1, size - 4, size - 2, 4), color if color is not None else QColor("#FFFFFF"))
    p.end()
    return QIcon(pm)


def ctx_for(pres: sm.Presentation, slide: sm.Slide | None) -> st.TextCtx:
    master = pres.master_of(slide) if slide is not None else pres.master
    return st.TextCtx(master, slide.layout if slide is not None else None, None)
