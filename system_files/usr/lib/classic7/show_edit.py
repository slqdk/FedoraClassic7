"""Show: the slide editing area (Normal view) - selecting, moving, sizing, turning shapes and
editing their text, like PowerPoint 2007."""
from __future__ import annotations

import copy
import math

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QKeySequence, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QTextCursor, QTransform)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView

import show_geom as geom
import show_model as sm
import show_render as sr
import show_text as st

HANDLE = 7          # pixels
BORDER_GRIP = 5     # pixels of a text box's frame that grab the shape instead of the text
PASTEBOARD = 60     # points of grey around the slide


def _shape_poly(s: sm.Shape, t: QTransform) -> list:
    w, h = sm.pt(s.cx), sm.pt(s.cy)
    return [t.map(QPointF(x, y)) for x, y in ((0, 0), (w, 0), (w, h), (0, h))]


def is_line(s: sm.Shape) -> bool:
    return s.kind == "sp" and s.geom in geom.LINE_SHAPES and not s.path


def line_points(s: sm.Shape) -> tuple[QPointF, QPointF]:
    x0, y0 = sm.pt(s.x), sm.pt(s.y)
    x1, y1 = x0 + sm.pt(s.cx), y0 + sm.pt(s.cy)
    a = QPointF(x1 if s.flip_h else x0, y1 if s.flip_v else y0)
    b = QPointF(x0 if s.flip_h else x1, y0 if s.flip_v else y1)
    if s.rot:
        c = QPointF((x0 + x1) / 2, (y0 + y1) / 2)
        t = QTransform().translate(c.x(), c.y()).rotate(s.rot).translate(-c.x(), -c.y())
        a, b = t.map(a), t.map(b)
    return a, b


def set_line_points(s: sm.Shape, a: QPointF, b: QPointF):
    s.rot = 0
    s.x, s.y = sm.emu(min(a.x(), b.x())), sm.emu(min(a.y(), b.y()))
    s.cx, s.cy = sm.emu(abs(b.x() - a.x())), sm.emu(abs(b.y() - a.y()))
    s.flip_h = a.x() > b.x()
    s.flip_v = a.y() > b.y()


def text_capable(s: sm.Shape) -> bool:
    return s.kind == "sp" and not is_line(s)


def edits_on_click(s: sm.Shape) -> bool:
    """Placeholders and text boxes take the text cursor on the first click (PowerPoint)."""
    return s.kind == "sp" and ((s.ph is not None and s.ph.type != "pic") or s.txbox)


class SlideItem(QGraphicsItem):
    def __init__(self, view: "SlideView"):
        super().__init__()
        self.view = view
        self.setZValue(0)

    def boundingRect(self) -> QRectF:
        pres = self.view.pres
        if pres is None:
            return QRectF()
        return QRectF(0, 0, sm.pt(pres.width), sm.pt(pres.height))

    def paint(self, p: QPainter, _opt, _w=None):
        v = self.view
        if v.pres is None or v.slide is None:
            return
        r = self.boundingRect()
        p.save()
        # a soft shadow under the slide
        for i, a in ((3, 40), (2, 60), (1, 90)):
            p.fillRect(r.translated(i * 0.6, i * 0.6), QColor(0, 0, 0, a))
        p.restore()
        v.renderer.paint_slide(p, v.slide, v.number, edit=True, no_text=v.skip_ids())
        if v.grid:
            pen = QPen(QColor(0, 0, 0, 60), 0)
            pen.setStyle(Qt.DotLine)
            p.setPen(pen)
            step = 36.0
            x = step
            while x < r.width():
                p.drawLine(QPointF(x, 0), QPointF(x, r.height()))
                x += step
            y = step
            while y < r.height():
                p.drawLine(QPointF(0, y), QPointF(r.width(), y))
                y += step


class OverlayItem(QGraphicsItem):
    """Selection frames, handles, the rubber band and the outline of a shape being drawn."""

    def __init__(self, view: "SlideView"):
        super().__init__()
        self.view = view
        self.setZValue(20)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self) -> QRectF:
        return self.view.area

    def paint(self, p: QPainter, _opt, _w=None):
        v = self.view
        px = 1.0 / max(0.01, v.transform().m11())
        p.setRenderHint(QPainter.Antialiasing)
        for s in v.selection:
            t = v.renderer.shape_transform(s, flips=False)
            if is_line(s):
                a, b = line_points(s)
                for pt in (a, b):
                    self._handle(p, pt, px, round_=True)
                continue
            poly = _shape_poly(s, t)
            editing = v.editing is not None and v.editing.shape is s
            pen = QPen(QColor("#7F9DB9") if not editing else QColor("#6E8BB4"), px * (1 if not editing else 1.5))
            if editing:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            path = QPainterPath(poly[0])
            for q in poly[1:]:
                path.lineTo(q)
            path.closeSubpath()
            p.drawPath(path)
            if len(v.selection) == 1 or True:
                pts = self.handle_points(s, t)
                for name, pt in pts.items():
                    if name == "rot":
                        top = (poly[0] + poly[1]) / 2
                        p.setPen(QPen(QColor("#7F9DB9"), px))
                        p.drawLine(top, pt)
                        self._handle(p, pt, px, rot=True)
                    else:
                        self._handle(p, pt, px, round_=name in ("tl", "tr", "bl", "br"))
        if v.cell_range is not None and v.cell_range[0] in v.slide.shapes:
            s, (r0, c0, r1, c1) = v.cell_range[0], v.cell_range[1]
            xs, ys = v.renderer.table_geometry(s, v.renderer.ctx(v.slide, s))
            t = v.renderer.shape_transform(s, flips=False)
            rect = QRectF(xs[min(c0, c1)], ys[min(r0, r1)], xs[max(c0, c1) + 1] - xs[min(c0, c1)],
                          ys[max(r0, r1) + 1] - ys[min(r0, r1)])
            p.save()
            p.setTransform(t, True)
            p.fillRect(rect, QColor(49, 106, 197, 70))
            p.restore()
        if v.band is not None:
            p.setPen(QPen(QColor("#3165C5"), px))
            p.setBrush(QColor(49, 106, 197, 40))
            p.drawRect(v.band.normalized())
        if v.draw_preview is not None:
            p.setPen(QPen(QColor("#3165C5"), px, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            r = v.draw_preview
            if v.draw_geom in geom.LINE_SHAPES:
                p.drawLine(QLineF(v.draw_start, v.draw_end))
            else:
                path = geom.preset_path(v.draw_geom or "rect", max(1, abs(r.width())), max(1, abs(r.height())))
                p.translate(r.normalized().topLeft())
                p.drawPath(path)

    def handle_points(self, s: sm.Shape, t: QTransform) -> dict:
        w, h = sm.pt(s.cx), sm.pt(s.cy)
        pts = {"tl": (0, 0), "t": (w / 2, 0), "tr": (w, 0), "r": (w, h / 2), "br": (w, h), "b": (w / 2, h),
               "bl": (0, h), "l": (0, h / 2)}
        out = {k: t.map(QPointF(*xy)) for k, xy in pts.items()}
        if s.kind != "table":
            px = 1.0 / max(0.01, self.view.transform().m11())
            out["rot"] = t.map(QPointF(w / 2, -22 * px))
        else:
            for k in ("t", "b", "l", "r"):
                out.pop(k)
        return out

    def _handle(self, p, pt, px, round_=False, rot=False):
        r = HANDLE * px / 2 + px
        p.setPen(QPen(QColor("#5A7EBF") if not rot else QColor("#3A7A2A"), px))
        if rot:
            p.setBrush(QColor("#7CD656"))
            p.drawEllipse(pt, r, r)
        elif round_:
            p.setBrush(QColor("#E6F0FB"))
            p.drawEllipse(pt, r, r)
        else:
            p.setBrush(QColor("#E6F0FB"))
            p.drawRect(QRectF(pt.x() - r, pt.y() - r, 2 * r, 2 * r))


class TextEditItem(QGraphicsTextItem):
    """The text of one shape (or table cell) being edited, laid out exactly like the slide."""

    def __init__(self, view: "SlideView", shape: sm.Shape, body: sm.TextBody, ctx: st.TextCtx, area: QRectF,
                 cell: tuple | None = None):
        super().__init__()
        self.view = view
        self.shape = shape
        self.cell = cell
        self.body = body
        self.ctx = ctx
        self.area = area
        doc = st.to_document(body, ctx, area.width() if body.wrap else None)
        self.setDocument(doc)
        doc.documentLayout().setPaintDevice(st.device())
        if body.wrap:
            self.setTextWidth(area.width())
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setZValue(10)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setCursor(Qt.IBeamCursor)
        doc.contentsChanged.connect(self.reposition)
        self.reposition()

    def reposition(self):
        doc = self.document()
        t = self.view.renderer.shape_transform(self.shape, flips=False)
        off = st.doc_offset(doc, self.body, self.area)
        tt = QTransform()
        tt.translate(self.area.left() + off.x(), self.area.top() + off.y())
        self.setTransform(tt * t)
        self.view.text_changed_live(self)

    def paint(self, p, opt, w=None):
        from PySide6.QtWidgets import QStyle, QStyleOptionGraphicsItem
        o = QStyleOptionGraphicsItem(opt)
        o.state &= ~(QStyle.State_HasFocus | QStyle.State_Selected)
        super().paint(p, o, w)
        p.save()
        st.paint_bullets(p, self.document(), self.ctx, show_empty=True)
        p.restore()

    def sceneEvent(self, e):
        if e.type() == QEvent.KeyPress:
            if self.view.text_key(self, e):
                return True
            if e.text() and e.text().isprintable():
                c = self.textCursor()
                if not c.hasSelection() and c.atBlockStart() and not c.charFormat().fontPointSize():
                    fix_cursor_format(c)
                    self.setTextCursor(c)
        return super().sceneEvent(e)

    def contextMenuEvent(self, e):
        self.view.context_menu_requested.emit(e.screenPos())


class SlideView(QGraphicsView):
    selectionChanged = Signal()
    formatChanged = Signal()           # the text cursor moved / the format under it changed
    editingChanged = Signal(bool)
    context_menu_requested = Signal(object)
    zoomChanged = Signal(float)
    shapeDrawn = Signal()
    slideStep = Signal(int)           # wheel / Page Up / Page Down: previous or next slide

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host                   # the window: begin_change / end_change / changed
        self.pres: sm.Presentation | None = None
        self.renderer: sr.Renderer | None = None
        self.slide: sm.Slide | None = None
        self.number = 0
        self.selection: list[sm.Shape] = []
        self.editing: TextEditItem | None = None
        self.cell_range = None             # (table shape, (r0, c0, r1, c1))
        self.band: QRectF | None = None
        self.drag = None
        self.draw_geom: str | None = None
        self.draw_preview: QRectF | None = None
        self.draw_start = self.draw_end = QPointF()
        self.grid = False
        self.fit = True
        self.area = QRectF(-PASTEBOARD, -PASTEBOARD, 720 + 2 * PASTEBOARD, 540 + 2 * PASTEBOARD)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(self.area)
        self.setScene(self._scene)
        self.slide_item = SlideItem(self)
        self.overlay = OverlayItem(self)
        self._scene.addItem(self.slide_item)
        self._scene.addItem(self.overlay)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#ABBACE"))
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.speller = None

    # ---- content -----------------------------------------------------------------------------
    def set_presentation(self, pres: sm.Presentation, renderer: sr.Renderer):
        self.end_edit()
        self.pres = pres
        self.renderer = renderer
        w, h = sm.pt(pres.width), sm.pt(pres.height)
        self.slide_item.prepareGeometryChange()
        self.overlay.prepareGeometryChange()
        self.area = QRectF(-PASTEBOARD, -PASTEBOARD, w + 2 * PASTEBOARD, h + 2 * PASTEBOARD)
        self._scene.setSceneRect(self.area)
        if self.fit:
            QTimer.singleShot(0, self.zoom_fit)

    def set_slide(self, slide: sm.Slide | None, number: int):
        if slide is not self.slide:
            self.end_edit()
            self.selection = []
            self.cell_range = None
        self.slide = slide
        self.number = number
        self.refresh()
        self.selectionChanged.emit()

    def refresh(self):
        self.slide_item.update()
        self.overlay.update()
        self._scene.update()

    def skip_ids(self) -> set:
        if self.editing is not None and self.editing.cell is None:
            return {self.editing.shape.id}
        return set()

    # ---- zoom --------------------------------------------------------------------------------
    def zoom_fit(self):
        if self.pres is None:
            return
        self.fit = True
        w, h = sm.pt(self.pres.width), sm.pt(self.pres.height)
        vw, vh = max(50, self.viewport().width() - 24), max(50, self.viewport().height() - 24)
        z = min(vw / w, vh / h)
        self._apply_zoom(z)
        self.centerOn(w / 2, h / 2)

    def set_zoom(self, z: float):
        self.fit = False
        self._apply_zoom(max(0.1, min(4.0, z)))

    def zoom_percent(self) -> int:
        """100 % = the slide at its real size (96 pixels per inch)."""
        return round(self.transform().m11() / (96.0 / 72.0) * 100)

    def set_zoom_percent(self, pct: float):
        self.set_zoom(pct / 100.0 * 96.0 / 72.0)

    def _apply_zoom(self, z: float):
        self.setTransform(QTransform.fromScale(z, z))
        self.overlay.update()
        self.zoomChanged.emit(z)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit:
            self.zoom_fit()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            steps = e.angleDelta().y() / 120.0
            self.set_zoom(self.transform().m11() * (1.1 ** steps))
            e.accept()
            return
        sb = self.verticalScrollBar()
        dy = e.angleDelta().y()
        # like PowerPoint: when the slide fits (or the scroll is at its end) the wheel turns the page
        if self.editing is None and dy and ((dy < 0 and sb.value() >= sb.maximum()) or
                                            (dy > 0 and sb.value() <= sb.minimum()) or self.fit):
            self._wheel_acc = getattr(self, "_wheel_acc", 0) + dy
            if abs(self._wheel_acc) >= 120:
                self.slideStep.emit(-1 if self._wheel_acc > 0 else 1)
                self._wheel_acc = 0
            e.accept()
            return
        super().wheelEvent(e)

    # ---- hit testing -------------------------------------------------------------------------
    def px(self) -> float:
        return 1.0 / max(0.01, self.transform().m11())

    def shape_at(self, pos: QPointF) -> sm.Shape | None:
        if self.slide is None:
            return None
        tol = 4 * self.px()
        for s in reversed(self.slide.shapes):
            t = self.renderer.shape_transform(s, flips=False)
            inv, ok = t.inverted()
            if not ok:
                continue
            lp = inv.map(pos)
            w, h = sm.pt(s.cx), sm.pt(s.cy)
            if is_line(s):
                a, b = line_points(s)
                if _dist_to_segment(pos, a, b) <= max(tol, 3 * self.px()):
                    return s
                continue
            if s.kind == "table" and s.table is not None:
                hh = self.renderer.table_height(s, self.renderer.ctx(self.slide, s))
                if -tol <= lp.x() <= w + tol and -tol <= lp.y() <= hh + tol:
                    return s
                continue
            if not (-tol <= lp.x() <= w + tol and -tol <= lp.y() <= h + tol):
                continue
            if s.kind == "sp" and not s.fill and not s.ph and not s.txbox and (s.text is None or s.text.is_empty()):
                # an outline-only shape: grab it at its line
                path = self.renderer.shape_path(s)
                ps = QPainterPathStroker()
                ps.setWidth(max(6 * self.px(), sm.pt((s.line or {}).get("width") or 9525) + 4 * self.px()))
                if ps.createStroke(path).contains(lp):
                    return s
                continue
            return s
        return None

    def on_border(self, s: sm.Shape, pos: QPointF) -> bool:
        t = self.renderer.shape_transform(s, flips=False)
        inv, _ok = t.inverted()
        lp = inv.map(pos)
        w, h = sm.pt(s.cx), sm.pt(s.cy)
        g = BORDER_GRIP * self.px()
        return lp.x() < g or lp.y() < g or lp.x() > w - g or lp.y() > h - g

    def handle_at(self, pos: QPointF):
        tol = (HANDLE / 2 + 3) * self.px()
        for s in self.selection:
            if is_line(s):
                a, b = line_points(s)
                if QLineF(pos, a).length() <= tol:
                    return s, "p0"
                if QLineF(pos, b).length() <= tol:
                    return s, "p1"
                continue
            t = self.renderer.shape_transform(s, flips=False)
            for name, pt in self.overlay.handle_points(s, t).items():
                if QLineF(pos, pt).length() <= tol:
                    return s, name
        return None

    # ---- selection ---------------------------------------------------------------------------
    def select(self, shapes: list, emit=True):
        self.selection = [s for s in shapes if s is not None]
        self.cell_range = None
        self.overlay.update()
        if emit:
            self.selectionChanged.emit()

    def select_all(self):
        if self.editing is not None:
            c = self.editing.textCursor()
            c.select(QTextCursor.Document)
            self.editing.setTextCursor(c)
            return
        if self.slide is not None:
            self.select(list(self.slide.shapes))

    # ---- mouse -------------------------------------------------------------------------------
    def mousePressEvent(self, e):
        if self.slide is None:
            return
        pos = self.mapToScene(e.position().toPoint())
        self.setFocus()
        if e.button() == Qt.RightButton:
            if self.editing is not None and self._in_edit_item(e):
                super().mousePressEvent(e)
                return
            s = self.shape_at(pos)
            if s is not None and s not in self.selection:
                self.end_edit()
                self.select([s])
            elif s is None:
                self.end_edit()
                self.select([])
            return
        if e.button() != Qt.LeftButton:
            return
        if self.draw_geom is not None:
            self.draw_start = self.draw_end = self.snap(pos)
            self.draw_preview = QRectF(self.draw_start, self.draw_start)
            self.drag = ("draw",)
            return
        if self.editing is not None:
            if self._in_edit_item(e):
                super().mousePressEvent(e)
                return
            h = self.handle_at(pos)
            if h is not None and h[0] is self.editing.shape:
                self.end_edit(keep_selection=True)
                self._start_handle(h, pos)
                return
            if self.editing.cell is not None and self.shape_at(pos) is self.editing.shape:
                cell = self.cell_at(self.editing.shape, pos)
                if cell is not None:
                    self.end_edit(keep_selection=True)
                    self.begin_edit(self.selection[0] if self.selection else self.editing.shape, pos, cell)
                    self.drag = ("cells", self.selection[0] if self.selection else None, cell)
                    return
            if self.on_border(self.editing.shape, pos) and self.shape_at(pos) is self.editing.shape:
                shape = self.editing.shape
                self.end_edit(keep_selection=True)
                self.select([shape])
                self._start_move(pos, e)
                return
            self.end_edit()
        h = self.handle_at(pos)
        if h is not None:
            self._start_handle(h, pos)
            return
        s = self.shape_at(pos)
        mods = e.modifiers()
        if s is None:
            if not mods & (Qt.ShiftModifier | Qt.ControlModifier):
                self.select([])
            self.band = QRectF(pos, pos)
            self.drag = ("band", pos, list(self.selection))
            return
        if mods & (Qt.ShiftModifier | Qt.ControlModifier):
            if s in self.selection and mods & Qt.ShiftModifier:
                self.select([x for x in self.selection if x is not s])
                return
            if s not in self.selection:
                self.select(self.selection + [s])
            self._start_move(pos, e)
            return
        if s.kind == "table" and s.table is not None:
            cell = self.cell_at(s, pos)
            if cell is not None and not self.on_border(s, pos):
                self.select([s], emit=False)
                self.begin_edit(s, pos, cell)
                self.drag = ("cells", s, cell)
                return
        if edits_on_click(s) and not self.on_border(s, pos) and s not in self.selection[1:]:
            self.select([s], emit=False)
            self.begin_edit(s, pos)
            return
        if s not in self.selection:
            self.select([s])
        self._start_move(pos, e)

    def _in_edit_item(self, e) -> bool:
        if self.editing is None:
            return False
        item = self.itemAt(e.position().toPoint())
        if item is self.editing:
            return True
        # the whole text area of the shape counts (below short text too)
        pos = self.mapToScene(e.position().toPoint())
        s = self.editing.shape
        if self.editing.cell is not None:
            return self.cell_at(s, pos) == self.editing.cell
        if self.shape_at(pos) is s and not self.on_border(s, pos):
            return True
        return False

    def _start_move(self, pos, e):
        self.drag = ("move", pos, [(s, s.x, s.y) for s in self.selection], False,
                     bool(e.modifiers() & Qt.ControlModifier))

    def _start_handle(self, h, pos):
        s, name = h
        if name == "rot":
            t = self.renderer.shape_transform(s, flips=False)
            c = t.map(QPointF(sm.pt(s.cx) / 2, sm.pt(s.cy) / 2))
            self.drag = ("rot", s, c, math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x())), s.rot, False)
        elif name in ("p0", "p1"):
            self.drag = ("line", s, name, False)
        else:
            self.drag = ("size", s, name, (s.x, s.y, s.cx, s.cy, s.flip_h, s.flip_v),
                         [(o, o.x, o.y, o.cx, o.cy) for o in self.selection], False)

    def mouseMoveEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        d = self.drag
        if d is None:
            if self.editing is not None and self._in_edit_item(e):
                super().mouseMoveEvent(e)
                if not (e.buttons() & Qt.LeftButton):
                    self.viewport().setCursor(Qt.IBeamCursor)
                return
            self._hover_cursor(pos)
            if e.buttons() & Qt.LeftButton:
                super().mouseMoveEvent(e)
            return
        kind = d[0]
        if kind == "draw":
            self.draw_end = self.snap(pos)
            if e.modifiers() & Qt.ShiftModifier and self.draw_geom not in geom.LINE_SHAPES:
                dx, dy = self.draw_end.x() - self.draw_start.x(), self.draw_end.y() - self.draw_start.y()
                m = max(abs(dx), abs(dy))
                self.draw_end = QPointF(self.draw_start.x() + math.copysign(m, dx or 1),
                                        self.draw_start.y() + math.copysign(m, dy or 1))
            self.draw_preview = QRectF(self.draw_start, self.draw_end)
            self.overlay.update()
        elif kind == "band":
            self.band = QRectF(d[1], pos)
            self.overlay.update()
        elif kind == "cells":
            s, start = d[1], d[2]
            cell = self.cell_at(s, pos)
            if cell is not None and cell != start:
                if self.editing is not None:
                    self.end_edit(keep_selection=True)
                self.cell_range = (s, (start[0], start[1], cell[0], cell[1]))
                self.overlay.update()
                self.selectionChanged.emit()
        elif kind == "move":
            start, items, started, dup = d[1], d[2], d[3], d[4]
            delta = pos - start
            if not started:
                if abs(delta.x()) + abs(delta.y()) < 3 * self.px():
                    return
                self.host.begin_change("Move")
                if dup:
                    clones = []
                    for s, x, y in items:
                        c = s.clone()
                        c.inherit = False
                        self.slide.shapes.append(c)
                        clones.append((c, x, y))
                    items = clones
                    self.select([c for c, _x, _y in clones], emit=False)
                self.drag = ("move", start, items, True, dup)
            if e.modifiers() & Qt.ShiftModifier:
                if abs(delta.x()) > abs(delta.y()):
                    delta.setY(0)
                else:
                    delta.setX(0)
            for s, x, y in items:
                nx, ny = x + sm.emu(delta.x()), y + sm.emu(delta.y())
                if self.grid and not e.modifiers() & Qt.AltModifier:
                    nx = sm.emu(round(sm.pt(nx) / 6) * 6)
                    ny = sm.emu(round(sm.pt(ny) / 6) * 6)
                s.x, s.y = nx, ny
                s.inherit = False
            self.refresh()
        elif kind == "rot":
            s, c, a0, r0, started = d[1], d[2], d[3], d[4], d[5]
            if not started:
                self.host.begin_change("Rotate")
                self.drag = ("rot", s, c, a0, r0, True)
            a = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))
            r = (r0 + a - a0) % 360
            if e.modifiers() & Qt.ShiftModifier:
                r = round(r / 15) * 15 % 360
            s.rot = r
            s.inherit = False
            self.refresh()
        elif kind == "line":
            s, name, started = d[1], d[2], d[3]
            if not started:
                self.host.begin_change("Size")
                self.drag = ("line", s, name, True)
            a, b = line_points(s)
            p = self.snap(pos)
            if e.modifiers() & Qt.ShiftModifier:
                other = b if name == "p0" else a
                ang = math.degrees(math.atan2(p.y() - other.y(), p.x() - other.x()))
                ang = math.radians(round(ang / 45) * 45)
                ln = QLineF(other, p).length()
                p = QPointF(other.x() + math.cos(ang) * ln, other.y() + math.sin(ang) * ln)
            if name == "p0":
                a = p
            else:
                b = p
            set_line_points(s, a, b)
            self.refresh()
        elif kind == "size":
            s, name, orig, group, started = d[1], d[2], d[3], d[4], d[5]
            if not started:
                self.host.begin_change("Size")
                self.drag = ("size", s, name, orig, group, True)
            if len(group) > 1:
                self._resize_group(group, name, pos, e)
            else:
                self._resize_one(s, name, orig, self.snap(pos), e)
            self.refresh()

    def _resize_one(self, s, name, orig, pos, e):
        x, y, cx, cy, fh, fv = orig
        w, h = sm.pt(cx), sm.pt(cy)
        ang = math.radians(s.rot)
        ca, sa = math.cos(ang), math.sin(ang)
        cxp, cyp = sm.pt(x) + w / 2, sm.pt(y) + h / 2
        sx = {"l": -1, "tl": -1, "bl": -1, "r": 1, "tr": 1, "br": 1}.get(name, 0)
        sy = {"t": -1, "tl": -1, "tr": -1, "b": 1, "bl": 1, "br": 1}.get(name, 0)
        # the fixed point: the opposite handle, in scene coordinates
        ax_l, ay_l = -sx * w / 2, -sy * h / 2
        ax = cxp + ax_l * ca - ay_l * sa
        ay = cyp + ax_l * sa + ay_l * ca
        vx, vy = pos.x() - ax, pos.y() - ay
        lx = vx * ca + vy * sa          # the mouse relative to the fixed point, in the shape's frame
        ly = -vx * sa + vy * ca
        nw = abs(lx) if sx else w
        nh = abs(ly) if sy else h
        keep = bool(e.modifiers() & Qt.ShiftModifier) or (s.kind == "pic" and sx and sy)
        if keep and w > 0 and h > 0:
            ratio = w / h
            if sx and sy:
                if nw / ratio > nh:
                    nh = nw / ratio
                else:
                    nw = nh * ratio
            elif sx:
                nh = nw / ratio
            else:
                nw = nh * ratio
        nw, nh = max(1.0, nw), max(1.0, nh)
        lx_s = math.copysign(nw, lx if lx else sx) if sx else 0.0
        ly_s = math.copysign(nh, ly if ly else sy) if sy else 0.0
        ncx = ax + (lx_s / 2) * ca - (ly_s / 2) * sa
        ncy = ay + (lx_s / 2) * sa + (ly_s / 2) * ca
        flip_x = bool(sx) and lx * sx < 0
        flip_y = bool(sy) and ly * sy < 0
        s.cx, s.cy = sm.emu(nw), sm.emu(nh)
        s.x, s.y = sm.emu(ncx - nw / 2), sm.emu(ncy - nh / 2)
        if s.kind not in ("table", "pic"):
            s.flip_h = fh ^ flip_x
            s.flip_v = fv ^ flip_y
        s.inherit = False
        if s.kind == "table" and s.table is not None:
            self._scale_table(s, cx, cy)

    def _scale_table(self, s, old_cx, old_cy):
        t = s.table
        if old_cx and sum(t.col_widths):
            k = s.cx / sum(t.col_widths)
            t.col_widths = [max(12700, int(w * k)) for w in t.col_widths]
        if old_cy and sum(t.row_heights):
            k = s.cy / sum(t.row_heights)
            t.row_heights = [max(12700, int(h * k)) for h in t.row_heights]

    def _resize_group(self, group, name, pos, e):
        x0 = min(o[1] for o in group)
        y0 = min(o[2] for o in group)
        x1 = max(o[1] + o[3] for o in group)
        y1 = max(o[2] + o[4] for o in group)
        bw, bh = max(1, x1 - x0), max(1, y1 - y0)
        px, py = sm.emu(pos.x()), sm.emu(pos.y())
        nx0, ny0, nx1, ny1 = x0, y0, x1, y1
        if "l" in name:
            nx0 = min(px, x1 - 12700)
        if "r" in name:
            nx1 = max(px, x0 + 12700)
        if name.startswith("t"):
            ny0 = min(py, y1 - 12700)
        if name.startswith("b"):
            ny1 = max(py, y0 + 12700)
        kx, ky = (nx1 - nx0) / bw, (ny1 - ny0) / bh
        for o, x, y, cx, cy in group:
            o.x = int(nx0 + (x - x0) * kx)
            o.y = int(ny0 + (y - y0) * ky)
            o.cx = max(12700, int(cx * kx))
            o.cy = max(12700, int(cy * ky))
            o.inherit = False

    def mouseReleaseEvent(self, e):
        d = self.drag
        self.drag = None
        if d is None:
            super().mouseReleaseEvent(e)
            self.formatChanged.emit()
            return
        kind = d[0]
        if kind == "draw":
            self._finish_draw(e)
        elif kind == "band":
            r = self.band.normalized() if self.band is not None else QRectF()
            self.band = None
            if r.width() > 2 * self.px() or r.height() > 2 * self.px():
                inside = []
                for s in self.slide.shapes:
                    poly = _shape_poly(s, self.renderer.shape_transform(s, flips=False))
                    if all(r.contains(q) for q in poly):
                        inside.append(s)
                base = d[2] if e.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier) else []
                self.select(base + [s for s in inside if s not in base])
            self.overlay.update()
        elif kind == "cells":
            self.selectionChanged.emit()
        elif kind == "move" and d[3]:
            self.host.end_change()
        elif kind in ("rot", "line") and d[-1]:
            self.host.end_change()
        elif kind == "size" and d[5]:
            s = d[1]
            if s.kind == "sp" and s.text is not None and s.text.autofit == "norm":
                self.autofit(s)
            self.host.end_change()
        self.refresh()
        self.selectionChanged.emit()

    def mouseDoubleClickEvent(self, e):
        pos = self.mapToScene(e.position().toPoint())
        if self.editing is not None and self._in_edit_item(e):
            super().mouseDoubleClickEvent(e)
            return
        s = self.shape_at(pos)
        if s is not None and text_capable(s) and self.editing is None:
            self.select([s], emit=False)
            self.begin_edit(s, pos)
            return
        if s is not None and s.kind == "pic":
            self.host.picture_double_clicked(s)
            return
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e):
        self.context_menu_requested.emit(e.globalPos())

    def _hover_cursor(self, pos):
        if self.draw_geom is not None:
            self.viewport().setCursor(Qt.CrossCursor)
            return
        h = self.handle_at(pos)
        if h is not None:
            s, name = h
            if name == "rot":
                self.viewport().setCursor(Qt.PointingHandCursor)
                return
            if name in ("p0", "p1"):
                self.viewport().setCursor(Qt.SizeAllCursor)
                return
            ang = {"l": 0, "r": 0, "t": 90, "b": 90, "tl": 45, "br": 45, "tr": 135, "bl": 135}[name]
            ang = (ang + s.rot) % 180
            cur = Qt.SizeHorCursor if ang < 22.5 or ang >= 157.5 else (
                Qt.SizeFDiagCursor if ang < 67.5 else (Qt.SizeVerCursor if ang < 112.5 else Qt.SizeBDiagCursor))
            self.viewport().setCursor(cur)
            return
        s = self.shape_at(pos)
        if s is None:
            self.viewport().setCursor(Qt.ArrowCursor)
        elif (edits_on_click(s) or s.kind == "table") and not self.on_border(s, pos):
            self.viewport().setCursor(Qt.IBeamCursor)
        else:
            self.viewport().setCursor(Qt.SizeAllCursor)

    def snap(self, pos: QPointF) -> QPointF:
        if not self.grid:
            return pos
        step = 6.0
        return QPointF(round(pos.x() / step) * step, round(pos.y() / step) * step)

    # ---- drawing new shapes ------------------------------------------------------------------
    def start_draw(self, geom_name: str):
        self.end_edit()
        self.draw_geom = geom_name
        self.viewport().setCursor(Qt.CrossCursor)

    def cancel_draw(self):
        self.draw_geom = None
        self.draw_preview = None
        self.viewport().unsetCursor()
        self.overlay.update()

    def _finish_draw(self, e):
        g = self.draw_geom
        a, b = self.draw_start, self.draw_end
        self.draw_geom = None
        self.draw_preview = None
        self.viewport().unsetCursor()
        click = QLineF(a, b).length() < 3 * self.px()
        self.host.begin_change("Insert Shape" if g != "textBox" else "Insert Text Box")
        if g == "textBox":
            s = sm.Shape(kind="sp", txbox=True, name="TextBox")
            s.text = sm.TextBody(wrap=not click, autofit="shape", anchor="t")
            s.text.paragraphs = [sm.Paragraph()]
            if click:
                s.x, s.y, s.cx, s.cy = sm.emu(a.x()), sm.emu(a.y()), sm.emu(20), sm.emu(28)
            else:
                r = QRectF(a, b).normalized()
                s.x, s.y, s.cx, s.cy = sm.emu(r.x()), sm.emu(r.y()), sm.emu(max(20, r.width())), sm.emu(28)
            s.fill, s.line = None, None
            s.name = f"TextBox {len(self.slide.shapes) + 1}"
            self.slide.shapes.append(s)
            self.host.end_change()
            self.select([s], emit=False)
            self.begin_edit(s)
            self.autosize(s)
            self.shapeDrawn.emit()
            return
        s = new_shape(g)
        if g in geom.LINE_SHAPES:
            if click:
                b = QPointF(a.x() + 72, a.y())
            set_line_points(s, a, b)
        elif click:
            s.x, s.y, s.cx, s.cy = sm.emu(a.x()), sm.emu(a.y()), sm.emu(72), sm.emu(72)
        else:
            r = QRectF(a, b).normalized()
            s.x, s.y, s.cx, s.cy = sm.emu(r.x()), sm.emu(r.y()), sm.emu(max(2, r.width())), sm.emu(max(2, r.height()))
        s.name = f"{geom.LABELS.get(g, 'Shape')} {len(self.slide.shapes) + 1}"
        self.slide.shapes.append(s)
        self.host.end_change()
        self.select([s])
        self.refresh()
        self.shapeDrawn.emit()

    # ---- text editing ------------------------------------------------------------------------
    def cell_at(self, s: sm.Shape, pos: QPointF):
        if s.kind != "table" or s.table is None:
            return None
        xs, ys = self.renderer.table_geometry(s, self.renderer.ctx(self.slide, s))
        t = self.renderer.shape_transform(s, flips=False)
        inv, _ok = t.inverted()
        lp = inv.map(pos)
        ci = next((i for i in range(len(xs) - 1) if xs[i] <= lp.x() < xs[i + 1]), None)
        ri = next((i for i in range(len(ys) - 1) if ys[i] <= lp.y() < ys[i + 1]), None)
        if ci is None or ri is None:
            return None
        # a merged cell belongs to the cell that spans it
        row = s.table.rows[ri]
        for c in range(ci, -1, -1):
            if c < len(row) and not row[c].merged and c + max(1, row[c].span) > ci:
                return ri, c
        return ri, ci

    def begin_edit(self, s: sm.Shape, pos: QPointF | None = None, cell: tuple | None = None):
        self.end_edit(keep_selection=True)
        if s not in self.selection:
            self.selection = [s]
        self._edit_snapshot = self.host.begin_change("Typing")
        ctx = self.renderer.ctx(self.slide, s, self.number, editing=True)
        w, h = sm.pt(s.cx), sm.pt(s.cy)
        if cell is not None:
            ri, ci = cell
            tcell = s.table.rows[ri][ci]
            xs, ys = self.renderer.table_geometry(s, ctx)
            x1 = xs[min(len(xs) - 1, ci + max(1, tcell.span))]
            y1 = ys[min(len(ys) - 1, ri + max(1, tcell.row_span))]
            l, t_, r, b = (sm.pt(v) for v in tcell.margins)
            area = QRectF(xs[ci] + l, ys[ri] + t_, max(1.0, x1 - xs[ci] - l - r), max(1.0, y1 - ys[ri] - t_ - b))
            ctx = self.renderer.cell_ctx(ctx, s, ri, ci)
            body = tcell.text
            body.anchor = tcell.anchor
            if getattr(ctx, "_header", False) and s.table.first_row and ri == 0:
                body = sr._bold_body(body)
        else:
            if s.text is None:
                s.text = sm.TextBody(anchor="ctr")
                s.text.paragraphs = [sm.Paragraph(align="ctr")]
            body = s.text
            area = st.text_area(w, h, body, geom.text_rect(s.geom or "rect", w, h) if not s.path else None)
            if s.text.autofit == "shape" and not s.text.wrap:
                area.setWidth(max(area.width(), 10000))
        item = TextEditItem(self, s, body, ctx, area, cell)
        if cell is not None:
            item.cell_body = s.table.rows[cell[0]][cell[1]].text
        self._scene.addItem(item)
        self.editing = item
        item.setFocus()
        if self.speller is not None:
            try:
                self.speller.setDocument(item.document())
            except RuntimeError:
                pass
        c = item.textCursor()
        if pos is not None:
            lp = item.mapFromScene(pos)
            hit = item.document().documentLayout().hitTest(lp, Qt.FuzzyHit)
            if hit >= 0:
                c.setPosition(hit)
            else:
                c.movePosition(QTextCursor.End)
        else:
            c.movePosition(QTextCursor.End)
        fix_cursor_format(c)
        item.setTextCursor(c)
        item.document().cursorPositionChanged.connect(lambda _c: self.formatChanged.emit())
        item.document().contentsChanged.connect(self.formatChanged.emit)
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(150)
        self._cursor_timer.timeout.connect(self._check_cursor)
        self._last_cursor = None
        self._cursor_timer.start()
        self.refresh()
        self.editingChanged.emit(True)
        self.formatChanged.emit()
        self.selectionChanged.emit()

    def _check_cursor(self):
        if self.editing is None:
            return
        c = self.editing.textCursor()
        key = (c.position(), c.anchor())
        if key != self._last_cursor:
            self._last_cursor = key
            self.formatChanged.emit()

    def text_changed_live(self, item: TextEditItem):
        """While typing: a growing text box follows its text."""
        s = item.shape
        if item.cell is None and s.text is not None and s.text.autofit == "shape":
            doc = item.document()
            l, t, r, b = (sm.pt(v) for v in s.text.insets)
            need_h = doc.size().height() + t + b
            changed = False
            if abs(sm.pt(s.cy) - need_h) > 0.5:
                s.cy = sm.emu(need_h)
                changed = True
            if not s.text.wrap:
                need_w = doc.idealWidth() + l + r + 2
                if abs(sm.pt(s.cx) - need_w) > 0.5:
                    s.cx = sm.emu(need_w)
                    changed = True
            if changed:
                item.area = st.text_area(sm.pt(s.cx), sm.pt(s.cy), s.text)
                if not s.text.wrap:
                    item.area.setWidth(max(item.area.width(), 10000))
                t2 = self.renderer.shape_transform(s, flips=False)
                tt = QTransform().translate(item.area.left(), item.area.top())
                item.setTransform(tt * t2)
                self.overlay.update()
        elif item.cell is not None:
            self.slide_item.update()

    def end_edit(self, keep_selection: bool = False):
        item = self.editing
        if item is None:
            return
        self.editing = None
        if hasattr(self, "_cursor_timer"):
            self._cursor_timer.stop()
        s = item.shape
        doc = item.document()
        if item.cell is not None:
            ri, ci = item.cell
            cell = s.table.rows[ri][ci]
            cell.text = st.from_document(doc, cell.text)
            if getattr(item.ctx, "_header", False):
                for par in cell.text.paragraphs:      # the header's bold comes from the style
                    for r in par.runs:
                        if r.bold is True:
                            r.bold = None
        else:
            s.text = st.from_document(doc, s.text)
            if s.text.autofit == "norm":
                self.autofit(s)
            elif s.text.autofit == "shape":
                self.autosize(s)
            if s.txbox and s.ph is None and s.text.is_empty():
                # an empty text box goes away when you leave it (PowerPoint)
                if s in self.slide.shapes:
                    self.slide.shapes.remove(s)
                    self.selection = [x for x in self.selection if x is not s]
        if self.speller is not None:
            try:
                self.speller.setDocument(None)
            except RuntimeError:
                pass
        self._scene.removeItem(item)
        item.deleteLater()
        self.host.end_change()
        if not keep_selection:
            self.selection = []
        self.refresh()
        self.editingChanged.emit(False)
        self.selectionChanged.emit()

    def autofit(self, s: sm.Shape):
        ctx = self.renderer.ctx(self.slide, s, self.number)
        w, h = sm.pt(s.cx), sm.pt(s.cy)
        area = st.text_area(w, h, s.text)
        trial = copy.copy(s.text)
        trial.font_scale, trial.line_reduction = 1.0, 0.0
        s.text.font_scale, s.text.line_reduction = st.fit_scale(trial, ctx, area)

    def autosize(self, s: sm.Shape):
        if s.text is None:
            return
        ctx = self.renderer.ctx(self.slide, s, self.number)
        l, t, r, b = (sm.pt(v) for v in s.text.insets)
        doc = st.to_document(s.text, ctx, sm.pt(s.cx) - l - r if s.text.wrap else None)
        s.cy = sm.emu(doc.size().height() + t + b)
        if not s.text.wrap:
            s.cx = sm.emu(max(20.0, doc.idealWidth() + l + r + 2))

    def text_key(self, item: TextEditItem, e) -> bool:
        """Keys with a PowerPoint meaning while typing; True when handled."""
        k = e.key()
        mods = e.modifiers()
        if k == Qt.Key_Escape:
            shape = item.shape
            self.end_edit(keep_selection=True)
            self.select([shape])
            return True
        if item.cell is not None and k in (Qt.Key_Tab, Qt.Key_Backtab):
            self.next_cell(item, back=(k == Qt.Key_Backtab or bool(mods & Qt.ShiftModifier)))
            return True
        if k in (Qt.Key_Tab, Qt.Key_Backtab) and item.cell is None:
            c = item.textCursor()
            at_start = c.positionInBlock() == 0 and not c.hasSelection()
            multi = c.hasSelection() and c.document().findBlock(c.selectionStart()) != c.document().findBlock(c.selectionEnd())
            back = k == Qt.Key_Backtab or bool(mods & Qt.ShiftModifier)
            if at_start or multi or back:
                self.change_level(-1 if back else 1)
                return True
        if k in (Qt.Key_Return, Qt.Key_Enter) and mods & Qt.ShiftModifier:
            item.textCursor().insertText(" ")
            return True
        if e.matches(QKeySequence.Paste):
            self.host.paste()
            return True
        return False

    def change_level(self, step: int):
        if self.editing is None:
            return
        c = self.editing.textCursor()
        for block in st.selected_blocks(c):
            lvl = int(block.blockFormat().property(st.P_LEVEL) or 0)
            st.set_para_prop(c, self.editing.ctx, "level", lvl + step, blocks=[block])
        self.editing.reposition()
        self.editing.update()

    def next_cell(self, item: TextEditItem, back=False):
        s = item.shape
        ri, ci = item.cell
        t = s.table
        self.end_edit(keep_selection=True)
        cells = [(r, c) for r in range(len(t.rows)) for c in range(len(t.rows[r])) if not t.rows[r][c].merged]
        i = cells.index((ri, ci)) if (ri, ci) in cells else 0
        i += -1 if back else 1
        if i >= len(cells):
            self.host.begin_change("Insert Row")
            add_row(t, len(t.rows) - 1, below=True)
            s.cy = sum(t.row_heights)
            self.host.end_change()
            cells = [(r, c) for r in range(len(t.rows)) for c in range(len(t.rows[r])) if not t.rows[r][c].merged]
        i = max(0, min(len(cells) - 1, i))
        self.begin_edit(s, None, cells[i])
        c = self.editing.textCursor()
        c.select(QTextCursor.Document)
        self.editing.setTextCursor(c)

    # ---- keys --------------------------------------------------------------------------------
    def keyPressEvent(self, e):
        if self.editing is not None:
            super().keyPressEvent(e)
            return
        k = e.key()
        if k == Qt.Key_Escape:
            if self.draw_geom is not None:
                self.cancel_draw()
            else:
                self.select([])
            return
        if k in (Qt.Key_PageDown, Qt.Key_PageUp) or (not self.selection and k in (Qt.Key_Down, Qt.Key_Up,
                                                                                    Qt.Key_Right, Qt.Key_Left)):
            self.slideStep.emit(1 if k in (Qt.Key_PageDown, Qt.Key_Down, Qt.Key_Right) else -1)
            return
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            if self.cell_range is not None:
                self.host.clear_cells()
                return
            if self.selection:
                self.host.delete_selection()
            return
        if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.selection:
            step = 1 if e.modifiers() & Qt.ControlModifier else 6
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            self.host.begin_change("Move")
            for s in self.selection:
                s.x += sm.emu(dx)
                s.y += sm.emu(dy)
                s.inherit = False
            self.host.end_change()
            self.refresh()
            return
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2) and len(self.selection) == 1 and \
                text_capable(self.selection[0]):
            self.begin_edit(self.selection[0])
            c = self.editing.textCursor()
            c.select(QTextCursor.Document)
            self.editing.setTextCursor(c)
            return
        if k in (Qt.Key_Tab, Qt.Key_Backtab) and self.slide is not None and self.slide.shapes:
            shapes = self.slide.shapes
            i = shapes.index(self.selection[0]) if self.selection and self.selection[0] in shapes else -1
            i = (i + (-1 if k == Qt.Key_Backtab else 1)) % len(shapes)
            self.select([shapes[i]])
            return
        text = e.text()
        if text and text.isprintable() and len(self.selection) == 1 and text_capable(self.selection[0]) and \
                not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            # typing with a shape selected replaces its text
            s = self.selection[0]
            self.begin_edit(s)
            c = self.editing.textCursor()
            c.select(QTextCursor.Document)
            c.insertText(text)
            self.editing.setTextCursor(c)
            return
        super().keyPressEvent(e)

    def focusNextPrevChild(self, nxt):
        return False

    def _tab_key(self, e) -> bool:
        """Tab and Shift+Tab belong to the slide (list levels, next cell, next shape), never to
        moving the keyboard focus to another part of the window."""
        if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Tab, Qt.Key_Backtab) and \
                not e.modifiers() & (Qt.ControlModifier | Qt.AltModifier):
            if self.editing is not None:
                if not self.text_key(self.editing, e):
                    self.editing.textCursor().insertText("\t")
            else:
                self.keyPressEvent(e)
            return True
        return False

    def event(self, e):
        if self._tab_key(e):
            return True
        return super().event(e)

    def viewportEvent(self, e):
        if self._tab_key(e):
            return True
        return super().viewportEvent(e)

    # ---- drops: pictures from Explorer --------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        pos = self.mapToScene(e.position().toPoint())
        if md.hasUrls():
            files = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if files:
                self.host.insert_picture_files(files, pos)
                e.acceptProposedAction()
                return
        if md.hasImage():
            self.host.insert_image(md.imageData(), pos)
            e.acceptProposedAction()


def fix_cursor_format(c: QTextCursor):
    """Typing at the start of a paragraph takes the paragraph's format (Qt would use an empty one)."""
    if c.hasSelection() or not c.atBlockStart():
        return
    block = c.block()
    it = block.begin()
    fmt = it.fragment().charFormat() if not it.atEnd() else block.charFormat()
    c.setCharFormat(fmt)


def _dist_to_segment(p: QPointF, a: QPointF, b: QPointF) -> float:
    ab = b - a
    ln2 = ab.x() ** 2 + ab.y() ** 2
    if ln2 == 0:
        return QLineF(p, a).length()
    t = max(0.0, min(1.0, ((p.x() - a.x()) * ab.x() + (p.y() - a.y()) * ab.y()) / ln2))
    proj = QPointF(a.x() + ab.x() * t, a.y() + ab.y() * t)
    return QLineF(p, proj).length()


# ---- new things ----------------------------------------------------------------------------------
def new_shape(g: str) -> sm.Shape:
    """A shape as PowerPoint 2007 draws it: accent 1 fill, darker outline, white centred text."""
    s = sm.Shape(kind="sp", geom=g)
    if g in geom.LINE_SHAPES:
        s.line = {"color": sm.scheme("accent1"), "width": 9525, "dash": "solid"}
        if g == "straightConnector1":
            s.line["tail"] = "triangle"
        elif g == "doubleArrowLine":
            s.geom = "straightConnector1"
            s.line["head"] = "triangle"
            s.line["tail"] = "triangle"
        s.fill = None
        return s
    if g in geom.OPEN_SHAPES:
        s.fill = None
        s.line = {"color": sm.scheme("accent1"), "width": 9525, "dash": "solid"}
        return s
    s.fill = {"type": "solid", "color": sm.scheme("accent1")}
    s.line = {"color": sm.scheme("accent1", ("shade", 50000)), "width": 25400, "dash": "solid"}
    s.style_text_color = sm.scheme("lt1")
    s.text = sm.TextBody(anchor="ctr", paragraphs=[sm.Paragraph(align="ctr")])
    return s


def new_table(rows: int, cols: int, x: int, y: int, width: int) -> sm.Shape:
    t = sm.Table(col_widths=[width // cols] * cols, row_heights=[370840] * rows)
    t.rows = [[sm.TableCell() for _c in range(cols)] for _r in range(rows)]
    s = sm.Shape(kind="table", name="Table", x=x, y=y, cx=width, cy=370840 * rows)
    s.table = t
    return s


def add_row(t: sm.Table, at: int, below: bool):
    i = at + 1 if below else at
    src = t.rows[min(max(0, at), len(t.rows) - 1)]
    row = []
    for c in src:
        cell = sm.TableCell(fill=copy.deepcopy(c.fill), anchor=c.anchor, margins=c.margins, span=c.span,
                            merged=c.merged and c.row_span <= 1 and c.span <= 1 and False)
        row.append(cell)
    t.rows.insert(i, row)
    t.row_heights.insert(i, t.row_heights[min(max(0, at), len(t.row_heights) - 1)] if t.row_heights else 370840)


def add_col(t: sm.Table, at: int, right: bool):
    i = at + 1 if right else at
    w = t.col_widths[min(max(0, at), len(t.col_widths) - 1)] if t.col_widths else 914400
    t.col_widths.insert(i, w)
    for row in t.rows:
        row.insert(min(i, len(row)), sm.TableCell())
