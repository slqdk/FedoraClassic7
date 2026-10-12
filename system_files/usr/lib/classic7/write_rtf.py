"""Write: Rich Text Format (.rtf) reading and writing.

RTF is also what Write puts in "Word 97-2003 Document (*.doc)" files: Word, WordPad and
LibreOffice open an RTF file with a .doc name without asking, which keeps those files
editable everywhere without writing Word's binary format.

The reader handles the common subset (what Write, Word and WordPad produce for normal
documents): fonts, sizes, bold/italic/underline/strike, colours, highlight, super/sub,
alignment, indents, spacing, page breaks, simple tables, PNG/JPEG pictures, header/footer,
page size and margins. Unknown destinations are skipped.
"""
from __future__ import annotations

import binascii
import re
from dataclasses import dataclass, field

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt, QUrl
from PySide6.QtGui import (QColor, QFont, QImage, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QTextFormat, QTextFrameFormat, QTextImageFormat, QTextLength, QTextTableFormat)

import write_model as m
from write_page import PX_PER_MM, PageSetup

TWIPS_PER_PX = 15
TWIPS_PER_MM = 1440 / 25.4


# =============================================================================
# Writer
# =============================================================================
def _esc(text: str) -> str:
    out = []
    for ch in text:
        o = ord(ch)
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ch == "\t":
            out.append("\\tab ")
        elif ch == "\u2028":
            out.append("\\line ")
        elif o < 128:
            out.append(ch)
        else:
            if o > 0xFFFF:
                ch_bytes = ch.encode("utf-16-le")
                for i in range(0, len(ch_bytes), 2):
                    v = int.from_bytes(ch_bytes[i:i + 2], "little")
                    out.append(f"\\u{v - 65536 if v > 32767 else v}?")
            else:
                out.append(f"\\u{o - 65536 if o > 32767 else o}?")
    return "".join(out)


class _Tables:
    def __init__(self):
        self.fonts: list[str] = []
        self.colors: list[str] = []

    def font(self, name: str) -> int:
        if name not in self.fonts:
            self.fonts.append(name)
        return self.fonts.index(name)

    def color(self, c: QColor) -> int:
        key = c.name().upper()
        if key not in self.colors:
            self.colors.append(key)
        return self.colors.index(key) + 1       # 0 = auto


STYLE_IDS = {s.name: i for i, s in enumerate(m.STYLES)}


def _char(cf: QTextCharFormat, t: _Tables) -> str:
    out = []
    fams = cf.fontFamilies()
    name = (fams[0] if fams else None) or m.BODY_FONT
    out.append(f"\\f{t.font(name)}")
    size = cf.fontPointSize() or 11
    out.append(f"\\fs{int(round(size * 2))}")
    if cf.fontWeight() >= QFont.DemiBold:
        out.append("\\b")
    if cf.fontItalic():
        out.append("\\i")
    if cf.fontUnderline():
        out.append("\\ul")
    if cf.fontStrikeOut():
        out.append("\\strike")
    va = cf.verticalAlignment()
    if va == QTextCharFormat.AlignSuperScript:
        out.append("\\super")
    elif va == QTextCharFormat.AlignSubScript:
        out.append("\\sub")
    if cf.hasProperty(QTextFormat.ForegroundBrush):
        out.append(f"\\cf{t.color(cf.foreground().color())}")
    if cf.hasProperty(QTextFormat.BackgroundBrush) and cf.background().style() != Qt.NoBrush:
        idx = t.color(cf.background().color())
        out.append(f"\\highlight{idx}\\cb{idx}")
    return "".join(out) + " "


def _para(block, t: _Tables, in_table: bool = False) -> str:
    bf = block.blockFormat()
    out = ["\\pard\\plain"]
    style = m.block_style(block)
    if style in STYLE_IDS:
        out.append(f"\\s{STYLE_IDS[style]}")
        if bf.headingLevel():
            out.append(f"\\outlinelevel{bf.headingLevel() - 1}")
    if in_table:
        out.append("\\intbl")
    al = bf.alignment()
    out.append("\\qc" if al & Qt.AlignHCenter else "\\qr" if al & Qt.AlignRight else
               "\\qj" if al & Qt.AlignJustify else "\\ql")
    lst = block.textList()
    if lst is not None:
        level = max(1, lst.format().indent())
        out.append(f"\\li{360 * 2 * level}\\fi-360")
    else:
        if bf.leftMargin():
            out.append(f"\\li{int(bf.leftMargin() * TWIPS_PER_PX)}")
        if bf.textIndent():
            out.append(f"\\fi{int(bf.textIndent() * TWIPS_PER_PX)}")
    if bf.rightMargin():
        out.append(f"\\ri{int(bf.rightMargin() * TWIPS_PER_PX)}")
    out.append(f"\\sb{int(bf.topMargin() * TWIPS_PER_PX)}\\sa{int(bf.bottomMargin() * TWIPS_PER_PX)}")
    if bf.lineHeightType() == m.PROPORTIONAL and bf.lineHeight() > 0:
        out.append(f"\\sl{int(240 * bf.lineHeight() / 100)}\\slmult1")
    elif bf.lineHeightType() == m.FIXED and bf.lineHeight() > 0:
        out.append(f"\\sl-{int(bf.lineHeight() * TWIPS_PER_PX)}\\slmult0")
    if bf.pageBreakPolicy() & QTextFormat.PageBreak_AlwaysBefore:
        out.append("\\pagebb")
    body = ["".join(out) + " "]
    if lst is not None:
        idx = lst.itemNumber(block)
        marker = lst.itemText(block) if m.list_kind(lst.format()) != "bullet" else "\u2022"
        body.append("{" + _char(block.charFormat(), t) + _esc(marker or "\u2022") + "\\tab}")
    it = block.begin()
    while not it.atEnd():
        frag = it.fragment()
        it += 1
        if not frag.isValid():
            continue
        cf = frag.charFormat()
        if cf.isImageFormat():
            body.append(_picture(block.document(), cf.toImageFormat()))
            continue
        text = frag.text()
        if cf.isAnchor() and cf.anchorHref():
            body.append('{\\field{\\*\\fldinst HYPERLINK "' + _esc(cf.anchorHref()) + '"}{\\fldrslt {'
                        + _char(cf, t) + _esc(text) + "}}}")
        else:
            body.append("{" + _char(cf, t) + _esc(text) + "}")
    return "".join(body)


def _picture(doc: QTextDocument, fmt: QTextImageFormat) -> str:
    img = doc.resource(QTextDocument.ImageResource, QUrl(fmt.name()))
    if not isinstance(img, QImage):
        img = QImage(fmt.name())
    if img is None or img.isNull():
        return ""
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    w = fmt.width() or img.width()
    h = fmt.height() or img.height() * w / max(1, img.width())
    hexdata = binascii.hexlify(bytes(ba)).decode()
    lines = "\n".join(hexdata[i:i + 128] for i in range(0, len(hexdata), 128))
    return (f"{{\\pict\\pngblip\\picw{img.width()}\\pich{img.height()}"
            f"\\picwgoal{int(w * TWIPS_PER_PX)}\\pichgoal{int(h * TWIPS_PER_PX)}\n{lines}}}")


def _hf(kind: str, text: str, t: _Tables) -> str:
    if not text:
        return ""
    parts = re.split(r"(\{page\}|\{pages\})", text)
    body = []
    for p in parts:
        if p == "{page}":
            body.append("{\\field{\\*\\fldinst PAGE}{\\fldrslt 1}}")
        elif p == "{pages}":
            body.append("{\\field{\\*\\fldinst NUMPAGES}{\\fldrslt 1}}")
        elif p:
            body.append(_esc(p))
    return f"{{\\{kind}\\pard\\plain\\qc\\f{t.font(m.BODY_FONT)}\\fs20 " + "".join(body) + "\\par}\n"


def save_rtf(doc: QTextDocument, setup: PageSetup, path: str):
    t = _Tables()
    t.font(m.BODY_FONT)
    body = []
    block = doc.begin()
    done_tables = set()
    while block.isValid():
        table = QTextCursor(block).currentTable()
        if table is not None:
            if table.firstPosition() not in done_tables:
                done_tables.add(table.firstPosition())
                body.append(_table(table, t, setup))
                block = doc.findBlock(table.lastPosition() + 1)
                continue
            block = block.next()
            continue
        body.append(_para(block, t) + "\\par\n")
        block = block.next()
    w_mm, h_mm = setup.size_mm
    page = (f"\\paperw{int(w_mm * TWIPS_PER_MM)}\\paperh{int(h_mm * TWIPS_PER_MM)}"
            f"\\margl{int(setup.left * TWIPS_PER_MM)}\\margr{int(setup.right * TWIPS_PER_MM)}"
            f"\\margt{int(setup.top * TWIPS_PER_MM)}\\margb{int(setup.bottom * TWIPS_PER_MM)}"
            f"\\headery{int(setup.header_distance * TWIPS_PER_MM)}\\footery{int(setup.footer_distance * TWIPS_PER_MM)}"
            + ("\\landscape" if setup.landscape else ""))
    header = _hf("header", setup.header, t) + _hf("footer", setup.footer, t)
    fonts = "{\\fonttbl" + "".join(f"{{\\f{i}\\fnil {_esc(f)};}}" for i, f in enumerate(t.fonts)) + "}"
    colors = "{\\colortbl;" + "".join(
        f"\\red{int(c[1:3], 16)}\\green{int(c[3:5], 16)}\\blue{int(c[5:7], 16)};" for c in t.colors) + "}"
    styles = "{\\stylesheet" + "".join(f"{{\\s{i} {s.name.lower() if s.heading else s.name};}}"
                                       for i, s in enumerate(m.STYLES)) + "}"
    rtf = ("{\\rtf1\\ansi\\ansicpg1252\\deff0\\uc1\n" + fonts + "\n" + colors + "\n" + styles + "\n"
           + page + "\n" + header + "".join(body) + "}\n")
    with open(path, "w", encoding="ascii", errors="replace") as f:
        f.write(rtf)


def _table(table, t: _Tables, setup: PageSetup) -> str:
    rows, cols = table.rows(), table.columns()
    content_w = (setup.size_mm[0] - setup.left - setup.right) * TWIPS_PER_MM
    col_w = int(content_w / max(1, cols))
    out = []
    for r in range(rows):
        out.append("\\trowd\\trgaph108")
        for c in range(cols):
            b = "\\clbrdrt\\brdrs\\brdrw10\\clbrdrl\\brdrs\\brdrw10\\clbrdrb\\brdrs\\brdrw10\\clbrdrr\\brdrs\\brdrw10"
            out.append(f"{b}\\cellx{col_w * (c + 1)}")
        out.append("\n")
        for c in range(cols):
            cell = table.cellAt(r, c)
            blk = cell.firstCursorPosition().block()
            end = cell.lastCursorPosition().block()
            first = True
            while blk.isValid():
                if not first:
                    out.append("\\par ")
                out.append(_para(blk, t, in_table=True))
                first = False
                if blk == end:
                    break
                blk = blk.next()
            out.append("\\cell\n")
        out.append("\\row\n")
    out.append("\\pard\n")
    return "".join(out)


# =============================================================================
# Reader
# =============================================================================
@dataclass
class _CharState:
    font: int = 0
    size: float = 12
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    color: int = 0
    highlight: int = 0
    valign: int = 0          # 1 super, -1 sub
    href: str = ""

    def copy(self):
        return _CharState(**self.__dict__)


@dataclass
class _ParaState:
    align: str = "l"
    li: int = 0
    fi: int = 0
    ri: int = 0
    sb: int = 0
    sa: int = 0
    sl: int = 0
    slmult: int = 0
    pagebb: bool = False
    intbl: bool = False
    style: int = -1

    def copy(self):
        return _ParaState(**self.__dict__)


@dataclass
class _Para:
    fmt: _ParaState
    runs: list = field(default_factory=list)     # (text | QImage+size, _CharState)


class _Reader:
    SKIP = {"info", "stylesheet", "listtable", "listoverridetable", "revtbl", "rsidtbl", "generator",
            "xmlnstbl", "themedata", "colorschememapping", "latentstyles", "datastore", "fldinst",
            "pgdsctbl", "filetbl", "mmathPr", "operator", "nonshppict", "bkmkstart", "bkmkend",
            "listtext", "pntext", "pntxtb", "pntxta", "ftnsep", "ftnsepc", "aftnsep", "aftnsepc",
            "headerl", "headerf", "footerl", "footerf", "objdata", "xe", "tc", "fldtype", "template"}

    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.fonts: dict[int, str] = {}
        self.colors: list[QColor | None] = []
        self.items: list = []          # _Para or ("table", rows)
        self.cur = _Para(_ParaState())
        self.row: list = []            # cells of the current row; a cell = list of _Para
        self.cell: list = []
        self.rows: list = []
        self.setup = PageSetup()
        self.paper_w = self.paper_h = None

    # ---- output -----------------------------------------------------------------------------
    def _end_para(self):
        if self.cur.fmt.intbl:
            self.cell.append(self.cur)
        else:
            self._flush_table()
            self.items.append(self.cur)
        self.cur = _Para(self.cur.fmt.copy())

    def _end_cell(self):
        self.cell.append(self.cur)
        self.row.append(self.cell)
        self.cell = []
        self.cur = _Para(self.cur.fmt.copy())

    def _end_row(self):
        if self.row:
            self.rows.append(self.row)
        self.row = []

    def _flush_table(self):
        if self.rows:
            self.items.append(("table", self.rows))
            self.rows = []

    def _text(self, text: str, cs: _CharState):
        if text:
            self.cur.runs.append((text, cs.copy()))

    # ---- parsing ------------------------------------------------------------------------------
    def parse(self):
        stack = []
        cs = _CharState()
        dest = None                  # None = body; else name of the destination being read
        uc = 1
        skip_chars = 0
        buf: list[str] = []
        hf_text: list[str] = []
        pict = None
        font_buf: list[str] = []
        font_id = 0
        color_parts = {}
        field_href = ""
        hf_field = False
        s = self.s
        n = len(s)

        def flush():
            if buf:
                text = "".join(buf)
                buf.clear()
                if dest is None:
                    self._text(text, cs)
                elif dest in ("header", "footer"):
                    hf_text.append(text)
                elif dest == "fonttbl":
                    font_buf.append(text)
                elif dest == "pict":
                    pict["hex"].append(text)
                elif dest == "colortbl":
                    if ";" in text:
                        for _ in range(text.count(";")):
                            self.colors.append(QColor(color_parts.get("red", 0), color_parts.get("green", 0),
                                                      color_parts.get("blue", 0)) if color_parts else None)
                            color_parts.clear()

        while self.i < n:
            ch = s[self.i]
            if ch == "{":
                flush()
                stack.append((cs.copy(), dest, uc, self.cur.fmt.copy() if dest is None else None, field_href))
                self.i += 1
                continue
            if ch == "}":
                flush()
                if dest == "fonttbl" and font_buf:
                    name = "".join(font_buf).strip().rstrip(";").strip()
                    if name:
                        self.fonts[font_id] = name
                    font_buf.clear()
                if dest == "pict" and pict is not None and stack and stack[-1][1] != "pict":
                    self._picture(pict, cs)
                    pict = None
                old_dest = dest
                cs, dest, uc, _pf, field_href = stack.pop() if stack else (cs, None, uc, None, "")
                if old_dest in ("header", "footer") and dest != old_dest:
                    text = "".join(hf_text).strip()
                    hf_text.clear()
                    if old_dest == "header":
                        self.setup.header = text
                    else:
                        self.setup.footer = text
                self.i += 1
                continue
            if ch == "\\":
                self.i += 1
                if self.i >= n:
                    break
                c2 = s[self.i]
                if c2 in "\\{}":
                    if skip_chars:
                        skip_chars -= 1
                    else:
                        buf.append(c2)
                    self.i += 1
                    continue
                if c2 == "'":
                    hexv = s[self.i + 1:self.i + 3]
                    self.i += 3
                    if skip_chars:
                        skip_chars -= 1
                        continue
                    try:
                        buf.append(bytes([int(hexv, 16)]).decode("cp1252", errors="replace"))
                    except ValueError:
                        pass
                    continue
                if c2 == "*":
                    flush()
                    self.i += 1
                    # an ignorable destination: skip unless it is one we read
                    m_ = re.match(r"\s*\\([a-zA-Z]+)", s[self.i:])
                    word = m_.group(1) if m_ else ""
                    if word not in ("shppict", "fldinst"):
                        dest = "skip"
                    continue
                if c2 == "~":
                    buf.append("\u00a0")
                    self.i += 1
                    continue
                if c2 in "-_":
                    self.i += 1
                    continue
                if c2 in "\r\n":
                    flush()
                    if dest is None:
                        self._end_para()
                    self.i += 1
                    continue
                m_ = re.match(r"([a-zA-Z]+)(-?\d+)? ?", s[self.i:])
                if not m_:
                    self.i += 1
                    continue
                word, arg = m_.group(1), m_.group(2)
                self.i += m_.end()
                val = int(arg) if arg is not None else None
                # unicode
                if word == "u" and val is not None:
                    if dest in (None, "header", "footer", "fonttbl"):
                        buf.append(chr(val + 65536 if val < 0 else val))
                    skip_chars = uc
                    continue
                if word == "uc":
                    uc = val or 0
                    continue
                if dest == "skip":
                    continue
                if dest == "pict":
                    flush()
                    if word in ("pngblip", "jpegblip"):
                        pict["kind"] = word
                    elif word in ("picwgoal", "pichgoal", "picw", "pich", "picscalex", "picscaley"):
                        pict[word] = val
                    continue
                if dest == "colortbl":
                    flush()                    # a ";" before this word closes the previous colour
                    if word in ("red", "green", "blue"):
                        color_parts[word] = val or 0
                    continue
                if dest == "fonttbl":
                    if word == "f":
                        flush()
                        if font_buf:
                            font_buf.clear()
                        font_id = val or 0
                    continue
                flush()
                if word == "fldinst":
                    instr = self._read_fldinst()
                    if dest in ("header", "footer"):
                        if re.match(r"\s*NUMPAGES", instr):
                            hf_text.append("{pages}")
                            hf_field = True
                        elif re.match(r"\s*PAGE\b", instr):
                            hf_text.append("{page}")
                            hf_field = True
                    dest = "fldinst"
                    continue
                if word in self.SKIP:
                    dest = "skip"
                    continue
                if word == "fonttbl":
                    dest = "fonttbl"
                    continue
                if word == "colortbl":
                    dest = "colortbl"
                    continue
                if word in ("header", "footer"):
                    dest = word
                    hf_text.clear()
                    continue
                if word == "pict":
                    dest = "pict"
                    pict = {"hex": [], "kind": None}
                    continue
                if word == "chpgn" and dest in ("header", "footer"):
                    hf_text.append("{page}")
                    continue
                if word == "fldrslt" and dest in ("header", "footer"):
                    if hf_field:
                        dest = "skip"          # the field's cached result ("1") is replaced
                        hf_field = False
                    continue
                if dest in ("header", "footer"):
                    if word in ("tab",):
                        hf_text.append("  ")
                    continue
                self._control(word, val, cs)
                if word == "fldrslt":
                    cs.href = self.pending_href
                continue
            if ch in "\r\n":
                self.i += 1
                continue
            if skip_chars:
                skip_chars -= 1
                self.i += 1
                continue
            j = self.i
            while j < n and s[j] not in "\\{}\r\n":
                j += 1
            chunk = s[self.i:j]
            if skip_chars and chunk:
                cut = min(skip_chars, len(chunk))
                chunk = chunk[cut:]
                skip_chars -= cut
            buf.append(chunk)
            self.i = j
        flush()
        if self.cur.runs:
            self._end_para()
        self._end_row()
        self._flush_table()

    pending_href = ""

    def _read_fldinst(self) -> str:
        """Read a field instruction (HYPERLINK "url", PAGE, ...) up to its closing brace."""
        depth, j, out = 0, self.i, []
        while j < len(self.s):
            c = self.s[j]
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    break
                depth -= 1
            else:
                out.append(c)
            j += 1
        instr = "".join(out)
        m_ = re.search(r'HYPERLINK\s+"([^"]+)"', instr)
        self.pending_href = m_.group(1) if m_ else ""
        self.i = j
        return instr

    def _picture(self, pict, cs):
        data = "".join(pict["hex"])
        data = re.sub(r"[^0-9a-fA-F]", "", data)
        try:
            raw = binascii.unhexlify(data[: len(data) // 2 * 2])
        except binascii.Error:
            return
        img = QImage.fromData(raw)
        if img.isNull():
            return
        w = pict.get("picwgoal")
        h = pict.get("pichgoal")
        w = (w / TWIPS_PER_PX) if w else img.width()
        h = (h / TWIPS_PER_PX) if h else img.height()
        sx, sy = pict.get("picscalex"), pict.get("picscaley")
        if sx:
            w = w * sx / 100
        if sy:
            h = h * sy / 100
        self.cur.runs.append(((img, w, h), cs.copy()))

    def _control(self, word, val, cs: _CharState):
        pf = self.cur.fmt
        on = val != 0
        if word == "par":
            self._end_para()
        elif word == "line":
            self._text("\u2028", cs)
        elif word == "tab":
            self._text("\t", cs)
        elif word in ("page",):
            self._end_para()
            self.cur.fmt.pagebb = True
        elif word == "cell":
            self._end_cell()
        elif word == "row":
            self._end_row()
        elif word == "pard":
            self.cur.fmt = _ParaState(intbl=False)
        elif word == "plain":
            cs.__init__()
        elif word == "intbl":
            pf.intbl = True
        elif word in ("ql", "qc", "qr", "qj"):
            pf.align = word[1]
        elif word in ("li", "fi", "ri", "sb", "sa"):
            setattr(pf, word, val or 0)
        elif word == "sl":
            pf.sl = val or 0
        elif word == "slmult":
            pf.slmult = val or 0
        elif word == "pagebb":
            pf.pagebb = True
        elif word == "s":
            pf.style = val or 0
        elif word == "f":
            cs.font = val or 0
        elif word == "fs":
            cs.size = (val or 24) / 2
        elif word == "b":
            cs.bold = on
        elif word == "i":
            cs.italic = on
        elif word in ("ul", "uld", "uldb", "ulw", "ulth"):
            cs.underline = on
        elif word == "ulnone":
            cs.underline = False
        elif word in ("strike", "striked"):
            cs.strike = on
        elif word == "super":
            cs.valign = 1
        elif word == "sub":
            cs.valign = -1
        elif word == "nosupersub":
            cs.valign = 0
        elif word == "cf":
            cs.color = val or 0
        elif word in ("highlight", "cb", "chcbpat"):
            cs.highlight = val or 0
        elif word == "paperw":
            self.paper_w = val
        elif word == "paperh":
            self.paper_h = val
        elif word in ("margl", "margr", "margt", "margb"):
            attr = {"margl": "left", "margr": "right", "margt": "top", "margb": "bottom"}[word]
            setattr(self.setup, attr, (val or 0) / TWIPS_PER_MM)
        elif word == "landscape":
            self.setup.landscape = True
        elif word == "headery":
            self.setup.header_distance = (val or 0) / TWIPS_PER_MM
        elif word == "footery":
            self.setup.footer_distance = (val or 0) / TWIPS_PER_MM

    # ---- build the QTextDocument ---------------------------------------------------------
    def _cf(self, cs: _CharState) -> QTextCharFormat:
        cf = QTextCharFormat()
        cf.setFontFamilies([self.fonts.get(cs.font, m.BODY_FONT)])
        cf.setFontPointSize(cs.size)
        cf.setFontWeight(QFont.Bold if cs.bold else QFont.Normal)
        cf.setFontItalic(cs.italic)
        cf.setFontUnderline(cs.underline)
        cf.setFontStrikeOut(cs.strike)
        if cs.valign == 1:
            cf.setVerticalAlignment(QTextCharFormat.AlignSuperScript)
        elif cs.valign == -1:
            cf.setVerticalAlignment(QTextCharFormat.AlignSubScript)
        # colour table entry 0 is "auto" (None)
        if 0 < cs.color < len(self.colors) and self.colors[cs.color] is not None:
            cf.setForeground(self.colors[cs.color])
        if 0 < cs.highlight < len(self.colors) and self.colors[cs.highlight] is not None:
            cf.setBackground(self.colors[cs.highlight])
        if cs.href:
            cf.setAnchor(True)
            cf.setAnchorHref(cs.href)
        return cf

    def _bf(self, ps: _ParaState) -> QTextBlockFormat:
        st = m.STYLES[ps.style] if 0 <= ps.style < len(m.STYLES) else m.STYLES[0]
        bf = m.style_block_format(st)
        bf.setAlignment({"l": Qt.AlignLeft, "c": Qt.AlignHCenter, "r": Qt.AlignRight, "j": Qt.AlignJustify}[ps.align])
        bf.setLeftMargin(max(0, ps.li) / TWIPS_PER_PX)
        bf.setTextIndent(ps.fi / TWIPS_PER_PX)
        bf.setRightMargin(max(0, ps.ri) / TWIPS_PER_PX)
        bf.setTopMargin(ps.sb / TWIPS_PER_PX)
        bf.setBottomMargin(ps.sa / TWIPS_PER_PX)
        if ps.sl:
            if ps.slmult:
                bf.setLineHeight(abs(ps.sl) / 240 * 100, m.PROPORTIONAL)
            elif ps.sl < 0:
                bf.setLineHeight(-ps.sl / TWIPS_PER_PX, m.FIXED)
        else:
            bf.setLineHeight(100, m.PROPORTIONAL)
        if ps.pagebb:
            bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
        return bf

    def build(self):
        doc = m.new_document()
        cur = QTextCursor(doc)
        first = [True]
        images = [0]

        lists = {"kind": None, "list": None}

        def list_marker(p: _Para):
            """Lists are written as a marker + tab with a hanging indent ("•\t", "1.\t")."""
            if not p.runs or p.fmt.fi >= 0 or not isinstance(p.runs[0][0], str):
                return None
            first = p.runs[0][0]
            if len(p.runs) > 1 and p.runs[1][0] == "\t" and "\t" not in first:
                # marker and tab came as two runs: merge them first
                p.runs[0:2] = [(first + "\t", p.runs[0][1])]
                first = p.runs[0][0]
            if first.startswith("\u2022\t") or first in ("\u2022", "\u00b7"):
                return "bullet", len("\u2022\t") if first.startswith("\u2022\t") else len(first)
            mm = re.match(r"^(\d+|[a-z]|[ivxlc]+)[.)]\t", first)
            if mm:
                kind = "decimal" if mm.group(1).isdigit() else ("roman" if set(mm.group(1)) <= set("ivxlc")
                                                               and len(mm.group(1)) > 1 else "lower")
                return kind, mm.end()
            return None

        def put_para(cursor, p: _Para, is_first: bool):
            bf = self._bf(p.fmt)
            marker = list_marker(p)
            if marker:
                bf.setLeftMargin(0)
                bf.setTextIndent(0)
                text, cs0 = p.runs[0]
                p.runs[0] = (text[marker[1]:], cs0)
                # a following "\t" run after a separate marker run
                if marker[1] == len(text) and len(p.runs) > 1 and p.runs[1][0] == "\t":
                    p.runs.pop(1)
            if is_first:
                cursor.setBlockFormat(bf)
            else:
                cursor.insertBlock(bf)
            if marker:
                level = max(1, round((p.fmt.li or 720) / 720))
                if lists["kind"] == (marker[0], level) and lists["list"] is not None:
                    lists["list"].add(cursor.block())
                else:
                    lists["list"] = cursor.createList(m.list_format(marker[0], level))
                    lists["kind"] = (marker[0], level)
            else:
                lists["kind"] = lists["list"] = None
            for content, cs in p.runs:
                cf = self._cf(cs)
                if isinstance(content, tuple):
                    img, w, h = content
                    images[0] += 1
                    name = f"rtf-image-{images[0]}"
                    doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
                    f = QTextImageFormat()
                    f.setName(name)
                    f.setWidth(w)
                    f.setHeight(h)
                    cursor.insertImage(f)
                elif content:
                    cursor.insertText(content, cf)

        for item in self.items:
            if isinstance(item, tuple) and item[0] == "table":
                rows = item[1]
                cols = max(len(r) for r in rows)
                fmt = QTextTableFormat()
                fmt.setBorder(1)
                fmt.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
                fmt.setCellPadding(4)
                fmt.setCellSpacing(0)
                fmt.setWidth(QTextLength(QTextLength.PercentageLength, 100))
                table = cur.insertTable(len(rows), cols, fmt)
                for r, row in enumerate(rows):
                    for c, cell in enumerate(row):
                        cc = table.cellAt(r, c).firstCursorPosition()
                        for k, p in enumerate(cell):
                            put_para(cc, p, k == 0)
                cur = table.lastCursorPosition()
                cur.movePosition(QTextCursor.NextBlock)
                first[0] = True
                continue
            put_para(cur, item, first[0])
            first[0] = False
        if self.paper_w and self.paper_h:
            w, h = self.paper_w / TWIPS_PER_MM, self.paper_h / TWIPS_PER_MM
            if self.setup.landscape and w > h:
                w, h = h, w
            from write_page import PAPER
            match = [k for k, (a, b) in PAPER.items() if abs(a - w) < 2 and abs(b - h) < 2]
            if match:
                self.setup.paper = match[0]
            else:
                self.setup.custom_size = (w, h)
        doc.setModified(False)
        return doc, self.setup


def load_rtf(path: str):
    raw = open(path, "rb").read()
    text = raw.decode("latin-1")
    r = _Reader(text)
    r.parse()
    return r.build()


def is_rtf(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"{\\rtf"
    except OSError:
        return False
