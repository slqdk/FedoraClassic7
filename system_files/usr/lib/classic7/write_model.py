"""Write: how a document is represented in a QTextDocument, shared by the editor and the
file formats.

  - paragraph style name : QTextBlockFormat property STYLE_PROP (plus headingLevel)
  - lists                : QTextList (bullet / decimal / letters / roman)
  - page breaks          : QTextBlockFormat.pageBreakPolicy = PageBreak_AlwaysBefore
  - pictures             : QTextImageFormat, image stored as a document resource
  - hyperlinks           : QTextCharFormat anchor + href
  - header / footer      : write_page.PageSetup

Sizes: fonts in points; margins and indents in document pixels (96 per inch).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import (QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument,
                           QTextFormat, QTextListFormat)

STYLE_PROP = QTextFormat.UserProperty + 1
PT = 96 / 72                      # pixels per point
PROPORTIONAL = QTextBlockFormat.LineHeightTypes.ProportionalHeight.value
FIXED = QTextBlockFormat.LineHeightTypes.FixedHeight.value
SINGLE = QTextBlockFormat.LineHeightTypes.SingleHeight.value

BODY_FONT = "Calibri"             # Word 2007 defaults; Carlito/Caladea are metric-compatible
HEADING_FONT = "Cambria"          # stand-ins that the system shows for these names
FONT_SUBSTITUTES = {"Calibri": ["Carlito"], "Cambria": ["Caladea"], "Arial": ["Liberation Sans"],
                    "Times New Roman": ["Liberation Serif"], "Courier New": ["Liberation Mono"],
                    "Segoe UI": ["Noto Sans"], "Tahoma": ["DejaVu Sans"], "Verdana": ["DejaVu Sans"]}

HIGHLIGHTS = {             # Word's highlight colours (name used in .docx: hex)
    "yellow": "#FFFF00", "green": "#00FF00", "cyan": "#00FFFF", "magenta": "#FF00FF",
    "blue": "#0000FF", "red": "#FF0000", "darkBlue": "#000080", "darkCyan": "#008080",
    "darkGreen": "#008000", "darkMagenta": "#800080", "darkRed": "#800000", "darkYellow": "#808000",
    "darkGray": "#808080", "lightGray": "#C0C0C0", "black": "#000000", "white": "#FFFFFF",
}


@dataclass(frozen=True)
class Style:
    name: str
    font: str = BODY_FONT
    size: float = 11
    bold: bool = False
    italic: bool = False
    color: str = "#000000"
    space_before: float = 0       # points
    space_after: float = 10
    line: float = 115             # percent
    heading: int = 0
    keep_char: bool = False       # character style (Strong, Emphasis): don't touch the paragraph


STYLES: list[Style] = [
    Style("Normal"),
    Style("No Spacing", space_after=0, line=100),
    Style("Heading 1", font=HEADING_FONT, size=14, bold=True, color="#365F91", space_before=24, space_after=0, heading=1),
    Style("Heading 2", font=HEADING_FONT, size=13, bold=True, color="#4F81BD", space_before=10, space_after=0, heading=2),
    Style("Heading 3", font=HEADING_FONT, size=11, bold=True, color="#4F81BD", space_before=10, space_after=0, heading=3),
    Style("Title", font=HEADING_FONT, size=26, color="#17365D", space_after=15, line=100),
    Style("Subtitle", font=HEADING_FONT, size=12, italic=True, color="#4F81BD", space_after=10),
    Style("Quote", italic=True, color="#000000"),
    Style("Intense Quote", bold=True, italic=True, color="#4F81BD", space_before=10, space_after=14),
    Style("Strong", bold=True, keep_char=True),
    Style("Emphasis", italic=True, keep_char=True),
]
STYLE_BY_NAME = {s.name: s for s in STYLES}


def style_char_format(st: Style) -> QTextCharFormat:
    cf = QTextCharFormat()
    if not st.keep_char:
        cf.setFontFamilies([st.font])
        cf.setFontPointSize(st.size)
        cf.setForeground(QColor(st.color))
    cf.setFontWeight(QFont.Bold if st.bold else QFont.Normal)
    cf.setFontItalic(st.italic)
    return cf


def style_block_format(st: Style, base: QTextBlockFormat | None = None) -> QTextBlockFormat:
    bf = QTextBlockFormat(base) if base is not None else QTextBlockFormat()
    bf.setTopMargin(st.space_before * PT)
    bf.setBottomMargin(st.space_after * PT)
    bf.setLineHeight(st.line, PROPORTIONAL)
    bf.setHeadingLevel(st.heading)
    bf.setProperty(STYLE_PROP, st.name)
    return bf


def apply_style(cursor: QTextCursor, name: str):
    """Apply a paragraph style to the paragraphs touched by the cursor (or a character
    style to the selection), like Word's Styles gallery."""
    st = STYLE_BY_NAME.get(name, STYLES[0])
    cursor.beginEditBlock()
    if st.keep_char:
        cursor.mergeCharFormat(style_char_format(st))
    else:
        start, end = sorted((cursor.position(), cursor.anchor()))
        c = QTextCursor(cursor.document())
        c.setPosition(start)
        c.movePosition(QTextCursor.StartOfBlock)
        c.setPosition(end, QTextCursor.KeepAnchor)
        c.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        c.setBlockFormat(style_block_format(st, c.blockFormat()))
        # the whole paragraph text takes the style's font, like Word does
        c.setCharFormat(style_char_format(st))
        cursor.setBlockCharFormat(style_char_format(st))
    cursor.endEditBlock()


def block_style(block) -> str:
    v = block.blockFormat().property(STYLE_PROP)
    if v:
        return str(v)
    lvl = block.blockFormat().headingLevel()
    return f"Heading {lvl}" if 1 <= lvl <= 3 else "Normal"


def new_document() -> QTextDocument:
    doc = QTextDocument()
    doc.setDefaultFont(QFont(BODY_FONT, 11))
    doc.setDocumentMargin(0)
    c = QTextCursor(doc)
    c.setBlockFormat(style_block_format(STYLES[0]))
    c.setBlockCharFormat(style_char_format(STYLES[0]))
    c.setCharFormat(style_char_format(STYLES[0]))
    doc.setModified(False)
    return doc


def list_format(kind: str, level: int = 1) -> QTextListFormat:
    lf = QTextListFormat()
    lf.setStyle({
        "bullet": [QTextListFormat.ListDisc, QTextListFormat.ListCircle, QTextListFormat.ListSquare][(level - 1) % 3],
        "decimal": QTextListFormat.ListDecimal,
        "lower": QTextListFormat.ListLowerAlpha,
        "upper": QTextListFormat.ListUpperAlpha,
        "roman": QTextListFormat.ListLowerRoman,
    }.get(kind, QTextListFormat.ListDisc))
    lf.setIndent(level)
    return lf


def list_kind(lf: QTextListFormat) -> str:
    s = lf.style()
    if s in (QTextListFormat.ListDecimal,):
        return "decimal"
    if s == QTextListFormat.ListLowerAlpha:
        return "lower"
    if s == QTextListFormat.ListUpperAlpha:
        return "upper"
    if s in (QTextListFormat.ListLowerRoman, QTextListFormat.ListUpperRoman):
        return "roman"
    return "bullet"


def tighten_lists(doc):
    """Word's list styles use "contextual spacing": no space between items of the same list,
    only after the last one. Apply that to every list in the document."""
    block = doc.begin()
    while block.isValid():
        nxt = block.next()
        lst = block.textList()
        if lst is not None and nxt.isValid() and nxt.textList() is not None:
            bf = block.blockFormat()
            if bf.bottomMargin() or nxt.blockFormat().topMargin():
                cc = QTextCursor(block)
                bf.setBottomMargin(0)
                cc.setBlockFormat(bf)
                nf = nxt.blockFormat()
                nf.setTopMargin(0)
                QTextCursor(nxt).setBlockFormat(nf)
        block = nxt
