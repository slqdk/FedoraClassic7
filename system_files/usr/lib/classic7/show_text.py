"""Show: slide text <-> QTextDocument (for drawing and editing), bullets and autofit.

The document is laid out in points (a 72 dpi paint device), the unit of the slide scene.
Every block keeps the paragraph's own (explicit) settings as JSON in P_EXPL and every character
format the run's own settings in C_EXPL, so that a document converts back to the model without
turning inherited values (theme fonts, placeholder sizes) into fixed ones.
"""
from __future__ import annotations

import copy
import json
from datetime import date

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QPainter, QTextBlockFormat, QTextCharFormat,
                           QTextCursor, QTextDocument, QTextFormat, QTextOption)

import show_model as sm

P_EXPL = QTextFormat.UserProperty + 101
P_LEVEL = QTextFormat.UserProperty + 102
C_EXPL = QTextFormat.UserProperty + 103

PARA_KEYS = ("align", "marL", "indent", "bullet", "space_before", "space_after", "line_spacing")
RUN_KEYS = ("font", "size", "bold", "italic", "underline", "strike", "color", "baseline", "caps", "link", "field")

_DEVICE: QImage | None = None


def device() -> QImage:
    """A 72 dpi paint device: one point of text = one unit of the slide scene."""
    global _DEVICE
    if _DEVICE is None:
        _DEVICE = QImage(1, 1, QImage.Format_ARGB32)
        dpm = round(72 / 0.0254)
        _DEVICE.setDotsPerMeterX(dpm)
        _DEVICE.setDotsPerMeterY(dpm)
    return _DEVICE


WINGDINGS = {"§": "▪", "Ø": "➢", "ü": "✓", "n": "■", "q": "❑", "v": "❖", "Ÿ": "•", "l": "●", "o": "□",
             "p": "◆", "u": "◆", "w": "⬥", "è": "➔", "Þ": "➢", "ð": "⇨", "à": "→", "ª": "✦", "¨": "◻",
             "®": "◉", "²": "◇", "Ö": "➔"}


def bullet_glyph(ch: str, font: str | None) -> str:
    if not ch:
        return "•"
    c = ch[0]
    if 0xF000 <= ord(c) <= 0xF0FF:
        c = chr(ord(c) - 0xF000)
        font = font or "Wingdings"
    if font and font.lower().startswith(("wingdings", "symbol", "webdings")):
        if font.lower().startswith("symbol"):
            return {"·": "•", "\xb7": "•", "§": "♣", "¨": "♦", "©": "♥", "ª": "♠"}.get(c, "•")
        return WINGDINGS.get(c, "•")
    return c


class TextCtx:
    """What text resolution needs: the theme, the colour map and the inherited level styles."""

    def __init__(self, master: sm.Master, layout: sm.Layout | None, shape: sm.Shape | None,
                 slide_number: int = 0, editing: bool = False, table_cell: bool = False):
        self.master = master
        self.theme = master.theme
        self.layout = layout
        self.shape = shape
        self.slide_number = slide_number
        self.editing = editing
        self.table_cell = table_cell
        self.scale = 1.0
        self.line_reduction = 0.0
        self.text_color: dict | None = None   # a shape style's text colour (fontRef)
        self._cache: dict[int, dict] = {}

    def defaults(self, level: int) -> dict:
        if level not in self._cache:
            if self.table_cell:
                d = {"size": 18, "font": "+mn-lt", "color": sm.scheme("tx1"), "align": "l", "marL": 0, "indent": 0,
                     "bullet": None, "space_before": 0.0, "line_spacing": 100.0}
            else:
                d = sm.level_defaults(self.master, self.layout, self.shape or sm.Shape(), level)
            if self.text_color is not None and not (self.shape and self.shape.ph):
                d = dict(d, color=self.text_color)
            self._cache[level] = d
        return self._cache[level]

    def color(self, c: dict | None, default: str = "000000") -> QColor:
        if not c:
            return QColor("#" + default)
        if "rgb" in c:
            hexv = c["rgb"]
        elif "scheme" in c:
            hexv = self.theme.scheme_rgb(c["scheme"], self.master.color_map)
        elif "sys" in c:
            hexv = c.get("last", "000000")
        else:
            hexv = default
        try:
            r, g, b = int(hexv[0:2], 16), int(hexv[2:4], 16), int(hexv[4:6], 16)
        except (ValueError, IndexError):
            r, g, b = 0, 0, 0
        r, g, b, a = sm.apply_mods(r, g, b, c.get("mods"))
        return QColor(r, g, b, a)

    def font_name(self, token: str | None) -> str:
        if not token or token in ("+mn-lt", "+mn-ea", "+mn-cs"):
            return self.theme.minor_font
        if token in ("+mj-lt", "+mj-ea", "+mj-cs"):
            return self.theme.major_font
        return token


def _effective(par: sm.Paragraph, ctx: TextCtx) -> dict:
    d = dict(ctx.defaults(par.level))
    for k in PARA_KEYS:
        v = getattr(par, k)
        if v is not None:
            d[k] = v
    return d


def _para_expl(par: sm.Paragraph) -> dict:
    return {k: getattr(par, k) for k in PARA_KEYS if getattr(par, k) is not None}


def _run_expl(run: sm.Run) -> dict:
    return {k: getattr(run, k) for k in RUN_KEYS if getattr(run, k) not in (None, 0) or
            (k in ("bold", "italic", "underline", "strike") and getattr(run, k) is False)}


def run_props(expl: dict, eff_para: dict) -> dict:
    d = {k: eff_para.get(k) for k in ("font", "size", "bold", "italic", "underline", "strike", "color", "caps")}
    d.update({k: v for k, v in expl.items()})
    return d


def char_format(props: dict, ctx: TextCtx, expl: dict) -> QTextCharFormat:
    cf = QTextCharFormat()
    size = float(props.get("size") or 18) * ctx.scale
    cf.setFontFamilies([ctx.font_name(props.get("font"))])
    cf.setFontPointSize(max(1.0, size))
    cf.setFontWeight(QFont.Bold if props.get("bold") else QFont.Normal)
    cf.setFontItalic(bool(props.get("italic")))
    cf.setFontUnderline(bool(props.get("underline")))
    cf.setFontStrikeOut(bool(props.get("strike")))
    cf.setFontHintingPreference(QFont.PreferNoHinting)
    caps = props.get("caps")
    if caps == "all":
        cf.setFontCapitalization(QFont.AllUppercase)
    elif caps == "small":
        cf.setFontCapitalization(QFont.SmallCaps)
    col = ctx.color(props.get("color"))
    if props.get("link"):
        col = ctx.color(sm.scheme("hlink"))
        cf.setFontUnderline(True)
        cf.setAnchor(True)
        cf.setAnchorHref(props["link"])
    cf.setForeground(col)
    bl = props.get("baseline") or 0
    if bl > 0:
        cf.setVerticalAlignment(QTextCharFormat.AlignSuperScript)
    elif bl < 0:
        cf.setVerticalAlignment(QTextCharFormat.AlignSubScript)
    cf.setProperty(C_EXPL, json.dumps(expl))
    return cf


def block_format(eff: dict, expl: dict, level: int, ctx: TextCtx, first_size: float) -> QTextBlockFormat:
    bf = QTextBlockFormat()
    bf.setAlignment({"ctr": Qt.AlignHCenter, "r": Qt.AlignRight, "just": Qt.AlignJustify,
                     "dist": Qt.AlignJustify}.get(eff.get("align") or "l", Qt.AlignLeft))
    marl = sm.pt(eff.get("marL") or 0)
    indent = sm.pt(eff.get("indent") or 0)
    has_bullet = _has_bullet(eff)
    bf.setLeftMargin(max(0.0, marl))
    if has_bullet:
        if indent >= 0:
            bf.setTextIndent(indent + first_size * ctx.scale * 0.9)
        else:
            bf.setTextIndent(0)
    else:
        bf.setTextIndent(indent if marl + indent >= 0 else -marl)
    size = first_size * ctx.scale

    def spacing(v):
        if v is None:
            return 0.0
        v = float(v)
        return (-v / 100.0) * size * 1.2 if v < 0 else v * ctx.scale
    bf.setTopMargin(spacing(eff.get("space_before")))
    bf.setBottomMargin(spacing(eff.get("space_after")))
    ls = eff.get("line_spacing") or 100.0
    if ls > 0:
        bf.setLineHeight(max(10.0, ls * (1.0 - ctx.line_reduction)), QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
    else:                      # negative: exact points
        bf.setLineHeight(-ls * ctx.scale, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
    bf.setProperty(P_EXPL, json.dumps(expl))
    bf.setProperty(P_LEVEL, level)
    return bf


def _has_bullet(eff: dict) -> bool:
    b = eff.get("bullet")
    return bool(b) and not b.get("none") and ("char" in b or "auto" in b)


def field_text(run: sm.Run, ctx: TextCtx) -> str:
    if run.field == "slidenum":
        return str(ctx.slide_number) if ctx.slide_number else (run.text or "‹#›")
    if run.field == "datetime":
        return run.text or date.today().strftime("%d-%m-%Y")
    return run.text


def to_document(body: sm.TextBody, ctx: TextCtx, width: float | None = None) -> QTextDocument:
    doc = QTextDocument()
    doc.documentLayout().setPaintDevice(device())
    doc.setDocumentMargin(0)
    doc.setUseDesignMetrics(True)
    opt = QTextOption()
    opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere if body.wrap else QTextOption.NoWrap)
    doc.setDefaultTextOption(opt)
    ctx.scale = body.font_scale or 1.0
    ctx.line_reduction = body.line_reduction or 0.0
    cur = QTextCursor(doc)
    first = True
    for par in body.paragraphs or [sm.Paragraph()]:
        eff = _effective(par, ctx)
        runs = par.runs
        first_size = float((runs[0].size if runs and runs[0].size else None) or par.end_size or eff.get("size") or 18)
        bf = block_format(eff, _para_expl(par), par.level, ctx, first_size)
        end_expl = {"size": par.end_size} if par.end_size else {}
        end_cf = char_format(run_props(end_expl, eff), ctx, end_expl)
        if first:
            cur.setBlockFormat(bf)
            cur.setBlockCharFormat(end_cf)
            first = False
        else:
            cur.insertBlock(bf, end_cf)
        for run in runs:
            expl = _run_expl(run)
            text = field_text(run, ctx).replace("\n", " ").replace("\v", " ")
            if text:
                cur.insertText(text, char_format(run_props(expl, eff), ctx, expl))
        cur.setCharFormat(end_cf)
    if width is not None:
        doc.setTextWidth(max(1.0, width))
    doc.setModified(False)
    return doc


def from_document(doc: QTextDocument, old: sm.TextBody | None = None) -> sm.TextBody:
    body = copy.copy(old) if old is not None else sm.TextBody()
    body.paragraphs = []
    block = doc.begin()
    while block.isValid():
        bf = block.blockFormat()
        try:
            pexpl = json.loads(bf.property(P_EXPL) or "{}")
        except (TypeError, ValueError):
            pexpl = {}
        level = bf.property(P_LEVEL)
        par = sm.Paragraph(level=int(level) if level is not None else 0)
        for k, v in pexpl.items():
            if k in PARA_KEYS:
                setattr(par, k, v)
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                cf = frag.charFormat()
                try:
                    rexpl = json.loads(cf.property(C_EXPL) or "{}")
                except (TypeError, ValueError):
                    rexpl = {}
                run = sm.Run(text=frag.text().replace(" ", "\v"))
                for k, v in rexpl.items():
                    if k in RUN_KEYS:
                        setattr(run, k, v)
                if run.field:
                    # a field keeps its kind; the text is what was shown
                    pass
                if par.runs and _run_expl(par.runs[-1]) == _run_expl(run) and not run.field:
                    par.runs[-1].text += run.text
                else:
                    par.runs.append(run)
            it += 1
        try:
            end = json.loads(block.charFormat().property(C_EXPL) or "{}")
            par.end_size = end.get("size")
        except (TypeError, ValueError):
            pass
        body.paragraphs.append(par)
        block = block.next()
    if not body.paragraphs:
        body.paragraphs = [sm.Paragraph()]
    return body


# ---- changing the explicit settings of the text being edited ------------------------------------
def set_run_prop(cursor: QTextCursor, ctx: TextCtx, key: str, value):
    """Set (or with value None remove) a run setting on the selection, keeping C_EXPL in step."""
    doc = cursor.document()
    start, end = cursor.selectionStart(), cursor.selectionEnd()
    cursor.beginEditBlock()
    if start == end:
        cf = cursor.charFormat()
        expl = _load(cf.property(C_EXPL))
        _set(expl, key, value)
        level = cursor.block().blockFormat().property(P_LEVEL) or 0
        eff = _block_eff(cursor.block(), ctx, int(level))
        cursor.setCharFormat(char_format(run_props(expl, eff), ctx, expl))
        if not cursor.block().text():
            QTextCursor(cursor.block()).setBlockCharFormat(char_format(run_props(expl, eff), ctx, expl))
    else:
        pos = start
        while pos < end:
            c = QTextCursor(doc)
            c.setPosition(pos)
            c.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
            block = c.block()
            it = block.begin()
            frag_end = pos + 1
            while not it.atEnd():
                f = it.fragment()
                if f.position() <= pos < f.position() + f.length():
                    frag_end = min(end, f.position() + f.length())
                    cf = f.charFormat()
                    break
                it += 1
            else:
                cf = c.charFormat()
                frag_end = min(end, block.position() + block.length())
            if frag_end <= pos:
                frag_end = pos + 1
            expl = _load(cf.property(C_EXPL))
            _set(expl, key, value)
            level = block.blockFormat().property(P_LEVEL) or 0
            eff = _block_eff(block, ctx, int(level))
            c.setPosition(pos)
            c.setPosition(frag_end, QTextCursor.KeepAnchor)
            c.setCharFormat(char_format(run_props(expl, eff), ctx, expl))
            pos = frag_end
    cursor.endEditBlock()


def set_para_prop(cursor: QTextCursor, ctx: TextCtx, key: str, value, blocks=None):
    cursor.beginEditBlock()
    for block in blocks or selected_blocks(cursor):
        bf = block.blockFormat()
        expl = _load(bf.property(P_EXPL))
        level = int(bf.property(P_LEVEL) or 0)
        if key == "level":
            level = max(0, min(8, int(value)))
        else:
            _set(expl, key, value)
        restyle_block(block, ctx, expl, level)
    cursor.endEditBlock()


def restyle_block(block, ctx: TextCtx, expl: dict | None = None, level: int | None = None):
    """Recompute a paragraph's shown formats from its explicit settings (after a level change)."""
    bf = block.blockFormat()
    expl = _load(bf.property(P_EXPL)) if expl is None else expl
    level = int(bf.property(P_LEVEL) or 0) if level is None else level
    par = sm.Paragraph(level=level)
    for k, v in expl.items():
        if k in PARA_KEYS:
            setattr(par, k, v)
    eff = _effective(par, ctx)
    first_size = None
    it = block.begin()
    frags = []
    while not it.atEnd():
        f = it.fragment()
        if f.isValid():
            frags.append((f.position(), f.length(), _load(f.charFormat().property(C_EXPL))))
        it += 1
    if frags:
        first_size = frags[0][2].get("size")
    end_expl = _load(block.charFormat().property(C_EXPL))
    first_size = float(first_size or end_expl.get("size") or eff.get("size") or 18)
    c = QTextCursor(block)
    c.setBlockFormat(block_format(eff, expl, level, ctx, first_size))
    c.setBlockCharFormat(char_format(run_props(end_expl, eff), ctx, end_expl))
    for pos, length, rexpl in frags:
        cc = QTextCursor(block.document())
        cc.setPosition(pos)
        cc.setPosition(pos + length, QTextCursor.KeepAnchor)
        cc.setCharFormat(char_format(run_props(rexpl, eff), ctx, rexpl))


def _block_eff(block, ctx: TextCtx, level: int) -> dict:
    expl = _load(block.blockFormat().property(P_EXPL))
    par = sm.Paragraph(level=level)
    for k, v in expl.items():
        if k in PARA_KEYS:
            setattr(par, k, v)
    return _effective(par, ctx)


def block_effective(block, ctx: TextCtx) -> dict:
    return _block_eff(block, ctx, int(block.blockFormat().property(P_LEVEL) or 0))


def selected_blocks(cursor: QTextCursor) -> list:
    doc = cursor.document()
    b = doc.findBlock(cursor.selectionStart())
    last = doc.findBlock(cursor.selectionEnd())
    out = []
    while b.isValid():
        out.append(b)
        if b == last:
            break
        b = b.next()
    return out


def char_expl(cf: QTextCharFormat) -> dict:
    return _load(cf.property(C_EXPL))


def _load(v) -> dict:
    try:
        return json.loads(v) if v else {}
    except (TypeError, ValueError):
        return {}


def _set(d: dict, key, value):
    if value is None:
        d.pop(key, None)
    else:
        d[key] = value


# ---- bullets -----------------------------------------------------------------------------------
def _roman(n: int) -> str:
    vals = [(1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
            (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")]
    out = ""
    for v, s in vals:
        while n >= v:
            out += s
            n -= v
    return out


def _alpha(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(97 + r) + s
    return s


def auto_number(scheme_: str, n: int) -> str:
    sch = scheme_ or "arabicPeriod"
    if sch.startswith("arabic"):
        core = str(n)
    elif sch.startswith("alphaLc"):
        core = _alpha(n)
    elif sch.startswith("alphaUc"):
        core = _alpha(n).upper()
    elif sch.startswith("romanLc"):
        core = _roman(n)
    elif sch.startswith("romanUc"):
        core = _roman(n).upper()
    else:
        core = str(n)
    if sch.endswith("ParenBoth"):
        return f"({core})"
    if sch.endswith("ParenR"):
        return f"{core})"
    if sch.endswith("Period"):
        return f"{core}."
    if sch.endswith("Minus"):
        return f"{core} -"
    return core


def paint_bullets(p: QPainter, doc: QTextDocument, ctx: TextCtx, show_empty: bool = False):
    counters: dict[int, int] = {}
    last_scheme: dict[int, str] = {}
    block = doc.begin()
    while block.isValid():
        level = int(block.blockFormat().property(P_LEVEL) or 0)
        eff = _block_eff(block, ctx, level)
        b = eff.get("bullet")
        for lv in list(counters):
            if lv > level:
                counters.pop(lv)
                last_scheme.pop(lv, None)
        if not _has_bullet(eff):
            counters.pop(level, None)
            block = block.next()
            continue
        if "auto" in b:
            sch = b.get("auto")
            if last_scheme.get(level) != sch:
                counters[level] = int(b.get("start", 1)) - 1
                last_scheme[level] = sch
            counters[level] = counters.get(level, int(b.get("start", 1)) - 1) + 1
        else:
            counters.pop(level, None)
            last_scheme.pop(level, None)
        if not block.text() and not show_empty:
            block = block.next()
            continue
        layout = block.layout()
        if layout.lineCount() == 0:
            block = block.next()
            continue
        line = layout.lineAt(0)
        it = block.begin()
        first_cf = it.fragment().charFormat() if not it.atEnd() else block.charFormat()
        size = first_cf.fontPointSize() or 18
        pct = float(b.get("size", 100)) / 100.0 if isinstance(b.get("size"), (int, float)) else 1.0
        if "auto" in b:
            text = auto_number(b.get("auto"), counters[level])
            fam = first_cf.fontFamilies() or [ctx.theme.minor_font]
            f = QFont(fam[0] if isinstance(fam, list) else str(fam))
        else:
            fam = b.get("font")
            text = bullet_glyph(b.get("char", "•"), fam)
            f = QFont("DejaVu Sans" if fam and fam.lower().startswith(("wingdings", "symbol", "webdings"))
                      else (ctx.font_name(fam) if fam else "Arial"))
        f.setPointSizeF(max(1.0, size * pct))
        f.setHintingPreference(QFont.PreferNoHinting)
        fm = QFontMetricsF(f, device())
        color = ctx.color(b["color"]) if b.get("color") else first_cf.foreground().color()
        pos = layout.position()
        bf = block.blockFormat()
        x = bf.leftMargin() + sm.pt(eff.get("indent") or 0)
        if (eff.get("indent") or 0) >= 0:
            x = bf.leftMargin() + sm.pt(eff.get("indent") or 0)
        # alignment of the first line moves the bullet with it
        if bf.alignment() & (Qt.AlignHCenter | Qt.AlignRight):
            x = line.x() + line.naturalTextRect().left() - (bf.textIndent() or fm.horizontalAdvance(text) * 1.3)
            x = max(0.0, x)
        y = pos.y() + line.y() + line.ascent()
        p.save()
        p.setFont(f)
        p.setPen(color)
        p.drawText(QPointF(pos.x() + x, y), text)
        p.restore()
        block = block.next()


# ---- laying out and drawing a text body --------------------------------------------------------
def text_area(shape_w: float, shape_h: float, body: sm.TextBody, geom_rect: QRectF | None = None) -> QRectF:
    r = geom_rect or QRectF(0, 0, shape_w, shape_h)
    l, t, rr, b = (sm.pt(v) for v in body.insets)
    return QRectF(r.left() + l, r.top() + t, max(1.0, r.width() - l - rr), max(1.0, r.height() - t - b))


def layout_doc(body: sm.TextBody, ctx: TextCtx, area: QRectF) -> QTextDocument:
    vertical = body.vert in ("vert", "vert270", "eaVert", "wordArtVert")
    width = area.height() if vertical else area.width()
    doc = to_document(body, ctx, width if body.wrap else None)
    if not body.wrap:
        doc.setTextWidth(-1)
    return doc


def doc_offset(doc: QTextDocument, body: sm.TextBody, area: QRectF) -> QPointF:
    h = doc.size().height()
    vertical = body.vert in ("vert", "vert270", "eaVert", "wordArtVert")
    avail = area.width() if vertical else area.height()
    if body.anchor == "ctr":
        dy = (avail - h) / 2
    elif body.anchor == "b":
        dy = avail - h
    else:
        dy = 0.0
    dx = 0.0
    if not body.wrap:
        w = doc.idealWidth()
        aw = area.height() if vertical else area.width()
        # unwrapped text keeps the alignment of its first paragraph inside the box
        al = doc.begin().blockFormat().alignment()
        if al & Qt.AlignHCenter:
            dx = (aw - w) / 2
        elif al & Qt.AlignRight:
            dx = aw - w
    return QPointF(dx, dy)


def paint_text(p: QPainter, body: sm.TextBody, ctx: TextCtx, area: QRectF, doc: QTextDocument | None = None):
    if body is None:
        return
    doc = doc or layout_doc(body, ctx, area)
    off = doc_offset(doc, body, area)
    p.save()
    if body.vert in ("vert", "eaVert"):
        p.translate(area.right(), area.top())
        p.rotate(90)
    elif body.vert == "vert270":
        p.translate(area.left(), area.bottom())
        p.rotate(-90)
    else:
        p.translate(area.topLeft())
    p.translate(off)
    if not body.wrap and doc.textWidth() < 0:
        doc.setTextWidth(doc.idealWidth() + 1)
    doc.drawContents(p)
    paint_bullets(p, doc, ctx)
    p.restore()


def text_height(body: sm.TextBody, ctx: TextCtx, width: float) -> float:
    doc = to_document(body, ctx, width if body.wrap else None)
    return doc.size().height()


def fit_scale(body: sm.TextBody, ctx: TextCtx, area: QRectF) -> tuple[float, float]:
    """normAutofit: the font scale and line reduction that make the text fit the box."""
    trial = copy.copy(body)
    for reduction, scales in ((0.0, [1.0]), (0.1, [0.9, 0.85, 0.8]), (0.2, [x / 1000 for x in range(775, 249, -25)])):
        for s in scales:
            trial.font_scale, trial.line_reduction = s, reduction
            if text_height(trial, ctx, area.width()) <= area.height() + 0.5:
                return s, reduction
    return 0.25, 0.2
