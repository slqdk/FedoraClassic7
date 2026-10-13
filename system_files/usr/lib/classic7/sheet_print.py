"""Printing for Sheet: pages laid out like Excel's (print area, fit to pages, repeated title
rows, header and footer), drawn by a hidden grid so they look exactly like the screen."""
from __future__ import annotations

import datetime as dt
import os

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPainter
from PySide6.QtPrintSupport import QPrinter

from sheet_model import Workbook, Worksheet

PAPERS = {"A4": QPageSize.A4, "A3": QPageSize.A3, "A5": QPageSize.A5, "Letter": QPageSize.Letter,
          "Legal": QPageSize.Legal}


def setup_printer(printer: QPrinter, ws: Worksheet):
    p = ws.page
    printer.setPageSize(QPageSize(PAPERS.get(p.paper, QPageSize.A4)))
    printer.setPageOrientation(QPageLayout.Landscape if p.orientation == "landscape" else QPageLayout.Portrait)
    left, right, top, bottom = p.margins
    printer.setPageMargins(QMarginsF(left * 25.4, top * 25.4, right * 25.4, bottom * 25.4), QPageLayout.Millimeter)


def print_area(ws: Worksheet, selection=None):
    if selection:
        return selection
    if ws.page.print_area:
        return ws.page.print_area
    used = ws.used_range()
    if not used:
        return None
    r2, c2 = used[2], used[3]
    for ch in ws.charts:
        r2, c2 = max(r2, ch.anchor[2]), max(c2, ch.anchor[3])
    return 0, 0, r2, c2


def pages_for(grid, ws: Worksheet, area, page_w: float, page_h: float):
    """Split the area into pages: lists of (row range, column range), down then over."""
    ax, ay = grid.axes()
    r1, c1, r2, c2 = area
    title_h = 0.0
    if ws.page.title_rows:
        a, b = ws.page.title_rows
        title_h = sum(ay.size(r) for r in range(a, b + 1))

    def split(start, end, size_of, limit):
        out, cur, acc = [], start, 0.0
        for i in range(start, end + 1):
            s = size_of(i)
            if acc + s > limit and i > cur:
                out.append((cur, i - 1))
                cur, acc = i, 0.0
            acc += s
        out.append((cur, end))
        return out
    col_pages = split(c1, c2, ax.size, page_w)
    row_pages = split(r1, r2, ay.size, max(page_h - title_h, page_h * 0.3))
    pages = []
    if ws.page.order == "overThenDown":
        for rp in row_pages:
            for cp in col_pages:
                pages.append((rp, cp))
    else:
        for cp in col_pages:
            for rp in row_pages:
                pages.append((rp, cp))
    return pages


def render(wb: Workbook, printer, sheets: list[Worksheet], selection=None, file_name: str = "") -> int:
    from sheet_grid import SheetGrid
    painter = QPainter()
    if not painter.begin(printer):
        return 0
    first = True
    count = 0
    dpi = printer.resolution()
    for ws in sheets:
        area = print_area(ws, selection if ws is wb.ws else None)
        if not area:
            continue
        old_active, old_zoom, old_freeze = wb.active, ws.zoom, ws.freeze
        wb.active = wb.sheets.index(ws)
        page_rect = printer.pageLayout().paintRectPixels(dpi)
        px_per_screen = dpi / 96.0
        # header/footer space
        hf = 0.35 * dpi
        avail_w = page_rect.width() / px_per_screen
        avail_h = (page_rect.height() - 2 * hf) / px_per_screen
        grid = SheetGrid(wb)
        grid.printing = True
        try:
            ws.freeze = None
            ws.zoom = 100
            grid._axes = None
            zoom = ws.page.scale / 100.0
            if ws.page.fit_width or ws.page.fit_height:
                ax, ay = grid.axes()
                total_w = ax.pos(area[3] + 1) - ax.pos(area[1])
                total_h = ay.pos(area[2] + 1) - ay.pos(area[0])
                zw = (avail_w * ws.page.fit_width) / total_w if ws.page.fit_width else 10
                zh = (avail_h * ws.page.fit_height) / total_h if ws.page.fit_height else 10
                zoom = max(0.1, min(1.0, zw, zh))
            ws.zoom = int(round(zoom * 100)) or 100
            grid._axes = None
            pages = pages_for(grid, ws, area, avail_w, avail_h)
            total = len(pages)
            for n, ((pr1, pr2), (pc1, pc2)) in enumerate(pages, start=1):
                if not first:
                    printer.newPage()
                first = False
                count += 1
                ax, ay = grid.axes()
                w = ax.pos(pc2 + 1) - ax.pos(pc1) + grid.header_w + 1
                tr = ws.page.title_rows
                title_h = 0
                if tr and pr1 > tr[1]:
                    title_h = ay.pos(tr[1] + 1) - ay.pos(tr[0])
                h = ay.pos(pr2 + 1) - ay.pos(pr1) + grid.header_h + title_h + 1
                grid.resize(int(w) + 2, int(h) + 2)
                grid.viewport().resize(int(w) + 2, int(h) + 2)
                grid.print_rows = (pr1, pr2, tr if title_h else None)
                grid.print_cols = (pc1, pc2)
                painter.save()
                x0 = page_rect.left() if not ws.page.center_h else page_rect.left() + max(
                    0, (page_rect.width() - w * px_per_screen) / 2)
                y0 = page_rect.top() + hf if not ws.page.center_v else page_rect.top() + hf + max(
                    0, (page_rect.height() - 2 * hf - h * px_per_screen) / 2)
                painter.translate(x0 - page_rect.left(), y0 - page_rect.top())
                painter.scale(px_per_screen, px_per_screen)
                grid.paint_page(painter)
                painter.restore()
                _header_footer(painter, page_rect, hf, ws, n, total, file_name, dpi)
        finally:
            ws.zoom, ws.freeze = old_zoom, old_freeze
            wb.active = old_active
            grid.deleteLater()
    painter.end()
    return count


def _expand(text: str, ws, n, total, file_name) -> str:
    return (text.replace("&P", str(n)).replace("&N", str(total)).replace("&A", ws.name)
            .replace("&F", os.path.basename(file_name) or "Book").replace("&D", dt.date.today().strftime("%d-%m-%Y"))
            .replace("&T", dt.datetime.now().strftime("%H:%M")).replace("&&", "&"))


def _header_footer(painter, page_rect, hf, ws, n, total, file_name, dpi):
    f = QFont("Calibri")
    f.setPointSizeF(10)
    painter.save()
    painter.setFont(f)
    if ws.page.header:
        painter.drawText(QRectF(page_rect.left(), page_rect.top(), page_rect.width(), hf),
                         Qt.AlignHCenter | Qt.AlignTop, _expand(ws.page.header, ws, n, total, file_name))
    if ws.page.footer:
        painter.drawText(QRectF(page_rect.left(), page_rect.bottom() - hf, page_rect.width(), hf),
                         Qt.AlignHCenter | Qt.AlignBottom, _expand(ws.page.footer, ws, n, total, file_name))
    painter.restore()


def export_pdf(wb: Workbook, path: str, sheets=None, selection=None) -> int:
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    sheets = sheets or [wb.ws]
    setup_printer(printer, sheets[0])
    return render(wb, printer, sheets, selection, wb.path or "")

