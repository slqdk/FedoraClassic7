"""Show: the built-in designs (themes), colour sets, font sets and background styles."""
from __future__ import annotations

import copy

from show_model import (DARK_COLOR_MAP, DEFAULT_COLOR_MAP, Master, Shape, Theme, scheme)


def _colors(dk2, lt2, a1, a2, a3, a4, a5, a6, hl="0000FF", fhl="800080", dk1="000000", lt1="FFFFFF") -> dict:
    return {"dk1": dk1, "lt1": lt1, "dk2": dk2, "lt2": lt2, "accent1": a1, "accent2": a2, "accent3": a3,
            "accent4": a4, "accent5": a5, "accent6": a6, "hlink": hl, "folHlink": fhl}


COLOR_SETS = {
    "Office": _colors("1F497D", "EEECE1", "4F81BD", "C0504D", "9BBB59", "8064A2", "4BACC6", "F79646"),
    "Grayscale": _colors("000000", "F8F8F8", "DDDDDD", "B2B2B2", "969696", "808080", "5F5F5F", "4D4D4D",
                         "5F5F5F", "919191"),
    "Horizon": _colors("17375E", "E8EEF4", "2E75B6", "C55A11", "70AD47", "7030A0", "00B0F0", "FFC000"),
    "Slate": _colors("44546A", "E7E6E6", "5B9BD5", "ED7D31", "A5A5A5", "FFC000", "4472C4", "70AD47",
                     "9DC3E6", "B4A7D6", dk1="1E232B", lt1="FFFFFF"),
    "Ember": _colors("5A2C17", "F2E8DE", "C0504D", "E36C09", "938953", "7F6084", "4F81BD", "D99694"),
    "Meadow": _colors("2F4F2F", "EBF1DE", "77933C", "4F81BD", "E2A300", "9C5B9A", "31859C", "C0504D"),
    "Ocean": _colors("1F4E79", "DEEAF6", "4BACC6", "F79646", "9BBB59", "FFD966", "8EA9DB", "C9C9C9",
                     "9DC3E6", "D9D2E9", dk1="0B2440", lt1="FFFFFF"),
    "Paper": _colors("4A3C31", "F4EEDC", "8C6D46", "6F8F72", "A35A4E", "5B6E8C", "C49A3B", "7C6A8E"),
    "Midnight": _colors("262626", "D9D9D9", "00B0F0", "FF3399", "92D050", "FFC000", "B266FF", "FF6600",
                        "66CCFF", "CC99FF", dk1="000000", lt1="FFFFFF"),
    "Sunrise": _colors("7F3F00", "FDE9D9", "E46C0A", "C0504D", "F2C314", "8B5A9C", "4BACC6", "76923C"),
}

FONT_SETS = {
    "Office": ("Calibri", "Calibri"),
    "Office Classic": ("Arial", "Arial"),
    "Office Classic 2": ("Arial", "Times New Roman"),
    "Cambria & Calibri": ("Cambria", "Calibri"),
    "Georgia": ("Georgia", "Georgia"),
    "Verdana": ("Verdana", "Verdana"),
    "Tahoma": ("Tahoma", "Tahoma"),
    "Trebuchet": ("Trebuchet MS", "Trebuchet MS"),
    "Century Gothic": ("Century Gothic", "Century Gothic"),
    "Franklin Gothic": ("Franklin Gothic Medium", "Franklin Gothic Book"),
    "Times & Arial": ("Times New Roman", "Arial"),
}


def _solid(c):
    return {"type": "solid", "color": c}


def _grad(stops, angle=90.0, path=None):
    return {"type": "grad", "stops": [[p, c] for p, c in stops], "angle": angle, "path": path}


def _rect(x, y, cx, cy, fill, name="Decoration", geom="rect", line=None):
    return Shape(kind="sp", name=name, x=int(x), y=int(y), cx=int(cx), cy=int(cy), geom=geom, fill=fill, line=line)


# design key -> (name, colour set, font set, dark?, background, decorations(w, h), title-slide decorations)
def _deco_none(w, h):
    return []


def _deco_horizon(w, h):
    return [_rect(0, h * 0.94, w, h * 0.06, _grad([(0, scheme("accent1")), (100000, scheme("accent1", ("lumMod", 75000)))], 0)),
            _rect(0, h * 0.932, w, h * 0.006, _solid(scheme("accent2")))]


def _deco_horizon_title(w, h):
    return [_rect(0, h * 0.535, w, h * 0.01, _solid(scheme("accent1"))),
            _rect(0, h * 0.549, w * 0.55, h * 0.005, _solid(scheme("accent2")))]


def _deco_slate(w, h):
    return [_rect(0, h * 0.205, w, h * 0.004, _solid(scheme("accent1")))]


def _deco_ember(w, h):
    return [_rect(0, 0, w * 0.028, h, _grad([(0, scheme("accent2")), (100000, scheme("accent1"))], 90)),
            _rect(w * 0.034, 0, w * 0.004, h, _solid(scheme("accent1", ("alpha", 60000))))]


def _deco_meadow(w, h):
    return [_rect(0, 0, w, h * 0.04, _grad([(0, scheme("accent1")), (100000, scheme("accent3"))], 0)),
            _rect(0, h * 0.045, w, h * 0.004, _solid(scheme("accent1", ("lumMod", 60000), ("lumOff", 40000))))]


def _deco_ocean(w, h):
    return [_rect(-w * 0.1, h * 0.86, w * 1.2, h * 0.3, _solid(scheme("accent1", ("alpha", 25000))), geom="ellipse"),
            _rect(-w * 0.2, h * 0.9, w * 1.0, h * 0.3, _solid(scheme("accent1", ("alpha", 20000))), geom="ellipse")]


def _deco_paper(w, h):
    line = {"color": scheme("accent1"), "width": 19050, "dash": "solid"}
    thin = {"color": scheme("accent1"), "width": 6350, "dash": "solid"}
    m = w * 0.02
    return [_rect(m, m, w - 2 * m, h - 2 * m, None, line=line),
            _rect(m * 1.6, m * 1.6, w - 3.2 * m, h - 3.2 * m, None, line=thin)]


def _deco_midnight(w, h):
    corner = _rect(w * 0.88, h * 0.86, w * 0.12, h * 0.14, _solid(scheme("accent1", ("alpha", 80000))),
                   geom="rtTriangle")
    corner.flip_h = True
    return [_rect(0, h * 0.2, w, h * 0.006, _grad([(0, scheme("accent1")), (100000, scheme("accent2"))], 0)),
            corner]


def _deco_sunrise(w, h):
    return [_rect(w * 0.7, -h * 0.2, w * 0.5, w * 0.5, _solid(scheme("accent1", ("alpha", 18000))), geom="ellipse")]


DESIGNS = {
    "office": dict(name="Office Theme", colors="Office", fonts="Office", dark=False,
                   bg=_solid(scheme("bg1")), deco=_deco_none, title_deco=_deco_none),
    "horizon": dict(name="Horizon", colors="Horizon", fonts="Cambria & Calibri", dark=False,
                    bg=_solid(scheme("bg1")), deco=_deco_horizon, title_deco=_deco_horizon_title,
                    title_color=scheme("tx2")),
    "slate": dict(name="Slate", colors="Slate", fonts="Verdana", dark=True,
                  bg=_grad([(0, scheme("bg2")), (100000, scheme("bg1"))], 90), deco=_deco_slate,
                  title_deco=_deco_none),
    "ember": dict(name="Ember", colors="Ember", fonts="Georgia", dark=False,
                  bg=_solid(scheme("bg2", ("lumMod", 100000), ("lumOff", 0))), deco=_deco_ember,
                  title_deco=_deco_none, title_color=scheme("tx2")),
    "meadow": dict(name="Meadow", colors="Meadow", fonts="Office", dark=False,
                   bg=_solid(scheme("bg1")), deco=_deco_meadow, title_deco=_deco_none,
                   title_color=scheme("accent1", ("lumMod", 75000))),
    "ocean": dict(name="Ocean", colors="Ocean", fonts="Tahoma", dark=True,
                  bg=_grad([(0, scheme("bg2")), (100000, scheme("bg1"))], 90, "circle"), deco=_deco_ocean,
                  title_deco=_deco_none),
    "paper": dict(name="Paper", colors="Paper", fonts="Times & Arial", dark=False,
                  bg=_solid(scheme("bg2", ("lumMod", 100000))), deco=_deco_paper, title_deco=_deco_none,
                  title_color=scheme("tx2")),
    "midnight": dict(name="Midnight", colors="Midnight", fonts="Century Gothic", dark=True,
                     bg=_solid(scheme("bg1")), deco=_deco_midnight, title_deco=_deco_none),
    "sunrise": dict(name="Sunrise", colors="Sunrise", fonts="Trebuchet", dark=False,
                    bg=_grad([(0, scheme("bg1")), (100000, scheme("bg2"))], 90), deco=_deco_sunrise,
                    title_deco=_deco_none, title_color=scheme("accent1", ("lumMod", 75000))),
}


def theme_for(key: str) -> Theme:
    d = DESIGNS.get(key, DESIGNS["office"])
    major, minor = FONT_SETS[d["fonts"]]
    return Theme(name=d["name"], colors_name=d["colors"], fonts_name=d["fonts"],
                 colors=dict(COLOR_SETS[d["colors"]]), major_font=major, minor_font=minor)


def apply_design(m: Master, key: str, w: int, h: int):
    """Give a master (and its layouts) a built-in design. Placeholders and text styles stay."""
    d = DESIGNS.get(key, DESIGNS["office"])
    m.design = key
    m.theme = theme_for(key)
    m.color_map = dict(DARK_COLOR_MAP if d["dark"] else DEFAULT_COLOR_MAP)
    m.background = copy.deepcopy(d["bg"])
    m.shapes = d["deco"](w, h)
    title_color = d.get("title_color")
    for lvl in m.title_style:
        lvl["color"] = copy.deepcopy(title_color) if title_color else scheme("tx1")
    for lay in m.layouts:
        lay.background = None
        lay.raw_xml = None
        lay.shapes = d["title_deco"](w, h) if lay.type == "title" else []


def set_colors(m: Master, name: str):
    m.theme.colors = dict(COLOR_SETS[name])
    m.theme.colors_name = name
    m.theme.raw_xml = None


def set_fonts(m: Master, name: str):
    m.theme.major_font, m.theme.minor_font = FONT_SETS[name]
    m.theme.fonts_name = name
    m.theme.raw_xml = None


def background_styles() -> list[tuple[str, dict]]:
    """Design > Background Styles: four colours, solid / soft gradient / strong gradient."""
    out = []
    for key in ("bg1", "bg2", "tx2", "tx1"):
        out.append((f"Solid {key}", _solid(scheme(key))))
    for key in ("bg1", "bg2", "tx2", "tx1"):
        out.append((f"Soft {key}", _grad([(0, scheme(key, ("tint", 60000))), (100000, scheme(key))], 90)))
    for key in ("bg1", "bg2", "tx2", "tx1"):
        out.append((f"Strong {key}", _grad([(0, scheme(key, ("tint", 40000))), (50000, scheme(key)),
                                            (100000, scheme(key, ("shade", 70000)))], 90, "circle")))
    return out
