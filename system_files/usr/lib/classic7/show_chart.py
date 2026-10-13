"""Show: drawing the charts of PowerPoint files (column/bar, line, area, pie/doughnut, scatter,
radar) from the numbers cached in the chart part. Charts are shown, and saved back unchanged."""
from __future__ import annotations

import math

from lxml import etree
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS = {"c": C[1:-1], "a": A[1:-1]}
ACCENTS = ["accent1", "accent2", "accent3", "accent4", "accent5", "accent6"]


def _val(el, tag, default=None):
    x = el.find(tag, NS) if el is not None else None
    return x.get("val", default) if x is not None else default


def _cache(el) -> list:
    """Values of a strRef/numRef/strLit/numLit: list indexed by point."""
    if el is None:
        return []
    cache = None
    for path in ("c:strRef/c:strCache", "c:numRef/c:numCache", "c:strLit", "c:numLit",
                 "c:multiLvlStrRef/c:multiLvlStrCache/c:lvl"):
        cache = el.find(path, NS)
        if cache is not None:
            break
    if cache is None:
        return []
    n = int(_val(cache, "c:ptCount", "0") or 0)
    out = [None] * n
    for pt in cache.findall("c:pt", NS):
        i = int(pt.get("idx", "0"))
        v = pt.find("c:v", NS)
        if v is not None and i < 100000:
            if i >= len(out):
                out += [None] * (i + 1 - len(out))
            out[i] = v.text
    return out


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _color_of(sppr):
    if sppr is None:
        return None
    from show_pptx import parse_color
    fill = sppr.find("a:solidFill", NS)
    if fill is not None:
        return parse_color(fill)
    grad = sppr.find("a:gradFill/a:gsLst/a:gs", NS)
    if grad is not None:
        return parse_color(grad)
    ln = sppr.find("a:ln/a:solidFill", NS)
    if ln is not None:
        return parse_color(ln)
    return None


def _rich_text(tx) -> str:
    if tx is None:
        return ""
    rich = tx.find("c:rich", NS)
    if rich is not None:
        return "\n".join("".join(t.text or "" for t in p.iter(A + "t")) for p in rich.findall("a:p", NS)).strip()
    ref = _cache(tx)
    return " ".join(v for v in ref if v)


def parse(xml: bytes) -> dict | None:
    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None
    chart = root.find("c:chart", NS)
    if chart is None:
        return None
    out = {"title": None, "legend": None, "plots": [], "style": int(_val(root, "c:style", "2") or 2)}
    t = chart.find("c:title", NS)
    if t is not None:
        out["title"] = _rich_text(t.find("c:tx", NS)) or ""
    if _val(chart, "c:autoTitleDeleted") in ("1", "true"):
        out["title"] = out["title"] or None
    lg = chart.find("c:legend", NS)
    if lg is not None:
        out["legend"] = _val(lg, "c:legendPos", "r")
    plot = chart.find("c:plotArea", NS)
    if plot is None:
        return out
    for el in plot:
        tag = etree.QName(el).localname
        if not tag.endswith("Chart"):
            continue
        p = {"type": tag[:-5], "dir": _val(el, "c:barDir", "col"), "grouping": _val(el, "c:grouping", "clustered"),
             "vary": _val(el, "c:varyColors") in ("1", "true"), "hole": _num(_val(el, "c:holeSize")) or 50,
             "series": [], "radar": _val(el, "c:radarStyle", "marker"),
             "scatter_style": _val(el, "c:scatterStyle", "lineMarker")}
        for ser in el.findall("c:ser", NS):
            s = {"name": _rich_text(ser.find("c:tx", NS)), "idx": int(_val(ser, "c:idx", "0") or 0),
                 "cat": _cache(ser.find("c:cat", NS)) or _cache(ser.find("c:xVal", NS)),
                 "val": [_num(v) for v in (_cache(ser.find("c:val", NS)) or _cache(ser.find("c:yVal", NS)))],
                 "color": _color_of(ser.find("c:spPr", NS)), "points": {}}
            for dpt in ser.findall("c:dPt", NS):
                c = _color_of(dpt.find("c:spPr", NS))
                if c is not None:
                    s["points"][int(_val(dpt, "c:idx", "0") or 0)] = c
            s["marker"] = _val(ser.find("c:marker", NS), "c:symbol", "none" if p["type"] != "scatter" else "circle")
            p["series"].append(s)
        out["plots"].append(p)
    return out


def _nice(lo, hi):
    if hi <= lo:
        hi = lo + 1
    span = hi - lo
    step = 10 ** math.floor(math.log10(span / 5))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= 6:
            step *= m
            break
    lo = math.floor(lo / step) * step
    hi = math.ceil(hi / step) * step
    return lo, hi, step


def _fmt(v):
    from PySide6.QtCore import QLocale
    loc = QLocale()
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", loc.groupSeparator())
    return f"{v:g}".replace(".", loc.decimalPoint())


def paint(p: QPainter, rect: QRectF, chart: dict, ctx):
    """Draw the chart into rect (points) with the slide's theme colours."""
    if not chart or not chart.get("plots"):
        return False
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    font = QFont(ctx.theme.minor_font)
    size = max(6.0, min(12.0, rect.height() / 25))
    font.setPointSizeF(size)
    p.setFont(font)
    fm = QFontMetricsF(font)
    text_color = ctx.color({"scheme": "tx1", "mods": [["lumMod", 65000], ["lumOff", 35000]]})
    area = QRectF(rect)
    if chart.get("title"):
        tf = QFont(font)
        tf.setPointSizeF(size * 1.5)
        p.setFont(tf)
        p.setPen(text_color)
        th = QFontMetricsF(tf).height() * (chart["title"].count("\n") + 1) + 6
        p.drawText(QRectF(area.left(), area.top(), area.width(), th), Qt.AlignCenter, chart["title"])
        area.setTop(area.top() + th)
        p.setFont(font)
    plot = chart["plots"][0]
    series = [s for pl in chart["plots"] for s in pl["series"]]

    def color(s, i=None, k=0):
        if i is not None and i in s.get("points", {}):
            return ctx.color(s["points"][i])
        if s.get("color"):
            return ctx.color(s["color"])
        n = s["idx"] if i is None else i
        base = {"scheme": ACCENTS[n % 6]}
        if n >= 6:
            base["mods"] = [["lumMod", 60000]]
        return ctx.color(base)
    pie = plot["type"] in ("pie", "doughnut", "pie3D", "ofPie")
    # legend
    legend = chart.get("legend")
    entries = []
    if legend:
        if pie and series:
            cats = series[0]["cat"] or [str(i + 1) for i in range(len(series[0]["val"]))]
            entries = [(str(c or ""), color(series[0], i)) for i, c in enumerate(cats)]
        else:
            entries = [(s["name"] or f"Series {k + 1}", color(s)) for k, s in enumerate(series)]
        box = fm.height() * 0.7
        if legend in ("r", "l", "tr"):
            lw = min(area.width() * 0.35, max((fm.horizontalAdvance(t) for t, _c in entries), default=0) + box + 12)
            lx = area.right() - lw if legend != "l" else area.left()
            total_h = len(entries) * fm.height() * 1.2
            y = area.center().y() - total_h / 2
            for t, c in entries:
                p.fillRect(QRectF(lx + 4, y + (fm.height() - box) / 2, box, box), c)
                p.setPen(text_color)
                p.drawText(QRectF(lx + 8 + box, y, lw - box - 8, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, t)
                y += fm.height() * 1.2
            if legend == "l":
                area.setLeft(area.left() + lw)
            else:
                area.setRight(area.right() - lw)
        else:
            total_w = sum(fm.horizontalAdvance(t) + box + 16 for t, _c in entries)
            x = area.center().x() - total_w / 2
            y = area.bottom() - fm.height() if legend == "b" else area.top()
            for t, c in entries:
                p.fillRect(QRectF(x, y + (fm.height() - box) / 2, box, box), c)
                p.setPen(text_color)
                p.drawText(QPointF(x + box + 4, y + fm.ascent()), t)
                x += fm.horizontalAdvance(t) + box + 16
            if legend == "b":
                area.setBottom(area.bottom() - fm.height() - 4)
            else:
                area.setTop(area.top() + fm.height() + 4)
    area = area.adjusted(4, 4, -4, -4)
    if pie:
        _pie(p, area, plot, series, color, text_color, fm)
    elif plot["type"] == "radar":
        _radar(p, area, series, color, text_color, fm)
    else:
        _axes_chart(p, area, chart, series, color, text_color, fm)
    p.restore()
    return True


def _pie(p, area, plot, series, color, text_color, fm):
    if not series:
        return
    s = series[0]
    vals = [max(0.0, v or 0.0) for v in s["val"]]
    total = sum(vals) or 1
    d = min(area.width(), area.height())
    r = QRectF(area.center().x() - d / 2, area.center().y() - d / 2, d, d)
    start = 90.0
    p.setPen(QPen(QColor("#FFFFFF"), 1))
    for i, v in enumerate(vals):
        span = -360.0 * v / total
        p.setBrush(color(s, i))
        p.drawPie(r, int(start * 16), int(span * 16))
        start += span
    if plot["type"] == "doughnut":
        hole = d * (plot.get("hole") or 50) / 100
        p.setBrush(QColor("#FFFFFF"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(r.center(), hole / 2, hole / 2)


def _radar(p, area, series, color, text_color, fm):
    n = max((len(s["val"]) for s in series), default=0)
    if n < 3:
        return
    vals = [v for s in series for v in s["val"] if v is not None]
    lo, hi, step = _nice(min(0.0, min(vals, default=0)), max(vals, default=1))
    c = area.center()
    rad = min(area.width(), area.height()) / 2 - fm.height()
    p.setPen(QPen(QColor("#D9D9D9"), 0.75))
    k = lo
    while k <= hi + 1e-9:
        rr = rad * (k - lo) / (hi - lo)
        p.drawPolygon(QPolygonF([QPointF(c.x() + rr * math.sin(2 * math.pi * i / n),
                                         c.y() - rr * math.cos(2 * math.pi * i / n)) for i in range(n)]))
        k += step
    for s in series:
        pts = [QPointF(c.x() + rad * ((v or 0) - lo) / (hi - lo) * math.sin(2 * math.pi * i / n),
                       c.y() - rad * ((v or 0) - lo) / (hi - lo) * math.cos(2 * math.pi * i / n))
               for i, v in enumerate(s["val"])]
        p.setPen(QPen(color(s), 2))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(QPolygonF(pts))


def _axes_chart(p, area, chart, series, color, text_color, fm):
    plot = chart["plots"][0]
    horizontal = plot["type"] in ("bar", "bar3D") and plot["dir"] == "bar"
    stacked = plot["grouping"] in ("stacked", "percentStacked")
    percent = plot["grouping"] == "percentStacked"
    ncat = max((len(s["val"]) for s in series), default=0)
    if ncat == 0:
        return
    cats = next((s["cat"] for s in series if s["cat"]), []) or [str(i + 1) for i in range(ncat)]
    scatter = plot["type"] == "scatter"
    if stacked:
        pos = [sum(max(0.0, s["val"][i] or 0) for s in series if i < len(s["val"])) for i in range(ncat)]
        neg = [sum(min(0.0, s["val"][i] or 0) for s in series if i < len(s["val"])) for i in range(ncat)]
        lo, hi = (min(neg + [0.0]), max(pos + [0.0])) if not percent else (0.0, 100.0)
    else:
        vals = [v for s in series for v in s["val"] if v is not None]
        lo, hi = min(vals + [0.0]), max(vals + [0.0])
    lo, hi, step = _nice(lo, hi)
    label_w = max(fm.horizontalAdvance(_fmt(lo)), fm.horizontalAdvance(_fmt(hi))) + 6
    if horizontal:
        label_w = max((fm.horizontalAdvance(str(c or "")) for c in cats), default=20) + 6
    # category labels that don't fit side by side are turned 45 degrees, as in Office
    cat_w = max((fm.horizontalAdvance(str(c or "")) for c in cats[:ncat]), default=0)
    slanted = (not horizontal and not scatter and ncat > 1
               and cat_w > (area.width() - label_w - 4) / ncat - 4)
    bottom = min(cat_w * 0.72 + fm.height(), area.height() * 0.4) if slanted else fm.height() * 1.8
    plot_r = QRectF(area.left() + label_w, area.top() + fm.height() / 2, area.width() - label_w - 4,
                    area.height() - fm.height() / 2 - bottom)
    if plot_r.width() < 10 or plot_r.height() < 10:
        return

    def vpos(v):
        f = (v - lo) / (hi - lo) if hi != lo else 0
        return plot_r.left() + f * plot_r.width() if horizontal else plot_r.bottom() - f * plot_r.height()
    # grid and value labels
    p.setPen(QPen(QColor("#D9D9D9"), 0.75))
    k = lo
    while k <= hi + 1e-9:
        x = vpos(k)
        if horizontal:
            p.drawLine(QPointF(x, plot_r.top()), QPointF(x, plot_r.bottom()))
        else:
            p.drawLine(QPointF(plot_r.left(), x), QPointF(plot_r.right(), x))
        k += step
    p.setPen(text_color)
    k = lo
    while k <= hi + 1e-9:
        x = vpos(k)
        label = _fmt(k) + ("%" if percent else "")
        if horizontal:
            p.drawText(QRectF(x - 30, plot_r.bottom() + 2, 60, fm.height()), Qt.AlignHCenter | Qt.AlignTop, label)
        else:
            p.drawText(QRectF(area.left(), x - fm.height() / 2, label_w - 4, fm.height()),
                       Qt.AlignRight | Qt.AlignVCenter, label)
        k += step
    band = (plot_r.height() if horizontal else plot_r.width()) / ncat
    for i, c in enumerate(cats[:ncat]):
        center = (plot_r.bottom() - band * (i + 0.5)) if horizontal else (plot_r.left() + band * (i + 0.5))
        text = str(c or "")
        if scatter:
            continue
        if horizontal:
            p.drawText(QRectF(area.left(), center - fm.height() / 2, label_w - 4, fm.height()),
                       Qt.AlignRight | Qt.AlignVCenter, text)
        elif slanted:
            p.save()
            p.translate(center + fm.height() * 0.3, plot_r.bottom() + 4)
            p.rotate(-45)
            p.drawText(QRectF(-cat_w - 2, -fm.height() / 2, cat_w + 2, fm.height()),
                       Qt.AlignRight | Qt.AlignVCenter, text)
            p.restore()
        else:
            p.drawText(QRectF(center - band / 2, plot_r.bottom() + 2, band, fm.height() * 1.6),
                       Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)
    p.setPen(QPen(QColor("#BFBFBF"), 1))
    if horizontal:
        p.drawLine(QPointF(vpos(max(lo, 0)), plot_r.top()), QPointF(vpos(max(lo, 0)), plot_r.bottom()))
    else:
        p.drawLine(QPointF(plot_r.left(), vpos(max(lo, 0))), QPointF(plot_r.right(), vpos(max(lo, 0))))
    kind = plot["type"]
    if kind in ("bar", "bar3D"):
        nser = max(1, len(series))
        gap = band * 0.25
        acc_pos = [0.0] * ncat
        acc_neg = [0.0] * ncat
        for k_, s in enumerate(series):
            for i, v in enumerate(s["val"][:ncat]):
                if v is None:
                    continue
                if percent:
                    tot = sum(abs(x["val"][i] or 0) for x in series if i < len(x["val"])) or 1
                    v = v / tot * 100
                if stacked:
                    base = acc_pos[i] if v >= 0 else acc_neg[i]
                    a, b = base, base + v
                    if v >= 0:
                        acc_pos[i] = b
                    else:
                        acc_neg[i] = b
                    w0 = gap
                    width = band - 2 * gap
                else:
                    a, b = max(lo, 0.0), v
                    width = (band - 2 * gap) / nser
                    w0 = gap + width * k_
                start = (plot_r.bottom() - band * (i + 1) + w0) if horizontal else (plot_r.left() + band * i + w0)
                p1, p2 = vpos(a), vpos(b)
                r = QRectF(min(p1, p2), start, abs(p2 - p1), width) if horizontal else \
                    QRectF(start, min(p1, p2), width, abs(p2 - p1))
                p.fillRect(r, color(s, i if plot.get("vary") else None))
    elif kind in ("line", "line3D", "area", "area3D", "scatter"):
        acc = [0.0] * ncat
        for s in series:
            pts = []
            for i, v in enumerate(s["val"][:ncat]):
                if v is None:
                    continue
                if stacked:
                    acc[i] += v
                    v = acc[i]
                if scatter:
                    xs = [_num(x) for x in s["cat"]] if s["cat"] else []
                    xv = xs[i] if i < len(xs) and xs[i] is not None else i
                    xlo = min((x for x in xs if x is not None), default=0)
                    xhi = max((x for x in xs if x is not None), default=ncat - 1) or 1
                    x = plot_r.left() + (xv - xlo) / ((xhi - xlo) or 1) * plot_r.width()
                else:
                    x = plot_r.left() + band * (i + 0.5)
                pts.append(QPointF(x, vpos(v)))
            if not pts:
                continue
            col = color(s)
            if kind.startswith("area"):
                path = QPainterPath(QPointF(pts[0].x(), vpos(max(lo, 0))))
                for pt in pts:
                    path.lineTo(pt)
                path.lineTo(QPointF(pts[-1].x(), vpos(max(lo, 0))))
                path.closeSubpath()
                p.fillPath(path, col)
            else:
                p.setPen(QPen(col, 2.25, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                if not scatter or plot.get("scatter_style", "lineMarker") in ("lineMarker", "line", "smooth",
                                                                             "smoothMarker"):
                    p.drawPolyline(QPolygonF(pts))
                if s.get("marker") not in (None, "none") or scatter:
                    p.setBrush(col)
                    p.setPen(Qt.NoPen)
                    for pt in pts:
                        p.drawEllipse(pt, 2.5, 2.5)
