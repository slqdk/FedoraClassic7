"""Charts in Sheet: read from Excel files (with their live cell references), drawn with
Show's chart painter from the current cell values, and written back with openpyxl."""
from __future__ import annotations

import colorsys
import re

from lxml import etree

import sheet_formula as F
from sheet_model import THEME_COLORS, Chart, ChartSeries

C = "{http://schemas.openxmlformats.org/drawingml/2006/chart}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS = {"c": C[1:-1], "a": A[1:-1]}

KINDS = {"barChart": "col", "bar3DChart": "col", "lineChart": "line", "line3DChart": "line", "pieChart": "pie",
         "pie3DChart": "pie", "doughnutChart": "doughnut", "areaChart": "area", "area3DChart": "area",
         "scatterChart": "scatter", "radarChart": "radar", "bubbleChart": "scatter"}

KIND_NAMES = [("col", "Column"), ("bar", "Bar"), ("line", "Line"), ("pie", "Pie"), ("area", "Area"),
              ("scatter", "Scatter"), ("doughnut", "Doughnut"), ("radar", "Radar")]


def _val(el, path, default=None):
    x = el.find(path, NS) if el is not None else None
    return x.get("val", default) if x is not None else default


def _text(el) -> str:
    if el is None:
        return ""
    f = el.find("c:strRef/c:f", NS)
    if f is not None and f.text:
        return "=" + f.text
    rich = el.find("c:rich", NS)
    if rich is not None:
        return "".join(t.text or "" for t in rich.iter(A + "t"))
    v = el.find("c:v", NS)
    return v.text if v is not None and v.text else ""


def _ref(el) -> str:
    if el is None:
        return ""
    for path in ("c:numRef/c:f", "c:strRef/c:f", "c:multiLvlStrRef/c:f"):
        f = el.find(path, NS)
        if f is not None and f.text:
            return f.text
    return ""


def _srgb(sppr) -> str | None:
    if sppr is None:
        return None
    c = sppr.find("a:solidFill/a:srgbClr", NS)
    if c is not None:
        return "#" + c.get("val", "000000").lower()
    return None


def parse_chart(xml: bytes) -> Chart | None:
    try:
        root = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None
    chart = root.find("c:chart", NS)
    plot = chart.find("c:plotArea", NS) if chart is not None else None
    if plot is None:
        return None
    out = Chart(raw=xml, style=int(_val(root, "c:style", "2") or 2))
    t = chart.find("c:title", NS)
    if t is not None:
        out.title = _text(t.find("c:tx", NS)) or ""
    lg = chart.find("c:legend", NS)
    out.legend = _val(lg, "c:legendPos", "r") if lg is not None else ""
    for el in plot:
        tag = etree.QName(el).localname
        if tag not in KINDS:
            continue
        if not out.series:
            out.kind = KINDS[tag]
            if tag.startswith("bar") and _val(el, "c:barDir", "col") == "bar":
                out.kind = "bar"
            out.grouping = _val(el, "c:grouping", "clustered" if "bar" in tag else "standard")
            out.data_labels = _val(el, "c:dLbls/c:showVal") in ("1", "true")
        for ser in el.findall("c:ser", NS):
            s = ChartSeries(name=_text(ser.find("c:tx", NS)),
                            values=_ref(ser.find("c:val", NS)) or _ref(ser.find("c:yVal", NS)),
                            categories=_ref(ser.find("c:cat", NS)) or _ref(ser.find("c:xVal", NS)),
                            color=_srgb(ser.find("c:spPr", NS)))
            out.series.append(s)
            if _val(ser, "c:smooth") in ("1", "true"):
                out.smooth = True
    for ax in list(plot.findall("c:valAx", NS)) + list(plot.findall("c:catAx", NS)):
        title = _text(ax.find("c:title/c:tx", NS))
        if not title:
            continue
        pos = _val(ax, "c:axPos", "b")
        if pos in ("l", "r") and out.kind != "bar" or pos in ("b", "t") and out.kind == "bar":
            out.y_title = title
        else:
            out.x_title = title
    return out


# ---- values for drawing -------------------------------------------------------------------------
def _range_values(book, ref: str, sheet: str):
    if not ref:
        return []
    try:
        tree = F.parse("=" + ref.lstrip("="))
    except F.FormulaError:
        return []
    v = F.evaluate(tree, F.Context(book, sheet, 0, 0))
    if isinstance(v, (F.Range, F.Array)):
        return [x for x in v]
    return [v]


def series_name(book, s: ChartSeries, sheet: str, k: int) -> str:
    if s.name.startswith("="):
        vals = _range_values(book, s.name[1:], sheet)
        return " ".join(F.to_text(v) for v in vals if v is not None and not isinstance(v, F.XLError))
    return s.name or f"Series{k + 1}"


def render_data(book, chart: Chart, sheet: str) -> dict:
    """The structure show_chart.paint() draws, with values read from the cells now."""
    kind = chart.kind
    ptype = {"col": "bar", "bar": "bar", "line": "line", "pie": "pie", "doughnut": "doughnut", "area": "area",
             "scatter": "scatter", "radar": "radar"}.get(kind, "bar")
    plot = {"type": ptype, "dir": "bar" if kind == "bar" else "col", "grouping": chart.grouping,
            "vary": kind in ("pie", "doughnut"), "hole": 50, "series": [], "radar": "marker",
            "scatter_style": "lineMarker"}
    for k, s in enumerate(chart.series):
        cats = _range_values(book, s.categories, sheet)
        vals = []
        for v in _range_values(book, s.values, sheet):
            n = F.to_number(v) if v is not None else None
            vals.append(n if isinstance(n, float) else None)
        plot["series"].append({
            "name": series_name(book, s, sheet, k), "idx": k,
            "cat": [F.to_text(c) if not isinstance(c, F.XLError) else "" for c in cats] if cats else [],
            "val": vals, "color": s.color, "points": {},
            "marker": "none" if kind != "scatter" else "circle"})
    title = chart.title
    if title.startswith("="):
        title = " ".join(F.to_text(v) for v in _range_values(book, title[1:], sheet) if v is not None)
    if not title and len(chart.series) == 1 and kind in ("pie", "doughnut"):
        title = plot["series"][0]["name"] if plot["series"] else ""
    return {"title": title or None, "legend": chart.legend or None, "plots": [plot], "style": chart.style}


class PaintContext:
    """What show_chart.paint() asks of the slide: theme fonts and colours."""

    class _Theme:
        minor_font = "Calibri"
        major_font = "Cambria"

    def __init__(self, theme_colors=None):
        self.theme = self._Theme()
        self.colors = theme_colors or THEME_COLORS

    def color(self, spec):
        from PySide6.QtGui import QColor
        if spec is None:
            return QColor("#000000")
        if isinstance(spec, str):
            return QColor(spec)
        if isinstance(spec, dict):
            base = "#000000"
            names = {"tx1": 0, "dk1": 0, "bg1": 1, "lt1": 1, "tx2": 2, "dk2": 2, "bg2": 3, "lt2": 3,
                     "accent1": 4, "accent2": 5, "accent3": 6, "accent4": 7, "accent5": 8, "accent6": 9}
            if "scheme" in spec:
                base = self.colors[names.get(spec["scheme"], 0)]
            elif "rgb" in spec:
                base = "#" + spec["rgb"]
            elif "srgb" in spec:
                base = "#" + spec["srgb"]
            c = QColor(base)
            h, l, s_ = colorsys.rgb_to_hls(c.redF(), c.greenF(), c.blueF())
            for mod, val in spec.get("mods", []):
                if mod == "lumMod":
                    l *= val / 100000
                elif mod == "lumOff":
                    l += val / 100000
            l = max(0.0, min(1.0, l))
            r, g, b = colorsys.hls_to_rgb(h, l, s_)
            return QColor.fromRgbF(r, g, b)
        return QColor("#000000")


def paint(p, rect, book, chart: Chart, sheet: str):
    import show_chart
    from PySide6.QtGui import QColor
    p.save()
    p.fillRect(rect, QColor("#ffffff"))
    p.setPen(QColor("#868686"))
    p.drawRect(rect.adjusted(0, 0, -1, -1))
    p.restore()
    data = render_data(book, chart, sheet)
    inner = rect.adjusted(6, 6, -6, -6)
    if not show_chart.paint(p, inner, data, PaintContext(book.theme_colors)):
        p.drawText(inner, 0x84, "(empty chart)")


# ---- making charts --------------------------------------------------------------------------------
def from_selection(book, ws, r1, c1, r2, c2, kind: str) -> Chart:
    """Like Insert > Chart in Excel: series in columns (or rows if there are more columns than rows),
    the first row/column used for names and categories when it holds text."""
    from sheet_model import sheet_ref_text

    def is_text(r, c):
        v = book.value(ws.name, r, c)
        return isinstance(v, str) or v is None

    header_row = all(is_text(r1, c) for c in range(c1, c2 + 1)) and r2 > r1
    header_col = all(is_text(r, c1) for r in range(r1 + (1 if header_row else 0), r2 + 1)) and c2 > c1
    if header_row and not header_col and is_text(r1, c1) and book.value(ws.name, r1, c1) is None:
        header_col = c2 > c1
    data_r1 = r1 + (1 if header_row else 0)
    data_c1 = c1 + (1 if header_col else 0)
    by_rows = (c2 - data_c1) > (r2 - data_r1) and kind not in ("pie", "doughnut", "scatter")
    chart = Chart(kind=kind, grouping="clustered" if kind in ("col", "bar") else "standard",
                  anchor=(r1, c2 + 2, r1 + 15, c2 + 9), legend="r" if kind not in ("pie", "doughnut") or True else "")
    if kind == "scatter":
        xs = sheet_ref_text(ws, data_r1, c1, r2, c1)
        for c in range(c1 + 1, c2 + 1):
            name = sheet_ref_text(ws, r1, c, r1, c) if header_row else ""
            chart.series.append(ChartSeries(name=("=" + name) if name else "", values=sheet_ref_text(ws, data_r1, c, r2, c),
                                            categories=xs))
        return chart
    if not by_rows:
        cats = sheet_ref_text(ws, data_r1, c1, r2, c1) if header_col else ""
        for c in range(data_c1, c2 + 1):
            name = sheet_ref_text(ws, r1, c, r1, c) if header_row else ""
            chart.series.append(ChartSeries(name=("=" + name) if name else "",
                                            values=sheet_ref_text(ws, data_r1, c, r2, c), categories=cats))
            if kind in ("pie", "doughnut"):
                break
    else:
        cats = sheet_ref_text(ws, r1, data_c1, r1, c2) if header_row else ""
        for r in range(data_r1, r2 + 1):
            name = sheet_ref_text(ws, r, c1, r, c1) if header_col else ""
            chart.series.append(ChartSeries(name=("=" + name) if name else "",
                                            values=sheet_ref_text(ws, r, data_c1, r, c2), categories=cats))
    if len(chart.series) == 1 and kind not in ("pie", "doughnut"):
        chart.legend = ""
        if chart.series[0].name.startswith("="):
            chart.title = chart.series[0].name
    return chart


def to_openpyxl(chart: Chart):
    """An openpyxl chart object for saving."""
    from openpyxl import chart as oc
    from openpyxl.chart.series import SeriesLabel, StrRef
    from openpyxl.chart.data_source import AxDataSource, NumDataSource, NumRef, StrRef as SRef

    kind = chart.kind
    if kind in ("col", "bar"):
        ch = oc.BarChart()
        ch.type = "bar" if kind == "bar" else "col"
        ch.grouping = chart.grouping if chart.grouping in ("clustered", "stacked", "percentStacked") else "clustered"
        if ch.grouping != "clustered":
            ch.overlap = 100
    elif kind == "line":
        ch = oc.LineChart()
        ch.grouping = chart.grouping if chart.grouping in ("standard", "stacked", "percentStacked") else "standard"
    elif kind == "pie":
        ch = oc.PieChart()
    elif kind == "doughnut":
        ch = oc.DoughnutChart()
    elif kind == "area":
        ch = oc.AreaChart()
        ch.grouping = chart.grouping if chart.grouping in ("standard", "stacked", "percentStacked") else "standard"
    elif kind == "scatter":
        ch = oc.ScatterChart()
        ch.style = 13
    elif kind == "radar":
        ch = oc.RadarChart()
    else:
        ch = oc.BarChart()
    for s in chart.series:
        if kind == "scatter":
            ser = oc.Series(NumDataSource(numRef=NumRef(f=s.values)),
                            xvalues=AxDataSource(numRef=NumRef(f=s.categories)) if s.categories else None)
        else:
            ser = oc.Series(NumDataSource(numRef=NumRef(f=s.values)))
            if s.categories:
                ser.cat = AxDataSource(strRef=SRef(f=s.categories))
        if s.name.startswith("="):
            ser.tx = SeriesLabel(strRef=StrRef(f=s.name[1:]))
        elif s.name:
            ser.tx = SeriesLabel(v=s.name)
        if s.color:
            ser.graphicalProperties.solidFill = s.color.lstrip("#")
            if kind in ("line", "scatter", "radar"):
                ser.graphicalProperties.line.solidFill = s.color.lstrip("#")
        if chart.smooth and kind in ("line", "scatter"):
            ser.smooth = True
        ch.series.append(ser)
    if chart.title and not chart.title.startswith("="):
        ch.title = chart.title
    if chart.legend:
        ch.legend.position = chart.legend
    else:
        ch.legend = None
    if chart.x_title and hasattr(ch, "x_axis"):
        ch.x_axis.title = chart.x_title
    if chart.y_title and hasattr(ch, "y_axis"):
        ch.y_axis.title = chart.y_title
    if hasattr(ch, "x_axis"):
        ch.x_axis.delete = False
        ch.y_axis.delete = False
    return ch


def ref_ok(text: str) -> bool:
    return bool(re.match(r"^(?:'[^']+'|[A-Za-z0-9_.]+)!\$?[A-Z]{1,3}\$?\d+(:\$?[A-Z]{1,3}\$?\d+)?$", text or ""))
