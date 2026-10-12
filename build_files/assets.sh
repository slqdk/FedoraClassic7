#!/bin/bash
# Builder stage: fetch Chicago95 (GPL-3.0+/MIT) at a pinned commit and turn it into
#   - the Classic7 GTK theme  (Chicago95 recoloured from Win95 grey to Windows Standard)
#   - the Chicago95 standard cursors
# Output lands in /out, which the final image copies to /.
set -ouex pipefail

CHICAGO95_REF="${CHICAGO95_REF:?pin a Chicago95 commit}"
SRC="${SRC:-/tmp/chicago95}"
OUT="${OUT:-/out}"

git init -q "$SRC"
git -C "$SRC" fetch -q --depth 1 https://github.com/grassmunk/Chicago95.git "$CHICAGO95_REF"
git -C "$SRC" checkout -q FETCH_HEAD

# --- GTK theme -------------------------------------------------------------------
THEME="$OUT/usr/share/themes/Classic7"
mkdir -p "$OUT/usr/share/themes"
cp -a "$SRC/Theme/Chicago95" "$THEME"
# Drop the bits that only matter on XFCE/Cinnamon/GNOME Shell
rm -rf "$THEME"/{xfwm4,xfwm4_hidpi,xfce-notify-4.0,cinnamon,gnome-shell,metacity-1,openbox-3}

sed -i -e 's/^Name=.*/Name=Classic7/' -e 's/^GtkTheme=.*/GtkTheme=Classic7/' \
    -e 's/^MetacityTheme=.*/MetacityTheme=Classic7/' \
    -e 's/^IconTheme=.*/IconTheme=breeze/' -e 's/^CursorTheme=.*/CursorTheme=Chicago95_Standard_Cursors/' -e 's/^CursorSize=.*/CursorSize=24/' \
    -e 's/^Comment=.*/Comment=Windows Standard palette, based on Chicago95/' "$THEME/index.theme"

# Windows 95 grey -> Windows Standard ("Win2000 / Win7 Classic") palette
find "$THEME" -type f -name '*.css' -print0 | xargs -0 sed -i -E \
    -e 's/#c0c0c0/#d4d0c8/Ig' \
    -e 's/#dfdfdf/#d4d0c8/Ig' \
    -e 's/(@define-color selected_bg_color )#000080/\1#0a246a/I' \
    -e 's/(@define-color border_dark )#000000/\1#404040/I'
find "$THEME" -type f -name 'gtkrc' -print0 | xargs -0 -r sed -i -E \
    -e 's/#c0c0c0/#d4d0c8/Ig' -e 's/#dfdfdf/#d4d0c8/Ig'

# Same swap in the bitmap assets (exact colour match only)
find "$THEME" -type f -name '*.png' -print0 | xargs -0 -r -n 200 \
    magick mogrify -fill '#d4d0c8' -opaque '#c0c0c0' -fill '#d4d0c8' -opaque '#dfdfdf'
find "$THEME" -type f -name '*.svg' -print0 | xargs -0 -r sed -i -E \
    -e 's/#c0c0c0/#d4d0c8/Ig' -e 's/#dfdfdf/#d4d0c8/Ig'

# (Icons: Classic 7 uses Breeze; the Chicago95 icon set is not installed)
mkdir -p "$OUT/usr/share/icons"

# --- Cursors -----------------------------------------------------------------------
cp -a "$SRC/Cursors/Chicago95_Standard_Cursors" "$OUT/usr/share/icons/Chicago95_Standard_Cursors"
rm -rf "$OUT/usr/share/icons/Chicago95_Standard_Cursors/build"

# --- Licence + provenance ----------------------------------------------------------
mkdir -p "$OUT/usr/share/licenses/classic7"
cp "$SRC/LICENSE" "$OUT/usr/share/licenses/classic7/Chicago95-LICENSE" 2>/dev/null || true
cp "$SRC/CREDITS" "$OUT/usr/share/licenses/classic7/Chicago95-CREDITS" 2>/dev/null || true
echo "Chicago95 ${CHICAGO95_REF}" > "$OUT/usr/share/licenses/classic7/SOURCES"

# ImageMagick writes the recoloured files through a temp file (mode 0600); everything here
# must be readable by every user (GTK apps load these images as the logged-in user).
chmod -R u+rwX,go+rX,go-w "$OUT"
