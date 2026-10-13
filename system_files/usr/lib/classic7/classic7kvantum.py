"""
Classic 7 Aero controls for Qt programs: a Kvantum theme (Classic7Aero.kvconfig + .svg) with the
Windows 7 look of push buttons, check boxes, radio buttons, combo boxes, text fields, tabs,
headers, scroll bars, sliders, progress bars, menus, tooltips and list selections. Drawn from
scratch with the same shape code as classic7aero.py; used by both the Aero and the Basic look.

    python3 classic7kvantum.py OUTDIR      writes OUTDIR/Classic7Aero/Classic7Aero.{kvconfig,svg}
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import classic7aero as A
from classic7aero import Defs, Layer, invisible, layer_svg, ring, rrect

THEME = "Classic7Aero"


class KSheet:
    """Elements laid out in rows on one SVG page."""

    def __init__(self):
        self.d = Defs()
        self.parts: list[str] = []
        self.x = 0.0
        self.y = 0.0
        self.row_h = 0.0
        self.max_w = 0.0

    def place(self, w: float, h: float) -> tuple[float, float]:
        if self.x + w > 900:
            self.x = 0
            self.y += self.row_h + 6
            self.row_h = 0
        pos = (self.x, self.y)
        self.x += w + 6
        self.row_h = max(self.row_h, h)
        self.max_w = max(self.max_w, self.x)
        return pos

    def element(self, eid: str, w: float, h: float, draw):
        x, y = self.place(w, h)
        layers = draw(self.d, x, y, w, h)
        self.parts.append(f'<g id="{eid}">{invisible(x, y, w, h)}{layer_svg(layers, x, y, x + w, y + h)}</g>\n')

    def frame(self, name: str, state: str, w: float, h: float, b: float, draw, interior: bool = True,
              interior_name: str | None = None):
        """Frame pieces <name>-<state>-<pos> and, if wanted, the interior <name>-<state>."""
        x, y = self.place(w, h)
        layers = draw(self.d, x, y, w, h)
        pre = f"{name}-{state}"
        cw, ch = w - 2 * b, h - 2 * b
        cols = ((x, b), (x + b, cw), (x + b + cw, b))
        rows = ((y, b), (y + b, ch), (y + b + ch, b))
        names = (("topleft", "top", "topright"), ("left", None, "right"), ("bottomleft", "bottom", "bottomright"))
        for (ry, rh), row in zip(rows, names):
            for (rx, rw), pos in zip(cols, row):
                if pos is None:
                    if interior:
                        eid = f"{interior_name or name}-{state}"
                        self.parts.append(f'<g id="{eid}">{invisible(rx, ry, rw, rh)}'
                                          f'{layer_svg(layers, rx, ry, rx + rw, ry + rh)}</g>\n')
                    continue
                self.parts.append(f'<g id="{pre}-{pos}">{invisible(rx, ry, rw, rh)}'
                                  f'{layer_svg(layers, rx, ry, rx + rw, ry + rh)}</g>\n')

    def svg(self) -> str:
        return A.doc(self.max_w + 10, self.y + self.row_h + 10, "".join(self.parts), self.d)


# ---- shapes -----------------------------------------------------------------------------------------
def boxed(outline: str | None, inner: str | None, inner_a: float, fill, r: float = 3, outline_a: float = 1.0,
          sides: str = "trbl"):
    """A rounded box: fill is a colour or a function (defs, x, y, w, h) -> paint. sides: which
    outline edges to draw (t r b l)."""
    def draw(d: Defs, x, y, w, h):
        rr = (r if "t" in sides and "l" in sides else 0, r if "t" in sides and "r" in sides else 0,
              r if "b" in sides and "r" in sides else 0, r if "b" in sides and "l" in sides else 0)
        ox0, oy0 = (x if "l" in sides else x - 1), (y if "t" in sides else y - 1)
        ox1, oy1 = (x + w if "r" in sides else x + w + 1), (y + h if "b" in sides else y + h + 1)
        shape = rrect(ox0, oy0, ox1 - ox0, oy1 - oy0, *rr)
        i1 = rrect(ox0 + 1, oy0 + 1, ox1 - ox0 - 2, oy1 - oy0 - 2, *(max(0, v - 1) for v in rr))
        i2 = rrect(ox0 + 2, oy0 + 2, ox1 - ox0 - 4, oy1 - oy0 - 4, *(max(0, v - 1.5) for v in rr))
        paint = fill(d, x, y, w, h) if callable(fill) else fill
        layers = []
        if paint:
            layers.append(Layer([i1 if outline else shape], paint))
        if inner and inner_a:
            layers.append(Layer(ring(i1, i2), inner, inner_a))
        if outline:
            layers.append(Layer(ring(shape, i1), outline, outline_a))
        return layers
    return draw


def vgrad(*stops):
    """Vertical gradient over the element: stops (offset, colour[, opacity])."""
    def paint(d: Defs, x, y, w, h):
        return d.linear(0, y, 0, y + h, [(s[0], s[1], s[2] if len(s) > 2 else 1) for s in stops])
    return paint


def hgrad(*stops):
    def paint(d: Defs, x, y, w, h):
        return d.linear(x, 0, x + w, 0, [(s[0], s[1], s[2] if len(s) > 2 else 1) for s in stops])
    return paint


def two_part(a, b, c, e):
    """The Windows 7 glossy split: a->b over the upper half, c->e below."""
    return vgrad((0, a), (0.5, b), (0.5001, c), (1, e))


def nothing(d, x, y, w, h):
    return []


BUTTON = {
    "normal": ("#707070", "#FFFFFF", 0.7, two_part("#F2F2F2", "#EBEBEB", "#DDDDDD", "#CFCFCF")),
    "focused": ("#3C7FB1", "#FFFFFF", 0.6, two_part("#EAF6FD", "#D9F0FC", "#BEE6FD", "#A7D9F5")),
    "pressed": ("#2C628B", "#9EB0BA", 0.5, two_part("#E5F4FC", "#C4E5F6", "#98D1EF", "#68B3DB")),
    "toggled": ("#2C628B", "#9EB0BA", 0.5, two_part("#E5F4FC", "#C4E5F6", "#98D1EF", "#68B3DB")),
}


def triangle(direction: str, x, y, w, h, size: float = 7) -> list:
    cx, cy = x + w / 2, y + h / 2
    s = size / 2
    t = size / 3.5
    if direction == "down":
        pts = [(cx - s, cy - t / 1.2), (cx + s, cy - t / 1.2), (cx, cy + t * 1.2)]
    elif direction == "up":
        pts = [(cx - s, cy + t / 1.2), (cx + s, cy + t / 1.2), (cx, cy - t * 1.2)]
    elif direction == "right":
        pts = [(cx - t / 1.2, cy - s), (cx - t / 1.2, cy + s), (cx + t * 1.2, cy)]
    else:
        pts = [(cx + t / 1.2, cy - s), (cx + t / 1.2, cy + s), (cx - t * 1.2, cy)]
    return [pts]


def check_mark(x, y) -> list:
    """A check mark in a 13x13 box at (x, y)."""
    pts = [(x + 3, y + 6.2), (x + 5.2, y + 8.4), (x + 10, y + 3.3), (x + 11.2, y + 4.6), (x + 5.2, y + 10.8),
           (x + 1.8, y + 7.4)]
    return [pts]


def circle(cx, cy, r, seg=24):
    return [(cx + r * math.cos(2 * math.pi * i / seg), cy + r * math.sin(2 * math.pi * i / seg)) for i in range(seg)]


# ---- the sheet -----------------------------------------------------------------------------------------
def build_svg() -> str:
    s = KSheet()

    # push buttons (also combo boxes and spin buttons)
    for state, (ol, inn, inn_a, fill) in BUTTON.items():
        s.frame("button", state, 26, 24, 3, boxed(ol, inn, inn_a, fill))
    s.element("button-default-indicator", 6, 6, nothing)

    # tool buttons: flat until the mouse is on them
    s.frame("tbutton", "normal", 24, 24, 3, nothing)
    s.frame("tbutton", "focused", 24, 24, 3, boxed("#7DA2CE", "#FFFFFF", 0.8,
                                                   two_part("#F7FBFF", "#E8F2FD", "#D9E9FC", "#E7F0FD")))
    s.frame("tbutton", "pressed", 24, 24, 3, boxed("#6F92BE", "#9DB8DA", 0.6, vgrad((0, "#C5DAF4"), (1, "#B5CEEF"))))
    s.frame("tbutton", "toggled", 24, 24, 3, boxed("#7DA2CE", "#FFFFFF", 0.5, vgrad((0, "#DCEBFC"), (1, "#C1DBFC"))))

    # spin box buttons
    s.frame("spin", "normal", 18, 12, 2, boxed("#BDC7D1", "#FFFFFF", 0.6, vgrad((0, "#F6F6F6"), (1, "#E5E5E5")), r=2))
    s.frame("spin", "focused", 18, 12, 2, boxed("#3C7FB1", "#FFFFFF", 0.5, vgrad((0, "#E5F4FC"), (1, "#B7E0F8")), r=2))
    s.frame("spin", "pressed", 18, 12, 2, boxed("#2C628B", None, 0, vgrad((0, "#C4E5F6"), (1, "#7EC2E8")), r=2))

    # text fields: darker top edge, lighter sides and bottom
    def field(top, sides, bottom):
        def draw(d, x, y, w, h):
            outer = rrect(x, y, w, h, 1, 1, 1, 1)
            i1 = rrect(x + 1, y + 1, w - 2, h - 2)
            return [Layer([i1], "#FFFFFF"),
                    Layer(ring(outer, i1), sides),
                    Layer([rrect(x + 1, y, w - 2, 1)], top),
                    Layer([rrect(x + 1, y + h - 1, w - 2, 1)], bottom)]
        return draw
    s.frame("lineedit", "normal", 22, 20, 2, field("#ABADB3", "#E2E3EA", "#E3E9EF"))
    s.frame("lineedit", "focused", 22, 20, 2, field("#3D7BAD", "#A4C9E3", "#B7D9ED"))

    # check boxes and radio buttons (13 x 13)
    def checkbox(hover: bool, mark: str):
        def draw(d, x, y, w, h):
            layers = [Layer([rrect(x, y, 13, 13)], "#3C7FB1" if hover else "#8E8F8F"),
                      Layer([rrect(x + 1, y + 1, 11, 11)], "#FFFFFF"),
                      Layer([rrect(x + 2, y + 2, 9, 9)],
                            d.linear(x + 2, y + 2, x + 11, y + 11,
                                     [(0, "#B4E2FC" if hover else "#D3D3D3", 1),
                                      (1, "#EAF7FE" if hover else "#F8F8F8", 1)])),
                      Layer(ring(rrect(x + 2, y + 2, 9, 9), rrect(x + 3, y + 3, 7, 7)),
                            "#79C6F9" if hover else "#B9B9B9", 0.8)]
            if mark == "checked":
                layers.append(Layer(check_mark(x + 0.3, y + 0.6), "#FFFFFF", 0.8, "nonzero"))
                layers.append(Layer(check_mark(x, y), "#4C607A", 1.0, "nonzero"))
            elif mark == "tristate":
                layers.append(Layer([rrect(x + 3.5, y + 3.5, 6, 6, 0.5, 0.5, 0.5, 0.5)],
                                    d.linear(0, y + 3.5, 0, y + 9.5, [(0, "#7CC4F7", 1), (1, "#2E7FD0", 1)])))
            return layers
        return draw
    for mark in ("", "checked", "tristate"):
        for hover in (False, True):
            name = "checkbox" + (f"-{mark}" if mark else "") + ("-focused" if hover else "-normal")
            s.element(name, 13, 13, checkbox(hover, mark))

    def radio(hover: bool, checked: bool):
        def draw(d, x, y, w, h):
            cx, cy = x + 6.5, y + 6.5
            layers = [Layer([circle(cx, cy, 6.5)], "#3C7FB1" if hover else "#8E8F8F"),
                      Layer([circle(cx, cy, 5.5)], "#FFFFFF"),
                      Layer([circle(cx, cy, 4.5)], d.linear(x + 2, y + 2, x + 11, y + 11,
                                                            [(0, "#B4E2FC" if hover else "#D3D3D3", 1),
                                                             (1, "#EAF7FE" if hover else "#F8F8F8", 1)]))]
            if checked:
                layers.append(Layer([circle(cx, cy, 3.3)], d.radial(cx - 0.8, cy - 1, 3.6, 3.6,
                                                                    [(0, "#C3F0FF", 1), (0.45, "#3CA3EE", 1),
                                                                     (1, "#145BA6", 1)])))
            return layers
        return draw
    for checked in (False, True):
        for hover in (False, True):
            name = "radio" + ("-checked" if checked else "") + ("-focused" if hover else "-normal")
            s.element(name, 13, 13, radio(hover, checked))

    # tabs (drawn on top; the selected one opens into the white page below)
    tab = {
        "normal": ("#898C95", two_part("#F2F2F2", "#EBEBEB", "#DDDDDD", "#CFCFCF"), "trbl"),
        "focused": ("#3C7FB1", two_part("#EAF6FD", "#D9F0FC", "#BEE6FD", "#A7D9F5"), "trbl"),
        "toggled": ("#898C95", "#FFFFFF", "trl"),
    }
    for state, (ol, fill, sides) in tab.items():
        s.frame("tab", state, 30, 22, 3, boxed(ol, "#FFFFFF", 0.6 if state != "toggled" else 0, fill, r=2, sides=sides))
    s.frame("tabframe", "normal", 24, 24, 3, boxed("#898C95", None, 0, "#FFFFFF", r=0))

    # tab close buttons
    def tab_close(state):
        def draw(d, x, y, w, h):
            layers = []
            if state in ("focused", "pressed"):
                layers.append(Layer([rrect(x, y, w, h, 2, 2, 2, 2)], "#C75050" if state == "focused" else "#99302A"))
            g = A.glyph_layers("close", x, y, w, h, 1.0)
            color = "#FFFFFF" if state in ("focused", "pressed") else "#5E5E5E"
            return layers + [Layer(lay.polys, color, 1.0 if lay.fill == "#FFFFFF" else 0, lay.rule) for lay in g]
        return draw
    for state in ("normal", "focused", "pressed", "disabled", "toggled"):
        s.element(f"tab-close-{state}", 16, 16, tab_close("normal" if state in ("disabled", "toggled") else state))

    # column headers (white, a separator on the right)
    def header(state):
        def draw(d, x, y, w, h):
            if state == "normal":
                return [Layer([rrect(x, y, w, h)], d.linear(0, y, 0, y + h, [(0, "#FFFFFF", 1), (1, "#F4F6F9", 1)])),
                        Layer([rrect(x + w - 1, y + 2, 1, h - 4)], "#DEDFE0"),
                        Layer([rrect(x, y + h - 1, w, 1)], "#D5D5D5")]
            top, bot, ol = (("#E3F7FF", "#BDEDFF", "#69BBE3") if state == "focused" else
                            ("#BCE4F9", "#8DD6F7", "#65A6D0"))
            return [Layer([rrect(x, y, w, h)], d.linear(0, y, 0, y + h, [(0, top, 1), (1, bot, 1)])),
                    Layer(ring(rrect(x, y, w, h), rrect(x + 1, y + 1, w - 2, h - 2)), ol)]
        return draw
    for state in ("normal", "focused", "pressed", "toggled"):
        s.frame("header", state, 30, 22, 2, header("normal" if state == "toggled" else state))

    # progress bars: grey groove, green bar with the glossy split
    s.frame("progress", "normal", 30, 15, 2, boxed("#BCBCBC", "#FFFFFF", 0.5,
                                                   vgrad((0, "#F3F3F3"), (0.5, "#E9E9E9"), (1, "#DADADA")), r=2))
    green = two_part("#D9FBD7", "#9AEA95", "#06B025", "#4ED553")
    s.frame("progress-pattern", "normal", 30, 15, 2, boxed("#1E8F2A", "#FFFFFF", 0.35, green, r=1.5, outline_a=0.5))
    s.frame("progress-pattern", "disabled", 30, 15, 2, boxed("#9A9A9A", None, 0, vgrad((0, "#DADADA"), (1, "#BDBDBD")),
                                                             r=1.5, outline_a=0.6))

    # slider: a thin groove and a button-like handle (drawn for a horizontal slider)
    groove = boxed("#A3A3A3", "#FFFFFF", 0.0, "#E7EAEA", r=1)
    for state in ("normal", "toggled"):
        s.frame("slider", state, 20, 8, 2, groove)
    for state, (ol, inn, inn_a, _f) in {"normal": BUTTON["normal"], "focused": BUTTON["focused"],
                                        "pressed": BUTTON["pressed"], "disabled": BUTTON["normal"]}.items():
        colours = {"normal": ("#F7F7F7", "#D4D4D4"), "focused": ("#EAF6FD", "#A7D9F5"),
                   "pressed": ("#C4E5F6", "#68B3DB"), "disabled": ("#F4F4F4", "#E4E4E4")}[state]
        s.element(f"slidercursor-{state}", 11, 21,
                  boxed("#B5B5B5" if state == "disabled" else ol, inn, inn_a,
                        hgrad((0, colours[0]), (1, colours[1])), r=2))

    # scroll bars (drawn vertical): light groove, rounded thumb with grip, flat arrow buttons
    s.frame("sgroove", "normal", 17, 40, 1, lambda d, x, y, w, h: [
        Layer([rrect(x, y, w, h)], d.linear(x, 0, x + w, 0, [(0, "#E6E6E6", 1), (0.4, "#F2F2F2", 1), (1, "#FAFAFA", 1)])),
        Layer([rrect(x, y, 1, h)], "#E0E0E0")])
    thumb = {"normal": ("#959595", ("#F3F3F3", "#E8E8E8", "#D8D8D8")),
             "focused": ("#3C7FB1", ("#E3F4FC", "#C4E5F6", "#A9DBF6")),
             "pressed": ("#2C628B", ("#C2E4F6", "#9FD3F0", "#7EC1E6"))}
    for state, (ol, (a, b, c)) in thumb.items():
        s.frame("scrollbarslider", state, 15, 40, 3, boxed(ol, "#FFFFFF", 0.75, hgrad((0, a), (0.5, b), (1, c)), r=2))

    def grip(colour):
        def draw(d, x, y, w, h):
            layers = []
            for i in range(3):
                layers.append(Layer([rrect(x + 1, y + 1 + i * 2.5, w - 2, 1)], colour))
                layers.append(Layer([rrect(x + 1, y + 2 + i * 2.5, w - 2, 1)], "#FFFFFF", 0.9))
            return layers
        return draw
    for state, colour in (("normal", "#8A8A8A"), ("focused", "#3C7FB1"), ("pressed", "#1F5786")):
        s.element(f"grip-{state}", 8, 8, grip(colour))
    s.frame("sbutton", "normal", 17, 17, 2, nothing)
    s.frame("sbutton", "focused", 17, 17, 2, boxed("#3C7FB1", "#FFFFFF", 0.6,
                                                   two_part("#EAF6FD", "#D9F0FC", "#BEE6FD", "#A7D9F5"), r=2))
    s.frame("sbutton", "pressed", 17, 17, 2, boxed("#2C628B", None, 0,
                                                   two_part("#E5F4FC", "#C4E5F6", "#98D1EF", "#68B3DB"), r=2))

    # arrows (scroll bars, combo boxes, spin boxes, menus)
    for prefix in ("arrow", "flat-arrow"):
        for direction in ("up", "down", "left", "right"):
            for state, colour in (("normal", "#3B3B3B"), ("focused", "#1F5786"), ("pressed", "#0E2F4F"),
                                  ("toggled", "#3B3B3B"), ("disabled", "#B5B5B5")):
                s.element(f"{prefix}-{direction}-{state}", 9, 9,
                          lambda d, x, y, w, h, di=direction, c=colour: [Layer(triangle(di, x, y, w, h, 7), c)])

    # tree expanders: an open triangle, a filled one when expanded
    def expander(open_: bool, hover: bool):
        def draw(d, x, y, w, h):
            if open_:
                pts = [(x + 7.5, y + 3), (x + 7.5, y + 8), (x + 2.5, y + 8)]
                return [Layer([pts], "#1C4F8A" if hover else "#595959")]
            outer = [(x + 3, y + 1.5), (x + 3, y + 9.5), (x + 7.5, y + 5.5)]
            inner = [(x + 4, y + 3.8), (x + 4, y + 7.2), (x + 6, y + 5.5)]
            return [Layer([outer, inner], "#1CC4F7" if hover else "#A6A6A6")]
        return draw
    for open_, name in ((False, "plus"), (True, "minus")):
        for state in ("normal", "focused", "pressed", "disabled"):
            s.element(f"tree-{name}-{state}", 11, 11, expander(open_, state in ("focused", "pressed")))

    # menus
    s.frame("menu", "normal", 24, 24, 3, boxed("#979797", "#F5F5F5", 1.0, "#F0F0F0", r=0))
    s.frame("menuitem", "normal", 24, 22, 3, nothing)
    for state in ("focused", "pressed", "toggled"):
        s.frame("menuitem", state, 24, 22, 3, boxed("#AECFF7", "#FFFFFF", 0.55,
                                                    vgrad((0, "#F2F8FE"), (1, "#DDEAFA")), r=3))
    s.element("menuitem-separator", 30, 7, lambda d, x, y, w, h: [Layer([rrect(x, y + 3, w, 1)], "#E0E0E0"),
                                                                 Layer([rrect(x, y + 4, w, 1)], "#FFFFFF")])
    s.frame("menubar", "normal", 24, 22, 1, lambda d, x, y, w, h: [
        Layer([rrect(x, y, w, h)], d.linear(0, y, 0, y + h, [(0, "#FBFCFE", 1), (1, "#E9EFF6", 1)])),
        Layer([rrect(x, y + h - 1, w, 1)], "#B6BCCC", 0.6)])
    s.frame("menubaritem", "focused", 24, 20, 3, boxed("#B8D6FB", "#FFFFFF", 0.6, vgrad((0, "#F8FBFF"), (1, "#E3EEFC")),
                                                       r=3))
    for state in ("pressed", "toggled"):
        s.frame("menubaritem", state, 24, 20, 3, boxed("#7DA2CE", "#FFFFFF", 0.4, vgrad((0, "#E4EFFB"), (1, "#C6DDF7")),
                                                       r=3))

    # tooltips
    s.frame("tooltip", "normal", 24, 24, 3, boxed("#767676", "#FFFFFF", 0.9, vgrad((0, "#FFFFFF"), (1, "#E4E5F0")), r=3))

    # list and tree selections (Explorer's light blue)
    s.frame("itemview", "normal", 30, 20, 3, nothing)
    sel = {"focused": ("#B8D6FB", ("#FAFBFD", "#EBF3FD")),
           "toggled": ("#7DA2CE", ("#DCEBFC", "#C1DBFC")),
           "pressed": ("#7DA2CE", ("#C9DFFB", "#ADCDF5")),
           "toggled-inactive": ("#D9D9D9", ("#F8F8F8", "#E5E5E5"))}
    for state, (ol, (a, b)) in sel.items():
        s.frame("itemview", state, 30, 20, 3, boxed(ol, "#FFFFFF", 0.6, vgrad((0, a), (1, b)), r=3))

    # group boxes, plain frames, the keyboard focus frame
    s.frame("group", "normal", 24, 24, 3, boxed("#D5DFE5", "#FFFFFF", 1.0, None, r=3), interior=False)
    s.frame("common", "normal", 12, 12, 1, boxed("#828790", None, 0, None, r=0), interior=False)
    s.frame("focus", "normal", 12, 12, 1, boxed("#3399FF", None, 0, None, r=2, outline_a=0.45), interior=False)
    return s.svg()


CONFIG = """[%General]
author=Classic7 project
comment=Windows 7 style controls for the Classic 7 Aero and Basic looks
x11drag=none
dialog_button_layout=4
alt_mnemonic=true
left_tabs=true
attach_active_tab=true
embedded_tabs=false
mirror_doc_tabs=true
group_toolbar_buttons=false
spread_progressbar=false
composite=true
menu_shadow_depth=0
tooltip_shadow_depth=0
spread_menuitems=true
scroll_width=17
scroll_arrows=true
scroll_min_extent=24
transient_scrollbar=false
transient_groove=false
slider_width=4
slider_handle_width=11
slider_handle_length=21
center_toolbar_handle=true
check_size=13
textless_progressbar=false
progressbar_thickness=15
menubar_mouse_tracking=true
toolbutton_style=0
click_behavior=0
translucent_windows=false
blurring=false
popup_blurring=false
vertical_spin_indicators=true
fill_rubberband=false
merge_menubar_with_toolbar=false
small_icon_size=16
large_icon_size=32
button_icon_size=16
toolbar_icon_size=22
combo_as_lineedit=false
combo_menu=false
combo_focus_rect=false
inline_spin_indicators=false
remove_extra_frames=false
animate_states=true
no_inactiveness=false
menu_separator_height=7
layout_spacing=6
layout_margin=9
submenu_overlap=0
respect_DE=true

[GeneralColors]
window.color=#F0F0F0
base.color=#FFFFFF
alt.base.color=#F5F8FB
button.color=#F0F0F0
light.color=#FFFFFF
mid.light.color=#E3E3E3
dark.color=#A0A0A0
mid.color=#C8C8C8
highlight.color=#3399FF
inactive.highlight.color=#CCE4F7
text.color=#000000
window.text.color=#000000
button.text.color=#000000
disabled.text.color=#6D6D6D
tooltip.text.color=#575757
highlight.text.color=#FFFFFF
link.color=#0066CC
link.visited.color=#800080
progress.indicator.text.color=#000000

[Hacks]
transparent_ktitle_label=true
transparent_dolphin_view=false
respect_darkness=false
iconless_pushbutton=true
iconless_menu=false
transparent_arrow_button=true
no_selection_tint=true
force_size_grip=false

[PanelButtonCommand]
frame=true
frame.element=button
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
interior=true
interior.element=button
indicator.size=9
indicator.element=arrow
text.normal.color=#000000
text.focus.color=#000000
text.press.color=#000000
text.toggle.color=#000000
text.shadow=0
text.margin=1
text.iconspacing=4
text.margin.top=2
text.margin.bottom=2
text.margin.left=8
text.margin.right=8
frame.expansion=0
min_width=+0.3font

[PanelButtonTool]
inherits=PanelButtonCommand
frame.element=tbutton
interior.element=tbutton
text.margin.left=4
text.margin.right=4
min_width=0

[ToolbarButton]
inherits=PanelButtonTool

[Dock]
inherits=PanelButtonCommand
frame=false
interior=false

[DockTitle]
inherits=PanelButtonCommand
frame=false
interior=false
text.bold=false

[IndicatorSpinBox]
inherits=PanelButtonCommand
frame.element=spin
interior.element=spin
frame.top=2
frame.bottom=2
frame.left=2
frame.right=2
indicator.element=arrow
indicator.size=7

[RadioButton]
inherits=PanelButtonCommand
frame=false
interior.element=radio

[CheckBox]
inherits=PanelButtonCommand
frame=false
interior.element=checkbox

[Focus]
frame=true
frame.element=focus
frame.top=1
frame.bottom=1
frame.left=1
frame.right=1
frame.patternsize=0

[GenericFrame]
inherits=PanelButtonCommand
frame=true
interior=false
frame.element=common
interior.element=common
frame.top=1
frame.bottom=1
frame.left=1
frame.right=1

[LineEdit]
inherits=PanelButtonCommand
frame.element=lineedit
interior.element=lineedit
frame.top=2
frame.bottom=2
frame.left=2
frame.right=2
text.margin.left=2
text.margin.right=2

[ToolbarLineEdit]
inherits=LineEdit

[DropDownButton]
inherits=PanelButtonCommand
indicator.element=arrow-down

[IndicatorArrow]
indicator.element=arrow
indicator.size=9

[ToolboxTab]
inherits=PanelButtonCommand

[Tab]
inherits=PanelButtonCommand
frame.element=tab
interior.element=tab
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
text.margin.left=8
text.margin.right=8
text.margin.top=2
text.margin.bottom=2
indicator.element=tab
indicator.size=12
focusFrame=false
min_width=+0.5font

[TabFrame]
inherits=PanelButtonCommand
frame.element=tabframe
interior.element=tabframe
interior=true
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3

[TabBarFrame]
inherits=GenericFrame
frame=false
interior=false

[TreeExpander]
inherits=PanelButtonCommand
frame=false
interior=false
indicator.size=11
indicator.element=tree

[HeaderSection]
inherits=PanelButtonCommand
frame.element=header
interior.element=header
frame.top=2
frame.bottom=2
frame.left=2
frame.right=2
text.margin.left=6
text.margin.right=6
text.margin.top=2
text.margin.bottom=2

[SizeGrip]
indicator.element=resize-grip

[Toolbar]
inherits=PanelButtonCommand
frame=false
interior=false
indicator.element=toolbar
indicator.size=5
text.margin=0

[Slider]
inherits=PanelButtonCommand
frame.element=slider
interior.element=slider
frame.top=2
frame.bottom=2
frame.left=2
frame.right=2

[SliderCursor]
inherits=PanelButtonCommand
frame=false
interior.element=slidercursor

[Progressbar]
inherits=PanelButtonCommand
frame.element=progress
interior.element=progress
frame.top=2
frame.bottom=2
frame.left=2
frame.right=2
text.margin=0
text.bold=false

[ProgressbarContents]
inherits=PanelButtonCommand
frame=true
frame.element=progress-pattern
interior.element=progress-pattern
frame.top=2
frame.bottom=2
frame.left=2
frame.right=2

[ItemView]
inherits=PanelButtonCommand
frame.element=itemview
interior.element=itemview
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
text.margin.top=0
text.margin.bottom=0
text.margin.left=3
text.margin.right=3
text.normal.color=#000000
text.focus.color=#000000
text.press.color=#000000
text.toggle.color=#000000

[Splitter]
indicator.size=32

[Scrollbar]
inherits=PanelButtonCommand
frame.element=sbutton
interior.element=sbutton
frame.top=2
frame.bottom=2
frame.left=2
frame.right=2
indicator.element=arrow
indicator.size=7

[ScrollbarSlider]
inherits=PanelButtonCommand
frame.element=scrollbarslider
interior.element=scrollbarslider
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
indicator.element=grip
indicator.size=8

[ScrollbarGroove]
inherits=PanelButtonCommand
frame=true
interior=true
frame.element=sgroove
interior.element=sgroove
frame.top=1
frame.bottom=1
frame.left=1
frame.right=1

[MenuItem]
inherits=PanelButtonCommand
frame=true
frame.element=menuitem
interior.element=menuitem
indicator.element=arrow
text.normal.color=#000000
text.focus.color=#000000
text.press.color=#000000
text.toggle.color=#000000
text.margin.top=2
text.margin.bottom=2
text.margin.left=4
text.margin.right=4
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3

[MenuBar]
inherits=PanelButtonCommand
frame=true
frame.element=menubar
interior.element=menubar
frame.top=1
frame.bottom=1
frame.left=1
frame.right=1
text.normal.color=#000000

[MenuBarItem]
inherits=PanelButtonCommand
interior=true
frame.element=menubaritem
interior.element=menubaritem
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
text.margin.left=4
text.margin.right=4
text.margin.top=1
text.margin.bottom=1
text.normal.color=#000000
text.focus.color=#000000
text.press.color=#000000
text.toggle.color=#000000

[TitleBar]
inherits=PanelButtonCommand
frame=false
interior=false

[ComboBox]
inherits=PanelButtonCommand
indicator.element=arrow

[Menu]
inherits=PanelButtonCommand
frame.element=menu
interior.element=menu
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
text.normal.color=#000000

[GroupBox]
inherits=GenericFrame
frame=true
interior=false
frame.element=group
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
text.normal.color=#000000
text.bold=false

[ToolTip]
inherits=GenericFrame
frame.element=tooltip
interior.element=tooltip
interior=true
frame.top=3
frame.bottom=3
frame.left=3
frame.right=3
text.margin=1
text.normal.color=#575757

[StatusBar]
inherits=GenericFrame
frame=false
interior=false

[Window]
interior=false

[Dialog]
interior=false
"""


def write(outdir: Path) -> list[Path]:
    folder = Path(outdir) / THEME
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{THEME}.kvconfig").write_text(CONFIG)
    (folder / f"{THEME}.svg").write_text(build_svg())
    return [folder / f"{THEME}.kvconfig", folder / f"{THEME}.svg"]


if __name__ == "__main__":
    for p in write(Path(sys.argv[1] if len(sys.argv) > 1 else ".")):
        print("wrote", p)
