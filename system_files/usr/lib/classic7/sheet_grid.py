"""The worksheet grid of Sheet: column and row headers, cells with their formats, merged
cells, frozen panes, the selection with its fill handle, editing in the cell, pointing at
cells while typing a formula, charts and pictures floating over the cells."""
from __future__ import annotations

import bisect
import re

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QLinearGradient, QPainter,
                           QPen, QPixmap, QPolygon)
from PySide6.QtWidgets import QAbstractScrollArea, QLineEdit, QToolTip

import sheet_formula as F
import sheet_numfmt as NF
import sheet_ops as OPS
from sheet_model import Workbook, Worksheet
from sheet_ref import MAX_COLS, MAX_ROWS, cell_name, col_name, cycle_reference, range_name

HEADER_BG1 = QColor("#f4f8fd")
HEADER_BG2 = QColor("#d9e5f3")
HEADER_SEL1 = QColor("#f9d99f")
HEADER_SEL2 = QColor("#f1c15f")
HEADER_LINE = QColor("#9eb6ce")
HEADER_TEXT = QColor("#1e395b")
GRID = QColor("#d0d7e5")
SELECT_FILL = QColor(102, 130, 189, 55)
FREEZE_LINE = QColor("#000000")
REF_COLORS = ["#0000ff", "#008000", "#9900cc", "#800000", "#00cc33", "#cc6600", "#cc0099"]

MAX_DIGIT_PX = 7.0      # Calibri 11 at 96 dpi: Excel's unit for column widths


class Axis:
    """Positions of rows or columns with a default size, custom sizes and hidden ones."""

    def __init__(self, default: float, sizes: dict[int, float], hidden: set[int], count: int):
        self.default = default
        self.count = count
        custom = {}
        for i, s in sizes.items():
            custom[i] = s
        for i in hidden:
            custom[i] = 0.0
        self.keys = sorted(custom)
        self.deltas = []
        acc = 0.0
        for k in self.keys:
            acc += custom[k] - default
            self.deltas.append(acc)
        self.custom = custom

    def size(self, i: int) -> float:
        return self.custom.get(i, self.default)

    def pos(self, i: int) -> float:
        """Start of item i (sum of the sizes before it)."""
        j = bisect.bisect_left(self.keys, i)
        return i * self.default + (self.deltas[j - 1] if j else 0.0)

    def index_at(self, p: float) -> int:
        lo, hi = 0, self.count - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.pos(mid) <= p:
                lo = mid
            else:
                hi = mid - 1
        return lo

    def next_visible(self, i: int, step: int = 1) -> int:
        j = i
        while 0 <= j < self.count and self.size(j) == 0:
            j += step
        return max(0, min(self.count - 1, j))


class Occupied:
    """`(r, c) in occupied`: the cell has a value (looked up only where text is drawn)."""

    def __init__(self, cells):
        self.cells = cells

    def __contains__(self, key):
        cell = self.cells.get(key)
        return cell is not None and not cell.empty


class RefLineEdit(QLineEdit):
    """A line edit where F4 toggles $ in the reference at the cursor, like Excel."""

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F4 and not e.modifiers():
            text, cur = cycle_reference(self.text(), self.cursorPosition())
            if text != self.text():
                self.setText(text)
                self.setCursorPosition(cur)
                self.textEdited.emit(text)
            return
        super().keyPressEvent(e)


class CellEditor(RefLineEdit):
    """The text box over the cell while typing."""
    commit = Signal(int, int)        # how to move after: (drow, dcol)
    cancel = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setFrame(False)
        self.enter_mode = True      # typing started the edit: arrow keys leave the cell
        self.setStyleSheet("QLineEdit { background: white; border: 2px solid #000000; padding: 0 1px; }")

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if e.modifiers() & Qt.AltModifier:
                self.insert("\n")
                return
            self.commit.emit(-1 if e.modifiers() & Qt.ShiftModifier else 1, 0)
            return
        if k == Qt.Key_Tab:
            self.commit.emit(0, 1)
            return
        if k == Qt.Key_Backtab:
            self.commit.emit(0, -1)
            return
        if k == Qt.Key_Escape:
            self.cancel.emit()
            return
        if self.enter_mode and k in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right) \
                and not self.text().startswith("="):
            d = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0), Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1)}[k]
            self.commit.emit(*d)
            return
        if k == Qt.Key_F2:
            self.enter_mode = not self.enter_mode
            return
        super().keyPressEvent(e)

    def event(self, e):
        if e.type() == QEvent.KeyPress and e.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(e)
            return True
        return super().event(e)


class SheetGrid(QAbstractScrollArea):
    selectionChanged = Signal()
    editTextChanged = Signal(str)
    editingChanged = Signal(bool)
    contentChanged = Signal()
    contextMenu = Signal(QPoint, str)          # global position, "cells" / "rows" / "cols" / "object"
    objectActivated = Signal(object)           # a chart was double-clicked
    filterClicked = Signal(int, QPoint)        # column, global position
    message = Signal(str)
    zoomChanged = Signal(int)

    def __init__(self, wb: Workbook, parent=None):
        super().__init__(parent)
        self.wb = wb
        self.setFocusPolicy(Qt.StrongFocus)
        self.viewport().setMouseTracking(True)
        self.viewport().setCursor(self._plus_cursor())
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.editor = CellEditor(self.viewport())
        self.editor.hide()
        self.editor.commit.connect(self._commit_move)
        self.editor.cancel.connect(self.cancel_edit)
        self.editor.textEdited.connect(self._editor_changed)
        self.editing = False
        self.drag = None                 # current mouse drag
        self.copy_range = None           # marching ants around copied cells
        self.ants = 0
        self.ant_timer = QTimer(self)
        self.ant_timer.timeout.connect(self._ants)
        self.scroll_timer = QTimer(self)
        self.scroll_timer.timeout.connect(self._autoscroll)
        self.selected_object = None
        self.point_ref = None           # (start, end) of the reference typed by pointing
        self.formula_refs = []
        self.horizontalScrollBar().valueChanged.connect(self._scrolled)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self._axes = None
        self._img_cache = {}
        self.printing = False
        self.show_formulas = False
        self.print_rows = None          # (first row, last row, title rows or None) of the page
        self.print_cols = None

    # ---- the sheet -------------------------------------------------------------------------------
    @property
    def ws(self) -> Worksheet:
        return self.wb.ws

    @property
    def z(self) -> float:
        return self.ws.zoom / 100.0

    def set_zoom(self, pct: int):
        pct = max(10, min(400, pct))
        if pct != self.ws.zoom:
            self.ws.zoom = pct
            self.invalidate()
            self.zoomChanged.emit(pct)

    def invalidate(self):
        self._axes = None
        self._update_scrollbars()
        self.viewport().update()

    def axes(self) -> tuple[Axis, Axis]:
        if self._axes is None:
            ws = self.ws
            z = self.z
            cw = {c: self._col_px(w) for c, w in ws.col_widths.items()}
            rh = {r: h * 96 / 72 * z for r, h in ws.row_heights.items()}
            self._axes = (Axis(self._col_px(ws.default_width), cw, ws.hidden_cols, MAX_COLS),
                          Axis(ws.default_height * 96 / 72 * z, rh, ws.hidden_rows, MAX_ROWS))
        return self._axes

    def _col_px(self, w: float) -> float:
        # Show Formulas doubles the columns, like Excel, so formulas have room
        k = 2 if self.show_formulas else 1
        return round(w * MAX_DIGIT_PX + 5) * self.z * k if w > 0 else 0.0

    def _show_headers(self) -> bool:
        return self.ws.page.headings if self.printing else self.ws.show_headers

    @property
    def header_w(self) -> int:
        if not self._show_headers():
            return 0
        rows = max(self.ws.extent()[0], self.top_row() + 60) + 1
        f = self._header_font()
        return QFontMetrics(f).horizontalAdvance(str(rows)) + int(12 * self.z) + 4

    @property
    def header_h(self) -> int:
        return int(20 * self.z) if self._show_headers() else 0

    def _header_font(self) -> QFont:
        f = QFont("Calibri")
        f.setPixelSize(max(8, int(14 * self.z)))
        return f

    def top_row(self) -> int:
        return self.verticalScrollBar().value()

    def left_col(self) -> int:
        return self.horizontalScrollBar().value()

    def frozen(self) -> tuple[int, int]:
        return self.ws.freeze or (0, 0)

    def _update_scrollbars(self):
        ws = self.ws
        rows, cols = ws.extent()
        vis_r = int(self.viewport().height() / max(1, self.axes()[1].default)) + 1
        vis_c = int(self.viewport().width() / max(1, self.axes()[0].default)) + 1
        vb, hb = self.verticalScrollBar(), self.horizontalScrollBar()
        fr, fc = self.frozen()
        vb.setRange(fr, max(rows + vis_r, ws.active[0] + vis_r, vb.value(), 100))
        hb.setRange(fc, max(cols + vis_c // 2, ws.active[1] + vis_c, hb.value(), 26))
        vb.setPageStep(max(1, vis_r - 2))
        hb.setPageStep(max(1, vis_c - 1))

    def _scrolled(self):
        if self.editing:
            self._place_editor()
        self.viewport().update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._update_scrollbars()

    # ---- geometry ----------------------------------------------------------------------------------
    def col_x(self, c: int) -> float:
        """x of a column's left edge in the viewport (frozen columns stay put)."""
        ax, _ = self.axes()
        if self.printing and self.print_cols:
            return self.header_w + ax.pos(c) - ax.pos(self.print_cols[0])
        fr, fc = self.frozen()
        if c < fc:
            return self.header_w + ax.pos(c)
        return self.header_w + ax.pos(fc) + ax.pos(c) - ax.pos(max(self.left_col(), fc))

    def row_y(self, r: int) -> float:
        _, ay = self.axes()
        if self.printing and self.print_rows:
            r1, _r2, titles = self.print_rows
            th = 0.0
            if titles:
                th = ay.pos(titles[1] + 1) - ay.pos(titles[0])
                if titles[0] <= r <= titles[1]:
                    return self.header_h + ay.pos(r) - ay.pos(titles[0])
            return self.header_h + th + ay.pos(r) - ay.pos(r1)
        fr, fc = self.frozen()
        if r < fr:
            return self.header_h + ay.pos(r)
        return self.header_h + ay.pos(fr) + ay.pos(r) - ay.pos(max(self.top_row(), fr))

    def cell_rect(self, r: int, c: int, merged=True) -> QRectF:
        if merged:
            m = self.ws.merge_at(r, c)
            if m:
                return self.range_rect(*m)
        ax, ay = self.axes()
        return QRectF(self.col_x(c), self.row_y(r), ax.size(c), ay.size(r))

    def range_rect(self, r1, c1, r2, c2) -> QRectF:
        ax, ay = self.axes()
        x1, y1 = self.col_x(c1), self.row_y(r1)
        x2 = self.col_x(c2) + ax.size(c2)
        y2 = self.row_y(r2) + ay.size(r2)
        return QRectF(x1, y1, x2 - x1, y2 - y1)

    def cell_at(self, pos) -> tuple[int, int]:
        ax, ay = self.axes()
        fr, fc = self.frozen()
        x, y = pos.x() - self.header_w, pos.y() - self.header_h
        if fc and x < ax.pos(fc):
            c = ax.index_at(max(0, x))
        else:
            c = ax.index_at(max(0, x - ax.pos(fc) + ax.pos(max(self.left_col(), fc))))
        if fr and y < ay.pos(fr):
            r = ay.index_at(max(0, y))
        else:
            r = ay.index_at(max(0, y - ay.pos(fr) + ay.pos(max(self.top_row(), fr))))
        return r, c

    def visible_rows(self):
        if self.printing and self.print_rows:
            r1, r2, titles = self.print_rows
            return (list(range(titles[0], titles[1] + 1)) if titles else []) + list(range(r1, r2 + 1))
        _, ay = self.axes()
        fr, _ = self.frozen()
        out = list(range(0, fr))
        r = max(self.top_row(), fr)
        h = self.viewport().height()
        while r < MAX_ROWS and self.row_y(r) < h:
            out.append(r)
            r += 1
        return out

    def visible_cols(self):
        if self.printing and self.print_cols:
            return list(range(self.print_cols[0], self.print_cols[1] + 1))
        _, _ = self.axes()
        _, fc = self.frozen()
        out = list(range(0, fc))
        c = max(self.left_col(), fc)
        w = self.viewport().width()
        while c < MAX_COLS and self.col_x(c) < w:
            out.append(c)
            c += 1
        return out

    def ensure_visible(self, r: int, c: int):
        ax, ay = self.axes()
        fr, fc = self.frozen()
        vb, hb = self.verticalScrollBar(), self.horizontalScrollBar()
        if r >= fr:
            if r < vb.value():
                vb.setValue(r)
            else:
                while self.row_y(r) + ay.size(r) > self.viewport().height() and vb.value() < r:
                    if vb.value() >= vb.maximum():
                        vb.setMaximum(vb.maximum() + 50)
                    vb.setValue(vb.value() + 1)
        if c >= fc:
            if c < hb.value():
                hb.setValue(c)
            else:
                while self.col_x(c) + ax.size(c) > self.viewport().width() and hb.value() < c:
                    if hb.value() >= hb.maximum():
                        hb.setMaximum(hb.maximum() + 20)
                    hb.setValue(hb.value() + 1)

    # ---- selection ---------------------------------------------------------------------------------
    @property
    def active(self) -> tuple[int, int]:
        return self.ws.active

    @property
    def ranges(self) -> list[tuple[int, int, int, int]]:
        return self.ws.selection

    def selection_range(self) -> tuple[int, int, int, int]:
        return self.ranges[-1]

    def select(self, r: int, c: int, extend=False, add=False):
        r = max(0, min(MAX_ROWS - 1, r))
        c = max(0, min(MAX_COLS - 1, c))
        ws = self.ws
        if extend:
            ar, ac = self._anchor
            rng = (min(ar, r), min(ac, c), max(ar, r), max(ac, c))
            rng = self._grow_for_merges(rng)
            ws.selection = ws.selection[:-1] + [rng]
            self._extent_cell = (r, c)
        else:
            m = ws.merge_at(r, c)
            rng = m if m else (r, c, r, c)
            if m:
                r, c = m[0], m[1]
            ws.selection = (ws.selection + [rng]) if add else [rng]
            ws.active = (r, c)
            self._anchor = (r, c)
            self._extent_cell = (r, c)
        self.ensure_visible(*(self._extent_cell if extend else (r, c)))
        self.viewport().update()
        self.selectionChanged.emit()

    _anchor = (0, 0)
    _extent_cell = (0, 0)

    def _grow_for_merges(self, rng):
        r1, c1, r2, c2 = rng
        changed = True
        while changed:
            changed = False
            for m in self.ws.merges:
                if m[0] <= r2 and m[2] >= r1 and m[1] <= c2 and m[3] >= c1:
                    n = (min(r1, m[0]), min(c1, m[1]), max(r2, m[2]), max(c2, m[3]))
                    if n != (r1, c1, r2, c2):
                        r1, c1, r2, c2 = n
                        changed = True
        return r1, c1, r2, c2

    def select_range(self, rng, active=None):
        self.ws.selection = [rng]
        self.ws.active = active or (rng[0], rng[1])
        self._anchor = self.ws.active
        self._extent_cell = (rng[2], rng[3])
        self.ensure_visible(*self.ws.active)
        self.viewport().update()
        self.selectionChanged.emit()

    def move_active(self, dr: int, dc: int, extend=False):
        """Arrow keys, Enter, Tab: move (inside a multi-cell selection, Enter and Tab cycle)."""
        ax, ay = self.axes()
        if extend:
            r, c = self._extent_cell
        else:
            r, c = self.active
            m = self.ws.merge_at(r, c)
            if m:
                r = m[2] if dr > 0 else m[0] if dr < 0 else r
                c = m[3] if dc > 0 else m[1] if dc < 0 else c
        r = ay.next_visible(max(0, min(MAX_ROWS - 1, r + dr)), 1 if dr >= 0 else -1)
        c = ax.next_visible(max(0, min(MAX_COLS - 1, c + dc)), 1 if dc >= 0 else -1)
        self.select(r, c, extend=extend)

    def jump(self, dr: int, dc: int, extend=False):
        """Ctrl+arrow: to the edge of the data."""
        ws = self.ws
        r, c = self._extent_cell if extend else self.active

        def filled(rr, cc):
            cell = ws.cells.get((rr, cc))
            return cell is not None and not cell.empty
        nr, nc = r + dr, c + dc
        if not (0 <= nr < MAX_ROWS and 0 <= nc < MAX_COLS):
            return
        if filled(r, c) and filled(nr, nc):
            while 0 <= nr + dr < MAX_ROWS and 0 <= nc + dc < MAX_COLS and filled(nr + dr, nc + dc):
                nr, nc = nr + dr, nc + dc
        else:
            limit_r, limit_c = ws.extent()
            while not filled(nr, nc):
                if (dr > 0 and nr >= limit_r) or (dc > 0 and nc >= limit_c) or nr + dr < 0 or nc + dc < 0:
                    nr = MAX_ROWS - 1 if dr > 0 and nr >= limit_r else nr
                    nc = MAX_COLS - 1 if dc > 0 and nc >= limit_c else nc
                    if dr < 0:
                        nr = max(0, nr)
                    if dc < 0:
                        nc = max(0, nc)
                    break
                nr, nc = nr + dr, nc + dc
        self.select(max(0, nr), max(0, nc), extend=extend)

    # ---- painting ------------------------------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self.viewport())
        self._paint_all(p)
        p.end()

    def paint_page(self, p: QPainter):
        """Printing: draw this page's cells with the painter (no selection, no frozen lines)."""
        self._paint_all(p)

    def _paint_all(self, p: QPainter):
        if not self.printing:
            p.fillRect(self.viewport().rect(), QColor("#ffffff"))
        rows = self.visible_rows()
        cols = self.visible_cols()
        if rows and cols:
            self._paint_cells(p, rows, cols)
            self._paint_objects(p)
            if not self.printing:
                self._paint_selection(p)
                self._paint_formula_refs(p)
                self._paint_freeze(p)
        self._paint_headers(p, rows, cols)

    def _style_font(self, st) -> QFont:
        f = QFont(st.font)
        f.setPixelSize(max(1, round(st.size * 96 / 72 * self.z)))
        f.setBold(st.bold)
        f.setItalic(st.italic)
        f.setUnderline(st.underline)
        f.setStrikeOut(st.strike)
        return f

    def _paint_cells(self, p: QPainter, rows, cols):
        ws, wb = self.ws, self.wb
        ax, ay = self.axes()
        right_edge = self.viewport().width()
        bottom_edge = self.viewport().height()
        fr, fc = self.frozen()
        cond = CondFormats(wb, ws) if ws.cond else None
        p.save()
        p.setClipRect(QRect(self.header_w, self.header_h, right_edge, bottom_edge))
        # gridlines
        if (ws.page.gridlines if self.printing else ws.show_grid):
            p.setPen(QPen(GRID, 1))
            for c in cols:
                x = int(self.col_x(c) + ax.size(c)) - 1
                if ax.size(c) > 0:
                    p.drawLine(x, self.header_h, x, bottom_edge)
            for r in rows:
                y = int(self.row_y(r) + ay.size(r)) - 1
                if ay.size(r) > 0:
                    p.drawLine(self.header_w, y, right_edge, y)
        merges = [m for m in ws.merges if m[2] >= rows[0] and m[3] >= cols[0]]
        covered = set()
        for m in merges:
            for r in range(m[0], m[2] + 1):
                for c in range(m[1], m[3] + 1):
                    if (r, c) != (m[0], m[1]):
                        covered.add((r, c))
        # fills
        filled_cells = []
        for r in rows:
            if ay.size(r) == 0:
                continue
            for c in cols:
                if ax.size(c) == 0 or (r, c) in covered:
                    continue
                st = ws.style_of(r, c)
                extra = cond.style_at(r, c) if cond else None
                fill = (extra.get("fill") if extra else None) or st.fill
                m = ws.merge_at(r, c) if merges else None
                rect = self.range_rect(*m) if m and (r, c) == (m[0], m[1]) else self.cell_rect(r, c, merged=False)
                if fill:
                    p.fillRect(rect, QColor(fill))
                elif m:
                    p.fillRect(rect.adjusted(0, 0, -1, -1), QColor("#ffffff"))
                if extra and extra.get("bar"):
                    frac, color = extra["bar"]
                    bar = QRectF(rect.left() + 2, rect.top() + 2, max(0, (rect.width() - 4) * frac), rect.height() - 5)
                    g = QLinearGradient(bar.left(), 0, bar.right(), 0)
                    g.setColorAt(0, QColor(color))
                    g.setColorAt(1, QColor("#ffffff"))
                    p.fillRect(bar, g)
                filled_cells.append((r, c, rect, st, extra))
        # text (with overflow into empty neighbours)
        occupied = Occupied(ws.cells)
        for r in rows:
            if ay.size(r) == 0:
                continue
            for c in self._text_cols(cols, r, occupied):
                if (r, c) in covered or ax.size(c) == 0:
                    continue
                cell = ws.cells.get((r, c))
                if cell is None or cell.empty:
                    continue
                self._paint_text(p, r, c, cell, occupied, cond, right_edge)
        # borders and comment marks
        for r, c, rect, st, extra in filled_cells:
            self._paint_borders(p, r, c, rect, st)
            if (r, c) in ws.comments and not self.printing:
                tri = QPolygon([QPoint(int(rect.right()) - 6, int(rect.top())), QPoint(int(rect.right()), int(rect.top())),
                                QPoint(int(rect.right()), int(rect.top()) + 6)])
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#ff0000"))
                p.drawPolygon(tri)
        # AutoFilter buttons
        if ws.autofilter and not self.printing:
            r1, c1, r2, c2 = ws.autofilter
            if r1 in rows:
                for c in range(c1, c2 + 1):
                    if c in cols:
                        self._paint_filter_button(p, r1, c, c in ws.filters and ws.filters[c] is not None)
        # validation drop-down on the active cell
        v = self._validation_at(*self.active)
        if v is not None and v.kind == "list" and not self.editing and not self.printing:
            rr = self.cell_rect(*self.active)
            self._paint_dropdown(p, QRectF(rr.right() + 1, rr.top(), 16 * self.z, rr.height()))
        p.restore()

    def _text_cols(self, cols, r, occupied):
        """Visible columns plus a few to the left whose text may run into view."""
        if not cols:
            return []
        extra = [c for c in range(max(0, cols[0] - 12), cols[0]) if (r, c) in occupied]
        return extra + list(cols)

    def _paint_text(self, p, r, c, cell, occupied, cond, right_edge):
        ws, wb = self.ws, self.wb
        ax, ay = self.axes()
        st = ws.style_of(r, c)
        extra = cond.style_at(r, c) if cond else None
        if self.show_formulas and cell is not None and cell.formula:
            text, color, value = cell.formula, None, cell.formula
        else:
            text, color = wb.display(ws, r, c)
            value = wb.value(ws.name, r, c)
        if text == "":
            return
        is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
        halign = st.halign
        if halign == "general":
            halign = "right" if is_num else ("center" if isinstance(value, (bool, F.XLError)) else "left")
        m = ws.merge_at(r, c) if ws.merges else None
        rect = self.range_rect(*m) if m else self.cell_rect(r, c, merged=False)
        font = self._style_font(st)
        if extra and extra.get("bold"):
            font.setBold(True)
        fm = QFontMetrics(font)
        pad = 2 * self.z + 1
        indent = st.indent * 9 * self.z
        tw = fm.horizontalAdvance(text)
        avail = rect.width() - 2 * pad - indent
        clip = QRectF(rect)
        if st.wrap or "\n" in text:
            flags = Qt.TextWordWrap
            draw = QRectF(rect.adjusted(pad + (indent if halign == "left" else 0), 1, -pad, -1))
        else:
            flags = Qt.TextSingleLine
            if tw > avail and is_num and not m:
                # numbers never spill over: General shows fewer digits, others show ####
                if st.numfmt == "General" and isinstance(value, float) and abs(value) >= 1:
                    shown = _shorter_general(value, fm, avail)
                    text = shown if shown else "#" * max(1, int(avail / max(1, fm.horizontalAdvance("#"))))
                else:
                    text = "#" * max(1, int(avail / max(1, fm.horizontalAdvance("#"))))
                tw = fm.horizontalAdvance(text)
            if tw > avail and not is_num and not m and not st.shrink:
                # run into empty neighbours
                if halign in ("left", "fill", "justify"):
                    c2 = c
                    while tw > clip.width() - 2 * pad and (r, c2 + 1) not in occupied and c2 + 1 < MAX_COLS \
                            and clip.right() < right_edge:
                        c2 += 1
                        clip.setRight(self.col_x(c2) + ax.size(c2))
                elif halign == "right":
                    c2 = c
                    while tw > clip.width() - 2 * pad and c2 - 1 >= 0 and (r, c2 - 1) not in occupied:
                        c2 -= 1
                        clip.setLeft(self.col_x(c2))
                elif halign in ("center", "centerContinuous"):
                    lc = rc = c
                    while tw > clip.width() - 2 * pad and ((r, rc + 1) not in occupied or (r, lc - 1) not in occupied):
                        if (r, rc + 1) not in occupied:
                            rc += 1
                            clip.setRight(self.col_x(rc) + ax.size(rc))
                        if lc - 1 >= 0 and (r, lc - 1) not in occupied:
                            lc -= 1
                            clip.setLeft(self.col_x(lc))
                        if lc == 0 and (r, rc + 1) in occupied:
                            break
            if st.shrink and tw > avail and tw > 0:
                font.setPixelSize(max(4, int(font.pixelSize() * avail / tw)))
            draw = QRectF(clip.adjusted(pad + (indent if halign == "left" else 0), 0,
                                        -pad - (indent if halign == "right" else 0), 0))
        h = {"left": Qt.AlignLeft, "right": Qt.AlignRight, "center": Qt.AlignHCenter,
             "centerContinuous": Qt.AlignHCenter, "justify": Qt.AlignJustify, "fill": Qt.AlignLeft}.get(halign, Qt.AlignLeft)
        v = {"top": Qt.AlignTop, "center": Qt.AlignVCenter}.get(st.valign, Qt.AlignBottom)
        if st.halign == "fill" and text:
            reps = max(1, int(draw.width() / max(1, fm.horizontalAdvance(text))))
            text = text * reps
        p.save()
        p.setClipRect(clip.intersected(QRectF(self.header_w, self.header_h, right_edge, self.viewport().height())))
        p.setFont(font)
        col = QColor((extra.get("color") if extra else None) or color or st.color)
        if (r, c) in ws.links and st.color == "#000000":
            col = QColor("#0000ff")
        p.setPen(col)
        if st.rotation and st.rotation not in (0, 255):
            angle = -st.rotation if st.rotation <= 90 else st.rotation - 90
            p.translate(draw.center())
            p.rotate(angle)
            p.drawText(QRectF(-draw.height() * 2, -draw.height() / 2, draw.height() * 4, draw.height()),
                       Qt.AlignCenter, text)
        else:
            p.drawText(draw.adjusted(0, 0, 0, -1), h | v | flags, text)
        p.restore()

    def _paint_borders(self, p, r, c, rect, st):
        for side in ("left", "right", "top", "bottom"):
            b = getattr(st, side)
            if not b.style:
                continue
            width = {"medium": 2, "thick": 3, "double": 3}.get(b.style, 1)
            pen = QPen(QColor(b.color), width)
            pen.setStyle({"dashed": Qt.DashLine, "dotted": Qt.DotLine, "hair": Qt.DotLine, "dashDot": Qt.DashDotLine,
                          "mediumDashed": Qt.DashLine, "dashDotDot": Qt.DashDotDotLine}.get(b.style, Qt.SolidLine))
            p.setPen(pen)
            x1, y1, x2, y2 = rect.left() - 1, rect.top() - 1, rect.right() - 1, rect.bottom() - 1
            if b.style == "double":
                pen.setWidth(1)
                p.setPen(pen)
                if side in ("top", "bottom"):
                    y = y1 if side == "top" else y2
                    p.drawLine(int(x1), int(y - 1), int(x2), int(y - 1))
                    p.drawLine(int(x1), int(y + 1), int(x2), int(y + 1))
                else:
                    x = x1 if side == "left" else x2
                    p.drawLine(int(x - 1), int(y1), int(x - 1), int(y2))
                    p.drawLine(int(x + 1), int(y1), int(x + 1), int(y2))
                continue
            if side == "left":
                p.drawLine(int(x1), int(y1), int(x1), int(y2))
            elif side == "right":
                p.drawLine(int(x2), int(y1), int(x2), int(y2))
            elif side == "top":
                p.drawLine(int(x1), int(y1), int(x2), int(y1))
            else:
                p.drawLine(int(x1), int(y2), int(x2), int(y2))

    def _paint_filter_button(self, p, r, c, active):
        rect = self.cell_rect(r, c, merged=False)
        s = min(rect.height() - 2, 16 * self.z)
        b = QRectF(rect.right() - s - 1, rect.bottom() - s - 1, s, s)
        g = QLinearGradient(0, b.top(), 0, b.bottom())
        g.setColorAt(0, QColor("#ffffff"))
        g.setColorAt(1, QColor("#e3e9f2"))
        p.fillRect(b, g)
        p.setPen(QColor("#8ea4c1"))
        p.drawRect(b.adjusted(0, 0, -1, -1))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#000000"))
        cx, cy = b.center().x(), b.center().y()
        if active:
            p.drawPolygon(QPolygon([QPoint(int(cx - 4), int(cy - 3)), QPoint(int(cx + 4), int(cy - 3)),
                                    QPoint(int(cx), int(cy + 1))]))
            p.drawRect(QRectF(cx - 1, cy, 2, 3))
        else:
            p.drawPolygon(QPolygon([QPoint(int(cx - 3), int(cy - 1)), QPoint(int(cx + 4), int(cy - 1)),
                                    QPoint(int(cx), int(cy + 3))]))

    def _paint_dropdown(self, p, b):
        g = QLinearGradient(0, b.top(), 0, b.bottom())
        g.setColorAt(0, QColor("#ffffff"))
        g.setColorAt(1, QColor("#dfe5ee"))
        p.fillRect(b, g)
        p.setPen(QColor("#8ea4c1"))
        p.drawRect(b.adjusted(0, 0, -1, -1))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#000000"))
        cx, cy = b.center().x(), b.center().y()
        p.drawPolygon(QPolygon([QPoint(int(cx - 3), int(cy - 1)), QPoint(int(cx + 4), int(cy - 1)),
                                QPoint(int(cx), int(cy + 3))]))

    def _paint_selection(self, p):
        ws = self.ws
        p.save()
        p.setClipRect(QRect(self.header_w, self.header_h, self.viewport().width(), self.viewport().height()))
        ar, ac = self.active
        active_rect = self.cell_rect(ar, ac)
        for rng in ws.selection:
            rect = self.range_rect(*self._clip_rng(rng))
            if rng[0] == rng[2] and rng[1] == rng[3] or ws.merge_at(rng[0], rng[1]) == rng:
                continue
            p.save()
            if len(ws.selection) == 1 or rng == ws.selection[-1]:
                clip_out = QRectF(active_rect)
                path_full = QRectF(rect)
                p.setClipRegion(_region_minus(path_full, clip_out), Qt.IntersectClip)
            p.fillRect(rect, SELECT_FILL)
            p.restore()
        if not self.editing:
            rng = self._clip_rng(ws.selection[-1])
            rect = self.range_rect(*rng)
            pen = QPen(QColor("#000000"), max(2, round(2 * self.z)))
            pen.setJoinStyle(Qt.MiterJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            if len(ws.selection) == 1:
                h = QRectF(rect.right() - 3, rect.bottom() - 3, 6, 6)
                p.fillRect(h.adjusted(-1, -1, 1, 1), QColor("#ffffff"))
                p.fillRect(h, QColor("#000000"))
        if self.copy_range:
            rect = self.range_rect(*self.copy_range)
            pen = QPen(QColor("#000000"), 1, Qt.CustomDashLine)
            pen.setDashPattern([4, 4])
            pen.setDashOffset(self.ants)
            p.setPen(pen)
            p.drawRect(rect.adjusted(0, 0, -1, -1))
            pen.setColor(QColor("#ffffff"))
            pen.setDashOffset(self.ants + 4)
            p.setPen(pen)
            p.drawRect(rect.adjusted(1, 1, -2, -2))
        if self.drag and self.drag.get("kind") == "fill" and self.drag.get("target"):
            rect = self.range_rect(*self.drag["target"])
            pen = QPen(QColor("#7f7f7f"), 2, Qt.DashLine)
            p.setPen(pen)
            p.drawRect(rect.adjusted(0, 0, -1, -1))
        p.restore()

    def _clip_rng(self, rng):
        r1, c1, r2, c2 = rng
        rows, cols = self.visible_rows(), self.visible_cols()
        if r2 - r1 > 2000:
            r2 = min(r2, (rows[-1] if rows else r1) + 1)
        if c2 - c1 > 500:
            c2 = min(c2, (cols[-1] if cols else c1) + 1)
        return r1, c1, r2, c2

    def _paint_formula_refs(self, p):
        if not self.editing or not self.formula_refs:
            return
        p.save()
        p.setClipRect(QRect(self.header_w, self.header_h, self.viewport().width(), self.viewport().height()))
        for i, (sheet, rng) in enumerate(self.formula_refs):
            if sheet and sheet.lower() != self.ws.name.lower():
                continue
            color = QColor(REF_COLORS[i % len(REF_COLORS)])
            rect = self.range_rect(*self._clip_rng(rng))
            p.setPen(QPen(color, 2))
            p.drawRect(rect.adjusted(1, 1, -2, -2))
            fill = QColor(color)
            fill.setAlpha(25)
            p.fillRect(rect, fill)
        p.restore()

    def _paint_freeze(self, p):
        fr, fc = self.frozen()
        p.setPen(QPen(FREEZE_LINE, 1))
        if fr:
            y = int(self.row_y(fr)) - 1
            p.drawLine(self.header_w, y, self.viewport().width(), y)
        if fc:
            x = int(self.col_x(fc)) - 1
            p.drawLine(x, self.header_h, x, self.viewport().height())

    def _paint_headers(self, p, rows, cols):
        if not self._show_headers():
            return
        ax, ay = self.axes()
        hw, hh = self.header_w, self.header_h
        font = self._header_font()
        p.setFont(font)
        sel_cols, sel_rows = set(), set()
        full_cols, full_rows = set(), set()
        for r1, c1, r2, c2 in self.ws.selection:
            vis_c = [c for c in cols if c1 <= c <= c2]
            vis_r = [r for r in rows if r1 <= r <= r2]
            sel_cols.update(vis_c)
            sel_rows.update(vis_r)
            if r1 == 0 and r2 >= MAX_ROWS - 1:
                full_cols.update(vis_c)
            if c1 == 0 and c2 >= MAX_COLS - 1:
                full_rows.update(vis_r)

        def header_cell(rect, text, selected, full):
            g = QLinearGradient(0, rect.top(), 0, rect.bottom()) if rect.height() <= hh + 1 else \
                QLinearGradient(rect.left(), 0, rect.right(), 0)
            if full:
                g.setColorAt(0, QColor("#ffd58d"))
                g.setColorAt(1, QColor("#f1a84b"))
            elif selected:
                g.setColorAt(0, HEADER_SEL1)
                g.setColorAt(1, HEADER_SEL2)
            else:
                g.setColorAt(0, HEADER_BG1)
                g.setColorAt(1, HEADER_BG2)
            p.fillRect(rect, g)
            p.setPen(HEADER_LINE)
            p.drawLine(int(rect.right()), int(rect.top()), int(rect.right()), int(rect.bottom()))
            p.drawLine(int(rect.left()), int(rect.bottom()), int(rect.right()), int(rect.bottom()))
            p.setPen(HEADER_TEXT)
            p.drawText(rect, Qt.AlignCenter, text)

        p.save()
        p.setClipRect(QRect(hw, 0, self.viewport().width(), hh))
        for c in cols:
            w = ax.size(c)
            if w <= 0:
                continue
            header_cell(QRectF(self.col_x(c), 0, w, hh), col_name(c), c in sel_cols, c in full_cols)
        p.restore()
        p.save()
        p.setClipRect(QRect(0, hh, hw, self.viewport().height()))
        for r in rows:
            h = ay.size(r)
            if h <= 0:
                continue
            header_cell(QRectF(0, self.row_y(r), hw, h), str(r + 1), r in sel_rows, r in full_rows)
        p.restore()
        corner = QRectF(0, 0, hw, hh)
        g = QLinearGradient(0, 0, 0, hh)
        g.setColorAt(0, HEADER_BG1)
        g.setColorAt(1, HEADER_BG2)
        p.fillRect(corner, g)
        p.setPen(HEADER_LINE)
        p.drawLine(hw - 1, 0, hw - 1, hh)
        p.drawLine(0, hh - 1, hw, hh - 1)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#b4c7df"))
        p.drawPolygon(QPolygon([QPoint(hw - 4, hh - 4 - int(10 * self.z)), QPoint(hw - 4, hh - 4),
                                QPoint(hw - 4 - int(10 * self.z), hh - 4)]))

    # ---- floating objects (charts, pictures) --------------------------------------------------------
    def objects(self):
        out = []
        for ch in self.ws.charts:
            r1, c1, r2, c2 = ch.anchor
            rect = QRectF(self.col_x(c1), self.row_y(r1), 0, 0)
            rect.setRight(self.col_x(c2))
            rect.setBottom(self.row_y(r2))
            out.append((ch, rect))
        for im in self.ws.images:
            r, c = im["anchor"]
            w, h = im.get("size") or (200, 150)
            out.append((im, QRectF(self.col_x(c), self.row_y(r), w * self.z, h * self.z)))
        return out

    def _paint_objects(self, p):
        objs = self.objects()
        if not objs:
            return
        import sheet_chart
        p.save()
        p.setClipRect(QRect(self.header_w, self.header_h, self.viewport().width(), self.viewport().height()))
        for obj, rect in objs:
            if not rect.intersects(QRectF(self.viewport().rect())):
                continue
            if isinstance(obj, dict):
                key = id(obj)
                pm = self._img_cache.get(key)
                if pm is None:
                    pm = QPixmap()
                    pm.loadFromData(obj["data"])
                    self._img_cache[key] = pm
                p.drawPixmap(rect.toRect(), pm)
            else:
                sheet_chart.paint(p, rect, self.wb, obj, self.ws.name)
            if self.drag and self.drag.get("obj") is obj and self.drag.get("new") is not None:
                p.setPen(QPen(QColor("#000000"), 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(self.drag["new"])
            if obj is self.selected_object:
                p.setPen(QPen(QColor("#5b7fb4"), 1))
                p.setBrush(Qt.NoBrush)
                p.drawRect(rect.adjusted(-2, -2, 1, 1))
                for hx, hy in self._handles(rect):
                    p.fillRect(QRectF(hx - 3, hy - 3, 7, 7), QColor("#ffffff"))
                    p.setPen(QColor("#5b7fb4"))
                    p.drawRect(QRectF(hx - 3, hy - 3, 6, 6))
        p.restore()

    @staticmethod
    def _handles(rect):
        return [(rect.left(), rect.top()), (rect.right(), rect.top()), (rect.left(), rect.bottom()),
                (rect.right(), rect.bottom())]

    def object_at(self, pos):
        for obj, rect in reversed(self.objects()):
            if rect.adjusted(-4, -4, 4, 4).contains(pos):
                return obj, rect
        return None, None

    # ---- mouse --------------------------------------------------------------------------------------
    def _plus_cursor(self) -> QCursor:
        pm = QPixmap(21, 21)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setPen(QColor("#000000"))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(7, 1, 6, 18)
        p.drawRect(1, 7, 18, 6)
        p.setPen(Qt.NoPen)
        p.drawRect(8, 2, 5, 17)
        p.end()
        return QCursor(pm, 10, 10)

    def _header_hit(self, pos):
        """('col'|'row'|'corner'|'colsize'|'rowsize'|None, index)"""
        hw, hh = self.header_w, self.header_h
        x, y = pos.x(), pos.y()
        if x < hw and y < hh:
            return "corner", 0
        ax, ay = self.axes()
        if y < hh and x >= hw:
            r, c = self.cell_at(QPoint(x, hh + 1))
            left = self.col_x(c)
            right = left + ax.size(c)
            if abs(x - right) <= 3:
                return "colsize", c
            if abs(x - left) <= 3 and c > 0:
                prev = c - 1
                while prev > 0 and ax.size(prev) == 0:
                    prev -= 1
                return "colsize", prev
            return "col", c
        if x < hw and y >= hh:
            r, c = self.cell_at(QPoint(hw + 1, y))
            top = self.row_y(r)
            bottom = top + ay.size(r)
            if abs(y - bottom) <= 3:
                return "rowsize", r
            if abs(y - top) <= 3 and r > 0:
                return "rowsize", r - 1
            return "row", r
        return None, 0

    def _on_fill_handle(self, pos) -> bool:
        if len(self.ws.selection) != 1 or self.editing:
            return False
        rect = self.range_rect(*self._clip_rng(self.ws.selection[-1]))
        return abs(pos.x() - rect.right()) <= 4 and abs(pos.y() - rect.bottom()) <= 4

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self.drag:
            self._drag_move(pos)
            return
        kind, _ = self._header_hit(pos)
        if kind == "colsize":
            self.viewport().setCursor(Qt.SplitHCursor)
        elif kind == "rowsize":
            self.viewport().setCursor(Qt.SplitVCursor)
        elif kind == "col":
            self.viewport().setCursor(Qt.ArrowCursor)
        elif kind == "row":
            self.viewport().setCursor(Qt.ArrowCursor)
        elif self._on_fill_handle(pos):
            self.viewport().setCursor(Qt.CrossCursor)
        elif self.object_at(pos)[0] is not None:
            obj, rect = self.object_at(pos)
            if obj is self.selected_object and any(abs(pos.x() - hx) <= 4 and abs(pos.y() - hy) <= 4
                                                   for hx, hy in self._handles(rect)):
                self.viewport().setCursor(Qt.SizeFDiagCursor)
            else:
                self.viewport().setCursor(Qt.SizeAllCursor)
        else:
            self.viewport().setCursor(self._plus_cursor())
            if kind is None and pos.x() > self.header_w and pos.y() > self.header_h:
                r, c = self.cell_at(pos)
                note = self.ws.comments.get((r, c))
                if note:
                    QToolTip.showText(e.globalPosition().toPoint(), note, self)
                elif (r, c) in self.ws.links:
                    QToolTip.showText(e.globalPosition().toPoint(),
                                      self.ws.links[(r, c)] + "\nCtrl+click to follow the link", self)

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        self.setFocus()
        if e.button() == Qt.RightButton:
            kind, idx = self._header_hit(pos)
            obj, _ = self.object_at(pos)
            if obj is not None:
                self.selected_object = obj
                self.viewport().update()
                self.contextMenu.emit(e.globalPosition().toPoint(), "object")
                return
            if kind in ("col", "row"):
                if not any(self._in_whole(kind, idx, rng) for rng in self.ws.selection):
                    self._select_header(kind, idx, False)
                self.contextMenu.emit(e.globalPosition().toPoint(), kind + "s")
                return
            r, c = self.cell_at(pos)
            if not any(r1 <= r <= r2 and c1 <= c <= c2 for r1, c1, r2, c2 in self.ws.selection):
                self.select(r, c)
            self.contextMenu.emit(e.globalPosition().toPoint(), "cells")
            return
        if e.button() != Qt.LeftButton:
            return
        # pointing at cells while typing a formula
        if self.editing and self._can_point():
            if pos.x() > self.header_w and pos.y() > self.header_h:
                r, c = self.cell_at(pos)
                self._point_insert((r, c, r, c))
                self.drag = {"kind": "point", "start": (r, c)}
                return
        if self.editing:
            self.commit_edit()
        kind, idx = self._header_hit(pos)
        shift = bool(e.modifiers() & Qt.ShiftModifier)
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if kind == "corner":
            self.select_range((0, 0, MAX_ROWS - 1, MAX_COLS - 1), active=(self.top_row(), self.left_col()))
            return
        if kind in ("colsize", "rowsize"):
            ax, ay = self.axes()
            start = ax.size(idx) if kind == "colsize" else ay.size(idx)
            old = (self.ws.col_widths if kind == "colsize" else self.ws.row_heights).get(idx)
            self.drag = {"kind": kind, "index": idx, "origin": pos, "start": start, "old": old}
            return
        if kind in ("col", "row"):
            self._select_header(kind, idx, shift, ctrl)
            self.drag = {"kind": "header", "axis": kind, "start": idx}
            return
        obj, rect = self.object_at(pos)
        if obj is not None:
            self.selected_object = obj
            resize = any(abs(pos.x() - hx) <= 4 and abs(pos.y() - hy) <= 4 for hx, hy in self._handles(rect))
            self.drag = {"kind": "resize" if resize else "move", "obj": obj, "origin": pos, "rect": QRectF(rect)}
            self.viewport().update()
            return
        if self.selected_object is not None:
            self.selected_object = None
            self.viewport().update()
        if self._on_fill_handle(pos):
            self.drag = {"kind": "fill", "source": self.ws.selection[-1], "target": None}
            return
        r, c = self.cell_at(pos)
        if ctrl and (r, c) in self.ws.links and not shift:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self.ws.links[(r, c)]))
            return
        if self.ws.autofilter and r == self.ws.autofilter[0] and self.ws.autofilter[1] <= c <= self.ws.autofilter[3]:
            rect = self.cell_rect(r, c, merged=False)
            s = min(rect.height() - 2, 16 * self.z)
            if pos.x() >= rect.right() - s - 2:
                self.filterClicked.emit(c, self.viewport().mapToGlobal(QPoint(int(rect.left()), int(rect.bottom()))))
                return
        v = self._validation_at(*self.active)
        if v is not None and v.kind == "list":
            rr = self.cell_rect(*self.active)
            if QRectF(rr.right(), rr.top(), 18 * self.z, rr.height()).contains(pos):
                self._validation_menu(v)
                return
        self.select(r, c, extend=shift, add=ctrl)
        self.drag = {"kind": "select"}

    def _in_whole(self, kind, idx, rng):
        r1, c1, r2, c2 = rng
        if kind == "col":
            return r1 == 0 and r2 >= MAX_ROWS - 1 and c1 <= idx <= c2
        return c1 == 0 and c2 >= MAX_COLS - 1 and r1 <= idx <= r2

    def _select_header(self, kind, idx, extend=False, add=False):
        if kind == "col":
            if extend:
                a = self._anchor[1]
                rng = (0, min(a, idx), MAX_ROWS - 1, max(a, idx))
                self.ws.selection = self.ws.selection[:-1] + [rng]
            else:
                rng = (0, idx, MAX_ROWS - 1, idx)
                self.ws.selection = (self.ws.selection + [rng]) if add else [rng]
                self.ws.active = (self.top_row(), idx)
                self._anchor = (0, idx)
        else:
            if extend:
                a = self._anchor[0]
                rng = (min(a, idx), 0, max(a, idx), MAX_COLS - 1)
                self.ws.selection = self.ws.selection[:-1] + [rng]
            else:
                rng = (idx, 0, idx, MAX_COLS - 1)
                self.ws.selection = (self.ws.selection + [rng]) if add else [rng]
                self.ws.active = (idx, self.left_col())
                self._anchor = (idx, 0)
        self.viewport().update()
        self.selectionChanged.emit()

    def _drag_move(self, pos):
        d = self.drag
        kind = d["kind"]
        self._last_drag_pos = pos
        if kind in ("select", "header", "fill", "point"):
            vp = self.viewport().rect()
            if not vp.adjusted(self.header_w, self.header_h, 0, 0).contains(pos):
                if not self.scroll_timer.isActive():
                    self.scroll_timer.start(60)
            else:
                self.scroll_timer.stop()
        if kind == "colsize":
            new = max(0.0, d["start"] + pos.x() - d["origin"].x())
            self.ws.col_widths[d["index"]] = max(0.0, (new / self.z / (2 if self.show_formulas else 1) - 5) / MAX_DIGIT_PX)
            self._axes = None
            self.viewport().update()
            QToolTip.showText(self.viewport().mapToGlobal(pos),
                              f"Width: {self.ws.col_widths[d['index']]:.2f} ({int(new / self.z)} pixels)", self)
        elif kind == "rowsize":
            new = max(0.0, d["start"] + pos.y() - d["origin"].y())
            self.ws.row_heights[d["index"]] = new / self.z * 72 / 96
            self._axes = None
            self.viewport().update()
            QToolTip.showText(self.viewport().mapToGlobal(pos),
                              f"Height: {self.ws.row_heights[d['index']]:.2f} ({int(new / self.z)} pixels)", self)
        elif kind == "select":
            r, c = self.cell_at(pos)
            if (r, c) != self._extent_cell:
                self.select(r, c, extend=True)
        elif kind == "header":
            r, c = self.cell_at(pos)
            self._select_header(d["axis"], c if d["axis"] == "col" else r, extend=True)
        elif kind == "fill":
            r, c = self.cell_at(pos)
            r1, c1, r2, c2 = d["source"]
            dr = r - r2 if r > r2 else (r - r1 if r < r1 else 0)
            dc = c - c2 if c > c2 else (c - c1 if c < c1 else 0)
            if abs(dr) >= abs(dc):
                tgt = (min(r1, r), c1, max(r2, r), c2) if dr else None
            else:
                tgt = (r1, min(c1, c), r2, max(c2, c)) if dc else None
            d["target"] = tgt
            self.viewport().update()
        elif kind == "point":
            r, c = self.cell_at(pos)
            sr, sc = d["start"]
            self._point_insert((min(sr, r), min(sc, c), max(sr, r), max(sc, c)))
        elif kind in ("move", "resize"):
            rect = QRectF(d["rect"])
            delta = pos - d["origin"]
            if kind == "move":
                rect.translate(delta.x(), delta.y())
            else:
                rect.setBottomRight(rect.bottomRight() + QPoint(delta.x(), delta.y()))
            d["new"] = rect
            self.viewport().update()

    def mouseReleaseEvent(self, e):
        self.scroll_timer.stop()
        d, self.drag = self.drag, None
        if not d:
            return
        kind = d["kind"]
        if kind in ("colsize", "rowsize"):
            # one undo step for the drag: put the old size back, then change it undoably
            store = self.ws.col_widths if kind == "colsize" else self.ws.row_heights
            idx = d["index"]
            new = store.get(idx)
            if d.get("old") is None:
                store.pop(idx, None)
            else:
                store[idx] = d["old"]
            sel = [rng for rng in self.ws.selection if self._in_whole("col" if kind == "colsize" else "row", idx, rng)]
            targets = [idx]
            if sel:
                r1, c1, r2, c2 = sel[-1]
                targets = list(range(c1, c2 + 1)) if kind == "colsize" else list(range(r1, r2 + 1))

            def do():
                for i in targets:
                    if new is not None:
                        store[i] = new
            self.wb.structural("Column Width" if kind == "colsize" else "Row Height", do)
            self.invalidate()
            self.contentChanged.emit()
        elif kind == "fill" and d.get("target"):
            OPS.fill(self.wb, self.ws, d["source"], d["target"],
                     copy_only=bool(e.modifiers() & Qt.ControlModifier))
            self.select_range(d["target"], active=self.active)
            self.contentChanged.emit()
        elif kind in ("move", "resize") and d.get("new") is not None:
            self._place_object(d["obj"], d["new"], kind)
        self.viewport().update()

    def _place_object(self, obj, rect: QRectF, kind):
        r1, c1 = self.cell_at(rect.topLeft().toPoint())
        r2, c2 = self.cell_at(rect.bottomRight().toPoint())

        def do():
            if isinstance(obj, dict):
                if kind == "move":
                    obj["anchor"] = (r1, c1)
                else:
                    obj["size"] = (max(10, rect.width() / self.z), max(10, rect.height() / self.z))
            else:
                if kind == "move":
                    h, w = obj.anchor[2] - obj.anchor[0], obj.anchor[3] - obj.anchor[1]
                    obj.anchor = (r1, c1, r1 + h, c1 + w)
                else:
                    obj.anchor = (obj.anchor[0], obj.anchor[1], max(obj.anchor[0] + 1, r2 + 1),
                                  max(obj.anchor[1] + 1, c2 + 1))
        self.wb.structural("Move Chart" if kind == "move" else "Size Chart", do)
        self.contentChanged.emit()

    def mouseDoubleClickEvent(self, e):
        pos = e.position().toPoint()
        kind, idx = self._header_hit(pos)
        if kind == "colsize":
            self.autofit_columns([idx])
            return
        if kind == "rowsize":
            self.autofit_rows([idx])
            return
        obj, _ = self.object_at(pos)
        if obj is not None:
            self.objectActivated.emit(obj)
            return
        if kind is None:
            self.start_edit(None, enter_mode=False)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            step = 10 if e.angleDelta().y() > 0 else -10
            self.set_zoom(self.ws.zoom + step)
            return
        dy = e.angleDelta().y()
        dx = e.angleDelta().x()
        if e.modifiers() & Qt.ShiftModifier:
            dx, dy = dy, 0
        if dy:
            vb = self.verticalScrollBar()
            steps = -int(dy / 40) or (-1 if dy > 0 else 1)
            if vb.value() + steps > vb.maximum() - 5:
                vb.setMaximum(vb.maximum() + 50)
            vb.setValue(vb.value() + steps)
        if dx:
            hb = self.horizontalScrollBar()
            steps = -int(dx / 60) or (-1 if dx > 0 else 1)
            if hb.value() + steps > hb.maximum() - 3:
                hb.setMaximum(hb.maximum() + 10)
            hb.setValue(hb.value() + steps)

    def _autoscroll(self):
        pos = getattr(self, "_last_drag_pos", None)
        if pos is None or not self.drag:
            self.scroll_timer.stop()
            return
        vb, hb = self.verticalScrollBar(), self.horizontalScrollBar()
        if pos.y() > self.viewport().height():
            vb.setMaximum(max(vb.maximum(), vb.value() + 2))
            vb.setValue(vb.value() + 1)
        elif pos.y() < self.header_h:
            vb.setValue(vb.value() - 1)
        if pos.x() > self.viewport().width():
            hb.setMaximum(max(hb.maximum(), hb.value() + 2))
            hb.setValue(hb.value() + 1)
        elif pos.x() < self.header_w:
            hb.setValue(hb.value() - 1)
        self._drag_move(pos)

    # ---- autofit -----------------------------------------------------------------------------------
    def autofit_columns(self, cols):
        def do():
            for c in cols:
                best = 0.0
                for (r, cc), cell in self.ws.cells.items():
                    if cc != c or cell.empty or self.ws.merge_at(r, c):
                        continue
                    st = self.ws.style_of(r, c)
                    f = QFont(st.font)
                    f.setPixelSize(round(st.size * 96 / 72))
                    f.setBold(st.bold)
                    text = self.wb.display(self.ws, r, c)[0]
                    width = max(QFontMetrics(f).horizontalAdvance(line) for line in text.split("\n")) + 6
                    best = max(best, width)
                if best:
                    self.ws.col_widths[c] = max(1.0, (best - 5) / MAX_DIGIT_PX)
                else:
                    self.ws.col_widths.pop(c, None)
        self.wb.structural("AutoFit Column Width", do)
        self.invalidate()
        self.contentChanged.emit()

    def autofit_rows(self, rows):
        def do():
            for r in rows:
                best = 0.0
                for (rr, c), cell in self.ws.cells.items():
                    if rr != r or cell.empty:
                        continue
                    st = self.ws.style_of(r, c)
                    f = QFont(st.font)
                    f.setPixelSize(round(st.size * 96 / 72))
                    fm = QFontMetrics(f)
                    text = self.wb.display(self.ws, r, c)[0]
                    if st.wrap:
                        w = self.axes()[0].size(c) / self.z - 4
                        h = fm.boundingRect(QRect(0, 0, int(w), 10000), Qt.TextWordWrap, text).height()
                    else:
                        h = fm.height() * (text.count("\n") + 1)
                    best = max(best, h + 4)
                if best:
                    self.ws.row_heights[r] = max(self.ws.default_height, best * 72 / 96)
                else:
                    self.ws.row_heights.pop(r, None)
        self.wb.structural("AutoFit Row Height", do)
        self.invalidate()
        self.contentChanged.emit()

    # ---- keys ----------------------------------------------------------------------------------------
    def keyPressEvent(self, e):
        k = e.key()
        mod = e.modifiers()
        ctrl = bool(mod & Qt.ControlModifier)
        shift = bool(mod & Qt.ShiftModifier)
        if self.selected_object is not None:
            if k in (Qt.Key_Delete, Qt.Key_Backspace):
                obj = self.selected_object
                self.selected_object = None

                def do():
                    if isinstance(obj, dict):
                        self.ws.images.remove(obj)
                    else:
                        self.ws.charts.remove(obj)
                self.wb.structural("Delete Chart", do)
                self.contentChanged.emit()
                self.viewport().update()
                return
            if k == Qt.Key_Escape:
                self.selected_object = None
                self.viewport().update()
                return
        moves = {Qt.Key_Up: (-1, 0), Qt.Key_Down: (1, 0), Qt.Key_Left: (0, -1), Qt.Key_Right: (0, 1)}
        if k in moves:
            dr, dc = moves[k]
            if ctrl:
                self.jump(dr, dc, extend=shift)
            else:
                self.move_active(dr, dc, extend=shift)
            return
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Backtab):
            dr, dc = (0, 1) if k == Qt.Key_Tab else (0, -1) if k == Qt.Key_Backtab else ((-1 if shift else 1), 0)
            self._move_in_selection(dr, dc)
            return
        if k == Qt.Key_Home:
            if ctrl:
                fr, fc = self.frozen()
                self.select(fr, fc, extend=shift)
            else:
                self.select(self.active[0], self.frozen()[1], extend=shift)
            return
        if k == Qt.Key_End and ctrl:
            r, c = self.ws.extent()
            self.select(r, c, extend=shift)
            return
        if k in (Qt.Key_PageDown, Qt.Key_PageUp):
            if ctrl:
                return super().keyPressEvent(e)
            page = max(1, len(self.visible_rows()) - 2)
            if mod & Qt.AltModifier:
                self.move_active(0, page if k == Qt.Key_PageDown else -page, extend=shift)
            else:
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() + (page if k == Qt.Key_PageDown else -page))
                self.move_active(page if k == Qt.Key_PageDown else -page, 0, extend=shift)
            return
        if k == Qt.Key_F2:
            self.start_edit(None, enter_mode=False)
            return
        if k == Qt.Key_Escape:
            if self.copy_range:
                self.copy_range = None
                self.ant_timer.stop()
                self.viewport().update()
            return
        if k == Qt.Key_Space and ctrl:
            c = self.active[1]
            self._select_header("col", c)
            return
        if k == Qt.Key_Space and shift:
            self._select_header("row", self.active[0])
            return
        if k == Qt.Key_Backspace:
            self.start_edit("", enter_mode=True)
            return
        if k == Qt.Key_Delete:
            for rng in self.ws.selection:
                OPS.clear(self.wb, self.ws, *rng, what="contents")
            self.contentChanged.emit()
            self.viewport().update()
            return
        text = e.text()
        if text and text.isprintable() and not ctrl and not (mod & Qt.AltModifier):
            self.start_edit(text, enter_mode=True)
            return
        super().keyPressEvent(e)

    def _move_in_selection(self, dr, dc):
        rng = self.ws.selection[-1]
        r1, c1, r2, c2 = rng
        r, c = self.active
        if r1 == r2 and c1 == c2 or len(self.ws.selection) > 1:
            self.move_active(dr, dc)
            return
        # cycle inside the selection like Excel
        if dc:
            c += dc
            if c > c2:
                c, r = c1, r + 1
            elif c < c1:
                c, r = c2, r - 1
            if r > r2:
                r = r1
            elif r < r1:
                r = r2
        else:
            r += dr
            if r > r2:
                r, c = r1, c + 1
            elif r < r1:
                r, c = r2, c - 1
            if c > c2:
                c = c1
            elif c < c1:
                c = c2
        self.ws.active = (r, c)
        self.ensure_visible(r, c)
        self.viewport().update()
        self.selectionChanged.emit()

    # ---- editing ------------------------------------------------------------------------------------
    def edit_text_for(self, r, c) -> str:
        cell = self.ws.cells.get((r, c))
        if cell is None:
            return ""
        if cell.formula is not None:
            return cell.formula
        return NF.edit_text(cell.value, self.wb.styles[cell.style].numfmt)

    def start_edit(self, text: str | None, enter_mode=True):
        if self.ws.merge_at(*self.active):
            m = self.ws.merge_at(*self.active)
            self.ws.active = (m[0], m[1])
        if self._locked(*self.active):
            self.message.emit("The cell you are trying to change is on a protected sheet.")
            return
        self.editing = True
        self.editor.enter_mode = enter_mode
        st = self.ws.style_of(*self.active)
        self.editor.setFont(self._style_font(st))
        self.editor.setText(self.edit_text_for(*self.active) if text is None else text)
        self.editor.setAlignment(Qt.AlignRight if text is None and isinstance(
            self.wb.value(self.ws.name, *self.active), float) and st.halign == "general" else Qt.AlignLeft)
        self._place_editor()
        self.editor.show()
        self.editor.setFocus()
        if text is None:
            self.editor.end(False)
        self._editor_changed(self.editor.text())
        self.editingChanged.emit(True)
        self.viewport().update()

    def _locked(self, r, c) -> bool:
        return False

    def _place_editor(self):
        rect = self.cell_rect(*self.active)
        fm = QFontMetrics(self.editor.font())
        w = max(rect.width() + 3, min(fm.horizontalAdvance(self.editor.text() + "MM"), self.viewport().width() - rect.left()))
        self.editor.setGeometry(QRect(int(rect.left()) - 2, int(rect.top()) - 2, int(w) + 2, int(max(rect.height(), fm.height() + 2)) + 3))

    def _editor_changed(self, text):
        self._place_editor()
        self.point_ref = None if not self.drag or self.drag.get("kind") != "point" else self.point_ref
        self.formula_refs = formula_ranges(text) if text.startswith("=") else []
        self.editTextChanged.emit(text)
        self.viewport().update()

    def set_edit_text(self, text: str):
        """From the formula bar."""
        if not self.editing:
            self.start_edit(text, enter_mode=False)
            return
        self.editor.setText(text)
        self._editor_changed(text)

    def _can_point(self) -> bool:
        t = self.editor.text()
        if not t.startswith("="):
            return False
        pos = self.editor.cursorPosition()
        if self.point_ref is not None:
            return True
        before = t[:pos].rstrip()
        return before.endswith(("=", "(", ",", ";", "+", "-", "*", "/", "^", "&", "<", ">", ":"))

    def _point_insert(self, rng):
        t = self.editor.text()
        ref = range_name(*rng) if rng[:2] != rng[2:] else cell_name(rng[0], rng[1])
        if self.ws.name != getattr(self, "edit_sheet", self.ws.name):
            from sheet_ref import quote_sheet
            ref = quote_sheet(self.ws.name) + "!" + ref
        if self.point_ref is not None:
            a, b = self.point_ref
            t = t[:a] + ref + t[b:]
            self.point_ref = (a, a + len(ref))
        else:
            pos = self.editor.cursorPosition()
            t = t[:pos] + ref + t[pos:]
            self.point_ref = (pos, pos + len(ref))
        self.editor.setText(t)
        self.editor.setCursorPosition(self.point_ref[1])
        self.formula_refs = formula_ranges(t)
        self.editTextChanged.emit(t)
        self.editor.setFocus()
        self.viewport().update()

    def _commit_move(self, dr, dc):
        if self.commit_edit():
            if dr or dc:
                self._move_in_selection(dr, dc)

    def commit_edit(self) -> bool:
        if not self.editing:
            return True
        text = self.editor.text()
        r, c = self.active
        v = self._validation_at(r, c)
        if v is not None and text and not validate(self.wb, self.ws, v, text):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Sheet", v.error or "The value you entered is not valid.\n\nA user has "
                                "restricted values that can be entered into this cell.")
            return False
        try:
            if text == "":
                cell = self.ws.cells.get((r, c))
                if cell is not None and not cell.empty:
                    self.wb.put(self.ws, r, c, cell.copy(value=None, formula=None) if cell.style else None)
            else:
                self.wb.set_input(self.ws, r, c, text)
                st = self.ws.style_of(r, c)
                if "\n" in text and not st.wrap:
                    self.wb.set_style(self.ws, r, c, wrap=True)
        except ValueError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Sheet", str(e))
            self.editor.setFocus()
            return False
        self._end_edit()
        self.contentChanged.emit()
        return True

    def cancel_edit(self):
        self._end_edit()

    def _end_edit(self):
        self.editing = False
        self.point_ref = None
        self.formula_refs = []
        self.editor.hide()
        self.setFocus()
        self.editingChanged.emit(False)
        self.viewport().update()

    # ---- copy marquee ------------------------------------------------------------------------------
    def show_copy(self, rng):
        self.copy_range = rng
        self.ant_timer.start(120)
        self.viewport().update()

    def _ants(self):
        self.ants = (self.ants + 1) % 8
        if self.copy_range:
            self.viewport().update()
        else:
            self.ant_timer.stop()

    # ---- validation lists --------------------------------------------------------------------------
    def _validation_at(self, r, c):
        for v in self.ws.validations:
            for r1, c1, r2, c2 in v.ranges:
                if r1 <= r <= r2 and c1 <= c <= c2:
                    return v
        return None

    def _validation_menu(self, v):
        from PySide6.QtWidgets import QMenu
        items = validation_items(self.wb, self.ws, v)
        m = QMenu(self)
        for it in items:
            m.addAction(it, lambda it=it: (self.wb.set_input(self.ws, *self.active, it), self.contentChanged.emit(),
                                           self.viewport().update()))
        rr = self.cell_rect(*self.active)
        m.exec(self.viewport().mapToGlobal(QPoint(int(rr.left()), int(rr.bottom()))))

    def sizeHint(self):
        return QSize(800, 500)


def _region_minus(outer: QRectF, inner: QRectF):
    from PySide6.QtGui import QRegion
    return QRegion(outer.toRect()).subtracted(QRegion(inner.toRect()))


def _shorter_general(v: float, fm: QFontMetrics, avail: float) -> str | None:
    """General numbers that don't fit get fewer decimals, then scientific notation (like Excel)."""
    for d in range(9, -1, -1):
        s = f"{v:.{d}f}".rstrip("0").rstrip(".") if d else f"{v:.0f}"
        s = s.replace(".", NF.DEC)
        if fm.horizontalAdvance(s) <= avail:
            return s
    for d in range(4, -1, -1):
        s = f"{v:.{d}E}".replace("E+0", "E+").replace(".", NF.DEC)
        if fm.horizontalAdvance(s) <= avail:
            return s
    return None


REF_TEXT = re.compile(r"(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?"
                      r"(?P<ref>\$?[A-Za-z]{1,3}\$?\d+(?::\$?[A-Za-z]{1,3}\$?\d+)?)(?![A-Za-z0-9_(])")


def formula_ranges(text: str):
    """The references in a formula being typed, for the coloured boxes."""
    from sheet_ref import parse_range
    out = []
    for is_str, part in _split(text):
        if is_str:
            continue
        for m in REF_TEXT.finditer(part):
            if m.start() > 0 and (part[m.start() - 1].isalnum() or part[m.start() - 1] in "_."):
                continue
            rng = parse_range(m.group("ref"))
            if rng:
                sheet = m.group("sheet")
                out.append((sheet.strip("'").replace("''", "'") if sheet else None, rng))
    return out


def _split(text):
    from sheet_ref import _split_strings
    return _split_strings(text)


class CondFormats:
    """Conditional formatting evaluated for the cells being drawn."""

    def __init__(self, wb: Workbook, ws: Worksheet):
        self.wb, self.ws = wb, ws
        self.cache = {}
        self.stats = {}

    def _range_numbers(self, rule):
        key = id(rule)
        if key not in self.stats:
            vals = []
            for r1, c1, r2, c2 in rule.ranges:
                for (r, c), _ in self.ws.cells.items():
                    if r1 <= r <= r2 and c1 <= c <= c2:
                        v = self.wb.value(self.ws.name, r, c)
                        if isinstance(v, float):
                            vals.append(v)
            self.stats[key] = sorted(vals)
        return self.stats[key]

    def style_at(self, r, c):
        out = None
        for rule in sorted(self.ws.cond, key=lambda x: x.priority):
            if not any(r1 <= r <= r2 and c1 <= c <= c2 for r1, c1, r2, c2 in rule.ranges):
                continue
            v = self.wb.value(self.ws.name, r, c)
            hit = False
            if rule.kind == "cellIs" and rule.formulas:
                vals = [self._eval(f, r, c, rule) for f in rule.formulas]
                op = rule.operator
                cmp = lambda a, b: F.compare(a, b)  # noqa: E731
                if v is None:
                    hit = False
                elif op == "between" and len(vals) == 2:
                    hit = cmp(v, vals[0]) >= 0 and cmp(v, vals[1]) <= 0
                elif op == "notBetween" and len(vals) == 2:
                    hit = cmp(v, vals[0]) < 0 or cmp(v, vals[1]) > 0
                else:
                    x = vals[0]
                    hit = {"greaterThan": cmp(v, x) > 0, "lessThan": cmp(v, x) < 0, "equal": cmp(v, x) == 0,
                           "notEqual": cmp(v, x) != 0, "greaterThanOrEqual": cmp(v, x) >= 0,
                           "lessThanOrEqual": cmp(v, x) <= 0}.get(op, False)
            elif rule.kind == "expression" and rule.formulas:
                res = self._eval(rule.formulas[0], r, c, rule)
                hit = F.to_bool(res) is True
            elif rule.kind in ("containsText", "notContainsText", "beginsWith", "endsWith") and isinstance(v, str):
                t, s = rule.text.lower(), v.lower()
                hit = {"containsText": t in s, "notContainsText": t not in s, "beginsWith": s.startswith(t),
                       "endsWith": s.endswith(t)}[rule.kind]
            elif rule.kind == "top10" and isinstance(v, float):
                nums = self._range_numbers(rule)
                n = max(1, int(len(nums) * rule.rank / 100)) if rule.percent else rule.rank
                hit = v <= nums[min(n, len(nums)) - 1] if rule.bottom else v >= nums[-min(n, len(nums))]
            elif rule.kind in ("aboveAverage", "belowAverage") and isinstance(v, float):
                nums = self._range_numbers(rule)
                avg = sum(nums) / len(nums) if nums else 0
                hit = v > avg if rule.kind == "aboveAverage" else v < avg
            elif rule.kind == "duplicateValues" and v is not None:
                hit = self._count(rule, v) > 1
            elif rule.kind == "uniqueValues" and v is not None:
                hit = self._count(rule, v) == 1
            elif rule.kind == "colorScale" and isinstance(v, float) and len(rule.colors) >= 2:
                nums = self._range_numbers(rule)
                if nums:
                    lo, hi = nums[0], nums[-1]
                    t = 0.5 if hi == lo else (v - lo) / (hi - lo)
                    out = dict(out or {})
                    out["fill"] = _blend(rule.colors, t)
                continue
            elif rule.kind == "dataBar" and isinstance(v, float):
                nums = self._range_numbers(rule)
                if nums:
                    lo, hi = min(0.0, nums[0]), nums[-1]
                    frac = 0 if hi == lo else (v - lo) / (hi - lo)
                    out = dict(out or {})
                    out["bar"] = (max(0.05, min(1.0, frac)), rule.colors[0] if rule.colors else "#638ec6")
                continue
            if hit:
                out = dict(out or {})
                if rule.fill:
                    out.setdefault("fill", rule.fill)
                if rule.color:
                    out.setdefault("color", rule.color)
                if rule.bold:
                    out["bold"] = True
                if rule.stop:
                    break
        return out

    def _count(self, rule, v):
        key = ("count", id(rule))
        if key not in self.stats:
            counts = {}
            for r1, c1, r2, c2 in rule.ranges:
                for (r, c), _ in self.ws.cells.items():
                    if r1 <= r <= r2 and c1 <= c <= c2:
                        x = self.wb.value(self.ws.name, r, c)
                        k = x.lower() if isinstance(x, str) else x
                        counts[k] = counts.get(k, 0) + 1
            self.stats[key] = counts
        return self.stats[key].get(v.lower() if isinstance(v, str) else v, 0)

    def _eval(self, formula, r, c, rule):
        """Formulas in rules are relative to the top-left cell of the rule's first range."""
        from sheet_ref import shift_formula
        r0, c0 = rule.ranges[0][0], rule.ranges[0][1]
        text = formula if formula.startswith("=") else "=" + formula
        text = shift_formula(text, r - r0, c - c0)
        try:
            v = F.evaluate(F.parse(text), F.Context(self.wb, self.ws.name, r, c))
        except F.FormulaError:
            return F.NAME
        return F.scalar(v)


def _blend(colors, t):
    def rgb(h):
        return [int(h[i:i + 2], 16) for i in (1, 3, 5)]
    if len(colors) == 3:
        if t <= 0.5:
            a, b, t = colors[0], colors[1], t * 2
        else:
            a, b, t = colors[1], colors[2], (t - 0.5) * 2
    else:
        a, b = colors[0], colors[-1]
    ca, cb = rgb(a), rgb(b)
    return "#%02x%02x%02x" % tuple(int(ca[i] + (cb[i] - ca[i]) * t) for i in range(3))


def validation_items(wb, ws, v) -> list[str]:
    f = v.formula1.strip()
    if f.startswith('"') and f.endswith('"'):
        return [x.strip() for x in f[1:-1].split(",")]
    try:
        res = F.evaluate(F.parse("=" + f.lstrip("=")), F.Context(wb, ws.name, 0, 0))
    except F.FormulaError:
        return []
    if isinstance(res, (F.Range, F.Array)):
        return [F.to_text(x) for x in res if x is not None]
    return [x.strip() for x in str(res).split(",")]


def validate(wb, ws, v, text) -> bool:
    if v.kind == "list":
        items = [i.lower() for i in validation_items(wb, ws, v)]
        return text.lower() in items
    if v.kind in ("whole", "decimal", "date", "time", "textLength"):
        val, _ = NF.parse_input(text)
        if v.kind == "textLength":
            val = float(len(text))
        if not isinstance(val, float):
            return False
        if v.kind == "whole" and val != int(val):
            return False

        def num(f):
            try:
                x = F.evaluate(F.parse("=" + f.lstrip("=")), F.Context(wb, ws.name, 0, 0)) if f else None
            except F.FormulaError:
                return None
            n = F.to_number(F.scalar(x))
            return n if isinstance(n, float) else None
        a, b = num(v.formula1), num(v.formula2)
        op = v.operator or "between"
        if a is None:
            return True
        return {"between": b is not None and a <= val <= b, "notBetween": b is not None and not (a <= val <= b),
                "equal": val == a, "notEqual": val != a, "greaterThan": val > a, "lessThan": val < a,
                "greaterThanOrEqual": val >= a, "lessThanOrEqual": val <= a}.get(op, True)
    return True
