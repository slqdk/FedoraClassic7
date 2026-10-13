"""
Classic 7 theme library.

Draws every pixel-made part of the Classic 7 look from one Palette:
  - KDE colour scheme           color-schemes/<id>.colors
  - Aurorae window decoration   aurorae/themes/<id>/
  - Plasma style                plasma/desktoptheme/<id>/
  - Start button image          classic7/<file>.svg
  - Previews (desktop mockup and the Appearance dialog's sample windows)

Used in two places:
  - at image build time by tools/generate_theme.py (system files, default ids)
  - at runtime by classic7-appearance (user files in ~/.local/share, per-slot ids)
Plain Python, no dependencies.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

UI_FONT = "Noto Sans"

# =============================================================================
# Palette
# =============================================================================


def _hex(c: str) -> tuple[int, int, int]:
    h = c.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _to_hex(r: float, g: float, b: float) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, round(v))) for v in (r, g, b)))


def mix(a: str, b: str, t: float) -> str:
    """Blend colour a towards b by t (0..1)."""
    ra, ga, ba = _hex(a)
    rb, gb, bb = _hex(b)
    return _to_hex(ra + (rb - ra) * t, ga + (gb - ga) * t, ba + (bb - ba) * t)


def rgb(c: str) -> str:
    return ",".join(str(v) for v in _hex(c))


def luminance(c: str) -> float:
    r, g, b = (v / 255 for v in _hex(c))
    return 0.299 * r + 0.587 * g + 0.114 * b


@dataclass
class Palette:
    """One colour scheme. Bevel shades are derived from `face` unless set explicitly."""

    name: str
    desktop: str
    face: str                 # 3D objects: window/button background
    face_text: str            # 3D objects: text on buttons, menus, dialogs
    window: str               # text areas, lists
    window_text: str
    select: str               # selected items
    select_text: str
    title_active: str         # active title bar, colour 1 (left)
    title_active2: str        # active title bar, colour 2 (right)
    title_active_text: str
    title_inactive: str
    title_inactive2: str
    title_inactive_text: str
    tooltip: str
    tooltip_text: str
    hilight: str | None = None    # 3D highlight (outer top-left)
    light: str | None = None      # 3D light (inner top-left)
    shadow: str | None = None     # 3D shadow (inner bottom-right)
    dkshadow: str | None = None   # 3D dark shadow (outer bottom-right)
    font_size: int = 9
    radius: int = 0               # rounded window corners (px, at most the border width)
    flat: bool = False            # thin 1-px window outline and flat title buttons (modern look)

    # --- derived bevel shades -------------------------------------------------
    @property
    def c_hilight(self) -> str:
        return self.hilight or mix(self.face, "#FFFFFF", 0.9)

    @property
    def c_light(self) -> str:
        return self.light or self.face

    @property
    def c_shadow(self) -> str:
        return self.shadow or mix(self.face, "#000000", 0.4)

    @property
    def c_dkshadow(self) -> str:
        return self.dkshadow or mix(self.face, "#000000", 0.7)

    @property
    def task_active(self) -> str:
        """Pressed-in task button: stands in for the classic white/face dither."""
        return mix(self.face, self.c_hilight, 0.5)

    @property
    def disabled_text(self) -> str:
        return self.c_shadow

    @property
    def dark(self) -> bool:
        return luminance(self.face) < 0.45

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> "Palette":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def renamed(self, name: str) -> "Palette":
        return replace(self, name=name)


# The schemes offered in the Appearance dialog. Names are our own.
SCHEMES: list[Palette] = [
    Palette(
        name="Classic 7 Standard",
        desktop="#3A6EA5", face="#D4D0C8", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#0A246A", select_text="#FFFFFF",
        title_active="#0A246A", title_active2="#A6CAF0", title_active_text="#FFFFFF",
        title_inactive="#808080", title_inactive2="#C0C0C0", title_inactive_text="#D4D0C8",
        tooltip="#FFFFE1", tooltip_text="#000000",
        hilight="#FFFFFF", light="#D4D0C8", shadow="#808080", dkshadow="#404040",
    ),
    Palette(
        name="XP Blue",
        desktop="#004E98", face="#ECE9D8", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#316AC5", select_text="#FFFFFF",
        title_active="#0A55E0", title_active2="#3D95FF", title_active_text="#FFFFFF",
        title_inactive="#7A96DF", title_inactive2="#A9C1F0", title_inactive_text="#D8E4F8",
        tooltip="#FFFFE1", tooltip_text="#000000",
        hilight="#FFFFFF", light="#F1EFE2", shadow="#ACA899", dkshadow="#716F64",
    ),
    Palette(
        name="Seven Basic",
        desktop="#1C4F8C", face="#F0F0F0", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#3399FF", select_text="#FFFFFF",
        title_active="#99B4D1", title_active2="#B9D1EA", title_active_text="#000000",
        title_inactive="#BFCDDB", title_inactive2="#D7E4F2", title_inactive_text="#434E54",
        tooltip="#FFFFE1", tooltip_text="#000000",
        hilight="#FFFFFF", light="#E3E3E3", shadow="#A0A0A0", dkshadow="#696969",
    ),
    Palette(
        name="Eleven Light",
        desktop="#3C6EB4", face="#F3F3F3", face_text="#1B1B1B",
        window="#FFFFFF", window_text="#1B1B1B", select="#0067C0", select_text="#FFFFFF",
        title_active="#F3F3F3", title_active2="#F3F3F3", title_active_text="#1B1B1B",
        title_inactive="#F3F3F3", title_inactive2="#F3F3F3", title_inactive_text="#8A8A8A",
        tooltip="#F9F9F9", tooltip_text="#1B1B1B",
        hilight="#FFFFFF", light="#F9F9F9", shadow="#CFCFCF", dkshadow="#9E9E9E",
        radius=4, flat=True,
    ),
    Palette(
        name="Classic Grey",
        desktop="#008080", face="#C0C0C0", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#000080", select_text="#FFFFFF",
        title_active="#000080", title_active2="#1084D0", title_active_text="#FFFFFF",
        title_inactive="#808080", title_inactive2="#B5B5B5", title_inactive_text="#C0C0C0",
        tooltip="#FFFFE1", tooltip_text="#000000",
        hilight="#FFFFFF", light="#DFDFDF", shadow="#808080", dkshadow="#000000",
    ),
    Palette(
        name="Slate",
        desktop="#2F4858", face="#B9C2CB", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#3B5874", select_text="#FFFFFF",
        title_active="#3B5874", title_active2="#9FB6CC", title_active_text="#FFFFFF",
        title_inactive="#7D8791", title_inactive2="#B4BCC4", title_inactive_text="#DDE2E6",
        tooltip="#FFFFE1", tooltip_text="#000000",
    ),
    Palette(
        name="Sandstone",
        desktop="#A28D68", face="#D5CCBB", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#7A6440", select_text="#FFFFFF",
        title_active="#7A6440", title_active2="#C9B48C", title_active_text="#FFFFFF",
        title_inactive="#A29A8B", title_inactive2="#CFC6B6", title_inactive_text="#E8E2D6",
        tooltip="#FFFFE1", tooltip_text="#000000",
    ),
    Palette(
        name="Terracotta",
        desktop="#6B3A2A", face="#D2C6B8", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#8C2F1B", select_text="#FFFFFF",
        title_active="#8C2F1B", title_active2="#D49A82", title_active_text="#FFFFFF",
        title_inactive="#9C9086", title_inactive2="#CBC0B4", title_inactive_text="#E4DCD2",
        tooltip="#FFFFE1", tooltip_text="#000000",
    ),
    Palette(
        name="Pine",
        desktop="#264D3A", face="#C4CFC2", face_text="#000000",
        window="#FFFFFF", window_text="#000000", select="#2E5E3E", select_text="#FFFFFF",
        title_active="#2E5E3E", title_active2="#93BA9C", title_active_text="#FFFFFF",
        title_inactive="#8A958A", title_inactive2="#BCC6BA", title_inactive_text="#E0E6DE",
        tooltip="#FFFFE1", tooltip_text="#000000",
    ),
    Palette(
        name="Night",
        desktop="#1C2733", face="#3A3D41", face_text="#E6E6E6",
        window="#25272A", window_text="#E6E6E6", select="#2F5FA8", select_text="#FFFFFF",
        title_active="#1E3A6E", title_active2="#5079B8", title_active_text="#FFFFFF",
        title_inactive="#2A2C2F", title_inactive2="#4A4D52", title_inactive_text="#A0A0A0",
        tooltip="#30343A", tooltip_text="#F0F0F0",
        hilight="#6A6E74", light="#4A4D52", shadow="#232527", dkshadow="#101112",
    ),
    Palette(
        name="High Contrast",
        desktop="#000000", face="#000000", face_text="#FFFFFF",
        window="#000000", window_text="#FFFFFF", select="#00007F", select_text="#FFFF00",
        title_active="#00007F", title_active2="#00007F", title_active_text="#FFFFFF",
        title_inactive="#404040", title_inactive2="#404040", title_inactive_text="#FFFFFF",
        tooltip="#000000", tooltip_text="#FFFFFF",
        hilight="#FFFFFF", light="#808080", shadow="#808080", dkshadow="#FFFFFF",
    ),
]

STANDARD = SCHEMES[0]


def scheme(name: str) -> Palette:
    for p in SCHEMES:
        if p.name == name:
            return p
    raise KeyError(name)


# Items shown in the Appearance dialog, like the classic "Item" list.
# (label, colour-1 field, colour-2 field or None, text field or None)
ITEMS: list[tuple[str, str, str | None, str | None]] = [
    ("Desktop", "desktop", None, None),
    ("Active Title Bar", "title_active", "title_active2", "title_active_text"),
    ("Inactive Title Bar", "title_inactive", "title_inactive2", "title_inactive_text"),
    ("3D Objects", "face", None, "face_text"),
    ("Window", "window", None, "window_text"),
    ("Selected Items", "select", None, "select_text"),
    ("ToolTip", "tooltip", None, "tooltip_text"),
]

FONT_SIZES = {"Normal": 9, "Large": 10, "Extra Large": 11}


# =============================================================================
# Pixel canvas -> SVG rects
# =============================================================================
class Canvas:
    """A pixel grid; each cell holds a colour string or None (transparent)."""

    def __init__(self, w: int, h: int, fill: str | None = None):
        self.w, self.h = w, h
        self.px = [[fill] * w for _ in range(h)]

    def set(self, x: int, y: int, c: str | None):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y][x] = c

    def rect(self, x: int, y: int, w: int, h: int, c: str | None):
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, c)

    def edge(self, x: int, y: int, w: int, h: int, tl: str, br: str):
        """One ring of a classic 3D edge; bottom/right drawn over the full length."""
        for xx in range(x, x + w - 1):
            self.set(xx, y, tl)
        for yy in range(y, y + h - 1):
            self.set(x, yy, tl)
        for xx in range(x, x + w):
            self.set(xx, y + h - 1, br)
        for yy in range(y, y + h):
            self.set(x + w - 1, yy, br)

    def bevel(self, x, y, w, h, outer, inner):
        self.edge(x, y, w, h, *outer)
        self.edge(x + 1, y + 1, w - 2, h - 2, *inner)

    def stamp(self, pattern: list[str], x: int, y: int, c: str):
        for dy, row in enumerate(pattern):
            for dx, ch in enumerate(row):
                if ch != " ":
                    self.set(x + dx, y + dy, c)

    def svg(self, x0: int, y0: int, w: int, h: int, ox: float = 0, oy: float = 0) -> str:
        """SVG rects for a sub-region, placed at (ox, oy). Horizontal runs are merged, and
        identical runs on consecutive rows become one tall rect: 1-px-high strips would show
        thin seams (lines) when Plasma stretches or tiles a frame piece."""
        out = []
        open_runs: dict[tuple, list] = {}          # (x, width, colour) -> [first row, height]

        def emit(key, start):
            xx, run, c = key
            first, height = start
            fill = f'fill="{c}"' if c is not None else 'fill="#000" fill-opacity="0"'
            if c is None:
                return                              # transparent: nothing to draw
            out.append(f'<rect x="{ox + xx - x0}" y="{oy + first - y0}" width="{run}" height="{height}" {fill}/>')

        for yy in range(y0, y0 + h):
            row_keys = set()
            xx = x0
            while xx < x0 + w:
                c = self.px[yy][xx]
                run = 1
                while xx + run < x0 + w and self.px[yy][xx + run] == c:
                    run += 1
                key = (xx, run, c)
                row_keys.add(key)
                if key in open_runs:
                    open_runs[key][1] += 1
                else:
                    open_runs[key] = [yy, 1]
                xx += run
            for key in [k for k in open_runs if k not in row_keys]:
                emit(key, open_runs.pop(key))
        for key, start in open_runs.items():
            emit(key, start)
        return "".join(out)

    def round_corners(self, r: int, border: str | None, top: bool = True, bottom: bool = True):
        """Cut rounded corners of radius r (pixels outside become transparent); the pixels on
        the arc get the border colour so the outline follows the curve."""
        if r <= 0:
            return
        corners = []
        if top:
            corners += [(0, 0, 1, 1), (self.w - r, 0, -1, 1)]
        if bottom:
            corners += [(0, self.h - r, 1, -1), (self.w - r, self.h - r, -1, -1)]
        for cx0, cy0, sx, sy in corners:
            for dy in range(r):
                for dx in range(r):
                    # distance of the pixel centre from the arc's centre (in corner space)
                    px_ = dx if sx == 1 else r - 1 - dx
                    py_ = dy if sy == 1 else r - 1 - dy
                    d = ((r - px_ - 0.5) ** 2 + (r - py_ - 0.5) ** 2) ** 0.5
                    if d > r:
                        self.set(cx0 + dx, cy0 + dy, None)
                    elif d > r - 1.3 and border:
                        self.set(cx0 + dx, cy0 + dy, border)


class Bevels:
    """The four classic edge styles for a palette, as (outer ring, inner ring)."""

    def __init__(self, p: Palette):
        self.window = ((p.c_light, p.c_dkshadow), (p.c_hilight, p.c_shadow))
        self.button = ((p.c_hilight, p.c_dkshadow), (p.c_light, p.c_shadow))
        self.pressed = ((p.c_dkshadow, p.c_hilight), (p.c_shadow, p.c_light))
        self.field = ((p.c_shadow, p.c_hilight), (p.c_dkshadow, p.c_light))
        self.thin_raised = (p.c_hilight, p.c_shadow)
        self.thin_sunken = (p.c_shadow, p.c_hilight)


def svg_doc(w: int, h: int, body: str, defs: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        'shape-rendering="crispEdges">\n'
        f"<defs>{defs}</defs>\n{body}\n</svg>\n"
    )


def group(gid: str, content: str) -> str:
    return f'<g id="{gid}">{content}</g>\n'


def hint(gid: str, x: float, y: float, w: float, h: float) -> str:
    return f'<rect id="{gid}" x="{x}" y="{y}" width="{w}" height="{h}" fill="#000" fill-opacity="0"/>\n'


def nine_slice(prefix: str, cv: Canvas, b: tuple[int, int, int, int], ox: float, oy: float,
               extra: dict[str, str] | None = None) -> str:
    """Split a canvas into the 9 FrameSvg elements. b = (left, top, right, bottom) border sizes.
    `extra` maps a piece name to SVG painted on top of that piece."""
    L, T, R, B = b
    W, H = cv.w, cv.h
    cw, ch = W - L - R, H - T - B
    p = f"{prefix}-" if prefix else ""
    parts = [
        ("topleft", 0, 0, L, T), ("top", L, 0, cw, T), ("topright", L + cw, 0, R, T),
        ("left", 0, T, L, ch), ("center", L, T, cw, ch), ("right", L + cw, T, R, ch),
        ("bottomleft", 0, T + ch, L, B), ("bottom", L, T + ch, cw, B), ("bottomright", L + cw, T + ch, R, B),
    ]
    out = ""
    for name, x, y, w, h in parts:
        if w > 0 and h > 0:
            out += group(p + name, cv.svg(x, y, w, h, ox + x, oy + y) + (extra or {}).get(name, ""))
    return out


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# =============================================================================
# Output ids: where and under which names a theme is written
# =============================================================================
@dataclass
class Ids:
    colors: str = "Classic7"            # color-schemes/<colors>.colors
    colors_name: str = "Classic 7"
    plasma: str = "classic7"            # plasma/desktoptheme/<plasma>/
    aurorae: str = "Classic7"           # aurorae/themes/<aurorae>/
    display: str = "Classic 7"
    start_button: str = "classic7/start-button.svg"
    extra: dict = field(default_factory=dict)

    @property
    def kwin_theme(self) -> str:
        return f"__aurorae__svg__{self.aurorae}"


def slot_ids(slot: str, scheme_name: str) -> Ids:
    """Per-user ids. Alternating slots (A/B) force Plasma and KWin to reload."""
    return Ids(
        colors=f"Classic7User{slot}",
        colors_name=f"Classic 7 ({scheme_name})",
        plasma=f"classic7-user-{slot.lower()}",
        aurorae=f"Classic7User{slot}",
        display=f"Classic 7 ({scheme_name})",
        start_button=f"classic7/start-button-{slot.lower()}.svg",
    )


class Writer:
    def __init__(self, data_dir: Path, verbose: bool = False):
        self.data_dir = Path(data_dir)
        self.verbose = verbose
        self.written: list[Path] = []

    def __call__(self, rel: str, text: str):
        path = self.data_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.written.append(path)
        if self.verbose:
            print("wrote", path)


# =============================================================================
# 1. KDE colour scheme
# =============================================================================
def color_scheme(p: Palette, ids: Ids) -> str:
    link = "#9CC4FF" if p.dark else "#0000FF"
    visited = "#C9A0FF" if p.dark else "#800080"
    common = {
        "ForegroundInactive": p.disabled_text, "ForegroundActive": link,
        "ForegroundLink": link, "ForegroundVisited": visited,
        "ForegroundNegative": "#FF6B6B" if p.dark else "#C00000",
        "ForegroundNeutral": "#E0A040" if p.dark else "#B06000",
        "ForegroundPositive": "#6BCB77" if p.dark else "#008000",
        "DecorationFocus": p.select, "DecorationHover": p.select,
    }
    sets = {
        "Window": {"BackgroundNormal": p.face, "BackgroundAlternate": mix(p.face, p.c_hilight, 0.3),
                   "ForegroundNormal": p.face_text},
        "Button": {"BackgroundNormal": p.face, "BackgroundAlternate": mix(p.face, p.c_hilight, 0.3),
                   "ForegroundNormal": p.face_text},
        "View": {"BackgroundNormal": p.window, "BackgroundAlternate": mix(p.window, p.face, 0.25),
                 "ForegroundNormal": p.window_text},
        "Header": {"BackgroundNormal": p.face, "BackgroundAlternate": p.face, "ForegroundNormal": p.face_text},
        "Tooltip": {"BackgroundNormal": p.tooltip, "BackgroundAlternate": p.tooltip,
                    "ForegroundNormal": p.tooltip_text},
        "Selection": {"BackgroundNormal": p.select, "BackgroundAlternate": mix(p.select, p.c_hilight, 0.15),
                      "ForegroundNormal": p.select_text, "ForegroundInactive": mix(p.select_text, p.select, 0.3),
                      "ForegroundActive": p.select_text, "ForegroundLink": mix(p.select_text, "#80C0FF", 0.5),
                      "ForegroundVisited": mix(p.select_text, "#E0C0FF", 0.5)},
        "Complementary": {"BackgroundNormal": p.c_shadow, "BackgroundAlternate": p.c_dkshadow,
                          "ForegroundNormal": "#FFFFFF", "ForegroundInactive": p.face},
    }
    lines = ["[ColorEffects:Disabled]", f"Color={rgb(p.disabled_text)}", "ColorAmount=0", "ColorEffect=0",
             "ContrastAmount=0.55", "ContrastEffect=1", "IntensityAmount=0", "IntensityEffect=0", "",
             "[ColorEffects:Inactive]", "ChangeSelectionColor=false", "Enable=false", ""]
    for name, vals in sets.items():
        merged = {**common, **vals}
        lines.append(f"[Colors:{name}]")
        for k in sorted(merged):
            lines.append(f"{k}={rgb(merged[k])}")
        lines.append("")
    lines += [
        "[General]", f"ColorScheme={ids.colors}", f"Name={ids.colors_name}", "shadeSortColumn=false", "",
        "[KDE]", "contrast=10", "",
        "[WM]",
        f"activeBackground={rgb(p.title_active)}", f"activeBlend={rgb(p.title_active2)}",
        f"activeForeground={rgb(p.title_active_text)}",
        f"inactiveBackground={rgb(p.title_inactive)}", f"inactiveBlend={rgb(p.title_inactive2)}",
        f"inactiveForeground={rgb(p.title_inactive_text)}", "",
    ]
    return "\n".join(lines)


# =============================================================================
# 2. Aurorae window decoration
# =============================================================================
BORDER = 4
TITLE_H = 18
TITLE_GAP = 1
TOP = BORDER + TITLE_H + TITLE_GAP
BTN_W, BTN_H = 16, 14

GLYPHS = {
    "close": (4, 3, [
        "xx    xx",
        " xx  xx ",
        "  xxxx  ",
        "   xx   ",
        "  xxxx  ",
        " xx  xx ",
        "xx    xx",
    ]),
    "minimize": (4, 9, [
        "xxxxxx",
        "xxxxxx",
    ]),
    "maximize": (3, 2, [
        "xxxxxxxxx",
        "xxxxxxxxx",
        "x       x",
        "x       x",
        "x       x",
        "x       x",
        "x       x",
        "x       x",
        "xxxxxxxxx",
    ]),
    "restore": (3, 2, [
        "  xxxxxx",
        "  xxxxxx",
        "  x    x",
        "xxxxxx x",
        "xxxxxx x",
        "x    xxx",
        "x    x  ",
        "x    x  ",
        "xxxxxx  ",
    ]),
}


def title_gradient(gid: str, c1: str, c2: str) -> str:
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>')


def decoration_svg(p: Palette) -> str:
    bv = Bevels(p)
    body, defs = "", ""
    stretch = 24
    W, H = BORDER * 2 + stretch, TOP + stretch + BORDER
    for i, (state, c1, c2) in enumerate((("decoration", p.title_active, p.title_active2),
                                         ("decoration-inactive", p.title_inactive, p.title_inactive2))):
        gid = f"grad-{i}"
        defs += title_gradient(gid, c1, c2)
        cv = Canvas(W, H, p.face)
        outline = mix(p.c_shadow, p.c_dkshadow, 0.3)
        if p.flat:
            cv.edge(0, 0, W, H, outline, outline)
            # the title band colour reaches into the side borders, like a modern title bar
            cv.rect(1, 1, W - 2, TOP - 1, c1)
        else:
            cv.bevel(0, 0, W, H, *bv.window)
        cv.round_corners(min(p.radius, BORDER), outline if p.flat else p.c_dkshadow)
        oy = i * (H + 10)
        band = f'<rect x="{BORDER}" y="{oy + BORDER}" width="{stretch}" height="{TITLE_H}" fill="url(#{gid})"/>'
        body += nine_slice(state, cv, (BORDER, TOP, BORDER, BORDER), 0, oy, {"top": band})
        # Maximized: borders vanish, only the title band (+1px gap) is drawn
        mx = W + 20
        mprefix = "decoration-maximized" if i == 0 else "decoration-maximized-inactive"
        body += group(f"{mprefix}-center",
                      f'<rect x="{mx}" y="{oy}" width="{stretch}" height="{TITLE_H}" fill="url(#{gid})"/>'
                      f'<rect x="{mx}" y="{oy + TITLE_H}" width="{stretch}" height="{TITLE_GAP}" fill="{p.face}"/>')
    body += hint("hint-stretch-borders", W * 2 + 60, 0, 4, 4)
    for prefix in ("decoration", "decoration-inactive"):
        body += hint(f"{prefix}-hint-stretch-borders", W * 2 + 60, 10, 4, 4)
    return svg_doc(W * 2 + 80, (H + 10) * 2, body, defs)


def button_canvas(p: Palette, kind: str, state: str, inactive: bool = False) -> Canvas:
    bv = Bevels(p)
    gx, gy, pat = GLYPHS[kind]
    if p.flat:
        # glyph on the title bar; a light box on hover, red for Close
        cv = Canvas(BTN_W, BTN_H, None)
        glyph = p.title_inactive_text if inactive else p.title_active_text
        if state in ("hover", "pressed"):
            box = "#C42B1C" if kind == "close" else mix(p.title_active, "#000000", 0.08 if state == "hover" else 0.16)
            cv.rect(0, 0, BTN_W, BTN_H, box)
            if kind == "close":
                glyph = "#FFFFFF"
        if state == "deactivated":
            glyph = p.c_shadow
        cv.stamp(pat, gx, gy, glyph)
        return cv
    cv = Canvas(BTN_W, BTN_H, p.face)
    if state == "pressed":
        cv.bevel(0, 0, BTN_W, BTN_H, *bv.pressed)
        cv.stamp(pat, gx + 1, gy + 1, p.face_text)
    else:
        cv.bevel(0, 0, BTN_W, BTN_H, *bv.button)
        if state == "deactivated":
            cv.stamp(pat, gx + 1, gy + 1, p.c_hilight)
            cv.stamp(pat, gx, gy, p.c_shadow)
        else:
            cv.stamp(pat, gx, gy, p.face_text)
    return cv


def button_svg(p: Palette, kind: str) -> str:
    body = ""
    states = ["active", "hover", "pressed", "inactive", "hover-inactive", "pressed-inactive", "deactivated"]
    for i, st in enumerate(states):
        base = st if st == "deactivated" else st.split("-")[0]
        cv = button_canvas(p, kind, "pressed" if base == "pressed" else base, st.endswith("inactive"))
        body += group(f"{st}-center", cv.svg(0, 0, BTN_W, BTN_H, i * (BTN_W + 4), 0))
    return svg_doc(len(states) * (BTN_W + 4), BTN_H, body)


def write_aurorae(p: Palette, ids: Ids, w: Writer):
    base = f"aurorae/themes/{ids.aurorae}/"
    w(base + "metadata.desktop", "\n".join([
        "[Desktop Entry]", f"Name={ids.display}",
        "Comment=Classic bevelled window borders",
        "X-KDE-PluginInfo-Author=Classic7 project", f"X-KDE-PluginInfo-Name={ids.aurorae}",
        "X-KDE-PluginInfo-Version=0.2", "X-KDE-PluginInfo-License=Apache-2.0",
        "X-Plasma-API=declarativeappletscript", "", ""]))
    w(base + f"{ids.aurorae}rc", "\n".join([
        "[General]",
        f"ActiveTextColor={rgb(p.title_active_text)}", f"InactiveTextColor={rgb(p.title_inactive_text)}",
        "TitleAlignment=Left", "TitleVerticalAlignment=Center", "Animation=0",
        "Shadow=false", "DecorationPosition=0", "",
        "[Layout]",
        f"BorderLeft={BORDER}", f"BorderRight={BORDER}", f"BorderBottom={BORDER}",
        f"TitleEdgeTop={BORDER}", f"TitleEdgeBottom={TITLE_GAP}",
        f"TitleEdgeLeft={BORDER}", f"TitleEdgeRight={BORDER}",
        "TitleEdgeTopMaximized=0", f"TitleEdgeBottomMaximized={TITLE_GAP}",
        "TitleEdgeLeftMaximized=0", "TitleEdgeRightMaximized=0",
        "TitleBorderLeft=3", "TitleBorderRight=3", f"TitleHeight={TITLE_H}",
        f"ButtonWidth={BTN_W}", f"ButtonHeight={BTN_H}", "ButtonSpacing=0",
        "ButtonMarginTop=2", "ButtonMarginTopMaximized=2", "ExplicitButtonSpacer=2",
        "PaddingTop=0", "PaddingBottom=0", "PaddingLeft=0", "PaddingRight=0", "", ""]))
    w(base + "decoration.svg", decoration_svg(p))
    for kind in GLYPHS:
        w(base + f"{kind}.svg", button_svg(p, kind))


# =============================================================================
# 3. Plasma style
# =============================================================================
def frame(items: list[tuple[str, Canvas, tuple[int, int, int, int]]],
          hints: dict[str, tuple[int, int, int, int]] | None = None) -> str:
    """One FrameSvg file. items = [(prefix, canvas, (l, t, r, b) borders)];
    hints = {prefix: (left, top, right, bottom) content margins}."""
    body, y, maxw = "", 0, 0
    for prefix, cv, border in items:
        body += nine_slice(prefix, cv, border, 0, y)
        y += cv.h + 6
        maxw = max(maxw, cv.w)
    hx = maxw + 10
    body += hint("hint-stretch-borders", hx, 30, 4, 4)
    for prefix, _cv, _b in items:
        if prefix:
            body += hint(f"{prefix}-hint-stretch-borders", hx, 30, 4, 4)
    for prefix, (l, t, r, b) in (hints or {}).items():
        pre = f"{prefix}-" if prefix else ""
        body += hint(f"{pre}hint-left-margin", hx, 0, l, 4)
        body += hint(f"{pre}hint-top-margin", hx + 10, 0, 4, t)
        body += hint(f"{pre}hint-right-margin", hx + 20, 0, r, 4)
        body += hint(f"{pre}hint-bottom-margin", hx + 30, 0, 4, b)
        hx += 40
    return svg_doc(hx + 10, max(y, 20), body)


def write_plasma_style(p: Palette, ids: Ids, w: Writer):
    bv = Bevels(p)
    base = f"plasma/desktoptheme/{ids.plasma}/"
    w(base + "metadata.json", json.dumps({
        "KPlugin": {
            "Authors": [{"Name": "Classic7 project"}],
            "Category": "",
            "Description": "Grey, bevelled classic look for panels and popups",
            "EnabledByDefault": True,
            "Id": ids.plasma,
            "License": "Apache-2.0",
            "Name": ids.display,
            "Version": "0.2",
        },
        "X-Plasma-API": "5.0",
    }, indent=4) + "\n")
    w(base + "plasmarc", "\n".join([
        "[Settings]", "FallbackTheme=default", "",
        "[ContrastEffect]", "enabled=false", "",
        "[BlurBehindEffect]", "enabled=false", "",
        "[AdaptiveTransparency]", "enabled=false", "", ""]))

    def bevelled(bevel, center=p.face) -> Canvas:
        cv = Canvas(12, 12, p.face)
        cv.bevel(0, 0, 12, 12, *bevel)
        cv.rect(2, 2, 8, 8, center)
        return cv

    def thin(ring) -> Canvas:
        cv = Canvas(8, 8, None)
        cv.edge(0, 0, 8, 8, *ring)
        return cv

    two, one = (2, 2, 2, 2), (1, 1, 1, 1)

    panel = Canvas(12, 12, p.face)
    panel.bevel(0, 0, 12, 12, *bv.window)
    w(base + "widgets/panel-background.svg", frame([("", panel, two)], {"": (2, 4, 2, 2)}))

    tasks = [
        ("normal", bevelled(bv.button), two),
        ("hover", bevelled(bv.button), two),
        ("minimized", bevelled(bv.button), two),
        ("attention", bevelled(bv.button, p.title_active2), two),
        ("focus", bevelled(bv.pressed, p.task_active), two),
        ("progress", bevelled(bv.button, mix(p.face, p.select, 0.25)), two),
    ]
    w(base + "widgets/tasks.svg", frame(tasks, {"normal": (5, 3, 5, 3)}))

    dialog = Canvas(12, 12, p.face)
    dialog.bevel(0, 0, 12, 12, *bv.window)
    dlg = frame([("", dialog, (3, 3, 3, 3))], {"": (4, 4, 4, 4)})
    w(base + "dialogs/background.svg", dlg)
    w(base + "widgets/background.svg", dlg)

    tip = Canvas(8, 8, p.tooltip)
    tip.edge(0, 0, 8, 8, p.tooltip_text, p.tooltip_text)
    w(base + "widgets/tooltip.svg", frame([("", tip, one)], {"": (4, 3, 4, 3)}))

    buttons = [
        ("normal", bevelled(bv.button), two),
        ("hover", bevelled(bv.button), two),
        ("focus", bevelled(bv.button), two),
        ("pressed", bevelled(bv.pressed), two),
        ("toolbutton-hover", thin(bv.thin_raised), one),
        ("toolbutton-focus", thin(bv.thin_raised), one),
        ("toolbutton-pressed", thin(bv.thin_sunken), one),
    ]
    w(base + "widgets/button.svg", frame(buttons, {
        "normal": (6, 4, 6, 4), "pressed": (6, 4, 6, 4),
        "toolbutton-hover": (4, 4, 4, 4), "toolbutton-pressed": (4, 4, 4, 4)}))

    # Square versions of what Plasma would otherwise borrow from Breeze (rounded):
    # text fields (Start menu search, KRunner, tray popups), list highlights and frames.
    w(base + "widgets/lineedit.svg", frame([("base", bevelled(bv.field, p.window), two)],
                                           {"base": (4, 3, 4, 3)}))

    def tint(amount: float) -> Canvas:
        cv = Canvas(8, 8, mix(p.window, p.select, amount))
        cv.edge(0, 0, 8, 8, mix(p.window, p.select, 0.6), mix(p.window, p.select, 0.6))
        return cv
    w(base + "widgets/viewitem.svg", frame([
        ("hover", tint(0.12), one),
        ("selected", tint(0.25), one),
        ("selected+hover", tint(0.32), one),
    ], {"hover": (4, 2, 4, 2), "selected": (4, 2, 4, 2), "selected+hover": (4, 2, 4, 2)}))
    w(base + "widgets/frame.svg", frame([
        ("plain", thin((p.c_shadow, p.c_shadow)), one),
        ("raised", bevelled(bv.button), two),
        ("sunken", bevelled(bv.field, p.window), two),
    ], {"plain": (2, 2, 2, 2), "raised": (3, 3, 3, 3), "sunken": (3, 3, 3, 3)}))


# =============================================================================
# 4. Start button
# =============================================================================
def emblem(p: Palette, ox: float, oy: float) -> str:
    """Our own Start emblem: a tiny bevelled window, 16x14."""
    cv = Canvas(16, 14, p.face)
    cv.edge(0, 0, 16, 14, p.c_hilight, p.c_dkshadow)
    cv.rect(2, 2, 12, 3, p.title_active)
    cv.rect(10, 3, 3, 1, p.title_active2)
    cv.rect(2, 6, 12, 6, p.window)
    cv.rect(3, 7, 6, 1, p.c_shadow)
    cv.rect(3, 9, 8, 1, p.c_shadow)
    return cv.svg(0, 0, 16, 14, ox, oy)


START_W, START_H = 56, 22


def start_button_body(p: Palette, pressed: bool = False) -> str:
    """The Start button; pressed = sunken bevel with the content moved 1 px down-right."""
    bv = Bevels(p)
    cv = Canvas(START_W, START_H, p.face)
    cv.bevel(0, 0, START_W, START_H, *(bv.pressed if pressed else bv.button))
    d = 1 if pressed else 0
    return (cv.svg(0, 0, START_W, START_H) + emblem(p, 4 + d, 4 + d)
            + f'<text x="{23 + d}" y="{15.5 + d}" font-family="{UI_FONT}, sans-serif" font-size="11" '
              f'font-weight="bold" fill="{p.face_text}" shape-rendering="auto">Start</text>')


# The panel is 30 px thick with 4 + 2 px content margins, so kicker shows the image 24 px
# high. Kicker scales the image to the panel height keeping its aspect ratio, so the file is
# exactly 24 px high (button 22 px + 1 px air) to stay pixel-sharp at 100 % scaling.
START_IMG_W, START_IMG_H = START_W + 2, 24


def start_button_svg(p: Palette, pressed: bool = False) -> str:
    return svg_doc(START_IMG_W, START_IMG_H, f'<g transform="translate(1,1)">{start_button_body(p, pressed)}</g>')


def pressed_path(path: str) -> str:
    """start-button.svg -> start-button-pressed.svg (the Start menu applet's naming rule)."""
    return path[:-4] + "-pressed.svg" if path.endswith(".svg") else path + "-pressed"


# =============================================================================
# 5. Previews
# =============================================================================
def _text(x, y, s, fill, size=11.5, weight="normal", anchor="start"):
    return (f'<text x="{x}" y="{y}" font-family="{UI_FONT}, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" shape-rendering="auto">{esc(s)}</text>')


def _window(p: Palette, x, y, w, h, title, active, gid, buttons=("minimize", "maximize", "close")) -> str:
    bv = Bevels(p)
    cv = Canvas(w, h, p.face)
    cv.bevel(0, 0, w, h, *bv.window)
    s = cv.svg(0, 0, w, h, x, y)
    s += f'<rect x="{x + 4}" y="{y + 4}" width="{w - 8}" height="{TITLE_H}" fill="url(#{gid})"/>'
    s += _text(x + 9, y + 17, title, p.title_active_text if active else p.title_inactive_text, 11.5, "bold")
    bx = x + w - 4 - 2 - BTN_W
    for kind in reversed(buttons):
        s += button_canvas(p, kind, "active").svg(0, 0, BTN_W, BTN_H, bx, y + 6)
        bx -= BTN_W + (2 if kind == "close" else 0)
    return s


def _push_button(p: Palette, x, y, w, h, label, default=False) -> str:
    bv = Bevels(p)
    cv = Canvas(w, h, p.face)
    if default:
        cv.edge(0, 0, w, h, p.c_dkshadow, p.c_dkshadow)
        cv.bevel(1, 1, w - 2, h - 2, *bv.button)
    else:
        cv.bevel(0, 0, w, h, *bv.button)
    return cv.svg(0, 0, w, h, x, y) + _text(x + w / 2, y + h / 2 + 4, label, p.face_text, anchor="middle")


def _field(p: Palette, x, y, w, h, fill) -> str:
    cv = Canvas(w, h, fill)
    cv.bevel(0, 0, w, h, *Bevels(p).field)
    return cv.svg(0, 0, w, h, x, y)


def _scrollbar(p: Palette, x, y, h) -> str:
    bv = Bevels(p)
    w = 16
    track = Canvas(w, h, mix(p.face, p.c_hilight, 0.5))
    s = track.svg(0, 0, w, h, x, y)
    for by, arrow in ((y, [" x ", "xxx"]), (y + h - 16, ["xxx", " x "])):
        cv = Canvas(w, 16, p.face)
        cv.bevel(0, 0, w, 16, *bv.button)
        cv.stamp([r.replace("x", "xx").replace(" ", "  ") for r in arrow], 5, 6, p.face_text)
        s += cv.svg(0, 0, w, 16, x, by)
    thumb = Canvas(w, 30, p.face)
    thumb.bevel(0, 0, w, 30, *bv.button)
    return s + thumb.svg(0, 0, w, 30, x, y + 18)


def appearance_preview_svg(p: Palette, W: int = 420, H: int = 250) -> str:
    """The sample windows shown in the Appearance dialog."""
    defs = (title_gradient("pa", p.title_active, p.title_active2)
            + title_gradient("pi", p.title_inactive, p.title_inactive2))
    out = [f'<rect width="{W}" height="{H}" fill="{p.desktop}"/>']

    # Inactive window (behind)
    out.append(_window(p, 12, 10, 300, 90, "Inactive Window", False, "pi"))
    # Active window with a menu bar and a text area
    ax, ay, aw, ah = 30, 40, 320, 150
    out.append(_window(p, ax, ay, aw, ah, "Active Window", True, "pa"))
    my = ay + 4 + TITLE_H + 2
    out.append(_text(ax + 12, my + 13, "Normal", p.face_text))
    out.append(_text(ax + 70, my + 14, "Disabled", p.c_hilight))
    out.append(_text(ax + 69, my + 13, "Disabled", p.disabled_text))
    out.append(f'<rect x="{ax + 130}" y="{my}" width="62" height="18" fill="{p.select}"/>')
    out.append(_text(ax + 136, my + 13, "Selected", p.select_text))
    fy = my + 22
    out.append(_field(p, ax + 6, fy, aw - 12, ah - (fy - ay) - 6, p.window))
    out.append(_text(ax + 12, fy + 18, "Window Text", p.window_text))
    out.append(_scrollbar(p, ax + aw - 6 - 18, fy + 2, ah - (fy - ay) - 10))
    # Message box
    bx, by, bw, bh = 150, 140, 230, 95
    out.append(_window(p, bx, by, bw, bh, "Message Box", True, "pa", buttons=("close",)))
    out.append(_text(bx + 14, by + 46, "Message Text", p.face_text))
    out.append(_push_button(p, bx + bw / 2 - 37, by + bh - 32, 75, 23, "OK", default=True))
    # Tooltip
    tcv = Canvas(64, 18, p.tooltip)
    tcv.edge(0, 0, 64, 18, p.tooltip_text, p.tooltip_text)
    out.append(tcv.svg(0, 0, 64, 18, 40, 212))
    out.append(_text(47, 225, "ToolTip", p.tooltip_text, 11))
    return svg_doc(W, H, "".join(out), defs)


def classic_scene_svg(p: Palette, W: int = 460, H: int = 260) -> str:
    """Personalization's preview of the Classic look: the same two windows and taskbar as
    classic7aero.scene() draws for Aero and Basic, so the three previews compare."""
    bv = Bevels(p)
    defs = title_gradient("sa", p.title_active, p.title_active2) + title_gradient("si", p.title_inactive, p.title_inactive2)
    out = [f'<rect width="{W}" height="{H}" fill="{p.desktop}"/>']
    area = H - 40                     # where Aero's 40 px taskbar starts (same window places)

    # Documents (inactive, behind)
    x, y, w, h = round(0.40 * W), 14, round(0.56 * W), round(0.72 * area)
    out.append(_window(p, x, y, w, h, "Documents", False, "si"))
    my = y + 4 + TITLE_H + 2
    out.append(_text(x + 10, my + 13, "File   Edit   View   Go   Help", p.face_text))
    fy = my + 20
    out.append(_field(p, x + 6, fy, w - 12, h - (fy - y) - 6, p.window))
    lx = x + round(w * 0.5)               # right of the Notepad window
    for i, name in enumerate(("Music", "Pictures", "Videos")):
        out.append(Canvas(12, 10, "#E8C34A").svg(0, 0, 12, 10, lx, fy + 9 + i * 19))
        out.append(_text(lx + 18, fy + 18 + i * 19, name, p.window_text))

    # Notepad (active, in front)
    x, y, w, h = round(0.07 * W), round(0.30 * area), round(0.52 * W), round(0.62 * area)
    out.append(_window(p, x, y, w, h, "Untitled - Notepad", True, "sa"))
    my = y + 4 + TITLE_H + 2
    out.append(_text(x + 10, my + 13, "File   Edit   Format   View   Help", p.face_text))
    fy = my + 20
    fh = h - (fy - y) - 6
    out.append(_field(p, x + 6, fy, w - 12, fh, p.window))
    for i, line in enumerate(("Classic 7", "Grey 3D borders in the", "colour scheme you pick.")):
        out.append(_text(x + 12, fy + 18 + 17 * i, line, p.window_text))
    out.append(_scrollbar(p, x + w - 6 - 18, fy + 2, fh - 4))

    # Taskbar: Start | Quick Launch | task buttons | notification area
    tb_h = 30
    ty = H - tb_h
    tb = Canvas(W, tb_h, p.face)
    for tx in range(W):
        tb.set(tx, 0, p.c_light)
        tb.set(tx, 1, p.c_hilight)
    out.append(tb.svg(0, 0, W, tb_h, 0, ty))
    out.append(f'<g transform="translate(2,{ty + 4})">{start_button_body(p)}</g>')
    sep = Canvas(2, 22, None)
    sep.rect(0, 0, 1, 22, p.c_shadow)
    sep.rect(1, 0, 1, 22, p.c_hilight)
    out.append(sep.svg(0, 0, 2, 22, 64, ty + 4))
    for i, col in enumerate(["#E8C34A", "#2B6CB0", "#2B2B2B"]):
        cv = Canvas(16, 16, col)
        cv.edge(0, 0, 16, 16, "#FFFFFF", "#404040")
        out.append(cv.svg(0, 0, 16, 16, 72 + i * 22, ty + 7))
    out.append(sep.svg(0, 0, 2, 22, 140, ty + 4))
    bw = int(max(60, min(160, (W - 148 - 92) / 2 - 4)))
    for i, (label, active) in enumerate([("Documents", False), ("Notepad", True)]):
        bx = 148 + i * (bw + 4)
        cv = Canvas(bw, 22, p.face)
        if active:
            cv.bevel(0, 0, bw, 22, *bv.pressed)
            cv.rect(2, 2, bw - 4, 18, p.task_active)
        else:
            cv.bevel(0, 0, bw, 22, *bv.button)
        out.append(cv.svg(0, 0, bw, 22, bx, ty + 4))
        out.append(_text(bx + 8, ty + 19, label, p.face_text, 11.5, "bold" if active else "normal"))
    tray = Canvas(84, 22, p.face)
    tray.edge(0, 0, 84, 22, p.c_shadow, p.c_hilight)
    out.append(tray.svg(0, 0, 84, 22, W - 88, ty + 4))
    out.append(_text(W - 50, ty + 19, "12:00", p.face_text))
    for i, col in enumerate(["#3C8D2F", "#555555"]):
        out.append(Canvas(12, 12, col).svg(0, 0, 12, 12, W - 82 + i * 16, ty + 9))
    return svg_doc(W, H, "".join(out), defs)


def desktop_preview_svg(p: Palette, W: int = 960, H: int = 600) -> str:
    """Full desktop mockup (Global Theme preview and README)."""
    bv = Bevels(p)
    defs = title_gradient("ta", p.title_active, p.title_active2) + title_gradient("ti", p.title_inactive, p.title_inactive2)
    out = [f'<rect width="{W}" height="{H}" fill="{p.desktop}"/>']

    for i, label in enumerate(["Computer", "Documents", "Steam", "Trash"]):
        ix, iy = 22, 18 + i * 78
        cv = Canvas(32, 28, None)
        cv.rect(0, 0, 32, 24, "#D4D0C8")
        cv.edge(0, 0, 32, 24, "#FFFFFF", "#404040")
        cv.rect(3, 3, 26, 17, "#1C5A9C" if i != 2 else "#2B2B2B")
        cv.rect(10, 24, 12, 4, "#808080")
        out.append(cv.svg(0, 0, 32, 28, ix + 8, iy))
        out.append(_text(ix + 24, iy + 44, label, "#FFFFFF", 11, anchor="middle"))

    # Explorer window (inactive)
    ex, ey, ew, eh = 150, 70, 440, 320
    out.append(_window(p, ex, ey, ew, eh, "Home - Dolphin", False, "ti"))
    out.append(_text(ex + 10, ey + 40, "File   Edit   View   Go   Tools   Help", p.face_text))
    nav_y = ey + 48
    for i, lbl in enumerate(["Back", "Fwd", "Up"]):
        out.append(_push_button(p, ex + 8 + i * 42, nav_y, 38, 20, lbl))
    out.append(_field(p, ex + 140, nav_y, ew - 150, 20, p.window))
    out.append(_text(ex + 146, nav_y + 14, "Home  >  Documents", p.window_text))
    cmd_y = nav_y + 24
    for lbl, cx in (("New Folder", 12), ("Views", 100), ("Properties", 150)):
        out.append(_text(ex + cx, cmd_y + 14, lbl, p.face_text))
    body_y = cmd_y + 22
    out.append(_field(p, ex + 6, body_y, 120, eh - (body_y - ey) - 26, p.window))
    for r, n in enumerate(["Home", "  Documents", "  Games", "  Pictures", "Devices", "  Disk (1 TB)"]):
        indent = 14 if n.startswith("  ") else 0
        out.append(_text(ex + 14 + indent, body_y + 18 + r * 19, n.strip(), p.window_text))
    lx = ex + 130
    out.append(_field(p, lx, body_y, ew - 136, eh - (body_y - ey) - 26, p.window))
    hdr = Canvas(ew - 140, 18, p.face)
    hdr.bevel(0, 0, ew - 140, 18, *bv.button)
    out.append(hdr.svg(0, 0, ew - 140, 18, lx + 2, body_y + 2))
    for c, (lbl, cx) in enumerate([("Name", 6), ("Date modified", 120), ("Type", 230)]):
        out.append(_text(lx + 2 + cx, body_y + 15, lbl, p.face_text, 11))
    for r, (n, d, t) in enumerate([("Games", "11-10-2026", "Folder"), ("Pictures", "02-10-2026", "Folder"),
                                   ("setup.log", "11-10-2026", "Log file")]):
        out.append(_text(lx + 8, body_y + 38 + r * 19, n, p.window_text, 11))
        out.append(_text(lx + 122, body_y + 38 + r * 19, d, p.window_text, 11))
        out.append(_text(lx + 232, body_y + 38 + r * 19, t, p.window_text, 11))
    out.append(_text(ex + 10, ey + eh - 9, "3 items", p.face_text, 11))

    # Welcome dialog (active)
    dx, dy, dw, dh = 360, 210, 360, 150
    out.append(_window(p, dx, dy, dw, dh, "Welcome", True, "ta"))
    out.append(f'<circle cx="{dx + 30}" cy="{dy + 54}" r="14" fill="{p.select}" shape-rendering="auto"/>')
    out.append(_text(dx + 30, dy + 60, "i", p.select_text, 16, "bold", "middle"))
    out.append(_text(dx + 60, dy + 46, "Classic 7 is installed and ready.", p.face_text))
    out.append(_text(dx + 60, dy + 68, "Steam, Lutris and Heroic are in the Start menu.", p.face_text))
    out.append(_push_button(p, dx + 180, dy + 110, 75, 23, "OK", default=True))
    out.append(_push_button(p, dx + 264, dy + 110, 75, 23, "Cancel"))

    # Taskbar
    tb_h = 30
    ty = H - tb_h
    tb = Canvas(W, tb_h, p.face)
    for x in range(W):
        tb.set(x, 0, p.c_light)
        tb.set(x, 1, p.c_hilight)
    out.append(tb.svg(0, 0, W, tb_h, 0, ty))
    out.append(f'<g transform="translate(2,{ty + 4})">{start_button_body(p)}</g>')
    sep = Canvas(2, 22, None)
    sep.rect(0, 0, 1, 22, p.c_shadow)
    sep.rect(1, 0, 1, 22, p.c_hilight)
    out.append(sep.svg(0, 0, 2, 22, 64, ty + 4))
    for i, col in enumerate(["#E8C34A", "#2B6CB0", "#2B2B2B"]):
        cv = Canvas(16, 16, col)
        cv.edge(0, 0, 16, 16, "#FFFFFF", "#404040")
        out.append(cv.svg(0, 0, 16, 16, 72 + i * 22, ty + 7))
    out.append(sep.svg(0, 0, 2, 22, 140, ty + 4))
    for i, (label, active) in enumerate([("Home - Dolphin", False), ("Welcome", True)]):
        bx = 148 + i * 164
        cv = Canvas(160, 22, p.face)
        if active:
            cv.bevel(0, 0, 160, 22, *bv.pressed)
            cv.rect(2, 2, 156, 18, p.task_active)
        else:
            cv.bevel(0, 0, 160, 22, *bv.button)
        out.append(cv.svg(0, 0, 160, 22, bx, ty + 4))
        out.append(_text(bx + 8, ty + 19, label, p.face_text, 11.5, "bold" if active else "normal"))
    tray = Canvas(84, 22, p.face)
    tray.edge(0, 0, 84, 22, p.c_shadow, p.c_hilight)
    out.append(tray.svg(0, 0, 84, 22, W - 88, ty + 4))
    out.append(_text(W - 50, ty + 19, "09:52", p.face_text))
    for i, col in enumerate(["#3C8D2F", "#555555"]):
        out.append(Canvas(12, 12, col).svg(0, 0, 12, 12, W - 82 + i * 16, ty + 9))
    return svg_doc(W, H, "".join(out), defs)


# =============================================================================
# 6. GTK recolouring map (used by the Appearance app on its copy of the GTK theme)
# =============================================================================
def gtk_define_colors(p: Palette) -> dict[str, str]:
    """Named colours of the Chicago95-based GTK theme -> this palette."""
    return {
        "bg_color": p.face, "fg_color": p.face_text, "panel_fg_color": p.face_text,
        "base_color": p.window, "text_color": p.window_text, "text_color_light": p.disabled_text,
        "selected_bg_color": p.select, "selected_fg_color": p.select_text,
        "selected_inactive_bg_color": p.c_shadow, "selected_inactive_fg_color": p.face_text,
        "tooltip_bg_color": p.tooltip, "tooltip_fg_color": p.tooltip_text,
        "border_bright": p.c_hilight, "border_light": p.c_light,
        "border_dark": p.c_dkshadow, "border_shade": p.c_shadow,
        "window_title_bg_color": p.title_active, "window_title_text_color": p.title_active_text,
        "inactive_title_bg_color": p.title_inactive, "inactive_title_text_color": p.title_inactive_text,
    }


def gtk_color_map(p: Palette) -> dict[str, str]:
    """Colours baked into the system Classic7 GTK theme's images and CSS -> this palette.
    Keys are the Classic 7 Standard values as they appear after the image build."""
    s = STANDARD
    pairs = [
        (s.face, p.face), ("#C0C0C0", p.face), (s.c_shadow, p.c_shadow),
        (s.c_dkshadow, p.c_dkshadow), (s.select, p.select), ("#000080", p.select),
        ("#FFFFE1", p.tooltip), ("#FFFFFF", p.c_hilight), ("#000000", p.face_text),
    ]
    out: dict[str, str] = {}
    for old, new in pairs:
        out.setdefault(old.upper(), new.upper())
    return out


# =============================================================================
# Render everything
# =============================================================================
def render(p: Palette, data_dir: Path, ids: Ids | None = None, verbose: bool = False) -> list[Path]:
    """Write colour scheme, window decoration, Plasma style and Start button under data_dir
    (e.g. <root>/usr/share or ~/.local/share). Returns the written files."""
    ids = ids or Ids()
    w = Writer(data_dir, verbose)
    w(f"color-schemes/{ids.colors}.colors", color_scheme(p, ids))
    write_aurorae(p, ids, w)
    write_plasma_style(p, ids, w)
    w(ids.start_button, start_button_svg(p))
    w(pressed_path(ids.start_button), start_button_svg(p, pressed=True))
    return w.written
