"""Things Sheet does to ranges of cells (no GUI code): copy and paste, fill series, sort,
filter, clear, merge, AutoSum, find and replace, remove duplicates."""
from __future__ import annotations

import datetime as dt
import functools
import re
from dataclasses import dataclass, replace

import sheet_formula as F
import sheet_numfmt as NF
from sheet_model import Cell, Workbook, Worksheet
from sheet_ref import cell_name, range_name, shift_formula

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LISTS = [MONTHS, [m[:3] for m in MONTHS], DAYS, [d[:3] for d in DAYS],
         ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober",
          "november", "december"],
         ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]]


# ---- clipboard ------------------------------------------------------------------------------------
@dataclass
class Clip:
    """Copied cells: values, formulas and styles, relative to the top-left corner."""
    rows: int
    cols: int
    cells: dict[tuple[int, int], Cell]
    styles: dict[int, object]
    origin: tuple[str, int, int]
    cut: bool = False
    widths: dict[int, float] | None = None
    merges: list | None = None


def copy_range(wb: Workbook, ws: Worksheet, r1, c1, r2, c2, cut=False) -> Clip:
    cells = {}
    styles = {}
    for (r, c), cell in ws.cells.items():
        if r1 <= r <= r2 and c1 <= c <= c2:
            cells[(r - r1, c - c1)] = cell
            if cell.style:
                styles[cell.style] = wb.styles[cell.style]
    merges = [(a - r1, b - c1, x - r1, y - c1) for a, b, x, y in ws.merges
              if a >= r1 and b >= c1 and x <= r2 and y <= c2]
    return Clip(r2 - r1 + 1, c2 - c1 + 1, cells, styles, (ws.name, r1, c1), cut,
                {c - c1: w for c, w in ws.col_widths.items() if c1 <= c <= c2}, merges)


def as_text(wb: Workbook, ws: Worksheet, r1, c1, r2, c2) -> str:
    """Tab-separated text, like Excel puts on the clipboard."""
    lines = []
    for r in range(r1, r2 + 1):
        if r in ws.hidden_rows:
            continue
        row = []
        for c in range(c1, c2 + 1):
            t = wb.display(ws, r, c)[0]
            if "\t" in t or "\n" in t or '"' in t:
                t = '"' + t.replace('"', '""') + '"'
            row.append(t)
        lines.append("\t".join(row))
    return "\n".join(lines) + "\n"


def as_html(wb: Workbook, ws: Worksheet, r1, c1, r2, c2) -> str:
    import html
    out = ["<table>"]
    for r in range(r1, r2 + 1):
        if r in ws.hidden_rows:
            continue
        out.append("<tr>")
        for c in range(c1, c2 + 1):
            st = ws.style_of(r, c)
            css = []
            if st.bold:
                css.append("font-weight:bold")
            if st.italic:
                css.append("font-style:italic")
            if st.fill:
                css.append(f"background:{st.fill}")
            if st.color != "#000000":
                css.append(f"color:{st.color}")
            out.append(f'<td style="{";".join(css)}">{html.escape(wb.display(ws, r, c)[0])}</td>')
        out.append("</tr>")
    out.append("</table>")
    return "".join(out)


def parse_text_table(text: str) -> list[list[str]]:
    import csv
    import io
    text = text.rstrip("\n")
    if "\t" not in text and "\n" not in text:
        return [[text]]
    return [row for row in csv.reader(io.StringIO(text), delimiter="\t")]


def paste(wb: Workbook, ws: Worksheet, clip: Clip, r0: int, c0: int, what: str = "all",
          target: tuple[int, int, int, int] | None = None, transpose=False, skip_blanks=False,
          src_ws: Worksheet | None = None):
    """Paste copied cells at (r0, c0); what = all, values, formulas, formats. A bigger target
    range that is a multiple of the copied size gets the cells repeated, like Excel."""
    rows, cols = (clip.cols, clip.rows) if transpose else (clip.rows, clip.cols)
    reps_r = reps_c = 1
    if target:
        tr = target[2] - target[0] + 1
        tc = target[3] - target[1] + 1
        if tr % rows == 0 and tc % cols == 0:
            reps_r, reps_c = tr // rows, tc // cols
    wb.begin("Paste")
    try:
        if clip.cut and src_ws is not None:
            for (r, c), cell in list(clip.cells.items()):
                sr, sc = clip.origin[1] + r, clip.origin[2] + c
                if src_ws.cells.get((sr, sc)) is cell:
                    wb.put(src_ws, sr, sc, None)
        for rr in range(reps_r):
            for cc in range(reps_c):
                for r in range(clip.rows):
                    for c in range(clip.cols):
                        cell = clip.cells.get((r, c))
                        tr_, tc_ = (c, r) if transpose else (r, c)
                        dr, dc = r0 + rr * rows + tr_, c0 + cc * cols + tc_
                        if cell is None:
                            if skip_blanks:
                                continue
                            if what in ("all", "values", "formulas"):
                                existing = ws.cells.get((dr, dc))
                                if what == "all":
                                    wb.put(ws, dr, dc, None)
                                elif existing is not None:
                                    wb.put(ws, dr, dc, existing.copy(value=None, formula=None))
                            continue
                        sid = cell.style
                        if sid and wb.styles[sid] != clip.styles.get(sid, wb.styles[sid]):
                            sid = wb.style_id(clip.styles[sid])
                        existing = ws.cells.get((dr, dc))
                        if what == "formats":
                            new = (existing or Cell()).copy(style=sid)
                        elif what == "values":
                            v = wb.value(clip.origin[0], clip.origin[1] + r, clip.origin[2] + c) \
                                if cell.formula is not None and wb.has_sheet(clip.origin[0]) else cell.value
                            new = Cell(v, None, existing.style if existing else 0)
                        else:
                            formula = cell.formula
                            if formula is not None and not clip.cut:
                                formula = shift_formula(formula, dr - (clip.origin[1] + r), dc - (clip.origin[2] + c))
                            new = Cell(cell.value, formula, sid if what == "all" else (existing.style if existing else 0))
                        wb.put(ws, dr, dc, new)
        if what == "all" and clip.merges and not transpose:
            for a, b, x, y in clip.merges:
                m = (r0 + a, c0 + b, r0 + x, c0 + y)
                if m not in ws.merges:
                    ws.merges.append(m)
    finally:
        wb.end()


def paste_text(wb: Workbook, ws: Worksheet, text: str, r0: int, c0: int):
    rows = parse_text_table(text)
    wb.begin("Paste")
    try:
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                if val == "":
                    existing = ws.cells.get((r0 + i, c0 + j))
                    if existing is not None and not existing.empty:
                        wb.put(ws, r0 + i, c0 + j, existing.copy(value=None, formula=None))
                    continue
                wb.set_input(ws, r0 + i, c0 + j, val)
    finally:
        wb.end()
    return len(rows), max((len(r) for r in rows), default=1)


# ---- clearing ------------------------------------------------------------------------------------
def clear(wb: Workbook, ws: Worksheet, r1, c1, r2, c2, what="contents"):
    """what = contents (Delete key), formats, all, comments, links."""
    wb.begin("Clear")
    try:
        for (r, c) in [k for k in ws.cells if r1 <= k[0] <= r2 and c1 <= k[1] <= c2]:
            cell = ws.cells[(r, c)]
            if what == "contents":
                wb.put(ws, r, c, cell.copy(value=None, formula=None) if cell.style else None)
            elif what == "formats":
                wb.put(ws, r, c, cell.copy(style=0))
            elif what == "all":
                wb.put(ws, r, c, None)
        if what in ("all", "comments"):
            for k in [k for k in ws.comments if r1 <= k[0] <= r2 and c1 <= k[1] <= c2]:
                ws.comments.pop(k)
        if what in ("all", "links"):
            for k in [k for k in ws.links if r1 <= k[0] <= r2 and c1 <= k[1] <= c2]:
                ws.links.pop(k)
    finally:
        wb.end()


# ---- formatting ----------------------------------------------------------------------------------
def apply_style(wb: Workbook, ws: Worksheet, ranges, **changes):
    """Set style properties on every cell of the ranges (whole rows/columns: on the column styles too)."""
    from sheet_ref import MAX_COLS, MAX_ROWS

    def restyle(sid: int) -> int:
        return wb.style_id(replace(wb.styles[sid], **changes))

    whole = any((r1 == 0 and r2 >= MAX_ROWS - 1) or (c1 == 0 and c2 >= MAX_COLS - 1) for r1, c1, r2, c2 in ranges)
    if not whole:
        wb.begin("Format")
        try:
            for r1, c1, r2, c2 in ranges:
                for r in range(r1, r2 + 1):
                    for c in range(c1, c2 + 1):
                        wb.set_style(ws, r, c, **changes)
        finally:
            wb.end()
        return

    def do():
        for r1, c1, r2, c2 in ranges:
            whole_cols = r1 == 0 and r2 >= MAX_ROWS - 1
            whole_rows = c1 == 0 and c2 >= MAX_COLS - 1
            if whole_cols and not whole_rows:
                for c in range(c1, c2 + 1):
                    ws.col_styles[c] = restyle(ws.col_styles.get(c, 0))
            elif whole_rows and not whole_cols:
                for r in range(r1, r2 + 1):
                    ws.row_styles[r] = restyle(ws.row_styles.get(r, 0))
            else:
                for c in list(ws.col_styles):
                    ws.col_styles[c] = restyle(ws.col_styles[c])
                for r in list(ws.row_styles):
                    ws.row_styles[r] = restyle(ws.row_styles[r])
                wb.styles[0] = wb.styles[0]
            for k in [k for k in ws.cells if r1 <= k[0] <= r2 and c1 <= k[1] <= c2]:
                cell = ws.cells[k]
                ws.cells[k] = cell.copy(style=restyle(cell.style or ws.style_index(*k)))
            if r1 <= r2 and c1 <= c2 and whole_cols and whole_rows:
                # Select All: every new cell gets the format through the column styles
                for c in range(0, max(ws.extent()[1], 50) + 1):
                    ws.col_styles[c] = restyle(ws.col_styles.get(c, 0))
    wb.structural("Format", do)


def set_borders(wb: Workbook, ws: Worksheet, rng, kind: str, style="thin", color="#000000"):
    """Borders button: bottom, top, left, right, none, all, outside, thick box..."""
    from sheet_model import Border
    r1, c1, r2, c2 = rng
    b = Border(style, color)
    none = Border()
    wb.begin("Borders")
    try:
        for r in range(r1, r2 + 1):
            for c in range(c1, c2 + 1):
                ch = {}
                if kind == "none":
                    ch = {"left": none, "right": none, "top": none, "bottom": none}
                elif kind == "all":
                    ch = {"left": b, "right": b, "top": b, "bottom": b}
                elif kind in ("outside", "thick_box"):
                    bb = Border("medium" if kind == "thick_box" else style, color)
                    if r == r1:
                        ch["top"] = bb
                    if r == r2:
                        ch["bottom"] = bb
                    if c == c1:
                        ch["left"] = bb
                    if c == c2:
                        ch["right"] = bb
                elif kind == "bottom" and r == r2:
                    ch["bottom"] = b
                elif kind == "top" and r == r1:
                    ch["top"] = b
                elif kind == "left" and c == c1:
                    ch["left"] = b
                elif kind == "right" and c == c2:
                    ch["right"] = b
                elif kind == "double_bottom" and r == r2:
                    ch["bottom"] = Border("double", color)
                elif kind == "thick_bottom" and r == r2:
                    ch["bottom"] = Border("medium", color)
                elif kind == "top_bottom":
                    if r == r1:
                        ch["top"] = b
                    if r == r2:
                        ch["bottom"] = b
                if ch:
                    wb.set_style(ws, r, c, **ch)
    finally:
        wb.end()


def number_format_step(fmt: str, more: bool) -> str:
    """Increase/Decrease Decimal."""
    if fmt in ("General", ""):
        return "0.0" if more else "0"
    m = re.search(r"0(\.0*)?(?=[^0]*$|%)", fmt)
    if not m:
        return fmt
    dec = m.group(1) or ""
    n = len(dec) - 1 if dec else 0
    n = n + 1 if more else max(0, n - 1)
    new = "0" + ("." + "0" * n if n else "")
    return fmt[:m.start()] + new + fmt[m.end():]


def merge(wb: Workbook, ws: Worksheet, rng, center=True, across=False):
    def do():
        r1, c1, r2, c2 = rng
        ws.merges = [m for m in ws.merges if m[2] < r1 or m[0] > r2 or m[3] < c1 or m[1] > c2]
        if across:
            for r in range(r1, r2 + 1):
                if c2 > c1:
                    ws.merges.append((r, c1, r, c2))
        else:
            for (r, c) in [k for k in ws.cells if r1 <= k[0] <= r2 and c1 <= k[1] <= c2 and k != (r1, c1)]:
                cell = ws.cells[(r, c)]
                ws.cells[(r, c)] = cell.copy(value=None, formula=None) if cell.style else None
                if ws.cells[(r, c)] is None:
                    ws.cells.pop((r, c))
            ws.merges.append((r1, c1, r2, c2))
        if center:
            cell = ws.cells.get((r1, c1)) or Cell()
            base = wb.styles[cell.style]
            ws.cells[(r1, c1)] = cell.copy(style=wb.style_id(replace(base, halign="center")))
    wb.structural("Merge Cells", do)


def unmerge(wb: Workbook, ws: Worksheet, rng):
    def do():
        r1, c1, r2, c2 = rng
        ws.merges = [m for m in ws.merges if m[2] < r1 or m[0] > r2 or m[3] < c1 or m[1] > c2]
    wb.structural("Unmerge Cells", do)


# ---- fill series -----------------------------------------------------------------------------------
def _list_for(text: str):
    for lst in LISTS:
        low = [x.lower() for x in lst]
        if text.lower() in low:
            return lst, low.index(text.lower())
    return None, None


def fill(wb: Workbook, ws: Worksheet, src, dst, copy_only=False):
    """Drag the fill handle from src (r1, c1, r2, c2) over dst (which contains src)."""
    sr1, sc1, sr2, sc2 = src
    dr1, dc1, dr2, dc2 = dst
    vertical = (dc1, dc2) == (sc1, sc2)
    wb.begin("Fill")
    try:
        if vertical:
            lines = [[(r, c) for r in range(sr1, sr2 + 1)] for c in range(sc1, sc2 + 1)]
            if dr2 > sr2:
                targets = [[(r, c) for r in range(sr2 + 1, dr2 + 1)] for c in range(sc1, sc2 + 1)]
                backwards = False
            else:
                targets = [[(r, c) for r in range(sr1 - 1, dr1 - 1, -1)] for c in range(sc1, sc2 + 1)]
                backwards = True
        else:
            lines = [[(r, c) for c in range(sc1, sc2 + 1)] for r in range(sr1, sr2 + 1)]
            if dc2 > sc2:
                targets = [[(r, c) for c in range(sc2 + 1, dc2 + 1)] for r in range(sr1, sr2 + 1)]
                backwards = False
            else:
                targets = [[(r, c) for c in range(sc1 - 1, dc1 - 1, -1)] for r in range(sr1, sr2 + 1)]
                backwards = True
        for line, tgt in zip(lines, targets):
            _fill_line(wb, ws, line, tgt, backwards, copy_only)
    finally:
        wb.end()


def _fill_line(wb, ws, line, targets, backwards, copy_only):
    cells = [ws.cells.get(k) for k in line]
    n = len(line)
    values = [c.value if c is not None and c.formula is None else None for c in cells]
    nums = [v for v in values if isinstance(v, float)]
    numeric = all(isinstance(v, float) for v in values) and n >= 1
    step = None
    if numeric and not copy_only:
        if n == 1:
            st = wb.styles[cells[0].style] if cells[0] is not None else None
            step = 1.0 if st is not None and NF.is_date_format(st.numfmt) else None
        else:
            diffs = [nums[i + 1] - nums[i] for i in range(n - 1)]
            step = sum(diffs) / len(diffs)
    for i, (tr, tc) in enumerate(targets):
        k = i % n
        src_key = line[k] if not backwards else line[-1 - k]
        cell = ws.cells.get(src_key)
        if cell is None:
            wb.put(ws, tr, tc, None)
            continue
        if cell.formula is not None:
            wb.put(ws, tr, tc, Cell(None, shift_formula(cell.formula, tr - src_key[0], tc - src_key[1]), cell.style))
            continue
        v = cell.value
        if step is not None:
            base = nums[-1] if not backwards else nums[0]
            v = base + step * (i + 1) * (1 if not backwards else -1)
        elif isinstance(v, str) and not copy_only:
            lst, idx = _list_for(v)
            if lst:
                j = (idx + (i // n + 1) * n * (1 if not backwards else -1)) if n > 1 else \
                    (idx + (i + 1) * (1 if not backwards else -1))
                word = lst[j % len(lst)]
                v = word.upper() if v.isupper() else word if v[0].isupper() else word.lower()
            else:
                m = re.match(r"^(.*?)(\d+)(\D*)$", v)
                if m:
                    num = int(m.group(2)) + (i // n + 1) * (1 if not backwards else -1) * (1 if n == 1 else n)
                    if n == 1:
                        num = int(m.group(2)) + (i + 1) * (1 if not backwards else -1)
                    v = f"{m.group(1)}{max(num, 0):0{len(m.group(2))}d}{m.group(3)}"
        wb.put(ws, tr, tc, Cell(v, None, cell.style))


# ---- sort and filter -------------------------------------------------------------------------------
def sort_range(wb: Workbook, ws: Worksheet, rng, keys: list[tuple[int, bool]], header=False):
    """keys = [(column index, ascending)]. Rows keep their formats; formulas move with them."""
    r1, c1, r2, c2 = rng
    if header:
        r1 += 1
    if r2 <= r1:
        return

    def cmp(a, b):
        for col, asc in keys:
            va, vb = a[1].get(col), b[1].get(col)
            # empty cells always last
            if va is None and vb is None:
                continue
            if va is None:
                return 1
            if vb is None:
                return -1
            c = F.compare(va, vb)
            if c:
                return c if asc else -c
        return 0

    rows = []
    for r in range(r1, r2 + 1):
        vals = {col: wb.value(ws.name, r, col) for col, _ in keys}
        rows.append((r, vals))
    order = sorted(rows, key=functools.cmp_to_key(cmp))
    snapshot = {(r, c): ws.cells.get((r, c)) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)}
    wb.begin("Sort")
    try:
        for new_r, (old_r, _) in enumerate(order, start=r1):
            for c in range(c1, c2 + 1):
                cell = snapshot.get((old_r, c))
                if cell is not None and cell.formula is not None and new_r != old_r:
                    cell = cell.copy(formula=shift_formula(cell.formula, new_r - old_r, 0))
                wb.put(ws, new_r, c, cell)
    finally:
        wb.end()


def column_values(wb: Workbook, ws: Worksheet, rng, col) -> list[str]:
    r1, _, r2, _ = rng
    seen = []
    for r in range(r1 + 1, r2 + 1):
        t = wb.display(ws, r, col)[0]
        if t not in seen:
            seen.append(t)
    return sorted(seen, key=lambda s: (s == "", s.lower()))


def apply_filter(wb: Workbook, ws: Worksheet):
    """Hide rows of the AutoFilter range that don't match the chosen values."""
    if not ws.autofilter:
        return
    r1, c1, r2, c2 = ws.autofilter
    r2 = max(r2, data_bottom(ws, r1, c1, c2))
    ws.autofilter = (r1, c1, r2, c2)
    for r in range(r1 + 1, r2 + 1):
        show = all(wb.display(ws, r, col)[0] in allowed for col, allowed in ws.filters.items() if allowed is not None)
        if show:
            ws.hidden_rows.discard(r)
        else:
            ws.hidden_rows.add(r)


def data_bottom(ws: Worksheet, r1, c1, c2) -> int:
    bottom = r1
    for (r, c), cell in ws.cells.items():
        if c1 <= c <= c2 and r > bottom and not cell.empty:
            bottom = r
    return bottom


def current_region(ws: Worksheet, r, c) -> tuple[int, int, int, int]:
    """The block of filled cells around (r, c), like Ctrl+Shift+* (used by Sort, Filter, charts)."""
    filled = {k for k, cell in ws.cells.items() if not cell.empty}
    if (r, c) not in filled and not any((r + dr, c + dc) in filled for dr in (-1, 0, 1) for dc in (-1, 0, 1)):
        return r, c, r, c
    r1 = r2 = r
    c1 = c2 = c
    changed = True
    while changed:
        changed = False
        for rr in range(r1 - 1, r2 + 2):
            for cc in range(c1 - 1, c2 + 2):
                if (rr, cc) in filled and not (r1 <= rr <= r2 and c1 <= cc <= c2):
                    r1, r2, c1, c2 = min(r1, rr), max(r2, rr), min(c1, cc), max(c2, cc)
                    changed = True
    return max(r1, 0), max(c1, 0), r2, c2


def remove_duplicates(wb: Workbook, ws: Worksheet, rng, columns: list[int], header=True) -> int:
    r1, c1, r2, c2 = rng
    start = r1 + (1 if header else 0)
    seen = set()
    keep_rows = []
    for r in range(start, r2 + 1):
        key = tuple((str(wb.value(ws.name, r, c)) or "").lower() for c in columns)
        if key in seen:
            continue
        seen.add(key)
        keep_rows.append(r)
    removed = (r2 - start + 1) - len(keep_rows)
    if not removed:
        return 0
    snapshot = {(r, c): ws.cells.get((r, c)) for r in range(start, r2 + 1) for c in range(c1, c2 + 1)}
    wb.begin("Remove Duplicates")
    try:
        for i, old in enumerate(keep_rows):
            new = start + i
            for c in range(c1, c2 + 1):
                wb.put(ws, new, c, snapshot.get((old, c)))
        for r in range(start + len(keep_rows), r2 + 1):
            for c in range(c1, c2 + 1):
                wb.put(ws, r, c, None)
    finally:
        wb.end()
    return removed


# ---- AutoSum ---------------------------------------------------------------------------------------
def autosum_range(wb: Workbook, ws: Worksheet, r: int, c: int) -> str | None:
    """The range AutoSum suggests for a cell: numbers above it, else to the left."""
    def is_num(rr, cc):
        v = wb.value(ws.name, rr, cc)
        return isinstance(v, float)
    rr = r - 1
    while rr >= 0 and wb.value(ws.name, rr, c) is None:
        rr -= 1
    if rr >= 0 and is_num(rr, c):
        top = rr
        while top - 1 >= 0 and (is_num(top - 1, c)):
            top -= 1
        return f"{cell_name(top, c)}:{cell_name(rr, c)}"
    cc = c - 1
    while cc >= 0 and wb.value(ws.name, r, cc) is None:
        cc -= 1
    if cc >= 0 and is_num(r, cc):
        left = cc
        while left - 1 >= 0 and is_num(r, left - 1):
            left -= 1
        return f"{cell_name(r, left)}:{cell_name(r, cc)}"
    return None


# ---- find and replace -----------------------------------------------------------------------------
def find_all(wb: Workbook, ws_list, text: str, match_case=False, whole=False, in_formulas=True):
    out = []
    t = text if match_case else text.lower()
    for ws in ws_list:
        for (r, c), cell in sorted(ws.cells.items()):
            hay = cell.formula if (in_formulas and cell.formula) else wb.display(ws, r, c)[0]
            if hay is None:
                continue
            h = hay if match_case else hay.lower()
            if (h == t) if whole else (t in h):
                out.append((ws, r, c))
    return out


def replace_in(wb: Workbook, ws: Worksheet, r: int, c: int, find: str, repl: str, match_case=False) -> bool:
    cell = ws.cells.get((r, c))
    if cell is None:
        return False
    src = cell.formula if cell.formula is not None else NF.edit_text(cell.value, wb.styles[cell.style].numfmt)
    flags = 0 if match_case else re.I
    new = re.sub(re.escape(find), lambda m: repl, src, flags=flags)
    if new == src:
        return False
    try:
        wb.set_input(ws, r, c, new)
    except ValueError:
        return False
    return True


def today_serial() -> float:
    return float(int(F.to_serial(dt.datetime.now())))


def selection_stats(wb: Workbook, ws: Worksheet, ranges) -> dict:
    """Average, Count and Sum for the status bar."""
    total, count, nums = 0.0, 0, 0
    for r1, c1, r2, c2 in ranges:
        for (r, c), cell in ws.cells.items():
            if r1 <= r <= r2 and c1 <= c <= c2 and r not in ws.hidden_rows:
                v = wb.value(ws.name, r, c)
                if v is None or v == "":
                    continue
                count += 1
                if isinstance(v, float):
                    nums += 1
                    total += v
    return {"count": count, "numbers": nums, "sum": total, "average": total / nums if nums else None}


def range_text(rng) -> str:
    return range_name(*rng)
