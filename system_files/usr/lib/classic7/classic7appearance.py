"""
Classic 7 Appearance backend: applies a Palette to the running Plasma session.

What "Apply" does, for the current user only:
  1. draws the colour scheme, window borders, Plasma style and Start button into
     ~/.local/share under alternating ids (slot A/B), so Plasma and KWin really reload
  2. switches Plasma, KWin and the colour scheme to the new ids
  3. recolours a private copy of the Classic7 GTK theme (~/.local/share/themes/Classic7)
  4. sets the UI font size, the Start button image and the desktop colour
Choosing "Classic 7 Standard" at Normal size returns to the system theme files.

No GUI code here; classic7-appearance --help shows the command line.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import classic7theme as t

SYSTEM_GTK_THEME = Path(os.environ.get("CLASSIC7_SYSTEM_GTK", "/usr/share/themes/Classic7"))
SYSTEM_START_BUTTON = "/usr/share/classic7/start-button.svg"
SYSTEM_IDS = t.Ids()


def _home() -> Path:
    return Path(os.environ.get("CLASSIC7_HOME", Path.home()))


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", _home() / ".local/share"))


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", _home() / ".config"))


def state_file() -> Path:
    return config_home() / "classic7" / "appearance.json"


def user_schemes_file() -> Path:
    return config_home() / "classic7" / "schemes.json"


# =============================================================================
# Command runner (dry-run aware, so the backend can be tested anywhere)
# =============================================================================
class Runner:
    def __init__(self, dry_run: bool | None = None):
        self.dry_run = bool(os.environ.get("CLASSIC7_DRY_RUN")) if dry_run is None else dry_run
        self.log: list[str] = []
        self.failures: list[str] = []

    def __call__(self, *cmd: str, check: bool = False) -> bool:
        line = " ".join(shlex.quote(c) for c in cmd)
        self.log.append(line)
        if self.dry_run:
            return True
        if shutil.which(cmd[0]) is None:
            self.failures.append(f"{cmd[0]} not found")
            return False
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            # plasma-apply-* exit non-zero when the theme is already active; not an error
            msg = (res.stdout + res.stderr).strip()
            if "already set" not in msg:
                self.failures.append(f"{cmd[0]}: {msg[:200]}")
            return False
        return True


# =============================================================================
# State
# =============================================================================
@dataclass
class State:
    palette: t.Palette
    slot: str | None  # None = using the system theme files

    @classmethod
    def load(cls) -> "State":
        try:
            data = json.loads(state_file().read_text())
            return cls(t.Palette.from_json(data["palette"]), data.get("slot"))
        except (OSError, ValueError, KeyError, TypeError):
            return cls(t.STANDARD, None)

    def save(self):
        f = state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"palette": self.palette.to_json(), "slot": self.slot}, indent=2) + "\n")


def load_user_schemes() -> list[t.Palette]:
    try:
        return [t.Palette.from_json(d) for d in json.loads(user_schemes_file().read_text())]
    except (OSError, ValueError, TypeError):
        return []


def save_user_schemes(schemes: list[t.Palette]):
    f = user_schemes_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([p.to_json() for p in schemes], indent=2) + "\n")


def is_system_default(p: t.Palette) -> bool:
    return replace(p, name=t.STANDARD.name) == t.STANDARD


# =============================================================================
# GTK: recoloured private copy of the Classic7 theme
# =============================================================================
_HEX6 = re.compile(r"#[0-9a-fA-F]{6}\b")
_DEFINE = re.compile(r"^(\s*@define-color\s+)([A-Za-z0-9_]+)(\s+)([^;]+)(;.*)$")


def _recolour_css(text: str, defines: dict[str, str], cmap: dict[str, str]) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        m = _DEFINE.match(line.rstrip("\n"))
        if m and m.group(2) in defines:
            nl = "\n" if line.endswith("\n") else ""
            out.append(f"{m.group(1)}{m.group(2)}{m.group(3)}{defines[m.group(2)].lower()}{m.group(5)}{nl}")
        else:
            out.append(_HEX6.sub(lambda h: cmap.get(h.group(0).upper(), h.group(0)), line))
    return "".join(out)


def _recolour_png(path: Path, cmap_rgb: dict[tuple, tuple]) -> bool:
    try:
        from PIL import Image
    except ImportError:
        return False
    with Image.open(path) as im:
        rgba = im.convert("RGBA")
    px = rgba.load()
    changed = False
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            new = cmap_rgb.get((r, g, b))
            if new and a:
                px[x, y] = (*new, a)
                changed = True
    if changed:
        rgba.save(path)
    return True


def write_gtk_theme(p: t.Palette, runner: Runner) -> str | None:
    """Copy the system Classic7 GTK theme to ~/.local/share/themes and recolour it.
    GTK prefers the user copy (same name). Returns a note if something was skipped."""
    dst = data_home() / "themes" / "Classic7"
    if not SYSTEM_GTK_THEME.is_dir():
        return "GTK theme not found; GTK apps keep their colours"
    runner.log.append(f"# recolour GTK theme copy -> {dst}")
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SYSTEM_GTK_THEME, dst, symlinks=True)
    cmap = t.gtk_color_map(p)
    defines = t.gtk_define_colors(p)
    for f in dst.rglob("*"):
        if f.is_symlink() or not f.is_file():
            continue
        if f.suffix in (".css", ".svg") or f.name == "gtkrc":
            try:
                f.write_text(_recolour_css(f.read_text(), defines if f.suffix == ".css" else {}, cmap))
            except UnicodeDecodeError:
                pass
    cmap_rgb = {t._hex(k): t._hex(v) for k, v in cmap.items() if k != v}
    note = None
    if cmap_rgb:
        for f in dst.rglob("*.png"):
            if not f.is_symlink() and not _recolour_png(f, cmap_rgb):
                note = "python3-pillow missing: GTK button images keep the standard grey"
                break
    return note


def remove_gtk_theme():
    dst = data_home() / "themes" / "Classic7"
    if dst.exists():
        shutil.rmtree(dst)


# =============================================================================
# Fonts, Start button, desktop colour
# =============================================================================
def _font(size: int, weight: int = 400) -> str:
    return f"{t.UI_FONT},{size},-1,5,{weight},0,0,0,0,0,0,0,0,0,0,1"


def apply_fonts(size: int, run: Runner):
    for key, value in (("font", _font(size)), ("menuFont", _font(size)), ("toolBarFont", _font(size)),
                       ("smallestReadableFont", _font(max(size - 1, 7)))):
        run("kwriteconfig6", "--notify", "--file", "kdeglobals", "--group", "General", "--key", key, value)
    run("kwriteconfig6", "--notify", "--file", "kdeglobals", "--group", "WM", "--key", "activeFont", _font(size, 700))
    for ver in ("gtk-3.0", "gtk-4.0"):
        ini = config_home() / ver / "settings.ini"
        ini.parent.mkdir(parents=True, exist_ok=True)
        run("kwriteconfig6", "--file", str(ini), "--group", "Settings", "--key", "gtk-font-name", f"{t.UI_FONT} {size}")
    run("gsettings", "set", "org.gnome.desktop.interface", "font-name", f"{t.UI_FONT} {size}")


def plasma_script(start_button: str, desktop: str) -> str:
    ours = [SYSTEM_START_BUTTON, str(data_home() / "classic7")]
    return f"""
var img = "{start_button}";
var ours = {json.dumps(ours)};
panels().forEach(function (panel) {{
    // The Classic 7 Start menu replaces the Classic 7-styled Kicker menu (first in the panel)
    var hasStart = panel.widgets("org.classic7.startmenu").length > 0;
    panel.widgets("org.kde.plasma.kicker").forEach(function (w) {{
        w.currentConfigGroup = ["General"];
        var cur = String(w.readConfig("customButtonImage", ""));
        var isOurs = cur === "" || ours.some(function (o) {{ return cur.indexOf(o) !== -1; }});
        if (!isOurs) {{
            return;
        }}
        if (!hasStart && knownWidgetTypes.indexOf("org.classic7.startmenu") !== -1) {{
            var favs = w.readConfig("favoriteApps", []);
            var start = panel.addWidget("org.classic7.startmenu");
            if (start) {{
                start.currentConfigGroup = ["General"];
                if (favs && favs.length) {{
                    start.writeConfig("favoriteApps", favs);
                }}
                w.remove();
                hasStart = true;
                try {{
                    var ids = panel.widgetIds.filter(function (i) {{ return i !== start.id; }});
                    panel.currentConfigGroup = ["General"];
                    panel.writeConfig("AppletOrder", [start.id].concat(ids).join(";"));
                }} catch (e) {{}}
                return;
            }}
        }}
        w.writeConfig("useCustomButtonImage", true);
        w.writeConfig("customButtonImage", img);
        w.writeConfig("showIconsRootLevel", true);
        w.reloadConfig();
    }});
    panel.widgets("org.classic7.startmenu").forEach(function (w) {{
        w.currentConfigGroup = ["General"];
        w.writeConfig("buttonImage", img);
        w.reloadConfig();
    }});
    panel.widgets("org.kde.plasma.taskmanager").forEach(function (w) {{
        w.currentConfigGroup = ["General"];
        w.writeConfig("taskMaxWidth", 0);
        w.writeConfig("maxTextLines", 1);
        w.writeConfig("taskHoverEffect", false);
        w.reloadConfig();
    }});
}});
panels().forEach(function (panel) {{
    panel.widgets("org.kde.plasma.quicklaunch").forEach(function (w) {{
        w.currentConfigGroup = ["General"];
        var urls = w.readConfig("launcherUrls", []);
        if (typeof urls === "string") urls = urls.split(",");
        var changed = false;
        urls = urls.map(function (u) {{
            if (String(u).indexOf("org.kde.konsole.desktop") !== -1) {{ changed = true;
                return "file:///usr/share/applications/classic7-prompt.desktop"; }}
            return u;
        }});
        if (changed) {{ w.writeConfig("launcherUrls", urls); w.reloadConfig(); }}
    }});
}});
desktops().forEach(function (d) {{
    d.currentConfigGroup = ["Wallpaper", "org.kde.color", "General"];
    d.writeConfig("Color", "{t.rgb(desktop)}");
    d.reloadConfig();
}});
"""


def run_plasma_script(script: str, run: Runner):
    run("dbus-send", "--session", "--dest=org.kde.plasmashell", "--type=method_call",
        "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", f"string:{script}")


def reload_kwin(ids: t.Ids, run: Runner):
    run("kwriteconfig6", "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "library", "org.kde.kwin.aurorae")
    run("kwriteconfig6", "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "theme", ids.kwin_theme)
    run("dbus-send", "--session", "--type=signal", "/KWin", "org.kde.KWin.reloadConfig")


def remove_slot_files(slot: str):
    ids = t.slot_ids(slot, "")
    base = data_home()
    for path in (base / f"color-schemes/{ids.colors}.colors",
                 base / f"plasma/desktoptheme/{ids.plasma}",
                 base / f"aurorae/themes/{ids.aurorae}",
                 base / ids.start_button,
                 base / t.pressed_path(ids.start_button)):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


# =============================================================================
# Explorer (Dolphin) layout for existing accounts
# =============================================================================
SKEL = Path(os.environ.get("CLASSIC7_SKEL", "/etc/skel"))
DOLPHIN_DEFAULTS = Path(os.environ.get("CLASSIC7_DEFAULTS", "/usr/share/classic7/xdg-defaults")) / "dolphinrc"
EXPLORER_FILES = [
    ".local/state/dolphinstaterc",
    ".local/share/kxmlgui5/dolphin/dolphinui.rc",
    ".local/share/dolphin/view_properties/global/.directory",
]


def _ini_entries(path: Path):
    group = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1]
        elif "=" in line and group:
            key, value = line.split("=", 1)
            yield group, key, value


# Same settings as the Classic 7 global theme's layout script
DESKTOP_MENU_SCRIPT = """
var actionPlugins = ConfigFile("plasma-org.kde.plasma.desktop-appletsrc", "ActionPlugins");
var desktopActions = ConfigFile(actionPlugins, "0");
desktopActions.writeEntry("RightButton;NoModifier", "org.kde.contextmenu");
desktopActions.writeEntry("MiddleButton;NoModifier", "org.kde.paste");
var desktopMenu = ConfigFile(desktopActions, "RightButton;NoModifier");
desktopMenu.writeEntry("desktop edit mode", false);
desktopMenu.writeEntry("manage activities", false);
desktopMenu.writeEntry("add widgets", false);
desktopMenu.writeEntry("_display_settings", true);
desktopMenu.writeEntry("configure", true);
"""


def explorer_layout(runner: Runner | None = None) -> Result:
    """Give this account the Classic 7 Dolphin layout and right-click menus
    (replaced files are kept as .bak). The desktop menu changes apply at the next login."""
    run = runner or Runner()
    home = _home()
    notes = []
    run("pkill", "-x", "dolphin")  # Dolphin saves its layout on exit, so close it first
    # Settings: set our keys, keep the user's others. An old [MainWindow] State would
    # override the new layout, so remove it.
    if DOLPHIN_DEFAULTS.exists():
        for group, key, value in _ini_entries(DOLPHIN_DEFAULTS):
            run("kwriteconfig6", "--file", "dolphinrc", "--group", group, "--key", key, value)
        run("kwriteconfig6", "--file", "dolphinrc", "--group", "MainWindow", "--key", "State", "--delete")
    else:
        notes.append(f"missing {DOLPHIN_DEFAULTS}")
    for rel in EXPLORER_FILES:
        src, dst = SKEL / rel, home / rel
        if not src.exists():
            notes.append(f"missing {src}")
            continue
        run.log.append(f"# copy {src} -> {dst}")
        if run.dry_run:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            shutil.copy2(dst, dst.with_name(dst.name + ".bak"))
        shutil.copy2(src, dst)
    run_plasma_script(DESKTOP_MENU_SCRIPT, run)
    return Result(ok=not notes, notes=notes, commands=run.log)


# =============================================================================
# Public API
# =============================================================================
@dataclass
class Result:
    ok: bool
    notes: list[str]
    commands: list[str]


def apply(p: t.Palette, runner: Runner | None = None) -> Result:
    run = runner or Runner()
    state = State.load()
    notes: list[str] = []

    if is_system_default(p):
        ids = SYSTEM_IDS
        start = SYSTEM_START_BUTTON
        new_slot = None
        remove_gtk_theme()
    else:
        new_slot = "B" if state.slot == "A" else "A"
        ids = t.slot_ids(new_slot, p.name)
        t.render(p, data_home(), ids)
        start = str(data_home() / ids.start_button)
        note = write_gtk_theme(p, run)
        if note:
            notes.append(note)

    run("plasma-apply-colorscheme", ids.colors)
    run("plasma-apply-desktoptheme", ids.plasma)
    reload_kwin(ids, run)
    apply_fonts(p.font_size, run)
    run_plasma_script(plasma_script(start, p.desktop), run)
    # Lock screen: plain desktop colour, like the classic "Computer locked" screen
    run("kwriteconfig6", "--file", "kscreenlockerrc", "--group", "Greeter", "--key", "WallpaperPlugin", "org.kde.color")
    run("kwriteconfig6", "--file", "kscreenlockerrc", "--group", "Greeter", "--group", "Wallpaper",
        "--group", "org.kde.color", "--group", "General", "--key", "Color", t.rgb(p.desktop))

    for slot in ("A", "B"):
        if slot != new_slot:
            remove_slot_files(slot)

    State(p, new_slot).save()
    notes.extend(run.failures)
    notes.append("Restart open GTK apps (Firefox, Steam, Lutris…) to see their new colours.")
    return Result(ok=not run.failures, notes=notes, commands=run.log)
