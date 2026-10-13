"""
Classic 7 Appearance backend: applies a look to the running Plasma session, for the current
user only. There are three looks:

  aero     glass window borders, taskbar and Start menu in the user's glass colour, the round
           Start orb, task buttons with icons (programs pinned to them), Windows 7 controls in
           Qt (Kvantum) and GTK programs
  basic    the same in opaque light blue
  classic  grey bevels and a Palette (scheme): what "Apply" does for it:
             1. draws the colour scheme, window borders, Plasma style and Start button into
                ~/.local/share under alternating ids (slot A/B), so Plasma and KWin really reload
             2. switches Plasma, KWin and the colour scheme to the new ids
             3. recolours a private copy of the Classic7 GTK theme (~/.local/share/themes/Classic7)
             4. sets the UI font size, the Start button image and the desktop colour
           Choosing "Classic 7 Standard" at Normal size returns to the system theme files.

Accounts made after the Aero look arrived start with Aero (/etc/skel); older ones keep Classic
until they choose otherwise (no "look" in appearance.json means Classic).

No GUI code here; classic7-appearance --help shows the command line.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import time
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

import classic7aero as aero
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
    """Runs the desktop commands. Each one gets a time limit, and everything goes to
    ~/.cache/classic7/appearance.log so a failed Apply can be explained."""
    TIMEOUT = 30

    def __init__(self, dry_run: bool | None = None):
        self.dry_run = bool(os.environ.get("CLASSIC7_DRY_RUN")) if dry_run is None else dry_run
        self.log: list[str] = []
        self.failures: list[str] = []

    @staticmethod
    def logfile() -> Path:
        base = Path(os.environ.get("XDG_CACHE_HOME") or _home() / ".cache")
        return base / "classic7" / "appearance.log"

    def note(self, text: str):
        if self.dry_run:
            return
        try:
            f = self.logfile()
            f.parent.mkdir(parents=True, exist_ok=True)
            if f.exists() and f.stat().st_size > 512_000:
                f.unlink()
            with f.open("a") as fh:
                fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
        except OSError:
            pass

    def __call__(self, *cmd: str, check: bool = False) -> bool:
        line = " ".join(shlex.quote(c) for c in cmd)
        self.log.append(line)
        if self.dry_run:
            return True
        if shutil.which(cmd[0]) is None:
            self.failures.append(f"{cmd[0]} not found")
            self.note(f"MISSING {cmd[0]}")
            return False
        t0 = time.monotonic()
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 stdin=subprocess.DEVNULL, timeout=self.TIMEOUT)
        except subprocess.TimeoutExpired:
            self.failures.append(f"{cmd[0]} did not answer within {self.TIMEOUT} s")
            self.note(f"TIMEOUT {line[:300]}")
            return False
        msg = (res.stdout + res.stderr).strip()
        self.note(f"rc={res.returncode} {time.monotonic() - t0:.1f}s {line[:300]}"
                  + (f"\n    {msg[:600]}" if msg else ""))
        if res.returncode != 0:
            # plasma-apply-* exit non-zero when the theme is already active; not an error
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
    slot: str | None                     # None = using the system theme files (Classic)
    look: str = "classic"                # aero, basic or classic
    glass: aero.Glass | None = None      # the Aero window colour
    glass_slot: str | None = None        # per-user Aero files (A/B) for a non-default glass colour
    small_icons: bool = False            # Aero/Basic taskbar 30 px instead of 40 px

    def __post_init__(self):
        if self.glass is None:
            self.glass = aero.Glass()
        if self.look not in aero.LOOKS:
            self.look = "classic"

    @classmethod
    def load(cls) -> "State":
        try:
            data = json.loads(state_file().read_text())
        except (OSError, ValueError):
            return cls(t.STANDARD, None)
        if not isinstance(data, dict):
            return cls(t.STANDARD, None)
        try:
            pal = t.Palette.from_json(data["palette"]) if data.get("palette") else t.STANDARD
        except (KeyError, TypeError, ValueError):
            pal = t.STANDARD
        return cls(pal, data.get("slot"), str(data.get("look") or "classic"),
                   aero.Glass.from_json(data.get("glass") if isinstance(data.get("glass"), dict) else None),
                   data.get("glass_slot"), bool(data.get("small_icons", False)))

    def save(self):
        f = state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"palette": self.palette.to_json(), "slot": self.slot, "look": self.look,
                                 "glass": self.glass.to_json(), "glass_slot": self.glass_slot,
                                 "small_icons": self.small_icons}, indent=2) + "\n")


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
    try:
        with Image.open(path) as im:
            rgba = im.convert("RGBA")
    except OSError:
        return True
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
        try:
            rgba.save(path)
        except OSError:
            pass
    return True


def write_gtk_theme(p: t.Palette, runner: Runner) -> str | None:
    """Copy the system Classic7 GTK theme to ~/.local/share/themes and recolour it.
    GTK prefers the user copy (same name). Returns a note if something was skipped."""
    dst = data_home() / "themes" / "Classic7"
    if not SYSTEM_GTK_THEME.is_dir():
        return "GTK theme not found; GTK apps keep their colours"
    runner.log.append(f"# recolour GTK theme copy -> {dst}")
    if runner.dry_run:
        return None
    if dst.exists():
        _make_writable(dst)
        shutil.rmtree(dst, ignore_errors=True)
    skipped = _copy_tree(SYSTEM_GTK_THEME, dst)
    if skipped:
        runner.note(f"GTK theme: {len(skipped)} unreadable files skipped, e.g. {skipped[0]}")
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


def _copy_tree(src: Path, dst: Path) -> list[str]:
    """Copy a theme folder as plain user files (0755 folders, 0644 files): the system copy
    may be read-only or partly unreadable. Returns the files that could not be read."""
    skipped = []
    for root, dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        os.chmod(dst / rel, 0o755)
        for name in files + [d for d in dirs if (Path(root) / d).is_symlink()]:
            s_path, d_path = Path(root) / name, dst / rel / name
            try:
                if s_path.is_symlink():
                    if not d_path.exists() and not d_path.is_symlink():
                        os.symlink(os.readlink(s_path), d_path)
                    continue
                shutil.copyfile(s_path, d_path)
                os.chmod(d_path, 0o644)
            except OSError:
                skipped.append(str(s_path))
    return skipped


def _make_writable(path: Path):
    for root, dirs, _files in os.walk(path):
        for d in dirs:
            try:
                os.chmod(Path(root) / d, 0o755)
            except OSError:
                pass
    try:
        os.chmod(path, 0o755)
    except OSError:
        pass


def remove_gtk_theme():
    dst = data_home() / "themes" / "Classic7"
    if dst.exists():
        _make_writable(dst)
        shutil.rmtree(dst, ignore_errors=True)


# =============================================================================
# Fonts, Start button, desktop colour
# =============================================================================
def _font(size: int, weight: int = 400) -> str:
    return f"{t.UI_FONT},{size},-1,5,{weight},0,0,0,0,0,0,0,0,0,0,1"


def apply_fonts(size: int, run: Runner, bold_titles: bool = True):
    for key, value in (("font", _font(size)), ("menuFont", _font(size)), ("toolBarFont", _font(size)),
                       ("smallestReadableFont", _font(max(size - 1, 7)))):
        run("kwriteconfig6", "--notify", "--file", "kdeglobals", "--group", "General", "--key", key, value)
    run("kwriteconfig6", "--notify", "--file", "kdeglobals", "--group", "WM", "--key", "activeFont",
        _font(size, 700 if bold_titles else 400))
    for ver in ("gtk-3.0", "gtk-4.0"):
        ini = config_home() / ver / "settings.ini"
        ini.parent.mkdir(parents=True, exist_ok=True)
        run("kwriteconfig6", "--file", str(ini), "--group", "Settings", "--key", "gtk-font-name", f"{t.UI_FONT} {size}")
    run("gsettings", "set", "org.gnome.desktop.interface", "font-name", f"{t.UI_FONT} {size}")


LAYOUT_JS = Path(os.environ.get(
    "CLASSIC7_LAYOUT_JS",
    "/usr/share/plasma/look-and-feel/org.classic7.desktop/contents/layouts/org.kde.plasma.desktop-layout.js"))
AERO_LAYOUT_JS = Path(os.environ.get(
    "CLASSIC7_AERO_LAYOUT_JS",
    "/usr/share/plasma/look-and-feel/org.classic7.aero.desktop/contents/layouts/org.kde.plasma.desktop-layout.js"))


def taskbar_js(start_button: str = SYSTEM_START_BUTTON, layout: Path | None = None) -> str:
    """The taskbar part of a Classic 7 layout script, run on its own: removes the bottom
    panel(s) and builds the taskbar again (Classic: Start | Quick Launch | tasks | tray | clock;
    Aero/Basic: Start orb | pinned and running programs | tray | clock)."""
    try:
        text = (layout or LAYOUT_JS).read_text()
        body = text[text.index("// BEGIN TASKBAR"):text.index("// END TASKBAR")]
    except (OSError, ValueError):
        return "// layout script not found"
    body = body.replace('"/usr/share/classic7/start-button.svg"', json.dumps(start_button))
    body = body.replace('"/usr/share/classic7/start-orb.svg"', json.dumps(start_button))
    return ('panels().forEach(function (p) { if (p.location === "bottom") { p.remove(); } });\n'
            + body)


def look_taskbar_js(look: str, start_button: str, small_icons: bool = False) -> str:
    """The taskbar of a look, built afresh (Classic: Start button and Quick Launch;
    Aero and Basic: the Start orb and task buttons with icons)."""
    if look == "classic":
        return taskbar_js(start_button)
    script = taskbar_js(SYSTEM_ORB, AERO_LAYOUT_JS)
    if look == "basic":
        script = script.replace('writeConfig("look", "aero")', 'writeConfig("look", "basic")')
    if small_icons:
        script = script.replace("panel.height = 40;", "panel.height = 30;")
    return script


def reset_taskbar(runner: "Runner | None" = None) -> "Result":
    """Rebuild this account's taskbar the Classic 7 way for its look (fixes the Start button position)."""
    run = runner or Runner()
    state = State.load()
    start = SYSTEM_START_BUTTON
    if state.look == "classic" and state.slot:
        start = str(data_home() / t.slot_ids(state.slot, state.palette.name).start_button)
    run_plasma_script(look_taskbar_js(state.look, start, state.small_icons), run)
    return Result(ok=not run.failures, notes=list(run.failures), commands=run.log)


def plasma_script(start_button: str, desktop: str, look: str = "classic", wallpaper: str | None = None,
                  set_desktop: bool = True, small_icons: bool = False) -> str:
    """Settings of the taskbar's applets for a look (Start button image, the look of the Start
    menu and Show desktop button) and, when set_desktop, the desktop's colour or picture."""
    ours = [SYSTEM_START_BUTTON, str(data_home() / "classic7")]
    classic = look == "classic"
    desktop_js = ""
    if set_desktop:
        if wallpaper:
            desktop_js = f"""
desktops().forEach(function (d) {{
    d.wallpaperPlugin = "org.kde.image";
    d.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    d.writeConfig("Image", {json.dumps("file://" + wallpaper)});
    d.writeConfig("FillMode", 2);
    d.writeConfig("Color", "{desktop.lower()}");
    d.reloadConfig();
}});"""
        else:
            desktop_js = f"""
desktops().forEach(function (d) {{
    if (d.wallpaperPlugin !== "org.kde.color") d.wallpaperPlugin = "org.kde.color";
    d.currentConfigGroup = ["Wallpaper", "org.kde.color", "General"];
    // "#rrggbb", not "r,g,b": a running wallpaper takes the value as a QColor, and Qt can't
    // read "r,g,b" there, so the desktop turned black
    d.writeConfig("Color", "{desktop.lower()}");
    d.reloadConfig();
}});"""
    tasks_js = """
    panel.widgets("org.kde.plasma.taskmanager").forEach(function (w) {
        w.currentConfigGroup = ["General"];
        w.writeConfig("taskMaxWidth", 0);
        w.writeConfig("maxTextLines", 1);
        w.writeConfig("taskHoverEffect", false);
        w.reloadConfig();
    });""" if classic else ""
    return f"""
var img = "{start_button}";
var look = "{look}";
var ours = {json.dumps(ours)};
var rebuildTaskbar = false;
panels().forEach(function (panel) {{
    // A Classic 7-styled Kicker menu means a taskbar from before the Classic 7 Start menu:
    // rebuild it (below) so the new Start button sits at the left end.
    panel.widgets("org.kde.plasma.kicker").forEach(function (w) {{
        w.currentConfigGroup = ["General"];
        var cur = String(w.readConfig("customButtonImage", ""));
        var isOurs = cur === "" || ours.some(function (o) {{ return cur.indexOf(o) !== -1; }});
        if (isOurs && knownWidgetTypes.indexOf("org.classic7.startmenu") !== -1) {{
            rebuildTaskbar = true;
        }} else if (isOurs) {{
            w.writeConfig("useCustomButtonImage", true);
            w.writeConfig("customButtonImage", img);
            w.writeConfig("showIconsRootLevel", true);
            w.reloadConfig();
        }}
    }});
    panel.widgets("org.classic7.startmenu").forEach(function (w) {{
        w.currentConfigGroup = ["General"];
        w.writeConfig("buttonImage", img);
        w.writeConfig("look", look);
        w.reloadConfig();
    }});
    panel.widgets("org.classic7.showdesktop").forEach(function (w) {{
        w.currentConfigGroup = ["General"];
        w.writeConfig("look", look);
        w.reloadConfig();
    }});{tasks_js}
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
}});{desktop_js}
if (rebuildTaskbar) {{
{look_taskbar_js(look, start_button, small_icons)}
}}
"""


APP_DIRS = ["/usr/share/applications", "/var/lib/flatpak/exports/share/applications"]


def desktop_file_urls() -> dict[str, str]:
    """Programs' .desktop files by name, as file:// URLs (the user's own win)."""
    out: dict[str, str] = {}
    dirs = APP_DIRS + [str(data_home() / "flatpak/exports/share/applications"), str(data_home() / "applications")]
    for d in dirs:
        try:
            for f in Path(d).glob("*.desktop"):
                out[f.name] = "file://" + str(f)
        except OSError:
            continue
    return out


# Shared by the Taskbar and Start Menu Properties dialog
TASKBAR_LIB = """
function c7List(w, key) {
    var v = w.readConfig(key, []);
    if (typeof v === "string") v = v ? v.split(",") : [];
    return v;
}
function c7Taskbar() {
    var ps = panels();
    for (var i = 0; i < ps.length; i++) {
        if (ps[i].widgets("org.classic7.startmenu").length || ps[i].widgets("org.kde.plasma.kicker").length) return ps[i];
    }
    for (var j = 0; j < ps.length; j++) {
        if (ps[j].location === "bottom") return ps[j];
    }
    return ps.length ? ps[0] : null;
}
function c7TaskManager(panel) {
    var t = panel.widgets("org.kde.plasma.icontasks").concat(panel.widgets("org.kde.plasma.taskmanager"));
    return t.length ? t[0] : null;
}
// Task buttons with icons only (always combined) or with text; keeps their position and pins
function c7TaskButtons(panel, type) {
    var tm = c7TaskManager(panel);
    var pins = [];
    if (tm) { tm.currentConfigGroup = ["General"]; pins = c7List(tm, "launchers"); }
    if (!tm || tm.type !== type) {
        var index = tm ? tm.index : -1;
        if (tm) tm.remove();
        tm = panel.addWidget(type);
        if (!tm) return null;
        if (index >= 0) tm.index = index;
        tm.currentConfigGroup = ["General"];
        tm.writeConfig("launchers", pins);
    }
    tm.currentConfigGroup = ["General"];
    return tm;
}
"""


def switch_taskbar_script(look: str, start_button: str, height: int) -> str:
    """Change the taskbar between looks: Aero and Basic put pinned programs on icon-only task
    buttons (Windows 7) and drop Quick Launch; Classic has Quick Launch and task buttons with text."""
    return TASKBAR_LIB + f"""
var paths = {json.dumps(desktop_file_urls())};
function c7Url(u) {{
    u = String(u);
    var m = u.match(/([^\\/:]+\\.desktop)$/);
    return (m && paths[m[1]]) ? paths[m[1]] : u;
}}
var panel = c7Taskbar();
if (panel) {{
    panel.height = {height};
    var ql = panel.widgets("org.kde.plasma.quicklaunch");
    if ({json.dumps(look != "classic")}) {{
        var tm = c7TaskManager(panel);
        var pins = [];
        if (tm) {{ tm.currentConfigGroup = ["General"]; pins = c7List(tm, "launchers"); }}
        ql.forEach(function (q) {{
            q.currentConfigGroup = ["General"];
            c7List(q, "launcherUrls").forEach(function (u) {{ if (pins.indexOf(u) === -1) pins.push(u); }});
            q.remove();
        }});
        tm = c7TaskButtons(panel, "org.kde.plasma.icontasks");
        if (tm) {{
            tm.writeConfig("launchers", pins);
            tm.writeConfig("groupingStrategy", 1);
            tm.writeConfig("onlyGroupWhenFull", false);
            tm.reloadConfig();
        }}
    }} else {{
        var tm2 = c7TaskManager(panel);
        var pins2 = [];
        if (tm2) {{ tm2.currentConfigGroup = ["General"]; pins2 = c7List(tm2, "launchers").map(c7Url); }}
        tm2 = c7TaskButtons(panel, "org.kde.plasma.taskmanager");
        if (tm2) {{
            tm2.writeConfig("launchers", []);
            tm2.writeConfig("groupingStrategy", 1);
            tm2.writeConfig("onlyGroupWhenFull", true);
            tm2.writeConfig("taskMaxWidth", 0);
            tm2.writeConfig("maxTextLines", 1);
            tm2.writeConfig("taskHoverEffect", false);
            tm2.reloadConfig();
        }}
        if (!ql.length && knownWidgetTypes.indexOf("org.kde.plasma.quicklaunch") !== -1) {{
            var q = panel.addWidget("org.kde.plasma.quicklaunch");
            if (q) {{
                q.index = 1;
                q.currentConfigGroup = ["General"];
                q.writeConfig("launcherUrls", pins2.length ? pins2 : [
                    "file:///usr/share/applications/org.kde.dolphin.desktop",
                    "file:///usr/share/applications/steam.desktop",
                    "file:///usr/share/applications/classic7-prompt.desktop"]);
                q.reloadConfig();
            }}
        }}
    }}
}}
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


# Places panel sections Windows 7's navigation pane doesn't have
HIDDEN_PLACE_GROUPS = ("RecentlySaved", "SearchFor", "Tags")


def hide_place_groups(home: Path | None = None) -> bool:
    """Hide the Recent / Search For / Tags sections of Dolphin's Places panel (stored as
    root metadata in user-places.xbel). Returns False while KDE hasn't created the file yet
    (it resets these flags when it fills a new one)."""
    path = (home or _home()) / ".local/share/user-places.xbel"
    try:
        text = path.read_text()
    except OSError:
        return False
    if "kde_places_version" not in text:
        return False
    new = text
    missing = []
    for g in HIDDEN_PLACE_GROUPS:
        key = f"GroupState-{g}-IsHidden"
        if f"<{key}>" in new:
            new = re.sub(rf"<{key}>[^<]*</{key}>", f"<{key}>true</{key}>", new)
        else:
            missing.append(f"   <{key}>true</{key}>\n")
    if missing:
        first = min([i for i in (new.find("<bookmark"), new.find("<separator"), new.find("</xbel>")) if i >= 0]
                    or [len(new)])
        head = new[:first]
        m = re.search(r'<metadata owner="http://www\.kde\.org">', head)
        if m:
            end = head.find("</metadata>", m.end())
            new = new[:end] + "".join(missing) + "  " + new[end:]
        else:
            root = re.search(r"<xbel[^>]*>\s*", new)
            if not root:
                return False
            info = re.match(r"<info>\s*", new[root.end():])
            block = '  <metadata owner="http://www.kde.org">\n' + "".join(missing) + "  </metadata>\n"
            if info:
                at = root.end() + info.end()
                new = new[:at] + block.lstrip() + " " + new[at:]
            else:
                new = new[:root.end()] + " <info>\n" + block + " </info>\n " + new[root.end():]
    if new != text:
        shutil.copy2(path, path.with_name(path.name + ".bak"))
        path.write_text(new)
    return True


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
    if not run.dry_run:
        run.log.append("# hide Recent / Search For / Tags in Places")
        try:
            hide_place_groups(home)
        except OSError as e:
            notes.append(f"places: {e}")
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


def apply(p: t.Palette | None = None, runner: Runner | None = None, look: str | None = None,
          glass: aero.Glass | None = None) -> Result:
    """Apply a look. Without arguments: the account's saved look again (after an update).
    p: the Classic scheme; look: aero, basic or classic; glass: the Aero window colour."""
    run = runner or Runner()
    state = State.load()
    p = p or state.palette
    look = look if look in aero.LOOKS else state.look
    glass = glass or state.glass
    switching = look != state.look
    run.note(f"== apply look={look} (was {state.look}) scheme={p.name!r} glass={glass.to_json()}")
    if look == "classic":
        return _apply_classic(p, run, state, switching)
    return _apply_modern(look, glass, p, run, state, switching)


def _apply_classic(p: t.Palette, run: Runner, state: State, switching: bool) -> Result:
    notes: list[str] = []
    if is_system_default(p):
        ids = SYSTEM_IDS
        start = SYSTEM_START_BUTTON
        new_slot = None
        if not run.dry_run:
            remove_gtk_theme()
    else:
        new_slot = "B" if state.slot == "A" else "A"
        ids = t.slot_ids(new_slot, p.name)
        run.log.append(f"# draw {p.name} -> {ids.colors}, {ids.plasma}, {ids.aurorae}")
        if not run.dry_run:
            t.render(p, data_home(), ids)
        start = str(data_home() / ids.start_button)
        try:
            note = write_gtk_theme(p, run)
        except Exception as e:  # noqa: BLE001 - GTK colours are optional, the rest must still apply
            run.note(f"GTK theme failed: {e!r}")
            note = "GTK apps keep their old colours (see the log)"
        if note:
            notes.append(note)

    run("plasma-apply-colorscheme", ids.colors)
    run("plasma-apply-desktoptheme", ids.plasma)
    set_widget_style("Windows", run)
    global_theme("org.classic7.desktop", run)
    set_gtk_theme("Classic7", CLASSIC_CURSORS, run)
    set_cursors(CLASSIC_CURSORS, run)
    kwin_look(ids.kwin_theme, "Normal", "IA_X", "classic7", run)
    apply_fonts(p.font_size, run)
    if switching:
        run_plasma_script(switch_taskbar_script("classic", start, 30), run)
    run_plasma_script(plasma_script(start, p.desktop, look="classic", wallpaper=None, set_desktop=True), run)
    # Lock screen: plain desktop colour, like the classic "Computer locked" screen
    lock_screen(None, p.desktop, run)

    if not run.dry_run:
        for slot in ("A", "B"):
            if slot != new_slot:
                remove_slot_files(slot)
            remove_glass_files(slot)
        State(p, new_slot, "classic", state.glass, None, state.small_icons).save()
    notes.extend(run.failures)
    notes.append("Restart open GTK apps (Firefox, Steam, Lutris…) to see their new colours.")
    return Result(ok=not run.failures, notes=notes, commands=run.log)


AERO_WALLPAPER = "/usr/share/wallpapers/Classic7Aero/"
AERO_DESKTOP = "#1C5A9E"           # behind the wallpaper, and the lock screen if it has none
SYSTEM_ORB = "/usr/share/classic7/start-orb.svg"
CLASSIC_CURSORS = "Chicago95_Standard_Cursors"


def aero_cursors() -> str:
    """Windows 7's cursors are white with a black edge: Breeze Light, else Breeze."""
    for name in ("Breeze_Light", "breeze_cursors"):
        for base in ("/usr/share/icons", str(data_home() / "icons")):
            if (Path(base) / name / "cursors").is_dir():
                return name
    return CLASSIC_CURSORS


def kvantum_installed() -> bool:
    import glob
    return bool(glob.glob("/usr/lib*/qt6/plugins/styles/libkvantum.so"))


def set_widget_style(style: str, run: Runner):
    run("kwriteconfig6", "--notify", "--file", "kdeglobals", "--group", "KDE", "--key", "widgetStyle", style)


def set_kvantum_theme(name: str, run: Runner):
    cfg = config_home() / "Kvantum" / "kvantum.kvconfig"
    if not run.dry_run:
        cfg.parent.mkdir(parents=True, exist_ok=True)
    run("kwriteconfig6", "--file", str(cfg), "--group", "General", "--key", "theme", name)


def set_gtk_theme(name: str, cursors: str, run: Runner):
    for ver in ("gtk-3.0", "gtk-4.0"):
        ini = config_home() / ver / "settings.ini"
        if not run.dry_run:
            ini.parent.mkdir(parents=True, exist_ok=True)
        run("kwriteconfig6", "--file", str(ini), "--group", "Settings", "--key", "gtk-theme-name", name)
        run("kwriteconfig6", "--file", str(ini), "--group", "Settings", "--key", "gtk-cursor-theme-name", cursors)
    run("gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", name)


def set_cursors(name: str, run: Runner):
    run("plasma-apply-cursortheme", name)
    run("gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", name)


def global_theme(package: str, run: Runner):
    """The Global Theme System Settings shows (and Dark Mode switches to) follows the look."""
    for key in ("LookAndFeelPackage", "DefaultLightLookAndFeel", "DefaultDarkLookAndFeel"):
        run("kwriteconfig6", "--file", "kdeglobals", "--group", "KDE", "--key", key, package)


def kwin_look(theme: str, border: str, right_buttons: str, tabbox: str, run: Runner, blur: bool = False):
    def kw(group, key, value):
        run("kwriteconfig6", "--file", "kwinrc", "--group", group, "--key", key, value)
    kw("org.kde.kdecoration2", "library", "org.kde.kwin.aurorae")
    kw("org.kde.kdecoration2", "theme", theme)
    kw("org.kde.kdecoration2", "BorderSize", border)
    kw("org.kde.kdecoration2", "BorderSizeAuto", "false")
    kw("org.kde.kdecoration2", "ButtonsOnLeft", "M")
    kw("org.kde.kdecoration2", "ButtonsOnRight", right_buttons)
    kw("TabBox", "LayoutName", tabbox)
    if blur:
        # Windows 7's glass is softly blurred, without noise
        kw("Plugins", "blurEnabled", "true")
        kw("Effect-blur", "BlurStrength", "8")
        kw("Effect-blur", "NoiseStrength", "0")
    run("dbus-send", "--session", "--type=signal", "/KWin", "org.kde.KWin.reloadConfig")


def lock_screen(image: str | None, colour: str, run: Runner):
    def lk(*groups_key_value):
        *groups, key, value = groups_key_value
        cmd = ["kwriteconfig6", "--file", "kscreenlockerrc"]
        for g in groups:
            cmd += ["--group", g]
        run(*cmd, "--key", key, value)
    if image:
        lk("Greeter", "WallpaperPlugin", "org.kde.image")
        lk("Greeter", "Wallpaper", "org.kde.image", "General", "Image", image)
    else:
        lk("Greeter", "WallpaperPlugin", "org.kde.color")
        lk("Greeter", "Wallpaper", "org.kde.color", "General", "Color", t.rgb(colour))


def remove_glass_files(slot: str):
    base = data_home()
    for look in ("aero", "basic"):
        ids = aero.slot_ids(look, slot)
        for path in (base / f"plasma/desktoptheme/{ids.plasma}", base / f"aurorae/themes/{ids.aurorae}"):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)


def _apply_modern(look: str, glass: aero.Glass, p: t.Palette, run: Runner, state: State, switching: bool) -> Result:
    notes: list[str] = []
    new_glass_slot = None
    if look == "aero" and not aero.is_default_glass(glass):
        new_glass_slot = "B" if state.glass_slot == "A" else "A"
        ids = aero.slot_ids("aero", new_glass_slot)
        if not run.dry_run:
            aero.render("aero", glass, data_home(), ids, with_scheme=False)
        run.log.append(f"# draw the Aero look in {glass.name} ({glass.color}) -> {ids.plasma}, {ids.aurorae}")
    else:
        ids = aero.system_ids(look)
    run("plasma-apply-colorscheme", "Classic7Aero")
    run("plasma-apply-desktoptheme", ids.plasma)
    if kvantum_installed():
        set_kvantum_theme("Classic7Aero", run)
        set_widget_style("kvantum", run)
    else:
        notes.append("Kvantum is not installed: programs keep plain controls.")
        set_widget_style("Fusion", run)
    global_theme("org.classic7.aero.desktop", run)
    cursors = aero_cursors()
    set_gtk_theme("Classic7Aero", cursors, run)
    set_cursors(cursors, run)
    kwin_look(ids.kwin_theme, "Large", "IAX", "classic7aero", run, blur=(look == "aero"))
    apply_fonts(p.font_size, run, bold_titles=False)
    height = 30 if state.small_icons else 40
    if switching:
        run_plasma_script(switch_taskbar_script(look, SYSTEM_ORB, height), run)
    run_plasma_script(plasma_script(SYSTEM_ORB, AERO_DESKTOP, look=look,
                                    wallpaper=AERO_WALLPAPER if switching else None, set_desktop=switching,
                                    small_icons=state.small_icons), run)
    lock_screen(AERO_WALLPAPER if Path(AERO_WALLPAPER).is_dir() else None, AERO_DESKTOP, run)
    if not run.dry_run:
        for slot in ("A", "B"):
            if slot != new_glass_slot:
                remove_glass_files(slot)
            # a Classic scheme's own files are drawn again when Classic is chosen
            remove_slot_files(slot)
        State(p, None, look, glass, new_glass_slot, state.small_icons).save()
    notes.extend(run.failures)
    notes.append("Restart open programs to give them the new controls.")
    return Result(ok=not run.failures, notes=notes, commands=run.log)
