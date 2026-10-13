"""
Classic 7 Aero and Basic looks, drawn from scratch (no Microsoft artwork):

  - Aurorae window borders   aurorae/themes/<id>/      glass (Aero) or opaque light blue (Basic)
  - Plasma style             plasma/desktoptheme/<id>/ taskbar, task buttons, popups, tooltips
  - Start orb                classic7/<file>.svg       normal, -hover and -pressed
  - KDE colour scheme        color-schemes/Classic7Aero.colors (both looks)

Glass is translucent colour over KWin's blur: the Aurorae "mask" frame and the Plasma style's
translucent/ files tell KWin where to blur. The glass colour, its intensity and whether it is
see-through at all are the user's (Personalization > Window Color); Basic has no options.

Every frame is drawn once as whole shapes (rounded rectangles, rings, gradients) and cut into
the nine pieces KSvg's FrameSvg expects, so corners, edges and gradients line up whatever size
the frame is stretched to. Plain Python, no dependencies (like classic7theme.py, which this
borrows its output ids and writer from).
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import classic7theme as ct

LOOKS = ("aero", "basic", "classic")

# Glass colours offered in Personalization > Window Color (names are plain colour words)
GLASS_COLORS: list[tuple[str, str]] = [
    ("Sky", "#74B8FC"), ("Twilight", "#2D63B0"), ("Sea", "#2FA0A6"), ("Leaf", "#3E9A48"),
    ("Lime", "#94C93D"), ("Sun", "#F2C53D"), ("Pumpkin", "#F08C2E"), ("Ruby", "#C7313E"),
    ("Fuchsia", "#D2479F"), ("Blush", "#EE9FC4"), ("Violet", "#7B4DC0"), ("Lavender", "#B3A3E3"),
    ("Taupe", "#9E8F80"), ("Chocolate", "#6B4630"), ("Slate", "#6E7F92"), ("Frost", "#F2F2F2"),
]


@dataclass
class Glass:
    """The Aero window colour: colour, intensity (0..1, how much colour vs. see-through)
    and whether glass is see-through at all."""
    name: str = "Sky"
    color: str = "#74B8FC"
    intensity: float = 0.45
    transparency: bool = True

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict | None) -> "Glass":
        known = {f.name for f in fields(cls)}
        g = cls(**{k: v for k, v in (data or {}).items() if k in known})
        g.intensity = max(0.0, min(1.0, float(g.intensity)))
        return g


DEFAULT_GLASS = Glass()


def is_default_glass(g: Glass) -> bool:
    return (g.color.upper() == DEFAULT_GLASS.color.upper() and abs(g.intensity - DEFAULT_GLASS.intensity) < 0.005
            and g.transparency == DEFAULT_GLASS.transparency)


# =============================================================================
# Output ids
# =============================================================================
def system_ids(look: str) -> ct.Ids:
    name = "Aero" if look == "aero" else "Basic"
    return ct.Ids(colors="Classic7Aero", colors_name="Classic 7 Aero", plasma=f"classic7-{look}",
                  aurorae=f"Classic7{name}", display=f"Classic 7 {name}",
                  start_button="classic7/start-orb.svg")


def slot_ids(look: str, slot: str) -> ct.Ids:
    """Per-user ids for a user's own glass colour (alternating A/B, as classic7theme.slot_ids)."""
    name = "Aero" if look == "aero" else "Basic"
    return ct.Ids(colors="Classic7Aero", colors_name="Classic 7 Aero",
                  plasma=f"classic7-{look}-user-{slot.lower()}", aurorae=f"Classic7{name}User{slot}",
                  display=f"Classic 7 {name} ({slot})", start_button="classic7/start-orb.svg")


# =============================================================================
# Colours
# =============================================================================
def _rgba(c: str, a: float) -> tuple[str, float]:
    return c, max(0.0, min(1.0, a))


def hexa(c: str) -> str:
    return "#" + "".join(f"{v:02X}" for v in ct._hex(c))


def shade(c: str, t: float) -> str:
    """t > 0 towards white, t < 0 towards black."""
    return ct.mix(c, "#FFFFFF", t) if t >= 0 else ct.mix(c, "#000000", -t)


# =============================================================================
# Geometry: rounded rectangles as polygons, cut to rectangles
# =============================================================================
Point = tuple[float, float]
Poly = list[Point]


def rrect(x: float, y: float, w: float, h: float, tl: float = 0, tr: float = 0, br: float = 0, bl: float = 0,
          seg: int = 10) -> Poly:
    """Clockwise polygon for a rectangle with rounded corners (radii per corner)."""
    pts: Poly = []

    def arc(cx, cy, r, a0, a1):
        for i in range(seg + 1):
            a = a0 + (a1 - a0) * i / seg
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))

    tl, tr, br, bl = (max(0.0, min(r, w / 2, h / 2)) for r in (tl, tr, br, bl))
    if tl:
        arc(x + tl, y + tl, tl, math.pi, 1.5 * math.pi)
    else:
        pts.append((x, y))
    if tr:
        arc(x + w - tr, y + tr, tr, 1.5 * math.pi, 2 * math.pi)
    else:
        pts.append((x + w, y))
    if br:
        arc(x + w - br, y + h - br, br, 0, 0.5 * math.pi)
    else:
        pts.append((x + w, y + h))
    if bl:
        arc(x + bl, y + h - bl, bl, 0.5 * math.pi, math.pi)
    else:
        pts.append((x, y + h))
    return pts


def grow(x, y, w, h, d) -> tuple[float, float, float, float]:
    return x - d, y - d, w + 2 * d, h + 2 * d


def clip(poly: Poly, x0: float, y0: float, x1: float, y1: float) -> Poly:
    """Sutherland-Hodgman: the part of a polygon inside an axis-aligned rectangle."""
    def edge(pts, inside, cut):
        out = []
        n = len(pts)
        for i in range(n):
            cur, prev = pts[i], pts[i - 1]
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur))
        return out

    def at_x(xc):
        return lambda p, q: (xc, p[1] + (q[1] - p[1]) * (xc - p[0]) / (q[0] - p[0]))

    def at_y(yc):
        return lambda p, q: (p[0] + (q[0] - p[0]) * (yc - p[1]) / (q[1] - p[1]), yc)

    pts = poly
    for inside, cut in ((lambda p: p[0] >= x0, at_x(x0)), (lambda p: p[0] <= x1, at_x(x1)),
                        (lambda p: p[1] >= y0, at_y(y0)), (lambda p: p[1] <= y1, at_y(y1))):
        if not pts:
            break
        pts = edge(pts, inside, cut)
    return pts


def _f(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def path_d(polys: list[Poly], dx: float = 0, dy: float = 0) -> str:
    out = []
    for poly in polys:
        if len(poly) < 3:
            continue
        out.append("M" + " L".join(f"{_f(x + dx)},{_f(y + dy)}" for x, y in poly) + " Z")
    return " ".join(out)


# =============================================================================
# Drawings: layers of shapes, cut into FrameSvg pieces
# =============================================================================
@dataclass
class Layer:
    polys: list[Poly]          # sub-paths, filled even-odd (a ring = outer + inner)
    fill: str                  # colour, or "url(#id)"
    opacity: float = 1.0
    rule: str = "evenodd"      # "nonzero" for shapes that overlap themselves (an X)


class Defs:
    """Gradients for one SVG file (ids are unique per file)."""

    def __init__(self):
        self.items: list[str] = []
        self.n = 0

    def linear(self, x1, y1, x2, y2, stops: list[tuple[float, str, float]]) -> str:
        """stops: (offset 0..1, colour, opacity); user-space coordinates."""
        self.n += 1
        gid = f"g{self.n}"
        s = "".join(f'<stop offset="{_f(o)}" stop-color="{hexa(c)}" stop-opacity="{_f(a)}"/>' for o, c, a in stops)
        self.items.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{_f(x1)}" y1="{_f(y1)}" '
                          f'x2="{_f(x2)}" y2="{_f(y2)}">{s}</linearGradient>')
        return f"url(#{gid})"

    def radial(self, cx, cy, rx, ry, stops: list[tuple[float, str, float]]) -> str:
        self.n += 1
        gid = f"g{self.n}"
        s = "".join(f'<stop offset="{_f(o)}" stop-color="{hexa(c)}" stop-opacity="{_f(a)}"/>' for o, c, a in stops)
        # an ellipse: a unit circle scaled in user space
        sy = ry / rx if rx else 1
        self.items.append(f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="{_f(cx)}" cy="{_f(cy / sy)}" '
                          f'r="{_f(rx)}" gradientTransform="scale(1,{_f(sy)})">{s}</radialGradient>')
        return f"url(#{gid})"

    def svg(self) -> str:
        return "".join(self.items)


def layer_svg(layers: list[Layer], x0: float, y0: float, x1: float, y1: float) -> str:
    """The layers' parts inside the rectangle, as SVG paths (no offset: drawings sit where they are)."""
    out = []
    for lay in layers:
        polys = [clip(p, x0, y0, x1, y1) for p in lay.polys]
        polys = [p for p in polys if len(p) >= 3]
        if not polys or lay.opacity <= 0:
            continue
        op = f' fill-opacity="{_f(lay.opacity)}"' if lay.opacity < 1 else ""
        out.append(f'<path d="{path_d(polys)}" fill="{lay.fill}"{op} fill-rule="{lay.rule}"/>')
    return "".join(out)


def invisible(x, y, w, h) -> str:
    """Gives a piece its full size even where nothing is drawn."""
    return f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="#000000" fill-opacity="0"/>'


def nine(prefix: str, layers: list[Layer], x: float, y: float, w: float, h: float,
         left: float, top: float, right: float, bottom: float) -> str:
    """The nine FrameSvg pieces of a drawing that occupies (x, y, w, h)."""
    p = f"{prefix}-" if prefix else ""
    cw, ch = w - left - right, h - top - bottom
    cols = ((x, left), (x + left, cw), (x + left + cw, right))
    rows = ((y, top), (y + top, ch), (y + top + ch, bottom))
    names = (("topleft", "top", "topright"), ("left", "center", "right"), ("bottomleft", "bottom", "bottomright"))
    out = ""
    for (ry, rh), row in zip(rows, names):
        for (rx, rw), name in zip(cols, row):
            if rw <= 0 or rh <= 0:
                continue
            out += ct.group(p + name, invisible(rx, ry, rw, rh) + layer_svg(layers, rx, ry, rx + rw, ry + rh))
    return out


def ring(outer: Poly, inner: Poly | None) -> list[Poly]:
    return [outer] + ([inner] if inner else [])


def doc(w: float, h: float, body: str, defs: Defs) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(w)}" height="{_f(h)}" '
            f'viewBox="0 0 {_f(w)} {_f(h)}">\n<defs>{defs.svg()}</defs>\n{body}\n</svg>\n')


# =============================================================================
# 1. Window borders (Aurorae)
# =============================================================================
BORDER = 8                    # left, right and bottom glass
TITLE_EDGE_TOP = 1
TITLE_H = 21                  # the caption row (icon, title, buttons)
TOP = 30                      # whole top border: 1 + 21 + 8
MAX_TOP = 23                  # maximized: 0 + 21 + 2
SHADOW = 12                   # shadow band around Aero windows (Aurorae's padding)
R_TOP, R_BOTTOM = 7, 4        # outer corner radii
BTN_H = 20
BTN_W = {"minimize": 27, "maximize": 27, "restore": 27, "close": 47}
STRETCH = 40                  # size of the stretchable middle in the drawings


@dataclass
class FrameColors:
    """Everything one state (active/inactive) of a window border needs."""
    fill: str
    fill_a: float
    frost_a: float            # white haze over the colour
    gloss_a: float            # highlight at the top of the title bar
    outline: str
    outline_a: float
    inner_a: float            # light line inside the outline
    edge_a: float             # dark line around the window's contents
    shadow_a: float           # 0 = no shadow
    title_text: str


def aero_frames(g: Glass) -> tuple[FrameColors, FrameColors]:
    tint = hexa(g.color)
    if g.transparency:
        a = 0.18 + 0.62 * g.intensity
        frost = 0.27 - 0.19 * g.intensity        # less white haze the stronger the colour
        act = FrameColors(tint, a, frost, 0.45, "#000000", 0.62, 0.55, 0.45, 0.32, "#000000")
        ina = FrameColors(shade(tint, 0.35), a * 0.55, frost + 0.08, 0.30, "#000000", 0.38, 0.45, 0.30, 0.20,
                          "#4A4A4A")
    else:
        # see-through off: the colour mixed with white, opaque
        act = FrameColors(shade(tint, 0.62 - 0.40 * g.intensity), 1.0, 0.0, 0.45, "#000000", 0.62, 0.55, 0.45,
                          0.32, "#000000")
        ina = FrameColors(shade(tint, 0.80 - 0.30 * g.intensity), 1.0, 0.0, 0.30, "#000000", 0.38, 0.45, 0.30,
                          0.20, "#4A4A4A")
    return act, ina


def basic_frames() -> tuple[FrameColors, FrameColors]:
    act = FrameColors("#B9D1EA", 1.0, 0.0, 0.0, "#4F6B8D", 1.0, 0.65, 0.55, 0.0, "#000000")
    ina = FrameColors("#D7E4F2", 1.0, 0.0, 0.0, "#8EA1B8", 1.0, 0.65, 0.35, 0.0, "#434E54")
    return act, ina


def frame_layers(fc: FrameColors, d: Defs, x: float, y: float, w: float, h: float, top: float,
                 basic: bool, pad: float) -> list[Layer]:
    """A window border drawn at (x, y, w, h) (the window's outer edge; shadow outside it),
    with the contents area inside its borders."""
    layers: list[Layer] = []
    outer = rrect(x, y, w, h, R_TOP, R_TOP, R_BOTTOM, R_BOTTOM)
    cx, cy, cw, ch = x + BORDER, y + top, w - 2 * BORDER, h - top - BORDER
    contents = rrect(cx, cy, cw, ch)
    # shadow: rings fading outwards, a little lower than the window
    if fc.shadow_a > 0 and pad > 0:
        steps = int(pad)
        for i in range(steps):
            t = 1 - (i + 0.5) / steps
            a = fc.shadow_a * t * t
            o = rrect(*grow(x, y + 2, w, h, i + 1), R_TOP + i + 1, R_TOP + i + 1, R_BOTTOM + i + 1, R_BOTTOM + i + 1)
            inn = rrect(*grow(x, y + 2, w, h, i), R_TOP + i, R_TOP + i, R_BOTTOM + i, R_BOTTOM + i)
            layers.append(Layer(ring(o, inn), "#000000", a))
    body = ring(outer, contents)
    if basic:
        fill = d.linear(0, y, 0, y + top, [(0, shade(fc.fill, 0.55), 1), (0.45, shade(fc.fill, 0.18), 1),
                                            (1, fc.fill, 1)])
        layers.append(Layer(body, fill, 1.0))
    else:
        layers.append(Layer(body, fc.fill, fc.fill_a))
        if fc.frost_a > 0:
            layers.append(Layer(body, "#FFFFFF", fc.frost_a))
        if fc.gloss_a > 0:
            gloss = d.linear(0, y, 0, y + top, [(0, "#FFFFFF", fc.gloss_a), (0.55, "#FFFFFF", fc.gloss_a * 0.25),
                                                 (1, "#FFFFFF", 0)])
            layers.append(Layer(body, gloss, 1.0))
    # light line inside the outline, dark outline
    i1 = rrect(*grow(x, y, w, h, -1), R_TOP - 1, R_TOP - 1, R_BOTTOM - 1, R_BOTTOM - 1)
    i2 = rrect(*grow(x, y, w, h, -2), R_TOP - 2, R_TOP - 2, R_BOTTOM - 2, R_BOTTOM - 2)
    layers.append(Layer(ring(i1, i2), "#FFFFFF", fc.inner_a))
    layers.append(Layer(ring(outer, i1), fc.outline, fc.outline_a))
    # around the contents: a light line, then a dark one touching them
    c1 = rrect(*grow(cx, cy, cw, ch, 1))
    c2 = rrect(*grow(cx, cy, cw, ch, 2))
    layers.append(Layer(ring(c2, c1), "#FFFFFF", fc.inner_a * 0.7))
    layers.append(Layer(ring(c1, contents), fc.outline, fc.edge_a))
    return layers


def maximized_layers(fc: FrameColors, d: Defs, x: float, y: float, w: float, h: float, basic: bool) -> list[Layer]:
    """The title strip of a maximized window (no borders), as a tile."""
    band = [rrect(x, y, w, h)]
    layers = []
    if basic:
        fill = d.linear(0, y, 0, y + h, [(0, shade(fc.fill, 0.55), 1), (0.45, shade(fc.fill, 0.18), 1),
                                          (1, fc.fill, 1)])
        layers.append(Layer(band, fill))
    else:
        layers.append(Layer(band, fc.fill, fc.fill_a))
        if fc.frost_a > 0:
            layers.append(Layer(band, "#FFFFFF", fc.frost_a))
        gloss = d.linear(0, y, 0, y + h, [(0, "#FFFFFF", fc.gloss_a), (0.6, "#FFFFFF", fc.gloss_a * 0.25),
                                           (1, "#FFFFFF", 0)])
        layers.append(Layer(band, gloss))
    layers.append(Layer([rrect(x, y + h - 1, w, 1)], fc.outline, fc.edge_a))
    return layers


def decoration_svg(look: str, g: Glass) -> str:
    basic = look == "basic"
    act, ina = basic_frames() if basic else aero_frames(g)
    pad = 0 if basic else SHADOW
    d = Defs()
    W = 2 * (pad + BORDER) + STRETCH
    H = (pad + TOP) + STRETCH + (BORDER + pad)
    body = ""
    gap = 20
    for i, (prefix, fc) in enumerate((("decoration", act), ("decoration-inactive", ina))):
        oy = i * (H + gap)
        layers = frame_layers(fc, d, pad, oy + pad, W - 2 * pad, H - 2 * pad, TOP, basic, pad)
        body += nine(prefix, layers, 0, oy, W, H, pad + BORDER, pad + TOP, pad + BORDER, pad + BORDER)
        mx = W + gap
        mprefix = "decoration-maximized" if i == 0 else "decoration-maximized-inactive"
        body += ct.group(f"{mprefix}-center", invisible(mx, oy, STRETCH, MAX_TOP)
                         + layer_svg(maximized_layers(fc, d, mx, oy, STRETCH, MAX_TOP, basic),
                                     mx, oy, mx + STRETCH, oy + MAX_TOP))
    hx = W * 2 + 2 * gap
    body += ct.hint("hint-stretch-borders", hx, 0, 4, 4)
    for prefix in ("decoration", "decoration-inactive"):
        body += ct.hint(f"{prefix}-hint-stretch-borders", hx, 10, 4, 4)
    for prefix in ("decoration-maximized", "decoration-maximized-inactive"):
        body += ct.hint(f"{prefix}-hint-tile-center", hx, 20, 4, 4)
    if not basic and g.transparency:
        # where KWin blurs: the border itself (no shadow); Aurorae renders this frame 1 px smaller
        # all round than the decoration and moves it by (1 - padding)
        my = 2 * (H + gap)
        mw, mh = W - 2, H - 2
        o = rrect(pad - 1, my + pad - 1, W - 2 * pad, H - 2 * pad, R_TOP, R_TOP, R_BOTTOM, R_BOTTOM)
        inner = rrect(pad - 1 + BORDER, my + pad - 1 + TOP, W - 2 * pad - 2 * BORDER, H - 2 * pad - TOP - BORDER)
        body += nine("mask", [Layer(ring(o, inner), "#000000", 1.0)], 0, my, mw, mh,
                     pad - 1 + BORDER, pad - 1 + TOP, pad - 1 + BORDER, pad - 1 + BORDER)
        body += ct.hint("mask-hint-stretch-borders", hx, 30, 4, 4)
        total_h = my + mh
    else:
        total_h = 2 * (H + gap)
    return doc(hx + 10, total_h, body, d)


# ---- caption buttons ---------------------------------------------------------------------------
@dataclass
class ButtonLook:
    top: tuple[str, str]       # gradient of the upper half (top, middle)
    bottom: tuple[str, str]    # lower half (middle, bottom)
    alpha: float               # body opacity (glass buttons are partly see-through)
    outline: str
    outline_a: float
    glow: str | None = None    # a light from below (hover)
    glyph_a: float = 1.0


def button_looks(kind: str, look: str) -> dict[str, ButtonLook]:
    red = kind == "close"
    if look == "basic":
        normal = (ButtonLook(("#F2C1B8", "#E08D7E"), ("#C9472F", "#D86C55"), 1.0, "#6B2A22", 1.0) if red else
                  ButtonLook(("#F7FAFE", "#E3EDF8"), ("#C8DAEF", "#D9E7F7"), 1.0, "#57718F", 1.0))
        inactive = ButtonLook(("#F4F7FB", "#E9EFF6"), ("#D9E3EF", "#E3EBF4"), 1.0, "#8EA1B8", 1.0, glyph_a=0.75)
    else:
        normal = (ButtonLook(("#F0B3A6", "#D9786A"), ("#C0402C", "#D2644F"), 0.92, "#3B0F09", 0.85) if red else
                  ButtonLook(("#FFFFFF", "#E3EEF8"), ("#BFD3E8", "#D8E6F4"), 0.42, "#000000", 0.55))
        inactive = ButtonLook(("#FFFFFF", "#F1F5F9"), ("#DFE7EF", "#EBF0F5"), 0.22, "#000000", 0.30, glyph_a=0.75)
    hover = (ButtonLook(("#F9C9BD", "#EE8669"), ("#E4300F", "#F86D4F"), 1.0, "#3B0F09", 0.9, glow="#FFD27A") if red else
             ButtonLook(("#E9F7FF", "#A9DDFB"), ("#2D9BE1", "#5FC7FF"), 1.0, "#0B2A49", 0.8, glow="#BFF2FF"))
    pressed = (ButtonLook(("#D7907F", "#B04A35"), ("#7F1405", "#A32A16"), 1.0, "#2E0A05", 0.95) if red else
               ButtonLook(("#9DC3E2", "#5C8DB9"), ("#123F72", "#2B6BA7"), 1.0, "#071A30", 0.9))
    return {"active": normal, "hover": hover, "pressed": pressed, "inactive": inactive,
            "hover-inactive": hover, "pressed-inactive": pressed,
            "deactivated": ButtonLook(normal.top, normal.bottom, normal.alpha * 0.8, normal.outline,
                                      normal.outline_a * 0.8, glyph_a=0.35),
            "deactivated-inactive": ButtonLook(inactive.top, inactive.bottom, inactive.alpha, inactive.outline,
                                               inactive.outline_a, glyph_a=0.3)}


def box(x, y, w, h) -> Poly:
    return rrect(x, y, w, h)


def glyph_layers(kind: str, x: float, y: float, w: float, h: float, alpha: float) -> list[Layer]:
    """The white symbol with a thin dark edge, on whole pixels in the middle of (x, y, w, h)."""
    gx, gy = round(x + (w - 11) / 2), round(y + (h - 10) / 2)
    dark, white = [], []
    if kind == "minimize":
        white = [Layer([box(gx + 1, gy + 6, 9, 3)], "#FFFFFF", alpha)]
        dark = [Layer([box(gx, gy + 5, 11, 5)], "#000000", 0.45 * alpha)]
    elif kind == "maximize":
        white = [Layer([box(gx + 1, gy + 1, 9, 8), box(gx + 2, gy + 3, 7, 5)], "#FFFFFF", alpha)]
        dark = [Layer([box(gx, gy, 11, 10), box(gx + 3, gy + 4, 5, 3)], "#000000", 0.45 * alpha)]
    elif kind == "restore":
        def window(ox, oy):
            return [box(gx + ox, gy + oy, 8, 6), box(gx + ox + 1, gy + oy + 2, 6, 3)]
        front = window(0, 3)
        back = window(3, 0)
        fy0, fx1 = gy + 3, gx + 8
        # the back window only where the front one doesn't cover it
        back_vis = [clip(p, fx1, gy - 1, gx + 12, gy + 12) for p in back] + \
                   [clip(p, gx - 1, gy - 1, fx1, fy0) for p in back]
        white = [Layer(back_vis, "#FFFFFF", alpha), Layer(front, "#FFFFFF", alpha)]
        dark = [Layer([box(gx + 2, gy - 1, 10, 8), box(gx - 1, gy + 2, 10, 8)], "#000000", 0.45 * alpha, "nonzero")]
    else:
        cx, cy = gx + 5.5, gy + 5
        bars, edges = [], []
        for ang in (40.0, 140.0):
            a = math.radians(ang)
            ux, uy = math.cos(a), math.sin(a)
            vx, vy = -uy, ux
            for t, s_, out in ((1.25, 5.6, bars), (2.25, 6.6, edges)):
                out.append([(cx + ux * s_ + vx * t, cy + uy * s_ + vy * t), (cx - ux * s_ + vx * t, cy - uy * s_ + vy * t),
                            (cx - ux * s_ - vx * t, cy - uy * s_ - vy * t), (cx + ux * s_ - vx * t, cy + uy * s_ - vy * t)])
        white = [Layer(bars, "#FFFFFF", alpha, "nonzero")]
        dark = [Layer(edges, "#000000", 0.45 * alpha, "nonzero")]
    return dark + white


def button_layers(kind: str, bl: ButtonLook, d: Defs, x: float, y: float, w: float, h: float) -> list[Layer]:
    """One caption button: the three join into one strip (Minimize rounded bottom-left,
    Close bottom-right; neighbours share their outline)."""
    left_round = 4 if kind == "minimize" else 0
    right_round = 4 if kind == "close" else 0
    inner = rrect(x + 1, y + 1, w - 2, h - 2, 0, 0, max(0, right_round - 1), max(0, left_round - 1))
    hl = rrect(x + 2, y + 2, w - 4, h - 4, 0, 0, max(0, right_round - 2), max(0, left_round - 2))
    mid = y + h * 0.5
    layers = [
        Layer([inner], d.linear(0, y, 0, mid, [(0, bl.top[0], 1), (1, bl.top[1], 1)]), bl.alpha),
        Layer([clip(inner, x, mid, x + w, y + h)], d.linear(0, mid, 0, y + h, [(0, bl.bottom[0], 1),
                                                                               (1, bl.bottom[1], 1)]), bl.alpha),
    ]
    if bl.glow:
        layers.append(Layer([inner], d.radial(x + w / 2, y + h, w * 0.45, h * 0.75,
                                             [(0, bl.glow, 0.95), (0.6, bl.glow, 0.35), (1, bl.glow, 0)])))
    layers.append(Layer(ring(inner, hl), "#FFFFFF", 0.45 * max(bl.alpha, 0.6)))
    # outline: all round for Minimize; the left side is the neighbour's for Maximize and Close
    lx = x if kind in ("minimize",) else x - 1
    out = rrect(lx, y, w + (x - lx), h, 0, 0, right_round, left_round)
    out_in = rrect(lx + 1, y + 1, w + (x - lx) - 2, h - 2, 0, 0, max(0, right_round - 1), max(0, left_round - 1))
    layers.append(Layer([clip(p, x, y, x + w, y + h) for p in ring(out, out_in)], bl.outline, bl.outline_a))
    return layers + glyph_layers(kind, x, y, w, h, bl.glyph_a)


def button_svg(kind: str, look: str) -> str:
    d = Defs()
    w, h = BTN_W[kind], BTN_H
    body = ""
    looks = button_looks("close" if kind == "close" else kind, look)
    for i, (state, bl) in enumerate(looks.items()):
        x = i * (w + 6)
        body += ct.group(f"{state}-center", invisible(x, 0, w, h) + layer_svg(button_layers(kind, bl, d, x, 0, w, h),
                                                                            x, 0, x + w, h))
    return doc(len(looks) * (w + 6), h, body, d)


def write_aurorae(look: str, g: Glass, ids: ct.Ids, w: ct.Writer):
    base = f"aurorae/themes/{ids.aurorae}/"
    act, ina = basic_frames() if look == "basic" else aero_frames(g)
    pad = 0 if look == "basic" else SHADOW
    w(base + "metadata.desktop", "\n".join([
        "[Desktop Entry]", f"Name={ids.display}",
        "Comment=" + ("Light blue window borders" if look == "basic" else "Glass window borders"),
        "X-KDE-PluginInfo-Author=Classic7 project", f"X-KDE-PluginInfo-Name={ids.aurorae}",
        "X-KDE-PluginInfo-Version=1.0", "X-KDE-PluginInfo-License=Apache-2.0",
        "X-Plasma-API=declarativeappletscript", "", ""]))
    w(base + f"{ids.aurorae}rc", "\n".join([
        "[General]",
        f"ActiveTextColor={ct.rgb(act.title_text)}", f"InactiveTextColor={ct.rgb(ina.title_text)}",
        "TitleAlignment=Left", "TitleVerticalAlignment=Center", "Animation=0", "DecorationPosition=0", "",
        "[Layout]",
        f"BorderLeft={BORDER}", f"BorderRight={BORDER}", f"BorderBottom={BORDER}",
        f"TitleEdgeTop={TITLE_EDGE_TOP}", f"TitleEdgeBottom={TOP - TITLE_EDGE_TOP - TITLE_H}",
        "TitleEdgeLeft=8", "TitleEdgeRight=6",
        "TitleEdgeTopMaximized=0", f"TitleEdgeBottomMaximized={MAX_TOP - TITLE_H}",
        "TitleEdgeLeftMaximized=4", "TitleEdgeRightMaximized=2",
        "TitleBorderLeft=6", "TitleBorderRight=6", f"TitleHeight={TITLE_H}",
        f"ButtonWidth={BTN_W['minimize']}", f"ButtonWidthMinimize={BTN_W['minimize']}",
        f"ButtonWidthMaximizeRestore={BTN_W['maximize']}", f"ButtonWidthClose={BTN_W['close']}",
        "ButtonWidthMenu=16", "ButtonWidthAppMenu=16", f"ButtonHeight={BTN_H}", "ButtonSpacing=0",
        "ButtonMarginTop=0", "ButtonMarginTopMaximized=0", "ExplicitButtonSpacer=4",
        f"PaddingTop={pad}", f"PaddingBottom={pad}", f"PaddingLeft={pad}", f"PaddingRight={pad}", "", ""]))
    w(base + "decoration.svg", decoration_svg(look, g))
    for kind in ("minimize", "maximize", "restore", "close"):
        w(base + f"{kind}.svg", button_svg(kind, look))


# =============================================================================
# 2. Plasma style: taskbar, task buttons, popups, tooltips, controls
# =============================================================================
@dataclass
class Box:
    """A rounded box: fill (colour or gradient stops top->bottom), outline, a light inner line,
    and an optional gloss over the upper part."""
    fill: list[tuple[float, str, float]]      # vertical gradient stops (offset, colour, opacity)
    outline: str | None = None
    outline_a: float = 1.0
    inner: str | None = None
    inner_a: float = 0.0
    gloss_a: float = 0.0
    radius: float = 3
    glow: str | None = None                   # light from the bottom middle
    glow_a: float = 0.0


def box_layers(b: Box, d: Defs, x: float, y: float, w: float, h: float) -> list[Layer]:
    r = b.radius
    shape = rrect(x, y, w, h, r, r, r, r)
    i1 = rrect(x + 1, y + 1, w - 2, h - 2, *(max(0, r - 1),) * 4) if b.outline else shape
    fill = d.linear(0, y, 0, y + h, b.fill) if len(b.fill) > 1 else b.fill[0][1]
    layers = [Layer([i1], fill, 1.0 if len(b.fill) > 1 else b.fill[0][2])]
    if b.gloss_a:
        layers.append(Layer([i1], d.linear(0, y, 0, y + h, [(0, "#FFFFFF", b.gloss_a), (0.5, "#FFFFFF", b.gloss_a * 0.35),
                                                             (0.5001, "#FFFFFF", 0), (1, "#FFFFFF", 0)])))
    if b.glow and b.glow_a:
        layers.append(Layer([i1], d.radial(x + w / 2, y + h, w * 0.55, h * 0.8,
                                           [(0, b.glow, b.glow_a), (1, b.glow, 0)])))
    if b.inner and b.inner_a:
        i2 = rrect(x + 2, y + 2, w - 4, h - 4, *(max(0, r - 2),) * 4)
        layers.append(Layer(ring(i1, i2), b.inner, b.inner_a))
    if b.outline:
        layers.append(Layer(ring(shape, i1), b.outline, b.outline_a))
    return layers


class Sheet:
    """One Plasma style SVG file: several framed boxes under prefixes, plus margin hints."""

    def __init__(self):
        self.d = Defs()
        self.body = ""
        self.y = 0
        self.hints: list[tuple[str, tuple[int, int, int, int]]] = []
        self.width = 0

    def frame(self, prefix: str, layers_fn, w: float, h: float, borders: tuple[float, float, float, float],
              margins: tuple[int, int, int, int] | None = None):
        layers = layers_fn(self.d, 0, self.y, w, h)
        self.body += nine(prefix, layers, 0, self.y, w, h, *borders)
        if margins:
            self.hints.append((prefix, margins))
        self.y += h + 8
        self.width = max(self.width, w)

    def box(self, prefix: str, b: Box, w: float = 24, h: float = 24, border: float = 6,
            margins: tuple[int, int, int, int] | None = None):
        self.frame(prefix, lambda d, x, y, ww, hh: box_layers(b, d, x, y, ww, hh), w, h, (border,) * 4, margins)

    def element(self, eid: str, content_fn, w: float, h: float):
        self.body += ct.group(eid, invisible(0, self.y, w, h) + layer_svg(content_fn(self.d, 0, self.y, w, h),
                                                                           0, self.y, w, h + self.y))
        self.y += h + 8
        self.width = max(self.width, w)

    def svg(self, stretch: bool = True) -> str:
        hx = self.width + 12
        body = self.body
        if stretch:
            body += ct.hint("hint-stretch-borders", hx, 0, 4, 4)
        for prefix, (l, t, r, b) in self.hints:
            pre = f"{prefix}-" if prefix else ""
            if stretch and prefix:
                body += ct.hint(f"{pre}hint-stretch-borders", hx, 0, 4, 4)
            body += ct.hint(f"{pre}hint-left-margin", hx + 10, 0, max(l, 0.01), 4)
            body += ct.hint(f"{pre}hint-top-margin", hx + 30, 0, 4, max(t, 0.01))
            body += ct.hint(f"{pre}hint-right-margin", hx + 40, 0, max(r, 0.01), 4)
            body += ct.hint(f"{pre}hint-bottom-margin", hx + 50, 0, 4, max(b, 0.01))
            hx += 70
        return doc(hx + 10, max(self.y, 20), body, self.d)


@dataclass
class StyleColors:
    look: str
    panel: list[tuple[float, str, float]]       # taskbar body, top->bottom
    panel_line: tuple[str, float]               # dark line along the top edge
    panel_light: tuple[str, float]              # light line under it
    popup: list[tuple[float, str, float]]
    popup_outline: tuple[str, float]
    popup_inner: tuple[str, float]
    glass: bool                                 # the taskbar and popups are glass (white text)


def style_colors(look: str, g: Glass, translucent: bool) -> StyleColors:
    if look == "basic":
        return StyleColors(
            "basic",
            panel=[(0, "#E4EEF9", 1), (0.5, "#CBDCF0", 1), (1, "#B7CCE6", 1)],
            panel_line=("#6E87A8", 1.0), panel_light=("#FFFFFF", 0.85),
            popup=[(0, "#F7FAFD", 1), (1, "#E6EDF6", 1)],
            popup_outline=("#7F97B5", 1.0), popup_inner=("#FFFFFF", 0.9), glass=False)
    tint = hexa(g.color)
    dark = shade(tint, -0.62)
    a = (0.48 + 0.35 * g.intensity) if (translucent and g.transparency) else 1.0
    pa = (0.80 + 0.12 * g.intensity) if (translucent and g.transparency) else 1.0
    return StyleColors(
        "aero",
        panel=[(0, shade(dark, 0.22), a), (0.5, dark, a), (1, shade(dark, -0.25), a)],
        panel_line=("#000000", 0.55), panel_light=("#FFFFFF", 0.40),
        popup=[(0, shade(dark, 0.18), pa), (1, shade(dark, -0.15), pa)],
        popup_outline=("#000000", 0.60), popup_inner=("#FFFFFF", 0.30), glass=True)


def panel_layers(sc: StyleColors, d: Defs, x: float, y: float, w: float, h: float) -> list[Layer]:
    full = [rrect(x, y, w, h)]
    layers = [Layer(full, d.linear(0, y, 0, y + h, sc.panel))]
    if sc.glass:
        layers.append(Layer(full, d.linear(0, y, 0, y + h, [(0, "#FFFFFF", 0.16), (0.5, "#FFFFFF", 0.05),
                                                             (0.5001, "#FFFFFF", 0), (1, "#FFFFFF", 0)])))
    layers.append(Layer([rrect(x, y, w, 1)], sc.panel_line[0], sc.panel_line[1]))
    layers.append(Layer([rrect(x, y + 1, w, 1)], sc.panel_light[0], sc.panel_light[1]))
    # the other edges: a thin line (seen when the taskbar is not at the bottom of the screen)
    layers.append(Layer([rrect(x, y + h - 1, w, 1), rrect(x, y + 1, 1, h - 2), rrect(x + w - 1, y + 1, 1, h - 2)],
                        sc.panel_line[0], sc.panel_line[1] * 0.6, "nonzero"))
    return layers


def popup_layers(sc: StyleColors, d: Defs, x: float, y: float, w: float, h: float, r: float = 6) -> list[Layer]:
    shape = rrect(x, y, w, h, r, r, r, r)
    i1 = rrect(x + 1, y + 1, w - 2, h - 2, r - 1, r - 1, r - 1, r - 1)
    i2 = rrect(x + 2, y + 2, w - 4, h - 4, r - 2, r - 2, r - 2, r - 2)
    layers = [Layer([i1], d.linear(0, y, 0, y + h, sc.popup))]
    if sc.glass:
        layers.append(Layer([i1], d.linear(0, y, 0, y + h, [(0, "#FFFFFF", 0.14), (0.12, "#FFFFFF", 0.04),
                                                             (1, "#FFFFFF", 0)])))
    layers.append(Layer(ring(i1, i2), sc.popup_inner[0], sc.popup_inner[1]))
    layers.append(Layer(ring(shape, i1), sc.popup_outline[0], sc.popup_outline[1]))
    return layers


def shadow_elements(sheet: Sheet, size: int = 14, alpha: float = 0.30, r: float = 6):
    """shadow-top, shadow-topright, ... around a box (Plasma draws them outside popups)."""
    s = size
    inner_w = inner_h = 2 * r + 4
    W, H = 2 * s + inner_w, 2 * s + inner_h
    y0 = sheet.y
    layers = []
    for i in range(s):
        t = 1 - (i + 0.5) / s
        a = alpha * t * t
        o = rrect(s - i - 1, y0 + s - i - 1 + 2, inner_w + 2 * (i + 1), inner_h + 2 * (i + 1), *(r + i + 1,) * 4)
        inn = rrect(s - i, y0 + s - i + 2, inner_w + 2 * i, inner_h + 2 * i, *(r + i,) * 4)
        layers.append(Layer(ring(o, inn), "#000000", a))
    parts = {"topleft": (0, y0, s, s), "top": (s, y0, inner_w, s), "topright": (s + inner_w, y0, s, s),
             "left": (0, y0 + s, s, inner_h), "right": (s + inner_w, y0 + s, s, inner_h),
             "bottomleft": (0, y0 + s + inner_h, s, s), "bottom": (s, y0 + s + inner_h, inner_w, s),
             "bottomright": (s + inner_w, y0 + s + inner_h, s, s)}
    for name, (x, y, w, h) in parts.items():
        sheet.body += ct.group(f"shadow-{name}", invisible(x, y, w, h) + layer_svg(layers, x, y, x + w, y + h))
    sheet.y += H + 8
    sheet.width = max(sheet.width, W)


def light_button(kind: str) -> Box:
    """The Windows 7 push button (also used by the Kvantum and GTK styles' colours)."""
    if kind == "hover":
        return Box([(0, "#EAF6FD", 1), (0.5, "#D9F0FC", 1), (0.5001, "#BEE6FD", 1), (1, "#A7D9F5", 1)],
                   "#3C7FB1", 1.0, "#FFFFFF", 0.6)
    if kind == "pressed":
        return Box([(0, "#E5F4FC", 1), (0.5, "#C4E5F6", 1), (0.5001, "#98D1EF", 1), (1, "#68B3DB", 1)],
                   "#2C628B", 1.0, "#9EB0BA", 0.5)
    if kind == "focus":
        return Box([(0, "#F2F2F2", 1), (0.5, "#EBEBEB", 1), (0.5001, "#DDDDDD", 1), (1, "#CFCFCF", 1)],
                   "#3399FF", 1.0, "#FFFFFF", 0.7)
    return Box([(0, "#F2F2F2", 1), (0.5, "#EBEBEB", 1), (0.5001, "#DDDDDD", 1), (1, "#CFCFCF", 1)],
               "#707070", 1.0, "#FFFFFF", 0.7)


def task_boxes(sc: StyleColors) -> dict[str, Box]:
    if sc.glass:
        return {
            "normal": Box([(0, "#FFFFFF", 0.14), (1, "#FFFFFF", 0.04)], "#000000", 0.45, "#FFFFFF", 0.28),
            "minimized": Box([(0, "#FFFFFF", 0.14), (1, "#FFFFFF", 0.04)], "#000000", 0.45, "#FFFFFF", 0.28),
            "hover": Box([(0, "#FFFFFF", 0.32), (1, "#FFFFFF", 0.10)], "#000000", 0.55, "#FFFFFF", 0.50,
                         glow="#FFFFFF", glow_a=0.30),
            "focus": Box([(0, "#FFFFFF", 0.28), (1, "#FFFFFF", 0.12)], "#000000", 0.60, "#FFFFFF", 0.55,
                         glow="#BFE6FF", glow_a=0.25),
            "attention": Box([(0, "#FFC56E", 0.75), (1, "#F07C18", 0.65)], "#3A1A00", 0.6, "#FFFFFF", 0.4),
            "progress": Box([(0, "#7BE07F", 0.55), (1, "#2EA836", 0.55)], None, 0, None, 0),
        }
    return {
        "normal": Box([(0, "#FBFDFF", 1), (1, "#DCE8F6", 1)], "#91A9C7", 1.0, "#FFFFFF", 0.8),
        "minimized": Box([(0, "#FBFDFF", 1), (1, "#DCE8F6", 1)], "#91A9C7", 1.0, "#FFFFFF", 0.8),
        "hover": Box([(0, "#FFFFFF", 1), (1, "#D3E6FB", 1)], "#5F8BC0", 1.0, "#FFFFFF", 0.9),
        "focus": Box([(0, "#C8DBF1", 1), (1, "#DBE8F6", 1)], "#5C7AA3", 1.0, "#AEC2DA", 0.8),
        "attention": Box([(0, "#FFE0A8", 1), (1, "#F9B04C", 1)], "#A86414", 1.0, "#FFFFFF", 0.6),
        "progress": Box([(0, "#A8EDA5", 1), (1, "#4CC452", 1)], None, 0, None, 0),
    }


def panel_svg(look: str, g: Glass, translucent: bool) -> str:
    """The taskbar's background (also drawn by Personalization's previews)."""
    sc = style_colors(look, g, translucent)
    panel = Sheet()
    panel.frame("", lambda d, x, y, ww, hh: panel_layers(sc, d, x, y, ww, hh), 40, 40, (1, 2, 1, 1), (0, 1, 0, 0))
    return panel.svg()


def write_plasma_style(look: str, g: Glass, ids: ct.Ids, w: ct.Writer):
    base = f"plasma/desktoptheme/{ids.plasma}/"
    glass_look = look == "aero"
    w(base + "metadata.json", json.dumps({
        "KPlugin": {
            "Authors": [{"Name": "Classic7 project"}], "Category": "",
            "Description": "Glass taskbar and popups" if glass_look else "Light blue taskbar and popups",
            "EnabledByDefault": True, "Id": ids.plasma, "License": "Apache-2.0",
            "Name": ids.display, "Version": "1.0"},
        "X-Plasma-API": "5.0"}, indent=4) + "\n")
    blur = glass_look and g.transparency
    w(base + "plasmarc", "\n".join([
        "[Settings]", "FallbackTheme=default", "",
        "[ContrastEffect]", "enabled=false", "",
        "[BlurBehindEffect]", f"enabled={'true' if blur else 'false'}", "",
        "[AdaptiveTransparency]", "enabled=false", "", ""]))
    if glass_look:
        w(base + "colors", glass_colors_file())

    variants = [("", False)] + ([("translucent/", True)] if blur else [])
    for sub, translucent in variants:
        sc = style_colors(look, g, translucent)
        w(base + sub + "widgets/panel-background.svg", panel_svg(look, g, translucent))
        popup = Sheet()
        popup.frame("", lambda d, x, y, ww, hh: popup_layers(sc, d, x, y, ww, hh), 30, 30, (7, 7, 7, 7), (8, 8, 8, 8))
        shadow_elements(popup)
        text = popup.svg()
        w(base + sub + "dialogs/background.svg", text)
        w(base + sub + "widgets/background.svg", text)
        tip = Sheet()
        tip.frame("", lambda d, x, y, ww, hh: popup_layers(sc, d, x, y, ww, hh, r=4), 24, 24, (5, 5, 5, 5),
                  (6, 4, 6, 4))
        shadow_elements(tip, 10, 0.25, 4)
        w(base + sub + "widgets/tooltip.svg", tip.svg())

    sc = style_colors(look, g, False)
    tasks = Sheet()
    for prefix, b in task_boxes(sc).items():
        tasks.box(prefix, b, 30, 30, 5, (4, 3, 4, 3) if prefix == "normal" else None)
    w(base + "widgets/tasks.svg", tasks.svg())

    buttons = Sheet()
    for prefix, kind in (("normal", "normal"), ("hover", "hover"), ("focus", "focus"), ("pressed", "pressed")):
        buttons.box(prefix, light_button(kind), 24, 24, 4, (6, 4, 6, 4))
    if glass_look:
        flat = {"toolbutton-hover": Box([(0, "#FFFFFF", 0.30), (1, "#FFFFFF", 0.12)], "#000000", 0.45, "#FFFFFF", 0.45),
                "toolbutton-focus": Box([(0, "#FFFFFF", 0.22), (1, "#FFFFFF", 0.08)], "#000000", 0.40, "#FFFFFF", 0.40),
                "toolbutton-pressed": Box([(0, "#000000", 0.25), (1, "#000000", 0.10)], "#000000", 0.55, "#FFFFFF", 0.15)}
    else:
        flat = {"toolbutton-hover": light_button("hover"), "toolbutton-focus": light_button("hover"),
                "toolbutton-pressed": light_button("pressed")}
    for prefix, b in flat.items():
        buttons.box(prefix, b, 24, 24, 4, (4, 4, 4, 4))
    w(base + "widgets/button.svg", buttons.svg())

    field = Sheet()
    field.box("base", Box([(0, "#FFFFFF", 1)], "#ABADB3", 1.0, None, 0, radius=2), 20, 20, 3, (4, 3, 4, 3))
    field.box("hover", Box([(0, "#FFFFFF", 1)], "#7EB4EA", 1.0, None, 0, radius=2), 20, 20, 3)
    field.box("focus", Box([(0, "#FFFFFF", 1)], "#569DE5", 1.0, None, 0, radius=2), 20, 20, 3)
    w(base + "widgets/lineedit.svg", field.svg())

    items = Sheet()
    if glass_look:
        sel = {"hover": Box([(0, "#FFFFFF", 0.20), (1, "#FFFFFF", 0.08)], "#FFFFFF", 0.45, None, 0),
               "selected": Box([(0, "#FFFFFF", 0.32), (1, "#FFFFFF", 0.16)], "#FFFFFF", 0.65, None, 0),
               "selected+hover": Box([(0, "#FFFFFF", 0.38), (1, "#FFFFFF", 0.20)], "#FFFFFF", 0.75, None, 0)}
    else:
        sel = {"hover": Box([(0, "#FAFBFD", 1), (1, "#EBF3FD", 1)], "#B8D6FB", 1.0, None, 0),
               "selected": Box([(0, "#DCEBFC", 1), (1, "#C1DBFC", 1)], "#7DA2CE", 1.0, None, 0),
               "selected+hover": Box([(0, "#DCEBFC", 1), (1, "#C1DBFC", 1)], "#7DA2CE", 1.0, None, 0)}
    for prefix, b in sel.items():
        items.box(prefix, b, 20, 20, 3, (4, 2, 4, 2))
    w(base + "widgets/viewitem.svg", items.svg())

    frames = Sheet()
    line = ("#FFFFFF", 0.25) if glass_look else ("#A0AFC3", 1.0)
    frames.box("plain", Box([(0, "#FFFFFF", 0)], line[0], line[1], None, 0, radius=2), 12, 12, 2, (2, 2, 2, 2))
    frames.box("raised", Box([(0, "#FFFFFF", 0.06 if glass_look else 0.5)], line[0], line[1], "#FFFFFF", 0.2, radius=2),
               12, 12, 2, (3, 3, 3, 3))
    frames.box("sunken", Box([(0, "#000000", 0.12 if glass_look else 0.04)], "#000000", 0.35, None, 0, radius=2),
               12, 12, 2, (3, 3, 3, 3))
    w(base + "widgets/frame.svg", frames.svg())


def glass_colors_file() -> str:
    """Plasma colours for the glass style: white text on the taskbar and popups; lists, buttons
    and fields stay light with black text (as on the Windows 7 Start menu)."""
    def group(name, vals):
        return [f"[Colors:{name}]"] + [f"{k}={ct.rgb(v)}" for k, v in vals.items()] + [""]
    glass_fg = {"ForegroundNormal": "#FFFFFF", "ForegroundInactive": "#C8D4E2", "ForegroundActive": "#FFFFFF",
                "ForegroundLink": "#9CD0FF", "ForegroundVisited": "#D2B8FF", "ForegroundNegative": "#FF8A80",
                "ForegroundNeutral": "#FFD27A", "ForegroundPositive": "#8EE59A",
                "DecorationFocus": "#7FC4FF", "DecorationHover": "#A9D8FF"}
    light_fg = {"ForegroundNormal": "#000000", "ForegroundInactive": "#6D6D6D", "ForegroundActive": "#0066CC",
                "ForegroundLink": "#0066CC", "ForegroundVisited": "#800080", "ForegroundNegative": "#C00000",
                "ForegroundNeutral": "#B06000", "ForegroundPositive": "#008000",
                "DecorationFocus": "#3399FF", "DecorationHover": "#7EB4EA"}
    lines = []
    lines += group("Window", {"BackgroundNormal": "#253547", "BackgroundAlternate": "#2E4157", **glass_fg})
    lines += group("Header", {"BackgroundNormal": "#253547", "BackgroundAlternate": "#2E4157", **glass_fg})
    lines += group("Tooltip", {"BackgroundNormal": "#253547", "BackgroundAlternate": "#2E4157", **glass_fg})
    lines += group("Complementary", {"BackgroundNormal": "#1B2633", "BackgroundAlternate": "#253547", **glass_fg})
    lines += group("View", {"BackgroundNormal": "#FFFFFF", "BackgroundAlternate": "#F3F6FA", **light_fg})
    lines += group("Button", {"BackgroundNormal": "#F0F0F0", "BackgroundAlternate": "#E6E6E6", **light_fg})
    lines += group("Selection", {"BackgroundNormal": "#3399FF", "BackgroundAlternate": "#5CADFF",
                                 **{**glass_fg, "ForegroundNormal": "#FFFFFF"}})
    return "\n".join(lines)


# =============================================================================
# 3. The Start orb
# =============================================================================
ORB_W, ORB_H = 54, 40


def orb_svg(state: str = "normal") -> str:
    """A round glass button with Classic 7's emblem (a small window). state: normal/hover/pressed."""
    d = Defs()
    return doc(ORB_W, ORB_H, orb_parts(d, state), d)


def orb_parts(d: Defs, state: str = "normal") -> str:
    """The orb's shapes at (0, 0) - (ORB_W, ORB_H), with gradients in d."""
    cx, cy, r = ORB_W / 2, ORB_H / 2, 17.5
    if state == "hover":
        body = [(0, "#BDEBFF", 1), (0.45, "#3C9BE6", 1), (1, "#0D3D7A", 1)]
        core = "#E6FBFF"
    elif state == "pressed":
        body = [(0, "#6FB0E6", 1), (0.45, "#1E5FA8", 1), (1, "#06234A", 1)]
        core = "#9FD7FF"
    else:
        body = [(0, "#8CD0FF", 1), (0.45, "#2B78C8", 1), (1, "#0A2F63", 1)]
        core = "#C4EEFF"
    parts = []

    def circle(rr, fill, op=1.0, ccx=cx, ccy=cy, rule=""):
        parts.append(f'<circle cx="{_f(ccx)}" cy="{_f(ccy)}" r="{_f(rr)}" fill="{fill}"'
                     + (f' fill-opacity="{_f(op)}"' if op < 1 else "") + "/>")

    if state == "hover":
        circle(r + 2.5, d.radial(cx, cy, r + 2.5, r + 2.5, [(0.80, "#9FE4FF", 0.6), (1, "#9FE4FF", 0)]))
    circle(r, "#05142B", 0.85)                                                  # dark rim
    circle(r - 1, d.radial(cx, cy + r * 0.55, r * 1.25, r * 1.1, body))         # the sphere, lit from below
    circle(r - 1, d.radial(cx, cy + r * 0.7, r * 0.75, r * 0.45, [(0, core, 0.85), (1, core, 0)]))
    # glossy upper half
    parts.append(f'<ellipse cx="{_f(cx)}" cy="{_f(cy - r * 0.42)}" rx="{_f(r * 0.78)}" ry="{_f(r * 0.52)}" '
                 f'fill="{d.linear(0, cy - r, 0, cy, [(0, "#FFFFFF", 0.85), (1, "#FFFFFF", 0.08)])}"/>')
    # the emblem: a little window, white with a dark edge
    ew, eh = 15, 13
    ex, ey = round(cx - ew / 2), round(cy - eh / 2 + 1)
    parts.append(f'<rect x="{ex - 1}" y="{ey - 1}" width="{ew + 2}" height="{eh + 2}" rx="2.5" fill="#001A3A" '
                 'fill-opacity="0.55"/>')
    parts.append(f'<rect x="{ex}" y="{ey}" width="{ew}" height="{eh}" rx="2" fill="#FFFFFF"/>')
    parts.append(f'<rect x="{ex + 1.5}" y="{ey + 4}" width="{ew - 3}" height="{eh - 5.5}" rx="0.8" '
                 f'fill="{d.linear(0, ey + 4, 0, ey + eh, [(0, "#3F8FE0", 1), (1, "#1B5AAE", 1)])}"/>')
    parts.append(f'<rect x="{ex + ew - 5}" y="{ey + 1.2}" width="3.2" height="1.8" rx="0.5" fill="#D9473A"/>')
    return "".join(parts)


# =============================================================================
# 4. Colour scheme for applications (Aero and Basic)
# =============================================================================
def color_scheme() -> str:
    def group(name, vals):
        return [f"[Colors:{name}]"] + [f"{k}={ct.rgb(v)}" for k, v in sorted(vals.items())] + [""]
    common = {"ForegroundInactive": "#6D6D6D", "ForegroundActive": "#0066CC", "ForegroundLink": "#0066CC",
              "ForegroundVisited": "#800080", "ForegroundNegative": "#C00000", "ForegroundNeutral": "#B06000",
              "ForegroundPositive": "#008000", "DecorationFocus": "#3399FF", "DecorationHover": "#7EB4EA"}
    lines = ["[ColorEffects:Disabled]", "Color=109,109,109", "ColorAmount=0", "ColorEffect=0", "ContrastAmount=0.55",
             "ContrastEffect=1", "IntensityAmount=0", "IntensityEffect=0", "",
             "[ColorEffects:Inactive]", "ChangeSelectionColor=false", "Enable=false", ""]
    lines += group("Window", {**common, "BackgroundNormal": "#F0F0F0", "BackgroundAlternate": "#F7F7F7",
                              "ForegroundNormal": "#000000"})
    lines += group("Button", {**common, "BackgroundNormal": "#F0F0F0", "BackgroundAlternate": "#E3E3E3",
                              "ForegroundNormal": "#000000"})
    lines += group("View", {**common, "BackgroundNormal": "#FFFFFF", "BackgroundAlternate": "#F5F8FB",
                            "ForegroundNormal": "#000000"})
    lines += group("Header", {**common, "BackgroundNormal": "#F0F0F0", "BackgroundAlternate": "#F0F0F0",
                              "ForegroundNormal": "#000000"})
    lines += group("Tooltip", {**common, "BackgroundNormal": "#FFFFFF", "BackgroundAlternate": "#E4E5F0",
                               "ForegroundNormal": "#575757"})
    lines += group("Selection", {**common, "BackgroundNormal": "#3399FF", "BackgroundAlternate": "#5CADFF",
                                 "ForegroundNormal": "#FFFFFF", "ForegroundInactive": "#E5F1FF",
                                 "ForegroundActive": "#FFFFFF", "ForegroundLink": "#E5F1FF",
                                 "ForegroundVisited": "#F0E0FF"})
    lines += group("Complementary", {**common, "BackgroundNormal": "#253547", "BackgroundAlternate": "#1B2633",
                                     "ForegroundNormal": "#FFFFFF", "ForegroundInactive": "#C8D4E2"})
    lines += ["[General]", "ColorScheme=Classic7Aero", "Name=Classic 7 Aero", "shadeSortColumn=true", "",
              "[KDE]", "contrast=4", "",
              "[WM]", f"activeBackground={ct.rgb('#B9D1EA')}", f"activeBlend={ct.rgb('#DCE9F7')}",
              "activeForeground=0,0,0", f"inactiveBackground={ct.rgb('#D7E4F2')}",
              f"inactiveBlend={ct.rgb('#EBF1F8')}", "inactiveForeground=67,78,84", ""]
    return "\n".join(lines)


# =============================================================================
# 5. Previews (Personalization): a small desktop drawn with the theme's own pieces
# =============================================================================
PREVIEW_BAR = 40              # taskbar height in the previews


def _all(layers: list[Layer]) -> str:
    return layer_svg(layers, -1e5, -1e5, 1e5, 1e5)


def _text(x: float, y: float, s: str, fill: str = "#000000", size: float = 12, weight: int = 400,
          anchor: str = "start") -> str:
    return (f'<text x="{_f(x)}" y="{_f(y)}" font-family="{ct.UI_FONT}" font-size="{_f(size)}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{ct.esc(s)}</text>')


def _icon(kind: str, d: Defs, x: float, y: float, s: float = 16) -> str:
    """Plain program icons for the previews: folder, page or globe, s pixels square."""
    k = s / 16

    def r(ax, ay, aw, ah, rad=0.0):
        return rrect(x + ax * k, y + ay * k, aw * k, ah * k, rad * k, rad * k, rad * k, rad * k)

    if kind == "folder":
        return _all([Layer([r(1, 1.5, 6, 3, 1), r(1, 2.5, 14, 11.5, 1.2)], "#B7862A", 1.0, "nonzero"),
                     Layer([r(1.5, 5, 13, 8.5, 1)], d.linear(0, y + 5 * k, 0, y + 14 * k,
                                                              [(0, "#FFE9A6", 1), (1, "#F0B93A", 1)]))])
    if kind == "page":
        lines = [r(4.5, 4 + 2.4 * i, 7, 1) for i in range(4)]
        return _all([Layer([r(2.5, 0.5, 11, 15, 1)], "#6F7F92"), Layer([r(3.5, 1.5, 9, 13, 0.5)], "#FFFFFF"),
                     Layer(lines, "#5B8FD0")])
    return _all([Layer([r(1, 1, 14, 14, 7)], "#1A4F8F"),
                 Layer([r(1.8, 1.8, 12.4, 12.4, 6.2)], d.radial(x + 8 * k, y + 11 * k, 9 * k, 9 * k,
                                                                [(0, "#9EE2FF", 1), (1, "#2A7FD6", 1)])),
                 Layer([r(4, 4, 5, 4, 2), r(8.5, 8, 4.5, 4, 2)], "#4FB548", 0.9, "nonzero"),
                 Layer([r(4, 2.5, 8, 4.5, 2.25)], "#FFFFFF", 0.45)])


def _window(d: Defs, look: str, fc: FrameColors, pad: float, x: float, y: float, w: float, h: float,
            title: str, icon: str, active: bool) -> tuple[str, Poly, Poly]:
    """A window's border, caption buttons, icon and title; returns (svg, outer edge, contents)."""
    basic = look == "basic"
    out = _all(frame_layers(fc, d, x, y, w, h, TOP, basic, pad))
    bx = x + w - 6                                   # TitleEdgeRight
    for kind in ("close", "maximize", "minimize"):
        bx -= BTN_W[kind]
        bl = button_looks(kind, look)["active" if active else "inactive"]
        out += _all(button_layers(kind, bl, d, bx, y + TITLE_EDGE_TOP, BTN_W[kind], BTN_H))
    out += _icon(icon, d, x + 8, y + TITLE_EDGE_TOP + (TITLE_H - 16) / 2)
    out += _text(x + 8 + 16 + 6, y + TITLE_EDGE_TOP + TITLE_H / 2 + 4.3, title, fc.title_text, 12)
    outer = rrect(x, y, w, h, R_TOP, R_TOP, R_BOTTOM, R_BOTTOM)
    contents = rrect(x + BORDER, y + TOP, w - 2 * BORDER, h - TOP - BORDER)
    return out, outer, contents


def _notepad(d: Defs, x: float, y: float, w: float, h: float) -> str:
    mb, sb = 20, 17
    out = _all([Layer([rrect(x, y, w, h)], "#FFFFFF"),
                Layer([rrect(x, y, w, mb)], d.linear(0, y, 0, y + mb, [(0, "#FFFFFF", 1), (1, "#E6ECF4", 1)])),
                Layer([rrect(x, y + mb - 1, w, 1)], "#D2DAE4")])
    tx = x + 8
    for word in ("File", "Edit", "Format", "View", "Help"):
        out += _text(tx, y + 14, word, "#000000", 11.5)
        tx += len(word) * 6.6 + 12
    for i, line in enumerate(("Classic 7", "Glass in the colour", "you pick.")):
        out += _text(x + 5, y + mb + 17 + 17 * i, line, "#000000", 12)
    track = rrect(x + w - sb, y + mb, sb, h - mb)
    thumb = rrect(x + w - sb + 2, y + mb + 18, sb - 4, max(18, (h - mb) * 0.4), 2, 2, 2, 2)
    out += _all([Layer([track], "#F0F0F0"), Layer([rrect(x + w - sb, y + mb, 1, h - mb)], "#E3E3E3"),
                 Layer([thumb], d.linear(x + w - sb, 0, x + w, 0, [(0, "#F5F5F5", 1), (1, "#DADADA", 1)])),
                 Layer(ring(thumb, rrect(x + w - sb + 3, y + mb + 19, sb - 6, max(16, (h - mb) * 0.4 - 2), 1, 1, 1, 1)),
                       "#979797")])
    return out


def _explorer(d: Defs, x: float, y: float, w: float, h: float) -> str:
    bar = 24
    nav = min(84, w * 0.32)
    out = _all([Layer([rrect(x, y, w, h)], "#FFFFFF"),
                Layer([rrect(x, y, w, bar)], d.linear(0, y, 0, y + bar, [(0, "#FAFCFE", 1), (1, "#E1EAF5", 1)])),
                Layer([rrect(x, y + bar - 1, w, 1)], "#B6C6D9"),
                Layer([rrect(x + nav, y + bar, 1, h - bar)], "#D6E5F5")])
    out += _text(x + 10, y + 16, "Organize ▾      New folder", "#1E395B", 11)
    for i, label in enumerate(("Favorites", "Libraries", "Computer", "Network")):
        out += _icon("folder" if i < 2 else "page" if i == 2 else "globe", d, x + 6, y + bar + 8 + 20 * i, 12)
        out += _text(x + 22, y + bar + 18 + 20 * i, label, "#1E395B", 11)
    fx = x + nav + 12
    for label in ("Music", "Pictures", "Videos"):
        if fx + 40 > x + w:
            break
        out += _icon("folder", d, fx + 4, y + bar + 10, 32)
        out += _text(fx + 20, y + bar + 56, label, "#000000", 11, anchor="middle")
        fx += 56
    return out


def _taskbar(d: Defs, look: str, g: Glass, W: float, H: float, translucent: bool) -> str:
    sc = style_colors(look, g, translucent)
    y = H - PREVIEW_BAR
    out = _all(panel_layers(sc, d, 0, y, W, PREVIEW_BAR))
    out += f'<g transform="translate(0,{_f(y)})">{orb_parts(d)}</g>'
    boxes = task_boxes(style_colors(look, g, False))
    bx = ORB_W + 4
    for icon, state in (("folder", "normal"), ("page", "focus"), ("globe", None)):
        if state:
            out += _all(box_layers(boxes[state], d, bx, y + 2, 56, PREVIEW_BAR - 3))
        out += _icon(icon, d, bx + 16, y + 8, 24)
        bx += 58
    fg = "#FFFFFF" if sc.glass else "#000000"
    # notification area: network bars and a speaker, the clock, then Show desktop
    tx = W - 15 - 58
    out += _all([Layer([rrect(tx - 34 + 3.2 * i, y + 26 - 3 * i, 2.2, 3 + 3 * i) for i in range(4)], fg, 0.95),
                 Layer([[(tx - 16, y + 17), (tx - 13, y + 17), (tx - 9, y + 13), (tx - 9, y + 27), (tx - 13, y + 23),
                         (tx - 16, y + 23)]], fg, 0.95)])
    out += _text(tx + 29, y + 25, "12:00", fg, 12, anchor="middle")
    out += _all([Layer([rrect(W - 15, y + 1, 1, PREVIEW_BAR - 1)], "#000000", 0.45 if sc.glass else 0.30),
                 Layer([rrect(W - 14, y + 2, 1, PREVIEW_BAR - 2)], "#FFFFFF", 0.35)])
    return out


def scene(look: str, g: Glass, W: float = 460, H: float = 260) -> list[tuple[str, list[list[Poly]]]]:
    """Personalization's preview of Aero or Basic: a desktop (no wallpaper) with two windows and
    the taskbar, drawn with the same pieces as the real theme. Layers in painting order, each an
    SVG of W x H and the glass areas (rings of polygons) where KWin would blur what is behind."""
    basic = look == "basic"
    act, ina = basic_frames() if basic else aero_frames(g)
    pad = 0 if basic else SHADOW
    see_through = look == "aero" and g.transparency
    area = H - PREVIEW_BAR
    layers = []
    for fc, (fx, fy, fw, fh), title, icon, active in (
            (ina, (0.40 * W, 14, 0.56 * W, 0.72 * area), "Documents", "folder", False),
            (act, (0.07 * W, 0.30 * area, 0.52 * W, 0.62 * area), "Notepad", "page", True)):
        d = Defs()
        x, y, w, h = round(fx), round(fy), round(fw), round(fh)
        svg, outer, contents = _window(d, look, fc, pad, x, y, w, h, title, icon, active)
        fill = _notepad if active else _explorer
        svg += fill(d, x + BORDER, y + TOP, w - 2 * BORDER, h - TOP - BORDER)
        layers.append((doc(W, H, svg, d), [[outer, contents]] if see_through else []))
    d = Defs()
    layers.append((doc(W, H, _taskbar(d, look, g, W, H, see_through), d),
                   [[rrect(0, H - PREVIEW_BAR, W, PREVIEW_BAR)]] if see_through else []))
    return layers


# =============================================================================
# Render everything
# =============================================================================
def render(look: str, g: Glass, data_dir: Path, ids: ct.Ids | None = None, verbose: bool = False,
           with_scheme: bool = True) -> list[Path]:
    """Window borders, Plasma style (and the colour scheme and orb) for Aero or Basic under
    data_dir (<root>/usr/share at build time, ~/.local/share for a user's own glass colour)."""
    ids = ids or system_ids(look)
    w = ct.Writer(Path(data_dir), verbose)
    write_aurorae(look, g, ids, w)
    write_plasma_style(look, g, ids, w)
    if with_scheme:
        w("color-schemes/Classic7Aero.colors", color_scheme())
        for state in ("normal", "hover", "pressed"):
            w("classic7/start-orb" + ("" if state == "normal" else f"-{state}") + ".svg", orb_svg(state))
    return w.written
