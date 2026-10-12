"""Write: open a PDF as an editable document ("PDF Reflow", like Word 2013 and later).

The text of each page is read with PyMuPDF and rebuilt as paragraphs: fonts, sizes, bold,
italic, colours, links, alignment, indents, bullet lists, tables, pictures and page breaks.
Repeated page headers/footers become Write's header/footer ("Page {page} of {pages}").
Scanned pages (pictures only) come in as pictures. Saving as PDF is Write's normal export.
"""
from __future__ import annotations

import re
from collections import Counter

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import (QColor, QFont, QImage, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QTextFormat, QTextImageFormat, QTextLength, QTextTableFormat)

import write_model as m
from write_page import PageSetup

try:
    import pymupdf
except ImportError:            # older PyMuPDF
    import fitz as pymupdf

PT = 96 / 72                   # document pixels per PDF point
MM = 25.4 / 72                 # millimetres per PDF point
BULLETS = "•●▪■◦○◆◇►▶➢✓✔-–—*·"
FONT_NAMES = {
    "helvetica": "Arial", "arialmt": "Arial", "arial": "Arial", "times": "Times New Roman",
    "timesroman": "Times New Roman", "timesnewromanpsmt": "Times New Roman", "timesnewroman": "Times New Roman",
    "courier": "Courier New", "couriernewpsmt": "Courier New", "couriernew": "Courier New",
    "symbol": "Symbol", "zapfdingbats": "DejaVu Sans", "calibri": "Calibri", "cambria": "Cambria",
    "segoeui": "Segoe UI", "verdana": "Verdana", "tahoma": "Tahoma", "georgia": "Georgia",
    "liberationsans": "Liberation Sans", "liberationserif": "Liberation Serif", "dejavusans": "DejaVu Sans",
    "carlito": "Calibri", "caladea": "Cambria", "notosans": "Noto Sans", "opensans": "Open Sans",
    "roboto": "Roboto", "garamond": "Garamond", "bookantiqua": "Book Antiqua", "centurygothic": "Century Gothic",
    "consolas": "Consolas", "trebuchetms": "Trebuchet MS", "palatinolinotype": "Palatino Linotype",
}


class PdfError(Exception):
    pass


# ---- fonts -------------------------------------------------------------------------------------
def font_family(name: str) -> str:
    n = re.sub(r"^[A-Z]{6}\+", "", name or "")
    base = re.split(r"[-,]", n)[0]
    key = re.sub(r"(PS)?MT$", "", base).lower()
    key = re.sub(r"(bold|italic|oblique|regular|light|medium|semibold|black|heavy|condensed)+$", "", key)
    if key in FONT_NAMES:
        return FONT_NAMES[key]
    if base.lower() in FONT_NAMES:
        return FONT_NAMES[base.lower()]
    # "SegoeUI" -> "Segoe UI", "DejaVuSans" -> "DejaVu Sans"
    nice = re.sub(r"(PS)?MT$", "", base)
    nice = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", nice).strip()
    return nice or "Calibri"


def is_bold(span) -> bool:
    n = (span.get("font") or "").lower()
    return bool(span.get("flags", 0) & 16) or any(w in n for w in ("bold", "black", "heavy", "semibold", "demi"))


def is_italic(span) -> bool:
    n = (span.get("font") or "").lower()
    return bool(span.get("flags", 0) & 2) or "italic" in n or "oblique" in n


def char_format(span, link: str = "") -> QTextCharFormat:
    cf = QTextCharFormat()
    cf.setFontFamilies([font_family(span.get("font", ""))])
    size = round(float(span.get("size", 11)) * 2) / 2
    cf.setFontPointSize(max(4.0, size))
    cf.setFontWeight(QFont.Bold if is_bold(span) else QFont.Normal)
    cf.setFontItalic(is_italic(span))
    col = int(span.get("color", 0) or 0)
    if col:
        cf.setForeground(QColor(f"#{col:06X}"))
    else:
        cf.setForeground(QColor("#000000"))
    if span.get("flags", 0) & 1:
        cf.setVerticalAlignment(QTextCharFormat.AlignSuperScript)
    if link:
        cf.setAnchor(True)
        cf.setAnchorHref(link)
        cf.setFontUnderline(True)
        if not col:
            cf.setForeground(QColor("#0000FF"))
    return cf


# ---- page analysis -------------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


def _inside(bbox, rects, pad=1.0) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return any(r[0] - pad <= cx <= r[2] + pad and r[1] - pad <= cy <= r[3] + pad for r in rects)


def _page_number_text(text: str) -> str | None:
    """'3', 'Page 3', 'Side 3 af 10', '3 / 10' -> the same with {page}/{pages}, else None."""
    t = text.strip()
    m2 = re.fullmatch(r"(?i)(\D*?)(\d+)(\s*(?:/|of|af|von|de)\s*)(\d+)(\D*)", t)
    if m2:
        return f"{m2.group(1)}{{page}}{m2.group(3)}{{pages}}{m2.group(5)}"
    m1 = re.fullmatch(r"(?i)(\D{0,12}?)(\d+)(\D{0,4})", t)
    if m1:
        return f"{m1.group(1)}{{page}}{m1.group(3)}"
    return None


class Converter:
    def __init__(self, path: str, progress=None):
        self.progress = progress          # progress(done, total) -> False to cancel
        try:
            self.pdf = pymupdf.open(path)
        except Exception as e:   # noqa: BLE001
            raise PdfError(f"The PDF can't be read ({e}).") from e
        if self.pdf.needs_pass:
            raise PdfError("The PDF is protected with a password.")
        self.doc = m.new_document()
        self.cur = QTextCursor(self.doc)
        self.first_block = True
        self.page_break_pending = False
        self.image_n = 0
        self.scanned_pages = 0
        self.notes: list[str] = []

    # -- whole-document facts --
    def _pages_data(self):
        self.pages = []
        total = self.pdf.page_count
        for page in self.pdf:
            if self.progress and self.progress(page.number, total * 2) is False:
                raise PdfError("cancelled")
            flags = None
            if hasattr(pymupdf, "TEXTFLAGS_DICT"):    # split ligatures ("fi") into letters, keep images
                flags = (pymupdf.TEXTFLAGS_DICT | pymupdf.TEXT_PRESERVE_IMAGES) & ~pymupdf.TEXT_PRESERVE_LIGATURES
            d = page.get_text("dict", flags=flags, sort=True)
            try:
                tables = [t for t in page.find_tables().tables if t.row_count >= 2 and t.col_count >= 2]
            except Exception:   # noqa: BLE001  (old PyMuPDF without table finder)
                tables = []
            links = [(lk["from"], lk.get("uri", "")) for lk in page.get_links() if lk.get("uri")]
            markers, fills = [], []
            try:
                for dr in page.get_drawings():
                    r, fill = dr.get("rect"), dr.get("fill")
                    if r is None or fill is None:
                        continue
                    if r.width <= 7 and r.height <= 7 and abs(r.width - r.height) < 2:
                        markers.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))     # drawn bullet
                    elif 4 < r.height < 30 and r.width > 4 and tuple(fill[:3]) != (1.0, 1.0, 1.0):
                        fills.append((r, fill))                                   # highlight behind text
            except Exception:   # noqa: BLE001
                pass
            self.pages.append({"page": page, "dict": d, "tables": tables, "links": links, "markers": markers,
                               "fills": fills, "w": page.rect.width, "h": page.rect.height})

    def _headers_footers(self):
        """Lines repeated at the top/bottom of most pages: header/footer, not body text."""
        self.skip: set[tuple[int, int, int]] = set()     # (page, block, line)
        self.header_text = self.footer_text = ""
        n = len(self.pages)
        if n < 2:
            return
        seen: Counter = Counter()
        where = []
        for pi, pd in enumerate(self.pages):
            h = pd["h"]
            for bi, b in enumerate(pd["dict"]["blocks"]):
                if b.get("type") != 0:
                    continue
                for li, ln in enumerate(b["lines"]):
                    text = "".join(s["text"] for s in ln["spans"]).strip()
                    if not text:
                        continue
                    y0, y1 = ln["bbox"][1], ln["bbox"][3]
                    band = "top" if y1 < h * 0.08 else "bottom" if y0 > h * 0.92 else None
                    if band:
                        key = (band, _norm(text))
                        seen[key] += 1
                        where.append((key, pi, bi, li, text))
        for key, pi, bi, li, text in where:
            if seen[key] >= max(2, int(n * 0.5)):
                self.skip.add((pi, bi, li))
                band = key[0]
                pn = _page_number_text(text)
                value = pn if pn is not None else text
                if band == "top" and not self.header_text:
                    self.header_text = value
                elif band == "bottom" and not self.footer_text:
                    self.footer_text = value

    def _metrics(self):
        sizes: Counter = Counter()
        lefts, rights, tops, bottoms = [], [], [], []
        for pi, pd in enumerate(self.pages[:8]):
            for bi, b in enumerate(pd["dict"]["blocks"]):
                if b.get("type") != 0:
                    continue
                for li, ln in enumerate(b["lines"]):
                    if (pi, bi, li) in self.skip:
                        continue
                    for s in ln["spans"]:
                        t = s["text"].strip()
                        if t:
                            sizes[round(s["size"] * 2) / 2] += len(t)
                    x0, y0, x1, y1 = ln["bbox"]
                    lefts.append(x0)
                    rights.append(x1)
                    tops.append(y0)
                    bottoms.append(y1)
        self.body_size = sizes.most_common(1)[0][0] if sizes else 11.0
        pw = self.pages[0]["w"] if self.pages else 595
        ph = self.pages[0]["h"] if self.pages else 842

        def pct(vals, q, default):
            if not vals:
                return default
            v = sorted(vals)
            return v[min(len(v) - 1, max(0, int(len(v) * q)))]

        self.left = pct(lefts, 0.05, 72)
        self.right = pct(rights, 0.97, pw - 72)
        self.top = min(tops) if tops else 72
        self.bottom = max(bottoms) if bottoms else ph - 72
        if self.right - self.left < pw * 0.3:      # mostly-empty pages: use normal margins
            self.left, self.right = 72, pw - 72
        # short lines end well before the right margin, and pages aren't always full: most
        # documents have equal left/right margins, so don't make the right one bigger
        if (pw - self.right) > self.left + 20:
            self.right = pw - self.left
        if (ph - self.bottom) > self.top + 20:
            self.bottom = ph - self.top
        self.text_w = self.right - self.left

    def setup(self) -> PageSetup:
        pw = self.pages[0]["w"] if self.pages else 595
        ph = self.pages[0]["h"] if self.pages else 842
        s = PageSetup()
        w_mm, h_mm = pw * MM, ph * MM
        landscape = w_mm > h_mm
        s.landscape = landscape
        s.custom_size = (min(w_mm, h_mm), max(w_mm, h_mm)) if landscape else (w_mm, h_mm)
        for name, (pw_mm, ph_mm) in (("A4", (210, 297)), ("Letter", (215.9, 279.4)), ("A5", (148, 210)),
                                     ("A3", (297, 420)), ("Legal", (215.9, 355.6))):
            short, long_ = sorted((w_mm, h_mm))
            if abs(short - pw_mm) < 2 and abs(long_ - ph_mm) < 2:
                s.paper, s.custom_size = name, None
        clamp = lambda v: max(6.0, min(60.0, v))   # noqa: E731
        s.left = clamp(self.left * MM - 1)
        s.right = clamp((pw - self.right) * MM - 1)
        s.top = clamp(self.top * MM - 1)
        s.bottom = clamp((ph - self.bottom) * MM - 1)
        s.header = self.header_text
        s.footer = self.footer_text
        return s

    # -- writing --
    def _new_block(self, bf: QTextBlockFormat, cf: QTextCharFormat | None = None):
        if self.page_break_pending and not self.first_block:
            bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
        self.page_break_pending = False
        if self.first_block:
            self.cur.setBlockFormat(bf)
            if cf is not None:
                self.cur.setBlockCharFormat(cf)
            self.first_block = False
        else:
            self.cur.insertBlock(bf, cf or QTextCharFormat())

    def _drawn_bullet(self, pi: int, ln) -> bool:
        x0, y0, _x1, y1 = ln["bbox"]
        return any(x0 - 25 <= mx <= x0 - 1 and y0 <= my <= y1 for mx, my in self.pages[pi]["markers"])

    def _paragraphs(self, pi: int, bi: int, block) -> list[dict]:
        """Split a text block into paragraphs: [{lines: [line], bullet: bool}]."""
        lines = [ln for li, ln in enumerate(block["lines"])
                 if (pi, bi, li) not in self.skip and "".join(s["text"] for s in ln["spans"]).strip()]
        if not lines:
            return []
        bx1 = max(ln["bbox"][2] for ln in lines)
        bw = bx1 - min(ln["bbox"][0] for ln in lines)
        paras: list[dict] = []
        prev = None
        for ln in lines:
            text = "".join(s["text"] for s in ln["spans"]).lstrip()
            bullet = (bool(text) and text[0] in BULLETS and (len(text) == 1 or text[1] in " \t\u00a0")) \
                or self._drawn_bullet(pi, ln)
            new = prev is None or bullet
            if prev is not None and not new:
                gap = ln["bbox"][1] - prev["bbox"][3]
                lh = prev["bbox"][3] - prev["bbox"][1]
                short = prev["bbox"][2] < bx1 - max(bw * 0.18, 20) or \
                    prev["bbox"][2] < self.left + self.text_w * 0.6
                if gap > lh * 0.6 or short:
                    new = True
                # a line that sits on the same baseline continues the previous one (columns of spans)
                if abs(ln["bbox"][1] - prev["bbox"][1]) < 2:
                    new = False
            if new:
                paras.append({"lines": [ln], "bullet": bullet})
            else:
                paras[-1]["lines"].append(ln)
            prev = ln
        return paras

    def _write_paragraph(self, para: dict, links, prev_bottom: float | None, fills=()):
        lines = para["lines"]
        x0s = [ln["bbox"][0] for ln in lines]
        x1s = [ln["bbox"][2] for ln in lines]
        top = min(ln["bbox"][1] for ln in lines)
        bottom = max(ln["bbox"][3] for ln in lines)
        bf = QTextBlockFormat()
        bf.setBottomMargin(0)
        lh = (bottom - top) / max(1, len(lines))
        if prev_bottom is not None:
            gap = top - prev_bottom - lh * 0.25
            bf.setTopMargin(max(0.0, min(gap, 48)) * PT)
        # alignment and indents
        left_pt = min(x0s) - self.left
        mid = (min(x0s) + max(x1s)) / 2
        centre = self.left + self.text_w / 2
        full = [x1 > self.right - 4 for x1 in x1s[:-1]]
        if len(lines) > 1 and full and sum(full) >= len(full) * 0.7 and \
                all(abs(x - min(x0s)) < 3 for x in x0s[1:]):
            bf.setAlignment(Qt.AlignJustify)
        elif abs(mid - centre) < self.text_w * 0.04 and left_pt > self.text_w * 0.08:
            bf.setAlignment(Qt.AlignHCenter)
            left_pt = 0
        elif max(x1s) > self.right - 4 and left_pt > self.text_w * 0.35:
            bf.setAlignment(Qt.AlignRight)
            left_pt = 0
        else:
            bf.setAlignment(Qt.AlignLeft)
        if left_pt > 3:
            bf.setLeftMargin(left_pt * PT)
        if len(lines) > 1 and x0s[0] - min(x0s[1:]) > 3:
            bf.setTextIndent((x0s[0] - min(x0s[1:])) * PT)

        spans = [s for ln in lines for s in ln["spans"]]
        sizes = [s["size"] for s in spans if s["text"].strip()]
        bold_all = all(is_bold(s) for s in spans if s["text"].strip())
        size = max(sizes) if sizes else self.body_size
        text_len = sum(len(s["text"]) for s in spans)
        level = 0
        if text_len < 200 and not para["bullet"]:
            if size >= self.body_size * 1.6:
                level = 1
            elif size >= self.body_size * 1.25 or (bold_all and size >= self.body_size * 1.1):
                level = 2
            elif bold_all and len(lines) == 1 and size >= self.body_size and text_len < 90:
                level = 3
        if level:
            bf.setHeadingLevel(level)
            bf.setProperty(m.STYLE_PROP, f"Heading {level}")
        else:
            bf.setProperty(m.STYLE_PROP, "Normal")

        first_cf = char_format(spans[0]) if spans else QTextCharFormat()
        self._new_block(bf, first_cf)
        if para["bullet"]:
            lf = m.list_format("bullet")
            if left_pt > 3:
                lf.setIndent(1 + int(left_pt * PT // 40))
            prev_list = self.cur.block().previous().textList() if self.cur.block().previous().isValid() else None
            if prev_list is not None and prev_list.format().style() == lf.style() and \
                    prev_list.format().indent() == lf.indent():
                prev_list.add(self.cur.block())
            else:
                self.cur.createList(lf)
            bf2 = self.cur.blockFormat()
            bf2.setLeftMargin(0)
            bf2.setTextIndent(0)
            self.cur.setBlockFormat(bf2)

        stripped_bullet = False
        for li, ln in enumerate(lines):
            if li > 0:
                prev_text = self.cur.block().text()
                if prev_text.endswith("-") and len(prev_text) > 1 and prev_text[-2].islower():
                    nxt = "".join(s["text"] for s in ln["spans"]).lstrip()
                    if nxt[:1].islower():
                        self.cur.deletePreviousChar()        # re-join a hyphenated word
                    else:
                        pass
                elif not prev_text.endswith((" ", "\u00a0", "-", "/")):
                    self.cur.insertText(" ", char_format(ln["spans"][0]) if ln["spans"] else QTextCharFormat())
            for si, s in enumerate(ln["spans"]):
                text = s["text"]
                if li == 0 and si == 0:
                    text = text.lstrip()
                if para["bullet"] and not stripped_bullet:
                    t = text.lstrip()
                    if t and t[0] in BULLETS:
                        text = t[1:].lstrip()
                        stripped_bullet = True
                    elif not t:
                        continue
                if not text:
                    continue
                link = ""
                for rect, uri in links:
                    bb = s["bbox"]
                    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                    if rect.x0 - 1 <= cx <= rect.x1 + 1 and rect.y0 - 1 <= cy <= rect.y1 + 1:
                        link = uri
                        break
                cf = char_format(s, link)
                bb = s["bbox"]
                cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
                for rect, fill in fills:
                    if rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1:
                        cf.setBackground(QColor.fromRgbF(*fill[:3]))
                        break
                self.cur.insertText(text.replace("\u00ad", ""), cf)
        return bottom

    def _write_image(self, block, prev_bottom):
        data = block.get("image")
        if not data:
            return prev_bottom
        img = QImage.fromData(data)
        if img.isNull():
            return prev_bottom
        x0, y0, x1, y1 = block["bbox"]
        self._insert_image(img, (x1 - x0) * PT, (y1 - y0) * PT, x0, x1, y0, prev_bottom)
        return y1

    def _insert_image(self, img: QImage, w_px: float, h_px: float, x0, x1, y0, prev_bottom):
        self.image_n += 1
        name = f"pdf-image-{self.image_n}"
        self.doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
        bf = QTextBlockFormat()
        mid = (x0 + x1) / 2
        if abs(mid - (self.left + self.text_w / 2)) < self.text_w * 0.06 and x0 > self.left + 10:
            bf.setAlignment(Qt.AlignHCenter)
        elif x0 - self.left > 3:
            bf.setLeftMargin((x0 - self.left) * PT)
        if prev_bottom is not None:
            bf.setTopMargin(max(0.0, min(y0 - prev_bottom, 48)) * PT)
        bf.setProperty(m.STYLE_PROP, "Normal")
        self._new_block(bf)
        fmt = QTextImageFormat()
        fmt.setName(name)
        maxw = self.text_w * PT
        if w_px > maxw:
            h_px *= maxw / w_px
            w_px = maxw
        fmt.setWidth(w_px)
        fmt.setHeight(h_px)
        self.cur.insertImage(fmt)

    def _write_table(self, tab, prev_bottom):
        try:
            rows = tab.extract()
        except Exception:   # noqa: BLE001
            return prev_bottom
        if not rows:
            return prev_bottom
        nrows, ncols = len(rows), max(len(r) for r in rows)
        bf = QTextBlockFormat()
        bf.setProperty(m.STYLE_PROP, "Normal")
        self._new_block(bf)
        tf = QTextTableFormat()
        tf.setBorder(1)
        tf.setBorderBrush(QColor("#000000"))
        tf.setBorderStyle(QTextTableFormat.BorderStyle_Solid)
        tf.setCellSpacing(0)
        tf.setCellPadding(3)
        tf.setBorderCollapse(True)
        x0, y0, x1, y1 = tab.bbox
        widths = []
        try:
            cells = tab.rows[0].cells
            if len(cells) == ncols and all(c is not None for c in cells):
                widths = [(c[2] - c[0]) * PT for c in cells]
        except Exception:   # noqa: BLE001
            widths = []
        if widths:
            tf.setColumnWidthConstraints([QTextLength(QTextLength.FixedLength, w) for w in widths])
        else:
            tf.setWidth(QTextLength(QTextLength.PercentageLength, min(100, (x1 - x0) / self.text_w * 100)))
        if x0 - self.left > 3:
            tf.setLeftMargin((x0 - self.left) * PT)
        table = self.cur.insertTable(nrows, ncols, tf)
        body = QTextCharFormat()
        body.setFontFamilies(["Calibri"])
        body.setFontPointSize(max(7.0, min(self.body_size, 11.0)))
        for r, row in enumerate(rows):
            for c in range(ncols):
                text = (row[c] if c < len(row) else None) or ""
                cell = table.cellAt(r, c)
                cc = cell.firstCursorPosition()
                cf = QTextCharFormat(body)
                if r == 0:
                    cf.setFontWeight(QFont.Bold)
                cc.insertText(text.replace("\n", " ").strip(), cf)
        # merged cells: PyMuPDF gives None for the covered cells
        for r, row in enumerate(rows):
            c = 0
            while c < len(row):
                span = 1
                while c + span < len(row) and row[c + span] is None and row[c] is not None:
                    span += 1
                if span > 1:
                    table.mergeCells(r, c, 1, span)
                c += span
        self.cur.movePosition(QTextCursor.End)
        return y1

    def _scanned_page(self, page, prev_bottom):
        pix = page.get_pixmap(dpi=120)
        img = QImage.fromData(pix.tobytes("png"))
        if img.isNull():
            return prev_bottom
        w = self.text_w * PT
        h = w * pix.height / max(1, pix.width)
        self._insert_image(img, w, h, self.left, self.right, self.top, None)
        self.scanned_pages += 1
        return None

    def run(self):
        self._pages_data()
        if not self.pages:
            raise PdfError("The PDF has no pages.")
        self._headers_footers()
        self._metrics()
        for pi, pd in enumerate(self.pages):
            if self.progress and self.progress(len(self.pages) + pi, len(self.pages) * 2) is False:
                raise PdfError("cancelled")
            if pi > 0:
                self.page_break_pending = True
            blocks = pd["dict"]["blocks"]
            has_text = any(b.get("type") == 0 and any(s["text"].strip() for ln in b["lines"] for s in ln["spans"])
                           for b in blocks)
            if not has_text:
                self._scanned_page(pd["page"], None)
                continue
            table_rects = [t.bbox for t in pd["tables"]]
            items = []
            for bi, b in enumerate(blocks):
                if table_rects and _inside(b["bbox"], table_rects):
                    continue
                items.append((b["bbox"][1], b["bbox"][0], "block", bi, b))
            for t in pd["tables"]:
                items.append((t.bbox[1], t.bbox[0], "table", -1, t))
            items.sort(key=lambda it: (round(it[0], 1), it[1]))
            prev_bottom = None
            for _y, _x, kind, bi, obj in items:
                if kind == "table":
                    prev_bottom = self._write_table(obj, prev_bottom)
                elif obj.get("type") == 1:
                    prev_bottom = self._write_image(obj, prev_bottom)
                elif obj.get("type") == 0:
                    for para in self._paragraphs(pi, bi, obj):
                        prev_bottom = self._write_paragraph(para, pd["links"], prev_bottom, pd["fills"])
        if self.first_block:
            self.notes.append("The PDF contains no text that Write can read.")
        if self.scanned_pages:
            self.notes.append(f"{self.scanned_pages} scanned page{'s' if self.scanned_pages > 1 else ''} "
                              "came in as pictures (the text on them can't be edited).")
        m.tighten_lists(self.doc)
        self.doc.setModified(False)
        return self.doc, self.setup(), " ".join(self.notes)


def load_pdf(path: str, progress=None):
    """-> (QTextDocument, PageSetup, note). progress(done, total) may return False to cancel."""
    return Converter(path, progress).run()
