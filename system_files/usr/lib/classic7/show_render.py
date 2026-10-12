"""Show: drawing slides (editor, thumbnails, slide show, printing). Coordinates are points."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF, QRadialGradient, QTransform)

import show_geom as geom
import show_model as sm
import show_text as st

TABLE_STYLES = {
    # GUIDs of PowerPoint's built-in table styles -> our style keys
    "{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}": "medium2-accent1",
    "{21E4AEA4-8DFA-4A89-87EB-49C32662AFE8}": "medium2-accent2",
    "{F5AB1C69-6EDB-4FF4-983F-18BD219EF322}": "medium2-accent3",
    "{00A15C55-8517-42AA-B614-E9B94910E393}": "medium2-accent4",
    "{7DF18680-E054-41AD-8BC1-D1AEF772440D}": "medium2-accent5",
    "{93296810-A885-4BE3-A3E7-6D5BEEA58F35}": "medium2-accent6",
    "{073A0DAA-6AF3-43AB-8588-CEC1D06C72B9}": "medium2-dk1",
    "{2D5ABB26-0587-4C30-8999-92F81FD0307C}": "none",
    "{5940675A-B579-460E-94D1-54222C63F5DA}": "grid",
    "{3B4B98B0-60AC-42C2-AFA5-B58CD77FA1E5}": "light1-accent1",
}
TABLE_STYLE_IDS = {v: k for k, v in TABLE_STYLES.items()}


class Renderer:
    def __init__(self, pres: sm.Presentation):
        self.pres = pres
        self._images: dict[str, QImage] = {}

    # -- media
    def image(self, key: str | None) -> QImage:
        if not key:
            return QImage()
        img = self._images.get(key)
        if img is None:
            data = self.pres.media.get(key)
            img = QImage()
            if data:
                img.loadFromData(data)
                if img.isNull():
                    img = _pil_image(data)
            self._images[key] = img
        return img

    def forget_images(self):
        self._images.clear()

    # -- contexts
    def ctx(self, slide: sm.Slide | None, shape: sm.Shape | None, number: int = 0, editing: bool = False,
            master: sm.Master | None = None, layout: sm.Layout | None = None) -> st.TextCtx:
        if master is None:
            master = self.pres.master_of(slide) if slide is not None else self.pres.master
        if layout is None and slide is not None:
            layout = slide.layout
        c = st.TextCtx(master, layout, shape, number, editing)
        if shape is not None and shape.style_text_color is not None:
            c.text_color = shape.style_text_color
        return c

    # -- whole slides
    def paint_background(self, p: QPainter, slide: sm.Slide | None, master: sm.Master, layout: sm.Layout | None):
        w, h = sm.pt(self.pres.width), sm.pt(self.pres.height)
        bg = (slide.background if slide is not None else None) or (layout.background if layout else None) \
            or master.background or {"type": "solid", "color": sm.scheme("bg1")}
        c = st.TextCtx(master, layout, None)
        self.paint_fill(p, QRectF(0, 0, w, h), bg, c, path=None)

    def paint_slide(self, p: QPainter, slide: sm.Slide, number: int = 0, edit: bool = False,
                    skip: set | None = None, decorations: bool = True, no_text: set | None = None):
        master = self.pres.master_of(slide)
        layout = slide.layout
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setClipRect(QRectF(0, 0, sm.pt(self.pres.width), sm.pt(self.pres.height)))
        self.paint_background(p, slide, master, layout)
        if decorations and not slide.hide_master_shapes:
            if layout is None or layout.show_master_shapes:
                for s in master.shapes:
                    self.paint_shape(p, s, slide, number, False, master=master, layout=layout)
            if layout is not None:
                for s in layout.shapes:
                    self.paint_shape(p, s, slide, number, False, master=master, layout=layout)
        for s in slide.shapes:
            if skip and s.id in skip:
                continue
            self.paint_shape(p, s, slide, number, edit, master=master, layout=layout,
                             text=not (no_text and s.id in no_text))
        p.restore()

    def paint_layout_preview(self, p: QPainter, master: sm.Master, layout: sm.Layout):
        """A layout as shown in the New Slide / Layout galleries: background + placeholder outlines."""
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p, None, master, layout)
        if layout.show_master_shapes:
            for s in master.shapes:
                self.paint_shape(p, s, None, 0, False, master=master, layout=layout)
        for s in layout.shapes:
            self.paint_shape(p, s, None, 0, False, master=master, layout=layout)
        pen = QPen(QColor(128, 128, 128), 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        for ph in layout.placeholders:
            if ph.ph.type in ("dt", "ftr", "sldNum"):
                continue
            r = QRectF(sm.pt(ph.x), sm.pt(ph.y), sm.pt(ph.cx), sm.pt(ph.cy))
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            ctx = st.TextCtx(master, layout, ph)
            d = ctx.defaults(0)
            p.setPen(ctx.color(d.get("color")))
            f = QFont(ctx.font_name(d.get("font")))
            f.setPointSizeF(max(6.0, min(sm.pt(ph.cy) * 0.45, float(d.get("size") or 18))))
            p.setFont(f)
            al = {"ctr": Qt.AlignHCenter, "r": Qt.AlignRight}.get(d.get("align") or "l", Qt.AlignLeft)
            if ph.ph.type in ("title", "ctrTitle"):
                p.drawText(r.adjusted(4, 2, -4, -2), al | Qt.AlignVCenter, "Title")
            elif ph.ph.type == "pic":
                p.drawText(r, Qt.AlignCenter, "Picture")
            else:
                p.drawText(r.adjusted(6, 4, -4, -2), al | Qt.AlignTop, "• Text" if d.get("bullet") else "Text")
        p.restore()

    def thumbnail(self, slide: sm.Slide, width: int, number: int = 0, dpr: float = 1.0) -> QImage:
        w, h = sm.pt(self.pres.width), sm.pt(self.pres.height)
        height = max(1, round(width * h / w))
        img = QImage(QSize(round(width * dpr), round(height * dpr)), QImage.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.white)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.scale(width / w, height / h)
        self.paint_slide(p, slide, number)
        p.end()
        return img

    # -- shapes
    def shape_transform(self, s: sm.Shape, flips: bool = True) -> QTransform:
        x, y, w, h = sm.pt(s.x), sm.pt(s.y), sm.pt(s.cx), sm.pt(s.cy)
        t = QTransform()
        t.translate(x + w / 2, y + h / 2)
        if s.rot:
            t.rotate(s.rot)
        if flips and (s.flip_h or s.flip_v):
            t.scale(-1 if s.flip_h else 1, -1 if s.flip_v else 1)
        t.translate(-w / 2, -h / 2)
        return t

    def shape_path(self, s: sm.Shape) -> QPainterPath:
        w, h = sm.pt(s.cx), sm.pt(s.cy)
        if s.path:
            return geom.custom_path(s.path, w, h)
        return geom.preset_path(s.geom or "rect", w, h, s.adj)

    def paint_shape(self, p: QPainter, s: sm.Shape, slide: sm.Slide | None, number: int, edit: bool,
                    master: sm.Master | None = None, layout: sm.Layout | None = None, text: bool = True):
        p.save()
        p.setTransform(self.shape_transform(s), True)
        w, h = sm.pt(s.cx), sm.pt(s.cy)
        ctx = self.ctx(slide, s, number, edit, master, layout)
        if s.kind == "group":
            ch = s.child_rect or (s.x, s.y, s.cx, s.cy)
            sx = s.cx / ch[2] if ch[2] else 1.0
            sy = s.cy / ch[3] if ch[3] else 1.0
            p.scale(sx, sy)
            p.translate(-sm.pt(ch[0]), -sm.pt(ch[1]))
            for c in s.children:
                self.paint_shape(p, c, slide, number, edit, master, layout, text)
            p.restore()
            return
        if s.kind == "pic":
            self._paint_picture(p, s, ctx, w, h)
        elif s.kind == "table" and s.table is not None:
            self.paint_table(p, s, ctx, w, h)
        elif s.kind in ("chart", "other"):
            img = self.image(s.fallback_image)
            drawn = False
            if s.kind == "chart" and s.chart:
                try:
                    import show_chart
                    drawn = show_chart.paint(p, QRectF(0, 0, w, h), s.chart, ctx)
                except Exception:   # noqa: BLE001
                    drawn = False
            if drawn:
                pass
            elif not img.isNull():
                p.drawImage(QRectF(0, 0, w, h), img)
            else:
                p.setPen(QPen(QColor("#A6A6A6"), 1))
                p.setBrush(QColor(242, 242, 242, 200))
                p.drawRect(QRectF(0, 0, w, h))
                p.setPen(QColor("#7F7F7F"))
                p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "Chart" if s.kind == "chart" else "Object")
        else:
            path = self.shape_path(s)
            open_shape = (s.geom in geom.OPEN_SHAPES) and not s.path
            if s.fill and not open_shape:
                self.paint_fill(p, QRectF(0, 0, w, h), s.fill, ctx, path)
            if s.line:
                self.paint_line(p, path, s.line, ctx, arrows=(s.geom in geom.LINE_SHAPES or bool(s.path)))
            empty_ph = s.ph is not None and (s.text is None or s.text.is_empty())
            if edit and empty_ph and text and s.ph.type not in ("dt", "ftr", "sldNum"):
                self._paint_prompt(p, s, ctx, w, h)
        if text and s.text is not None and s.kind not in ("table", "group") and not s.text.is_empty():
            # text is not mirrored by a flip (a vertical flip turns it upside down, like PowerPoint)
            if s.flip_h or s.flip_v:
                p.translate(w / 2, h / 2)
                p.scale(-1 if s.flip_h else 1, -1 if s.flip_v else 1)
                p.translate(-w / 2, -h / 2)
            area = st.text_area(w, h, s.text, geom.text_rect(s.geom or "rect", w, h) if s.kind == "sp" else None)
            st.paint_text(p, s.text, ctx, area)
        p.restore()

    def _paint_prompt(self, p, s, ctx, w, h):
        pen = QPen(QColor(150, 150, 150), 1.0, Qt.DashLine)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(0, 0, w, h))
        if not s.prompt:
            return
        body = sm.TextBody(anchor=s.text.anchor if s.text else "t", insets=s.text.insets if s.text else (91440, 45720, 91440, 45720))
        par = sm.Paragraph(runs=[sm.Run(text=s.prompt)])
        if s.text and s.text.paragraphs:
            src = s.text.paragraphs[0]
            par.align, par.level = src.align, src.level
        body.paragraphs = [par]
        if s.ph.type == "pic":
            body.anchor = "ctr"
            par.align = "ctr"
            par.bullet = {"none": True}
        area = st.text_area(w, h, body)
        st.paint_text(p, body, ctx, area)

    def _paint_picture(self, p, s, ctx, w, h):
        img = self.image(s.image)
        path = self.shape_path(s)
        if s.fill:
            self.paint_fill(p, QRectF(0, 0, w, h), s.fill, ctx, path)
        if not img.isNull():
            l, t, r, b = (v / 100000.0 for v in s.crop)
            src = QRectF(img.width() * l, img.height() * t, img.width() * (1 - l - r), img.height() * (1 - t - b))
            p.save()
            if s.geom and s.geom != "rect":
                p.setClipPath(path, Qt.IntersectClip)
            p.drawImage(QRectF(0, 0, w, h), img, src)
            p.restore()
        elif s.ph is None:
            p.setPen(QPen(QColor("#C00000"), 1))
            p.drawRect(QRectF(0, 0, w, h))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignCenter, "Picture")
        if s.line:
            self.paint_line(p, path, s.line, ctx)

    # -- fills and lines
    def paint_fill(self, p: QPainter, rect: QRectF, fill: dict | None, ctx: st.TextCtx, path: QPainterPath | None):
        if not fill:
            return
        brush = self.brush(fill, rect, ctx)
        if brush is None:
            return
        if fill.get("type") == "pic":
            img = self.image(fill.get("image"))
            if not img.isNull():
                p.save()
                if path is not None:
                    p.setClipPath(path, Qt.IntersectClip)
                if fill.get("tile"):
                    p.fillRect(rect, QBrush(img))
                else:
                    p.drawImage(rect, img)
                p.restore()
            return
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(brush)
        if path is None:
            p.drawRect(rect)
        else:
            p.drawPath(path)
        p.restore()

    def brush(self, fill: dict, rect: QRectF, ctx: st.TextCtx):
        t = fill.get("type")
        if t == "solid":
            return QBrush(ctx.color(fill.get("color")))
        if t == "pattern":
            fg = ctx.color(fill.get("fg"))
            bg = ctx.color(fill.get("bg"), "FFFFFF")
            mix = QColor((fg.red() + bg.red()) // 2, (fg.green() + bg.green()) // 2, (fg.blue() + bg.blue()) // 2)
            return QBrush(mix)
        if t == "grad":
            stops = fill.get("stops") or []
            if not stops:
                return None
            if fill.get("path") in ("circle", "rect", "shape"):
                g = QRadialGradient(rect.center(), math.hypot(rect.width(), rect.height()) / 2)
                for pos, c in sorted(stops, key=lambda s: s[0]):
                    g.setColorAt(max(0.0, min(1.0, pos / 100000.0)), ctx.color(c))
                return QBrush(g)
            ang = math.radians(float(fill.get("angle") or 0))
            cx, cy = rect.center().x(), rect.center().y()
            dx, dy = math.cos(ang), math.sin(ang)
            half = abs(rect.width() / 2 * dx) + abs(rect.height() / 2 * dy)
            g = QLinearGradient(cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half)
            for pos, c in sorted(stops, key=lambda s: s[0]):
                g.setColorAt(max(0.0, min(1.0, pos / 100000.0)), ctx.color(c))
            return QBrush(g)
        if t == "pic":
            return QBrush(Qt.NoBrush)
        return None

    def pen(self, line: dict, ctx: st.TextCtx) -> QPen:
        width = sm.pt(line.get("width") or 9525)
        pen = QPen(ctx.color(line.get("color")), max(0.5, width))
        dash = line.get("dash") or "solid"
        patterns = {"dash": [4, 3], "sysDash": [3, 1], "sysDot": [1, 1], "dot": [1, 3], "lgDash": [8, 3],
                    "dashDot": [4, 3, 1, 3], "lgDashDot": [8, 3, 1, 3], "lgDashDotDot": [8, 3, 1, 3, 1, 3],
                    "sysDashDot": [3, 1, 1, 1], "sysDashDotDot": [3, 1, 1, 1, 1, 1]}
        if dash in patterns:
            pen.setDashPattern(patterns[dash])
        pen.setCapStyle({"rnd": Qt.RoundCap, "sq": Qt.SquareCap}.get(line.get("cap", "flat"), Qt.FlatCap))
        pen.setJoinStyle({"round": Qt.RoundJoin, "bevel": Qt.BevelJoin}.get(line.get("join", "round"), Qt.RoundJoin))
        return pen

    def paint_line(self, p: QPainter, path: QPainterPath, line: dict, ctx: st.TextCtx, arrows: bool = False):
        pen = self.pen(line, ctx)
        p.save()
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if arrows and (line.get("head") not in (None, "none") or line.get("tail") not in (None, "none")):
            n = path.elementCount()
            if n >= 2:
                first = QPointF(path.elementAt(0).x, path.elementAt(0).y)
                second = QPointF(path.elementAt(1).x, path.elementAt(1).y)
                last = QPointF(path.elementAt(n - 1).x, path.elementAt(n - 1).y)
                before = QPointF(path.elementAt(n - 2).x, path.elementAt(n - 2).y)
                if line.get("head") not in (None, "none"):
                    self._arrow(p, first, second, line["head"], line.get("head_size", "med"), pen)
                if line.get("tail") not in (None, "none"):
                    self._arrow(p, last, before, line["tail"], line.get("tail_size", "med"), pen)
        p.restore()

    def _arrow(self, p: QPainter, tip: QPointF, frm: QPointF, kind: str, size: str, pen: QPen):
        ang = math.atan2(tip.y() - frm.y(), tip.x() - frm.x())
        k = {"sm": 2.0, "med": 3.0, "lg": 5.0}.get(size, 3.0)
        L = max(3.0, pen.widthF() * k)
        W = L * 0.6
        ca, sa = math.cos(ang), math.sin(ang)

        def pt_(dx, dy):
            return QPointF(tip.x() + dx * ca - dy * sa, tip.y() + dx * sa + dy * ca)
        p.save()
        p.setPen(QPen(pen.color(), pen.widthF() * 0.5))
        p.setBrush(pen.color())
        if kind == "oval":
            p.drawEllipse(tip, W, W)
        elif kind == "diamond":
            p.drawPolygon(QPolygonF([pt_(W, 0), pt_(0, W), pt_(-W, 0), pt_(0, -W)]))
        elif kind == "arrow":
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(pen.color(), pen.widthF(), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline(QPolygonF([pt_(-L, -W), tip, pt_(-L, W)]))
        elif kind == "stealth":
            p.drawPolygon(QPolygonF([tip, pt_(-L, -W), pt_(-L * 0.6, 0), pt_(-L, W)]))
        else:
            p.drawPolygon(QPolygonF([tip, pt_(-L, -W), pt_(-L, W)]))
        p.restore()

    # -- tables
    def table_geometry(self, s: sm.Shape, ctx: st.TextCtx) -> tuple[list, list]:
        """Column x positions and row y positions (points); rows grow to fit their text."""
        t = s.table
        xs = [0.0]
        for wcol in t.col_widths:
            xs.append(xs[-1] + sm.pt(wcol))
        ys = [0.0]
        for ri, row in enumerate(t.rows):
            hrow = sm.pt(t.row_heights[ri]) if ri < len(t.row_heights) else 20.0
            for ci, cell in enumerate(row):
                if cell.merged or ci >= len(xs) - 1:
                    continue
                span = max(1, cell.span)
                cw = xs[min(len(xs) - 1, ci + span)] - xs[ci]
                l, tt, r, b = (sm.pt(v) for v in cell.margins)
                cctx = self.cell_ctx(ctx, s, ri, ci)
                need = st.text_height(cell.text, cctx, max(1.0, cw - l - r)) + tt + b
                if cell.row_span <= 1:
                    hrow = max(hrow, need)
            ys.append(ys[-1] + hrow)
        return xs, ys

    def cell_ctx(self, ctx: st.TextCtx, s: sm.Shape, ri: int, ci: int) -> st.TextCtx:
        c = st.TextCtx(ctx.master, ctx.layout, s, ctx.slide_number, ctx.editing, table_cell=True)
        t = s.table
        style, accent = _split_style(t.style)
        header = (t.first_row and ri == 0) or (t.last_row and ri == len(t.rows) - 1) or \
                 (t.first_col and ci == 0) or (t.last_col and ci == len(t.col_widths) - 1)
        if style in ("medium2",) and header:
            c.text_color = sm.scheme("lt1")
        else:
            c.text_color = sm.scheme("dk1")
        c._header = header
        return c

    def cell_fill(self, t: sm.Table, ri: int, ci: int, cell: sm.TableCell) -> dict | None:
        if cell.fill != "auto":
            return cell.fill
        style, accent = _split_style(t.style)
        if style in ("none", "grid"):
            return None
        first = t.first_row and ri == 0
        last = t.last_row and ri == len(t.rows) - 1
        fcol = t.first_col and ci == 0
        lcol = t.last_col and ci == len(t.col_widths) - 1
        if style == "medium2":
            if first or last or fcol or lcol:
                return {"type": "solid", "color": sm.scheme(accent)}
            body_row = ri - (1 if t.first_row else 0)
            if t.band_rows and body_row % 2 == 0:
                return {"type": "solid", "color": sm.scheme(accent, ("tint", 40000))}
            if t.band_cols and ci % 2 == 0:
                return {"type": "solid", "color": sm.scheme(accent, ("tint", 40000))}
            return {"type": "solid", "color": sm.scheme(accent, ("tint", 20000))}
        if style == "light1":
            body_row = ri - (1 if t.first_row else 0)
            if t.band_rows and not first and body_row % 2 == 0:
                return {"type": "solid", "color": sm.scheme(accent, ("alpha", 20000))}
            return None
        return None

    def paint_table(self, p: QPainter, s: sm.Shape, ctx: st.TextCtx, w: float, h: float):
        t = s.table
        xs, ys = self.table_geometry(s, ctx)
        style, accent = _split_style(t.style)
        for ri, row in enumerate(t.rows):
            for ci, cell in enumerate(row):
                if cell.merged or ci >= len(xs) - 1 or ri >= len(ys) - 1:
                    continue
                x0, y0 = xs[ci], ys[ri]
                x1 = xs[min(len(xs) - 1, ci + max(1, cell.span))]
                y1 = ys[min(len(ys) - 1, ri + max(1, cell.row_span))]
                rect = QRectF(x0, y0, x1 - x0, y1 - y0)
                fill = self.cell_fill(t, ri, ci, cell)
                if fill:
                    self.paint_fill(p, rect, fill, ctx, None)
                cctx = self.cell_ctx(ctx, s, ri, ci)
                if getattr(cctx, "_header", False) and t.first_row and ri == 0 and not cell.text.is_empty():
                    body = _bold_body(cell.text)
                else:
                    body = cell.text
                l, tt, r, b = (sm.pt(v) for v in cell.margins)
                area = QRectF(rect.left() + l, rect.top() + tt, max(1.0, rect.width() - l - r),
                              max(1.0, rect.height() - tt - b))
                body.anchor = cell.anchor
                st.paint_text(p, body, cctx, area)
        # borders: the style's lines, then the cells' own
        if style in ("medium2", "grid", "light1"):
            col = ctx.color(sm.scheme("lt1")) if style == "medium2" else ctx.color(sm.scheme("tx1" if style == "grid" else accent))
            pen = QPen(col, 1.0 if style != "light1" else 0.75)
            p.setPen(pen)
            if style in ("medium2", "grid"):
                for x in xs[1:-1]:
                    p.drawLine(QPointF(x, ys[0]), QPointF(x, ys[-1]))
                for y in ys[1:-1]:
                    p.drawLine(QPointF(xs[0], y), QPointF(xs[-1], y))
                if style == "grid":
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(QRectF(xs[0], ys[0], xs[-1] - xs[0], ys[-1] - ys[0]))
            else:
                p.drawLine(QPointF(xs[0], ys[0]), QPointF(xs[-1], ys[0]))
                p.drawLine(QPointF(xs[0], ys[-1]), QPointF(xs[-1], ys[-1]))
                if t.first_row and len(ys) > 2:
                    p.drawLine(QPointF(xs[0], ys[1]), QPointF(xs[-1], ys[1]))
        for ri, row in enumerate(t.rows):
            for ci, cell in enumerate(row):
                if cell.merged or not cell.borders or ci >= len(xs) - 1 or ri >= len(ys) - 1:
                    continue
                x0, y0 = xs[ci], ys[ri]
                x1 = xs[min(len(xs) - 1, ci + max(1, cell.span))]
                y1 = ys[min(len(ys) - 1, ri + max(1, cell.row_span))]
                for side, (a, b) in (("l", ((x0, y0), (x0, y1))), ("r", ((x1, y0), (x1, y1))),
                                     ("t", ((x0, y0), (x1, y0))), ("b", ((x0, y1), (x1, y1)))):
                    ln = cell.borders.get(side)
                    if ln:
                        p.setPen(self.pen(ln, ctx))
                        p.drawLine(QPointF(*a), QPointF(*b))

    def table_height(self, s: sm.Shape, ctx: st.TextCtx) -> float:
        _xs, ys = self.table_geometry(s, ctx)
        return ys[-1]


def _split_style(key: str) -> tuple[str, str]:
    if not key or key in ("none", "grid"):
        return key or "none", "accent1"
    if "-" in key:
        a, b = key.split("-", 1)
        return a, b
    return key, "accent1"


def _bold_body(body: sm.TextBody) -> sm.TextBody:
    import copy
    b = copy.deepcopy(body)
    for par in b.paragraphs:
        for r in par.runs:
            if r.bold is None:
                r.bold = True
    return b


def _pil_image(data: bytes) -> QImage:
    """Pictures Qt can't read (WMF/EMF previews, odd TIFFs): try Pillow."""
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            im = im.convert("RGBA")
            return QImage(im.tobytes("raw", "RGBA"), im.width, im.height, 4 * im.width,
                          QImage.Format_RGBA8888).copy()
    except Exception:   # noqa: BLE001
        return QImage()
