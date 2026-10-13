"""Paint's picture and canvas: the image with undo, flood fill, brushes, shapes, selections that
can be moved, stretched and made transparent, text boxes, zoom, gridlines and the handles that
change the canvas size. The window around it is paint_app.py."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient,
                           QTextDocument, QTransform)
from PySide6.QtWidgets import QAbstractScrollArea, QTextEdit

WORKSPACE = QColor(0xcb, 0xd6, 0xe6)
MARGIN = 5
UNDO_LIMIT = 40

SHAPES = ["line", "curve", "oval", "rect", "roundrect", "polygon", "triangle", "righttriangle", "diamond",
          "pentagon", "hexagon", "arrow_right", "arrow_left", "arrow_up", "arrow_down", "star4", "star5", "star6",
          "callout_round", "callout_oval", "heart", "lightning"]
BRUSHES = ["brush", "calligraphy1", "calligraphy2", "airbrush", "oil", "crayon", "marker", "pencil_natural",
           "watercolor"]
SIZES = {"pencil": [1, 2, 3, 4], "eraser": [4, 6, 8, 10], "shape": [1, 3, 5, 8], "brush": [3, 6, 10, 16],
         "airbrush": [10, 18, 26, 36]}


# ---- pixels -------------------------------------------------------------------------------------
def pixels(img: QImage) -> np.ndarray:
    """The image as a writable (height, width) array of 0xAARRGGBB values (RGB32/ARGB32 only)."""
    w, h = img.width(), img.height()
    buf = img.bits()
    arr = np.frombuffer(buf, dtype=np.uint32).reshape(h, img.bytesPerLine() // 4)
    return arr[:, :w]


def flood_fill(img: QImage, x: int, y: int, color: QColor) -> QRect | None:
    """Fill the area of one colour around (x, y): Paint's Fill with color. Returns what changed."""
    if not (0 <= x < img.width() and 0 <= y < img.height()):
        return None
    arr = pixels(img)
    target = arr[y, x]
    new = np.uint32(color.rgba() | 0xFF000000)
    if target == new:
        return None
    mask = arr == target
    h, w = mask.shape
    filled = np.zeros_like(mask)
    stack = [(x, y)]
    while stack:
        sx, sy = stack.pop()
        if filled[sy, sx] or not mask[sy, sx]:
            continue
        row = mask[sy]
        left = row[: sx + 1][::-1]
        n_left = int(np.argmin(left)) if not left.all() else len(left)
        right = row[sx:]
        n_right = int(np.argmin(right)) if not right.all() else len(right)
        lo, hi = sx - n_left + 1, sx + n_right - 1
        filled[sy, lo:hi + 1] = True
        for ny in (sy - 1, sy + 1):
            if 0 <= ny < h:
                seg = mask[ny, lo:hi + 1] & ~filled[ny, lo:hi + 1]
                if seg.any():
                    d = np.diff(np.concatenate(([0], seg.astype(np.int8))))
                    for s in np.nonzero(d == 1)[0]:
                        stack.append((lo + int(s), ny))
    rows = np.nonzero(filled.any(axis=1))[0]
    cols = np.nonzero(filled.any(axis=0))[0]
    if not len(rows):
        return None
    arr[filled] = new
    return QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))


def shape_path(kind: str, r: QRectF) -> QPainterPath:
    """The outline of one of Paint's shapes inside the rectangle r."""
    path = QPainterPath()
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    cx, cy = r.center().x(), r.center().y()

    def poly(points):
        path.addPolygon(QPolygonF([QPointF(px, py) for px, py in points]))
        path.closeSubpath()

    def regular(n, rot=-math.pi / 2):
        poly([(cx + w / 2 * math.cos(rot + 2 * math.pi * i / n), cy + h / 2 * math.sin(rot + 2 * math.pi * i / n))
              for i in range(n)])

    def star(n, inner):
        pts = []
        for i in range(n * 2):
            rad = 1 if i % 2 == 0 else inner
            a = -math.pi / 2 + math.pi * i / n
            pts.append((cx + w / 2 * rad * math.cos(a), cy + h / 2 * rad * math.sin(a)))
        poly(pts)

    if kind == "oval":
        path.addEllipse(r)
    elif kind == "rect":
        path.addRect(r)
    elif kind == "roundrect":
        rad = min(w, h) * 0.18
        path.addRoundedRect(r, rad, rad)
    elif kind == "triangle":
        poly([(cx, y), (x + w, y + h), (x, y + h)])
    elif kind == "righttriangle":
        poly([(x, y), (x + w, y + h), (x, y + h)])
    elif kind == "diamond":
        poly([(cx, y), (x + w, cy), (cx, y + h), (x, cy)])
    elif kind == "pentagon":
        regular(5)
    elif kind == "hexagon":
        regular(6, 0)
    elif kind.startswith("arrow_"):
        pts = [(0, 0.3), (0.6, 0.3), (0.6, 0), (1, 0.5), (0.6, 1), (0.6, 0.7), (0, 0.7)]
        if kind == "arrow_left":
            pts = [(1 - px, py) for px, py in pts]
        elif kind == "arrow_up":
            pts = [(py, 1 - px) for px, py in pts]
        elif kind == "arrow_down":
            pts = [(py, px) for px, py in pts]
        poly([(x + px * w, y + py * h) for px, py in pts])
    elif kind == "star4":
        star(4, 0.38)
    elif kind == "star5":
        star(5, 0.4)
    elif kind == "star6":
        star(6, 0.55)
    elif kind == "callout_round":
        body = QRectF(x, y, w, h * 0.75)
        rad = min(w, h) * 0.12
        path.addRoundedRect(body, rad, rad)
        tail = QPainterPath()
        tail.addPolygon(QPolygonF([QPointF(x + w * 0.2, y + h * 0.7), QPointF(x + w * 0.12, y + h),
                                   QPointF(x + w * 0.38, y + h * 0.7)]))
        path = path.united(tail)
    elif kind == "callout_oval":
        path.addEllipse(QRectF(x, y, w, h * 0.78))
        tail = QPainterPath()
        tail.addPolygon(QPolygonF([QPointF(x + w * 0.22, y + h * 0.6), QPointF(x + w * 0.1, y + h),
                                   QPointF(x + w * 0.42, y + h * 0.7)]))
        path = path.united(tail)
    elif kind == "heart":
        path.moveTo(cx, y + h * 0.28)
        path.cubicTo(cx, y, x, y, x, y + h * 0.33)
        path.cubicTo(x, y + h * 0.62, cx - w * 0.1, y + h * 0.8, cx, y + h)
        path.cubicTo(cx + w * 0.1, y + h * 0.8, x + w, y + h * 0.62, x + w, y + h * 0.33)
        path.cubicTo(x + w, y, cx, y, cx, y + h * 0.28)
        path.closeSubpath()
    elif kind == "lightning":
        pts = [(0.38, 0), (0.62, 0.3), (0.53, 0.34), (0.82, 0.62), (0.72, 0.66), (1, 1), (0.48, 0.72),
               (0.58, 0.68), (0.22, 0.44), (0.33, 0.39), (0, 0.18)]
        poly([(x + px * w, y + py * h) for px, py in pts])
    return path


@dataclass
class UndoStep:
    rect: QRect | None          # None: the whole picture (size may change)
    before: QImage
    after: QImage


class Document:
    def __init__(self, width: int = 1024, height: int = 768):
        self.image = QImage(width, height, QImage.Format_RGB32)
        self.image.fill(QColor("white"))
        self.path: str | None = None
        self.modified = False
        self.undo_steps: list[UndoStep] = []
        self.redo_steps: list[UndoStep] = []
        self._before: QImage | None = None
        self._before_rect: QRect | None = None

    def load(self, image: QImage, path: str | None):
        self.image = image.convertToFormat(QImage.Format_RGB32) if not image.hasAlphaChannel() else \
            self._flatten(image)
        self.path = path
        self.modified = False
        self.undo_steps.clear()
        self.redo_steps.clear()

    @staticmethod
    def _flatten(image: QImage) -> QImage:
        out = QImage(image.size(), QImage.Format_RGB32)
        out.fill(QColor("white"))
        p = QPainter(out)
        p.drawImage(0, 0, image)
        p.end()
        return out

    # undo: begin(rect) before changing pixels, end() after
    def begin(self, rect: QRect | None = None):
        if rect is not None:
            rect = rect.intersected(self.image.rect())
        self._before_rect = rect
        self._before = self.image.copy(rect) if rect is not None else self.image.copy()

    def end(self, rect: QRect | None = None):
        if self._before is None:
            return
        r = self._before_rect
        if rect is not None and r is not None and rect != r:
            r = r.united(rect).intersected(self.image.rect())
        after = self.image.copy(r) if r is not None else self.image.copy()
        self.undo_steps.append(UndoStep(r, self._before, after))
        del self.undo_steps[:-UNDO_LIMIT]
        self.redo_steps.clear()
        self._before = None
        self.modified = True

    def replace(self, image: QImage):
        """A change of the whole picture (resize, rotate, crop)."""
        self.begin(None)
        self.image = image.convertToFormat(QImage.Format_RGB32)
        self.end(None)

    def undo(self) -> bool:
        if not self.undo_steps:
            return False
        step = self.undo_steps.pop()
        self._apply(step, step.before)
        self.redo_steps.append(step)
        self.modified = True
        return True

    def redo(self) -> bool:
        if not self.redo_steps:
            return False
        step = self.redo_steps.pop()
        self._apply(step, step.after)
        self.undo_steps.append(step)
        self.modified = True
        return True

    def _apply(self, step: UndoStep, img: QImage):
        if step.rect is None:
            self.image = img.copy()
        else:
            p = QPainter(self.image)
            p.setCompositionMode(QPainter.CompositionMode_Source)
            p.drawImage(step.rect.topLeft(), img)
            p.end()


class Canvas(QAbstractScrollArea):
    """The picture on the light blue workspace, and everything the tools do with the mouse."""
    changed = Signal()            # pixels changed (title, file size)
    cursorMoved = Signal(object)  # QPoint in the picture, or None
    selectionChanged = Signal(object)  # QRect or None
    zoomChanged = Signal(float)
    colorPicked = Signal(int, QColor)  # which (1 or 2), colour
    toolDone = Signal(str)        # e.g. after the colour picker, go back to the previous tool
    sizeChanged = Signal()

    def __init__(self, doc: Document):
        super().__init__()
        self.doc = doc
        self.zoom = 1.0
        self.tool = "pencil"
        self.brush = "brush"
        self.shape = "rect"
        self.outline = "solid"           # none, solid
        self.fill = "none"               # none, solid
        self.size_index = 1
        self.color1 = QColor("black")
        self.color2 = QColor("white")
        self.grid = False
        self.transparent_select = False
        self.select_mode = "rect"        # rect, free
        self._button = Qt.NoButton
        self._last: QPointF | None = None
        self._points: list[QPointF] = []
        self.layer: QImage | None = None         # the stroke being drawn (brushes, marker...)
        self.layer_opacity = 1.0
        self.preview: QPainterPath | None = None
        self.preview_kind = ""
        self.curve_stage = 0
        self.curve_pts: list[QPointF] = []
        self.poly_pts: list[QPointF] = []
        self.selection: QRect | None = None
        self.sel_path: QPainterPath | None = None   # free-form outline (picture coordinates)
        self.floating: QImage | None = None        # a lifted selection
        self.float_rect: QRectF | None = None
        self._drag = None
        self.text_edit: QTextEdit | None = None
        self.text_rect: QRect | None = None
        self.text_font = QFont("Liberation Sans")
        self.text_font.setPointSize(11)
        self.text_opaque = False
        self.resize_drag: str | None = None
        self.resize_preview: QRect | None = None
        self.air_timer = QTimer(self)
        self.air_timer.setInterval(30)
        self.air_timer.timeout.connect(self._air_tick)
        self.ants = 0
        self.ant_timer = QTimer(self)
        self.ant_timer.setInterval(250)
        self.ant_timer.timeout.connect(self._ants)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.update_scroll()

    # ---- geometry ---------------------------------------------------------------------------
    def update_scroll(self):
        w = int(self.doc.image.width() * self.zoom) + MARGIN * 2 + 12
        h = int(self.doc.image.height() * self.zoom) + MARGIN * 2 + 12
        vw, vh = self.viewport().width(), self.viewport().height()
        self.horizontalScrollBar().setRange(0, max(0, w - vw))
        self.verticalScrollBar().setRange(0, max(0, h - vh))
        self.horizontalScrollBar().setPageStep(vw)
        self.verticalScrollBar().setPageStep(vh)
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.update_scroll()

    def scrollContentsBy(self, dx, dy):
        if self.text_edit is not None:
            self.text_edit.move(self.text_edit.pos() + QPoint(dx, dy))
        self.viewport().update()

    def origin(self) -> QPointF:
        return QPointF(MARGIN - self.horizontalScrollBar().value(), MARGIN - self.verticalScrollBar().value())

    def to_image(self, pos: QPointF) -> QPointF:
        o = self.origin()
        return QPointF((pos.x() - o.x()) / self.zoom, (pos.y() - o.y()) / self.zoom)

    def to_view(self, p: QPointF) -> QPointF:
        o = self.origin()
        return QPointF(o.x() + p.x() * self.zoom, o.y() + p.y() * self.zoom)

    def view_rect(self, r: QRectF) -> QRectF:
        a = self.to_view(r.topLeft())
        return QRectF(a.x(), a.y(), r.width() * self.zoom, r.height() * self.zoom)

    def set_zoom(self, z: float, anchor: QPointF | None = None):
        z = max(0.125, min(8.0, z))
        if abs(z - self.zoom) < 1e-6:
            return
        self.commit_text()
        if anchor is None:
            anchor = QPointF(self.viewport().width() / 2, self.viewport().height() / 2)
        img_pt = self.to_image(anchor)
        self.zoom = z
        self.update_scroll()
        # keep the point under the mouse in place
        self.horizontalScrollBar().setValue(int(MARGIN + img_pt.x() * z - anchor.x()))
        self.verticalScrollBar().setValue(int(MARGIN + img_pt.y() * z - anchor.y()))
        self.zoomChanged.emit(z)
        self.viewport().update()

    def handle_rects(self) -> dict[str, QRectF]:
        img = self.doc.image
        br = self.to_view(QPointF(img.width(), img.height()))
        s = 5
        return {"r": QRectF(br.x() + 1, (self.to_view(QPointF(0, img.height() / 2))).y() - s / 2, s, s),
                "b": QRectF(self.to_view(QPointF(img.width() / 2, 0)).x() - s / 2, br.y() + 1, s, s),
                "br": QRectF(br.x() + 1, br.y() + 1, s, s)}

    # ---- painting ---------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), WORKSPACE)
        img = self.doc.image
        target = self.view_rect(QRectF(0, 0, img.width(), img.height()))
        p.fillRect(target.translated(3, 3), QColor(0, 0, 0, 40))
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.zoom < 1)
        p.drawImage(target, img)
        if self.layer is not None:
            p.setOpacity(self.layer_opacity)
            p.drawImage(target, self.layer)
            p.setOpacity(1.0)
        p.save()
        p.translate(self.origin())
        p.scale(self.zoom, self.zoom)
        p.setClipRect(QRectF(0, 0, img.width(), img.height()))
        if self.preview is not None:
            p.setRenderHint(QPainter.Antialiasing, self.size_index > 0)
            self._paint_shape(p, self.preview, preview=True)
        if self.floating is not None and self.float_rect is not None:
            p.drawImage(self.float_rect, self._floating_for_paint())
        p.restore()
        if self.grid and self.zoom >= 4:
            p.setPen(QColor(128, 128, 128, 120))
            x0 = max(0, int(-self.origin().x() / self.zoom))
            y0 = max(0, int(-self.origin().y() / self.zoom))
            x1 = min(img.width(), x0 + int(self.viewport().width() / self.zoom) + 2)
            y1 = min(img.height(), y0 + int(self.viewport().height() / self.zoom) + 2)
            for x in range(x0, x1 + 1):
                vx = self.to_view(QPointF(x, 0)).x()
                p.drawLine(QPointF(vx, target.top()), QPointF(vx, target.bottom()))
            for y in range(y0, y1 + 1):
                vy = self.to_view(QPointF(0, y)).y()
                p.drawLine(QPointF(target.left(), vy), QPointF(target.right(), vy))
        # selection outline: marching ants
        sel = self._sel_view()
        if sel is not None:
            for color, offset in ((QColor("white"), 0), (QColor("black"), 4)):
                pen = QPen(color, 1, Qt.CustomDashLine)
                pen.setDashPattern([4, 4])
                pen.setDashOffset(self.ants + offset)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                if isinstance(sel, QPainterPath):
                    p.drawPath(sel)
                else:
                    p.drawRect(sel.adjusted(0, 0, -1, -1))
            if self.floating is not None and isinstance(sel, QRectF):
                for h in self._sel_handles(sel).values():
                    p.fillRect(h, QColor("white"))
                    p.setPen(QColor("#2060c0"))
                    p.drawRect(h)
        if self.curve_stage or self.poly_pts:
            pass
        # canvas size handles
        for h in self.handle_rects().values():
            p.fillRect(h, QColor("white"))
            p.setPen(QColor("#404040"))
            p.drawRect(h)
        if self.resize_preview is not None:
            pen = QPen(QColor("black"), 1, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(self.view_rect(QRectF(self.resize_preview)))

    def _floating_for_paint(self) -> QImage:
        if not self.transparent_select:
            return self.floating
        img = self.floating.convertToFormat(QImage.Format_ARGB32)
        arr = pixels(img)
        key = np.uint32(self.color2.rgba() | 0xFF000000)
        arr[arr == key] = 0
        return img

    def _sel_view(self):
        if self.floating is not None and self.float_rect is not None:
            return self.view_rect(self.float_rect)
        if self.sel_path is not None and self.selection is not None:
            t = QTransform()
            o = self.origin()
            t.translate(o.x(), o.y())
            t.scale(self.zoom, self.zoom)
            return t.map(self.sel_path)
        if self.selection is not None:
            return self.view_rect(QRectF(self.selection))
        return None

    @staticmethod
    def _sel_handles(r: QRectF) -> dict[str, QRectF]:
        s = 5
        pts = {"tl": r.topLeft(), "t": QPointF(r.center().x(), r.top()), "tr": r.topRight(),
               "l": QPointF(r.left(), r.center().y()), "r": QPointF(r.right(), r.center().y()),
               "bl": r.bottomLeft(), "b": QPointF(r.center().x(), r.bottom()), "br": r.bottomRight()}
        return {k: QRectF(v.x() - s / 2, v.y() - s / 2, s, s) for k, v in pts.items()}

    def _ants(self):
        self.ants = (self.ants + 1) % 8
        self.viewport().update()

    # ---- pens -------------------------------------------------------------------------------
    def size_px(self) -> int:
        group = {"pencil": "pencil", "eraser": "eraser", "shape": "shape"}.get(self.tool, "brush")
        if self.tool == "brush" and self.brush == "airbrush":
            group = "airbrush"
        return SIZES[group][self.size_index]

    def _paint_shape(self, p: QPainter, path: QPainterPath, preview=False):
        if self.preview_kind == "textbox":
            pen = QPen(QColor("#3070c0"), 1 / self.zoom, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            return
        c_out = self.color1 if self._button != Qt.RightButton else self.color2
        c_fill = self.color2 if self._button != Qt.RightButton else self.color1
        width = SIZES["shape"][self.size_index]
        if self.preview_kind in ("line", "curve"):
            p.setPen(QPen(c_out, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            return
        p.setPen(QPen(c_out, width, Qt.SolidLine, Qt.SquareCap if self.preview_kind == "rect" else Qt.RoundCap,
                      Qt.MiterJoin if self.preview_kind == "rect" else Qt.RoundJoin)
                 if self.outline == "solid" else Qt.NoPen)
        p.setBrush(c_fill if self.fill == "solid" else Qt.NoBrush)
        if self.outline != "solid" and self.fill != "solid":
            p.setPen(QPen(c_out, 1))
        p.drawPath(path)

    def _stamp(self, p: QPainter, pt: QPointF, color: QColor):
        size = self.size_px()
        kind = self.brush
        if kind in ("brush", "oil", "marker", "watercolor"):
            p.setPen(Qt.NoPen)
            if kind == "marker":
                p.setBrush(color)
                p.drawRect(QRectF(pt.x() - size / 2, pt.y() - size / 2, size, size))
            elif kind == "watercolor":
                g = QRadialGradient(pt, size / 2)
                g.setColorAt(0, color)
                c2 = QColor(color)
                c2.setAlpha(0)
                g.setColorAt(1, c2)
                p.setBrush(QBrush(g))
                p.drawEllipse(pt, size / 2, size / 2)
            else:
                p.setBrush(color)
                p.drawEllipse(pt, size / 2, size / 2)
                if kind == "oil":
                    c = QColor(color).lighter(115)
                    p.setBrush(c)
                    for _ in range(2):
                        p.drawEllipse(pt + QPointF(random.uniform(-size / 3, size / 3), random.uniform(-size / 3, size / 3)),
                                      size / 6, size / 6)
        elif kind in ("calligraphy1", "calligraphy2"):
            d = size / 2 / math.sqrt(2)
            sign = 1 if kind == "calligraphy1" else -1
            p.setPen(QPen(color, 1.5))
            p.drawLine(QPointF(pt.x() - d, pt.y() + d * sign), QPointF(pt.x() + d, pt.y() - d * sign))
        elif kind == "crayon":
            p.setPen(QPen(color, 1))
            r = size / 2
            for _ in range(int(size * 1.5)):
                a = random.uniform(0, 2 * math.pi)
                rr = r * math.sqrt(random.random())
                p.drawPoint(QPointF(pt.x() + rr * math.cos(a), pt.y() + rr * math.sin(a)))
        elif kind == "pencil_natural":
            c = QColor(color)
            c.setAlpha(170)
            p.setPen(QPen(c, max(1.0, size / 4)))
            p.drawPoint(pt + QPointF(random.uniform(-0.6, 0.6), random.uniform(-0.6, 0.6)))
        elif kind == "airbrush":
            p.setPen(QPen(color, 1))
            r = size / 2
            for _ in range(12):
                a = random.uniform(0, 2 * math.pi)
                rr = r * math.sqrt(random.random())
                p.drawPoint(QPointF(pt.x() + rr * math.cos(a), pt.y() + rr * math.sin(a)))

    def _stroke_to(self, pt: QPointF):
        """Draw from the last point to pt with the current pencil, brush or eraser."""
        last = self._last if self._last is not None else pt
        color = self.color1 if self._button == Qt.LeftButton else self.color2
        if self.tool == "pencil":
            p = QPainter(self.doc.image)
            p.setPen(QPen(color, self.size_px(), Qt.SolidLine, Qt.SquareCap if self.size_px() > 1 else Qt.FlatCap))
            a = QPoint(int(math.floor(last.x())), int(math.floor(last.y())))
            b = QPoint(int(math.floor(pt.x())), int(math.floor(pt.y())))
            if a == b:
                p.drawPoint(a)
            else:
                p.drawLine(a, b)
            p.end()
            s = self.size_px() + 2
            self._dirty = self._dirty.united(QRect(a, b).normalized().adjusted(-s, -s, s, s))
        elif self.tool == "eraser":
            size = self.size_px()
            steps = max(1, int(math.hypot(pt.x() - last.x(), pt.y() - last.y()) / max(1, size / 3)))
            if self._button == Qt.LeftButton:
                p = QPainter(self.doc.image)
                for i in range(steps + 1):
                    q = last + (pt - last) * (i / steps)
                    p.fillRect(QRectF(math.floor(q.x() - size / 2), math.floor(q.y() - size / 2), size, size),
                               self.color2)
                p.end()
            else:
                # colour eraser: only pixels of colour 1 become colour 2
                arr = pixels(self.doc.image)
                c1 = np.uint32(self.color1.rgba() | 0xFF000000)
                c2 = np.uint32(self.color2.rgba() | 0xFF000000)
                for i in range(steps + 1):
                    q = last + (pt - last) * (i / steps)
                    x0, y0 = max(0, int(q.x() - size / 2)), max(0, int(q.y() - size / 2))
                    x1 = min(self.doc.image.width(), x0 + size)
                    y1 = min(self.doc.image.height(), y0 + size)
                    block = arr[y0:y1, x0:x1]
                    block[block == c1] = c2
            r = QRect(QPoint(int(min(last.x(), pt.x()) - size), int(min(last.y(), pt.y()) - size)),
                      QPoint(int(max(last.x(), pt.x()) + size), int(max(last.y(), pt.y()) + size)))
            self._dirty = self._dirty.united(r)
        else:
            p = QPainter(self.layer)
            p.setRenderHint(QPainter.Antialiasing)
            size = self.size_px()
            dist = math.hypot(pt.x() - last.x(), pt.y() - last.y())
            step = max(0.8, size / 6 if self.brush not in ("airbrush", "crayon") else size / 3)
            n = max(1, int(dist / step))
            opaque = QColor(color)
            opaque.setAlpha(255)
            for i in range(1, n + 1):
                self._stamp(p, last + (pt - last) * (i / n), opaque)
            if self._last is None:
                self._stamp(p, pt, opaque)
            p.end()
            s = size + 4
            r = QRect(QPoint(int(min(last.x(), pt.x()) - s), int(min(last.y(), pt.y()) - s)),
                      QPoint(int(max(last.x(), pt.x()) + s), int(max(last.y(), pt.y()) + s)))
            self._dirty = self._dirty.united(r)
        self._last = pt
        self.viewport().update()

    def _air_tick(self):
        if self._last is not None and self.layer is not None:
            p = QPainter(self.layer)
            color = self.color1 if self._button == Qt.LeftButton else self.color2
            self._stamp(p, self._last, color)
            p.end()
            self.viewport().update()

    # ---- mouse --------------------------------------------------------------------------------
    def _resize_handle_at(self, pos: QPointF) -> str | None:
        for name, r in self.handle_rects().items():
            if r.adjusted(-3, -3, 3, 3).contains(pos):
                return name
        return None

    def mousePressEvent(self, e):
        pos = e.position()
        ipt = self.to_image(pos)
        button = e.button()
        if button not in (Qt.LeftButton, Qt.RightButton):
            return
        self.setFocus()
        h = self._resize_handle_at(pos)
        if h and button == Qt.LeftButton:
            self.commit_all()
            self.resize_drag = h
            self.resize_preview = QRect(self.doc.image.rect())
            return
        self._button = button
        tool = self.tool
        if tool != "text":
            self.commit_text()
        if tool in ("select", "freeselect"):
            self._select_press(ipt, e)
            return
        if self.floating is not None or self.selection is not None:
            if tool not in ("picker", "magnifier"):
                self.commit_floating()
                self.clear_selection()
        if tool == "picker":
            x, y = int(ipt.x()), int(ipt.y())
            if self.doc.image.rect().contains(x, y):
                self.colorPicked.emit(1 if button == Qt.LeftButton else 2, QColor(self.doc.image.pixel(x, y)))
                self.toolDone.emit("picker")
            return
        if tool == "magnifier":
            self.set_zoom(self.zoom * (2 if button == Qt.LeftButton else 0.5), pos)
            return
        if tool == "fill":
            color = self.color1 if button == Qt.LeftButton else self.color2
            img = self.doc.image
            before = img.copy()
            r = flood_fill(img, int(ipt.x()), int(ipt.y()), color)
            if r is not None:
                self.doc.undo_steps.append(UndoStep(r, before.copy(r), img.copy(r)))
                del self.doc.undo_steps[:-UNDO_LIMIT]
                self.doc.redo_steps.clear()
                self.doc.modified = True
                self.changed.emit()
            self.viewport().update()
            return
        if tool == "text":
            if self.text_edit is not None:
                if not self.text_edit.geometry().contains(pos.toPoint()):
                    self.commit_text()
                return
            self._drag = ("text", ipt)
            return
        if tool in ("pencil", "eraser", "brush"):
            self._dirty = QRect()
            if tool == "brush":
                self.layer = QImage(self.doc.image.size(), QImage.Format_ARGB32_Premultiplied)
                self.layer.fill(Qt.transparent)
                self.layer_opacity = {"marker": 0.45, "watercolor": 0.35, "pencil_natural": 0.9}.get(self.brush, 1.0)
                self.doc.begin(None)
                if self.brush == "airbrush":
                    self.air_timer.start()
            else:
                self.doc.begin(None)
            self._last = None
            self._stroke_to(ipt)
            return
        if tool == "shape":
            if self.shape == "curve" and self.curve_stage in (1, 2):
                self._drag = ("curve", ipt)
                self._update_curve(ipt)
                return
            if self.shape == "polygon" and self.poly_pts:
                self.poly_pts.append(ipt)
                self._drag = ("polygon", ipt)
                self._update_polygon(ipt)
                return
            self._drag = ("shape", ipt)
            self.preview_kind = self.shape
            return

    def mouseMoveEvent(self, e):
        pos = e.position()
        ipt = self.to_image(pos)
        inside = self.doc.image.rect().contains(int(ipt.x()), int(ipt.y()))
        self.cursorMoved.emit(QPoint(int(ipt.x()), int(ipt.y())) if inside else None)
        if self.resize_drag:
            img = self.doc.image
            w = img.width() if self.resize_drag == "b" else max(1, int(ipt.x()))
            hgt = img.height() if self.resize_drag == "r" else max(1, int(ipt.y()))
            self.resize_preview = QRect(0, 0, w, hgt)
            self.selectionChanged.emit(self.resize_preview)
            self.viewport().update()
            return
        if not (e.buttons() & (Qt.LeftButton | Qt.RightButton)):
            self._hover_cursor(pos, ipt)
            if self.tool == "shape" and self.shape == "polygon" and self.poly_pts:
                self._update_polygon(ipt)
            return
        tool = self.tool
        if tool in ("select", "freeselect"):
            self._select_move(ipt, e)
            return
        if tool in ("pencil", "eraser", "brush") and self.doc._before is not None:
            self._stroke_to(ipt)
            return
        if self._drag is None:
            return
        kind, start = self._drag
        if kind == "shape":
            self._update_shape(start, ipt, e.modifiers() & Qt.ShiftModifier)
        elif kind == "curve":
            self._update_curve(ipt)
        elif kind == "polygon":
            self._update_polygon(ipt)
        elif kind == "text":
            self.preview = QPainterPath()
            self.preview.addRect(QRectF(start, ipt).normalized())
            self.preview_kind = "textbox"
            self.viewport().update()

    def mouseReleaseEvent(self, e):
        ipt = self.to_image(e.position())
        if self.resize_drag:
            r = self.resize_preview
            self.resize_drag = None
            self.resize_preview = None
            if r is not None and r.size() != self.doc.image.size():
                self.resize_canvas(r.width(), r.height())
            self.viewport().update()
            return
        tool = self.tool
        if tool in ("select", "freeselect"):
            self._select_release(ipt, e)
            return
        if tool in ("pencil", "eraser", "brush") and self.doc._before is not None:
            self.air_timer.stop()
            if tool == "brush" and self.layer is not None:
                p = QPainter(self.doc.image)
                p.setOpacity(self.layer_opacity)
                p.drawImage(0, 0, self.layer)
                p.end()
                self.layer = None
            self.doc.end(None)
            self._last = None
            self.changed.emit()
            self.viewport().update()
            return
        if self._drag is None:
            return
        kind, start = self._drag
        self._drag = None
        if kind == "shape":
            if self.shape == "curve":
                self.curve_pts = [start, ipt, start, ipt]
                self.curve_stage = 1
                self._update_curve(None)
                return
            if self.shape == "polygon":
                self.poly_pts = [start, ipt]
                self._update_polygon(ipt)
                return
            self._update_shape(start, ipt, e.modifiers() & Qt.ShiftModifier)
            self.commit_shape()
        elif kind == "curve":
            self.curve_stage += 1
            if self.curve_stage > 2:
                self.commit_shape()
        elif kind == "polygon":
            if len(self.poly_pts) > 2 and math.hypot(ipt.x() - self.poly_pts[0].x(),
                                                     ipt.y() - self.poly_pts[0].y()) < 6 / self.zoom:
                self.poly_pts[-1] = self.poly_pts[0]
                self.commit_polygon()
        elif kind == "text":
            r = QRectF(start, ipt).normalized().toRect()
            if r.width() < 20 or r.height() < 12:
                r = QRect(start.toPoint(), QSize(160, 40))
            self.preview = None
            self.start_text(r)

    def mouseDoubleClickEvent(self, e):
        if self.tool == "shape" and self.shape == "polygon" and len(self.poly_pts) > 2:
            self.commit_polygon()
        else:
            super().mouseDoubleClickEvent(e)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.25 if e.angleDelta().y() > 0 else 0.8), e.position())
            return
        super().wheelEvent(e)

    def _hover_cursor(self, pos: QPointF, ipt: QPointF):
        h = self._resize_handle_at(pos)
        if h:
            self.viewport().setCursor({"r": Qt.SizeHorCursor, "b": Qt.SizeVerCursor, "br": Qt.SizeFDiagCursor}[h])
            return
        if self.tool in ("select", "freeselect") and self.float_rect is not None:
            vr = self.view_rect(self.float_rect)
            for name, r in self._sel_handles(vr).items():
                if r.adjusted(-3, -3, 3, 3).contains(pos):
                    self.viewport().setCursor(Qt.SizeFDiagCursor if name in ("tl", "br") else
                                              Qt.SizeBDiagCursor if name in ("tr", "bl") else
                                              Qt.SizeVerCursor if name in ("t", "b") else Qt.SizeHorCursor)
                    return
            if vr.contains(pos):
                self.viewport().setCursor(Qt.SizeAllCursor)
                return
        if self.tool in ("select", "freeselect") and self.selection is not None and self.floating is None:
            if self.view_rect(QRectF(self.selection)).contains(pos):
                self.viewport().setCursor(Qt.SizeAllCursor)
                return
        cursors = {"text": Qt.IBeamCursor, "picker": Qt.CrossCursor, "magnifier": Qt.PointingHandCursor,
                   "fill": Qt.PointingHandCursor}
        self.viewport().setCursor(cursors.get(self.tool, Qt.CrossCursor))

    # ---- shapes -------------------------------------------------------------------------------
    def _update_shape(self, a: QPointF, b: QPointF, square: bool):
        if self.shape == "line":
            if square:
                d = b - a
                ang = round(math.atan2(d.y(), d.x()) / (math.pi / 4)) * (math.pi / 4)
                length = math.hypot(d.x(), d.y())
                b = a + QPointF(length * math.cos(ang), length * math.sin(ang))
            path = QPainterPath(a)
            path.lineTo(b)
        else:
            if square:
                side = max(abs(b.x() - a.x()), abs(b.y() - a.y()))
                b = QPointF(a.x() + math.copysign(side, b.x() - a.x()), a.y() + math.copysign(side, b.y() - a.y()))
            path = shape_path(self.shape, QRectF(a, b).normalized())
        self.preview = path
        self.preview_kind = self.shape
        self.viewport().update()

    def _update_curve(self, pt: QPointF | None):
        a, c1, c2, b = self.curve_pts
        if pt is not None:
            if self.curve_stage == 1:
                c1 = c2 = pt
            elif self.curve_stage == 2:
                c2 = pt
            self.curve_pts = [a, c1, c2, b]
        path = QPainterPath(a)
        path.cubicTo(c1, c2, b)
        self.preview = path
        self.preview_kind = "curve"
        self.viewport().update()

    def _update_polygon(self, pt: QPointF):
        if not self.poly_pts:
            return
        pts = self.poly_pts[:-1] + [pt]
        self.poly_pts[-1] = pt
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        self.preview = path
        self.preview_kind = "line"
        self.viewport().update()

    def commit_polygon(self):
        pts = self.poly_pts
        self.poly_pts = []
        if len(pts) < 3:
            self.preview = None
            self.viewport().update()
            return
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        path.closeSubpath()
        self.preview = path
        self.preview_kind = "polygon"
        self.commit_shape()

    def commit_shape(self):
        if self.preview is None:
            return
        self.doc.begin(None)
        p = QPainter(self.doc.image)
        p.setRenderHint(QPainter.Antialiasing, SIZES["shape"][self.size_index] > 1)
        self._paint_shape(p, self.preview)
        p.end()
        self.doc.end(None)
        self.preview = None
        self.curve_stage = 0
        self.curve_pts = []
        self.changed.emit()
        self.viewport().update()

    # ---- selections -------------------------------------------------------------------------------
    def _select_press(self, ipt: QPointF, e):
        if self.floating is not None and self.float_rect is not None:
            vr = self.view_rect(self.float_rect)
            for name, r in self._sel_handles(vr).items():
                if r.adjusted(-3, -3, 3, 3).contains(e.position()):
                    self._drag = ("stretch", name, QRectF(self.float_rect), ipt)
                    return
            if self.float_rect.contains(ipt):
                self._drag = ("move", ipt, QRectF(self.float_rect))
                return
            self.commit_floating()
        elif self.selection is not None and QRectF(self.selection).contains(ipt):
            self.lift(copy=bool(e.modifiers() & Qt.ControlModifier))
            self._drag = ("move", ipt, QRectF(self.float_rect))
            return
        self.clear_selection()
        if self.tool == "freeselect":
            self._points = [ipt]
            self._drag = ("free", ipt)
        else:
            self._drag = ("rect", ipt)
        self.ant_timer.start()

    def _select_move(self, ipt: QPointF, e):
        if self._drag is None:
            return
        kind = self._drag[0]
        img_rect = QRectF(self.doc.image.rect())
        if kind == "rect":
            start = self._drag[1]
            r = QRectF(start, ipt).normalized().intersected(img_rect)
            self.selection = r.toAlignedRect()
            self.selectionChanged.emit(self.selection)
        elif kind == "free":
            self._points.append(QPointF(max(0, min(img_rect.width(), ipt.x())),
                                        max(0, min(img_rect.height(), ipt.y()))))
            path = QPainterPath(self._points[0])
            for q in self._points[1:]:
                path.lineTo(q)
            self.sel_path = path
            self.selection = path.boundingRect().toAlignedRect()
        elif kind == "move":
            start, rect0 = self._drag[1], self._drag[2]
            self.float_rect = rect0.translated(round(ipt.x() - start.x()), round(ipt.y() - start.y()))
            self.selectionChanged.emit(self.float_rect.toRect())
        elif kind == "stretch":
            name, rect0, start = self._drag[1], self._drag[2], self._drag[3]
            d = ipt - start
            r = QRectF(rect0)
            if "l" in name:
                r.setLeft(r.left() + d.x())
            if "r" in name:
                r.setRight(r.right() + d.x())
            if "t" in name:
                r.setTop(r.top() + d.y())
            if "b" in name:
                r.setBottom(r.bottom() + d.y())
            if r.width() >= 1 and r.height() >= 1:
                self.float_rect = QRectF(round(r.x()), round(r.y()), round(r.width()), round(r.height()))
                self.selectionChanged.emit(self.float_rect.toRect())
        self.viewport().update()

    def _select_release(self, ipt: QPointF, e):
        if self._drag is None:
            return
        kind = self._drag[0]
        self._drag = None
        if kind == "free" and len(self._points) > 2:
            self.sel_path.closeSubpath()
            self.selection = self.sel_path.boundingRect().toAlignedRect().intersected(self.doc.image.rect())
        if kind in ("rect", "free") and (self.selection is None or self.selection.width() < 1
                                          or self.selection.height() < 1):
            self.clear_selection()
        self.selectionChanged.emit(self.selection if self.floating is None else self.float_rect.toRect())
        self.viewport().update()

    def lift(self, copy: bool = False):
        """Pick the selection up so it can be moved (Paint leaves colour 2 behind, or a copy with Ctrl)."""
        if self.selection is None or self.floating is not None:
            return
        self.doc.begin(None)
        r = self.selection
        img = self.doc.image.copy(r).convertToFormat(QImage.Format_ARGB32)
        if self.sel_path is not None:
            mask = QImage(r.size(), QImage.Format_ARGB32)
            mask.fill(Qt.transparent)
            mp = QPainter(mask)
            mp.translate(-r.topLeft())
            mp.fillPath(self.sel_path, QColor("black"))
            mp.end()
            a = pixels(img)
            m = pixels(mask)
            a[(m >> 24) == 0] = 0
        self.floating = img
        self.float_rect = QRectF(r)
        if not copy:
            p = QPainter(self.doc.image)
            if self.sel_path is not None:
                p.fillPath(self.sel_path, self.color2)
            else:
                p.fillRect(r, self.color2)
            p.end()
        self.sel_path = None

    def commit_floating(self):
        if self.floating is None or self.float_rect is None:
            return
        img = self._floating_for_paint()
        p = QPainter(self.doc.image)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(self.float_rect, img)
        p.end()
        if self.doc._before is None:
            self.doc.begin(None)
        self.doc.end(None)
        self.floating = None
        self.float_rect = None
        self.selection = None
        self.changed.emit()
        self.viewport().update()

    def clear_selection(self):
        self.selection = None
        self.sel_path = None
        if self.floating is None:
            self.ant_timer.stop()
        self.selectionChanged.emit(None)
        self.viewport().update()

    def commit_all(self):
        self.commit_text()
        self.commit_floating()
        if self.preview is not None and (self.curve_stage or self.poly_pts):
            if self.poly_pts:
                self.commit_polygon()
            else:
                self.commit_shape()
        self.clear_selection()

    def select_all(self):
        self.commit_all()
        self.selection = QRect(self.doc.image.rect())
        self.ant_timer.start()
        self.selectionChanged.emit(self.selection)
        self.viewport().update()

    def selected_image(self) -> QImage | None:
        if self.floating is not None:
            return self._floating_for_paint().scaled(self.float_rect.size().toSize())
        if self.selection is not None:
            img = self.doc.image.copy(self.selection)
            if self.sel_path is not None:
                img = img.convertToFormat(QImage.Format_ARGB32)
                mask = QImage(self.selection.size(), QImage.Format_ARGB32)
                mask.fill(Qt.transparent)
                mp = QPainter(mask)
                mp.translate(-self.selection.topLeft())
                mp.fillPath(self.sel_path, QColor("black"))
                mp.end()
                a = pixels(img)
                a[(pixels(mask) >> 24) == 0] = 0
            return img
        return None

    def delete_selection(self):
        if self.floating is not None:
            if self.doc._before is None:
                self.doc.begin(None)
            self.floating = None
            self.float_rect = None
            self.doc.end(None)
        elif self.selection is not None:
            self.doc.begin(None)
            p = QPainter(self.doc.image)
            if self.sel_path is not None:
                p.fillPath(self.sel_path, self.color2)
            else:
                p.fillRect(self.selection, self.color2)
            p.end()
            self.doc.end(None)
        self.clear_selection()
        self.changed.emit()

    def paste_image(self, img: QImage, at: QPoint | None = None):
        self.commit_all()
        if at is None:
            tl = self.to_image(QPointF(0, 0))
            at = QPoint(max(0, int(tl.x())), max(0, int(tl.y())))
        self.doc.begin(None)
        self.floating = img.convertToFormat(QImage.Format_ARGB32)
        self.float_rect = QRectF(QPointF(at), QSize(img.width(), img.height()).toSizeF())
        self.selection = self.float_rect.toRect()
        self.ant_timer.start()
        self.selectionChanged.emit(self.selection)
        self.viewport().update()

    def cancel_floating(self) -> bool:
        """Undo while a selection is lifted: put everything back as it was."""
        if self.floating is None:
            return False
        if self.doc._before is not None:
            self.doc.image = self.doc._before.copy()
            self.doc._before = None
        self.floating = None
        self.float_rect = None
        self.clear_selection()
        self.viewport().update()
        return True

    def crop(self):
        img = self.selected_image()
        if img is None:
            return
        if self.floating is not None:
            self.commit_floating()
        self.clear_selection()
        out = QImage(img.size(), QImage.Format_RGB32)
        out.fill(self.color2)
        p = QPainter(out)
        p.drawImage(0, 0, img)
        p.end()
        self.doc.replace(out)
        self.update_scroll()
        self.changed.emit()
        self.sizeChanged.emit()

    # ---- whole-picture changes ------------------------------------------------------------------
    def resize_canvas(self, w: int, h: int):
        out = QImage(w, h, QImage.Format_RGB32)
        out.fill(self.color2)
        p = QPainter(out)
        p.drawImage(0, 0, self.doc.image)
        p.end()
        self.doc.replace(out)
        self.update_scroll()
        self.changed.emit()
        self.sizeChanged.emit()

    def transform(self, kind: str, sx: float = 1.0, sy: float = 1.0, skew_x: float = 0.0, skew_y: float = 0.0):
        """rotate90, rotate270, rotate180, flipv, fliph, resize (sx, sy), skew (degrees)."""
        t = QTransform()
        if kind == "rotate90":
            t.rotate(90)
        elif kind == "rotate270":
            t.rotate(-90)
        elif kind == "rotate180":
            t.rotate(180)
        elif kind == "fliph":
            t.scale(-1, 1)
        elif kind == "flipv":
            t.scale(1, -1)
        elif kind == "resize":
            t.scale(sx, sy)
        elif kind == "skew":
            t.shear(math.tan(math.radians(skew_x)), math.tan(math.radians(skew_y)))
        if self.floating is not None or self.selection is not None:
            if self.floating is None:
                self.lift()
            img = self.floating.transformed(t, Qt.SmoothTransformation if kind in ("resize", "skew")
                                            else Qt.FastTransformation)
            c = self.float_rect.topLeft()
            self.floating = img.convertToFormat(QImage.Format_ARGB32)
            self.float_rect = QRectF(c, QSize(img.width(), img.height()).toSizeF())
            self.selectionChanged.emit(self.float_rect.toRect())
            self.viewport().update()
            return
        img = self.doc.image.transformed(t, Qt.SmoothTransformation if kind in ("resize", "skew")
                                         else Qt.FastTransformation)
        if kind == "skew":
            out = QImage(img.size(), QImage.Format_RGB32)
            out.fill(self.color2)
            p = QPainter(out)
            p.drawImage(0, 0, img)
            p.end()
            img = out
        self.doc.replace(img)
        self.update_scroll()
        self.changed.emit()
        self.sizeChanged.emit()

    def invert_colors(self):
        if self.floating is None and self.selection is None:
            self.doc.begin(None)
            self.doc.image.invertPixels()
            self.doc.end(None)
        else:
            if self.floating is None:
                self.lift()
            self.floating.invertPixels(QImage.InvertRgb)
        self.changed.emit()
        self.viewport().update()

    # ---- text ---------------------------------------------------------------------------------
    def start_text(self, r: QRect):
        ed = QTextEdit(self.viewport())
        ed.setFrameStyle(0)
        ed.setAcceptRichText(False)
        ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.document().setDocumentMargin(1)
        self.text_rect = r
        self.text_edit = ed
        self._style_text()
        ed.setGeometry(self.view_rect(QRectF(r)).toRect())
        ed.show()
        ed.setFocus()
        ed.textChanged.connect(self._grow_text)

    def _style_text(self):
        ed = self.text_edit
        if ed is None:
            return
        f = QFont(self.text_font)
        f.setPointSizeF(self.text_font.pointSizeF() * self.zoom)
        ed.setFont(f)
        bg = self.color2.name() if self.text_opaque else "transparent"
        ed.setStyleSheet(f"QTextEdit {{ background: {bg}; color: {self.color1.name()};"
                         " border: 1px dashed #3070c0; }")

    def _grow_text(self):
        ed = self.text_edit
        if ed is None:
            return
        need = int(ed.document().size().height()) + 4
        if need > ed.height():
            ed.resize(ed.width(), need)
            self.text_rect.setHeight(int(need / self.zoom))

    def set_text_font(self, font: QFont):
        self.text_font = QFont(font)
        self._style_text()

    def commit_text(self):
        ed = self.text_edit
        if ed is None:
            return
        self.text_edit = None
        text = ed.toPlainText()
        r = self.text_rect
        ed.hide()
        ed.deleteLater()
        if text.strip():
            self.doc.begin(None)
            p = QPainter(self.doc.image)
            p.setRenderHint(QPainter.TextAntialiasing)
            if self.text_opaque:
                p.fillRect(r, self.color2)
            doc = QTextDocument()
            doc.setDefaultFont(self.text_font)
            doc.setDocumentMargin(1)
            doc.setTextWidth(r.width())
            doc.setDefaultStyleSheet(f"body {{ color: {self.color1.name()}; }}")
            esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            doc.setHtml(f"<body>{esc}</body>")
            p.translate(r.topLeft())
            doc.drawContents(p, QRectF(0, 0, r.width(), r.height()))
            p.end()
            self.doc.end(None)
            self.changed.emit()
        self.viewport().update()

    # ---- keys -----------------------------------------------------------------------------------
    def keyPressEvent(self, e):
        k = e.key()
        if self.floating is not None and k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            d = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}[k]
            self.float_rect.translate(*d)
            self.viewport().update()
            return
        if self.selection is not None and self.floating is None and \
                k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self.lift()
            self.keyPressEvent(e)
            return
        if k == Qt.Key_Escape:
            if self.poly_pts or self.curve_stage:
                self.poly_pts = []
                self.curve_stage = 0
                self.preview = None
                self.viewport().update()
            elif self.floating is not None:
                self.commit_floating()
            else:
                self.clear_selection()
            return
        if k in (Qt.Key_Return, Qt.Key_Enter) and (self.poly_pts or self.curve_stage):
            if self.poly_pts:
                self.commit_polygon()
            else:
                self.commit_shape()
            return
        super().keyPressEvent(e)
