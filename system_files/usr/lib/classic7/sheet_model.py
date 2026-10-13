"""The workbook behind Sheet: sheets of cells with values, formulas and styles, the
calculation engine (what depends on what, recalculating only what changed), and undo."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, replace

import sheet_formula as F
import sheet_numfmt as NF
from sheet_ref import MAX_COLS, MAX_ROWS, adjust_for_insert, quote_sheet, rename_sheet_in_formula, shift_formula

DEFAULT_FONT = "Calibri"
DEFAULT_SIZE = 11.0
DEFAULT_COL_WIDTH = 8.43          # characters, like Excel
DEFAULT_ROW_HEIGHT = 15.0         # points

# Excel's 64 indexed colours (used by old files and [ColorN] formats)
INDEXED_COLORS = [
    "#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff",
    "#000000", "#ffffff", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff",
    "#800000", "#008000", "#000080", "#808000", "#800080", "#008080", "#c0c0c0", "#808080",
    "#9999ff", "#993366", "#ffffcc", "#ccffff", "#660066", "#ff8080", "#0066cc", "#ccccff",
    "#000080", "#ff00ff", "#ffff00", "#00ffff", "#800080", "#800000", "#008080", "#0000ff",
    "#00ccff", "#ccffff", "#ccffcc", "#ffff99", "#99ccff", "#ff99cc", "#cc99ff", "#ffcc99",
    "#3366ff", "#33cccc", "#99cc00", "#ffcc00", "#ff9900", "#ff6600", "#666699", "#969696",
    "#003366", "#339966", "#003300", "#333300", "#993300", "#993366", "#333399", "#333333",
]

# Office 2007 theme colours (Office theme): dk1 lt1 dk2 lt2 accent1..6 hlink folHlink
THEME_COLORS = ["#000000", "#ffffff", "#1f497d", "#eeece1", "#4f81bd", "#c0504d", "#9bbb59", "#8064a2",
                "#4bacc6", "#f79646", "#0000ff", "#800080"]


@dataclass(frozen=True)
class Border:
    style: str = ""              # "", thin, medium, thick, dashed, dotted, double, hair
    color: str = "#000000"


NO_BORDER = Border()


@dataclass(frozen=True)
class Style:
    font: str = DEFAULT_FONT
    size: float = DEFAULT_SIZE
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    color: str = "#000000"
    fill: str | None = None              # background colour
    halign: str = "general"              # general left center right fill justify centerContinuous
    valign: str = "bottom"               # top center bottom
    wrap: bool = False
    indent: int = 0
    rotation: int = 0
    shrink: bool = False
    numfmt: str = "General"
    left: Border = NO_BORDER
    right: Border = NO_BORDER
    top: Border = NO_BORDER
    bottom: Border = NO_BORDER
    locked: bool = True


DEFAULT_STYLE = Style()


class Cell:
    """A cell is never changed in place (undo keeps the old object)."""
    __slots__ = ("value", "formula", "style")

    def __init__(self, value=None, formula: str | None = None, style: int = 0):
        self.value = value
        self.formula = formula
        self.style = style

    def copy(self, **kw) -> "Cell":
        c = Cell(self.value, self.formula, self.style)
        for k, v in kw.items():
            setattr(c, k, v)
        return c

    @property
    def empty(self) -> bool:
        return self.value is None and self.formula is None

    def __repr__(self):
        return f"Cell({self.value!r}, {self.formula!r}, {self.style})"


@dataclass
class ChartSeries:
    name: str = ""                 # text, or a reference like Sheet1!$B$1
    values: str = ""               # Sheet1!$B$2:$B$10
    categories: str = ""           # Sheet1!$A$2:$A$10 (or x values for scatter)
    color: str | None = None


@dataclass
class Chart:
    kind: str = "col"              # col bar line area pie doughnut scatter radar
    grouping: str = "clustered"    # clustered stacked percentStacked standard
    title: str = ""
    series: list[ChartSeries] = field(default_factory=list)
    anchor: tuple[int, int, int, int] = (1, 4, 16, 11)    # from row, from col, to row, to col
    offsets: tuple[float, float, float, float] = (0, 0, 0, 0)
    legend: str = "r"              # r b t l, or "" for none
    x_title: str = ""
    y_title: str = ""
    style: int = 2
    raw: bytes | None = None       # the chart part as read, kept if the chart isn't changed
    data_labels: bool = False
    smooth: bool = False


@dataclass
class CondRule:
    """Conditional formatting: cell value is (between, >, <, =...) or a formula; fill/font colour."""
    ranges: list[tuple[int, int, int, int]]
    kind: str = "cellIs"           # cellIs, expression, colorScale, dataBar, top10, aboveAverage, containsText
    operator: str = "greaterThan"
    formulas: list[str] = field(default_factory=list)
    fill: str | None = None
    color: str | None = None
    bold: bool = False
    colors: list[str] = field(default_factory=list)  # colour scale / data bar
    rank: int = 10
    percent: bool = False
    bottom: bool = False
    text: str = ""
    priority: int = 1
    stop: bool = False


@dataclass
class Validation:
    ranges: list[tuple[int, int, int, int]]
    kind: str = "list"             # list whole decimal date textLength custom
    formula1: str = ""
    formula2: str = ""
    operator: str = "between"
    allow_blank: bool = True
    show_dropdown: bool = True
    error: str = ""
    prompt: str = ""


@dataclass
class PageSetup:
    orientation: str = "portrait"
    paper: str = "A4"
    margins: tuple[float, float, float, float] = (0.7, 0.7, 0.75, 0.75)   # left right top bottom (inches)
    header_margin: float = 0.3
    footer_margin: float = 0.3
    fit_width: int = 0             # 0 = not fitted
    fit_height: int = 0
    scale: int = 100
    gridlines: bool = False
    headings: bool = False
    center_h: bool = False
    center_v: bool = False
    header: str = ""
    footer: str = "Page &P"
    print_area: tuple[int, int, int, int] | None = None
    title_rows: tuple[int, int] | None = None
    title_cols: tuple[int, int] | None = None
    order: str = "downThenOver"


class Worksheet:
    def __init__(self, book: "Workbook", name: str):
        self.book = book
        self.name = name
        self.cells: dict[tuple[int, int], Cell] = {}
        self.col_widths: dict[int, float] = {}
        self.row_heights: dict[int, float] = {}
        self.hidden_rows: set[int] = set()
        self.hidden_cols: set[int] = set()
        self.col_styles: dict[int, int] = {}
        self.row_styles: dict[int, int] = {}
        self.merges: list[tuple[int, int, int, int]] = []
        self.freeze: tuple[int, int] | None = None        # top-left cell of the unfrozen part
        self.autofilter: tuple[int, int, int, int] | None = None
        self.filters: dict[int, set] = {}                 # column -> values shown (text)
        self.charts: list[Chart] = []
        self.images: list[dict] = []                      # {"data": bytes, "anchor": (r, c), "size": (w, h)}
        self.cond: list[CondRule] = []
        self.validations: list[Validation] = []
        self.comments: dict[tuple[int, int], str] = {}
        self.links: dict[tuple[int, int], str] = {}
        self.page = PageSetup()
        self.tab_color: str | None = None
        self.zoom = 100
        self.show_grid = True
        self.show_headers = True
        self.show_zeros = True
        self.default_width = DEFAULT_COL_WIDTH
        self.default_height = DEFAULT_ROW_HEIGHT
        self.active = (0, 0)
        self.selection = [(0, 0, 0, 0)]
        self.top_left = (0, 0)
        self.hidden = False

    # ---- extents
    def used_range(self) -> tuple[int, int, int, int] | None:
        if not self.cells:
            return None
        rows = [r for (r, c), cell in self.cells.items() if not cell.empty or cell.style]
        cols = [c for (r, c), cell in self.cells.items() if not cell.empty or cell.style]
        if not rows:
            return None
        return min(rows), min(cols), max(rows), max(cols)

    _ext = None

    def extent(self) -> tuple[int, int]:
        """Last used row and column (cached; Workbook.put keeps it up to date)."""
        if self._ext is None or self._ext[2] is not self.cells:
            if not self.cells:
                self._ext = (0, 0, self.cells)
            else:
                self._ext = (max(r for r, _ in self.cells), max(c for _, c in self.cells), self.cells)
        return self._ext[0], self._ext[1]

    def grew(self, r: int, c: int):
        if self._ext is not None and self._ext[2] is self.cells:
            self._ext = (max(self._ext[0], r), max(self._ext[1], c), self.cells)

    def shrank(self):
        self._ext = None

    def get(self, r: int, c: int) -> Cell | None:
        return self.cells.get((r, c))

    def style_of(self, r: int, c: int) -> Style:
        cell = self.cells.get((r, c))
        if cell is not None and cell.style:
            return self.book.styles[cell.style]
        if r in self.row_styles:
            return self.book.styles[self.row_styles[r]]
        if c in self.col_styles:
            return self.book.styles[self.col_styles[c]]
        return self.book.styles[0]

    def style_index(self, r: int, c: int) -> int:
        cell = self.cells.get((r, c))
        if cell is not None and cell.style:
            return cell.style
        return self.row_styles.get(r, self.col_styles.get(c, 0))

    def merge_at(self, r: int, c: int) -> tuple[int, int, int, int] | None:
        for m in self.merges:
            if m[0] <= r <= m[2] and m[1] <= c <= m[3]:
                return m
        return None

    def col_width(self, c: int) -> float:
        if c in self.hidden_cols:
            return 0.0
        return self.col_widths.get(c, self.default_width)

    def row_height(self, r: int) -> float:
        if r in self.hidden_rows:
            return 0.0
        return self.row_heights.get(r, self.default_height)


# ---- undo ----------------------------------------------------------------------------------------
@dataclass
class Change:
    label: str
    cells: list[tuple[str, int, int, Cell | None, Cell | None]] = field(default_factory=list)
    snapshot_before: dict | None = None     # whole-sheet state for structural changes
    snapshot_after: dict | None = None
    selection: tuple | None = None


SHEET_STATE = ("cells", "col_widths", "row_heights", "hidden_rows", "hidden_cols", "col_styles", "row_styles",
               "merges", "freeze", "autofilter", "filters", "charts", "images", "cond", "validations", "comments",
               "links", "page", "tab_color", "name", "hidden", "show_grid", "zoom")


class Workbook:
    def __init__(self):
        self.sheets: list[Worksheet] = []
        self.styles: list[Style] = [DEFAULT_STYLE]
        self._style_ids: dict[Style, int] = {DEFAULT_STYLE: 0}
        self.names: dict[str, str] = {}                 # global defined names -> "=Sheet1!$A$1:$B$5"
        self.local_names: dict[tuple[str, str], str] = {}
        self.active = 0
        self.path: str | None = None
        self.modified = False
        self.calc_auto = True
        self.circular: set[tuple[str, int, int]] = set()
        self.undo_stack: list[Change] = []
        self.redo_stack: list[Change] = []
        self._pending: Change | None = None
        self._depth = 0
        # calculation
        self._deps: dict[tuple, list] = {}             # formula cell -> its references
        self._cell_deps: dict[tuple, set] = {}         # (sheet, r, c) -> formula cells using it
        self._range_deps: dict[str, list] = {}         # sheet -> [(r1, c1, r2, c2, formula cell)]
        self._name_deps: dict[str, set] = {}           # defined name -> formula cells
        self._volatile: set[tuple] = set()
        self._dirty: set[tuple] = set()
        self._computing: set[tuple] = set()
        self._by_name: dict[str, Worksheet] = {}
        self._parsed_names: dict[str, tuple] = {}
        self.theme_colors = list(THEME_COLORS)
        self.theme_fonts = ("Cambria", "Calibri")
        self.extra_parts: dict = {}

    # ---- sheets
    def add_sheet(self, name: str | None = None, at: int | None = None) -> Worksheet:
        name = name or self.unique_name("Sheet")
        ws = Worksheet(self, name)
        if at is None:
            self.sheets.append(ws)
        else:
            self.sheets.insert(at, ws)
        self._by_name[name.lower()] = ws
        return ws

    def unique_name(self, base: str) -> str:
        i = 1
        while self.sheet(f"{base}{i}") is not None:
            i += 1
        return f"{base}{i}"

    def sheet(self, name: str) -> Worksheet | None:
        return self._by_name.get(name.lower())

    def has_sheet(self, name: str) -> bool:
        return name.lower() in self._by_name

    def reindex(self):
        self._by_name = {ws.name.lower(): ws for ws in self.sheets}

    @property
    def ws(self) -> Worksheet:
        return self.sheets[self.active]

    # ---- styles
    def style_id(self, style: Style) -> int:
        i = self._style_ids.get(style)
        if i is None:
            i = len(self.styles)
            self.styles.append(style)
            self._style_ids[style] = i
        return i

    # ---- values (the formula engine reads through these)
    def value(self, sheet: str, r: int, c: int):
        ws = self._by_name.get(sheet.lower())
        if ws is None:
            return F.REF
        cell = ws.cells.get((r, c))
        if cell is None:
            return None
        if cell.formula is not None:
            key = (ws.name, r, c)
            if key in self._dirty:
                self._compute(key, ws, cell)
                cell = ws.cells.get((r, c))
        v = cell.value
        if isinstance(v, (F.Range, F.Array)):
            return F.first(v)
        return v

    def used_extent(self, sheet: str) -> tuple[int, int]:
        ws = self._by_name.get(sheet.lower())
        return ws.extent() if ws else (0, 0)

    def cells_in(self, sheet: str, r1, c1, r2, c2):
        ws = self._by_name.get(sheet.lower())
        if not ws:
            return []
        er, ec = ws.extent()
        r2, c2 = min(r2, er), min(c2, ec)
        if (r2 - r1 + 1) * (c2 - c1 + 1) <= len(ws.cells):
            cells = ws.cells
            return [(r, c) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1) if (r, c) in cells]
        return sorted(k for k in ws.cells if r1 <= k[0] <= r2 and c1 <= k[1] <= c2)

    def defined_name(self, name: str, sheet: str):
        key = name.upper()
        text = self.local_names.get((sheet.lower(), key)) or next(
            (v for k, v in self.names.items() if k.upper() == key), None)
        if text is None:
            return None
        tree = self._parsed_names.get(text)
        if tree is None:
            try:
                tree = F.parse(text if text.startswith("=") else "=" + text)
            except F.FormulaError:
                return F.NAME
            self._parsed_names[text] = tree
        return tree

    # ---- dependencies
    def _register(self, key, cell: Cell):
        self._unregister(key)
        if cell.formula is None:
            return
        try:
            tree = F.parse(cell.formula)
        except F.FormulaError:
            return
        refs = F.references(tree)
        self._deps[key] = refs
        sheet = key[0]
        for ref in refs:
            if ref[0] == "name":
                self._name_deps.setdefault(ref[1].upper(), set()).add(key)
                target = self.defined_name(ref[1], sheet)
                if isinstance(target, tuple):
                    for sub in F.references(target):
                        if sub[0] == "ref":
                            self._add_ref(sub, sheet, key)
                continue
            self._add_ref(ref, sheet, key)
        if F.is_volatile(tree):
            self._volatile.add(key)

    def _add_ref(self, ref, sheet, key):
        s = (ref[1] or sheet)
        ws = self.sheet(s)
        s = ws.name if ws else s
        r1, c1, r2, c2 = ref[2:6]
        if r1 == r2 and c1 == c2:
            self._cell_deps.setdefault((s, r1, c1), set()).add(key)
        else:
            self._range_deps.setdefault(s, []).append((r1, c1, r2, c2, key))

    def _unregister(self, key):
        refs = self._deps.pop(key, None)
        self._volatile.discard(key)
        if not refs:
            return
        for ref in refs:
            if ref[0] == "name":
                self._name_deps.get(ref[1].upper(), set()).discard(key)
                target = self.defined_name(ref[1], key[0])
                if isinstance(target, tuple):
                    for sub in F.references(target):
                        if sub[0] == "ref":
                            self._remove_ref(sub, key)
                continue
            self._remove_ref(ref, key)

    def _remove_ref(self, ref, key):
        s = ref[1] or key[0]
        ws = self.sheet(s)
        s = ws.name if ws else s
        r1, c1, r2, c2 = ref[2:6]
        if r1 == r2 and c1 == c2:
            deps = self._cell_deps.get((s, r1, c1))
            if deps:
                deps.discard(key)
        else:
            lst = self._range_deps.get(s)
            if lst:
                self._range_deps[s] = [x for x in lst if x[4] != key]

    def dependents(self, sheet: str, r: int, c: int) -> set:
        out = set(self._cell_deps.get((sheet, r, c), ()))
        for r1, c1, r2, c2, key in self._range_deps.get(sheet, ()):
            if r1 <= r <= r2 and c1 <= c <= c2:
                out.add(key)
        return out

    def _mark_dirty(self, starts):
        todo = list(starts)
        seen = set()
        while todo:
            k = todo.pop()
            if k in seen:
                continue
            seen.add(k)
            ws = self.sheet(k[0])
            cell = ws.cells.get((k[1], k[2])) if ws else None
            if cell is not None and cell.formula is not None:
                self._dirty.add(k)
            todo.extend(self.dependents(*k))
        return seen

    def _compute(self, key, ws: Worksheet, cell: Cell):
        if key in self._computing:
            self.circular.add(key)
            return
        self._computing.add(key)
        try:
            try:
                tree = F.parse(cell.formula)
                v = F.evaluate(tree, F.Context(self, ws.name, key[1], key[2]))
            except F.FormulaError:
                v = F.NAME
            except RecursionError:
                v = F.NUM
            if isinstance(v, F.Range):
                v = F.scalar(v, F.Context(self, ws.name, key[1], key[2]))
            elif isinstance(v, F.Array):
                v = v.value(0, 0) if v.rows and v.cols else None
            if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                v = F.NUM
            if key in self.circular:
                v = 0.0
            current = ws.cells.get((key[1], key[2]))
            if current is not None:
                current.value = v       # cached result: not part of undo
        finally:
            self._computing.discard(key)
            self._dirty.discard(key)

    def recalc(self, keys=None):
        """Recalculate dirty cells (all formula cells if keys is 'all')."""
        if keys == "all":
            self.circular.clear()
            for ws in self.sheets:
                for (r, c), cell in ws.cells.items():
                    if cell.formula is not None:
                        self._dirty.add((ws.name, r, c))
        self._dirty |= self._volatile
        for key in list(self._dirty):
            ws = self.sheet(key[0])
            if not ws:
                self._dirty.discard(key)
                continue
            cell = ws.cells.get((key[1], key[2]))
            if cell is None or cell.formula is None:
                self._dirty.discard(key)
                continue
            if key in self._dirty:
                self._compute(key, ws, cell)

    def rebuild_dependencies(self):
        self._deps.clear()
        self._cell_deps.clear()
        self._range_deps.clear()
        self._name_deps.clear()
        self._volatile.clear()
        self._parsed_names.clear()
        self.reindex()
        for ws in self.sheets:
            for (r, c), cell in ws.cells.items():
                if cell.formula is not None:
                    self._register((ws.name, r, c), cell)

    # ---- changing cells (with undo)
    def begin(self, label: str):
        if self._depth == 0:
            self._pending = Change(label)
        self._depth += 1

    def end(self):
        self._depth -= 1
        if self._depth == 0 and self._pending is not None:
            ch = self._pending
            self._pending = None
            if ch.cells or ch.snapshot_before is not None:
                self.undo_stack.append(ch)
                if len(self.undo_stack) > 200:
                    self.undo_stack.pop(0)
                self.redo_stack.clear()
                self.modified = True
            if self.calc_auto:
                self.recalc()

    def put(self, ws: Worksheet, r: int, c: int, cell: Cell | None):
        """Replace a cell (None removes it). Records undo, updates dependencies."""
        key = (ws.name, r, c)
        old = ws.cells.get((r, c))
        if cell is not None and cell.empty and not cell.style:
            cell = None
        if old is None and cell is None:
            return
        own = self._pending is None
        if own:
            self.begin("Edit")
        self._pending.cells.append((ws.name, r, c, old, cell))
        if cell is None:
            ws.cells.pop((r, c), None)
            ws.shrank()
        else:
            ws.cells[(r, c)] = cell
            ws.grew(r, c)
        if (old is not None and old.formula is not None) or (cell is not None and cell.formula is not None):
            self._register(key, cell) if cell is not None else self._unregister(key)
            if cell is not None and cell.formula is not None:
                self._dirty.add(key)
        if old is None or cell is None or old.value != cell.value or old.formula != cell.formula:
            self._mark_dirty([key])
        if own:
            self.end()

    def set_input(self, ws: Worksheet, r: int, c: int, text: str, keep_format=True):
        """What the user typed into a cell: a formula, a number, a date, text."""
        old = ws.cells.get((r, c))
        style = old.style if old is not None else ws.style_index(r, c)
        if text.startswith("=") and len(text) > 1:
            try:
                F.parse(text)
            except F.FormulaError as e:
                raise ValueError(f"There's a problem with this formula: {e}") from e
            st = self.styles[style]
            auto = auto_format(text)
            if auto and st.numfmt == "General":
                style = self.style_id(replace(st, numfmt=auto))
            self.put(ws, r, c, Cell(None, normalize_formula(text), style))
            return
        if text.startswith("'"):
            self.put(ws, r, c, Cell(text[1:], None, style))
            return
        value, fmt = NF.parse_input(text)
        if fmt and keep_format:
            st = self.styles[style]
            if st.numfmt == "General" or (NF.is_date_format(fmt) != NF.is_date_format(st.numfmt)):
                style = self.style_id(replace(st, numfmt=fmt))
        self.put(ws, r, c, Cell(value, None, style) if value is not None or style else None)

    def set_style(self, ws: Worksheet, r: int, c: int, **changes):
        cell = ws.cells.get((r, c))
        base = self.styles[cell.style if cell is not None and cell.style else ws.style_index(r, c)]
        new_id = self.style_id(replace(base, **changes))
        if cell is None:
            self.put(ws, r, c, Cell(None, None, new_id))
        elif cell.style != new_id:
            self.put(ws, r, c, cell.copy(style=new_id))

    # ---- structural changes (snapshots)
    def snapshot(self) -> dict:
        state = {}
        for ws in self.sheets:
            d = {}
            for attr in SHEET_STATE:
                v = getattr(ws, attr)
                d[attr] = copy.copy(v) if isinstance(v, (dict, list, set)) else v
            d["charts"] = copy.deepcopy(ws.charts)
            d["cond"] = copy.deepcopy(ws.cond)
            d["page"] = copy.deepcopy(ws.page)
            state[id(ws)] = (ws, d)
        return {"sheets": list(self.sheets), "state": state, "names": dict(self.names), "active": self.active}

    def restore(self, snap: dict):
        self.sheets = list(snap["sheets"])
        for _, (ws, d) in snap["state"].items():
            for attr, v in d.items():
                setattr(ws, attr, copy.copy(v) if isinstance(v, (dict, list, set)) else v)
        self.names = dict(snap["names"])
        self.active = min(snap["active"], len(self.sheets) - 1)
        self.rebuild_dependencies()
        self.recalc("all")

    def structural(self, label: str, fn):
        """Run fn() as one undoable step that may change anything (rows, sheets, merges...)."""
        before = self.snapshot()
        if self._pending is not None:
            # flush pending cell edits first so they stay in order
            pass
        fn()
        after = self.snapshot()
        self.undo_stack.append(Change(label, snapshot_before=before, snapshot_after=after))
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.modified = True
        self.rebuild_dependencies()
        self.recalc("all")

    def undo(self) -> str | None:
        if not self.undo_stack:
            return None
        ch = self.undo_stack.pop()
        if ch.snapshot_before is not None:
            self.restore(ch.snapshot_before)
        else:
            for sheet, r, c, old, new in reversed(ch.cells):
                ws = self.sheet(sheet)
                if ws is None:
                    continue
                if old is None:
                    ws.cells.pop((r, c), None)
                    ws.shrank()
                else:
                    ws.cells[(r, c)] = old
                    ws.grew(r, c)
                self._register((sheet, r, c), old) if old is not None else self._unregister((sheet, r, c))
                self._mark_dirty([(sheet, r, c)])
            self.recalc()
        self.redo_stack.append(ch)
        self.modified = True
        return ch.label

    def redo(self) -> str | None:
        if not self.redo_stack:
            return None
        ch = self.redo_stack.pop()
        if ch.snapshot_after is not None:
            self.restore(ch.snapshot_after)
        else:
            for sheet, r, c, old, new in ch.cells:
                ws = self.sheet(sheet)
                if ws is None:
                    continue
                if new is None:
                    ws.cells.pop((r, c), None)
                    ws.shrank()
                else:
                    ws.cells[(r, c)] = new
                    ws.grew(r, c)
                self._register((sheet, r, c), new) if new is not None else self._unregister((sheet, r, c))
                self._mark_dirty([(sheet, r, c)])
            self.recalc()
        self.undo_stack.append(ch)
        self.modified = True
        return ch.label

    # ---- rows and columns
    def insert(self, ws: Worksheet, axis: str, at: int, count: int):
        """Insert (count > 0) or delete (count < 0) rows/columns, moving cells and fixing formulas."""
        def move(idx):
            if count > 0:
                return idx + count if idx >= at else idx
            if at <= idx < at - count:
                return None
            return idx + count if idx >= at - count else idx

        new_cells = {}
        for (r, c), cell in ws.cells.items():
            nr, nc = (move(r), c) if axis == "row" else (r, move(c))
            if nr is None or nc is None:
                continue
            new_cells[(nr, nc)] = cell
        ws.cells = new_cells
        for other in self.sheets:
            for k, cell in list(other.cells.items()):
                if cell.formula is not None:
                    f2 = adjust_for_insert(cell.formula, ws.name, other.name, axis, at, count)
                    if f2 != cell.formula:
                        other.cells[k] = cell.copy(formula=f2)
        for name, text in list(self.names.items()):
            self.names[name] = adjust_for_insert(text if text.startswith("=") else "=" + text, ws.name, "", axis, at,
                                                 count)

        def remap(d):
            return {move(k): v for k, v in d.items() if move(k) is not None}
        if axis == "row":
            ws.row_heights = remap(ws.row_heights)
            ws.row_styles = remap(ws.row_styles)
            ws.hidden_rows = {move(r) for r in ws.hidden_rows if move(r) is not None}
            ws.comments = {(move(r), c): v for (r, c), v in ws.comments.items() if move(r) is not None}
            ws.links = {(move(r), c): v for (r, c), v in ws.links.items() if move(r) is not None}
        else:
            ws.col_widths = remap(ws.col_widths)
            ws.col_styles = remap(ws.col_styles)
            ws.hidden_cols = {move(c) for c in ws.hidden_cols if move(c) is not None}
            ws.comments = {(r, move(c)): v for (r, c), v in ws.comments.items() if move(c) is not None}
            ws.links = {(r, move(c)): v for (r, c), v in ws.links.items() if move(c) is not None}
        merges = []
        for m in ws.merges:
            r1, c1, r2, c2 = m
            if axis == "row":
                a, b = move(r1), move(r2)
                if a is None and b is None:
                    continue
                a = a if a is not None else at
                b = b if b is not None else at - 1
                if b >= a and (b > a or c2 > c1):
                    merges.append((a, c1, b, c2))
            else:
                a, b = move(c1), move(c2)
                if a is None and b is None:
                    continue
                a = a if a is not None else at
                b = b if b is not None else at - 1
                if b >= a and (b > a or r2 > r1):
                    merges.append((r1, a, r2, b))
        ws.merges = merges
        for ch in ws.charts:
            r1, c1, r2, c2 = ch.anchor
            if axis == "row":
                ch.anchor = (move(r1) if move(r1) is not None else at, c1,
                             move(r2) if move(r2) is not None else at, c2)
            else:
                ch.anchor = (r1, move(c1) if move(c1) is not None else at,
                             r2, move(c2) if move(c2) is not None else at)
            for s in ch.series:
                for attr in ("values", "categories", "name"):
                    v = getattr(s, attr)
                    if v and "!" in v:
                        setattr(s, attr, adjust_for_insert("=" + v, ws.name, ws.name, axis, at, count)[1:])

    def rename_sheet(self, ws: Worksheet, new: str):
        old = ws.name
        for other in self.sheets:
            for k, cell in list(other.cells.items()):
                if cell.formula is not None and old.lower() in cell.formula.lower():
                    other.cells[k] = cell.copy(formula=rename_sheet_in_formula(cell.formula, old, new))
            for ch in other.charts:
                for s in ch.series:
                    for attr in ("values", "categories", "name"):
                        v = getattr(s, attr)
                        if v:
                            setattr(s, attr, rename_sheet_in_formula("=" + v, old, new)[1:])
        for name, text in list(self.names.items()):
            self.names[name] = rename_sheet_in_formula(text if text.startswith("=") else "=" + text, old, new)
        ws.name = new
        self.reindex()

    # ---- copy/paste helpers
    def formula_moved(self, formula: str, dr: int, dc: int) -> str:
        return shift_formula(formula, dr, dc)

    def display(self, ws: Worksheet, r: int, c: int) -> tuple[str, str | None]:
        cell = ws.cells.get((r, c))
        if cell is None:
            return "", None
        v = self.value(ws.name, r, c)
        if v == 0 and isinstance(v, float) and not ws.show_zeros:
            return "", None
        return NF.format_value(v, self.styles[cell.style].numfmt if cell.style else "General")


DATE_FUNCS = {"DATE": "dd-mm-yyyy", "TODAY": "dd-mm-yyyy", "NOW": "dd-mm-yyyy h:mm", "EDATE": "dd-mm-yyyy",
              "EOMONTH": "dd-mm-yyyy", "DATEVALUE": "dd-mm-yyyy", "WORKDAY": "dd-mm-yyyy", "TIME": "h:mm",
              "TIMEVALUE": "h:mm", "PMT": "#,##0.00", "PV": "#,##0.00", "FV": "#,##0.00", "IPMT": "#,##0.00",
              "PPMT": "#,##0.00"}


def auto_format(formula: str) -> str | None:
    """Like Excel: =TODAY() shows a date, =PMT(...) a money amount (only if the cell has no format)."""
    m = re.match(r"=\s*([A-Za-z.]+)\(", formula)
    return DATE_FUNCS.get(m.group(1).upper()) if m else None


def normalize_formula(text: str) -> str:
    """Function names in capitals, like Excel does when you press Enter."""
    out = ""
    for is_str, part in _pieces(text):
        if is_str:
            out += part
        else:
            part = re.sub(r"([A-Za-z_][A-Za-z0-9_.]*)(?=\()", lambda m: m.group(1).upper(), part)
            # and references: =sum(a1:b2) becomes =SUM(A1:B2)
            out += re.sub(r"(?<![A-Za-z0-9_.'])\$?[A-Za-z]{1,3}\$?\d{1,7}(?![A-Za-z0-9_(!.])",
                          lambda m: m.group(0).upper(), part)
    return out


def _pieces(text):
    from sheet_ref import _split_strings
    return _split_strings(text)


def new_workbook() -> Workbook:
    wb = Workbook()
    for i in range(3):
        wb.add_sheet(f"Sheet{i + 1}")
    return wb


def sheet_ref_text(ws: Worksheet, r1, c1, r2, c2, absolute=True) -> str:
    from sheet_ref import cell_name
    a = cell_name(r1, c1, absolute, absolute)
    b = cell_name(r2, c2, absolute, absolute)
    return f"{quote_sheet(ws.name)}!{a}" + (f":{b}" if (r1, c1) != (r2, c2) else "")


MAX = (MAX_ROWS, MAX_COLS)
