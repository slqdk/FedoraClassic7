"""Photo Viewer: the painted buttons of the bottom bar (Windows 7 Photo Viewer look)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import QAbstractButton

BLUE_TOP, BLUE_BOTTOM, BLUE_EDGE = QColor("#6FA8E8"), QColor("#1C5AA8"), QColor("#123E77")
GRAY_TOP, GRAY_BOTTOM, GRAY_EDGE = QColor("#6D7F99"), QColor("#30435E"), QColor("#1F2C3F")
RED_TOP, RED_BOTTOM, RED_EDGE = QColor("#F0705E"), QColor("#B8231A"), QColor("#7A140E")


def _fill(p: QPainter, path: QPainterPath, top: QColor, bottom: QColor, edge: QColor):
    r = path.boundingRect()
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, top)
    g.setColorAt(1, bottom)
    p.setPen(QPen(edge, 1.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(QBrush(g))
    p.drawPath(path)
    # a glassy shine over the upper half
    p.save()
    p.setClipPath(path)
    shine = QLinearGradient(r.topLeft(), QPointF(r.left(), r.center().y()))
    shine.setColorAt(0, QColor(255, 255, 255, 120))
    shine.setColorAt(1, QColor(255, 255, 255, 20))
    p.setPen(Qt.NoPen)
    p.setBrush(shine)
    p.drawRect(QRectF(r.left(), r.top(), r.width(), r.height() / 2))
    p.restore()


def arrow_path(s: float, left: bool) -> QPainterPath:
    """A fat arrow pointing right (or left) in an s x s box."""
    m = s * 0.14
    w, h = s - 2 * m, s * 0.62
    top = (s - h) / 2
    shaft = h * 0.44
    head = w * 0.48
    pts = [QPointF(m, top + (h - shaft) / 2), QPointF(m + w - head, top + (h - shaft) / 2),
           QPointF(m + w - head, top), QPointF(m + w, top + h / 2), QPointF(m + w - head, top + h),
           QPointF(m + w - head, top + (h + shaft) / 2), QPointF(m, top + (h + shaft) / 2)]
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    path.closeSubpath()
    if left:
        path = QTransform(-1, 0, 0, 1, s, 0).map(path)
    return path


def rotate_path(s: float, clockwise: bool) -> QPainterPath:
    c = QPointF(s / 2, s / 2 + s * 0.04)
    r = s * 0.28
    arc = QPainterPath()
    start = 200          # degrees, Qt counts counter-clockwise from 3 o'clock
    span = -250
    rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    arc.arcMoveTo(rect, start)
    arc.arcTo(rect, start, span)
    st = QPainterPathStroker()
    st.setWidth(s * 0.13)
    st.setCapStyle(Qt.FlatCap)
    body = st.createStroke(arc)
    end = math.radians(start + span)
    ex, ey = c.x() + r * math.cos(end), c.y() - r * math.sin(end)
    # tangent direction (moving clockwise along the arc on screen)
    tx, ty = math.sin(end), math.cos(end)
    nx, ny = -ty, tx
    hw, hl = s * 0.2, s * 0.25
    head = QPainterPath(QPointF(ex + nx * hw, ey + ny * hw))
    head.lineTo(QPointF(ex + tx * hl, ey + ty * hl))
    head.lineTo(QPointF(ex - nx * hw, ey - ny * hw))
    head.closeSubpath()
    path = body.united(head).simplified()
    if not clockwise:
        path = QTransform(-1, 0, 0, 1, s, 0).map(path)
    return path


def flip_paths(s: float, vertical: bool) -> tuple[QPainterPath, QPainterPath]:
    m = s * 0.16
    gap = s * 0.06
    a = QPainterPath(QPointF(s / 2 - gap, m))
    a.lineTo(QPointF(s / 2 - gap, s - m))
    a.lineTo(QPointF(m, s - m))
    a.closeSubpath()
    b = QTransform(-1, 0, 0, 1, s, 0).map(a)
    if vertical:
        t = QTransform(0, 1, 1, 0, 0, 0)     # swap x and y
        a, b = t.map(a), t.map(b)
    return a, b


def x_path(s: float) -> QPainterPath:
    m = s * 0.22
    line = QPainterPath(QPointF(m, m))
    line.lineTo(QPointF(s - m, s - m))
    line.moveTo(QPointF(s - m, m))
    line.lineTo(QPointF(m, s - m))
    st = QPainterPathStroker()
    st.setWidth(s * 0.2)
    st.setCapStyle(Qt.SquareCap)
    return st.createStroke(line).simplified()


def paint_glyph(p: QPainter, kind: str, s: float, enabled: bool = True):
    p.setRenderHint(QPainter.Antialiasing)
    if not enabled:
        p.setOpacity(0.35)
    if kind in ("prev", "next"):
        _fill(p, arrow_path(s, kind == "prev"), BLUE_TOP, BLUE_BOTTOM, BLUE_EDGE)
    elif kind in ("rotcw", "rotccw"):
        _fill(p, rotate_path(s, kind == "rotcw"), BLUE_TOP, BLUE_BOTTOM, BLUE_EDGE)
    elif kind in ("fliph", "flipv"):
        a, b = flip_paths(s, kind == "flipv")
        _fill(p, a, BLUE_TOP, BLUE_BOTTOM, BLUE_EDGE)
        p.setPen(QPen(BLUE_EDGE, 1.0))
        p.setBrush(QColor(255, 255, 255, 150))
        p.drawPath(b)
        pen = QPen(GRAY_EDGE, 1.0, Qt.DashLine)
        p.setPen(pen)
        if kind == "fliph":
            p.drawLine(QPointF(s / 2, s * 0.08), QPointF(s / 2, s * 0.92))
        else:
            p.drawLine(QPointF(s * 0.08, s / 2), QPointF(s * 0.92, s / 2))
    elif kind == "delete":
        _fill(p, x_path(s), RED_TOP, RED_BOTTOM, RED_EDGE)
    elif kind == "zoom":
        ring = QPainterPath()
        c, r = QPointF(s * 0.42, s * 0.42), s * 0.24
        ring.addEllipse(c, r, r)
        st = QPainterPathStroker()
        st.setWidth(s * 0.1)
        handle = QPainterPath(QPointF(s * 0.6, s * 0.6))
        handle.lineTo(QPointF(s * 0.84, s * 0.84))
        st2 = QPainterPathStroker()
        st2.setWidth(s * 0.16)
        st2.setCapStyle(Qt.RoundCap)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(210, 230, 255, 170))
        p.drawEllipse(c, r, r)
        _fill(p, st.createStroke(ring).united(st2.createStroke(handle)).simplified(), GRAY_TOP, GRAY_BOTTOM,
              GRAY_EDGE)
    elif kind == "actual":       # "Actual size": 1:1
        f = p.font()
        f.setBold(True)
        f.setPixelSize(int(s * 0.42))
        p.setFont(f)
        path = QPainterPath()
        path.addText(0, 0, f, "1:1")
        br = path.boundingRect()
        path.translate(s / 2 - br.center().x(), s / 2 - br.center().y())
        _fill(p, path, GRAY_TOP, GRAY_BOTTOM, GRAY_EDGE)
    elif kind == "fit":          # "Fit to window": a frame with corner arrows
        m = s * 0.2
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(m, m + s * 0.06, s - 2 * m, s - 2 * m - s * 0.12), 2, 2)
        st = QPainterPathStroker()
        st.setWidth(s * 0.08)
        body = st.createStroke(frame)
        corners = QPainterPath()
        k = s * 0.16
        for (x, y, dx, dy) in ((m - 2, m, 1, 1), (s - m + 2, m, -1, 1), (m - 2, s - m, 1, -1),
                               (s - m + 2, s - m, -1, -1)):
            corners.moveTo(QPointF(x, y))
            corners.lineTo(QPointF(x + dx * k, y))
            corners.lineTo(QPointF(x, y + dy * k))
            corners.closeSubpath()
        _fill(p, body.united(corners).simplified(), GRAY_TOP, GRAY_BOTTOM, GRAY_EDGE)
    elif kind == "play":
        r = s / 2 - 1
        c = QPointF(s / 2, s / 2)
        g = QRadialGradient(QPointF(s / 2, s * 0.3), s * 0.75)
        g.setColorAt(0, QColor("#8CC4FF"))
        g.setColorAt(0.55, QColor("#2B6CC4"))
        g.setColorAt(1, QColor("#0E3D7E"))
        p.setPen(QPen(QColor("#0B2F63"), 1.2))
        p.setBrush(g)
        p.drawEllipse(c, r, r)
        shine = QLinearGradient(QPointF(0, 0), QPointF(0, s / 2))
        shine.setColorAt(0, QColor(255, 255, 255, 170))
        shine.setColorAt(1, QColor(255, 255, 255, 25))
        p.setPen(Qt.NoPen)
        p.setBrush(shine)
        p.drawEllipse(QRectF(s * 0.18, s * 0.06, s * 0.64, s * 0.42))
        # a small projection screen with a play mark
        sw, sh = s * 0.42, s * 0.3
        screen = QRectF(c.x() - sw / 2, c.y() - sh / 2 + s * 0.03, sw, sh)
        p.setPen(QPen(QColor("#FFFFFF"), max(1.2, s * 0.045)))
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRoundedRect(screen, 1.5, 1.5)
        tri = QPainterPath(QPointF(screen.center().x() - sh * 0.22, screen.center().y() - sh * 0.28))
        tri.lineTo(QPointF(screen.center().x() + sh * 0.3, screen.center().y()))
        tri.lineTo(QPointF(screen.center().x() - sh * 0.22, screen.center().y() + sh * 0.28))
        tri.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawPath(tri)
    p.setOpacity(1.0)


def glyph_pixmap(kind: str, size: int, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_glyph(p, kind, size)
    p.end()
    return pm


def app_icon_pixmap(size: int = 64) -> QPixmap:
    """The window icon: a framed landscape picture."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    s = size
    frame = QRectF(s * 0.08, s * 0.16, s * 0.84, s * 0.68)
    p.setPen(QPen(QColor("#6B7B8F"), max(1, s / 40)))
    p.setBrush(QColor("#FFFFFF"))
    p.drawRoundedRect(frame, s * 0.04, s * 0.04)
    inner = frame.adjusted(s * 0.06, s * 0.06, -s * 0.06, -s * 0.06)
    sky = QLinearGradient(inner.topLeft(), inner.bottomLeft())
    sky.setColorAt(0, QColor("#3D8BE0"))
    sky.setColorAt(1, QColor("#BFE1FF"))
    p.setPen(Qt.NoPen)
    p.setBrush(sky)
    p.drawRect(inner)
    p.setBrush(QColor("#FFE36B"))
    p.drawEllipse(QPointF(inner.right() - inner.width() * 0.22, inner.top() + inner.height() * 0.28),
                  inner.height() * 0.13, inner.height() * 0.13)
    hill = QPainterPath(inner.bottomLeft())
    hill.lineTo(QPointF(inner.left(), inner.bottom() - inner.height() * 0.3))
    hill.quadTo(QPointF(inner.left() + inner.width() * 0.3, inner.bottom() - inner.height() * 0.7),
                QPointF(inner.left() + inner.width() * 0.62, inner.bottom() - inner.height() * 0.25))
    hill.quadTo(QPointF(inner.right() - inner.width() * 0.15, inner.bottom() - inner.height() * 0.45),
                inner.topRight() + QPointF(0, inner.height() * 0.62))
    hill.lineTo(inner.bottomRight())
    hill.closeSubpath()
    g = QLinearGradient(inner.topLeft(), inner.bottomLeft())
    g.setColorAt(0, QColor("#7CC24A"))
    g.setColorAt(1, QColor("#2F7D1E"))
    p.setBrush(g)
    p.drawPath(hill)
    p.end()
    return pm


class GlyphButton(QAbstractButton):
    """A flat bottom-bar button: a painted glyph with a soft glow when the mouse is over it."""

    def __init__(self, kind: str, size: int = 28, parent=None, tip: str = ""):
        super().__init__(parent)
        self.kind = kind
        self.glyph = size
        self.setFixedSize(QSize(size + 12, size + 10) if kind != "play" else QSize(size + 12, size + 12))
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip(tip)
        self._hover = False

    def set_kind(self, kind: str):
        if kind != self.kind:
            self.kind = kind
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        if self.isEnabled() and (self._hover or self.isDown()) and self.kind != "play":
            g = QRadialGradient(r.center(), r.width() * 0.62)
            g.setColorAt(0, QColor(255, 255, 255, 230 if not self.isDown() else 140))
            g.setColorAt(0.7, QColor(220, 236, 255, 120))
            g.setColorAt(1, QColor(220, 236, 255, 0))
            p.setPen(QPen(QColor(120, 160, 210, 150 if not self.isDown() else 220), 1))
            p.setBrush(g)
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 4, 4)
        s = self.glyph
        p.translate((r.width() - s) / 2, (r.height() - s) / 2 + (1 if self.isDown() else 0))
        if self.kind == "play" and self.isEnabled() and self._hover:
            p.save()
            glow = QRadialGradient(QPointF(s / 2, s / 2), s * 0.62)
            glow.setColorAt(0.75, QColor(120, 200, 255, 160))
            glow.setColorAt(1, QColor(120, 200, 255, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(s / 2, s / 2), s * 0.62, s * 0.62)
            p.restore()
        paint_glyph(p, self.kind, s, self.isEnabled())
        p.end()
