"""Taskbar and Start Menu Properties without the GUI: what the taskbar has now (asked from the
running Plasma) and the Plasma script that changes it. classic7-taskbar-properties is the dialog.

Everything lives in Plasma's own settings (the panel, its task manager, the Start menu applet,
the Show desktop button and the notification area), so Plasma's own tools see the same."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

import classic7appearance as backend

LOCATIONS = [("bottom", "Bottom"), ("left", "Left"), ("right", "Right"), ("top", "Top")]
BUTTONS = [("always", "Always combine, hide labels"), ("full", "Combine when taskbar is full"),
           ("never", "Never combine")]
POWER = [("switch-user", "Switch user"), ("logout", "Log off"), ("lock", "Lock"), ("reboot", "Restart"),
         ("suspend", "Sleep"), ("hibernate", "Hibernate"), ("shutdown", "Shut down")]
# Customize Start Menu: (Start menu setting, label, Windows 7's default)
START_ITEMS = [
    ("showComputer", "Computer", True),
    ("showControlPanel", "Control Panel", True),
    ("showDefaultPrograms", "Default Programs", True),
    ("showDevices", "Devices and Printers", True),
    ("showDocuments", "Documents", True),
    ("showDownloads", "Downloads", False),
    ("showGames", "Games", True),
    ("showHelp", "Help", True),
    ("showMusic", "Music", True),
    ("showPersonalFolder", "Personal folder", True),
    ("showPictures", "Pictures", True),
    ("showRun", "Run command", True),
    ("largeIcons", "Use large icons", True),
    ("showVideos", "Videos", False),
]
RECENT_DEFAULT = 10
# the Start menu settings this dialog reads and writes, with their defaults
START_DEFAULTS: dict[str, object] = {
    **{key: default for key, _, default in START_ITEMS},
    "powerAction": "shutdown", "showRecentPrograms": True, "showJumpLists": True, "recentCount": RECENT_DEFAULT,
}
# Notification area: each icon is shown, hidden, or (Plasma's default) shown when it has news
SHOW, HIDE, AUTO = "show", "hide", "auto"
BEHAVIORS = [(SHOW, "Show icon and notifications"), (HIDE, "Hide icon and notifications"),
             (AUTO, "Only show notifications")]
TASK_MANAGERS = ("org.kde.plasma.icontasks", "org.kde.plasma.taskmanager")
QUICK_LAUNCH_DEFAULT = ["file:///usr/share/applications/org.kde.dolphin.desktop",
                        "file:///usr/share/applications/steam.desktop",
                        "file:///usr/share/applications/classic7-prompt.desktop"]


@dataclass
class Tray:
    shown: list[str] = field(default_factory=list)
    hidden: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)      # notification area icons that are on
    known: list[str] = field(default_factory=list)
    show_all: bool = False


@dataclass
class Taskbar:
    found: bool = False
    location: str = "bottom"
    height: int = 30
    hiding: str = "none"                 # none or autohide (Plasma also has dodgewindows...)
    locked: bool = False
    buttons: str = "full"                # always, full or never (BUTTONS)
    quicklaunch: bool = False
    can_quicklaunch: bool = True         # the Quick Launch widget is installed
    peek: bool = True
    has_showdesktop: bool = False
    start: dict = field(default_factory=lambda: dict(START_DEFAULTS))
    has_startmenu: bool = False
    tray: Tray | None = None


# =============================================================================
# Talking to Plasma
# =============================================================================
def evaluate(script: str, timeout: int = 20) -> str | None:
    """Run a Plasma desktop script; returns what it print()ed, or None if Plasma didn't answer."""
    try:
        r = subprocess.run(["dbus-send", "--session", "--print-reply=literal", "--dest=org.kde.plasmashell",
                            "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", "string:" + script],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _bool(v, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None or v == "":
        return default
    return str(v).strip().lower() == "true"


def _list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v if str(x)]
    return [x for x in str(v or "").split(",") if x]


QUERY_JS = """
function c7Bool(v) { return String(v) === "true"; }
var out = {found: false};
var p = c7Taskbar();
if (p) {
    out.found = true;
    out.location = p.location; out.height = p.height; out.hiding = p.hiding; out.locked = p.locked;
    var tm = c7TaskManager(p);
    out.tasks = tm ? tm.type : "";
    if (tm) {
        tm.currentConfigGroup = ["General"];
        out.grouping = Number(tm.readConfig("groupingStrategy", 1));
        out.onlyWhenFull = c7Bool(tm.readConfig("onlyGroupWhenFull", true));
    }
    out.quicklaunch = p.widgets("org.kde.plasma.quicklaunch").length > 0;
    out.canQuicklaunch = knownWidgetTypes.indexOf("org.kde.plasma.quicklaunch") !== -1;
    var sm = p.widgets("org.classic7.startmenu");
    if (sm.length) {
        sm[0].currentConfigGroup = ["General"];
        out.start = {};
        Object.keys(START).forEach(function (k) { out.start[k] = sm[0].readConfig(k, START[k]); });
    }
    var sd = p.widgets("org.classic7.showdesktop");
    out.showdesktop = sd.length > 0;
    if (sd.length) { sd[0].currentConfigGroup = ["General"]; out.peek = c7Bool(sd[0].readConfig("peek", true)); }
    var tray = p.widgets("org.kde.plasma.systemtray");
    if (tray.length) {
        var t = tray[0];
        t.currentConfigGroup = [];
        var id = t.readConfig("SystrayContainmentId");
        var c = id ? desktopById(id) : null;
        var o = c || t;
        o.currentConfigGroup = ["General"];
        out.tray = {shown: c7List(o, "shownItems"), hidden: c7List(o, "hiddenItems"), extra: c7List(o, "extraItems"),
                    known: c7List(o, "knownItems"), showAll: c7Bool(o.readConfig("showAllItems", false))};
    }
}
print("C7JSON" + JSON.stringify(out) + "C7END");
"""


def parse(text: str | None) -> Taskbar:
    m = re.search(r"C7JSON(.*)C7END", text or "", re.S)
    if not m:
        return Taskbar()
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return Taskbar()
    if not d.get("found"):
        return Taskbar()
    tasks = d.get("tasks", "")
    if tasks == "org.kde.plasma.icontasks":
        buttons = "always"
    elif int(d.get("grouping", 1) or 0) == 0:
        buttons = "never"
    else:
        buttons = "full"
    start = dict(START_DEFAULTS)
    for k, v in (d.get("start") or {}).items():
        if k in START_DEFAULTS:
            dv = START_DEFAULTS[k]
            if isinstance(dv, bool):
                start[k] = _bool(v, dv)
            elif isinstance(dv, int):
                try:
                    start[k] = int(v)
                except (TypeError, ValueError):
                    start[k] = dv
            else:
                start[k] = str(v or dv)
    tray = None
    if isinstance(d.get("tray"), dict):
        t = d["tray"]
        tray = Tray(_list(t.get("shown")), _list(t.get("hidden")), _list(t.get("extra")), _list(t.get("known")),
                    _bool(t.get("showAll"), False))
    return Taskbar(True, str(d.get("location") or "bottom"), int(d.get("height") or 30),
                   str(d.get("hiding") or "none"), _bool(d.get("locked"), False), buttons,
                   _bool(d.get("quicklaunch"), False), _bool(d.get("canQuicklaunch"), True),
                   _bool(d.get("peek"), True), _bool(d.get("showdesktop"), False), start,
                   d.get("start") is not None, tray)


def query_script() -> str:
    return backend.TASKBAR_LIB + "var START = " + json.dumps(START_DEFAULTS) + ";\n" + QUERY_JS


def read() -> Taskbar:
    return parse(evaluate(query_script()))


# =============================================================================
# Changing it
# =============================================================================
def look() -> str:
    return backend.State.load().look


def taskbar_height(look_name: str, small: bool) -> int:
    """Classic's taskbar is always the thin one; Aero and Basic have large or small icons."""
    return 30 if look_name == "classic" or small else 40


def change_script(old: Taskbar, new: Taskbar, look_name: str) -> str:
    """The script that turns the taskbar from old into new (only what differs)."""
    js = ["var p = c7Taskbar();", "if (p) {", "p.locked = false;"]
    if new.location != old.location:
        js.append(f"p.location = {json.dumps(new.location)};")
    if new.hiding != old.hiding:
        js.append(f"p.hiding = {json.dumps(new.hiding)};")
    if new.height != old.height:
        js.append(f"p.height = {int(new.height)};")
    if new.buttons != old.buttons:
        kind = "org.kde.plasma.icontasks" if new.buttons == "always" else "org.kde.plasma.taskmanager"
        js.append(f"var tm = c7TaskButtons(p, {json.dumps(kind)});")
        js.append("if (tm) {")
        js.append(f'tm.writeConfig("groupingStrategy", {0 if new.buttons == "never" else 1});')
        js.append(f'tm.writeConfig("onlyGroupWhenFull", {json.dumps(new.buttons == "full")});')
        if kind == "org.kde.plasma.taskmanager":
            # one line of text on each button, as in Windows 7
            js.append('tm.writeConfig("maxTextLines", 1);')
            if look_name == "classic":
                js.append('tm.writeConfig("taskMaxWidth", 0); tm.writeConfig("taskHoverEffect", false);')
        js.append("tm.reloadConfig(); }")
    if new.quicklaunch != old.quicklaunch and new.can_quicklaunch:
        if new.quicklaunch:
            js.append('var q = p.addWidget("org.kde.plasma.quicklaunch");')
            js.append('if (q) { var sm = p.widgets("org.classic7.startmenu").concat(p.widgets("org.kde.plasma.kicker"));')
            js.append("q.index = sm.length ? sm[0].index + 1 : 1;")
            js.append(f'q.currentConfigGroup = ["General"]; q.writeConfig("launcherUrls", {json.dumps(QUICK_LAUNCH_DEFAULT)});')
            js.append("q.reloadConfig(); }")
        else:
            js.append('p.widgets("org.kde.plasma.quicklaunch").forEach(function (q) { q.remove(); });')
    start_changes = {k: v for k, v in new.start.items() if old.start.get(k) != v}
    if start_changes:
        js.append('p.widgets("org.classic7.startmenu").forEach(function (w) { w.currentConfigGroup = ["General"];')
        for k, v in start_changes.items():
            js.append(f"w.writeConfig({json.dumps(k)}, {json.dumps(v)});")
        js.append("w.reloadConfig(); });")
    if new.peek != old.peek:
        js.append('p.widgets("org.classic7.showdesktop").forEach(function (w) { w.currentConfigGroup = ["General"]; '
                  f'w.writeConfig("peek", {json.dumps(new.peek)}); w.reloadConfig(); }});')
    if new.tray is not None and old.tray is not None and new.tray != old.tray:
        js.append('var tray = p.widgets("org.kde.plasma.systemtray");')
        js.append("if (tray.length) { var t = tray[0]; t.currentConfigGroup = [];")
        js.append('var id = t.readConfig("SystrayContainmentId"); var c = id ? desktopById(id) : null; var o = c || t;')
        js.append('o.currentConfigGroup = ["General"];')
        known = list(dict.fromkeys(new.tray.known + new.tray.extra))
        for key, value in (("shownItems", new.tray.shown), ("hiddenItems", new.tray.hidden),
                           ("extraItems", new.tray.extra), ("knownItems", known),
                           ("showAllItems", new.tray.show_all)):
            js.append(f"o.writeConfig({json.dumps(key)}, {json.dumps(value)});")
        js.append("o.reloadConfig(); }")
    js.append(f"p.locked = {json.dumps(new.locked)};")
    js.append("}")
    return backend.TASKBAR_LIB + "\n".join(js) + "\n"


def apply(old: Taskbar, new: Taskbar) -> bool:
    """Change the running taskbar. The taskbar height for small icons is also remembered for the
    Appearance settings (an Aero or Basic Apply keeps it)."""
    look_name = look()
    small = new.height < 40
    state = backend.State.load()
    if look_name != "classic" and state.small_icons != small:
        state.small_icons = small
        try:
            state.save()
        except OSError:
            pass
    if new == old:
        return True
    return evaluate(change_script(old, new, look_name)) is not None


# =============================================================================
# Notification area icons: names and pictures
# =============================================================================
PLASMOID_DIRS = [Path.home() / ".local/share/plasma/plasmoids", Path("/usr/share/plasma/plasmoids")]
PLUGIN_DIRS = [Path("/usr/lib64/qt6/plugins"), Path("/usr/lib/qt6/plugins")]
_applets: dict[str, dict] | None = None


def applets() -> dict[str, dict]:
    """Every installed Plasma applet's metadata by id: QML packages (metadata.json) and the ones
    built into libraries (plasma/applets/*.so, read with QPluginLoader without loading them)."""
    global _applets
    if _applets is not None:
        return _applets
    found: dict[str, dict] = {}
    for base in PLASMOID_DIRS:
        try:
            dirs = sorted(base.iterdir())
        except OSError:
            continue
        for d in dirs:
            try:
                meta = json.loads((d / "metadata.json").read_text())
            except (OSError, ValueError):
                continue
            found.setdefault(str(meta.get("KPlugin", {}).get("Id") or d.name), meta)
    try:
        from PySide6.QtCore import QLibraryInfo, QPluginLoader
        dirs = [Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))] + PLUGIN_DIRS
    except ImportError:
        QPluginLoader, dirs = None, []
    for base in dirs:
        for lib in sorted((base / "plasma/applets").glob("*.so")) if QPluginLoader else []:
            try:
                meta = QPluginLoader(str(lib)).metaData().get("MetaData") or {}
            except (RuntimeError, AttributeError):
                continue
            if isinstance(meta, dict) and meta.get("KPlugin"):
                found.setdefault(str(meta["KPlugin"].get("Id") or lib.stem), meta)
    _applets = found
    return found


def plasmoid_info(plugin: str) -> tuple[str, str] | None:
    """(name, icon) from an installed applet's metadata."""
    meta = applets().get(plugin)
    if meta is None:
        return None
    kp = meta.get("KPlugin", {})
    return str(kp.get("Name") or plugin), str(kp.get("Icon") or "preferences-desktop-notification")


def tray_plasmoids() -> list[str]:
    """Applets made for the notification area (the system icons that can be turned on or off)."""
    return [pid for pid, meta in applets().items() if str(meta.get("X-Plasma-NotificationArea")).lower() == "true"]


def with_behavior(tray: Tray, item: str, behavior: str) -> Tray:
    shown = [x for x in tray.shown if x != item]
    hidden = [x for x in tray.hidden if x != item]
    if behavior == SHOW:
        shown.append(item)
    elif behavior == HIDE:
        hidden.append(item)
    return replace(tray, shown=shown, hidden=hidden)


def behavior_of(tray: Tray, item: str) -> str:
    if item in tray.shown:
        return SHOW
    if item in tray.hidden:
        return HIDE
    return AUTO
