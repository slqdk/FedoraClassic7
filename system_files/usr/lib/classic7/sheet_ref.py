"""Cell references for Sheet: A1 notation, ranges, and moving references when formulas are
copied or rows and columns are inserted. Rows and columns count from 0 inside the program."""
from __future__ import annotations

import re

MAX_ROWS = 1048576
MAX_COLS = 16384

CELL_RE = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)(\d{1,7})$")


def col_name(c: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA"""
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def col_index(name: str) -> int:
    n = 0
    for ch in name.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def cell_name(r: int, c: int, abs_r: bool = False, abs_c: bool = False) -> str:
    return f"{'$' if abs_c else ''}{col_name(c)}{'$' if abs_r else ''}{r + 1}"


def parse_cell(text: str) -> tuple[int, int] | None:
    m = CELL_RE.match(text.strip())
    if not m:
        return None
    c, r = col_index(m.group(2)), int(m.group(4)) - 1
    if not (0 <= r < MAX_ROWS and 0 <= c < MAX_COLS):
        return None
    return r, c


def parse_range(text: str) -> tuple[int, int, int, int] | None:
    """'A1', 'A1:B5', 'A:C', '3:7' -> (r1, c1, r2, c2), normalised."""
    t = text.strip().replace("$", "")
    if ":" in t:
        a, b = t.split(":", 1)
        if re.fullmatch(r"[A-Za-z]{1,3}", a) and re.fullmatch(r"[A-Za-z]{1,3}", b):
            c1, c2 = sorted((col_index(a), col_index(b)))
            return 0, c1, MAX_ROWS - 1, c2
        if a.isdigit() and b.isdigit():
            r1, r2 = sorted((int(a) - 1, int(b) - 1))
            return r1, 0, r2, MAX_COLS - 1
        p, q = parse_cell(a), parse_cell(b)
        if not p or not q:
            return None
        return min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])
    p = parse_cell(t)
    return (p[0], p[1], p[0], p[1]) if p else None


def range_name(r1: int, c1: int, r2: int, c2: int) -> str:
    if r1 == 0 and r2 == MAX_ROWS - 1:
        return f"{col_name(c1)}:{col_name(c2)}"
    if c1 == 0 and c2 == MAX_COLS - 1:
        return f"{r1 + 1}:{r2 + 1}"
    if (r1, c1) == (r2, c2):
        return cell_name(r1, c1)
    return f"{cell_name(r1, c1)}:{cell_name(r2, c2)}"


def quote_sheet(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", name) and not CELL_RE.match(name):
        return name
    return "'" + name.replace("'", "''") + "'"


# ---- moving references in formula text ------------------------------------------------------------
# A reference token inside a formula: optional sheet, then a cell or a row/column range.
REF_IN_FORMULA = re.compile(
    r"""(?P<sheet>(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?
        (?:
          (?P<c1a>\$?)(?P<c1>[A-Za-z]{1,3})(?P<r1a>\$?)(?P<r1>\d{1,7})
          (?::(?P<c2a>\$?)(?P<c2>[A-Za-z]{1,3})(?P<r2a>\$?)(?P<r2>\d{1,7}))?
        |
          (?P<cca>\$?)(?P<cc1>[A-Za-z]{1,3}):(?P<ccb>\$?)(?P<cc2>[A-Za-z]{1,3})(?![A-Za-z0-9(])
        |
          (?P<rra>\$?)(?P<rr1>\d{1,7}):(?P<rrb>\$?)(?P<rr2>\d{1,7})
        )(?![A-Za-z0-9_(])""", re.X)


def _split_strings(formula: str):
    """Yield (is_string_literal, text) pieces so references inside "..." are left alone."""
    out, cur, i, n = [], "", 0, len(formula)
    while i < n:
        ch = formula[i]
        if ch == '"':
            if cur:
                out.append((False, cur))
                cur = ""
            j = i + 1
            while j < n:
                if formula[j] == '"':
                    if j + 1 < n and formula[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            out.append((True, formula[i:j + 1]))
            i = j + 1
            continue
        cur += ch
        i += 1
    if cur:
        out.append((False, cur))
    return out


def _is_function_name(text: str, start: int, end: int) -> bool:
    return end < len(text) and text[end] == "("


def shift_formula(formula: str, dr: int, dc: int) -> str:
    """Copying a formula dr rows down and dc columns right: relative references move along."""
    def fix(m):
        if m.group("c1"):
            parts = []
            for c, ca, r, ra in (("c1", "c1a", "r1", "r1a"), ("c2", "c2a", "r2", "r2a")):
                if not m.group(c):
                    continue
                col = col_index(m.group(c)) + (0 if m.group(ca) else dc)
                row = int(m.group(r)) - 1 + (0 if m.group(ra) else dr)
                if col < 0 or row < 0 or col >= MAX_COLS or row >= MAX_ROWS:
                    return "#REF!"
                parts.append(f"{m.group(ca)}{col_name(col)}{m.group(ra)}{row + 1}")
            return (m.group("sheet") or "") + ":".join(parts)
        if m.group("cc1"):
            a = col_index(m.group("cc1")) + (0 if m.group("cca") else dc)
            b = col_index(m.group("cc2")) + (0 if m.group("ccb") else dc)
            if a < 0 or b < 0:
                return "#REF!"
            return f"{m.group('sheet') or ''}{m.group('cca')}{col_name(a)}:{m.group('ccb')}{col_name(b)}"
        a = int(m.group("rr1")) + (0 if m.group("rra") else dr)
        b = int(m.group("rr2")) + (0 if m.group("rrb") else dr)
        if a < 1 or b < 1:
            return "#REF!"
        return f"{m.group('sheet') or ''}{m.group('rra')}{a}:{m.group('rrb')}{b}"

    return _rewrite(formula, fix)


def _rewrite(formula: str, fix) -> str:
    if not formula.startswith("="):
        return formula
    out = "="
    for is_str, text in _split_strings(formula[1:]):
        if is_str:
            out += text
            continue
        res, last = "", 0
        for m in REF_IN_FORMULA.finditer(text):
            # not part of a longer name (LOG10, SUM1X...) and not a function call
            if m.start() > 0 and (text[m.start() - 1].isalnum() or text[m.start() - 1] in "_."):
                continue
            res += text[last:m.start()] + fix(m)
            last = m.end()
        out += res + text[last:]
    return out


def adjust_for_insert(formula: str, sheet: str, this_sheet: str, axis: str, at: int, count: int) -> str:
    """Rows/columns inserted (count > 0) or deleted (count < 0) at index `at` of `sheet`:
    fix references to that sheet (absolute ones too, like Excel)."""
    def moved(i: int) -> int | None:
        if count > 0:
            return i + count if i >= at else i
        if at <= i < at - count:
            return None
        return i + count if i >= at - count else i

    def fix(m):
        target = m.group("sheet")
        tname = target[:-1].strip("'").replace("''", "'") if target else this_sheet
        if tname != sheet:
            return m.group(0)
        if m.group("c1"):
            coords = []
            for c, r in (("c1", "r1"), ("c2", "r2")):
                if m.group(c):
                    coords.append([col_index(m.group(c)), int(m.group(r)) - 1])
            if axis == "row":
                rows = [moved(x[1]) for x in coords]
                if len(coords) == 2 and count < 0:
                    lo, hi = coords[0][1], coords[1][1]
                    if at <= lo and hi < at - count:
                        return "#REF!"
                    lo2 = lo if lo < at else (at if lo < at - count else lo + count)
                    hi2 = hi if hi < at else (at - 1 if hi < at - count else hi + count)
                    rows = [lo2, hi2]
                if any(x is None for x in rows):
                    return "#REF!"
                for x, nr in zip(coords, rows):
                    x[1] = nr
            else:
                cols = [moved(x[0]) for x in coords]
                if len(coords) == 2 and count < 0:
                    lo, hi = coords[0][0], coords[1][0]
                    if at <= lo and hi < at - count:
                        return "#REF!"
                    lo2 = lo if lo < at else (at if lo < at - count else lo + count)
                    hi2 = hi if hi < at else (at - 1 if hi < at - count else hi + count)
                    cols = [lo2, hi2]
                if any(x is None for x in cols):
                    return "#REF!"
                for x, nc in zip(coords, cols):
                    x[0] = nc
            parts = []
            for (c, r), (ca, ra) in zip(coords, (("c1a", "r1a"), ("c2a", "r2a"))):
                parts.append(f"{m.group(ca) or ''}{col_name(c)}{m.group(ra) or ''}{r + 1}")
            return (m.group("sheet") or "") + ":".join(parts)
        if m.group("cc1") and axis == "col":
            a, b = moved(col_index(m.group("cc1"))), moved(col_index(m.group("cc2")))
            if a is None or b is None:
                return "#REF!"
            return f"{m.group('sheet') or ''}{m.group('cca')}{col_name(a)}:{m.group('ccb')}{col_name(b)}"
        if m.group("rr1") and axis == "row":
            a, b = moved(int(m.group("rr1")) - 1), moved(int(m.group("rr2")) - 1)
            if a is None or b is None:
                return "#REF!"
            return f"{m.group('sheet') or ''}{m.group('rra')}{a + 1}:{m.group('rrb')}{b + 1}"
        return m.group(0)

    return _rewrite(formula, fix)


def rename_sheet_in_formula(formula: str, old: str, new: str) -> str:
    def fix(m):
        s = m.group("sheet")
        if s and s[:-1].strip("'").replace("''", "'") == old:
            return quote_sheet(new) + "!" + m.group(0)[len(s):]
        return m.group(0)
    return _rewrite(formula, fix)
