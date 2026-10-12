"""Write: opening Word 97-2003 binary documents (.doc).

1. A .doc that is really RTF (as Write and many programs save it) opens with full formatting.
2. With wvHtml (package "wv") installed, the document is converted to HTML first, which keeps
   most formatting, tables and pictures.
3. Otherwise the text is read straight from the file (Word 97+ piece table): paragraphs,
   line and page breaks and table cells as tabs, without character formatting.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile

from PySide6.QtGui import QTextBlockFormat, QTextCursor, QTextFormat

import write_model as m
import write_rtf
from write_page import PageSetup


class DocError(Exception):
    pass


def load_doc(path: str):
    """Returns (QTextDocument, PageSetup, note) where note says how much was kept."""
    if write_rtf.is_rtf(path):
        doc, setup = write_rtf.load_rtf(path)
        return doc, setup, ""
    if shutil.which("wvHtml"):
        try:
            return _via_wvhtml(path)
        except (OSError, subprocess.SubprocessError, DocError):
            pass
    text = extract_text(path)
    return _from_text(text), PageSetup(), "Opened as text: formatting in this old Word file could not be read."


def _via_wvhtml(path: str):
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "doc.html")
        subprocess.run(["wvHtml", f"--targetdir={tmp}", path, "doc.html"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        if not os.path.exists(out):
            raise DocError("no output")
        html = open(out, encoding="utf-8", errors="replace").read()
        doc = m.new_document()
        doc.setBaseUrl(__import__("PySide6.QtCore", fromlist=["QUrl"]).QUrl.fromLocalFile(tmp + "/"))
        doc.setHtml(html)
        # pictures are loaded while the temp dir exists: force them into the document
        _embed_images(doc)
    doc.setModified(False)
    return doc, PageSetup(), "Opened with the old-Word-file converter: check the layout."


def _embed_images(doc):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QImage, QTextDocument
    block = doc.begin()
    while block.isValid():
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            it += 1
            cf = frag.charFormat()
            if cf.isImageFormat():
                name = cf.toImageFormat().name()
                img = doc.resource(QTextDocument.ImageResource, QUrl(name))
                if isinstance(img, QImage) and not img.isNull():
                    doc.addResource(QTextDocument.ImageResource, QUrl(name), img)
        block = block.next()


def _items(text: str):
    """Split Word's text stream into paragraphs and tables. In the stream a paragraph ends
    with \r, a table cell with \x07 and a table row with an extra \x07."""
    items, buf, cells, rows, prev = [], [], [], [], ""
    for ch in text:
        if ch == "\x07":
            if prev == "\x07":
                rows.append(cells)
                cells = []
            else:
                cells.append("".join(buf))
                buf = []
        elif ch == "\r":
            if rows and not cells and not buf:
                pass                                   # end of row followed by \r
            elif cells:
                buf.append("\u2028")                  # paragraph inside a table cell
            else:
                if rows:
                    items.append(("table", rows))
                    rows = []
                items.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
        prev = ch
    if cells:
        rows.append(cells + (["".join(buf)] if buf else []))
        buf = []
    if rows:
        items.append(("table", rows))
    if buf:
        items.append("".join(buf))
    return items


def _from_text(text: str):
    from PySide6.QtGui import QColor, QTextFrameFormat, QTextLength, QTextTableFormat
    doc = m.new_document()
    cur = QTextCursor(doc)
    first = True
    pending_break = False

    def clean(s: str) -> str:
        return s.replace("\x0b", "\u2028").replace("\x0c", "")

    for item in _items(text):
        if isinstance(item, tuple):
            rows = item[1]
            cols = max(len(r) for r in rows)
            fmt = QTextTableFormat()
            fmt.setBorder(1)
            fmt.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
            fmt.setBorderBrush(QColor("#000000"))
            fmt.setCellPadding(4)
            fmt.setCellSpacing(0)
            fmt.setWidth(QTextLength(QTextLength.PercentageLength, 100))
            table = cur.insertTable(len(rows), cols, fmt)
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    table.cellAt(r, c).firstCursorPosition().insertText(clean(cell))
            cur = table.lastCursorPosition()
            cur.movePosition(QTextCursor.NextBlock)
            first = True
            continue
        bf = m.style_block_format(m.STYLES[0])
        if pending_break:
            bf.setPageBreakPolicy(QTextFormat.PageBreak_AlwaysBefore)
            pending_break = False
        if "\x0c" in item and not item.replace("\x0c", "").strip():
            pending_break = True                     # a paragraph holding only a page break
            continue
        if first:
            cur.setBlockFormat(bf)
            first = False
        else:
            cur.insertBlock(bf)
        cur.insertText(clean(item))
        if "\x0c" in item:
            pending_break = True
    doc.setModified(False)
    return doc


# ---- Word 97 piece table ----------------------------------------------------------------------
def extract_text(path: str) -> str:
    try:
        import olefile
    except ImportError as e:
        raise DocError("The olefile Python module is needed to read old .doc files.") from e
    if not olefile.isOleFile(path):
        raise DocError("This is not a Word 97-2003 document.")
    ole = olefile.OleFileIO(path)
    try:
        word = ole.openstream("WordDocument").read()
        if len(word) < 0x1A2 + 8 or struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
            raise DocError("Unsupported Word file (older than Word 97).")
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        if flags & 0x0100:
            raise DocError("This document is password-protected.")
        table_name = "1Table" if flags & 0x0200 else "0Table"
        table = ole.openstream(table_name).read()
        fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x01A2)
        clx = table[fc_clx:fc_clx + lcb_clx]
        pos = 0
        while pos < len(clx) and clx[pos] == 0x01:          # Prc entries (formatting) come first
            cb = struct.unpack_from("<H", clx, pos + 1)[0]
            pos += 3 + cb
        if pos >= len(clx) or clx[pos] != 0x02:
            raise DocError("Could not find the text in this document.")
        lcb = struct.unpack_from("<I", clx, pos + 1)[0]
        plc = clx[pos + 5:pos + 5 + lcb]
        n = (lcb - 4) // 12
        cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
        out = []
        for i in range(n):
            pcd = plc[(n + 1) * 4 + i * 8:(n + 1) * 4 + (i + 1) * 8]
            fc = struct.unpack_from("<I", pcd, 2)[0]
            count = cps[i + 1] - cps[i]
            if fc & 0x40000000:
                start = (fc & 0x3FFFFFFF) // 2
                out.append(word[start:start + count].decode("cp1252", errors="replace"))
            else:
                start = fc & 0x3FFFFFFF
                out.append(word[start:start + 2 * count].decode("utf-16-le", errors="replace"))
        text = "".join(out)
    finally:
        ole.close()
    return _clean_fields(text)


def _clean_fields(text: str) -> str:
    """Keep field results (\\x14 ... \\x15), drop field codes (\\x13 ... \\x14), and drop
    object placeholders."""
    out, depth, in_code = [], 0, []
    for ch in text:
        if ch == "\x13":
            depth += 1
            in_code.append(True)
        elif ch == "\x14":
            if in_code:
                in_code[-1] = False
        elif ch == "\x15":
            if in_code:
                in_code.pop()
            depth = max(0, depth - 1)
        elif in_code and in_code[-1]:
            continue
        elif ch in "\x01\x08\x02\x05":
            continue
        else:
            out.append(ch)
    return "".join(out)
