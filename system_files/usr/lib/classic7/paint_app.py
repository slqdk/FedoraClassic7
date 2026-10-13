"""Paint, as in Windows 7: the Paint menu, Home and View ribbon tabs (Text when typing), the
Clipboard, Image, Tools, Brushes, Shapes, Size and Colors groups, rulers, gridlines, full screen,
status bar with zoom slider. The picture and the tools are in paint_canvas.py."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QIcon, QImage, QImageReader, QKeySequence, QPainter,
                           QPen, QPixmap)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFontComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QMainWindow, QMenu, QMessageBox, QRadioButton, QSlider, QSpinBox, QStatusBar,
                               QToolButton, QVBoxLayout, QWidget)

import accessories as acc
import paint_canvas as pc
import write_ribbon as rb

APP = "Paint"
ICON = ("kolourpaint", "applications-graphics")
PALETTE = ["#000000", "#7f7f7f", "#880015", "#ed1c24", "#ff7f27", "#fff200", "#22b14c", "#00a2e8", "#3f48cc",
           "#a349a4", "#ffffff", "#c3c3c3", "#b97a57", "#ffaec9", "#ffc90e", "#efe4b0", "#b5e61d", "#99d9ea",
           "#7092be", "#c8bfe7"]
SHAPE_NAMES = {"line": "Line", "curve": "Curve", "oval": "Oval", "rect": "Rectangle", "roundrect": "Rounded rectangle",
               "polygon": "Polygon", "triangle": "Triangle", "righttriangle": "Right triangle", "diamond": "Diamond",
               "pentagon": "Pentagon", "hexagon": "Hexagon", "arrow_right": "Right arrow", "arrow_left": "Left arrow",
               "arrow_up": "Up arrow", "arrow_down": "Down arrow", "star4": "Four-point star",
               "star5": "Five-point star", "star6": "Six-point star", "callout_round": "Rounded rectangular callout",
               "callout_oval": "Oval callout", "heart": "Heart", "lightning": "Lightning"}
BRUSH_NAMES = {"brush": "Brush", "calligraphy1": "Calligraphy brush 1", "calligraphy2": "Calligraphy brush 2",
               "airbrush": "Airbrush", "oil": "Oil brush", "crayon": "Crayon", "marker": "Marker",
               "pencil_natural": "Natural pencil", "watercolor": "Watercolor brush"}
READ_FILTER = "All Picture Files (*.bmp *.dib *.jpg *.jpeg *.jpe *.jfif *.gif *.tif *.tiff *.png *.ico *.webp);;" \
              "Bitmap Files (*.bmp *.dib);;JPEG (*.jpg *.jpeg *.jpe *.jfif);;GIF (*.gif);;TIFF (*.tif *.tiff);;" \
              "PNG (*.png);;ICO (*.ico);;All Files (*)"
FORMATS = [("PNG picture", "png"), ("JPEG picture", "jpg"), ("BMP picture", "bmp"), ("GIF picture", "gif"),
           ("TIFF picture", "tif")]


def shape_icon(kind: str) -> QIcon:
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor("#1d3d6b"), 1.2))
    r = QRectF(2, 2, 14, 14)
    if kind == "line":
        p.drawLine(QPointF(3, 15), QPointF(15, 3))
    elif kind == "curve":
        from PySide6.QtGui import QPainterPath
        path = QPainterPath(QPointF(2, 14))
        path.cubicTo(QPointF(6, 0), QPointF(12, 18), QPointF(16, 4))
        p.drawPath(path)
    elif kind == "polygon":
        from PySide6.QtGui import QPolygonF
        p.drawPolygon(QPolygonF([QPointF(3, 4), QPointF(12, 2), QPointF(16, 10), QPointF(8, 16), QPointF(2, 12)]))
    else:
        p.drawPath(pc.shape_path(kind, r))
    p.end()
    return QIcon(pm)


def brush_icon(kind: str) -> QIcon:
    """A sample stroke of each brush, drawn with the real brush code."""
    img = QImage(70, 26, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    doc = pc.Document(70, 26)
    c = pc.Canvas(doc)
    c.tool = "brush"
    c.brush = kind
    c.size_index = 1
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setOpacity({"marker": 0.45, "watercolor": 0.35}.get(kind, 1.0))
    import math
    color = QColor("#1d3d6b")
    pts = [QPointF(6 + i * 1.5, 13 + 7 * math.sin(i / 6)) for i in range(40)]
    for pt in pts:
        c._stamp(p, pt, color)
    p.end()
    c.deleteLater()
    return QIcon(QPixmap.fromImage(img))


def size_icon(px: int) -> QIcon:
    pm = QPixmap(80, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.fillRect(QRect(4, 8 - px // 2, 72, max(1, px)), QColor("black"))
    p.end()
    return QIcon(pm)


def swatch_icon(color: QColor | None, size: int = 16, empty: bool = False) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setPen(QColor("#808080"))
    p.setBrush(color if color is not None and not empty else QColor("#f0f0f0"))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)


class Ruler(QWidget):
    def __init__(self, canvas: pc.Canvas, horizontal: bool):
        super().__init__()
        self.canvas = canvas
        self.horizontal = horizontal
        self.mark: QPoint | None = None
        if horizontal:
            self.setFixedHeight(18)
        else:
            self.setFixedWidth(18)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#f4f6fa"))
        p.setPen(QColor("#9aa8bd"))
        z = self.canvas.zoom
        o = self.canvas.origin()
        offset = (o.x() if self.horizontal else o.y()) + (18 if not self.horizontal else 0) * 0
        length = self.width() if self.horizontal else self.height()
        step = 10
        while step * z < 6:
            step *= 2
        f = self.font()
        f.setPixelSize(9)
        p.setFont(f)
        start = int(-offset / z / step) * step
        v = start
        while True:
            pos = offset + v * z
            if pos > length:
                break
            if pos >= 0:
                big = v % (step * 10) == 0
                mid = v % (step * 5) == 0
                tick = 12 if big else (7 if mid else 4)
                if self.horizontal:
                    p.drawLine(int(pos), self.height() - tick, int(pos), self.height())
                    if big:
                        p.drawText(int(pos) + 2, 9, str(v))
                else:
                    p.drawLine(self.width() - tick, int(pos), self.width(), int(pos))
                    if big:
                        p.save()
                        p.translate(9, int(pos) + 2)
                        p.rotate(90)
                        p.drawText(0, 0, str(v))
                        p.restore()
            v += step
        if self.mark is not None:
            p.setPen(QColor("#d02020"))
            pos = offset + (self.mark.x() if self.horizontal else self.mark.y()) * z
            if self.horizontal:
                p.drawLine(int(pos), 0, int(pos), self.height())
            else:
                p.drawLine(0, int(pos), self.width(), int(pos))


class ResizeDialog(QDialog):
    def __init__(self, parent, size: QSize):
        super().__init__(parent)
        self.setWindowTitle("Resize and Skew")
        self.base = size
        lay = QVBoxLayout(self)
        box = QGroupBox("Resize")
        bl = QGridLayout(box)
        self.pct = QRadioButton("Percentage")
        self.px = QRadioButton("Pixels")
        self.pct.setChecked(True)
        by = QHBoxLayout()
        by.addWidget(QLabel("By:"))
        by.addWidget(self.pct)
        by.addWidget(self.px)
        bl.addLayout(by, 0, 0, 1, 2)
        self.h = QSpinBox()
        self.v = QSpinBox()
        for sp in (self.h, self.v):
            sp.setRange(1, 50000)
            sp.setValue(100)
        bl.addWidget(QLabel("Horizontal:"), 1, 0)
        bl.addWidget(self.h, 1, 1)
        bl.addWidget(QLabel("Vertical:"), 2, 0)
        bl.addWidget(self.v, 2, 1)
        self.keep = QCheckBox("Maintain aspect ratio")
        self.keep.setChecked(True)
        bl.addWidget(self.keep, 3, 0, 1, 2)
        lay.addWidget(box)
        box2 = QGroupBox("Skew (Degrees)")
        sl = QGridLayout(box2)
        self.sh = QSpinBox()
        self.sv = QSpinBox()
        for sp in (self.sh, self.sv):
            sp.setRange(-89, 89)
        sl.addWidget(QLabel("Horizontal:"), 0, 0)
        sl.addWidget(self.sh, 0, 1)
        sl.addWidget(QLabel("Vertical:"), 1, 0)
        sl.addWidget(self.sv, 1, 1)
        lay.addWidget(box2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._sync = False
        self.h.valueChanged.connect(lambda v: self._keep("h", v))
        self.v.valueChanged.connect(lambda v: self._keep("v", v))
        self.px.toggled.connect(self._mode)

    def _mode(self, pixels: bool):
        self._sync = True
        if pixels:
            self.h.setValue(self.base.width())
            self.v.setValue(self.base.height())
        else:
            self.h.setValue(100)
            self.v.setValue(100)
        self._sync = False

    def _keep(self, which: str, v: int):
        if self._sync or not self.keep.isChecked():
            return
        self._sync = True
        if self.pct.isChecked():
            (self.v if which == "h" else self.h).setValue(v)
        else:
            ratio = self.base.height() / max(1, self.base.width())
            if which == "h":
                self.v.setValue(max(1, round(v * ratio)))
            else:
                self.h.setValue(max(1, round(v / ratio)))
        self._sync = False

    def factors(self) -> tuple[float, float]:
        if self.pct.isChecked():
            return self.h.value() / 100, self.v.value() / 100
        return self.h.value() / max(1, self.base.width()), self.v.value() / max(1, self.base.height())


class PropertiesDialog(QDialog):
    def __init__(self, parent, doc: pc.Document):
        super().__init__(parent)
        self.setWindowTitle("Image Properties")
        lay = QVBoxLayout(self)
        attrs = QGroupBox("File attributes")
        al = QFormLayout(attrs)
        saved, size = "Not Available", "Not Available"
        if doc.path and Path(doc.path).exists():
            st = Path(doc.path).stat()
            saved = time.strftime("%d-%m-%Y %H:%M", time.localtime(st.st_mtime))
            size = f"{st.st_size:,} bytes"
        al.addRow("Last Saved:", QLabel(saved))
        al.addRow("Size on disk:", QLabel(size))
        al.addRow("Resolution:", QLabel("96 DPI"))
        lay.addWidget(attrs)
        units = QGroupBox("Units")
        ul = QHBoxLayout(units)
        self.inches = QRadioButton("Inches")
        self.cm = QRadioButton("Centimeters")
        self.pixels = QRadioButton("Pixels")
        self.pixels.setChecked(True)
        for b in (self.inches, self.cm, self.pixels):
            ul.addWidget(b)
            b.toggled.connect(self._units)
        lay.addWidget(units)
        dims = QHBoxLayout()
        self.w = QSpinBox()
        self.h = QSpinBox()
        for sp in (self.w, self.h):
            sp.setRange(1, 100000)
        self.w.setValue(doc.image.width())
        self.h.setValue(doc.image.height())
        dims.addWidget(QLabel("Width:"))
        dims.addWidget(self.w)
        dims.addWidget(QLabel("Height:"))
        dims.addWidget(self.h)
        lay.addLayout(dims)
        self.px_w, self.px_h = doc.image.width(), doc.image.height()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _units(self):
        # the spin boxes always edit pixels; the other units are shown as a hint
        if self.inches.isChecked():
            self.setToolTip(f"{self.w.value() / 96:.2f} x {self.h.value() / 96:.2f} inches")
        elif self.cm.isChecked():
            self.setToolTip(f"{self.w.value() / 96 * 2.54:.2f} x {self.h.value() / 96 * 2.54:.2f} cm")

    def size(self) -> QSize:
        return QSize(self.w.value(), self.h.value())


class FullScreen(QWidget):
    def __init__(self, img: QImage):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.img = img
        self.setCursor(Qt.BlankCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        size = self.img.size()
        if size.width() > self.width() or size.height() > self.height():
            size = size.scaled(self.size(), Qt.KeepAspectRatio)
        r = QRect(QPoint(0, 0), size)
        r.moveCenter(self.rect().center())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(r, self.img)

    def keyPressEvent(self, _e):
        self.close()

    def mousePressEvent(self, _e):
        self.close()


class PaintWindow(QMainWindow):
    def __init__(self, path: str | None = None):
        super().__init__()
        self.settings = QSettings("Classic7", "Paint")
        self.setWindowIcon(acc.icon(*ICON))
        self.doc = pc.Document()
        self.canvas = pc.Canvas(self.doc)
        self.custom_colors: list[str] = list(self.settings.value("custom_colors", []) or [])[:10]
        self.prev_tool = "pencil"
        self.active_color = 1
        self.fullscreen_view: FullScreen | None = None
        self._actions()
        self._ribbon()
        central = QWidget()
        grid = QGridLayout(central)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        self.hruler = Ruler(self.canvas, True)
        self.vruler = Ruler(self.canvas, False)
        corner = QWidget()
        corner.setFixedSize(18, 18)
        corner.setStyleSheet("background: #f4f6fa;")
        self.corner = corner
        grid.addWidget(corner, 0, 0)
        grid.addWidget(self.hruler, 0, 1)
        grid.addWidget(self.vruler, 1, 0)
        grid.addWidget(self.canvas, 1, 1)
        self.setCentralWidget(central)
        self._statusbar()
        self.canvas.changed.connect(self._changed)
        self.canvas.cursorMoved.connect(self._cursor)
        self.canvas.selectionChanged.connect(self._selection)
        self.canvas.zoomChanged.connect(self._zoom_changed)
        self.canvas.colorPicked.connect(self._picked)
        self.canvas.toolDone.connect(lambda _t: self.set_tool(self.prev_tool))
        self.canvas.sizeChanged.connect(self._update_status)
        self.canvas.horizontalScrollBar().valueChanged.connect(lambda _v: self.hruler.update())
        self.canvas.verticalScrollBar().valueChanged.connect(lambda _v: self.vruler.update())
        self.show_rulers(self.settings.value("rulers", False, bool))
        self.statusBar().setVisible(self.settings.value("statusbar", True, bool))
        self.a_status.setChecked(self.statusBar().isVisible())
        self.setAcceptDrops(True)
        self.resize(self.settings.value("size", QSize(1000, 720)))
        self.set_tool("pencil")
        self._update_colors()
        if path:
            self.open_path(path)
        self._title()
        self._update_status()

    # ---- actions ------------------------------------------------------------------------------
    def _act(self, text, slot, keys=None, icon=None, fallback="", checkable=False):
        a = QAction(text, self)
        if icon or fallback:
            a.setIcon(rb.icon(icon or [], fallback or text[:1]))
        if keys:
            a.setShortcuts([QKeySequence(k) for k in (keys if isinstance(keys, list) else [keys])])
        a.setCheckable(checkable)
        a.triggered.connect(slot if not checkable else (lambda on, f=slot: f(on)))
        self.addAction(a)
        return a

    def _actions(self):
        A = self._act
        self.a_new = A("&New", self.new, "Ctrl+N", ["document-new"])
        self.a_open = A("&Open", self.open_dialog, "Ctrl+O", ["document-open"])
        self.a_save = A("&Save", self.save, "Ctrl+S", ["document-save"])
        self.a_save_as = A("Save &as", self.save_as, "F12", ["document-save-as"])
        self.a_print = A("&Print", self.print_, "Ctrl+P", ["document-print"])
        self.a_undo = A("Undo", self.undo, "Ctrl+Z", ["edit-undo"])
        self.a_redo = A("Redo", self.redo, "Ctrl+Y", ["edit-redo"])
        self.a_paste = A("Paste", self.paste, "Ctrl+V", ["edit-paste"])
        self.a_cut = A("Cut", self.cut, "Ctrl+X", ["edit-cut"])
        self.a_copy = A("Copy", self.copy, "Ctrl+C", ["edit-copy"])
        self.a_select_all = A("Select all", self.canvas.select_all, "Ctrl+A", ["edit-select-all"])
        self.a_delete = A("Delete", self.canvas.delete_selection, "Del", ["edit-delete"])
        self.a_crop = A("Crop", self.canvas.crop, "Ctrl+Shift+X", ["transform-crop"])
        self.a_resize = A("Resize", self.resize_dialog, "Ctrl+W", ["transform-scale"])
        self.a_props = A("Properties", self.properties, "Ctrl+E", ["document-properties"])
        self.a_zoom_in = A("Zoom in", lambda: self.canvas.set_zoom(self._next_zoom(1)), ["Ctrl+PgUp", "Ctrl++"],
                           ["zoom-in"])
        self.a_zoom_out = A("Zoom out", lambda: self.canvas.set_zoom(self._next_zoom(-1)), ["Ctrl+PgDown", "Ctrl+-"],
                            ["zoom-out"])
        self.a_zoom_100 = A("100%", lambda: self.canvas.set_zoom(1.0), None, ["zoom-original"])
        self.a_rulers = A("Rulers", self.show_rulers, "Ctrl+R", checkable=True)
        self.a_grid = A("Gridlines", self.show_grid, "Ctrl+G", checkable=True)
        self.a_status = A("Status bar", self.show_status, checkable=True)
        self.a_full = A("Full screen", self.full_screen, "F11", ["view-fullscreen"])
        self.a_invert = A("Invert color", self.canvas.invert_colors, "Ctrl+Shift+I")
        self.a_transparent = A("Transparent selection", self._transparent, checkable=True)

    def _next_zoom(self, direction: int) -> float:
        steps = [0.125, 0.25, 0.5, 1, 2, 3, 4, 5, 6, 7, 8]
        z = self.canvas.zoom
        if direction > 0:
            return next((s for s in steps if s > z + 1e-6), steps[-1])
        return next((s for s in reversed(steps) if s < z - 1e-6), steps[0])

    # ---- ribbon -------------------------------------------------------------------------------
    def _ribbon(self):
        top = QWidget()
        v = QVBoxLayout(top)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        qat = QHBoxLayout()
        qat.setContentsMargins(2, 2, 2, 0)
        menu_btn = QToolButton()
        menu_btn.setObjectName("orb")
        menu_btn.setIcon(rb.office_orb(30, "P"))
        menu_btn.setIconSize(QSize(30, 30))
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu_btn.setToolTip("Paint\nNew, Open, Save, Print, Set as desktop background")
        menu_btn.setMenu(self._paint_menu())
        menu_btn.setAutoRaise(True)
        qat.addWidget(menu_btn)
        qat.addSpacing(4)
        for a in (self.a_save, self.a_undo, self.a_redo):
            qat.addWidget(rb.small_button(a))
        qat.addStretch(1)
        v.addLayout(qat)
        r = rb.Ribbon()
        self.ribbon = r
        self._tab_home(r)
        self._tab_view(r)
        self._tab_text(r)
        v.addWidget(r)
        rb.apply_scheme(top, r, self.settings.value("ribbon/scheme", "blue"))
        self.setMenuWidget(top)

    def _paint_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction(self.a_new)
        m.addAction(self.a_open)
        m.addAction(self.a_save)
        save_as = m.addMenu(rb.icon(["document-save-as"], "S"), "Save as")
        for label, ext in FORMATS:
            save_as.addAction(label, lambda e=ext: self.save_as(e))
        save_as.addAction("Other formats", lambda: self.save_as(None))
        pm = m.addMenu(rb.icon(["document-print"], "P"), "Print")
        pm.addAction("Print", self.print_)
        pm.addAction("Print preview", self.print_preview)
        m.addAction(rb.icon(["mail-send"], "@"), "Send in e-mail", self.email)
        bg = m.addMenu(rb.icon(["preferences-desktop-wallpaper"], "D"), "Set as desktop background")
        for label, mode in (("Fill", "preserveAspectCrop"), ("Tile", "tile"), ("Center", "pad")):
            bg.addAction(label, lambda md=mode: self.set_wallpaper(md))
        m.addSeparator()
        m.addAction(self.a_props)
        m.addAction(rb.icon(["help-about"], "?"), "About Paint", lambda: acc.about(self, APP, ICON))
        m.addSeparator()
        m.addAction(rb.icon(["application-exit"], "X"), "Exit", self.close)
        return m

    def _tool_button(self, key: str, text: str, icons: list[str]) -> QToolButton:
        a = QAction(rb.icon(icons, text[0]), text, self)
        a.setCheckable(True)
        a.triggered.connect(lambda _c=False, k=key: self.set_tool(k))
        self.tool_group.addAction(a)
        self.tool_actions[key] = a
        return rb.small_button(a)

    def _tab_home(self, r):
        tab = r.add_tab("Home")
        g = r.group(tab, "Clipboard")
        g.add(rb.big_button(self.a_paste))
        g.add_column([rb.small_button(self.a_cut, with_text=True)], [rb.small_button(self.a_copy, with_text=True)])
        g = r.group(tab, "Image")
        sel_menu = QMenu(self)
        self.sel_group = QActionGroup(self)
        for text, mode in (("Rectangular selection", "select"), ("Free-form selection", "freeselect")):
            a = sel_menu.addAction(text, lambda m=mode: self.set_tool(m))
            a.setCheckable(True)
            self.sel_group.addAction(a)
            if mode == "select":
                self.a_sel_rect = a
        sel_menu.addSeparator()
        sel_menu.addAction(self.a_select_all)
        sel_menu.addAction(self.a_invert)
        sel_menu.addAction(self.a_delete)
        sel_menu.addAction(self.a_transparent)
        sel = QAction(rb.icon(["select-rectangular", "edit-select"], "S", size=rb.BIG), "Select", self)
        sel.setData("split")
        sel.triggered.connect(lambda: self.set_tool(self.settings.value("select_mode", "select")))
        g.add(rb.big_button(sel, sel_menu))
        rot = QMenu(self)
        rot.addAction(rb.icon(["object-rotate-right"], "R"), "Rotate right 90°",
                      lambda: self.canvas.transform("rotate90"))
        rot.addAction(rb.icon(["object-rotate-left"], "L"), "Rotate left 90°",
                      lambda: self.canvas.transform("rotate270"))
        rot.addAction("Rotate 180°", lambda: self.canvas.transform("rotate180"))
        rot.addAction(rb.icon(["object-flip-vertical"], "V"), "Flip vertical", lambda: self.canvas.transform("flipv"))
        rot.addAction(rb.icon(["object-flip-horizontal"], "H"), "Flip horizontal",
                      lambda: self.canvas.transform("fliph"))
        rotate = QAction(rb.icon(["object-rotate-right"], "R"), "Rotate", self)
        g.add_column([rb.small_button(self.a_crop, with_text=True)], [rb.small_button(self.a_resize, with_text=True)],
                     [rb.small_button(rotate, rot, with_text=True)])
        g = r.group(tab, "Tools")
        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[str, QAction] = {}
        g.add_column([self._tool_button("pencil", "Pencil", ["draw-freehand"]),
                      self._tool_button("fill", "Fill with color", ["color-fill", "fill-color"]),
                      self._tool_button("text", "Text", ["draw-text"])],
                     [self._tool_button("eraser", "Eraser", ["draw-eraser"]),
                      self._tool_button("picker", "Color picker", ["color-picker"]),
                      self._tool_button("magnifier", "Magnifier", ["zoom-in"])])
        for key in ("select", "freeselect", "brush", "shape"):
            a = QAction(key, self)
            a.setCheckable(True)
            self.tool_group.addAction(a)
            self.tool_actions[key] = a
        g = r.group(tab, "Brushes")
        bm = QMenu(self)
        for key, name in pc_brushes():
            bm.addAction(brush_icon(key), name, lambda k=key: self.set_brush(k))
        self.brush_btn_action = QAction(brush_icon("brush"), "Brushes", self)
        self.brush_btn_action.setData("split")
        self.brush_btn_action.triggered.connect(lambda: self.set_tool("brush"))
        g.add(rb.big_button(self.brush_btn_action, bm))
        g = r.group(tab, "Shapes")
        gallery = QWidget()
        gl = QGridLayout(gallery)
        gl.setContentsMargins(0, 0, 0, 0)
        gl.setSpacing(0)
        self.shape_buttons: dict[str, QToolButton] = {}
        for i, key in enumerate(pc.SHAPES):
            b = QToolButton()
            b.setIcon(shape_icon(key))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(SHAPE_NAMES[key])
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setFixedSize(22, 22)
            b.clicked.connect(lambda _c=False, k=key: self.set_shape(k))
            gl.addWidget(b, i // 8, i % 8)
            self.shape_buttons[key] = b
        g.add(gallery)
        outline = QMenu(self)
        self.outline_group = QActionGroup(self)
        for text, val in (("No outline", "none"), ("Solid color", "solid")):
            a = outline.addAction(text, lambda v=val: setattr(self.canvas, "outline", v))
            a.setCheckable(True)
            a.setChecked(val == "solid")
            self.outline_group.addAction(a)
        fill = QMenu(self)
        self.fill_group = QActionGroup(self)
        for text, val in (("No fill", "none"), ("Solid color", "solid")):
            a = fill.addAction(text, lambda v=val: setattr(self.canvas, "fill", v))
            a.setCheckable(True)
            a.setChecked(val == "none")
            self.fill_group.addAction(a)
        g.add_column([rb.small_button(QAction(rb.icon(["format-stroke-color"], "O"), "Outline", self), outline,
                                      with_text=True)],
                     [rb.small_button(QAction(rb.icon(["format-fill-color"], "F"), "Fill", self), fill,
                                      with_text=True)])
        g = r.group(tab, "Size")
        sm = QMenu(self)
        for i in range(4):
            sm.addAction(size_icon([1, 3, 5, 8][i]), "", lambda idx=i: self.set_size(idx))
        self.size_action = QAction(size_icon(3), "Size", self)
        g.add(rb.big_button(self.size_action, sm))
        g = r.group(tab, "Colors")
        self.color1_btn = QToolButton()
        self.color1_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.color1_btn.setText("Color\n1")
        self.color1_btn.setIconSize(QSize(26, 26))
        self.color1_btn.setCheckable(True)
        self.color1_btn.setAutoRaise(True)
        self.color1_btn.clicked.connect(lambda: self._active_color(1))
        self.color2_btn = QToolButton()
        self.color2_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.color2_btn.setText("Color\n2")
        self.color2_btn.setIconSize(QSize(20, 20))
        self.color2_btn.setCheckable(True)
        self.color2_btn.setAutoRaise(True)
        self.color2_btn.clicked.connect(lambda: self._active_color(2))
        g.add(self.color1_btn)
        g.add(self.color2_btn)
        pal = QWidget()
        pl = QGridLayout(pal)
        pl.setContentsMargins(0, 2, 0, 2)
        pl.setSpacing(2)
        self.custom_buttons: list[QToolButton] = []
        for i, c in enumerate(PALETTE + [None] * 10):
            b = QToolButton()
            b.setFixedSize(18, 18)
            b.setAutoRaise(True)
            if c is None:
                self.custom_buttons.append(b)
                b.clicked.connect(lambda _c=False, idx=len(self.custom_buttons) - 1: self._custom_clicked(idx))
            else:
                b.setIcon(swatch_icon(QColor(c), 14))
                b.clicked.connect(lambda _c=False, col=c: self._set_active(QColor(col)))
            b.setIconSize(QSize(14, 14))
            pl.addWidget(b, i // 10, i % 10)
        self._refresh_custom()
        g.add(pal)
        edit = QAction(rb.icon(["color-management", "preferences-desktop-color"], "E", size=rb.BIG),
                       "Edit\ncolors", self)
        edit.triggered.connect(self.edit_colors)
        g.add(rb.big_button(edit))

    def _tab_view(self, r):
        tab = r.add_tab("View")
        g = r.group(tab, "Zoom")
        for a in (self.a_zoom_in, self.a_zoom_out, self.a_zoom_100):
            a.setIcon(rb.icon([{"Zoom in": "zoom-in", "Zoom out": "zoom-out", "100%": "zoom-original"}[a.text()]],
                              a.text()[0], size=rb.BIG))
            g.add(rb.big_button(a))
        g = r.group(tab, "Show or hide")
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(4, 2, 4, 2)
        for a in (self.a_rulers, self.a_grid, self.a_status):
            cb = QCheckBox(a.text())
            cb.setChecked(a.isChecked())
            cb.toggled.connect(a.trigger)
            a.toggled.connect(cb.setChecked)
            cl.addWidget(cb)
        g.add(col)
        g = r.group(tab, "Display")
        self.a_full.setIcon(rb.icon(["view-fullscreen"], "F", size=rb.BIG))
        g.add(rb.big_button(self.a_full))

    def _tab_text(self, r):
        self.text_tab_index = r.count()
        tab = r.add_tab("Text")
        self.text_tab_page = r.widget(self.text_tab_index)
        g = r.group(tab, "Font")
        self.font_box = QFontComboBox()
        self.font_box.setMaximumWidth(170)
        self.font_box.setCurrentFont(QFont("Liberation Sans"))
        self.font_box.currentFontChanged.connect(lambda _f: self._text_font())
        self.font_size = QComboBox()
        self.font_size.setEditable(True)
        self.font_size.addItems(["8", "9", "10", "11", "12", "14", "16", "18", "20", "22", "24", "26", "28", "36",
                                 "48", "72"])
        self.font_size.setCurrentText("11")
        self.font_size.setFixedWidth(60)
        self.font_size.currentTextChanged.connect(lambda _t: self._text_font())
        self.text_style: dict[str, QAction] = {}
        buttons = []
        for key, text, icon in (("bold", "Bold", "format-text-bold"), ("italic", "Italic", "format-text-italic"),
                                ("underline", "Underline", "format-text-underline"),
                                ("strike", "Strikethrough", "format-text-strikethrough")):
            a = QAction(rb.icon([icon], text[0]), text, self)
            a.setCheckable(True)
            a.toggled.connect(lambda _on: self._text_font())
            self.text_style[key] = a
            buttons.append(rb.small_button(a))
        g.add_column([self.font_box, self.font_size], buttons)
        g = r.group(tab, "Background")
        col = QWidget()
        cl = QVBoxLayout(col)
        cl.setContentsMargins(4, 2, 4, 2)
        self.opaque = QRadioButton("Opaque")
        self.transparent = QRadioButton("Transparent")
        self.transparent.setChecked(True)
        self.opaque.toggled.connect(self._text_bg)
        cl.addWidget(self.opaque)
        cl.addWidget(self.transparent)
        g.add(col)
        r.setTabVisible(self.text_tab_index, False)

    def _text_font(self):
        f = QFont(self.font_box.currentFont())
        try:
            f.setPointSizeF(float(self.font_size.currentText().replace(",", ".")))
        except ValueError:
            f.setPointSize(11)
        f.setBold(self.text_style["bold"].isChecked())
        f.setItalic(self.text_style["italic"].isChecked())
        f.setUnderline(self.text_style["underline"].isChecked())
        f.setStrikeOut(self.text_style["strike"].isChecked())
        self.canvas.set_text_font(f)

    def _text_bg(self, opaque: bool):
        self.canvas.text_opaque = opaque
        self.canvas._style_text()

    # ---- status bar ---------------------------------------------------------------------------
    def _statusbar(self):
        sb = QStatusBar()
        self.pos_label = QLabel()
        self.sel_label = QLabel()
        self.size_label = QLabel()
        self.file_label = QLabel()
        for lab, w in ((self.pos_label, 120), (self.sel_label, 120), (self.size_label, 130), (self.file_label, 120)):
            lab.setMinimumWidth(w)
            sb.addWidget(lab)
        self.zoom_label = QLabel("100%")
        sb.addPermanentWidget(self.zoom_label)
        minus = QToolButton()
        minus.setText("−")
        minus.setAutoRaise(True)
        minus.clicked.connect(self.a_zoom_out.trigger)
        sb.addPermanentWidget(minus)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, 100)
        self.zoom_slider.setFixedWidth(120)
        self.zoom_slider.valueChanged.connect(self._slider_zoom)
        sb.addPermanentWidget(self.zoom_slider)
        plus = QToolButton()
        plus.setText("+")
        plus.setAutoRaise(True)
        plus.clicked.connect(self.a_zoom_in.trigger)
        sb.addPermanentWidget(plus)
        self.setStatusBar(sb)
        self._zoom_changed(1.0)

    @staticmethod
    def _zoom_to_slider(z: float) -> int:
        import math
        return int(round((math.log2(z) + 3) / 6 * 100))

    def _slider_zoom(self, v: int):
        z = 2 ** (v / 100 * 6 - 3)
        if abs(self._zoom_to_slider(self.canvas.zoom) - v) > 0:
            self.canvas.set_zoom(z)

    def _zoom_changed(self, z: float):
        self.zoom_label.setText(f"{round(z * 100)}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(self._zoom_to_slider(z))
        self.zoom_slider.blockSignals(False)
        self.hruler.update() if hasattr(self, "hruler") else None
        self.vruler.update() if hasattr(self, "vruler") else None

    def _cursor(self, pt):
        self.pos_label.setText(f"✚  {pt.x()}, {pt.y()}px" if pt is not None else "")
        self.hruler.mark = pt
        self.vruler.mark = pt
        self.hruler.update()
        self.vruler.update()

    def _selection(self, r):
        self.sel_label.setText(f"⬚  {r.width()} × {r.height()}px" if r is not None else "")

    def _update_status(self):
        img = self.doc.image
        self.size_label.setText(f"▣  {img.width()} × {img.height()}px")
        if self.doc.path and Path(self.doc.path).exists():
            size = Path(self.doc.path).stat().st_size
            self.file_label.setText(f"Size: {size / 1024:.1f}KB")
        else:
            self.file_label.setText("")

    def _changed(self):
        self._title()
        self._update_status()

    def _title(self):
        name = Path(self.doc.path).name if self.doc.path else "Untitled"
        self.setWindowTitle(f"{name} - {APP}")

    # ---- tools and colours --------------------------------------------------------------------
    def set_tool(self, key: str):
        c = self.canvas
        if key != "text":
            c.commit_text()
        if key not in ("select", "freeselect"):
            c.commit_floating()
            c.clear_selection()
        if key not in ("picker", "magnifier") and c.tool not in ("picker", "magnifier"):
            self.prev_tool = c.tool
        if key in ("picker",):
            self.prev_tool = c.tool if c.tool != "picker" else self.prev_tool
        c.tool = key
        if key in ("select", "freeselect"):
            self.settings.setValue("select_mode", key)
        for k, a in self.tool_actions.items():
            a.setChecked(k == key)
        for k, b in self.shape_buttons.items():
            b.setChecked(key == "shape" and k == c.shape)
        self.ribbon.setTabVisible(self.text_tab_index, key == "text")
        if key == "text":
            self._text_font()

    def set_brush(self, key: str):
        self.canvas.brush = key
        self.brush_btn_action.setIcon(brush_icon(key))
        self.set_tool("brush")

    def set_shape(self, key: str):
        self.canvas.shape = key
        self.set_tool("shape")

    def set_size(self, idx: int):
        self.canvas.size_index = idx
        self.size_action.setIcon(size_icon([1, 3, 5, 8][idx]))

    def _active_color(self, which: int):
        self.active_color = which
        self._update_colors()

    def _set_active(self, color: QColor):
        if self.active_color == 1:
            self.canvas.color1 = color
        else:
            self.canvas.color2 = color
        self._update_colors()
        self.canvas._style_text()

    def _picked(self, which: int, color: QColor):
        if which == 1:
            self.canvas.color1 = color
        else:
            self.canvas.color2 = color
        self._update_colors()

    def _update_colors(self):
        self.color1_btn.setIcon(swatch_icon(self.canvas.color1, 26))
        self.color2_btn.setIcon(swatch_icon(self.canvas.color2, 20))
        self.color1_btn.setChecked(self.active_color == 1)
        self.color2_btn.setChecked(self.active_color == 2)

    def _refresh_custom(self):
        for i, b in enumerate(self.custom_buttons):
            if i < len(self.custom_colors):
                b.setIcon(swatch_icon(QColor(self.custom_colors[i]), 14))
                b.setEnabled(True)
            else:
                b.setIcon(swatch_icon(None, 14, empty=True))
                b.setEnabled(False)

    def _custom_clicked(self, idx: int):
        if idx < len(self.custom_colors):
            self._set_active(QColor(self.custom_colors[idx]))

    def edit_colors(self):
        current = self.canvas.color1 if self.active_color == 1 else self.canvas.color2
        c = QColorDialog.getColor(current, self, "Edit Colors")
        if c.isValid():
            self._set_active(c)
            if c.name() not in self.custom_colors:
                self.custom_colors = ([c.name()] + self.custom_colors)[:10]
                self.settings.setValue("custom_colors", self.custom_colors)
                self._refresh_custom()

    def _transparent(self, on: bool):
        self.canvas.transparent_select = on
        self.canvas.viewport().update()

    # ---- view ----------------------------------------------------------------------------------
    def show_rulers(self, on: bool):
        self.hruler.setVisible(on)
        self.vruler.setVisible(on)
        self.corner.setVisible(on)
        self.a_rulers.setChecked(on)
        self.settings.setValue("rulers", on)

    def show_grid(self, on: bool):
        self.canvas.grid = on
        self.canvas.viewport().update()

    def show_status(self, on: bool):
        self.statusBar().setVisible(on)
        self.settings.setValue("statusbar", on)

    def full_screen(self):
        self.canvas.commit_all()
        self.fullscreen_view = FullScreen(self.doc.image.copy())
        self.fullscreen_view.showFullScreen()

    # ---- clipboard -------------------------------------------------------------------------------
    def copy(self):
        img = self.canvas.selected_image()
        if img is not None:
            QApplication.clipboard().setImage(img)

    def cut(self):
        img = self.canvas.selected_image()
        if img is not None:
            QApplication.clipboard().setImage(img)
            self.canvas.delete_selection()

    def paste(self):
        img = QApplication.clipboard().image()
        if img.isNull():
            return
        doc = self.doc.image
        if img.width() > doc.width() or img.height() > doc.height():
            r = QMessageBox.question(self, APP, "The image you are pasting is larger than the canvas.\n"
                                                "Would you like the canvas to be enlarged?",
                                     QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return
            if r == QMessageBox.Yes:
                self.canvas.resize_canvas(max(img.width(), doc.width()), max(img.height(), doc.height()))
        self.set_tool("select")
        self.canvas.paste_image(img, QPoint(0, 0))

    def undo(self):
        c = self.canvas
        if c.text_edit is not None:
            c.text_edit.deleteLater()
            c.text_edit = None
            return
        if c.cancel_floating():
            self._changed()
            return
        if c.preview is not None:
            c.preview = None
            c.poly_pts = []
            c.curve_stage = 0
            c.viewport().update()
            return
        if self.doc.undo():
            c.update_scroll()
            self._changed()

    def redo(self):
        if self.doc.redo():
            self.canvas.update_scroll()
            self._changed()

    # ---- image ---------------------------------------------------------------------------------
    def resize_dialog(self):
        c = self.canvas
        base = c.float_rect.size().toSize() if c.float_rect is not None else \
            (c.selection.size() if c.selection is not None else self.doc.image.size())
        dlg = ResizeDialog(self, base)
        if dlg.exec() != QDialog.Accepted:
            return
        sx, sy = dlg.factors()
        if abs(sx - 1) > 1e-6 or abs(sy - 1) > 1e-6:
            c.transform("resize", sx, sy)
        if dlg.sh.value() or dlg.sv.value():
            c.transform("skew", skew_x=dlg.sh.value(), skew_y=dlg.sv.value())

    def properties(self):
        dlg = PropertiesDialog(self, self.doc)
        if dlg.exec() == QDialog.Accepted and dlg.size() != self.doc.image.size():
            self.canvas.commit_all()
            self.canvas.resize_canvas(dlg.size().width(), dlg.size().height())

    # ---- files ---------------------------------------------------------------------------------
    def maybe_save(self) -> bool:
        self.canvas.commit_all()
        if not self.doc.modified:
            return True
        name = Path(self.doc.path).name if self.doc.path else "Untitled"
        box = QMessageBox(QMessageBox.NoIcon, APP, f"Do you want to save changes to {name}?", parent=self)
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
        self.doc.load(QImage(self.settings.value("new_w", 1024, int), self.settings.value("new_h", 768, int),
                             QImage.Format_RGB32), None)
        self.doc.image.fill(QColor("white"))
        self.canvas.update_scroll()
        self._changed()

    def open_dialog(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open", self.settings.value("dir", acc.pictures_dir()),
                                              READ_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            QMessageBox.warning(self, APP, f"Paint cannot read this file.\n\n{Path(path).name}\n"
                                           "This is not a valid bitmap file, or its format is not currently supported.")
            return False
        self.doc.load(img, str(Path(path).resolve()))
        self.settings.setValue("dir", str(Path(path).parent))
        self.canvas.set_zoom(1.0)
        self.canvas.update_scroll()
        self._changed()
        return True

    def save(self) -> bool:
        self.canvas.commit_all()
        if not self.doc.path:
            return self.save_as()
        return self._write(self.doc.path)

    def save_as(self, ext: str | None = "png") -> bool:
        self.canvas.commit_all()
        name = Path(self.doc.path).stem if self.doc.path else "Untitled"
        start = str(Path(self.settings.value("dir", acc.pictures_dir())) / f"{name}.{ext or 'png'}")
        filters = ";;".join(f"{label.split()[0]} (*.{e})" for label, e in FORMATS)
        selected = next((f"{label.split()[0]} (*.{e})" for label, e in FORMATS if e == ext), "")
        path, _f = QFileDialog.getSaveFileName(self, "Save As", start, filters, selected)
        if not path:
            return False
        if not Path(path).suffix:
            path += f".{ext or 'png'}"
        if self._write(path):
            self.doc.path = str(Path(path).resolve())
            self.settings.setValue("dir", str(Path(path).parent))
            self._changed()
            return True
        return False

    def _write(self, path: str) -> bool:
        ext = Path(path).suffix.lower().lstrip(".")
        img = self.doc.image
        quality = 95 if ext in ("jpg", "jpeg") else -1
        if ext == "gif":
            img = img.convertToFormat(QImage.Format_Indexed8)
        if not img.save(path, None, quality):
            QMessageBox.warning(self, APP, f"Paint could not save {Path(path).name}.")
            return False
        self.doc.modified = False
        self._update_status()
        return True

    def _render_print(self, printer: QPrinter):
        p = QPainter(printer)
        page = printer.pageLayout().paintRectPixels(printer.resolution())
        img = self.doc.image
        scale = printer.resolution() / 96
        size = QSize(int(img.width() * scale), int(img.height() * scale))
        if size.width() > page.width() or size.height() > page.height():
            size = size.scaled(page.size(), Qt.KeepAspectRatio)
        p.drawImage(QRect(QPoint(0, 0), size), img)
        p.end()

    def print_(self):
        self.canvas.commit_all()
        printer = QPrinter(QPrinter.HighResolution)
        if QPrintDialog(printer, self).exec() == QDialog.Accepted:
            self._render_print(printer)

    def print_preview(self):
        self.canvas.commit_all()
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintPreviewDialog(printer, self)
        dlg.paintRequested.connect(self._render_print)
        dlg.exec()

    def _export_temp(self) -> str:
        self.canvas.commit_all()
        d = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "classic7-paint"
        d.mkdir(parents=True, exist_ok=True)
        name = (Path(self.doc.path).stem if self.doc.path else "Untitled") + ".png"
        path = d / name
        self.doc.image.save(str(path), "PNG")
        return str(path)

    def email(self):
        path = self._export_temp()
        try:
            subprocess.Popen(["classic7-mail", "--compose", "--attach", path], start_new_session=True)
        except OSError:
            QMessageBox.warning(self, APP, "Mail is not available.")

    def set_wallpaper(self, mode: str):
        self.canvas.commit_all()
        d = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "classic7" / "wallpapers"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"paint-{time.strftime('%Y%m%d-%H%M%S')}.png"
        self.doc.image.save(str(path), "PNG")
        try:
            subprocess.Popen(["plasma-apply-wallpaperimage", "--fill-mode", mode, str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            QMessageBox.warning(self, APP, "The desktop background could not be changed.")

    # ---- window --------------------------------------------------------------------------------
    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("size", self.size())
        e.accept()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()

    def dropEvent(self, e):
        md = e.mimeData()
        urls = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if urls:
            if self.maybe_save():
                self.open_path(urls[0])
        elif md.hasImage():
            QApplication.clipboard().setImage(QImage(md.imageData()))
            self.paste()


def pc_brushes():
    return [(k, BRUSH_NAMES[k]) for k in pc.BRUSHES]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-paint")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-paint")
    files = [QUrl(a).toLocalFile() if a.startswith("file://") else a for a in argv if not a.startswith("-")]
    w = PaintWindow(files[0] if files else None)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
