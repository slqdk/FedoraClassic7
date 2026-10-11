#!/usr/bin/env python3
"""
Regenerate the system-wide Classic 7 theme files from the default palette.

All drawing code lives in system_files/usr/lib/classic7/classic7theme.py, which the
Appearance app also uses at runtime. Change colours there (SCHEMES[0] is the default),
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

import classic7theme as t  # noqa: E402


def main():
    p = t.STANDARD
    share = SYSTEM / "usr/share"
    for path in t.render(p, share):
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
