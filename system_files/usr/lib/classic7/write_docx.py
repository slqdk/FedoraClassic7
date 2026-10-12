"""Write: Word .docx import and export (python-docx).

Covers what everyday documents use: paragraph styles (Normal, Headings, Title, ...), fonts,
sizes, bold/italic/underline/strike, colours, highlight, super/subscript, alignment,
indents, spacing, line spacing, bullet and numbered lists, tables (with merged cells),
pictures, hyperlinks, page breaks, page size/orientation/margins, header and footer
(with page number fields). Anything else in a file is kept as plain text where possible.
"""
from __future__ import annotations

import io

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_COLOR_INDEX, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Mm, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QUrl
from PySide6.QtGui import (QColor, QFont, QImage, QTextBlockFormat, QTextCharFormat, QTextCursor,
                           QTextDocument, QTextFormat, QTextImageFormat, QTextLength, QTextTableFormat)

import write_model as m
from write_page import PageSetup

EMU_PER_PX = 9525
ALIGN_IN = {WD_ALIGN_PARAGRAPH.CENTER: Qt.AlignHCenter, WD_ALIGN_PARAGRAPH.RIGHT: Qt.AlignRight,
            WD_ALIGN_PARAGRAPH.JUSTIFY: Qt.AlignJustify, WD_ALIGN_PARAGRAPH.LEFT: Qt.AlignLeft}
HL_BY_INDEX = {
    WD_COLOR_INDEX.YELLOW: "yellow", WD_COLOR_INDEX.BRIGHT_GREEN: "green", WD_COLOR_INDEX.TURQUOISE: "cyan",
    WD_COLOR_INDEX.PINK: "magenta", WD_COLOR_INDEX.BLUE: "blue", WD_COLOR_INDEX.RED: "red",
    WD_COLOR_INDEX.DARK_BLUE: "darkBlue", WD_COLOR_INDEX.TEAL: "darkCyan", WD_COLOR_INDEX.GREEN: "darkGreen",
    WD_COLOR_INDEX.VIOLET: "darkMagenta", WD_COLOR_INDEX.DARK_RED: "darkRed", WD_COLOR_INDEX.DARK_YELLOW: "darkYellow",
    WD_COLOR_INDEX.GRAY_50: "darkGray", WD_COLOR_INDEX.GRAY_25: "lightGray", WD_COLOR_INDEX.BLACK: "black",
    WD_COLOR_INDEX.WHITE: "white",
}
INDEX_BY_HL = {v: k for k, v in HL_BY_INDEX.items()}


# =============================================================================
# Import
# =============================================================================
class _Importer:
    def __init__(self, path: str):
        self.d = Document(path)
        self.doc = m.new_document()
        self.cursor = QTextCursor(self.doc)
        self.first_block = True
        self.lists: dict[tuple[str, int], object] = {}
        self.images = 0
        self.pending_break = False       # a page break waits for the next text or paragraph
        self.num_formats = self._read_numbering()

    # ---- numbering: numId -> {ilvl: numFmt} -----------------------------------------------
    def _read_numbering(self) -> dict[str, dict[int, str]]:
        out: dict[str, dict[int, str]] = {}
        try:
            numbering = self.d.part.numbering_part.element
        except (NotImplementedError, KeyError, AttributeError):
            return out
        abstract = {}
        for an in numbering.findall(qn("w:abstractNum")):
            levels = {}
            for lvl in an.findall(qn("w:lvl")):
                fmt = lvl.find(qn("w:numFmt"))
                levels[int(lvl.get(qn("w:ilvl"), 0))] = fmt.get(qn("w:val")) if fmt is not None else "bullet"
            abstract[an.get(qn("w:abstractNumId"))] = levels
        for num in numbering.findall(qn("w:num")):
            ref = num.find(qn("w:abstractNumId"))
            if ref is not None:
                out[num.get(qn("w:numId"))] = abstract.get(ref.get(qn("w:val")), {})
        return out

    # ---- styles: effective values through the style chain ----------------------------------
    @staticmethod
    def _chain(style):
        while style is not None:
            yield style
            style = style.base_style

    def _style_font(self, para_style, attr):
        for st in self._chain(para_style):
            v = getattr(st.font, attr, None)
            if v is not None:
                return v
        try:
            v = getattr(self.d.styles["Normal"].font, attr, None)
        except KeyError:
            v = None
        return v

    def _char_format(self, run, para_style, heading: bool) -> QTextCharFormat:
        cf = QTextCharFormat()
        f = run.font

        def eff(attr):
            v = getattr(f, attr, None)
            if v is None and run.style is not None and run.style.type == 2:   # character style
                for st in self._chain(run.style):
                    v = getattr(st.font, attr, None)
                    if v is not None:
                        break
            if v is None:
                v = self._style_font(para_style, attr)
            return v

        name = eff("name") or (m.HEADING_FONT if heading else m.BODY_FONT)
        cf.setFontFamilies([name])
        size = eff("size")
        cf.setFontPointSize(size.pt if size is not None else 11)
        cf.setFontWeight(QFont.Bold if eff("bold") else QFont.Normal)
        cf.setFontItalic(bool(eff("italic")))
        cf.setFontUnderline(bool(eff("underline")))
        cf.setFontStrikeOut(bool(eff("strike")))
        if eff("superscript"):
            cf.setVerticalAlignment(QTextCharFormat.AlignSuperScript)
        elif eff("subscript"):
            cf.setVerticalAlignment(QTextCharFormat.AlignSubScript)
        color = None
        try:
            color = f.color.rgb if f.color is not None and f.color.type is not None else None
        except (AttributeError, ValueError):
            color = None
        if color is None:
            for st in self._chain(para_style):
                try:
                    if st.font.color is not None and st.font.color.rgb is not None:
                        color = st.font.color.rgb
                        break
                except (AttributeError, ValueError):
                    pass
        if color is not None:
            cf.setForeground(QColor(f"#{color}"))
        hl = f.highlight_color
        if hl is not None and hl in HL_BY_INDEX:
            cf.setBackground(QColor(m.HIGHLIGHTS[HL_BY_INDEX[hl]]))
        return cf

    def _block_format(self, para: Paragraph) -> QTextBlockFormat:
        style_name = para.style.name if para.style is not None else "Normal"
        st = m.STYLE_BY_NAME.get(style_name)
        bf = m.style_block_format(st) if st else m.style_block_format(m.STYLES[0])
        if not st:
            bf.setProperty(m.STYLE_PROP, style_name)
            if style_name.lower().startswith("heading "):
                try:
                    bf.setHeadingLevel(int(style_name.split()[-1]))
                except ValueError:
                    pass
        pf = para.paragraph_format

        def pchain(attr):
            v = getattr(pf, attr, None)
            if v is None:
                for s in self._chain(para.style):
                    v = getattr(s.paragraph_format, attr, None)
                    if v is not None:
                        break
            return v

        al = pchain("alignment")
        if al in ALIGN_IN:
            bf.setAlignment(ALIGN_IN[al])
        for attr, setter in (("space_before", bf.setTopMargin), ("space_after", bf.setBottomMargin)):
            v = pchain(attr)
            if v is not None:
                setter(v.pt * m.PT)
        ls = pchain("line_spacing")
        rule = pchain("line_spacing_rule")
        if isinstance(ls, float):
            bf.setLineHeight(ls * 100, m.PROPORTIONAL)
        elif ls is not None and rule in (WD_LINE_SPACING.EXACTLY, WD_LINE_SPACING.AT_LEAST):
            bf.setLineHeight(ls.pt * m.PT, m.FIXED)
        li = pchain("left_indent")
        if li is not None:
            bf.setLeftMargin(max(0.0, li.pt * m.PT))
        ri = pchain("right_indent")
        if ri is not None:
            bf.setRightMargin(max(0.0, ri.pt * m.PT))
        fi = pchain("first_line_indent")
        if fi is not None:
            bf.setTextIndent(fi.pt * m.PT)
        if pchain("page_break_before"):
            bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
        return bf

    # ---- writing into the QTextDocument ---------------------------------------------------
    def _new_block(self, bf: QTextBlockFormat, cf: QTextCharFormat | None = None):
        if self.pending_break:
            bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
            self.pending_break = False
        if self.first_block:
            self.cursor.setBlockFormat(bf)
            if cf is not None:
                self.cursor.setBlockCharFormat(cf)
            self.first_block = False
        else:
            self.cursor.insertBlock(bf, cf or QTextCharFormat())

    def _list_for(self, para: Paragraph):
        ppr = para._p.pPr
        numpr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if numpr is None:
            # list styles without numPr in the paragraph ("List Bullet", "List Number")
            name = (para.style.name if para.style is not None else "").lower()
            if name.startswith("list bullet"):
                return ("style-bullet", 0, "bullet")
            if name.startswith("list number"):
                return ("style-number", 0, "decimal")
            return None
        num_id_el = numpr.find(qn("w:numId"))
        ilvl_el = numpr.find(qn("w:ilvl"))
        if num_id_el is None:
            return None
        num_id = num_id_el.get(qn("w:val"))
        if num_id == "0":
            return None
        ilvl = int(ilvl_el.get(qn("w:val"))) if ilvl_el is not None else 0
        fmt = self.num_formats.get(num_id, {}).get(ilvl, "bullet")
        kind = {"decimal": "decimal", "lowerLetter": "lower", "upperLetter": "upper",
                "lowerRoman": "roman", "upperRoman": "roman"}.get(fmt, "bullet")
        return (num_id, ilvl, kind)

    def paragraph(self, para: Paragraph, in_cell: bool = False):
        bf = self._block_format(para)
        heading = bf.headingLevel() > 0 or str(bf.property(m.STYLE_PROP)) in ("Title", "Subtitle")
        self._new_block(bf)
        lst = self._list_for(para)
        if lst:
            key = (lst[0], lst[1])
            if key in self.lists and not in_cell:
                self.lists[key].add(self.cursor.block())
            else:
                self.lists[key] = self.cursor.createList(m.list_format(lst[2], lst[1] + 1))
        else:
            # a paragraph that is not in a list ends the current lists of the same level
            pass
        self._content(para._p, para, heading)

    def _content(self, p_el, para, heading: bool):
        from docx.text.run import Run
        para_style = para.style
        for child in p_el.iterchildren():
            tag = child.tag
            if tag == qn("w:r"):
                self._run(Run(child, para), para_style, heading)
            elif tag == qn("w:hyperlink"):
                rid = child.get(qn("r:id"))
                url = ""
                if rid:
                    try:
                        url = self.d.part.rels[rid].target_ref
                    except KeyError:
                        url = ""
                anchor = child.get(qn("w:anchor"))
                if not url and anchor:
                    url = "#" + anchor
                for r_el in child.findall(qn("w:r")):
                    self._run(Run(r_el, para), para_style, heading, href=url)
            elif tag in (qn("w:ins"), qn("w:smartTag"), qn("w:customXml"), qn("w:sdt")):
                content = child.find(qn("w:sdtContent")) if tag == qn("w:sdt") else child
                if content is not None:
                    self._content(content, para, heading)
            elif tag == qn("w:fldSimple"):
                for r_el in child.findall(qn("w:r")):
                    self._run(Run(r_el, para), para_style, heading)

    def _run(self, run, para_style, heading: bool, href: str = ""):
        cf = self._char_format(run, para_style, heading)
        if href:
            cf.setAnchor(True)
            cf.setAnchorHref(href)
            cf.setForeground(QColor("#0000FF"))
            cf.setFontUnderline(True)
        for el in run._r.iterchildren():
            tag = el.tag
            if tag == qn("w:t"):
                if self.pending_break and el.text:
                    bf = QTextBlockFormat(self.cursor.blockFormat())
                    bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
                    self.cursor.insertBlock(bf, cf)
                    self.pending_break = False
                self.cursor.insertText(el.text or "", cf)
            elif tag == qn("w:tab"):
                self.cursor.insertText("\t", cf)
            elif tag in (qn("w:br"), qn("w:cr")):
                if el.get(qn("w:type")) == "page":
                    self.pending_break = True
                else:
                    self.cursor.insertText(" ", cf)       # line break inside the paragraph
            elif tag == qn("w:sym"):
                ch = el.get(qn("w:char"))
                try:
                    self.cursor.insertText(chr(int(ch, 16) & 0xFFFF if int(ch, 16) >= 0xF000 else int(ch, 16)), cf)
                except (TypeError, ValueError):
                    pass
            elif tag == qn("w:drawing") or tag == qn("w:pict"):
                self._image(el)

    def _image(self, el):
        blips = el.findall(".//" + qn("a:blip"))
        if not blips:
            return
        rid = blips[0].get(qn("r:embed"))
        try:
            blob = self.d.part.related_parts[rid].blob
        except KeyError:
            return
        img = QImage.fromData(blob)
        if img.isNull():
            return
        ext = el.find(".//" + qn("wp:extent"))
        w = h = None
        if ext is not None:
            w = int(ext.get("cx", 0)) / EMU_PER_PX
            h = int(ext.get("cy", 0)) / EMU_PER_PX
        self.images += 1
        name = f"docx-image-{self.images}"
        self.doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
        fmt = QTextImageFormat()
        fmt.setName(name)
        fmt.setWidth(w or img.width())
        fmt.setHeight(h or img.height())
        self.cursor.insertImage(fmt)

    def table(self, tbl: Table):
        rows = tbl._tbl.tr_lst
        if not rows:
            return
        cols = len(tbl._tbl.tblGrid.gridCol_lst) if tbl._tbl.tblGrid is not None else max(
            len(r.tc_lst) for r in rows)
        cols = max(1, cols)
        # a table needs a paragraph before it in Qt
        if self.first_block:
            self.first_block = False
        fmt = QTextTableFormat()
        fmt.setBorder(1)
        fmt.setBorderBrush(QColor("#000000"))
        fmt.setBorderStyle(QTextFrameFormat_Solid())
        fmt.setCellPadding(4)
        fmt.setCellSpacing(0)
        fmt.setWidth(QTextLength(QTextLength.PercentageLength, 100))
        table = self.cursor.insertTable(len(rows), cols, fmt)
        vmerge_start: dict[int, int] = {}
        for r, tr in enumerate(rows):
            c = 0
            for tc in tr.tc_lst:
                span = tc.grid_span if hasattr(tc, "grid_span") else 1
                vm = tc.vMerge if hasattr(tc, "vMerge") else None
                if c >= cols:
                    break
                if vm == "continue" and c in vmerge_start:
                    start = vmerge_start[c]
                    table.mergeCells(start, c, r - start + 1, span)
                    c += span
                    continue
                if vm == "restart":
                    vmerge_start[c] = r
                elif c in vmerge_start:
                    del vmerge_start[c]
                if span > 1:
                    table.mergeCells(r, c, 1, min(span, cols - c))
                cell = table.cellAt(r, c)
                cur = cell.firstCursorPosition()
                saved, saved_first = self.cursor, self.first_block
                self.cursor, self.first_block = cur, True
                for p_el in tc.iterchildren():
                    if p_el.tag == qn("w:p"):
                        self.paragraph(Paragraph(p_el, tbl._parent), in_cell=True)
                self.cursor, self.first_block = saved, saved_first
                c += span
        self.cursor = table.lastCursorPosition()
        self.cursor.movePosition(QTextCursor.NextBlock)
        self.first_block = True          # Qt keeps a paragraph after every table: use it

    def section(self) -> PageSetup:
        setup = PageSetup()
        try:
            s = self.d.sections[0]
        except IndexError:
            return setup
        if s.page_width and s.page_height:
            w, h = s.page_width.mm, s.page_height.mm
            landscape = s.orientation == WD_ORIENT.LANDSCAPE or w > h
            setup.landscape = landscape
            pw, ph = (h, w) if landscape else (w, h)
            from write_page import PAPER
            match = [k for k, (a, b) in PAPER.items() if abs(a - pw) < 2 and abs(b - ph) < 2]
            if match:
                setup.paper = match[0]
            else:
                setup.custom_size = (pw, ph)
        for attr in ("top", "bottom", "left", "right"):
            v = getattr(s, f"{attr}_margin")
            if v is not None:
                setattr(setup, attr, max(0.0, v.mm))
        if s.header_distance is not None:
            setup.header_distance = s.header_distance.mm
        if s.footer_distance is not None:
            setup.footer_distance = s.footer_distance.mm
        setup.header = _hf_text(s.header)
        setup.footer = _hf_text(s.footer)
        return setup

    def run(self):
        for child in self.d.element.body.iterchildren():
            if child.tag == qn("w:p"):
                self.paragraph(Paragraph(child, self.d._body))
            elif child.tag == qn("w:tbl"):
                self.table(Table(child, self.d._body))
        setup = self.section()
        m.tighten_lists(self.doc)
        self.doc.setModified(False)
        return self.doc, setup


def QTextFrameFormat_Solid():  # noqa: N802
    from PySide6.QtGui import QTextFrameFormat
    return QTextFrameFormat.BorderStyle_Solid


def _hf_text(hf) -> str:
    """Header/footer as one line of text; PAGE / NUMPAGES fields become {page} / {pages}."""
    try:
        if hf.is_linked_to_previous and not hf._has_definition:
            return ""
    except AttributeError:
        pass
    parts = []
    for p in hf.paragraphs:
        text = []
        el = p._p
        instr_pending = None
        for node in el.iter():
            if node.tag == qn("w:fldSimple"):
                instr = (node.get(qn("w:instr")) or "").strip().upper()
                text.append("{pages}" if instr.startswith("NUMPAGES") else "{page}" if instr.startswith("PAGE") else "")
            elif node.tag == qn("w:instrText"):
                instr_pending = (node.text or "").strip().upper()
            elif node.tag == qn("w:fldChar") and node.get(qn("w:fldCharType")) == "end" and instr_pending:
                text.append("{pages}" if instr_pending.startswith("NUMPAGES") else
                            "{page}" if instr_pending.startswith("PAGE") else "")
                instr_pending = None
            elif node.tag == qn("w:t") and instr_pending is None:
                parent = node.getparent()
                if parent is not None and parent.getparent() is not None and \
                        parent.getparent().tag == qn("w:fldSimple"):
                    continue
                text.append(node.text or "")
            elif node.tag == qn("w:tab"):
                text.append("    ")
        line = "".join(text).strip()
        if line:
            parts.append(line)
    return "   ".join(parts)


def load_docx(path: str):
    return _Importer(path).run()


# =============================================================================
# Export
# =============================================================================
def _length_pt(px: float) -> Pt:
    return Pt(px / m.PT)


def _add_field(paragraph, instr: str):
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), instr)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    paragraph._p.append(fld)


def _write_hf(container, text: str):
    p = container.paragraphs[0] if container.paragraphs else container.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    rest = text
    while rest:
        i_page, i_pages = rest.find("{page}"), rest.find("{pages}")
        idx = [i for i in (i_page, i_pages) if i >= 0]
        if not idx:
            p.add_run(rest)
            break
        i = min(idx)
        if i:
            p.add_run(rest[:i])
        if rest.startswith("{pages}", i):
            _add_field(p, "NUMPAGES")
            rest = rest[i + 7:]
        else:
            _add_field(p, "PAGE")
            rest = rest[i + 6:]


def _hyperlink(paragraph, url: str, text: str, cf: QTextCharFormat):
    part = paragraph.part
    if url.startswith("#"):
        link = OxmlElement("w:hyperlink")
        link.set(qn("w:anchor"), url[1:])
    else:
        rid = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
                             is_external=True)
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), rid)
    r = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    style = OxmlElement("w:color")
    style.set(qn("w:val"), "0000FF")
    rpr.append(style)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rpr.append(u)
    r.append(rpr)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    link.append(r)
    paragraph._p.append(link)


class _Exporter:
    def __init__(self, doc: QTextDocument, setup: PageSetup):
        self.src = doc
        self.setup = setup
        self.d = Document()
        self._prepare()

    def _prepare(self):
        s = self.d.sections[0]
        w, h = self.setup.size_mm
        s.orientation = WD_ORIENT.LANDSCAPE if self.setup.landscape else WD_ORIENT.PORTRAIT
        s.page_width, s.page_height = Mm(w), Mm(h)
        s.top_margin, s.bottom_margin = Mm(self.setup.top), Mm(self.setup.bottom)
        s.left_margin, s.right_margin = Mm(self.setup.left), Mm(self.setup.right)
        s.header_distance, s.footer_distance = Mm(self.setup.header_distance), Mm(self.setup.footer_distance)
        normal = self.d.styles["Normal"]
        normal.font.name = m.BODY_FONT
        normal.font.size = Pt(11)
        normal.paragraph_format.space_after = Pt(10)
        normal.paragraph_format.line_spacing = 1.15
        if self.setup.header:
            _write_hf(s.header, self.setup.header)
        if self.setup.footer:
            _write_hf(s.footer, self.setup.footer)
        # python-docx's template starts with one empty paragraph
        body = self.d.element.body
        for p in list(body.findall(qn("w:p"))):
            body.remove(p)

    def _style_for(self, block) -> str:
        lst = block.textList()
        if lst is not None:
            kind = m.list_kind(lst.format())
            level = max(1, lst.format().indent())
            base = "List Bullet" if kind == "bullet" else "List Number"
            name = base if level == 1 else f"{base} {min(level, 3)}"
            return name
        return m.block_style(block)

    def _paragraph(self, container, block):
        name = self._style_for(block)
        try:
            p = container.add_paragraph(style=name)
        except KeyError:
            p = container.add_paragraph()
        bf = block.blockFormat()
        pf = p.paragraph_format
        al = bf.alignment()
        if al & Qt.AlignHCenter:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif al & Qt.AlignRight:
            p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif al & Qt.AlignJustify:
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf.space_before = _length_pt(bf.topMargin())
        pf.space_after = _length_pt(bf.bottomMargin())
        if bf.lineHeightType() == m.PROPORTIONAL and bf.lineHeight() > 0:
            pf.line_spacing = bf.lineHeight() / 100
        elif bf.lineHeightType() == m.FIXED and bf.lineHeight() > 0:
            pf.line_spacing = _length_pt(bf.lineHeight())
            pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        if block.textList() is None:
            if bf.leftMargin():
                pf.left_indent = _length_pt(bf.leftMargin())
            if bf.textIndent():
                pf.first_line_indent = _length_pt(bf.textIndent())
        if bf.rightMargin():
            pf.right_indent = _length_pt(bf.rightMargin())
        if bf.pageBreakPolicy() & QTextFormat.PageBreak_AlwaysBefore:
            pf.page_break_before = True
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            it += 1
            if not frag.isValid():
                continue
            cf = frag.charFormat()
            if cf.isImageFormat():
                self._image(p, cf.toImageFormat())
                continue
            text = frag.text().replace(" ", "")
            if cf.isAnchor() and cf.anchorHref():
                _hyperlink(p, cf.anchorHref(), text, cf)
                continue
            parts = text.split(" ")
            for i, part in enumerate(parts):
                if i:
                    p.add_run().add_break(WD_BREAK.LINE)
                if part:
                    self._run(p, part, cf)
        return p

    def _run(self, p, text: str, cf: QTextCharFormat):
        segs = text.split("\t")
        for i, seg in enumerate(segs):
            if i:
                r = p.add_run()
                r.add_tab()
                self._fmt(r, cf)
            if seg:
                r = p.add_run(seg)
                self._fmt(r, cf)

    def _fmt(self, r, cf: QTextCharFormat):
        f = r.font
        fams = cf.fontFamilies()
        if fams:
            f.name = fams[0] if isinstance(fams, list) else str(fams)
        if cf.fontPointSize() > 0:
            f.size = Pt(cf.fontPointSize())
        if cf.fontWeight() >= QFont.DemiBold:
            f.bold = True
        if cf.fontItalic():
            f.italic = True
        if cf.fontUnderline():
            f.underline = True
        if cf.fontStrikeOut():
            f.strike = True
        va = cf.verticalAlignment()
        if va == QTextCharFormat.AlignSuperScript:
            f.superscript = True
        elif va == QTextCharFormat.AlignSubScript:
            f.subscript = True
        if cf.hasProperty(QTextFormat.ForegroundBrush):
            c = cf.foreground().color()
            if c.isValid() and c != QColor("#000000"):
                f.color.rgb = RGBColor(c.red(), c.green(), c.blue())
        if cf.hasProperty(QTextFormat.BackgroundBrush):
            c = cf.background().color().name().upper()
            name = next((k for k, v in m.HIGHLIGHTS.items() if v.upper() == c), None)
            if name and name in INDEX_BY_HL:
                f.highlight_color = INDEX_BY_HL[name]
            elif cf.background().style() != Qt.NoBrush:
                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), c.lstrip("#"))
                r._r.get_or_add_rPr().append(shd)

    def _image(self, p, fmt: QTextImageFormat):
        img = self.src.resource(QTextDocument.ImageResource, QUrl(fmt.name()))
        if not isinstance(img, QImage):
            img = QImage(fmt.name())
        if img is None or img.isNull():
            return
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        buf.close()
        w = fmt.width() or img.width()
        h = fmt.height() or (img.height() * w / max(1, img.width()))
        p.add_run().add_picture(io.BytesIO(bytes(ba)), width=Emu(int(w * EMU_PER_PX)),
                                height=Emu(int(h * EMU_PER_PX)))

    def _table(self, container, table):
        rows, cols = table.rows(), table.columns()
        t = container.add_table(rows=rows, cols=cols)
        try:
            t.style = self.d.styles["Table Grid"]
        except KeyError:
            pass
        done = set()
        for r in range(rows):
            for c in range(cols):
                cell = table.cellAt(r, c)
                if (cell.row(), cell.column()) in done:
                    continue
                done.add((cell.row(), cell.column()))
                target = t.cell(r, c)
                rs, cs = cell.rowSpan(), cell.columnSpan()
                if rs > 1 or cs > 1:
                    target = target.merge(t.cell(r + rs - 1, c + cs - 1))
                # remove the empty default paragraph, then copy the cell's blocks
                for p in list(target.paragraphs):
                    p._p.getparent().remove(p._p)
                b = cell.firstCursorPosition().block()
                end = cell.lastCursorPosition().block()
                while b.isValid():
                    self._paragraph(target, b)
                    if b == end:
                        break
                    b = b.next()
                if not target.paragraphs:
                    target.add_paragraph()
        return t

    def run(self, path: str):
        block = self.src.begin()
        seen_tables = set()
        while block.isValid():
            cur = QTextCursor(block)
            table = cur.currentTable()
            if table is not None:
                key = table.firstPosition()
                if key not in seen_tables:
                    seen_tables.add(key)
                    self._table(self.d, table)
                    block = self.src.findBlock(table.lastPosition() + 1)
                    continue
                block = block.next()
                continue
            p = self._paragraph(self.d, block)
            if block.blockFormat().hasProperty(QTextFormat.BlockTrailingHorizontalRulerWidth):
                ppr = p._p.get_or_add_pPr()
                bdr = OxmlElement("w:pBdr")
                bottom = OxmlElement("w:bottom")
                for k, v in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "auto")):
                    bottom.set(qn(k), v)
                bdr.append(bottom)
                ppr.append(bdr)
            block = block.next()
        if not self.d.paragraphs and not self.d.tables:
            self.d.add_paragraph()
        self.d.core_properties.title = self.src.metaInformation(QTextDocument.DocumentTitle) or ""
        self.d.save(path)


def save_docx(doc: QTextDocument, setup: PageSetup, path: str):
    _Exporter(doc, setup).run(path)
