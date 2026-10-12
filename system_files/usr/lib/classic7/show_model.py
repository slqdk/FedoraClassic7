"""Show: the presentation model shared by the editor, the slide show and the file formats.

Units: positions and sizes in EMU (914400 per inch, 12700 per point), font sizes in points.
Colours are small dicts so that theme colours stay theme colours:
    {"rgb": "4F81BD"}  or  {"scheme": "accent1"}  plus optional "mods": [["lumMod", 75000], ...]
Fills:  None (no fill) | {"type": "solid", "color": C} | {"type": "grad", "stops": [[pos 0..100000, C]],
        "angle": degrees, "path": None|"circle"|"rect"} | {"type": "pic", "image": media key}
Lines:  None (no line) | {"color": C, "width": EMU, "dash": "solid"|"dash"|"sysDot"|..., "head": str, "tail": str}
"""
from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field

EMU_PER_INCH = 914400
EMU_PER_PT = 12700
SLIDE_4_3 = (9144000, 6858000)
SLIDE_16_9 = (9144000, 5143500)
SLIDE_16_10 = (9144000, 5715000)

SLIDE_SIZES = {
    "On-screen Show (4:3)": SLIDE_4_3,
    "On-screen Show (16:9)": SLIDE_16_9,
    "On-screen Show (16:10)": SLIDE_16_10,
    "A4 Paper (210x297 mm)": (9906000, 6858000),
    "Letter Paper (8.5x11 in)": (9144000, 6858000),
    "35mm Slides": (10287000, 6858000),
    "Banner (8x1 in)": (7315200, 914400),
}


def pt(emu: float) -> float:
    return emu / EMU_PER_PT


def emu(points: float) -> int:
    return int(round(points * EMU_PER_PT))


# ---- colours -----------------------------------------------------------------------------------
def rgb(hexcolor: str) -> dict:
    return {"rgb": hexcolor.lstrip("#").upper()}


def scheme(name: str, *mods) -> dict:
    c = {"scheme": name}
    if mods:
        c["mods"] = [list(m) for m in mods]
    return c


SCHEME_KEYS = ["dk1", "lt1", "dk2", "lt2", "accent1", "accent2", "accent3", "accent4", "accent5", "accent6",
               "hlink", "folHlink"]
DEFAULT_COLOR_MAP = {"bg1": "lt1", "tx1": "dk1", "bg2": "lt2", "tx2": "dk2", "accent1": "accent1",
                     "accent2": "accent2", "accent3": "accent3", "accent4": "accent4", "accent5": "accent5",
                     "accent6": "accent6", "hlink": "hlink", "folHlink": "folHlink"}
DARK_COLOR_MAP = dict(DEFAULT_COLOR_MAP, bg1="dk1", tx1="lt1", bg2="dk2", tx2="lt2")


def _hsl(r, g, b):
    import colorsys
    h, l_, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return h, s, l_


def _rgb_from_hsl(h, s, l_):
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h, l_, s)
    return round(r * 255), round(g * 255), round(b * 255)


def apply_mods(r: int, g: int, b: int, mods) -> tuple[int, int, int, int]:
    """Apply DrawingML colour transforms; returns (r, g, b, alpha 0..255)."""
    a = 255
    for name, val in mods or []:
        v = float(val) / 100000.0
        if name in ("lumMod", "lumOff"):
            h, s, l_ = _hsl(r, g, b)
            l_ = l_ * v if name == "lumMod" else l_ + v
            r, g, b = _rgb_from_hsl(h, s, max(0.0, min(1.0, l_)))
        elif name == "tint":          # towards white
            r, g, b = (round(c + (255 - c) * (1 - v)) for c in (r, g, b))
        elif name == "shade":         # towards black
            r, g, b = (round(c * v) for c in (r, g, b))
        elif name == "satMod":
            h, s, l_ = _hsl(r, g, b)
            r, g, b = _rgb_from_hsl(h, max(0.0, min(1.0, s * v)), l_)
        elif name == "alpha":
            a = round(255 * v)
        elif name == "alphaMod":
            a = round(a * v)
    return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), max(0, min(255, a))


# ---- themes ------------------------------------------------------------------------------------
@dataclass
class Theme:
    name: str = "Office Theme"
    colors_name: str = "Office"
    fonts_name: str = "Office"
    colors: dict = field(default_factory=lambda: {
        "dk1": "000000", "lt1": "FFFFFF", "dk2": "1F497D", "lt2": "EEECE1", "accent1": "4F81BD",
        "accent2": "C0504D", "accent3": "9BBB59", "accent4": "8064A2", "accent5": "4BACC6", "accent6": "F79646",
        "hlink": "0000FF", "folHlink": "800080"})
    major_font: str = "Calibri"
    minor_font: str = "Calibri"
    raw_xml: bytes | None = None      # the theme part as read from a file (written back unchanged if set)
    fill_styles: list = field(default_factory=list)      # fmtScheme fills with {"scheme": "phClr"}
    line_styles: list = field(default_factory=list)
    bg_fill_styles: list = field(default_factory=list)

    def scheme_rgb(self, key: str, color_map: dict | None = None) -> str:
        key = (color_map or DEFAULT_COLOR_MAP).get(key, key)
        if key == "phClr":
            key = "accent1"
        return self.colors.get(key, "000000")


# ---- text --------------------------------------------------------------------------------------
@dataclass
class Run:
    text: str = ""
    font: str | None = None          # a font name, or "+mj-lt" / "+mn-lt" for the theme fonts
    size: float | None = None        # points
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    strike: bool | None = None
    color: dict | None = None
    baseline: int = 0                # percent: 30 superscript, -25 subscript
    caps: str | None = None          # "all" | "small"
    link: str | None = None
    field: str | None = None         # "slidenum" | "datetime" | None


@dataclass
class Paragraph:
    runs: list = field(default_factory=list)
    level: int = 0
    align: str | None = None          # "l" "ctr" "r" "just"
    marL: int | None = None           # EMU
    indent: int | None = None         # EMU (negative: hanging, room for the bullet)
    bullet: dict | None = None        # {"char": "•", "font": .., "color": C, "size": pct} | {"auto": "arabicPeriod", "start": 1} | {"none": True}
    space_before: float | None = None  # points (>= 0) or percent of a line (< 0: -20 = 20%)
    space_after: float | None = None
    line_spacing: float | None = None  # percent (100 = single)
    end_size: float | None = None     # size of the empty paragraph mark

    def text(self) -> str:
        return "".join(r.text for r in self.runs)


@dataclass
class TextBody:
    paragraphs: list = field(default_factory=lambda: [Paragraph()])
    anchor: str = "t"                 # t | ctr | b
    anchor_ctr: bool = False
    insets: tuple = (91440, 45720, 91440, 45720)   # l t r b
    wrap: bool = True
    autofit: str = "none"             # none | norm | shape
    font_scale: float = 1.0
    line_reduction: float = 0.0
    vert: str = "horz"               # horz | vert | vert270
    columns: int = 1

    def plain(self) -> str:
        return "\n".join(p.text() for p in self.paragraphs)

    def is_empty(self) -> bool:
        return not any(p.text().strip() for p in self.paragraphs)


# ---- shapes ------------------------------------------------------------------------------------
_ids = itertools.count(2)


@dataclass
class Placeholder:
    type: str = "body"               # title ctrTitle subTitle body obj pic dt ftr sldNum tbl chart media ...
    idx: int = 0
    orient: str = ""
    size: str = ""                   # "" | half | quarter


@dataclass
class TableCell:
    text: TextBody = field(default_factory=TextBody)
    fill: dict | None | str = "auto"     # "auto": from the table style
    span: int = 1                    # gridSpan
    row_span: int = 1
    merged: bool = False             # covered by a span (hMerge / vMerge)
    borders: dict = field(default_factory=dict)   # "l" "r" "t" "b": Line or None
    anchor: str = "t"
    margins: tuple = (91440, 45720, 91440, 45720)


@dataclass
class Table:
    col_widths: list = field(default_factory=list)   # EMU
    row_heights: list = field(default_factory=list)
    rows: list = field(default_factory=list)         # list[list[TableCell]]
    first_row: bool = True
    band_rows: bool = True
    first_col: bool = False
    last_row: bool = False
    last_col: bool = False
    band_cols: bool = False
    style: str = "medium2-accent1"


@dataclass
class Shape:
    kind: str = "sp"                 # sp | pic | table | cxn | group | chart | other
    name: str = ""
    id: int = field(default_factory=lambda: next(_ids))
    x: int = 0
    y: int = 0
    cx: int = 914400
    cy: int = 914400
    rot: float = 0.0                 # degrees, clockwise
    flip_h: bool = False
    flip_v: bool = False
    geom: str = "rect"               # preset geometry name
    adj: dict = field(default_factory=dict)
    path: list | None = None         # custom geometry: [(w, h, [("M", x, y), ("L", x, y), ("C", ...), ("Z",)])]
    fill: dict | None = None
    line: dict | None = None
    text: TextBody | None = None
    ph: Placeholder | None = None
    txbox: bool = False
    image: str | None = None         # media key (pictures)
    crop: tuple = (0, 0, 0, 0)       # l t r b in 1/100000
    table: Table | None = None
    children: list = field(default_factory=list)
    child_rect: tuple | None = None  # chOff/chExt of a group
    shadow: dict | None = None
    link: str | None = None
    anim: dict | None = None         # {"effect": "fade", "trigger": "click"|"with"|"after", "dir": "l", "order": n}
    prompt: str = ""                 # the "Click to add ..." text of a placeholder
    raw: bytes | None = None         # untouched XML for things we can't edit (charts)
    fallback_image: str | None = None
    level_styles: list | None = None  # per level: dict of paragraph/run defaults (a:lstStyle)
    extra_level: dict | None = None   # defaults for every level (built-in layouts)
    inherit: bool = False            # a slide placeholder that keeps the layout's position
    style_text_color: dict | None = None   # p:style fontRef colour (text on shapes)

    def rect(self) -> tuple[int, int, int, int]:
        return self.x, self.y, self.cx, self.cy

    def clone(self) -> "Shape":
        s = copy.deepcopy(self)
        s.id = next(_ids)
        for c in s.children:
            c.id = next(_ids)
        return s


def walk(shapes):
    for s in shapes:
        yield s
        if s.kind == "group":
            yield from walk(s.children)


# ---- slides, layouts, masters ------------------------------------------------------------------
@dataclass
class Transition:
    type: str = "none"               # none fade push wipe split cover pull zoom dissolve circle wheel randomBar ...
    dir: str = ""                    # l r u d / in out / horz vert
    through_black: bool = False
    speed: str = "fast"              # slow | med | fast
    on_click: bool = True
    after_ms: int | None = None
    sound: str | None = None

    def duration_ms(self) -> int:
        return {"slow": 1000, "med": 750, "fast": 500}.get(self.speed, 500)


@dataclass
class Layout:
    name: str = "Blank"
    type: str = "blank"               # title obj secHead twoObj twoTxTwoObj titleOnly blank objTx picTx ...
    placeholders: list = field(default_factory=list)   # Shapes with .ph
    shapes: list = field(default_factory=list)         # decorations
    background: dict | None = None
    show_master_shapes: bool = True
    raw_xml: bytes | None = None


@dataclass
class Master:
    theme: Theme = field(default_factory=Theme)
    background: dict | None = field(default_factory=lambda: {"type": "solid", "color": scheme("bg1")})
    shapes: list = field(default_factory=list)          # decorations
    placeholders: list = field(default_factory=list)    # title, body, dt, ftr, sldNum
    title_style: list = field(default_factory=list)     # per level: dict of Paragraph/Run defaults
    body_style: list = field(default_factory=list)
    other_style: list = field(default_factory=list)
    layouts: list = field(default_factory=list)
    color_map: dict = field(default_factory=lambda: dict(DEFAULT_COLOR_MAP))
    design: str = "office"

    def layout(self, name_or_type: str) -> Layout | None:
        for lay in self.layouts:
            if lay.name == name_or_type or lay.type == name_or_type:
                return lay
        return None


@dataclass
class Slide:
    layout: Layout | None = None
    shapes: list = field(default_factory=list)
    background: dict | None = None
    hide_master_shapes: bool = False
    notes: str = ""
    transition: Transition = field(default_factory=Transition)
    hidden: bool = False
    name: str = ""
    raw_timing: bytes | None = None   # animations from a file, written back while their shapes exist
    raw_anim_sig: tuple | None = None  # the animations as they were read (raw_timing is kept while equal)


@dataclass
class Presentation:
    width: int = SLIDE_4_3[0]
    height: int = SLIDE_4_3[1]
    masters: list = field(default_factory=list)
    slides: list = field(default_factory=list)
    media: dict = field(default_factory=dict)        # key -> bytes (key keeps the extension: "image3.png")
    title: str = ""
    author: str = ""
    footer: dict = field(default_factory=lambda: {"date": False, "date_text": "", "date_auto": True,
                                                  "number": False, "footer": False, "footer_text": "",
                                                  "not_on_title": False})
    show_loop: bool = False

    @property
    def master(self) -> Master:
        return self.masters[0]

    def master_of(self, slide: Slide) -> Master:
        for m in self.masters:
            if slide.layout in m.layouts:
                return m
        return self.masters[0]

    def add_media(self, data: bytes, ext: str) -> str:
        import hashlib
        ext = ext.lower().lstrip(".") or "png"
        if ext == "jpeg":
            ext = "jpg"
        key = f"img-{hashlib.sha1(data).hexdigest()[:16]}.{ext}"
        self.media.setdefault(key, data)
        return key


# ---- text style defaults (Office 2007) ----------------------------------------------------------
def _lvl(size, marL=0, indent=0, bullet=None, align=None, space_before=-20.0, font="+mn-lt", color=None, bold=None,
         caps=None):
    d = {"size": size, "marL": marL, "indent": indent, "bullet": bullet, "align": align,
         "space_before": space_before, "font": font, "color": color or scheme("tx1"), "line_spacing": 100.0}
    if bold is not None:
        d["bold"] = bold
    if caps:
        d["caps"] = caps
    return d


def office_title_style() -> list:
    return [_lvl(44, align="ctr", space_before=0, font="+mj-lt") for _ in range(9)]


def office_body_style() -> list:
    b = {"char": "•", "font": "Arial"}
    dash = {"char": "–", "font": "Arial"}
    raquo = {"char": "»", "font": "Arial"}
    out = [_lvl(32, 342900, -342900, b), _lvl(28, 742950, -285750, dash), _lvl(24, 1143000, -228600, b),
           _lvl(20, 1600200, -228600, dash), _lvl(20, 2057400, -228600, raquo)]
    for i in range(5, 9):
        out.append(_lvl(20, 2514600 + (i - 5) * 457200, -228600, b))
    return out


def office_other_style() -> list:
    return [dict(_lvl(18, i * 457200, 0, None, "l", 0), line_spacing=100.0) for i in range(9)]


# ---- the built-in designs ----------------------------------------------------------------------
LAYOUT_NAMES = [("title", "Title Slide"), ("obj", "Title and Content"), ("secHead", "Section Header"),
                ("twoObj", "Two Content"), ("twoTxTwoObj", "Comparison"), ("titleOnly", "Title Only"),
                ("blank", "Blank"), ("objTx", "Content with Caption"), ("picTx", "Picture with Caption")]

PROMPTS = {"title": "Click to add title", "ctrTitle": "Click to add title", "subTitle": "Click to add subtitle",
           "body": "Click to add text", "obj": "Click to add text", "pic": "Click icon to add picture",
           "tbl": "Click icon to add table", "chart": "Click icon to add chart", "dt": "", "ftr": "",
           "sldNum": ""}


def _ph(type_, idx, x, y, cx, cy, name, **text_kw) -> Shape:
    s = Shape(kind="sp", name=name, x=x, y=y, cx=cx, cy=cy, ph=Placeholder(type_, idx))
    s.text = TextBody(**{k: v for k, v in text_kw.items() if k in ("anchor", "autofit")})
    paras = text_kw.get("paras")
    if paras:
        s.text.paragraphs = paras
    s.prompt = text_kw.get("prompt", PROMPTS.get(type_, "Click to add text"))
    return s


def _scaled_layouts(w: int, h: int) -> list[Layout]:
    """The nine Office layouts for a slide of w x h EMU (positions scaled from 4:3)."""
    sx, sy = w / SLIDE_4_3[0], h / SLIDE_4_3[1]

    def R(x, y, cx, cy):
        return int(x * sx), int(y * sy), int(cx * sx), int(cy * sy)

    title = R(457200, 274638, 8229600, 1143000)
    body = R(457200, 1600200, 8229600, 4525963)
    out = []
    for type_, name in LAYOUT_NAMES:
        lay = Layout(name=name, type=type_)
        P = lay.placeholders
        if type_ == "title":
            P.append(_ph("ctrTitle", 0, *R(685800, 2130425, 7772400, 1470025), "Title 1", anchor="ctr"))
            sub = _ph("subTitle", 1, *R(1371600, 3886200, 6400800, 1752600), "Subtitle 2")
            sub.extra_level = {"size": 32, "color": scheme("tx1", ("tint", 75000)), "align": "ctr",
                               "bullet": {"none": True}, "marL": 0, "indent": 0}
            P.append(sub)
        elif type_ == "obj":
            P.append(_ph("title", 0, *title, "Title 1", anchor="ctr"))
            P.append(_ph("obj", 1, *body, "Content Placeholder 2", autofit="norm"))
        elif type_ == "secHead":
            t = _ph("title", 0, *R(722313, 4406900, 7772400, 1362075), "Title 1", anchor="t")
            t.extra_level = {"size": 40, "bold": True, "caps": "all", "align": "l"}
            P.append(t)
            b = _ph("body", 1, *R(722313, 2906713, 7772400, 1500187), "Text Placeholder 2", anchor="b")
            b.extra_level = {"size": 20, "bullet": {"none": True}, "marL": 0, "indent": 0,
                             "color": scheme("tx1", ("tint", 75000))}
            P.append(b)
        elif type_ == "twoObj":
            P.append(_ph("title", 0, *title, "Title 1", anchor="ctr"))
            for i, x in ((1, 457200), (2, 4648200)):
                b = _ph("obj", i, *R(x, 1600200, 4038600, 4525963), f"Content Placeholder {i + 1}", autofit="norm")
                b.ph.size = "half"
                b.extra_level = {"size_step": -4}
                P.append(b)
        elif type_ == "twoTxTwoObj":
            P.append(_ph("title", 0, *title, "Title 1", anchor="ctr"))
            for i, (x, cx) in enumerate(((457200, 4040188), (4645025, 4041775))):
                hdr = _ph("body", 1 + 2 * i, *R(x, 1535113, cx, 639762), f"Text Placeholder {2 + 2 * i}", anchor="b")
                hdr.extra_level = {"size": 24, "bold": True, "bullet": {"none": True}, "marL": 0, "indent": 0}
                P.append(hdr)
                b = _ph("obj", 2 + 2 * i, *R(x, 2174875, cx, 3951288), f"Content Placeholder {3 + 2 * i}",
                        autofit="norm")
                b.ph.size = "quarter"
                b.extra_level = {"size_step": -8}
                P.append(b)
        elif type_ == "titleOnly":
            P.append(_ph("title", 0, *title, "Title 1", anchor="ctr"))
        elif type_ == "objTx":
            t = _ph("title", 0, *R(457200, 273050, 3008313, 1162050), "Title 1", anchor="b")
            t.extra_level = {"size": 20, "bold": True, "align": "l"}
            P.append(t)
            b = _ph("obj", 1, *R(3575050, 273050, 5111750, 5853113), "Content Placeholder 2", autofit="norm")
            P.append(b)
            c = _ph("body", 2, *R(457200, 1435100, 3008313, 4691063), "Text Placeholder 3")
            c.ph.size = "half"
            c.extra_level = {"size": 14, "bullet": {"none": True}, "marL": 0, "indent": 0}
            P.append(c)
        elif type_ == "picTx":
            t = _ph("title", 0, *R(1792288, 4800600, 5486400, 566738), "Title 1", anchor="b")
            t.extra_level = {"size": 20, "bold": True, "align": "l"}
            P.append(t)
            pic = _ph("pic", 1, *R(1792288, 612775, 5486400, 4114800), "Picture Placeholder 2")
            pic.extra_level = {"size": 32, "bullet": {"none": True}, "marL": 0, "indent": 0}
            P.append(pic)
            c = _ph("body", 2, *R(1792288, 5367338, 5486400, 804862), "Text Placeholder 3")
            c.extra_level = {"size": 14, "bullet": {"none": True}, "marL": 0, "indent": 0}
            P.append(c)
        out.append(lay)
    return out


def master_footers(w: int, h: int) -> list[Shape]:
    sx, sy = w / SLIDE_4_3[0], h / SLIDE_4_3[1]
    y, cy = int(6356350 * sy), int(365125 * sy)
    out = []
    for type_, idx, x, cx, align, name in (("dt", 2, 457200, 2133600, "l", "Date Placeholder 3"),
                                           ("ftr", 3, 3124200, 2895600, "ctr", "Footer Placeholder 4"),
                                           ("sldNum", 4, 6553200, 2133600, "r", "Slide Number Placeholder 5")):
        s = _ph(type_, idx, int(x * sx), y, int(cx * sx), cy, name, anchor="ctr")
        s.extra_level = {"size": 12, "color": scheme("tx1", ("tint", 75000)), "align": align}
        out.append(s)
    return out


def new_master(design_key: str = "office", w: int = SLIDE_4_3[0], h: int = SLIDE_4_3[1]) -> Master:
    import show_designs
    m = Master()
    m.title_style = office_title_style()
    m.body_style = office_body_style()
    m.other_style = office_other_style()
    sx, sy = w / SLIDE_4_3[0], h / SLIDE_4_3[1]
    m.placeholders = [
        _ph("title", 0, int(457200 * sx), int(274638 * sy), int(8229600 * sx), int(1143000 * sy), "Title Placeholder 1",
            anchor="ctr"),
        _ph("body", 1, int(457200 * sx), int(1600200 * sy), int(8229600 * sx), int(4525963 * sy),
            "Text Placeholder 2"),
    ] + master_footers(w, h)
    m.layouts = _scaled_layouts(w, h)
    show_designs.apply_design(m, design_key, w, h)
    return m


def new_presentation(design_key: str = "office", size=SLIDE_4_3) -> Presentation:
    p = Presentation(width=size[0], height=size[1])
    p.masters = [new_master(design_key, *size)]
    s = new_slide(p, p.master.layout("title"))
    p.slides.append(s)
    return p


def new_slide(pres: Presentation, layout: Layout | None = None) -> Slide:
    layout = layout or pres.master.layout("obj") or pres.master.layouts[0]
    s = Slide(layout=layout)
    for ph in layout.placeholders:
        if ph.ph.type in ("dt", "ftr", "sldNum"):
            continue
        s.shapes.append(placeholder_shape(ph))
    return s


def placeholder_shape(layout_ph: Shape) -> Shape:
    """An empty placeholder on a slide, linked to the layout's placeholder (same type/idx)."""
    s = Shape(kind="sp", name=layout_ph.name, x=layout_ph.x, y=layout_ph.y, cx=layout_ph.cx, cy=layout_ph.cy,
              ph=copy.deepcopy(layout_ph.ph))
    s.text = TextBody(anchor=layout_ph.text.anchor if layout_ph.text else "t",
                      autofit=layout_ph.text.autofit if layout_ph.text else "none")
    s.prompt = layout_ph.prompt
    s.inherit = True
    return s


def find_layout_placeholder(layout: Layout | None, master: Master, ph: Placeholder) -> Shape | None:
    """The layout (or master) placeholder a slide placeholder inherits from (by idx, then type)."""
    cands = list(layout.placeholders) if layout else []

    def norm(t):
        return {"ctrTitle": "title", "obj": "body", "subTitle": "body"}.get(t, t)
    for c in cands:
        if c.ph.idx == ph.idx and (ph.idx != 0 or norm(c.ph.type) == norm(ph.type)):
            return c
    for c in cands:
        if c.ph.type == ph.type:
            return c
    for c in cands:
        if norm(c.ph.type) == norm(ph.type):
            return c
    for c in master.placeholders:
        if norm(c.ph.type) == norm(ph.type):
            return c
    return None


def level_defaults(master: Master, layout: Layout | None, shape: Shape, level: int) -> dict:
    """The paragraph/run defaults of a level in a placeholder or text box (resolved inheritance)."""
    ph = shape.ph
    if ph is None:
        base = dict(master.other_style[min(level, len(master.other_style) - 1)]) if master.other_style else {}
        base.update({"size": 18, "bullet": None, "marL": 0, "indent": 0, "align": "l", "space_before": 0.0,
                     "font": "+mn-lt", "color": scheme("tx1")})
        return base
    t = ph.type
    if t in ("title", "ctrTitle"):
        style = master.title_style
    elif t in ("dt", "ftr", "sldNum"):
        style = master.other_style
    else:
        style = master.body_style
    base = dict(style[min(level, len(style) - 1)]) if style else {}
    if t in ("dt", "ftr", "sldNum"):
        base.update({"size": 12, "bullet": None, "marL": 0, "indent": 0})
    # the master placeholder, then the layout placeholder may change it
    chain = []
    for c in master.placeholders:
        if c.ph.type == ({"ctrTitle": "title", "subTitle": "body", "obj": "body"}.get(t, t)):
            chain.append(c)
            break
    lp = find_layout_placeholder(layout, master, ph) if layout else None
    if lp is not None and lp not in chain:
        chain.append(lp)
    for c in chain:
        extra = getattr(c, "extra_level", None)
        if extra:
            ex = dict(extra)
            step = ex.pop("size_step", 0)
            if step:
                base["size"] = max(8, base.get("size", 18) + step)
            base.update(ex)
        lvls = getattr(c, "level_styles", None)
        if lvls and level < len(lvls) and lvls[level]:
            base.update(lvls[level])
    own = getattr(shape, "level_styles", None)
    if own and level < len(own) and own[level]:
        base.update(own[level])
    return base


def bump_ids(n: int):
    """Make new shape ids larger than n (after loading a file)."""
    global _ids
    cur = next(_ids)
    _ids = itertools.count(max(cur, n + 1))


def slide_index(pres: Presentation, slide: Slide) -> int:
    for i, s in enumerate(pres.slides):
        if s is slide:
            return i
    return -1
