#!/usr/bin/python3
"""Classic 7's startup programs: what the image changes in the XDG autostart folder (build.sh runs it).

 * off by default, still listed (unticked) in System Configuration > Startup and turned on there:
   Hidden=true with X-Classic7-Disabled=true;
 * not for Plasma at all: KDE added to NotShowIn (systemd's autostart generator then skips them).

A file that isn't there is left out with a note, so a change in Bazzite doesn't stop the build.

    trim_startup.py [AUTOSTART_DIR]
"""
from __future__ import annotations

import sys
from pathlib import Path

# Bazzite's news pop-ups (Classic 7 Update shows what's new) and KDE Connect (phone pairing; it
# listens on the network, and its app starts it when opened)
OFF_BY_DEFAULT = ("bazzite-announcement.desktop", "org.kde.kdeconnect.daemon.desktop")
# the XApp status icon watcher is for Cinnamon, MATE and Xfce; Plasma has its own
NOT_IN_PLASMA = ("xapp-sn-watcher.desktop",)


def edit(path: Path, drop: set[str], add: list[str]) -> None:
    out, group = [], None
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("["):
            group = s
            out.append(line)
            if s == "[Desktop Entry]":
                out.extend(add)
            continue
        if group == "[Desktop Entry]" and "=" in s and not s.startswith("#") and s.split("=", 1)[0].strip() in drop:
            continue
        out.append(line)
    path.write_text("\n".join(out) + "\n")


def value(path: Path, key: str) -> str:
    group = None
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if s.startswith("["):
            group = s
        elif group == "[Desktop Entry]" and s.startswith(key + "="):
            return s.split("=", 1)[1].strip()
    return ""


def main(argv: list[str]) -> int:
    folder = Path(argv[0] if argv else "/etc/xdg/autostart")
    for name in OFF_BY_DEFAULT:
        f = folder / name
        if not f.is_file():
            print(f"trim_startup: {name} isn't there")
            continue
        edit(f, {"Hidden", "X-Classic7-Disabled"}, ["Hidden=true", "X-Classic7-Disabled=true"])
        print(f"trim_startup: {name} is off by default")
    for name in NOT_IN_PLASMA:
        f = folder / name
        if not f.is_file():
            print(f"trim_startup: {name} isn't there")
            continue
        desktops = [d for d in value(f, "NotShowIn").split(";") if d]
        if "KDE" not in desktops:
            desktops.append("KDE")
        edit(f, {"NotShowIn"}, ["NotShowIn=" + ";".join(desktops) + ";"])
        print(f"trim_startup: {name} doesn't start in Plasma")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
