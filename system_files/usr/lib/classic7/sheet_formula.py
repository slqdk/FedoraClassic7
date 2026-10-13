"""Formulas for Sheet: Excel's formula language parsed into a tree and evaluated.

Values are float, str, bool, None (empty) or XLError. Dates are numbers (days since
1899-12-30, as in Excel). A range used as an argument is a Range object.
"""
from __future__ import annotations

import datetime as dt
import math
import random
import re
import statistics
from functools import reduce

from sheet_ref import MAX_COLS, MAX_ROWS, col_index, parse_cell


class XLError:
    __slots__ = ("code",)

    def __init__(self, code: str):
        self.code = code

    def __eq__(self, other):
        return isinstance(other, XLError) and other.code == self.code

    def __hash__(self):
        return hash(self.code)

    def __repr__(self):
        return self.code

    __str__ = __repr__


DIV0, NA, VALUE, REF, NAME, NUM, NULL = (XLError(c) for c in
                                          ("#DIV/0!", "#N/A", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#NULL!"))
ERRORS = {e.code: e for e in (DIV0, NA, VALUE, REF, NAME, NUM, NULL)}
CIRC = XLError("#CIRC!")      # shown as 0 with a warning, like Excel


class FormulaError(Exception):
    pass


# ---- tokens -------------------------------------------------------------------------------------
TOKEN_RE = re.compile(r"""
    (?P<ws>\s+)
  | (?P<str>"(?:[^"]|"")*")
  | (?P<err>\#(?:DIV/0!|N/A|VALUE!|REF!|NAME\?|NUM!|NULL!))
  | (?P<ref>(?:(?:'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_.]*)!)?
        (?:\$?[A-Za-z]{1,3}\$?\d{1,7}(?::\$?[A-Za-z]{1,3}\$?\d{1,7})?
          |\$?[A-Za-z]{1,3}:\$?[A-Za-z]{1,3}
          |\$?\d{1,7}:\$?\d{1,7})(?![A-Za-z0-9_(]))
  | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<func>[A-Za-z_][A-Za-z0-9_.]*(?=\())
  | (?P<name>[A-Za-z_\\][A-Za-z0-9_.]*)
  | (?P<op><>|<=|>=|[-+*/^&=<>%(),;:{}])
""", re.X)


def tokenize(text: str):
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN_RE.match(text, pos)
        if not m:
            raise FormulaError(f"Unexpected character: {text[pos]}")
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group()))
        pos = m.end()
    return out


# ---- parser -------------------------------------------------------------------------------------
# Nodes: ("num", v) ("str", s) ("bool", b) ("err", e) ("ref", sheet, r1, c1, r2, c2)
#        ("name", n) ("bin", op, a, b) ("neg", a) ("pct", a) ("call", NAME, [args]) ("arr", rows)
#        ("missing",)
def unquote_sheet(s: str) -> str:
    return s[1:-1].replace("''", "'") if s.startswith("'") else s


def parse_ref(text: str):
    sheet = None
    if "!" in text:
        sheet, text = text.rsplit("!", 1)
        sheet = unquote_sheet(sheet)
    t = text.replace("$", "")
    if ":" in t:
        a, b = t.split(":")
        if a.isalpha() and b.isalpha():
            c1, c2 = sorted((col_index(a), col_index(b)))
            return ("ref", sheet, 0, c1, MAX_ROWS - 1, c2)
        if a.isdigit() and b.isdigit():
            r1, r2 = sorted((int(a) - 1, int(b) - 1))
            return ("ref", sheet, r1, 0, r2, MAX_COLS - 1)
        p, q = parse_cell(a), parse_cell(b)
        if not p or not q:
            return ("err", REF)
        return ("ref", sheet, min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
    p = parse_cell(t)
    if not p:
        return ("err", REF)
    return ("ref", sheet, p[0], p[1], p[0], p[1])


class Parser:
    PREC = {"=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1, "&": 2, "+": 3, "-": 3, "*": 4, "/": 4, "^": 5}

    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect(self, val):
        k, v = self.take()
        if v != val:
            raise FormulaError(f"Expected {val}")

    def parse(self):
        node = self.expr(0)
        if self.i != len(self.t):
            raise FormulaError(f"Unexpected {self.peek()[1]}")
        return node

    def expr(self, min_prec):
        left = self.unary()
        while True:
            k, v = self.peek()
            if k != "op" or v not in self.PREC or self.PREC[v] < min_prec:
                break
            prec = self.PREC[v]
            self.take()
            right = self.expr(prec + 1)        # all of Excel's operators are left-associative
            left = ("bin", v, left, right)
        return left

    def unary(self):
        k, v = self.peek()
        if k == "op" and v in "+-":
            self.take()
            node = self.unary()
            return ("neg", node) if v == "-" else node
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while True:
            k, v = self.peek()
            if k == "op" and v == "%":
                self.take()
                node = ("pct", node)
            elif k == "op" and v == ":" and node[0] == "ref":
                # A1:B2 written with the range split, or a name/INDEX result: join two references
                self.take()
                other = self.primary()
                if other[0] != "ref":
                    raise FormulaError("Bad range")
                node = ("ref", node[1], min(node[2], other[2]), min(node[3], other[3]),
                        max(node[4], other[4]), max(node[5], other[5]))
            else:
                return node

    def primary(self):
        k, v = self.take()
        if k == "num":
            return ("num", float(v))
        if k == "str":
            return ("str", v[1:-1].replace('""', '"'))
        if k == "err":
            return ("err", ERRORS[v])
        if k == "ref":
            return parse_ref(v)
        if k == "func":
            name = v.upper()
            if name.startswith("_XLFN."):
                name = name[6:]
            self.expect("(")
            args = []
            k2, v2 = self.peek()
            if v2 == ")":
                self.take()
                return ("call", name, args)
            while True:
                k2, v2 = self.peek()
                if v2 in (",", ";", ")"):
                    args.append(("missing",))
                else:
                    args.append(self.expr(0))
                k2, v2 = self.take()
                if v2 == ")":
                    break
                if v2 not in (",", ";"):
                    raise FormulaError("Expected , or )")
            return ("call", name, args)
        if k == "name":
            up = v.upper()
            if up in ("TRUE", "FALSE"):
                return ("bool", up == "TRUE")
            return ("name", v)
        if k == "op" and v == "(":
            node = self.expr(0)
            self.expect(")")
            return node
        if k == "op" and v == "{":
            rows, row = [], []
            while True:
                k2, v2 = self.peek()
                if v2 == "}":
                    self.take()
                    break
                neg = False
                if v2 == "-":
                    self.take()
                    neg = True
                item = self.primary()
                if neg and item[0] == "num":
                    item = ("num", -item[1])
                row.append(item)
                k2, v2 = self.take()
                if v2 == ";":
                    rows.append(row)
                    row = []
                elif v2 == "}":
                    break
                elif v2 != ",":
                    raise FormulaError("Bad array")
            rows.append(row)
            return ("arr", rows)
        raise FormulaError(f"Unexpected {v}")


_cache: dict[str, tuple] = {}


def parse(formula: str):
    """'=SUM(A1:A3)*2' -> tree (cached)."""
    text = formula[1:] if formula.startswith("=") else formula
    tree = _cache.get(text)
    if tree is None:
        tree = Parser(tokenize(text)).parse()
        if len(_cache) > 20000:
            _cache.clear()
        _cache[text] = tree
    return tree


def references(tree, out=None):
    """All ('ref', ...) and ('name', ...) nodes in a tree: what a formula depends on."""
    if out is None:
        out = []
    kind = tree[0]
    if kind in ("ref", "name"):
        out.append(tree)
    elif kind == "bin":
        references(tree[2], out)
        references(tree[3], out)
    elif kind in ("neg", "pct"):
        references(tree[1], out)
    elif kind == "call":
        for a in tree[2]:
            references(a, out)
    return out


def is_volatile(tree) -> bool:
    if tree[0] == "call":
        if tree[1] in VOLATILE:
            return True
        return any(is_volatile(a) for a in tree[2])
    if tree[0] == "bin":
        return is_volatile(tree[2]) or is_volatile(tree[3])
    if tree[0] in ("neg", "pct"):
        return is_volatile(tree[1])
    return False


# ---- ranges -------------------------------------------------------------------------------------
class Range:
    """A rectangle of cells handed to a function; values are read lazily."""

    def __init__(self, ctx, sheet, r1, c1, r2, c2):
        self.ctx, self.sheet = ctx, sheet
        # whole columns/rows: clip to the used area of the sheet
        used_r, used_c = ctx.book.used_extent(sheet)
        self.r1, self.c1 = r1, c1
        self.r2 = min(r2, max(r1, used_r)) if r2 - r1 > 100000 else r2
        self.c2 = min(c2, max(c1, used_c)) if c2 - c1 > 1000 else c2

    @property
    def rows(self):
        return self.r2 - self.r1 + 1

    @property
    def cols(self):
        return self.c2 - self.c1 + 1

    def value(self, r, c):
        return self.ctx.cell_value(self.sheet, self.r1 + r, self.c1 + c)

    def __iter__(self):
        """Values row by row (only cells that exist are visited for big ranges)."""
        if self.rows * self.cols > 5000:
            for (r, c) in self.ctx.book.cells_in(self.sheet, self.r1, self.c1, self.r2, self.c2):
                yield self.ctx.cell_value(self.sheet, r, c)
            return
        for r in range(self.r1, self.r2 + 1):
            for c in range(self.c1, self.c2 + 1):
                yield self.ctx.cell_value(self.sheet, r, c)

    def matrix(self):
        return [[self.value(r, c) for c in range(self.cols)] for r in range(self.rows)]

    def cells(self):
        for r in range(self.r1, self.r2 + 1):
            for c in range(self.c1, self.c2 + 1):
                yield r, c, self.ctx.cell_value(self.sheet, r, c)


class Array:
    """An array constant {1,2;3,4} or a computed array."""

    def __init__(self, rows):
        self.data = rows

    @property
    def rows(self):
        return len(self.data)

    @property
    def cols(self):
        return len(self.data[0]) if self.data else 0

    def value(self, r, c):
        return self.data[r][c]

    def __iter__(self):
        for row in self.data:
            yield from row

    def matrix(self):
        return self.data


# ---- conversions --------------------------------------------------------------------------------
EPOCH = dt.datetime(1899, 12, 30)


def to_serial(d) -> float:
    if isinstance(d, dt.datetime):
        delta = d - EPOCH
    else:
        delta = dt.datetime(d.year, d.month, d.day) - EPOCH
    return delta.days + delta.seconds / 86400 + delta.microseconds / 86400e6


def from_serial(n: float) -> dt.datetime:
    return EPOCH + dt.timedelta(days=float(n))


DATE_PATTERNS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y",
                 "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M",
                 "%d/%m/%Y %H:%M", "%H:%M", "%H:%M:%S", "%I:%M %p"]


def parse_date(text: str):
    t = text.strip()
    for p in DATE_PATTERNS:
        try:
            d = dt.datetime.strptime(t, p)
        except ValueError:
            continue
        if p.startswith("%H") or p.startswith("%I"):
            return (d.hour * 3600 + d.minute * 60 + d.second) / 86400
        return to_serial(d)
    return None


def to_number(v):
    if isinstance(v, XLError):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        t = v.strip().replace(",", "") if v.count(",") and "." in v else v.strip()
        try:
            return float(t)
        except ValueError:
            pass
        if t.endswith("%"):
            try:
                return float(t[:-1]) / 100
            except ValueError:
                pass
        d = parse_date(t)
        if d is not None:
            return d
        return VALUE
    if isinstance(v, (Range, Array)):
        return to_number(first(v))
    return VALUE


def to_text(v) -> str | XLError:
    if isinstance(v, XLError):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return fmt_general(v)
    if isinstance(v, (Range, Array)):
        return to_text(first(v))
    return str(v)


def to_bool(v):
    if isinstance(v, XLError):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        if v.upper() == "TRUE":
            return True
        if v.upper() == "FALSE":
            return False
        return VALUE
    if isinstance(v, (Range, Array)):
        return to_bool(first(v))
    return VALUE


def fmt_general(v: float) -> str:
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    s = f"{v:.15g}"
    if "e" in s:
        m, e = s.split("e")
        return f"{float(m):.5g}E{int(e):+03d}"
    return s


def first(v):
    if isinstance(v, (Range, Array)):
        if v.rows == 0 or v.cols == 0:
            return None
        return v.value(0, 0)
    return v


def flatten(args, skip_text=True, skip_bool_in_ranges=True):
    """Numbers from function arguments, like SUM: ranges give only their numbers; direct
    arguments are converted (so =SUM("3", TRUE) is 4)."""
    for a in args:
        if isinstance(a, (Range, Array)):
            for v in a:
                if isinstance(v, XLError):
                    yield v
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    yield float(v)
                elif isinstance(v, bool) and not skip_bool_in_ranges:
                    yield 1.0 if v else 0.0
        elif a is None:
            continue
        else:
            n = to_number(a)
            if isinstance(n, XLError) and isinstance(a, str) and skip_text:
                yield n
            else:
                yield n


def values_of(args):
    for a in args:
        if isinstance(a, (Range, Array)):
            yield from a
        else:
            yield a


# ---- evaluation ------------------------------------------------------------------------------------
class Context:
    """What a formula sees: the workbook, the sheet and the cell it is in."""

    def __init__(self, book, sheet, row, col):
        self.book, self.sheet, self.row, self.col = book, sheet, row, col

    def cell_value(self, sheet, r, c):
        return self.book.value(sheet or self.sheet, r, c)


def evaluate(tree, ctx: Context):
    kind = tree[0]
    if kind == "num":
        return tree[1]
    if kind == "str":
        return tree[1]
    if kind == "bool":
        return tree[1]
    if kind == "err":
        return tree[1]
    if kind == "missing":
        return None
    if kind == "ref":
        sheet = tree[1] or ctx.sheet
        if not ctx.book.has_sheet(sheet):
            return REF
        return Range(ctx, sheet, *tree[2:6])
    if kind == "name":
        target = ctx.book.defined_name(tree[1], ctx.sheet)
        if target is None:
            return NAME
        if isinstance(target, tuple):        # a parsed tree
            return evaluate(target, ctx)
        return target
    if kind == "neg":
        v = scalar(evaluate(tree[1], ctx), ctx)
        n = to_number(v)
        return n if isinstance(n, XLError) else -n
    if kind == "pct":
        v = scalar(evaluate(tree[1], ctx), ctx)
        n = to_number(v)
        return n if isinstance(n, XLError) else n / 100
    if kind == "bin":
        op = tree[1]
        a = evaluate(tree[2], ctx)
        b = evaluate(tree[3], ctx)
        if isinstance(a, (Range, Array)) and (a.rows > 1 or a.cols > 1) or \
                isinstance(b, (Range, Array)) and (b.rows > 1 or b.cols > 1):
            return array_op(op, a, b, ctx)
        return binop(op, scalar(a, ctx), scalar(b, ctx))
    if kind == "arr":
        return Array([[evaluate(x, ctx) for x in row] for row in tree[1]])
    if kind == "call":
        fn = FUNCTIONS.get(tree[1])
        if fn is None:
            return NAME
        if getattr(fn, "lazy", False):
            return fn(ctx, tree[2])
        args = [evaluate(a, ctx) for a in tree[2]]
        try:
            return fn(*args) if not getattr(fn, "ctx", False) else fn(ctx, *args)
        except ZeroDivisionError:
            return DIV0
        except (ValueError, OverflowError):
            return NUM
        except (TypeError, IndexError):
            return VALUE
    return VALUE


def scalar(v, ctx: Context | None = None):
    """A range in a place that wants one value: Excel's implicit intersection with the row or
    column of the formula, else the first cell."""
    if isinstance(v, Range):
        if v.rows == 1 and v.cols == 1:
            return v.value(0, 0)
        if ctx is not None and ctx.sheet == v.sheet:
            if v.cols == 1 and v.r1 <= ctx.row <= v.r2:
                return v.value(ctx.row - v.r1, 0)
            if v.rows == 1 and v.c1 <= ctx.col <= v.c2:
                return v.value(0, ctx.col - v.c1)
        return VALUE
    if isinstance(v, Array):
        return v.value(0, 0) if v.rows and v.cols else None
    return v


def compare(a, b):
    """Excel ordering: numbers < text < booleans; text compares without case."""
    def rank(x):
        if x is None:
            return 0
        if isinstance(x, bool):
            return 3
        if isinstance(x, (int, float)):
            return 1
        return 2
    if a is None and isinstance(b, str):
        a = ""
    if b is None and isinstance(a, str):
        b = ""
    if a is None and isinstance(b, (int, float)) and not isinstance(b, bool):
        a = 0.0
    if b is None and isinstance(a, (int, float)) and not isinstance(a, bool):
        b = 0.0
    if a is None and isinstance(b, bool):
        a = False
    if b is None and isinstance(a, bool):
        b = False
    ra, rb = rank(a), rank(b)
    if ra != rb:
        return -1 if ra < rb else 1
    if isinstance(a, str):
        a, b = a.lower(), b.lower()
    if a is None:
        return 0
    return (a > b) - (a < b)


def binop(op, a, b):
    if isinstance(a, XLError):
        return a
    if isinstance(b, XLError):
        return b
    if op == "&":
        return to_text(a) + to_text(b)
    if op in ("=", "<>", "<", ">", "<=", ">="):
        c = compare(a, b)
        return {"=": c == 0, "<>": c != 0, "<": c < 0, ">": c > 0, "<=": c <= 0, ">=": c >= 0}[op]
    x, y = to_number(a), to_number(b)
    if isinstance(x, XLError):
        return x
    if isinstance(y, XLError):
        return y
    if op == "+":
        return x + y
    if op == "-":
        return x - y
    if op == "*":
        return x * y
    if op == "/":
        return DIV0 if y == 0 else x / y
    if op == "^":
        try:
            r = x ** y
        except (OverflowError, ZeroDivisionError):
            return NUM
        if isinstance(r, complex):
            return NUM
        return r
    return VALUE


def array_op(op, a, b, ctx):
    def grid(v):
        if isinstance(v, (Range, Array)):
            return v.matrix()
        return [[v]]
    ga, gb = grid(a), grid(b)
    rows = max(len(ga), len(gb))
    cols = max(len(ga[0]) if ga else 0, len(gb[0]) if gb else 0)

    def at(g, r, c):
        if len(g) == 1 and len(g[0]) == 1:
            return g[0][0]
        if len(g) == 1:
            return g[0][c] if c < len(g[0]) else NA
        if len(g[0]) == 1:
            return g[r][0] if r < len(g) else NA
        return g[r][c] if r < len(g) and c < len(g[0]) else NA
    return Array([[binop(op, at(ga, r, c), at(gb, r, c)) for c in range(cols)] for r in range(rows)])


# ---- functions -------------------------------------------------------------------------------------
FUNCTIONS: dict = {}
VOLATILE = {"NOW", "TODAY", "RAND", "RANDBETWEEN", "OFFSET", "INDIRECT"}
CATEGORIES: dict[str, list[str]] = {}
HELP: dict[str, str] = {}


def fn(name, category="Math & Trig", lazy=False, ctx=False, help=""):
    def deco(f):
        f.lazy = lazy
        f.ctx = ctx
        for n in name.split():
            FUNCTIONS[n] = f
            CATEGORIES.setdefault(category, []).append(n)
            if help:
                HELP[n] = help
        return f
    return deco


def num_arg(v):
    n = to_number(scalar(v))
    if isinstance(n, XLError):
        raise _Err(n)
    return n


class _Err(Exception):
    def __init__(self, e):
        self.e = e


def guard(f):
    """Return a raised _Err as the error value."""
    def wrapper(*a):
        try:
            return f(*a)
        except _Err as e:
            return e.e
    wrapper.lazy = getattr(f, "lazy", False)
    wrapper.ctx = getattr(f, "ctx", False)
    wrapper.__name__ = f.__name__
    return wrapper


def register(name, category, help=""):
    def deco(f):
        g = guard(f)
        g.lazy = False
        g.ctx = False
        for n in name.split():
            FUNCTIONS[n] = g
            CATEGORIES.setdefault(category, []).append(n)
            if help:
                HELP[n] = help
        return g
    return deco


def first_error(values):
    for v in values:
        if isinstance(v, XLError):
            return v
    return None


def nums(args):
    out = list(flatten(args))
    err = first_error(out)
    if err:
        raise _Err(err)
    return out


# Math
@register("SUM", "Math & Trig", "SUM(number1, [number2], ...) adds all the numbers.")
def _sum(*args):
    return math.fsum(nums(args))


@register("PRODUCT", "Math & Trig")
def _product(*args):
    return reduce(lambda a, b: a * b, nums(args), 1.0)


@register("SUMSQ", "Math & Trig")
def _sumsq(*args):
    return math.fsum(x * x for x in nums(args))


@register("ABS", "Math & Trig")
def _abs(x):
    return abs(num_arg(x))


@register("SIGN", "Math & Trig")
def _sign(x):
    n = num_arg(x)
    return float((n > 0) - (n < 0))


@register("INT", "Math & Trig")
def _int(x):
    return float(math.floor(num_arg(x)))


@register("TRUNC", "Math & Trig")
def _trunc(x, digits=None):
    n, d = num_arg(x), int(num_arg(digits)) if digits is not None else 0
    f = 10 ** d
    return math.trunc(n * f) / f


def _round_half_away(n, d):
    f = 10 ** d
    v = abs(n) * f
    r = math.floor(v + 0.5 + 1e-9)
    return math.copysign(r / f, n)


@register("ROUND", "Math & Trig", "ROUND(number, num_digits) rounds a number to a number of digits.")
def _round(x, d=None):
    return _round_half_away(num_arg(x), int(num_arg(d)) if d is not None else 0)


@register("ROUNDUP", "Math & Trig")
def _roundup(x, d=None):
    n, dd = num_arg(x), int(num_arg(d)) if d is not None else 0
    f = 10 ** dd
    return math.copysign(math.ceil(abs(n) * f - 1e-9) / f, n)


@register("ROUNDDOWN", "Math & Trig")
def _rounddown(x, d=None):
    n, dd = num_arg(x), int(num_arg(d)) if d is not None else 0
    f = 10 ** dd
    return math.copysign(math.floor(abs(n) * f + 1e-9) / f, n)


@register("MROUND", "Math & Trig")
def _mround(x, m):
    n, mm = num_arg(x), num_arg(m)
    if mm == 0:
        return 0.0
    if n * mm < 0:
        return NUM
    return _round_half_away(n / mm, 0) * mm


@register("CEILING CEILING.MATH", "Math & Trig")
def _ceiling(x, sig=None, *_):
    n = num_arg(x)
    s = num_arg(sig) if sig is not None else 1.0
    if s == 0:
        return 0.0
    return math.ceil(n / s - 1e-12) * s


@register("FLOOR FLOOR.MATH", "Math & Trig")
def _floor(x, sig=None, *_):
    n = num_arg(x)
    s = num_arg(sig) if sig is not None else 1.0
    if s == 0:
        return DIV0
    return math.floor(n / s + 1e-12) * s


@register("EVEN", "Math & Trig")
def _even(x):
    n = num_arg(x)
    v = math.ceil(abs(n) / 2) * 2
    return math.copysign(v, n)


@register("ODD", "Math & Trig")
def _odd(x):
    n = num_arg(x)
    v = math.ceil((abs(n) - 1) / 2) * 2 + 1
    return math.copysign(max(v, 1), n)


@register("MOD", "Math & Trig")
def _mod(a, b):
    x, y = num_arg(a), num_arg(b)
    if y == 0:
        return DIV0
    return x - y * math.floor(x / y)


@register("QUOTIENT", "Math & Trig")
def _quotient(a, b):
    x, y = num_arg(a), num_arg(b)
    if y == 0:
        return DIV0
    return float(math.trunc(x / y))


@register("POWER", "Math & Trig")
def _power(a, b):
    return binop("^", num_arg(a), num_arg(b))


@register("SQRT", "Math & Trig")
def _sqrt(x):
    n = num_arg(x)
    return NUM if n < 0 else math.sqrt(n)


@register("EXP", "Math & Trig")
def _exp(x):
    return math.exp(num_arg(x))


@register("LN", "Math & Trig")
def _ln(x):
    n = num_arg(x)
    return NUM if n <= 0 else math.log(n)


@register("LOG", "Math & Trig")
def _log(x, base=None):
    n = num_arg(x)
    b = num_arg(base) if base is not None else 10.0
    if n <= 0 or b <= 0 or b == 1:
        return NUM
    return math.log(n, b)


@register("LOG10", "Math & Trig")
def _log10(x):
    n = num_arg(x)
    return NUM if n <= 0 else math.log10(n)


@register("PI", "Math & Trig")
def _pi():
    return math.pi


for _name, _f in (("SIN", math.sin), ("COS", math.cos), ("TAN", math.tan), ("ASIN", math.asin),
                  ("ACOS", math.acos), ("ATAN", math.atan), ("SINH", math.sinh), ("COSH", math.cosh),
                  ("TANH", math.tanh), ("DEGREES", math.degrees), ("RADIANS", math.radians)):
    register(_name, "Math & Trig")(lambda x, _f=_f: _f(num_arg(x)))


@register("ATAN2", "Math & Trig")
def _atan2(x, y):
    a, b = num_arg(x), num_arg(y)
    if a == 0 and b == 0:
        return DIV0
    return math.atan2(b, a)


@register("FACT", "Math & Trig")
def _fact(x):
    n = int(num_arg(x))
    return NUM if n < 0 else float(math.factorial(n))


@register("COMBIN", "Math & Trig")
def _combin(n, k):
    a, b = int(num_arg(n)), int(num_arg(k))
    if a < 0 or b < 0 or b > a:
        return NUM
    return float(math.comb(a, b))


@register("PERMUT", "Statistical")
def _permut(n, k):
    a, b = int(num_arg(n)), int(num_arg(k))
    if a < 0 or b < 0 or b > a:
        return NUM
    return float(math.perm(a, b))


@register("GCD", "Math & Trig")
def _gcd(*args):
    return float(reduce(math.gcd, (int(x) for x in nums(args)), 0))


@register("LCM", "Math & Trig")
def _lcm(*args):
    return float(reduce(lambda a, b: a * b // math.gcd(a, b) if a and b else 0, (int(x) for x in nums(args)), 1))


@register("RAND", "Math & Trig")
def _rand():
    return random.random()


@register("RANDBETWEEN", "Math & Trig")
def _randbetween(a, b):
    lo, hi = math.ceil(num_arg(a)), math.floor(num_arg(b))
    if lo > hi:
        return NUM
    return float(random.randint(lo, hi))


@register("SUMPRODUCT", "Math & Trig", "SUMPRODUCT(array1, [array2], ...) multiplies matching items and adds them up.")
def _sumproduct(*arrays):
    mats = []
    for a in arrays:
        if isinstance(a, (Range, Array)):
            mats.append(a.matrix())
        else:
            mats.append([[a]])
    shape = (len(mats[0]), len(mats[0][0]) if mats[0] else 0)
    if any((len(m), len(m[0]) if m else 0) != shape for m in mats):
        return VALUE
    total = 0.0
    for r in range(shape[0]):
        for c in range(shape[1]):
            p = 1.0
            for m in mats:
                v = m[r][c]
                if isinstance(v, XLError):
                    return v
                if isinstance(v, bool):
                    v = 1.0 if v else 0.0
                p *= v if isinstance(v, (int, float)) else 0.0
            total += p
    return total


def _criteria(crit):
    """COUNTIF criteria: 5, ">5", "<>x", "a*", "=b?" -> a test function."""
    if isinstance(crit, (int, float)) and not isinstance(crit, bool):
        return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == float(crit)
    if isinstance(crit, bool):
        return lambda v: v is crit
    if crit is None:
        crit = ""
    text = str(crit)
    m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", text, re.S)
    op, operand = m.group(1) or "=", m.group(2)
    num = to_number(operand) if operand != "" else None
    if isinstance(num, float) and op != "=" or (isinstance(num, float) and op == "=" and operand.strip() != ""):
        def test(v, op=op, num=num):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                if isinstance(v, str):
                    n2 = to_number(v)
                    if isinstance(n2, XLError):
                        return op == "<>"
                    v = n2
                else:
                    return op == "<>" if v is not None else (op == "<>")
            return {"=": v == num, "<>": v != num, "<": v < num, ">": v > num, "<=": v <= num, ">=": v >= num}[op]
        return test
    if operand == "":
        if op == "=":
            return lambda v: v is None or v == ""
        if op == "<>":
            return lambda v: v is not None and v != ""
    pat = "^" + "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch)
                         for ch in re.sub(r"~([*?])", r"\1", operand)) + "$"
    rx = re.compile(pat, re.I | re.S)
    if op in ("=", "<>"):
        def test(v, rx=rx, op=op):
            match = isinstance(v, str) and bool(rx.match(v))
            return match if op == "=" else not match
        return test

    def test(v, op=op, operand=operand):
        if not isinstance(v, str):
            return False
        c = (v.lower() > operand.lower()) - (v.lower() < operand.lower())
        return {"<": c < 0, ">": c > 0, "<=": c <= 0, ">=": c >= 0}[op]
    return test


def _range_values(r):
    if isinstance(r, Range):
        return [v for _, _, v in r.cells()] if r.rows * r.cols <= 200000 else list(r)
    if isinstance(r, Array):
        return list(r)
    return [r]


@register("COUNTIF", "Statistical", "COUNTIF(range, criteria) counts the cells that meet the criteria.")
def _countif(rng, crit):
    t = _criteria(scalar(crit))
    return float(sum(1 for v in _range_values(rng) if t(v)))


@register("COUNTIFS", "Statistical")
def _countifs(*args):
    pairs = [(_range_values(args[i]), _criteria(scalar(args[i + 1]))) for i in range(0, len(args) - 1, 2)]
    n = len(pairs[0][0])
    if any(len(p[0]) != n for p in pairs):
        return VALUE
    return float(sum(1 for i in range(n) if all(t(vals[i]) for vals, t in pairs)))


@register("SUMIF", "Math & Trig", "SUMIF(range, criteria, [sum_range]) adds the cells that meet the criteria.")
def _sumif(rng, crit, sum_rng=None):
    t = _criteria(scalar(crit))
    vals = _range_values(rng)
    sums = _range_values(sum_rng) if sum_rng is not None else vals
    total = 0.0
    for v, s in zip(vals, sums):
        if t(v) and isinstance(s, (int, float)) and not isinstance(s, bool):
            total += s
    return total


@register("SUMIFS", "Math & Trig")
def _sumifs(sum_rng, *args):
    sums = _range_values(sum_rng)
    pairs = [(_range_values(args[i]), _criteria(scalar(args[i + 1]))) for i in range(0, len(args) - 1, 2)]
    if any(len(p[0]) != len(sums) for p in pairs):
        return VALUE
    return math.fsum(s for i, s in enumerate(sums) if isinstance(s, (int, float)) and not isinstance(s, bool)
                     and all(t(vals[i]) for vals, t in pairs))


@register("AVERAGEIF", "Statistical")
def _averageif(rng, crit, avg_rng=None):
    t = _criteria(scalar(crit))
    vals = _range_values(rng)
    avgs = _range_values(avg_rng) if avg_rng is not None else vals
    sel = [s for v, s in zip(vals, avgs) if t(v) and isinstance(s, (int, float)) and not isinstance(s, bool)]
    return DIV0 if not sel else math.fsum(sel) / len(sel)


@register("AVERAGEIFS", "Statistical")
def _averageifs(avg_rng, *args):
    avgs = _range_values(avg_rng)
    pairs = [(_range_values(args[i]), _criteria(scalar(args[i + 1]))) for i in range(0, len(args) - 1, 2)]
    sel = [s for i, s in enumerate(avgs) if isinstance(s, (int, float)) and not isinstance(s, bool)
           and all(t(vals[i]) for vals, t in pairs)]
    return DIV0 if not sel else math.fsum(sel) / len(sel)


@register("MAXIFS", "Statistical")
def _maxifs(rng, *args):
    vals = _range_values(rng)
    pairs = [(_range_values(args[i]), _criteria(scalar(args[i + 1]))) for i in range(0, len(args) - 1, 2)]
    sel = [s for i, s in enumerate(vals) if isinstance(s, (int, float)) and not isinstance(s, bool)
           and all(t(v[i]) for v, t in pairs)]
    return max(sel) if sel else 0.0


@register("MINIFS", "Statistical")
def _minifs(rng, *args):
    vals = _range_values(rng)
    pairs = [(_range_values(args[i]), _criteria(scalar(args[i + 1]))) for i in range(0, len(args) - 1, 2)]
    sel = [s for i, s in enumerate(vals) if isinstance(s, (int, float)) and not isinstance(s, bool)
           and all(t(v[i]) for v, t in pairs)]
    return min(sel) if sel else 0.0


# Statistical
@register("AVERAGE", "Statistical", "AVERAGE(number1, [number2], ...) returns the average of the numbers.")
def _average(*args):
    n = nums(args)
    return DIV0 if not n else math.fsum(n) / len(n)


@register("AVERAGEA", "Statistical")
def _averagea(*args):
    vals = [1.0 if v is True else 0.0 if v is False or isinstance(v, str) else v
            for v in values_of(args) if v is not None]
    err = first_error(vals)
    if err:
        return err
    return DIV0 if not vals else math.fsum(vals) / len(vals)


@register("COUNT", "Statistical", "COUNT(value1, [value2], ...) counts the cells that contain numbers.")
def _count(*args):
    c = 0
    for a in args:
        if isinstance(a, (Range, Array)):
            c += sum(1 for v in a if isinstance(v, (int, float)) and not isinstance(v, bool))
        elif not isinstance(to_number(a), XLError) and a is not None:
            c += 1
    return float(c)


@register("COUNTA", "Statistical", "COUNTA(value1, [value2], ...) counts the cells that are not empty.")
def _counta(*args):
    c = 0
    for a in args:
        if isinstance(a, (Range, Array)):
            c += sum(1 for v in a if v is not None and v != "")
        elif a is not None:
            c += 1
    return float(c)


@register("COUNTBLANK", "Statistical")
def _countblank(rng):
    if isinstance(rng, Range):
        total = rng.rows * rng.cols
        filled = sum(1 for _, _, v in rng.cells() if v is not None and v != "")
        return float(total - filled)
    return 0.0


@register("MAX", "Statistical", "MAX(number1, [number2], ...) returns the largest number.")
def _max(*args):
    n = nums(args)
    return max(n) if n else 0.0


@register("MIN", "Statistical", "MIN(number1, [number2], ...) returns the smallest number.")
def _min(*args):
    n = nums(args)
    return min(n) if n else 0.0


@register("MAXA", "Statistical")
def _maxa(*args):
    n = [1.0 if v is True else 0.0 if v is False or isinstance(v, str) else v for v in values_of(args) if v is not None]
    return max(n) if n else 0.0


@register("MINA", "Statistical")
def _mina(*args):
    n = [1.0 if v is True else 0.0 if v is False or isinstance(v, str) else v for v in values_of(args) if v is not None]
    return min(n) if n else 0.0


@register("MEDIAN", "Statistical")
def _median(*args):
    n = nums(args)
    return NUM if not n else statistics.median(n)


@register("MODE MODE.SNGL", "Statistical")
def _mode(*args):
    n = nums(args)
    counts = {}
    for x in n:
        counts[x] = counts.get(x, 0) + 1
    best = max(counts.values(), default=0)
    if best < 2:
        return NA
    return next(x for x in n if counts[x] == best)


@register("STDEV STDEV.S", "Statistical")
def _stdev(*args):
    n = nums(args)
    return DIV0 if len(n) < 2 else statistics.stdev(n)


@register("STDEVP STDEV.P", "Statistical")
def _stdevp(*args):
    n = nums(args)
    return DIV0 if not n else statistics.pstdev(n)


@register("VAR VAR.S", "Statistical")
def _var(*args):
    n = nums(args)
    return DIV0 if len(n) < 2 else statistics.variance(n)


@register("VARP VAR.P", "Statistical")
def _varp(*args):
    n = nums(args)
    return DIV0 if not n else statistics.pvariance(n)


@register("LARGE", "Statistical")
def _large(rng, k):
    n = sorted(nums([rng]), reverse=True)
    i = int(num_arg(k))
    return NUM if i < 1 or i > len(n) else n[i - 1]


@register("SMALL", "Statistical")
def _small(rng, k):
    n = sorted(nums([rng]))
    i = int(num_arg(k))
    return NUM if i < 1 or i > len(n) else n[i - 1]


@register("RANK RANK.EQ", "Statistical")
def _rank(x, rng, order=None):
    v = num_arg(x)
    n = nums([rng])
    if v not in n:
        return NA
    asc = order is not None and num_arg(order) != 0
    return float(sorted(n, reverse=not asc).index(v) + 1)


@register("PERCENTILE PERCENTILE.INC", "Statistical")
def _percentile(rng, k):
    n = sorted(nums([rng]))
    p = num_arg(k)
    if not n or p < 0 or p > 1:
        return NUM
    pos = p * (len(n) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(n) - 1)
    return n[lo] + (n[hi] - n[lo]) * (pos - lo)


@register("QUARTILE QUARTILE.INC", "Statistical")
def _quartile(rng, q):
    qq = int(num_arg(q))
    if qq < 0 or qq > 4:
        return NUM
    return _percentile(rng, qq / 4)


@register("CORREL", "Statistical")
def _correl(a, b):
    pa, pb = _pairs(a, b)
    if len(pa) < 2:
        return DIV0
    try:
        return statistics.correlation(pa, pb)
    except statistics.StatisticsError:
        return DIV0


def _pairs(a, b):
    va, vb = _range_values(a), _range_values(b)
    pa, pb = [], []
    for x, y in zip(va, vb):
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool) and not isinstance(y, bool):
            pa.append(float(x))
            pb.append(float(y))
    return pa, pb


@register("SLOPE", "Statistical")
def _slope(ys, xs):
    py, px = _pairs(ys, xs)
    if len(px) < 2:
        return DIV0
    try:
        return statistics.linear_regression(px, py).slope
    except statistics.StatisticsError:
        return DIV0


@register("INTERCEPT", "Statistical")
def _intercept(ys, xs):
    py, px = _pairs(ys, xs)
    if len(px) < 2:
        return DIV0
    try:
        return statistics.linear_regression(px, py).intercept
    except statistics.StatisticsError:
        return DIV0


@register("FORECAST FORECAST.LINEAR", "Statistical")
def _forecast(x, ys, xs):
    py, px = _pairs(ys, xs)
    if len(px) < 2:
        return DIV0
    lr = statistics.linear_regression(px, py)
    return lr.intercept + lr.slope * num_arg(x)


# Logical
def _lazy_eval(ctx, node):
    return evaluate(node, ctx)


@fn("IF", "Logical", lazy=True, help="IF(logical_test, [value_if_true], [value_if_false]) checks a condition.")
def _if(ctx, args):
    if not args:
        return VALUE
    cond = to_bool(scalar(evaluate(args[0], ctx), ctx))
    if isinstance(cond, XLError):
        return cond
    if cond:
        return evaluate(args[1], ctx) if len(args) > 1 and args[1][0] != "missing" else (0.0 if len(args) > 1 else True)
    if len(args) > 2:
        return evaluate(args[2], ctx) if args[2][0] != "missing" else 0.0
    return False


@fn("IFERROR", "Logical", lazy=True, help="IFERROR(value, value_if_error) gives another value if there is an error.")
def _iferror(ctx, args):
    v = evaluate(args[0], ctx)
    if isinstance(scalar(v, ctx), XLError):
        return evaluate(args[1], ctx) if len(args) > 1 else ""
    return v


@fn("IFNA", "Logical", lazy=True)
def _ifna(ctx, args):
    v = evaluate(args[0], ctx)
    if scalar(v, ctx) == NA:
        return evaluate(args[1], ctx)
    return v


@fn("IFS", "Logical", lazy=True)
def _ifs(ctx, args):
    for i in range(0, len(args) - 1, 2):
        c = to_bool(scalar(evaluate(args[i], ctx), ctx))
        if isinstance(c, XLError):
            return c
        if c:
            return evaluate(args[i + 1], ctx)
    return NA


@fn("SWITCH", "Logical", lazy=True)
def _switch(ctx, args):
    v = scalar(evaluate(args[0], ctx), ctx)
    rest = args[1:]
    for i in range(0, len(rest) - 1, 2):
        if compare(v, scalar(evaluate(rest[i], ctx), ctx)) == 0:
            return evaluate(rest[i + 1], ctx)
    if len(rest) % 2:
        return evaluate(rest[-1], ctx)
    return NA


def _logic_values(args):
    out = []
    for a in args:
        if isinstance(a, (Range, Array)):
            out += [to_bool(v) for v in a if isinstance(v, (bool, int, float)) or isinstance(v, XLError)]
        elif a is not None:
            out.append(to_bool(a))
    return out


@register("AND", "Logical")
def _and(*args):
    v = _logic_values(args)
    err = first_error(v)
    return err or (all(v) if v else VALUE)


@register("OR", "Logical")
def _or(*args):
    v = _logic_values(args)
    err = first_error(v)
    return err or (any(v) if v else VALUE)


@register("XOR", "Logical")
def _xor(*args):
    v = _logic_values(args)
    err = first_error(v)
    return err or (sum(1 for x in v if x) % 2 == 1)


@register("NOT", "Logical")
def _not(x):
    b = to_bool(scalar(x))
    return b if isinstance(b, XLError) else not b


@register("TRUE", "Logical")
def _true():
    return True


@register("FALSE", "Logical")
def _false():
    return False


# Information
@register("ISBLANK", "Information")
def _isblank(x):
    return scalar(x) is None


@register("ISNUMBER", "Information")
def _isnumber(x):
    v = scalar(x)
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@register("ISTEXT", "Information")
def _istext(x):
    return isinstance(scalar(x), str)


@register("ISNONTEXT", "Information")
def _isnontext(x):
    return not isinstance(scalar(x), str)


@register("ISLOGICAL", "Information")
def _islogical(x):
    return isinstance(scalar(x), bool)


@register("ISERROR", "Information")
def _iserror(x):
    return isinstance(scalar(x), XLError)


@register("ISERR", "Information")
def _iserr(x):
    v = scalar(x)
    return isinstance(v, XLError) and v != NA


@register("ISNA", "Information")
def _isna(x):
    return scalar(x) == NA


@register("ISEVEN", "Information")
def _iseven(x):
    return int(num_arg(x)) % 2 == 0


@register("ISODD", "Information")
def _isodd(x):
    return int(num_arg(x)) % 2 == 1


@register("NA", "Information")
def _na():
    return NA


@register("N", "Information")
def _n(x):
    v = scalar(x)
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, XLError):
        return v
    return 0.0


@register("TYPE", "Information")
def _type(x):
    if isinstance(x, (Range, Array)) and (x.rows > 1 or x.cols > 1):
        return 64.0
    v = scalar(x)
    if isinstance(v, bool):
        return 4.0
    if isinstance(v, (int, float)) or v is None:
        return 1.0
    if isinstance(v, str):
        return 2.0
    return 16.0


@register("ERROR.TYPE", "Information")
def _errortype(x):
    v = scalar(x)
    order = ["#NULL!", "#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#NUM!", "#N/A"]
    if isinstance(v, XLError) and v.code in order:
        return float(order.index(v.code) + 1)
    return NA


# Text
def text_arg(v):
    t = to_text(scalar(v))
    if isinstance(t, XLError):
        raise _Err(t)
    return t


@register("CONCATENATE", "Text")
def _concatenate(*args):
    return "".join(text_arg(a) for a in args)


@register("CONCAT", "Text")
def _concat(*args):
    out = []
    for a in args:
        if isinstance(a, (Range, Array)):
            out += [to_text(v) for v in a]
        else:
            out.append(text_arg(a))
    err = first_error(out)
    return err or "".join(out)


@register("TEXTJOIN", "Text")
def _textjoin(delim, ignore_empty, *args):
    d = text_arg(delim)
    skip = to_bool(scalar(ignore_empty))
    parts = []
    for a in args:
        vals = list(a) if isinstance(a, (Range, Array)) else [scalar(a)]
        for v in vals:
            t = to_text(v)
            if isinstance(t, XLError):
                return t
            if skip and t == "":
                continue
            parts.append(t)
    return d.join(parts)


@register("LEFT", "Text")
def _left(t, n=None):
    k = int(num_arg(n)) if n is not None else 1
    return VALUE if k < 0 else text_arg(t)[:k]


@register("RIGHT", "Text")
def _right(t, n=None):
    k = int(num_arg(n)) if n is not None else 1
    s = text_arg(t)
    return VALUE if k < 0 else (s[-k:] if k else "")


@register("MID", "Text")
def _mid(t, start, n):
    s, a, k = text_arg(t), int(num_arg(start)), int(num_arg(n))
    if a < 1 or k < 0:
        return VALUE
    return s[a - 1:a - 1 + k]


@register("LEN", "Text")
def _len(t):
    return float(len(text_arg(t)))


@register("UPPER", "Text")
def _upper(t):
    return text_arg(t).upper()


@register("LOWER", "Text")
def _lower(t):
    return text_arg(t).lower()


@register("PROPER", "Text")
def _proper(t):
    return re.sub(r"[A-Za-zÀ-ÿ]+", lambda m: m.group(0)[0].upper() + m.group(0)[1:].lower(), text_arg(t))


@register("TRIM", "Text")
def _trim(t):
    return re.sub(r" +", " ", text_arg(t)).strip(" ")


@register("CLEAN", "Text")
def _clean(t):
    return "".join(ch for ch in text_arg(t) if ord(ch) >= 32)


@register("FIND", "Text")
def _find(sub, text, start=None):
    s, t = text_arg(sub), text_arg(text)
    a = int(num_arg(start)) if start is not None else 1
    if a < 1 or a > len(t) + 1:
        return VALUE
    i = t.find(s, a - 1)
    return VALUE if i < 0 else float(i + 1)


@register("SEARCH", "Text")
def _search(sub, text, start=None):
    s, t = text_arg(sub), text_arg(text)
    a = int(num_arg(start)) if start is not None else 1
    if a < 1 or a > len(t) + 1:
        return VALUE
    pat = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in s)
    m = re.compile(pat, re.I | re.S).search(t, a - 1)
    return VALUE if not m else float(m.start() + 1)


@register("SUBSTITUTE", "Text")
def _substitute(text, old, new, instance=None):
    t, o, n = text_arg(text), text_arg(old), text_arg(new)
    if not o:
        return t
    if instance is None:
        return t.replace(o, n)
    k = int(num_arg(instance))
    if k < 1:
        return VALUE
    idx = -1
    for _ in range(k):
        idx = t.find(o, idx + 1)
        if idx < 0:
            return t
    return t[:idx] + n + t[idx + len(o):]


@register("REPLACE", "Text")
def _replace(text, start, n, new):
    t, a, k, s = text_arg(text), int(num_arg(start)), int(num_arg(n)), text_arg(new)
    if a < 1 or k < 0:
        return VALUE
    return t[:a - 1] + s + t[a - 1 + k:]


@register("REPT", "Text")
def _rept(text, n):
    k = int(num_arg(n))
    return VALUE if k < 0 else text_arg(text) * k


@register("EXACT", "Text")
def _exact(a, b):
    return text_arg(a) == text_arg(b)


@register("CHAR", "Text")
def _char(n):
    k = int(num_arg(n))
    return VALUE if k < 1 or k > 255 else bytes([k]).decode("cp1252", errors="replace")


@register("CODE", "Text")
def _code(t):
    s = text_arg(t)
    if not s:
        return VALUE
    try:
        return float(s[0].encode("cp1252")[0])
    except UnicodeEncodeError:
        return 63.0


@register("UNICHAR", "Text")
def _unichar(n):
    return chr(int(num_arg(n)))


@register("UNICODE", "Text")
def _unicode(t):
    s = text_arg(t)
    return VALUE if not s else float(ord(s[0]))


@register("VALUE", "Text")
def _value(t):
    v = scalar(t)
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return to_number(text_arg(v))


@register("T", "Text")
def _t(v):
    x = scalar(v)
    return x if isinstance(x, str) else ""


@register("TEXT", "Text", "TEXT(value, format_text) shows a number with a number format, like \"0.00\" or \"dd-mm-yyyy\".")
def _text(v, fmt):
    import sheet_numfmt
    x = scalar(v)
    n = to_number(x) if not isinstance(x, str) or not isinstance(to_number(x), XLError) else x
    return sheet_numfmt.format_value(n if not isinstance(n, XLError) else x, text_arg(fmt))[0]


@register("FIXED", "Text")
def _fixed(v, decimals=None, no_commas=None):
    n = num_arg(v)
    d = int(num_arg(decimals)) if decimals is not None else 2
    r = _round_half_away(n, d)
    s = f"{r:,.{max(d, 0)}f}" if not (no_commas is not None and to_bool(scalar(no_commas))) else f"{r:.{max(d, 0)}f}"
    return s


@register("DOLLAR", "Text")
def _dollar(v, decimals=None):
    return "$" + _fixed(v, decimals)


@register("NUMBERVALUE", "Text")
def _numbervalue(t, dec=None, group=None):
    s = text_arg(t)
    d = text_arg(dec) if dec is not None else "."
    g = text_arg(group) if group is not None else ","
    s = s.replace(g, "").replace(d, ".").replace(" ", "")
    return to_number(s)


# Date & time
def date_arg(v):
    n = num_arg(v)
    if n < 0:
        raise _Err(NUM)
    return from_serial(n)


@register("DATE", "Date & Time", "DATE(year, month, day) gives the date's number.")
def _date(y, m, d):
    yy, mm, dd = int(num_arg(y)), int(num_arg(m)), int(num_arg(d))
    if yy < 1900:
        yy += 1900
    yy += (mm - 1) // 12
    mm = (mm - 1) % 12 + 1
    base = dt.datetime(yy, mm, 1) + dt.timedelta(days=dd - 1)
    return to_serial(base)


@register("TIME", "Date & Time")
def _time(h, m, s):
    total = num_arg(h) * 3600 + num_arg(m) * 60 + num_arg(s)
    return (total % 86400) / 86400


@register("TODAY", "Date & Time")
def _today():
    return float(int(to_serial(dt.datetime.now())))


@register("NOW", "Date & Time")
def _now():
    return to_serial(dt.datetime.now())


@register("YEAR", "Date & Time")
def _year(d):
    return float(date_arg(d).year)


@register("MONTH", "Date & Time")
def _month(d):
    return float(date_arg(d).month)


@register("DAY", "Date & Time")
def _day(d):
    return float(date_arg(d).day)


@register("HOUR", "Date & Time")
def _hour(d):
    return float(date_arg(d).hour)


@register("MINUTE", "Date & Time")
def _minute(d):
    return float(date_arg(d).minute)


@register("SECOND", "Date & Time")
def _second(d):
    x = date_arg(d)
    return float(round(x.second + x.microsecond / 1e6) % 60)


@register("WEEKDAY", "Date & Time")
def _weekday(d, kind=None):
    w = date_arg(d).isoweekday()        # Monday 1 .. Sunday 7
    k = int(num_arg(kind)) if kind is not None else 1
    if k == 1:
        return float(w % 7 + 1)
    if k == 2:
        return float(w)
    if k == 3:
        return float(w - 1)
    return NUM


@register("WEEKNUM", "Date & Time")
def _weeknum(d, kind=None):
    x = date_arg(d)
    k = int(num_arg(kind)) if kind is not None else 1
    if k == 21:
        return float(x.isocalendar()[1])
    jan1 = dt.datetime(x.year, 1, 1)
    start = 6 if k == 1 else 0           # Sunday or Monday
    offset = (jan1.weekday() - start) % 7
    return float((x - jan1).days + offset) // 7 + 1


@register("ISOWEEKNUM", "Date & Time")
def _isoweeknum(d):
    return float(date_arg(d).isocalendar()[1])


@register("DATEVALUE", "Date & Time")
def _datevalue(t):
    v = parse_date(text_arg(t))
    return VALUE if v is None else float(int(v))


@register("TIMEVALUE", "Date & Time")
def _timevalue(t):
    v = parse_date(text_arg(t))
    return VALUE if v is None else v % 1


def _add_months(d: dt.datetime, months: int) -> dt.datetime:
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    import calendar
    last = calendar.monthrange(y, m)[1]
    return d.replace(year=y, month=m, day=min(d.day, last))


@register("EDATE", "Date & Time")
def _edate(d, months):
    return float(int(to_serial(_add_months(date_arg(d), int(num_arg(months))))))


@register("EOMONTH", "Date & Time")
def _eomonth(d, months):
    import calendar
    x = _add_months(date_arg(d).replace(day=1), int(num_arg(months)))
    return float(int(to_serial(x.replace(day=calendar.monthrange(x.year, x.month)[1]))))


@register("DATEDIF", "Date & Time")
def _datedif(a, b, unit):
    x, y, u = date_arg(a), date_arg(b), text_arg(unit).upper()
    if y < x:
        return NUM
    if u == "D":
        return float((y - x).days)
    months = (y.year - x.year) * 12 + y.month - x.month - (1 if y.day < x.day else 0)
    if u == "M":
        return float(months)
    if u == "Y":
        return float(months // 12)
    if u == "YM":
        return float(months % 12)
    if u == "MD":
        return float((y - _add_months(x, months)).days)
    if u == "YD":
        z = x.replace(year=y.year)
        if z > y:
            z = x.replace(year=y.year - 1)
        return float((y - z).days)
    return NUM


@register("DAYS", "Date & Time")
def _days(end, start):
    return float(int(num_arg(end)) - int(num_arg(start)))


def _holidays(h):
    if h is None:
        return set()
    return {int(x) for x in nums([h])}


@register("NETWORKDAYS", "Date & Time")
def _networkdays(a, b, hol=None):
    x, y = int(num_arg(a)), int(num_arg(b))
    sign = 1
    if y < x:
        x, y, sign = y, x, -1
    hs = _holidays(hol)
    n = sum(1 for d in range(x, y + 1) if from_serial(d).weekday() < 5 and d not in hs)
    return float(n * sign)


@register("WORKDAY", "Date & Time")
def _workday(a, days, hol=None):
    d, k = int(num_arg(a)), int(num_arg(days))
    hs = _holidays(hol)
    step = 1 if k >= 0 else -1
    while k:
        d += step
        if from_serial(d).weekday() < 5 and d not in hs:
            k -= step
    return float(d)


@register("YEARFRAC", "Date & Time")
def _yearfrac(a, b, basis=None):
    x, y = date_arg(a), date_arg(b)
    if y < x:
        x, y = y, x
    k = int(num_arg(basis)) if basis is not None else 0
    if k == 0:
        d1, d2 = min(x.day, 30), y.day
        if d2 == 31 and d1 >= 30:
            d2 = 30
        return ((y.year - x.year) * 360 + (y.month - x.month) * 30 + (d2 - d1)) / 360
    days = (y - x).days
    return days / (365.0 if k in (1, 3) else 360.0)


# Lookup & reference
def _match_index(lookup, values, kind):
    if kind == 0:
        if isinstance(lookup, str) and any(ch in lookup for ch in "*?"):
            t = _criteria(lookup)
            for i, v in enumerate(values):
                if t(v):
                    return i
            return None
        for i, v in enumerate(values):
            if v is not None and compare(v, lookup) == 0 and (isinstance(v, str) == isinstance(lookup, str)):
                return i
        return None
    best = None
    for i, v in enumerate(values):
        if v is None or isinstance(v, str) != isinstance(lookup, str):
            continue
        c = compare(v, lookup)
        if kind > 0:
            if c <= 0:
                best = i
            else:
                break
        else:
            if c >= 0:
                best = i
            else:
                break
    return best


@register("VLOOKUP", "Lookup & Reference",
          "VLOOKUP(lookup_value, table_array, col_index_num, [range_lookup]) finds a value in the first column and returns one from the same row.")
def _vlookup(lookup, table, col, approx=None):
    if not isinstance(table, (Range, Array)):
        return VALUE
    v = scalar(lookup)
    if isinstance(v, XLError):
        return v
    k = int(num_arg(col))
    if k < 1:
        return VALUE
    if k > table.cols:
        return REF
    exact = approx is not None and not to_bool(scalar(approx))
    first_col = [table.value(r, 0) for r in range(table.rows)]
    i = _match_index(v, first_col, 0 if exact else 1)
    return NA if i is None else table.value(i, k - 1)


@register("HLOOKUP", "Lookup & Reference")
def _hlookup(lookup, table, row, approx=None):
    if not isinstance(table, (Range, Array)):
        return VALUE
    v = scalar(lookup)
    k = int(num_arg(row))
    if k < 1:
        return VALUE
    if k > table.rows:
        return REF
    exact = approx is not None and not to_bool(scalar(approx))
    first_row = [table.value(0, c) for c in range(table.cols)]
    i = _match_index(v, first_row, 0 if exact else 1)
    return NA if i is None else table.value(k - 1, i)


@register("LOOKUP", "Lookup & Reference")
def _lookup(lookup, vec, result=None):
    v = scalar(lookup)
    vals = list(vec) if isinstance(vec, (Range, Array)) else [vec]
    i = _match_index(v, vals, 1)
    if i is None:
        return NA
    res = list(result) if isinstance(result, (Range, Array)) else vals
    return res[i] if i < len(res) else NA


@register("MATCH", "Lookup & Reference", "MATCH(lookup_value, lookup_array, [match_type]) gives the position of a value.")
def _match(lookup, arr, kind=None):
    v = scalar(lookup)
    vals = list(arr) if isinstance(arr, (Range, Array)) else [arr]
    k = int(num_arg(kind)) if kind is not None else 1
    i = _match_index(v, vals, 0 if k == 0 else (1 if k > 0 else -1))
    return NA if i is None else float(i + 1)


@register("XLOOKUP", "Lookup & Reference")
def _xlookup(lookup, arr, ret, if_not_found=None, mode=None, search=None):
    v = scalar(lookup)
    vals = list(arr) if isinstance(arr, (Range, Array)) else [arr]
    m = int(num_arg(mode)) if mode is not None else 0
    rev = search is not None and num_arg(search) < 0
    idx = range(len(vals) - 1, -1, -1) if rev else range(len(vals))
    found = None
    if m == 0 or m == 2:
        t = _criteria(v) if m == 2 and isinstance(v, str) else None
        for i in idx:
            if (t(vals[i]) if t else (vals[i] is not None and compare(vals[i], v) == 0)):
                found = i
                break
    else:
        best = None
        for i in idx:
            x = vals[i]
            if x is None:
                continue
            c = compare(x, v)
            if c == 0:
                found = i
                break
            if m == -1 and c < 0 and (best is None or compare(x, vals[best]) > 0):
                best = i
            if m == 1 and c > 0 and (best is None or compare(x, vals[best]) < 0):
                best = i
        if found is None:
            found = best
    if found is None:
        return if_not_found if if_not_found is not None else NA
    if isinstance(ret, (Range, Array)):
        if ret.rows == len(vals) and ret.cols >= 1:
            return ret.value(found, 0) if ret.cols == 1 else Array([[ret.value(found, c) for c in range(ret.cols)]])
        if ret.cols == len(vals):
            return ret.value(0, found)
    return VALUE


@register("INDEX", "Lookup & Reference", "INDEX(array, row_num, [column_num]) gives the value at a row and column.")
def _index(arr, row=None, col=None):
    if not isinstance(arr, (Range, Array)):
        return arr if (row is None or num_arg(row) in (0, 1)) else REF
    r = int(num_arg(row)) if row is not None else 0
    c = int(num_arg(col)) if col is not None else 0
    if arr.rows == 1 and col is None:
        r, c = 1, r
    if r < 0 or c < 0 or r > arr.rows or c > arr.cols:
        return REF
    if isinstance(arr, Range):
        if r == 0 and c == 0:
            return arr
        if r == 0:
            return Range(arr.ctx, arr.sheet, arr.r1, arr.c1 + c - 1, arr.r2, arr.c1 + c - 1)
        if c == 0:
            if arr.cols == 1:
                return arr.value(r - 1, 0)
            return Range(arr.ctx, arr.sheet, arr.r1 + r - 1, arr.c1, arr.r1 + r - 1, arr.c2)
        return Range(arr.ctx, arr.sheet, arr.r1 + r - 1, arr.c1 + c - 1, arr.r1 + r - 1, arr.c1 + c - 1)
    return arr.value(max(r, 1) - 1, max(c, 1) - 1)


@register("CHOOSE", "Lookup & Reference")
def _choose(i, *opts):
    k = int(num_arg(i))
    if k < 1 or k > len(opts):
        return VALUE
    return opts[k - 1]


@fn("ROW", "Lookup & Reference", lazy=True)
def _row(ctx, args):
    if not args:
        return float(ctx.row + 1)
    node = args[0]
    return float(node[2] + 1) if node[0] == "ref" else VALUE


@fn("COLUMN", "Lookup & Reference", lazy=True)
def _column(ctx, args):
    if not args:
        return float(ctx.col + 1)
    node = args[0]
    return float(node[3] + 1) if node[0] == "ref" else VALUE


@register("ROWS", "Lookup & Reference")
def _rows(a):
    return float(a.rows) if isinstance(a, (Range, Array)) else 1.0


@register("COLUMNS", "Lookup & Reference")
def _columns(a):
    return float(a.cols) if isinstance(a, (Range, Array)) else 1.0


@fn("OFFSET", "Lookup & Reference", ctx=True)
def _offset(ctx, ref, rows, cols, height=None, width=None):
    if not isinstance(ref, Range):
        return VALUE
    try:
        dr, dc = int(num_arg(rows)), int(num_arg(cols))
        h = int(num_arg(height)) if height is not None else ref.rows
        w = int(num_arg(width)) if width is not None else ref.cols
    except _Err as e:
        return e.e
    r1, c1 = ref.r1 + dr, ref.c1 + dc
    if r1 < 0 or c1 < 0 or h < 1 or w < 1:
        return REF
    return Range(ctx, ref.sheet, r1, c1, r1 + h - 1, c1 + w - 1)


@fn("INDIRECT", "Lookup & Reference", ctx=True)
def _indirect(ctx, text, a1=None):
    t = to_text(scalar(text))
    if isinstance(t, XLError):
        return t
    try:
        node = parse_ref(t) if re.search(r"\d|:", t) else None
    except Exception:  # noqa: BLE001
        node = None
    if not node or node[0] != "ref":
        target = ctx.book.defined_name(t, ctx.sheet)
        return evaluate(target, ctx) if isinstance(target, tuple) else REF
    sheet = node[1] or ctx.sheet
    if not ctx.book.has_sheet(sheet):
        return REF
    return Range(ctx, sheet, *node[2:6])


@fn("ADDRESS", "Lookup & Reference")
def _address(row, col, abs_num=None, a1=None, sheet=None):
    from sheet_ref import col_name, quote_sheet
    try:
        r, c = int(num_arg(row)), int(num_arg(col))
        k = int(num_arg(abs_num)) if abs_num is not None else 1
    except _Err as e:
        return e.e
    ar, ac = k in (1, 2), k in (1, 3)
    s = f"{'$' if ac else ''}{col_name(c - 1)}{'$' if ar else ''}{r}"
    if sheet is not None:
        s = quote_sheet(to_text(scalar(sheet))) + "!" + s
    return s


@register("TRANSPOSE", "Lookup & Reference")
def _transpose(a):
    if not isinstance(a, (Range, Array)):
        return a
    m = a.matrix()
    return Array([list(r) for r in zip(*m)])


@register("UNIQUE", "Lookup & Reference")
def _unique(a):
    seen, out = set(), []
    for v in (list(a) if isinstance(a, (Range, Array)) else [a]):
        key = v.lower() if isinstance(v, str) else v
        if key not in seen and v is not None:
            seen.add(key)
            out.append([v])
    return Array(out or [[None]])


@register("SORT", "Lookup & Reference")
def _sort(a, idx=None, order=None, by_col=None):
    if not isinstance(a, (Range, Array)):
        return a
    m = a.matrix()
    k = int(num_arg(idx)) - 1 if idx is not None else 0
    desc = order is not None and num_arg(order) < 0
    import functools
    m = sorted(m, key=functools.cmp_to_key(lambda x, y: compare(x[k], y[k])), reverse=desc)
    return Array(m)


@register("FILTER", "Lookup & Reference")
def _filter(a, include, empty=None):
    if not isinstance(a, (Range, Array)):
        return a
    m = a.matrix()
    inc = list(include) if isinstance(include, (Range, Array)) else [include]
    rows = [row for row, keep in zip(m, inc) if to_bool(keep) is True]
    if not rows:
        return empty if empty is not None else XLError("#CALC!")
    return Array(rows)


@register("SEQUENCE", "Math & Trig")
def _sequence(rows, cols=None, start=None, step=None):
    r = int(num_arg(rows))
    c = int(num_arg(cols)) if cols is not None else 1
    s = num_arg(start) if start is not None else 1.0
    st = num_arg(step) if step is not None else 1.0
    return Array([[s + (i * c + j) * st for j in range(c)] for i in range(r)])


# Financial
@register("PMT", "Financial", "PMT(rate, nper, pv, [fv], [type]) gives the payment for a loan.")
def _pmt(rate, nper, pv, fv=None, typ=None):
    r, n, p = num_arg(rate), num_arg(nper), num_arg(pv)
    f = num_arg(fv) if fv is not None else 0.0
    t = num_arg(typ) if typ is not None else 0.0
    if n == 0:
        return NUM
    if r == 0:
        return -(p + f) / n
    return -(r * (p * (1 + r) ** n + f)) / ((1 + r * t) * ((1 + r) ** n - 1))


@register("FV", "Financial")
def _fv(rate, nper, pmt, pv=None, typ=None):
    r, n, m = num_arg(rate), num_arg(nper), num_arg(pmt)
    p = num_arg(pv) if pv is not None else 0.0
    t = num_arg(typ) if typ is not None else 0.0
    if r == 0:
        return -(p + m * n)
    return -(p * (1 + r) ** n + m * (1 + r * t) * ((1 + r) ** n - 1) / r)


@register("PV", "Financial")
def _pv(rate, nper, pmt, fv=None, typ=None):
    r, n, m = num_arg(rate), num_arg(nper), num_arg(pmt)
    f = num_arg(fv) if fv is not None else 0.0
    t = num_arg(typ) if typ is not None else 0.0
    if r == 0:
        return -(f + m * n)
    return -(f + m * (1 + r * t) * ((1 + r) ** n - 1) / r) / (1 + r) ** n


@register("NPER", "Financial")
def _nper(rate, pmt, pv, fv=None, typ=None):
    r, m, p = num_arg(rate), num_arg(pmt), num_arg(pv)
    f = num_arg(fv) if fv is not None else 0.0
    t = num_arg(typ) if typ is not None else 0.0
    if r == 0:
        return NUM if m == 0 else -(p + f) / m
    a = m * (1 + r * t) - f * r
    b = p * r + m * (1 + r * t)
    if a / b <= 0:
        return NUM
    return math.log(a / b) / math.log(1 + r)


@register("NPV", "Financial")
def _npv(rate, *values):
    r = num_arg(rate)
    return math.fsum(v / (1 + r) ** (i + 1) for i, v in enumerate(nums(values)))


@register("IRR", "Financial")
def _irr(values, guess=None):
    v = nums([values])
    r = num_arg(guess) if guess is not None else 0.1
    for _ in range(100):
        f = sum(x / (1 + r) ** i for i, x in enumerate(v))
        d = sum(-i * x / (1 + r) ** (i + 1) for i, x in enumerate(v))
        if d == 0:
            return NUM
        nr = r - f / d
        if abs(nr - r) < 1e-10:
            return nr
        r = nr
    return NUM


@register("RATE", "Financial")
def _rate(nper, pmt, pv, fv=None, typ=None, guess=None):
    n, m, p = num_arg(nper), num_arg(pmt), num_arg(pv)
    f = num_arg(fv) if fv is not None else 0.0
    t = num_arg(typ) if typ is not None else 0.0
    r = num_arg(guess) if guess is not None else 0.1
    for _ in range(100):
        if abs(r) < 1e-12:
            y = p + m * n + f
            dy = m * n * (n - 1) / 2 + p * n
        else:
            q = (1 + r) ** n
            y = p * q + m * (1 + r * t) * (q - 1) / r + f
            dq = n * (1 + r) ** (n - 1)
            dy = p * dq + m * t * (q - 1) / r + m * (1 + r * t) * (dq * r - (q - 1)) / (r * r)
        if dy == 0:
            return NUM
        nr = r - y / dy
        if abs(nr - r) < 1e-10:
            return nr
        r = nr
    return NUM


@register("IPMT", "Financial")
def _ipmt(rate, per, nper, pv, fv=None, typ=None):
    r = num_arg(rate)
    payment = _pmt(rate, nper, pv, fv, typ)
    if isinstance(payment, XLError):
        return payment
    k = int(num_arg(per))
    bal = _fv(rate, float(k - 1), payment, pv, typ)
    return -bal * r if not (typ is not None and num_arg(typ) == 1 and k == 1) else 0.0


@register("PPMT", "Financial")
def _ppmt(rate, per, nper, pv, fv=None, typ=None):
    p = _pmt(rate, nper, pv, fv, typ)
    i = _ipmt(rate, per, nper, pv, fv, typ)
    if isinstance(p, XLError):
        return p
    if isinstance(i, XLError):
        return i
    return p - i


@register("SLN", "Financial")
def _sln(cost, salvage, life):
    lf = num_arg(life)
    return DIV0 if lf == 0 else (num_arg(cost) - num_arg(salvage)) / lf


# Engineering-ish conversions people use
@register("DEC2BIN", "Engineering")
def _dec2bin(n, places=None):
    s = bin(int(num_arg(n)))[2:]
    return s.zfill(int(num_arg(places))) if places is not None else s


@register("BIN2DEC", "Engineering")
def _bin2dec(s):
    return float(int(text_arg(s), 2))


@register("DEC2HEX", "Engineering")
def _dec2hex(n, places=None):
    s = format(int(num_arg(n)), "X")
    return s.zfill(int(num_arg(places))) if places is not None else s


@register("HEX2DEC", "Engineering")
def _hex2dec(s):
    return float(int(text_arg(s), 16))


@register("CONVERT", "Engineering")
def _convert(n, frm, to):
    units = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048, "yd": 0.9144,
             "mi": 1609.344, "g": 1.0, "kg": 1000.0, "lbm": 453.59237, "ozm": 28.349523125,
             "l": 1.0, "ml": 0.001, "gal": 3.785411784}
    temps = {"C", "F", "K"}
    v, a, b = num_arg(n), text_arg(frm), text_arg(to)
    if a in temps and b in temps:
        c = v if a == "C" else (v - 32) * 5 / 9 if a == "F" else v - 273.15
        return c if b == "C" else c * 9 / 5 + 32 if b == "F" else c + 273.15
    if a in units and b in units:
        return v * units[a] / units[b]
    return NA


# ---- formula help for the Insert Function dialog -------------------------------------------------
def describe(name: str) -> str:
    return HELP.get(name, "")


def all_function_names() -> list[str]:
    return sorted(FUNCTIONS)
