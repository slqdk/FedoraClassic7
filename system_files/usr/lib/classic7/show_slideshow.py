"""Show: the full-screen slide show - transitions, entrance animations, pen, black/white screen."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import QMenu, QWidget

import show_model as sm
import show_render as sr

ANIM_MS = 500


def slide_title(slide: sm.Slide) -> str:
    for s in slide.shapes:
        if s.ph is not None and s.ph.type in ("title", "ctrTitle") and s.text is not None:
            t = s.text.plain().strip().replace("\v", " ")
            if t:
                return t.split("\n")[0]
    return ""


def anim_steps(slide: sm.Slide) -> list:
    """Shapes with an entrance animation, in click order: [[shape, ...], ...]."""
    items = [s for s in slide.shapes if s.anim and s.anim.get("effect") not in (None, "none")]
    items.sort(key=lambda s: s.anim.get("order", 0))
    steps: list = []
    for s in items:
        trig = s.anim.get("trigger", "click")
        if trig == "click" or not steps:
            steps.append([s])
        else:
            steps[-1].append(s)
    return steps


class SlideShow(QWidget):
    finished = Signal(int)            # the slide shown last (index in the presentation)

    def __init__(self, pres: sm.Presentation, start: int = 0, loop: bool = False, use_timings: bool = True,
                 first: int | None = None, last: int | None = None, screen=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setWindowTitle("Slide Show")
        self.pres = pres
        self.renderer = sr.Renderer(pres)
        self.loop = loop or pres.show_loop
        self.use_timings = use_timings
        lo = 0 if first is None else max(0, first)
        hi = len(pres.slides) - 1 if last is None else min(len(pres.slides) - 1, last)
        self.order = [i for i in range(lo, hi + 1) if not pres.slides[i].hidden or i == start]
        if not self.order:
            self.order = [min(max(0, start), len(pres.slides) - 1)]
        self.pos = self.order.index(start) if start in self.order else 0
        self.step = 0
        self.cache: dict = {}
        self.ended = False
        self.screen_mode = None            # "black" | "white" | None
        self.pen = False
        self.ink: dict[int, list] = {}
        self.stroke: list | None = None
        self.history: list[int] = []
        self.typed = ""
        self._trans = None                 # (old image, new image, transition)
        self._anim = None                  # (base image, shapes, effect, ...)
        self._t = 1.0
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.valueChanged.connect(self._tick)
        self.anim.finished.connect(self._anim_done)
        self.auto = QTimer(self)
        self.auto.setSingleShot(True)
        self.auto.timeout.connect(self.next)
        self.hide_mouse = QTimer(self)
        self.hide_mouse.setSingleShot(True)
        self.hide_mouse.setInterval(3000)
        self.hide_mouse.timeout.connect(lambda: self.setCursor(Qt.BlankCursor) if not self.pen else None)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.StrongFocus)
        scr = screen or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.setGeometry(scr.geometry())
        self._dissolve = list(range(24 * 18))
        random.shuffle(self._dissolve)

    # ---- running -----------------------------------------------------------------------------
    def start(self):
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.setCursor(Qt.BlankCursor)
        self._enter_slide(transition=False)

    @property
    def index(self) -> int:
        return self.order[self.pos]

    @property
    def slide(self) -> sm.Slide:
        return self.pres.slides[self.index]

    def slide_rect(self) -> QRectF:
        w, h = sm.pt(self.pres.width), sm.pt(self.pres.height)
        k = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * k) / 2, (self.height() - h * k) / 2, w * k, h * k)

    def frame(self, index: int, step: int) -> QImage:
        key = (index, step, self.width(), self.height())
        img = self.cache.get(key)
        if img is None:
            slide = self.pres.slides[index]
            steps = anim_steps(slide)
            hidden = {s.id for grp in steps[step:] for s in grp}
            r = self.slide_rect()
            dpr = self.devicePixelRatioF()
            img = QImage(QSize(round(r.width() * dpr), round(r.height() * dpr)), QImage.Format_ARGB32_Premultiplied)
            img.setDevicePixelRatio(dpr)
            img.fill(Qt.white)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            k = r.width() / sm.pt(self.pres.width)
            p.scale(k, k)
            self.renderer.paint_slide(p, slide, index + 1, skip=hidden)
            p.end()
            if len(self.cache) > 12:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = img
        return img

    def shape_layer(self, index: int, shapes: list) -> QImage:
        """Just the shapes being animated in, on a transparent picture."""
        r = self.slide_rect()
        dpr = self.devicePixelRatioF()
        img = QImage(QSize(round(r.width() * dpr), round(r.height() * dpr)), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        k = r.width() / sm.pt(self.pres.width)
        p.scale(k, k)
        slide = self.pres.slides[index]
        for s in shapes:
            self.renderer.paint_shape(p, s, slide, index + 1, False)
        p.end()
        return img

    def _enter_slide(self, transition=True, old: QImage | None = None):
        self.step = 0
        self.auto.stop()
        new = self.frame(self.index, 0)
        t = self.slide.transition
        if transition and old is not None and t.type not in (None, "", "none", "cut"):
            self._trans = (old, new, t)
            self._anim = None
            self.anim.stop()
            self.anim.setDuration(t.duration_ms() if t.type != "fade" or not t.through_black else t.duration_ms() * 2)
            self.anim.start()
        else:
            self._trans = None
            self._t = 1.0
            self.update()
            self._arm_auto()
        self.frame(self.order[(self.pos + 1) % len(self.order)], 0)   # get the next one ready

    def _arm_auto(self):
        t = self.slide.transition
        if self.use_timings and t.after_ms is not None and not self.ended:
            self.auto.start(max(0, t.after_ms) if self.step >= len(anim_steps(self.slide)) else 1500)

    def _tick(self, v):
        self._t = float(v)
        self.update()

    def _anim_done(self):
        self._t = 1.0
        self._trans = None
        self._anim = None
        self.update()
        self._arm_auto()

    def next(self):
        if self.pen and self.stroke:
            return
        if self.anim.state() == QVariantAnimation.Running:
            self.anim.stop()
            self._anim_done()
            return
        if self.screen_mode:
            self.screen_mode = None
            self.update()
            return
        if self.ended:
            self.close()
            return
        steps = anim_steps(self.slide)
        if self.step < len(steps):
            base = self.frame(self.index, self.step)
            shapes = steps[self.step]
            self.step += 1
            self._anim = (base, self.shape_layer(self.index, shapes), shapes[0].anim.get("effect", "fade"),
                          shapes[0].anim.get("dir", "b"), self.frame(self.index, self.step))
            self._trans = None
            self.anim.stop()
            self.anim.setDuration(ANIM_MS)
            self.anim.start()
            return
        old = self.frame(self.index, self.step)
        if self.pos + 1 >= len(self.order):
            if self.loop:
                self.history.append(self.pos)
                self.pos = 0
                self._enter_slide(True, old)
                return
            self.ended = True
            self.auto.stop()
            self.update()
            return
        self.history.append(self.pos)
        self.pos += 1
        self._enter_slide(True, old)

    def prev(self):
        if self.ended:
            self.ended = False
            self.update()
            return
        self.anim.stop()
        self._trans = None
        self._anim = None
        if self.step > 0:
            self.step -= 1
            self.update()
            return
        if self.pos > 0:
            self.pos -= 1
            self.step = len(anim_steps(self.slide))
            self.update()
        elif self.loop:
            self.pos = len(self.order) - 1
            self.update()

    def go(self, index: int):
        if index in self.order:
            self.history.append(self.pos)
            self.pos = self.order.index(index)
        elif 0 <= index < len(self.pres.slides):
            self.order.append(index)
            self.order.sort()
            self.pos = self.order.index(index)
        self.ended = False
        self._enter_slide(transition=False)

    # ---- painting ----------------------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        if self.ended:
            p.setPen(QColor("#FFFFFF"))
            f = QFont(p.font())
            f.setPointSize(12)
            p.setFont(f)
            p.drawText(self.rect().adjusted(0, 12, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                       "End of slide show, click to exit.")
            return
        if self.screen_mode:
            p.fillRect(self.rect(), Qt.black if self.screen_mode == "black" else Qt.white)
            return
        r = self.slide_rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._trans is not None:
            old, new, t = self._trans
            self.paint_transition(p, r, old, new, t, self._t)
        elif self._anim is not None:
            base, layer, effect, direction, _final = self._anim
            p.drawImage(r.topLeft(), base)
            self.paint_effect(p, r, layer, effect, self._t)
        else:
            p.drawImage(r.topLeft(), self.frame(self.index, self.step))
        self.paint_ink(p, r)

    def paint_effect(self, p: QPainter, r: QRectF, layer: QImage, effect: str, t: float):
        t = max(0.0, min(1.0, t))
        if effect == "appear":
            p.drawImage(r.topLeft(), layer)
        elif effect == "wipe":
            p.save()
            p.setClipRect(QRectF(r.left(), r.bottom() - r.height() * t, r.width(), r.height() * t))
            p.drawImage(r.topLeft(), layer)
            p.restore()
        elif effect == "fly":
            e = 1 - (1 - t) ** 3
            p.drawImage(QPointF(r.left(), r.top() + (1 - e) * self.height()), layer)
        elif effect == "zoom":
            p.save()
            p.setOpacity(t)
            c = r.center()
            p.translate(c)
            p.scale(max(0.01, t), max(0.01, t))
            p.translate(-c)
            p.drawImage(r.topLeft(), layer)
            p.restore()
        else:
            p.save()
            p.setOpacity(t)
            p.drawImage(r.topLeft(), layer)
            p.restore()

    def paint_transition(self, p: QPainter, r: QRectF, old: QImage, new: QImage, tr: sm.Transition, t: float):
        typ = tr.type
        d = tr.dir or ""
        e = 1 - (1 - t) ** 2
        W, H = r.width(), r.height()
        if typ == "fade":
            if tr.through_black:
                if t < 0.5:
                    p.setOpacity(1 - t * 2)
                    p.drawImage(r.topLeft(), old)
                else:
                    p.setOpacity((t - 0.5) * 2)
                    p.drawImage(r.topLeft(), new)
                p.setOpacity(1)
                return
            p.drawImage(r.topLeft(), old)
            p.setOpacity(t)
            p.drawImage(r.topLeft(), new)
            p.setOpacity(1)
            return
        vec = {"l": (-1, 0), "r": (1, 0), "u": (0, -1), "d": (0, 1), "lu": (-1, -1), "ru": (1, -1),
               "ld": (-1, 1), "rd": (1, 1)}
        if typ in ("push", "cover", "pull"):
            dx, dy = vec.get(d, (-1, 0) if typ != "pull" else (-1, 0))
            p.save()
            p.setClipRect(r)
            if typ == "push":
                p.drawImage(r.topLeft() + QPointF(dx * W * e, dy * H * e), old)
                p.drawImage(r.topLeft() + QPointF(dx * W * e - dx * W, dy * H * e - dy * H), new)
            elif typ == "cover":
                p.drawImage(r.topLeft(), old)
                p.drawImage(r.topLeft() + QPointF(-dx * W * (1 - e), -dy * H * (1 - e)), new)
            else:
                p.drawImage(r.topLeft(), new)
                p.drawImage(r.topLeft() + QPointF(dx * W * e, dy * H * e), old)
            p.restore()
            return
        p.drawImage(r.topLeft(), old)
        clip = QPainterPath()
        if typ == "wipe":
            d = d or "r"
            if d == "r":
                clip.addRect(QRectF(r.left(), r.top(), W * t, H))
            elif d == "l":
                clip.addRect(QRectF(r.right() - W * t, r.top(), W * t, H))
            elif d == "d":
                clip.addRect(QRectF(r.left(), r.top(), W, H * t))
            else:
                clip.addRect(QRectF(r.left(), r.bottom() - H * t, W, H * t))
        elif typ == "split":
            orient, _s, inout = (d or "horz-out").partition("-")
            if orient == "horz":
                if inout == "in":
                    clip.addRect(QRectF(r.left(), r.top(), W, H * t / 2))
                    clip.addRect(QRectF(r.left(), r.bottom() - H * t / 2, W, H * t / 2))
                else:
                    clip.addRect(QRectF(r.left(), r.center().y() - H * t / 2, W, H * t))
            else:
                if inout == "in":
                    clip.addRect(QRectF(r.left(), r.top(), W * t / 2, H))
                    clip.addRect(QRectF(r.right() - W * t / 2, r.top(), W * t / 2, H))
                else:
                    clip.addRect(QRectF(r.center().x() - W * t / 2, r.top(), W * t, H))
        elif typ == "circle":
            rad = math.hypot(W, H) / 2 * t
            clip.addEllipse(r.center(), rad, rad)
        elif typ == "diamond":
            rad = (W + H) / 2 * t
            c = r.center()
            clip.addPolygon(QPolygonF([QPointF(c.x(), c.y() - rad), QPointF(c.x() + rad, c.y()),
                                       QPointF(c.x(), c.y() + rad), QPointF(c.x() - rad, c.y())]))
        elif typ == "plus":
            c = r.center()
            clip.addRect(QRectF(c.x() - W * t / 2, r.top(), W * t, H))
            clip.addRect(QRectF(r.left(), c.y() - H * t / 2, W, H * t))
        elif typ in ("wheel", "wedge"):
            c = r.center()
            rad = math.hypot(W, H)
            clip.moveTo(c)
            if typ == "wheel":
                clip.arcTo(QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad), 90, -360 * t)
            else:
                clip.arcTo(QRectF(c.x() - rad, c.y() - rad, 2 * rad, 2 * rad), 90 - 180 * t, 360 * t)
            clip.closeSubpath()
        elif typ in ("blinds", "comb"):
            n = 6
            vert = d == "vert"
            for i in range(n):
                if vert:
                    clip.addRect(QRectF(r.left() + W / n * i, r.top(), W / n * t, H))
                else:
                    clip.addRect(QRectF(r.left(), r.top() + H / n * i, W, H / n * t))
        elif typ in ("dissolve", "checker", "random", "randomBar"):
            if typ == "randomBar":
                n = 60
                order = self._dissolve[:n] if len(self._dissolve) >= n else list(range(n))
                ranked = sorted(range(n), key=lambda i: order[i])
                for k in ranked[:int(n * t)]:
                    if d == "vert":
                        clip.addRect(QRectF(r.left() + W / n * k, r.top(), W / n + 0.5, H))
                    else:
                        clip.addRect(QRectF(r.left(), r.top() + H / n * k, W, H / n + 0.5))
            else:
                cols, rows = 24, 18
                cw, ch = W / cols, H / rows
                for k in self._dissolve[:int(len(self._dissolve) * t)]:
                    clip.addRect(QRectF(r.left() + (k % cols) * cw, r.top() + (k // cols) * ch, cw + 0.5, ch + 0.5))
        elif typ in ("zoom", "newsflash"):
            p.save()
            c = r.center()
            p.translate(c)
            if typ == "newsflash":
                p.rotate(360 * (1 - t))
            k = max(0.01, t) if d != "out" else 1 + (1 - t)
            p.scale(k, k)
            p.translate(-c)
            p.setOpacity(t)
            p.drawImage(r.topLeft(), new)
            p.restore()
            return
        else:
            p.setOpacity(t)
            p.drawImage(r.topLeft(), new)
            p.setOpacity(1)
            return
        p.save()
        p.setClipPath(clip)
        p.drawImage(r.topLeft(), new)
        p.restore()

    def paint_ink(self, p: QPainter, r: QRectF):
        strokes = self.ink.get(self.index, [])
        if not strokes and not self.stroke:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#E00000"), max(2.0, r.width() / 400), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        for st_ in strokes + ([self.stroke] if self.stroke else []):
            pts = [QPointF(r.left() + x * r.width(), r.top() + y * r.height()) for x, y in st_]
            if len(pts) == 1:
                p.drawPoint(pts[0])
            else:
                p.drawPolyline(QPolygonF(pts))
        p.restore()

    # ---- input -------------------------------------------------------------------------------
    def keyPressEvent(self, e):
        k = e.key()
        txt = e.text()
        if txt.isdigit():
            self.typed += txt
            return
        if k in (Qt.Key_Return, Qt.Key_Enter) and self.typed:
            n = int(self.typed) - 1
            self.typed = ""
            self.go(n)
            return
        self.typed = ""
        if k in (Qt.Key_Escape, Qt.Key_Minus, Qt.Key_Pause) and not (k == Qt.Key_Escape and self.pen):
            self.close()
        elif k == Qt.Key_Escape and self.pen:
            self.set_pen(False)
        elif k in (Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown, Qt.Key_N, Qt.Key_Return, Qt.Key_Enter):
            self.next()
        elif k in (Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp, Qt.Key_P, Qt.Key_Backspace) and \
                not (k == Qt.Key_P and e.modifiers() & Qt.ControlModifier):
            self.prev()
        elif k == Qt.Key_Home:
            self.go(self.order[0])
        elif k == Qt.Key_End:
            self.go(self.order[-1])
        elif k in (Qt.Key_B, Qt.Key_Period):
            self.screen_mode = None if self.screen_mode == "black" else "black"
            self.update()
        elif k in (Qt.Key_W, Qt.Key_Comma):
            self.screen_mode = None if self.screen_mode == "white" else "white"
            self.update()
        elif k == Qt.Key_P and e.modifiers() & Qt.ControlModifier:
            self.set_pen(True)
        elif k == Qt.Key_A and e.modifiers() & Qt.ControlModifier:
            self.set_pen(False)
        elif k == Qt.Key_E:
            self.ink.pop(self.index, None)
            self.update()
        else:
            super().keyPressEvent(e)

    def set_pen(self, on: bool):
        self.pen = on
        if on:
            self.setCursor(Qt.CrossCursor)
        else:
            self.unsetCursor()
            self.hide_mouse.start()

    def _norm(self, pos) -> tuple[float, float]:
        r = self.slide_rect()
        return ((pos.x() - r.left()) / r.width(), (pos.y() - r.top()) / r.height())

    def link_at(self, pos) -> str | None:
        """A hyperlink under the mouse: on a shape, or on a word in its text."""
        if self.ended or self.screen_mode:
            return None
        import show_geom as geom
        import show_text as st
        r = self.slide_rect()
        k = r.width() / sm.pt(self.pres.width)
        pt = QPointF((pos.x() - r.left()) / k, (pos.y() - r.top()) / k)
        slide = self.slide
        hidden = {x.id for grp in anim_steps(slide)[self.step:] for x in grp}
        for s in reversed(slide.shapes):
            if s.id in hidden:
                continue
            t = self.renderer.shape_transform(s, flips=False)
            inv, ok = t.inverted()
            if not ok:
                continue
            lp = inv.map(pt)
            w, h = sm.pt(s.cx), sm.pt(s.cy)
            if not (0 <= lp.x() <= w and 0 <= lp.y() <= h):
                continue
            if s.link:
                return s.link
            if s.text is not None and s.kind == "sp" and not s.text.is_empty():
                ctx = self.renderer.ctx(slide, s, self.index + 1)
                area = st.text_area(w, h, s.text, geom.text_rect(s.geom or "rect", w, h))
                doc = st.layout_doc(s.text, ctx, area)
                off = st.doc_offset(doc, s.text, area)
                dp = lp - area.topLeft() - off
                hit = doc.documentLayout().hitTest(dp, Qt.ExactHit)
                if hit >= 0:
                    from PySide6.QtGui import QTextCursor
                    c = QTextCursor(doc)
                    c.setPosition(hit + 1)
                    href = c.charFormat().anchorHref()
                    if href:
                        return href
            return None
        return None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self.pen:
                self.stroke = [self._norm(e.position())]
                return
            link = self.link_at(e.position())
            if link:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(link))
                return
            self.next()
        elif e.button() == Qt.RightButton:
            self._menu(e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self.pen and self.stroke is not None:
            self.stroke.append(self._norm(e.position()))
            self.update()
            return
        if not self.pen:
            if self.link_at(e.position()):
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.unsetCursor()
            self.hide_mouse.start()

    def mouseReleaseEvent(self, e):
        if self.pen and self.stroke is not None and e.button() == Qt.LeftButton:
            self.ink.setdefault(self.index, []).append(self.stroke)
            self.stroke = None
            self.update()

    def wheelEvent(self, e):
        if e.angleDelta().y() < 0:
            self.next()
        elif e.angleDelta().y() > 0:
            self.prev()

    def _menu(self, pos):
        self.unsetCursor()
        m = QMenu(self)
        m.addAction("Next", self.next)
        m.addAction("Previous", self.prev)
        last = m.addAction("Last Viewed", lambda: self.go(self.order[self.history[-1]]) if self.history else None)
        last.setEnabled(bool(self.history))
        go = m.addMenu("Go to Slide")
        for i, s in enumerate(self.pres.slides):
            t = slide_title(s) or f"Slide {i + 1}"
            a = go.addAction(f"{'(' if s.hidden else ''}{i + 1}{')' if s.hidden else ''} {t}"[:80],
                             lambda i=i: self.go(i))
            a.setCheckable(True)
            a.setChecked(i == self.index)
        m.addSeparator()
        scr = m.addMenu("Screen")
        scr.addAction("Black Screen", lambda: self._screen("black"))
        scr.addAction("White Screen", lambda: self._screen("white"))
        po = m.addMenu("Pointer Options")
        a = po.addAction("Arrow", lambda: self.set_pen(False))
        a.setCheckable(True)
        a.setChecked(not self.pen)
        a = po.addAction("Felt Tip Pen", lambda: self.set_pen(True))
        a.setCheckable(True)
        a.setChecked(self.pen)
        po.addAction("Erase All Ink on Slide", lambda: (self.ink.pop(self.index, None), self.update()))
        m.addSeparator()
        m.addAction("End Show", self.close)
        m.exec(pos)
        if not self.pen:
            self.hide_mouse.start()

    def _screen(self, mode):
        self.screen_mode = mode
        self.update()

    def resizeEvent(self, e):
        self.cache.clear()
        super().resizeEvent(e)

    def closeEvent(self, e):
        self.auto.stop()
        self.anim.stop()
        self.finished.emit(self.index)
        super().closeEvent(e)
