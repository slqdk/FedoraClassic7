"""Write: the page view. A QTextEdit whose document is laid out on real pages.

Qt's document layout paginates by itself once the document has a page size with a height:
lines never fall into the top/bottom margins. This widget sets that page size, centres the
page column, paints white pages with grey gaps behind the text, and draws the header and
footer (with page numbers) in the margins. Printing and PDF export use the same pages.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QPageLayout, QPageSize, QPainter, QPalette, QPen, QTextDocument,
                           QTextFrameFormat, QTextOption)
from PySide6.QtWidgets import QStyle, QTextEdit

PX_PER_MM = 96 / 25.4          # documents are laid out at 96 dpi, like Word at 100 %

PAPER = {                      # name: (width mm, height mm)
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "A5": (148.0, 210.0),
    "A3": (297.0, 420.0),
}
MARGINS = {                    # name: (top, bottom, left, right) mm, Word 2007's presets
    "Normal": (25.4, 25.4, 31.75, 31.75),
    "Narrow": (12.7, 12.7, 12.7, 12.7),
    "Moderate": (25.4, 25.4, 19.05, 19.05),
    "Wide": (25.4, 25.4, 50.8, 50.8),
    "Office 2003 Default": (25.4, 25.4, 31.75, 31.75),
}
GAP = 14                       # grey gap between pages on screen (px)


@dataclass
class PageSetup:
    paper: str = "A4"
    landscape: bool = False
    top: float = 25.4          # margins in mm
    bottom: float = 25.4
    left: float = 31.75
    right: float = 31.75
    header: str = ""           # "{page}" and "{pages}" are replaced
    footer: str = ""
    header_distance: float = 12.5   # mm from the page edge
    footer_distance: float = 12.5
    custom_size: tuple[float, float] | None = field(default=None)   # mm, from imported files

    @property
    def size_mm(self) -> tuple[float, float]:
        w, h = self.custom_size or PAPER.get(self.paper, PAPER["A4"])
        return (h, w) if self.landscape else (w, h)

    @property
    def size_px(self) -> QSizeF:
        w, h = self.size_mm
        return QSizeF(round(w * PX_PER_MM), round(h * PX_PER_MM))


class PageEdit(QTextEdit):
    """Rich text editor showing the document as pages ("Print Layout") or as one long
    column ("Draft")."""

    pageChanged = Signal(int, int)       # current page, page count

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup = PageSetup()
        self.draft = False
        self.setLineWrapMode(QTextEdit.NoWrap)      # we control the width via the page size
        self.setAcceptRichText(True)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)       # like Word
        pal = self.viewport().palette()
        pal.setColor(QPalette.Base, QColor("#9AA6B8"))    # Word 2007-like blue-grey around pages
        self.viewport().setPalette(pal)
        self.setAutoFillBackground(True)
        pal2 = self.palette()
        pal2.setColor(QPalette.Window, QColor("#9AA6B8"))
        pal2.setColor(QPalette.Base, QColor("#9AA6B8"))
        self.setPalette(pal2)
        self.document().documentLayout().documentSizeChanged.connect(self._emit_page)
        self.cursorPositionChanged.connect(self._emit_page)
        self.apply_setup()

    # ---- page setup ------------------------------------------------------------------------
    def setDocument(self, doc: QTextDocument):
        super().setDocument(doc)
        doc.documentLayout().documentSizeChanged.connect(self._emit_page)
        self.apply_setup()

    def apply_setup(self, setup: PageSetup | None = None):
        if setup is not None:
            self.setup = setup
        doc = self.document()
        was_modified = doc.isModified()
        size = self.setup.size_px
        opt = doc.defaultTextOption()
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        doc.setPageSize(QSizeF(size.width(), -1 if self.draft else size.height()))
        fmt = doc.rootFrame().frameFormat()
        fmt.setTopMargin(self.setup.top * PX_PER_MM)
        fmt.setBottomMargin(self.setup.bottom * PX_PER_MM)
        fmt.setLeftMargin(self.setup.left * PX_PER_MM)
        fmt.setRightMargin(self.setup.right * PX_PER_MM)
        doc.rootFrame().setFrameFormat(fmt)
        doc.setModified(was_modified)
        self._center()
        self.viewport().update()
        self._emit_page()

    def set_draft(self, draft: bool):
        self.draft = draft
        self.apply_setup()

    def page_height(self) -> float:
        return self.setup.size_px.height()

    def page_count(self) -> int:
        return max(1, self.document().pageCount()) if not self.draft else 1

    def current_page(self) -> int:
        if self.draft:
            return 1
        y = self.cursorRect().center().y() + self.verticalScrollBar().value()
        return min(self.page_count(), int(y // self.page_height()) + 1)

    def _emit_page(self, *_):
        self.pageChanged.emit(self.current_page(), self.page_count())

    def _center(self):
        width = self.setup.size_px.width()
        free = max(0, self.width() - width - self.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self) - 4)
        side = int(free // 2)
        self.setViewportMargins(side, GAP if not self.draft else 0, side, 0)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._center()
        # QTextEdit resets the page size when it relayouts; put ours back
        size = self.setup.size_px
        want = QSizeF(size.width(), -1 if self.draft else size.height())
        if self.document().pageSize() != want:
            self.document().setPageSize(want)

    # ---- painting --------------------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self.viewport())
        dy = -self.verticalScrollBar().value()
        dx = -self.horizontalScrollBar().value()
        size = self.setup.size_px
        W, H = size.width(), size.height()
        if self.draft:
            p.fillRect(QRectF(dx, 0, W, self.viewport().height()), Qt.white)
        else:
            first = max(0, int(-dy // H))
            last = min(self.page_count() - 1, int((-dy + self.viewport().height()) // H) + 1)
            for i in range(first, last + 1):
                top = i * H + dy
                page = QRectF(dx, top + (GAP / 2 if i else 0), W, H - (GAP / 2 if i else 0) - GAP / 2)
                p.fillRect(page, Qt.white)
                p.setPen(QPen(QColor("#6E7B90"), 1))
                p.drawRect(page.adjusted(0, 0, -1, -1))
                self._paint_header_footer(p, QRectF(dx, i * H + dy, W, H), i + 1)
        p.end()
        super().paintEvent(e)

    def _paint_header_footer(self, p: QPainter, page: QRectF, number: int):
        paint_header_footer(p, self.setup, self.document().defaultFont(), page, number, self.page_count())


def paint_header_footer(p: QPainter, s: PageSetup, base_font: QFont, page: QRectF, number: int, total: int):
    font = QFont(base_font)
    font.setPointSizeF(max(8.0, font.pointSizeF() - 1))
    p.setFont(font)
    p.setPen(QColor("#404040"))
    left = page.left() + s.left * PX_PER_MM
    width = page.width() - (s.left + s.right) * PX_PER_MM
    if s.header:
        text = s.header.replace("{page}", str(number)).replace("{pages}", str(total))
        p.drawText(QRectF(left, page.top() + s.header_distance * PX_PER_MM, width, 20),
                   Qt.AlignHCenter | Qt.AlignTop, text)
    if s.footer:
        text = s.footer.replace("{page}", str(number)).replace("{pages}", str(total))
        p.drawText(QRectF(left, page.bottom() - s.footer_distance * PX_PER_MM - 20, width, 20),
                   Qt.AlignHCenter | Qt.AlignBottom, text)


def print_document(doc: QTextDocument, setup: PageSetup, printer) -> None:
    """Paint the pages exactly as laid out on screen onto a QPrinter (paper or PDF)."""
    w_mm, h_mm = setup.size_mm
    printer.setPageSize(QPageSize(QSizeF(w_mm, h_mm), QPageSize.Millimeter, "", QPageSize.ExactMatch))
    printer.setPageOrientation(QPageLayout.Portrait)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
    printer.setFullPage(True)

    work = doc.clone()
    size = setup.size_px
    work.setPageSize(size)
    fmt = work.rootFrame().frameFormat()
    fmt.setTopMargin(setup.top * PX_PER_MM)
    fmt.setBottomMargin(setup.bottom * PX_PER_MM)
    fmt.setLeftMargin(setup.left * PX_PER_MM)
    fmt.setRightMargin(setup.right * PX_PER_MM)
    work.rootFrame().setFrameFormat(fmt)
    opt = work.defaultTextOption()
    opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    work.setDefaultTextOption(opt)
    pages = max(1, work.pageCount())

    from PySide6.QtPrintSupport import QPrinter
    painter = QPainter(printer)
    rect = printer.paperRect(QPrinter.DevicePixel)
    scale = rect.width() / size.width()
    painter.scale(scale, scale)
    for i in range(pages):
        if i:
            printer.newPage()
        painter.save()
        painter.translate(0, -i * size.height())
        clip = QRectF(0, i * size.height(), size.width(), size.height())
        painter.setClipRect(clip)
        work.drawContents(painter, clip)
        painter.restore()
        paint_header_footer(painter, setup, work.defaultFont(), QRectF(0, 0, size.width(), size.height()), i + 1, pages)
    painter.end()
