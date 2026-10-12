"""Show: preset shapes (DrawingML prstGeom) as painter paths in a w x h box."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

# gallery: (group, [(preset, label), ...]) in the order of PowerPoint 2007's Shapes button
GALLERY = [
    ("Lines", [("line", "Line"), ("straightConnector1", "Arrow"), ("doubleArrowLine", "Double Arrow")]),
    ("Rectangles", [("rect", "Rectangle"), ("roundRect", "Rounded Rectangle"), ("snip1Rect", "Snip Single Corner Rectangle"),
                    ("snip2SameRect", "Snip Same Side Corner Rectangle"), ("round1Rect", "Round Single Corner Rectangle"),
                    ("round2SameRect", "Round Same Side Corner Rectangle")]),
    ("Basic Shapes", [("ellipse", "Oval"), ("triangle", "Isosceles Triangle"), ("rtTriangle", "Right Triangle"),
                      ("parallelogram", "Parallelogram"), ("trapezoid", "Trapezoid"), ("diamond", "Diamond"),
                      ("pentagon", "Regular Pentagon"), ("hexagon", "Hexagon"), ("heptagon", "Heptagon"),
                      ("octagon", "Octagon"), ("decagon", "Decagon"), ("dodecagon", "Dodecagon"),
                      ("pie", "Pie"), ("chord", "Chord"), ("teardrop", "Teardrop"), ("frame", "Frame"),
                      ("plus", "Cross"), ("plaque", "Plaque"), ("can", "Can"), ("cube", "Cube"),
                      ("bevel", "Bevel"), ("donut", "Donut"), ("noSmoking", "\"No\" Symbol"),
                      ("blockArc", "Block Arc"), ("foldedCorner", "Folded Corner"), ("smileyFace", "Smiley Face"),
                      ("heart", "Heart"), ("lightningBolt", "Lightning Bolt"), ("sun", "Sun"), ("moon", "Moon"),
                      ("cloud", "Cloud"), ("arc", "Arc"), ("bracketPair", "Double Bracket"),
                      ("bracePair", "Double Brace"), ("leftBracket", "Left Bracket"),
                      ("rightBracket", "Right Bracket"), ("leftBrace", "Left Brace"), ("rightBrace", "Right Brace")]),
    ("Block Arrows", [("rightArrow", "Right Arrow"), ("leftArrow", "Left Arrow"), ("upArrow", "Up Arrow"),
                      ("downArrow", "Down Arrow"), ("leftRightArrow", "Left-Right Arrow"),
                      ("upDownArrow", "Up-Down Arrow"), ("quadArrow", "Quad Arrow"),
                      ("notchedRightArrow", "Notched Right Arrow"), ("stripedRightArrow", "Striped Right Arrow"),
                      ("homePlate", "Pentagon"), ("chevron", "Chevron"), ("uturnArrow", "U-Turn Arrow"),
                      ("bentArrow", "Bent Arrow")]),
    ("Equation Shapes", [("mathPlus", "Plus"), ("mathMinus", "Minus"), ("mathMultiply", "Multiply"),
                         ("mathDivide", "Division"), ("mathEqual", "Equal"), ("mathNotEqual", "Not Equal")]),
    ("Flowchart", [("flowChartProcess", "Process"), ("flowChartAlternateProcess", "Alternate Process"),
                   ("flowChartDecision", "Decision"), ("flowChartInputOutput", "Data"),
                   ("flowChartPredefinedProcess", "Predefined Process"), ("flowChartDocument", "Document"),
                   ("flowChartTerminator", "Terminator"), ("flowChartPreparation", "Preparation"),
                   ("flowChartManualInput", "Manual Input"), ("flowChartManualOperation", "Manual Operation"),
                   ("flowChartConnector", "Connector"), ("flowChartOffpageConnector", "Off-page Connector"),
                   ("flowChartMerge", "Merge"), ("flowChartExtract", "Extract"), ("flowChartDelay", "Delay"),
                   ("flowChartMagneticDisk", "Magnetic Disk")]),
    ("Stars and Banners", [("irregularSeal1", "Explosion 1"), ("star4", "4-Point Star"), ("star5", "5-Point Star"),
                           ("star6", "6-Point Star"), ("star8", "8-Point Star"), ("star10", "10-Point Star"),
                           ("star12", "12-Point Star"), ("star16", "16-Point Star"), ("star24", "24-Point Star"),
                           ("wave", "Wave"), ("doubleWave", "Double Wave")]),
    ("Callouts", [("wedgeRectCallout", "Rectangular Callout"), ("wedgeRoundRectCallout", "Rounded Rectangular Callout"),
                  ("wedgeEllipseCallout", "Oval Callout"), ("cloudCallout", "Cloud Callout")]),
]
LABELS = {k: v for _g, items in GALLERY for k, v in items}
OPEN_SHAPES = {"line", "straightConnector1", "doubleArrowLine", "arc", "bracketPair", "bracePair", "leftBracket",
               "rightBracket", "leftBrace", "rightBrace", "bentConnector2", "bentConnector3", "curvedConnector3"}
LINE_SHAPES = {"line", "straightConnector1", "doubleArrowLine", "bentConnector2", "bentConnector3",
               "curvedConnector3"}

DEFAULT_ADJ = {"roundRect": 16667, "snip1Rect": 16667, "snip2SameRect": 16667, "round1Rect": 16667,
               "round2SameRect": 16667, "triangle": 50000, "parallelogram": 25000, "trapezoid": 25000,
               "plaque": 16667, "can": 25000, "cube": 25000, "bevel": 12500, "donut": 25000, "noSmoking": 18750,
               "blockArc": 25000, "foldedCorner": 16667, "frame": 12500, "plus": 25000, "homePlate": 50000,
               "chevron": 50000, "rightArrow": 50000, "leftArrow": 50000, "upArrow": 50000, "downArrow": 50000,
               "leftRightArrow": 50000, "upDownArrow": 50000, "quadArrow": 22500, "notchedRightArrow": 50000,
               "stripedRightArrow": 50000, "wedgeRectCallout": -20833, "wedgeRoundRectCallout": -20833,
               "wedgeEllipseCallout": -20833, "cloudCallout": -20833, "star4": 12500, "star5": 19098,
               "star6": 28868, "star8": 38268, "star10": 42533, "star12": 37500, "star16": 37500,
               "star24": 37500, "moon": 50000, "teardrop": 100000, "hexagon": 25000, "octagon": 29289,
               "pie": 0, "chord": 0, "arc": 0, "bracketPair": 16667, "bracePair": 8333, "leftBracket": 8333,
               "rightBracket": 8333, "leftBrace": 8333, "rightBrace": 8333, "wave": 12500, "doubleWave": 6250,
               "sun": 25000, "smileyFace": 4653, "mathPlus": 23520, "mathMinus": 23520, "mathMultiply": 23520,
               "mathDivide": 23520, "mathEqual": 23520, "mathNotEqual": 23520, "uturnArrow": 25000,
               "bentArrow": 25000}


def _poly(pts) -> QPainterPath:
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))
    p.closeSubpath()
    return p


def _regular(n, w, h, rot=-90.0) -> list:
    return [(w / 2 + w / 2 * math.cos(math.radians(rot + 360 * i / n)),
             h / 2 + h / 2 * math.sin(math.radians(rot + 360 * i / n))) for i in range(n)]


def _star(n, w, h, inner) -> QPainterPath:
    pts = []
    for i in range(2 * n):
        r = 1.0 if i % 2 == 0 else inner
        a = math.radians(-90 + 180 * i / n)
        pts.append((w / 2 + w / 2 * r * math.cos(a), h / 2 + h / 2 * r * math.sin(a)))
    return _poly(pts)


def _arrow_h(w, h, a1, a2, left=False, right=True) -> QPainterPath:
    """Horizontal block arrow; a1 = shaft thickness (fraction of h), a2 = head length (fraction of min)."""
    ss = min(w, h)
    head = min(ss * a2, w / (2 if left and right else 1))
    t = h * a1
    y1, y2 = (h - t) / 2, (h + t) / 2
    x0 = head if left else 0
    x1 = w - head if right else w
    pts = []
    if left:
        pts += [(0, h / 2), (x0, 0), (x0, y1)]
    else:
        pts += [(0, y1)]
    pts += [(x1, y1)]
    if right:
        pts += [(x1, 0), (w, h / 2), (x1, h)]
    pts += [(x1, y2)]
    if left:
        pts += [(x0, y2), (x0, h)]
    else:
        pts += [(0, y2)]
    return _poly(pts)


def _rot90(path: QPainterPath, w, h, ccw=False) -> QPainterPath:
    """A path drawn in an h x w box, turned to fit w x h (for the vertical arrows)."""
    from PySide6.QtGui import QTransform
    t = QTransform()
    if ccw:
        t.translate(0, h)
        t.rotate(-90)
    else:
        t.translate(w, 0)
        t.rotate(90)
    return t.map(path)


def preset_path(name: str, w: float, h: float, adj: dict | None = None) -> QPainterPath:
    """The outline of a preset shape; open shapes (lines, arcs, brackets) are not closed."""
    adj = adj or {}
    a = adj.get("adj", adj.get("adj1", DEFAULT_ADJ.get(name, 0))) / 100000.0
    ss = min(w, h)
    p = QPainterPath()
    r = QRectF(0, 0, w, h)
    if name in ("rect", "flowChartProcess", "textBox"):
        p.addRect(r)
    elif name in ("roundRect", "flowChartAlternateProcess"):
        rr = ss * a
        p.addRoundedRect(r, rr, rr)
    elif name == "snip1Rect":
        d = ss * a
        p = _poly([(0, 0), (w - d, 0), (w, d), (w, h), (0, h)])
    elif name == "snip2SameRect":
        d = ss * a
        p = _poly([(d, 0), (w - d, 0), (w, d), (w, h), (0, h), (0, d)])
    elif name == "round1Rect":
        d = ss * a
        p.moveTo(0, 0)
        p.lineTo(w - d, 0)
        p.arcTo(QRectF(w - 2 * d, 0, 2 * d, 2 * d), 90, -90)
        p.lineTo(w, h)
        p.lineTo(0, h)
        p.closeSubpath()
    elif name == "round2SameRect":
        d = ss * a
        p.moveTo(d, 0)
        p.lineTo(w - d, 0)
        p.arcTo(QRectF(w - 2 * d, 0, 2 * d, 2 * d), 90, -90)
        p.lineTo(w, h)
        p.lineTo(0, h)
        p.lineTo(0, d)
        p.arcTo(QRectF(0, 0, 2 * d, 2 * d), 180, -90)
        p.closeSubpath()
    elif name in ("ellipse", "flowChartConnector"):
        p.addEllipse(r)
    elif name in ("triangle", "flowChartExtract"):
        p = _poly([(w * (a if name == "triangle" else 0.5), 0), (w, h), (0, h)])
    elif name == "flowChartMerge":
        p = _poly([(0, 0), (w, 0), (w / 2, h)])
    elif name == "rtTriangle":
        p = _poly([(0, 0), (w, h), (0, h)])
    elif name in ("parallelogram", "flowChartInputOutput"):
        d = ss * (a if name == "parallelogram" else 0.2)
        if name == "flowChartInputOutput":
            d = w * 0.2
        p = _poly([(d, 0), (w, 0), (w - d, h), (0, h)])
    elif name in ("trapezoid", "flowChartManualOperation"):
        d = ss * a if name == "trapezoid" else w * 0.2
        p = _poly([(0, 0), (w, 0), (w - d, h), (d, h)]) if name == "flowChartManualOperation" else \
            _poly([(d, 0), (w - d, 0), (w, h), (0, h)])
    elif name in ("diamond", "flowChartDecision"):
        p = _poly([(w / 2, 0), (w, h / 2), (w / 2, h), (0, h / 2)])
    elif name == "pentagon":
        p = _poly([(w / 2, 0), (w, h * 0.382), (w * 0.81, h), (w * 0.19, h), (0, h * 0.382)])
    elif name == "hexagon":
        d = ss * a
        p = _poly([(d, 0), (w - d, 0), (w, h / 2), (w - d, h), (d, h), (0, h / 2)])
    elif name in ("heptagon", "decagon", "dodecagon"):
        p = _poly(_regular({"heptagon": 7, "decagon": 10, "dodecagon": 12}[name], w, h))
    elif name == "octagon":
        d = ss * a
        p = _poly([(d, 0), (w - d, 0), (w, d), (w, h - d), (w - d, h), (d, h), (0, h - d), (0, d)])
    elif name == "flowChartPreparation":
        d = w * 0.2
        p = _poly([(d, 0), (w - d, 0), (w, h / 2), (w - d, h), (d, h), (0, h / 2)])
    elif name == "pie":
        start, end = adj.get("adj1", 0) / 60000.0, adj.get("adj2", 16200000) / 60000.0
        p.moveTo(w / 2, h / 2)
        p.arcTo(r, -start, -((end - start) % 360 or 360))
        p.closeSubpath()
    elif name == "chord":
        start, end = adj.get("adj1", 2700000) / 60000.0, adj.get("adj2", 16200000) / 60000.0
        p.arcMoveTo(r, -start)
        p.arcTo(r, -start, -((end - start) % 360 or 360))
        p.closeSubpath()
    elif name == "arc":
        start, end = adj.get("adj1", 16200000) / 60000.0, adj.get("adj2", 0) / 60000.0
        p.arcMoveTo(r, -start)
        p.arcTo(r, -start, -((end - start) % 360 or 360))
    elif name == "teardrop":
        p.moveTo(w / 2, 0)
        p.lineTo(w, 0)
        p.lineTo(w, h / 2)
        p.arcTo(r, 0, -270)
        p.closeSubpath()
    elif name == "frame":
        d = ss * a
        p.addRect(r)
        p.addRect(QRectF(d, d, w - 2 * d, h - 2 * d))
    elif name == "plus":
        d = ss * a
        p = _poly([(d, 0), (w - d, 0), (w - d, d), (w, d), (w, h - d), (w - d, h - d), (w - d, h), (d, h),
                   (d, h - d), (0, h - d), (0, d), (d, d)])
    elif name == "plaque":
        d = ss * a
        p.moveTo(d, 0)
        p.lineTo(w - d, 0)
        p.arcTo(QRectF(w - d, -d, 2 * d, 2 * d), 180, 90)
        p.lineTo(w, h - d)
        p.arcTo(QRectF(w - d, h - d, 2 * d, 2 * d), 90, 90)
        p.lineTo(d, h)
        p.arcTo(QRectF(-d, h - d, 2 * d, 2 * d), 0, 90)
        p.lineTo(0, d)
        p.arcTo(QRectF(-d, -d, 2 * d, 2 * d), 270, 90)
        p.closeSubpath()
    elif name in ("can", "flowChartMagneticDisk"):
        d = ss * a / 2 if name == "can" else h * 0.1
        p.moveTo(0, d)
        p.arcTo(QRectF(0, 0, w, 2 * d), 180, 180)
        p.lineTo(w, h - d)
        p.arcTo(QRectF(0, h - 2 * d, w, 2 * d), 0, -180)
        p.closeSubpath()
        p.moveTo(0, d)
        p.arcTo(QRectF(0, 0, w, 2 * d), 180, 180)
    elif name == "cube":
        d = ss * a
        p = _poly([(0, d), (d, 0), (w, 0), (w, h - d), (w - d, h), (0, h)])
        p.addPolygon(QPolygonF([QPointF(0, d), QPointF(w - d, d), QPointF(w, 0)]))
        p.moveTo(w - d, d)
        p.lineTo(w - d, h)
    elif name == "bevel":
        d = ss * a
        p.addRect(r)
        p.addRect(QRectF(d, d, w - 2 * d, h - 2 * d))
        for x1, y1, x2, y2 in ((0, 0, d, d), (w, 0, w - d, d), (0, h, d, h - d), (w, h, w - d, h - d)):
            p.moveTo(x1, y1)
            p.lineTo(x2, y2)
    elif name == "donut":
        d = ss * a
        p.addEllipse(r)
        p.addEllipse(QRectF(d, d, w - 2 * d, h - 2 * d))
    elif name == "noSmoking":
        d = ss * a
        p.addEllipse(r)
        inner = QPainterPath()
        inner.addEllipse(QRectF(d, d, w - 2 * d, h - 2 * d))
        bar = QPainterPath()
        from PySide6.QtGui import QTransform
        bar.addRect(QRectF(-w, -d / 2, 2 * w, d))
        t = QTransform()
        t.translate(w / 2, h / 2)
        t.rotate(45)
        bar = t.map(bar)
        p = p.subtracted(inner.subtracted(bar))
    elif name == "blockArc":
        d = ss * a
        p.arcMoveTo(r, 180)
        p.arcTo(r, 180, -180)
        inner = QRectF(d, d, w - 2 * d, h - 2 * d)
        p.arcTo(inner, 0, 180)
        p.closeSubpath()
    elif name == "foldedCorner":
        d = ss * a
        p = _poly([(0, 0), (w, 0), (w, h - d), (w - d, h), (0, h)])
        p.addPolygon(QPolygonF([QPointF(w - d, h), QPointF(w - d * 0.8, h - d * 0.8), QPointF(w, h - d)]))
    elif name == "smileyFace":
        p.addEllipse(r)
        p.addEllipse(QRectF(w * 0.3, h * 0.3, w * 0.1, h * 0.1))
        p.addEllipse(QRectF(w * 0.6, h * 0.3, w * 0.1, h * 0.1))
        p.moveTo(w * 0.25, h * 0.65)
        p.quadTo(w * 0.5, h * 0.85, w * 0.75, h * 0.65)
    elif name == "heart":
        p.moveTo(w / 2, h * 0.25)
        p.cubicTo(w * 0.5, h * -0.1, w * -0.15, h * 0.05, w * 0.05, h * 0.42)
        p.cubicTo(w * 0.15, h * 0.62, w * 0.4, h * 0.8, w / 2, h)
        p.cubicTo(w * 0.6, h * 0.8, w * 0.85, h * 0.62, w * 0.95, h * 0.42)
        p.cubicTo(w * 1.15, h * 0.05, w * 0.5, h * -0.1, w / 2, h * 0.25)
        p.closeSubpath()
    elif name == "lightningBolt":
        pts = [(0.39, 0), (0.62, 0.32), (0.53, 0.36), (0.79, 0.62), (0.71, 0.66), (1, 1), (0.45, 0.72),
               (0.55, 0.68), (0.22, 0.47), (0.33, 0.42), (0, 0.18)]
        p = _poly([(x * w, y * h) for x, y in pts])
    elif name == "sun":
        d = a
        p.addEllipse(QRectF(w * (0.5 - (0.5 - d) * 0.6), h * (0.5 - (0.5 - d) * 0.6),
                            w * (1 - d) * 0.6, h * (1 - d) * 0.6))
        for i in range(8):
            ang = math.radians(i * 45)
            cx, cy = w / 2 + math.cos(ang) * w * 0.42, h / 2 + math.sin(ang) * h * 0.42
            tri = []
            for da, rr in ((0, 0.08), (120, 0.06), (240, 0.06)):
                b = ang + math.radians(da)
                tri.append((cx + math.cos(b) * w * rr, cy + math.sin(b) * h * rr))
            p.addPolygon(QPolygonF([QPointF(x, y) for x, y in tri]))
            p.closeSubpath()
    elif name == "moon":
        d = w * a
        p.moveTo(w, 0)
        p.arcTo(QRectF(0, 0, 2 * w, h), 90, 180)
        p.arcTo(QRectF(d, 0, 2 * (w - d), h), 270, -180)
        p.closeSubpath()
    elif name in ("cloud", "cloudCallout"):
        circles = [(0.2, 0.45, 0.22), (0.38, 0.28, 0.24), (0.62, 0.25, 0.25), (0.8, 0.45, 0.2), (0.65, 0.68, 0.22),
                   (0.38, 0.7, 0.22), (0.18, 0.62, 0.16)]
        for cx, cy, rr in circles:
            e = QPainterPath()
            e.addEllipse(QPointF(cx * w, cy * h), rr * w, rr * h)
            p = p.united(e)
        if name == "cloudCallout":
            ax = w / 2 + adj.get("adj1", -20833) / 100000.0 * w
            ay = h / 2 + adj.get("adj2", 62500) / 100000.0 * h
            for t, rr in ((0.45, 0.035), (0.7, 0.025), (0.9, 0.015)):
                e = QPainterPath()
                e.addEllipse(QPointF(w / 2 + (ax - w / 2) * t, h * 0.7 + (ay - h * 0.7) * t), rr * w, rr * h)
                p.addPath(e)
    elif name == "bracketPair":
        d = ss * a
        p.moveTo(d, h)
        p.arcTo(QRectF(0, h - 2 * d, 2 * d, 2 * d), 270, -90)
        p.lineTo(0, d)
        p.arcTo(QRectF(0, 0, 2 * d, 2 * d), 180, -90)
        p.moveTo(w - d, 0)
        p.arcTo(QRectF(w - 2 * d, 0, 2 * d, 2 * d), 90, -90)
        p.lineTo(w, h - d)
        p.arcTo(QRectF(w - 2 * d, h - 2 * d, 2 * d, 2 * d), 0, -90)
    elif name in ("leftBracket", "rightBracket"):
        d = min(h * a, w)
        p.moveTo(w, h)
        p.arcTo(QRectF(0, h - 2 * d, 2 * w, 2 * d), 270, -90)
        p.lineTo(0, d)
        p.arcTo(QRectF(0, 0, 2 * w, 2 * d), 180, -90)
        if name == "rightBracket":
            from PySide6.QtGui import QTransform
            p = QTransform(-1, 0, 0, 1, w, 0).map(p)
    elif name in ("leftBrace", "rightBrace", "bracePair"):
        def brace(x0, ww, hh, flip):
            q = QPainterPath()
            d = min(hh * 0.083, ww)
            q.moveTo(ww, 0)
            q.quadTo(ww / 2, 0, ww / 2, d)
            q.lineTo(ww / 2, hh / 2 - d)
            q.quadTo(ww / 2, hh / 2, 0, hh / 2)
            q.quadTo(ww / 2, hh / 2, ww / 2, hh / 2 + d)
            q.lineTo(ww / 2, hh - d)
            q.quadTo(ww / 2, hh, ww, hh)
            from PySide6.QtGui import QTransform
            if flip:
                q = QTransform(-1, 0, 0, 1, ww, 0).map(q)
            return q.translated(x0, 0)
        if name == "bracePair":
            bw = min(w * 0.15, h * 0.1)
            p = brace(0, bw, h, False)
            p.addPath(brace(w - bw, bw, h, True))
        else:
            p = brace(0, w, h, name == "rightBrace")
    elif name in ("rightArrow", "leftArrow", "leftRightArrow"):
        a1 = adj.get("adj1", 50000) / 100000.0
        a2 = adj.get("adj2", 50000) / 100000.0
        p = _arrow_h(w, h, a1, a2, left=name != "rightArrow", right=name != "leftArrow")
    elif name in ("upArrow", "downArrow", "upDownArrow"):
        a1 = adj.get("adj1", 50000) / 100000.0
        a2 = adj.get("adj2", 50000) / 100000.0
        q = _arrow_h(h, w, a1, a2, left=name != "downArrow", right=name != "upArrow")
        p = _rot90(q, w, h)
        if name in ("upArrow", "downArrow"):
            from PySide6.QtGui import QTransform
            p = QTransform(-1, 0, 0, 1, w, 0).map(p)
    elif name == "quadArrow":
        t = ss * 0.11
        hd = ss * 0.22
        cx, cy = w / 2, h / 2
        p = _poly([(cx, 0), (cx + hd, hd), (cx + t, hd), (cx + t, cy - t), (w - hd, cy - t), (w - hd, cy - hd),
                   (w, cy), (w - hd, cy + hd), (w - hd, cy + t), (cx + t, cy + t), (cx + t, h - hd),
                   (cx + hd, h - hd), (cx, h), (cx - hd, h - hd), (cx - t, h - hd), (cx - t, cy + t),
                   (hd, cy + t), (hd, cy + hd), (0, cy), (hd, cy - hd), (hd, cy - t), (cx - t, cy - t),
                   (cx - t, hd), (cx - hd, hd)])
    elif name == "notchedRightArrow":
        head = min(ss * 0.5, w)
        t = h * 0.5
        y1, y2 = (h - t) / 2, (h + t) / 2
        p = _poly([(0, y1), (w - head, y1), (w - head, 0), (w, h / 2), (w - head, h), (w - head, y2), (0, y2),
                   (head * 0.5, h / 2)])
    elif name == "stripedRightArrow":
        p = _arrow_h(w, h, 0.5, 0.5)
        x = w * 0.13
        p = p.subtracted(_poly([(0, 0), (x * 0.25, 0), (x * 0.25, h), (0, h)]))
        p = p.subtracted(_poly([(x * 0.4, 0), (x * 0.55, 0), (x * 0.55, h), (x * 0.4, h)]))
    elif name == "homePlate":
        d = min(ss * a, w)
        p = _poly([(0, 0), (w - d, 0), (w, h / 2), (w - d, h), (0, h)])
    elif name == "chevron":
        d = min(ss * a, w / 2)
        p = _poly([(0, 0), (w - d, 0), (w, h / 2), (w - d, h), (0, h), (d, h / 2)])
    elif name == "uturnArrow":
        t = ss * 0.25
        hd = ss * 0.25
        top = h * 0.25
        p.moveTo(0, h)
        p.lineTo(0, t * 1.5)
        p.arcTo(QRectF(0, 0, w - hd, t * 3), 180, -180)
        p.lineTo(w - hd, top + t)
        p.lineTo(w, top + t)
        p.lineTo(w - hd * 1.5, top + t + hd)
        p.lineTo(w - hd * 2.5, top + t)
        p.lineTo(w - hd * 2, top + t)
        p.lineTo(w - hd * 2, t * 1.5)
        p.arcTo(QRectF(t, t, w - hd * 2 - t, t * 1.0), 0, 180)
        p.lineTo(t, h)
        p.closeSubpath()
    elif name == "bentArrow":
        t = ss * 0.25
        hd = ss * 0.25
        p = _poly([(0, h), (0, hd + t / 2), (w - hd, hd + t / 2 - t / 2), (w - hd, 0), (w, hd), (w - hd, 2 * hd),
                   (w - hd, hd + t / 2), (t, hd + t / 2), (t, h)])
    elif name in ("mathPlus", "mathMinus", "mathMultiply", "mathDivide", "mathEqual", "mathNotEqual"):
        t = ss * a
        if name == "mathPlus":
            m = ss * 0.1
            p = _poly([(w / 2 - t / 2, m), (w / 2 + t / 2, m), (w / 2 + t / 2, h / 2 - t / 2), (w - m, h / 2 - t / 2),
                       (w - m, h / 2 + t / 2), (w / 2 + t / 2, h / 2 + t / 2), (w / 2 + t / 2, h - m),
                       (w / 2 - t / 2, h - m), (w / 2 - t / 2, h / 2 + t / 2), (m, h / 2 + t / 2),
                       (m, h / 2 - t / 2), (w / 2 - t / 2, h / 2 - t / 2)])
        elif name == "mathMinus":
            p.addRect(QRectF(w * 0.1, h / 2 - t / 2, w * 0.8, t))
        elif name == "mathMultiply":
            from PySide6.QtGui import QTransform
            q = preset_path("mathPlus", ss, ss, {"adj1": adj.get("adj1", 23520)})
            tr = QTransform()
            tr.translate(w / 2, h / 2)
            tr.scale(w / ss, h / ss)
            tr.rotate(45)
            tr.translate(-ss / 2, -ss / 2)
            p = tr.map(q)
        elif name == "mathDivide":
            p.addRect(QRectF(w * 0.1, h / 2 - t / 2, w * 0.8, t))
            p.addEllipse(QPointF(w / 2, h / 2 - t * 1.6), t * 0.7, t * 0.7)
            p.addEllipse(QPointF(w / 2, h / 2 + t * 1.6), t * 0.7, t * 0.7)
        else:
            p.addRect(QRectF(w * 0.1, h / 2 - t * 1.3, w * 0.8, t))
            p.addRect(QRectF(w * 0.1, h / 2 + t * 0.3, w * 0.8, t))
            if name == "mathNotEqual":
                p = p.united(_poly([(w * 0.58, h * 0.12), (w * 0.66, h * 0.16), (w * 0.42, h * 0.88),
                                    (w * 0.34, h * 0.84)]))
    elif name == "flowChartPredefinedProcess":
        p.addRect(r)
        p.moveTo(w * 0.125, 0)
        p.lineTo(w * 0.125, h)
        p.moveTo(w * 0.875, 0)
        p.lineTo(w * 0.875, h)
    elif name == "flowChartDocument":
        p.moveTo(0, 0)
        p.lineTo(w, 0)
        p.lineTo(w, h * 0.83)
        p.cubicTo(w * 0.75, h * 0.7, w * 0.5, h * 0.95, w * 0.25, h * 1.0)
        p.cubicTo(w * 0.12, h * 1.02, 0, h * 0.95, 0, h * 0.92)
        p.closeSubpath()
    elif name == "flowChartTerminator":
        p.addRoundedRect(r, min(h / 2, w / 2), h / 2)
    elif name == "flowChartManualInput":
        p = _poly([(0, h * 0.2), (w, 0), (w, h), (0, h)])
    elif name == "flowChartOffpageConnector":
        p = _poly([(0, 0), (w, 0), (w, h * 0.8), (w / 2, h), (0, h * 0.8)])
    elif name == "flowChartDelay":
        p.moveTo(0, 0)
        p.lineTo(w / 2, 0)
        p.arcTo(QRectF(0, 0, w, h), 90, -180)
        p.lineTo(0, h)
        p.closeSubpath()
    elif name.startswith("star") and name[4:].isdigit():
        n = int(name[4:])
        p = _star(n, w, h, max(0.05, min(1.0, 2 * a)))
    elif name in ("irregularSeal1", "irregularSeal2"):
        pts = [(0.5, 0.1), (0.62, 0.28), (0.82, 0.08), (0.78, 0.33), (1.0, 0.36), (0.83, 0.5), (0.97, 0.72),
               (0.73, 0.65), (0.7, 0.92), (0.55, 0.72), (0.38, 1.0), (0.36, 0.73), (0.08, 0.83), (0.24, 0.6),
               (0.0, 0.47), (0.22, 0.38), (0.12, 0.12), (0.37, 0.27)]
        p = _poly([(x * w, y * h) for x, y in pts])
    elif name in ("wave", "doubleWave"):
        d = h * (a if name == "wave" else a * 1.5)
        n = 1 if name == "wave" else 2
        p.moveTo(0, d)
        for i in range(n):
            x0, x1 = w * i / n, w * (i + 1) / n
            p.cubicTo(x0 + (x1 - x0) / 3, -d, x0 + 2 * (x1 - x0) / 3, 3 * d, x1, d)
        p.lineTo(w, h - d)
        for i in range(n, 0, -1):
            x0, x1 = w * i / n, w * (i - 1) / n
            p.cubicTo(x0 + (x1 - x0) / 3, h + d, x0 + 2 * (x1 - x0) / 3, h - 3 * d, x1, h - d)
        p.closeSubpath()
    elif name in ("wedgeRectCallout", "wedgeRoundRectCallout", "wedgeEllipseCallout"):
        ax = w / 2 + adj.get("adj1", -20833) / 100000.0 * w
        ay = h / 2 + adj.get("adj2", 62500) / 100000.0 * h
        body = QPainterPath()
        if name == "wedgeEllipseCallout":
            body.addEllipse(r)
        elif name == "wedgeRoundRectCallout":
            body.addRoundedRect(r, ss * 0.1667, ss * 0.1667)
        else:
            body.addRect(r)
        cx, cy = w / 2, h / 2
        ang = math.atan2(ay - cy, ax - cx)
        spread = 0.18
        b1 = (cx + math.cos(ang - spread) * w * 0.3, cy + math.sin(ang - spread) * h * 0.3)
        b2 = (cx + math.cos(ang + spread) * w * 0.3, cy + math.sin(ang + spread) * h * 0.3)
        p = body.united(_poly([b1, (ax, ay), b2]))
    elif name in ("line", "straightConnector1", "doubleArrowLine", "bentConnector2", "bentConnector3",
                  "curvedConnector3"):
        p.moveTo(0, 0)
        if name == "bentConnector3":
            p.lineTo(w / 2, 0)
            p.lineTo(w / 2, h)
        elif name == "bentConnector2":
            p.lineTo(w, 0)
        elif name == "curvedConnector3":
            p.cubicTo(w / 2, 0, w / 2, h, w, h)
            return p
        p.lineTo(w, h)
    else:
        p.addRect(r)
    return p


def custom_path(paths: list, w: float, h: float) -> QPainterPath:
    """custGeom: [(pw, ph, [commands]), ...] scaled to w x h."""
    out = QPainterPath()
    for pw, ph, cmds, *rest in paths:
        sx = w / pw if pw else 1.0
        sy = h / ph if ph else 1.0
        cur = QPointF(0, 0)
        for c in cmds:
            op = c[0]
            if op == "M":
                cur = QPointF(c[1] * sx, c[2] * sy)
                out.moveTo(cur)
            elif op == "L":
                cur = QPointF(c[1] * sx, c[2] * sy)
                out.lineTo(cur)
            elif op == "C":
                out.cubicTo(c[1] * sx, c[2] * sy, c[3] * sx, c[4] * sy, c[5] * sx, c[6] * sy)
                cur = QPointF(c[5] * sx, c[6] * sy)
            elif op == "Q":
                out.quadTo(c[1] * sx, c[2] * sy, c[3] * sx, c[4] * sy)
                cur = QPointF(c[3] * sx, c[4] * sy)
            elif op == "A":          # arcTo: wR hR stAng swAng (60000ths of a degree)
                wr, hr = c[1] * sx, c[2] * sy
                st, sw = c[3] / 60000.0, c[4] / 60000.0
                cx = cur.x() - wr * math.cos(math.radians(st))
                cy = cur.y() - hr * math.sin(math.radians(st))
                out.arcTo(QRectF(cx - wr, cy - hr, 2 * wr, 2 * hr), -st, -sw)
                cur = out.currentPosition()
            elif op == "Z":
                out.closeSubpath()
    return out


def text_rect(name: str, w: float, h: float) -> QRectF:
    """Where the text of a preset shape goes (before insets)."""
    if name in ("ellipse", "flowChartConnector", "wedgeEllipseCallout", "donut", "noSmoking", "smileyFace", "sun",
                "cloud", "cloudCallout"):
        k = 0.1464
        return QRectF(w * k, h * k, w * (1 - 2 * k), h * (1 - 2 * k))
    if name in ("diamond", "flowChartDecision"):
        return QRectF(w / 4, h / 4, w / 2, h / 2)
    if name in ("triangle", "flowChartExtract"):
        return QRectF(w / 4, h / 2, w / 2, h / 2)
    if name == "rtTriangle":
        return QRectF(w / 12, h * 7 / 12, w / 2, h * 5 / 12)
    if name in ("parallelogram", "trapezoid", "flowChartInputOutput", "flowChartManualOperation"):
        return QRectF(w * 0.2, 0, w * 0.6, h)
    if name in ("hexagon", "octagon", "flowChartPreparation", "chevron", "homePlate"):
        return QRectF(w * 0.15, h * 0.1, w * 0.7, h * 0.8)
    if name.startswith("star") or name.startswith("irregularSeal"):
        return QRectF(w * 0.25, h * 0.3, w * 0.5, h * 0.45)
    if name in ("can", "flowChartMagneticDisk", "cube"):
        return QRectF(0, h * 0.2, w * (0.8 if name == "cube" else 1), h * 0.75)
    if name == "flowChartPredefinedProcess":
        return QRectF(w * 0.125, 0, w * 0.75, h)
    if name == "heart":
        return QRectF(w * 0.18, h * 0.2, w * 0.64, h * 0.5)
    return QRectF(0, 0, w, h)
