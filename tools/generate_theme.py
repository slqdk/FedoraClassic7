#!/usr/bin/env python3
"""
Regenerate the system-wide Classic 7 theme files: the Classic look from the default palette,
and the Aero and Basic looks with the default glass colour.

The drawing code lives in system_files/usr/lib/classic7/classic7theme.py (Classic),
classic7aero.py (Aero, Basic) and classic7kvantum.py (Qt controls for Aero and Basic); the
Appearance app also uses them at runtime. Change colours there (SCHEMES[0] is the default),
then run from the repo root:

    python3 tools/generate_theme.py

Writes into system_files/usr/share/ and docs/. PNG previews need cairosvg
(pip install cairosvg); everything else is plain Python.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SYSTEM = REPO / "system_files"
sys.path.insert(0, str(SYSTEM / "usr/lib/classic7"))

import classic7aero as aero  # noqa: E402
import classic7kvantum as kvantum  # noqa: E402
import classic7theme as t  # noqa: E402


def main():
    p = t.STANDARD
    share = SYSTEM / "usr/share"
    for path in t.render(p, share):
        print("wrote", path.relative_to(REPO))
    # the Aero and Basic looks (window borders, Plasma style, orb, colours) and their Qt controls
    for look in ("aero", "basic"):
        for path in aero.render(look, aero.DEFAULT_GLASS, share):
            print("wrote", path.relative_to(REPO))
    for path in kvantum.write(share / "Kvantum"):
        print("wrote", path.relative_to(REPO))

    docs = REPO / "docs"
    docs.mkdir(exist_ok=True)
    desktop = t.desktop_preview_svg(p)
    (docs / "preview.svg").write_text(desktop)

    try:
        import cairosvg
    except ImportError:
        print("cairosvg not installed - skipping PNG previews", file=sys.stderr)
        return
    lnf = share / "plasma/look-and-feel/org.classic7.desktop/contents/previews"
    lnf.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(bytestring=desktop.encode(), write_to=str(lnf / "fullscreenpreview.png"))
    cairosvg.svg2png(bytestring=desktop.encode(), write_to=str(lnf / "preview.png"),
                     output_width=320, output_height=200)
    cairosvg.svg2png(bytestring=desktop.encode(), write_to=str(docs / "preview.png"))
    print("wrote previews")


if __name__ == "__main__":
    main()
