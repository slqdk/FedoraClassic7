"""Classic 7 Update: the steps behind the Update window and the classic7-update command.

One run does everything, in order:
  1. System     the newest Classic 7 image (bootc), staged for the next restart
  2. Apps       Flatpak apps and runtimes
  3. Settings   this account gets what changed in Classic 7 (look, taskbar, Start menu pins,
                shortcuts, program list), without undoing the user's own choices
After a restart into a new image, step 3 runs again by itself at login (--after-login), because
the new theme code and files only exist once the new image is running.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

HELPER = os.environ.get("CLASSIC7_UPDATE_HELPER", "/usr/libexec/classic7-update-system")
SHARE = Path(os.environ.get("CLASSIC7_SHARE", "/usr/share/classic7"))
BUILD_INFO = SHARE / "build-info.json"
CHANGES = SHARE / "changes.txt"
# What the newest published image contains: written by the build after each push (branch "published")
REPO = os.environ.get("CLASSIC7_REPO", "slqdk/FedoraClassic7")
PUBLISHED_URL = f"https://raw.githubusercontent.com/{REPO}/published/latest.json"
MAIN_CHANGES_URL = f"https://raw.githubusercontent.com/{REPO}/main/system_files/usr/share/classic7/changes.txt"
SKEL = Path(os.environ.get("CLASSIC7_SKEL", "/etc/skel"))
# Skeleton files whose missing entries are added to existing accounts (never overwriting)
SKEL_MERGE = [".config/kglobalshortcutsrc"]
# Programs added to the Start menu's pinned list after the first release, oldest first.
# Each is pinned once for existing accounts; unpinning it afterwards sticks.
PIN_ADDITIONS = ["classic7-write.desktop", "classic7-mail.desktop", "classic7-show.desktop"]

Log = Callable[[str], None]


# ---- versions --------------------------------------------------------------------------------
def build_info() -> dict:
    try:
        return json.loads(BUILD_INFO.read_text())
    except (OSError, ValueError):
        return {}


def current_build() -> str:
    """The Classic 7 build running now (UTC time of the image build), "" if unknown."""
    return str(build_info().get("build", ""))


def current_content() -> str:
    """Hash of Classic 7's own files in this image (Bazzite-only rebuilds keep it)."""
    return str(build_info().get("content", "")) or current_build()


def pretty_build(build: str) -> str:
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)", build or "")
    if not m:
        return build or "unknown"
    y, mo, d, h, mi = m.groups()
    return f"{int(d)}-{int(mo)}-{y} {h}:{mi} UTC"


# ---- per-account state -----------------------------------------------------------------------
def state_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "classic7" / "update.json"


@dataclass
class UpdateState:
    applied_build: str = ""        # the build whose settings this account has
    applied_content: str = ""      # ... and its Classic 7 content hash
    last_check: float = 0
    last_install: float = 0
    last_result: str = ""
    seen_pins: list[str] = field(default_factory=list)
    done_migrations: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "UpdateState":
        try:
            data = json.loads(state_file().read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self):
        f = state_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(asdict(self), indent=2) + "\n")


# ---- running commands ------------------------------------------------------------------------
def run_stream(cmd: list[str], log: Log, env: dict | None = None) -> int:
    """Run a command and pass each output line to log (progress lines ending in \\r too)."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env=env)
    except OSError as e:
        log(f"{cmd[0]}: {e}")
        return 127
    buf = b""
    last = ""
    while True:
        chunk = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(4096)
        if not chunk:
            break
        buf += chunk
        parts = re.split(rb"\r\n|\n|\r", buf)
        buf = parts.pop()
        for p in parts:
            line = _strip_ansi(p.decode("utf-8", "replace")).rstrip()
            if line and line != last:
                log(line)
                last = line
    if buf.strip():
        log(_strip_ansi(buf.decode("utf-8", "replace")).rstrip())
    return proc.wait()


def _strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07", "", s)


def system_cmd(action: str) -> list[str]:
    """The root helper, via pkexec (no password for the person at the computer, see
    org.classic7.update.policy) unless we already are root."""
    if os.geteuid() == 0:
        return [HELPER, action]
    return ["pkexec", HELPER, action]


def system_status() -> dict:
    """bootc's status as a dict ({} if it can't be read)."""
    try:
        out = subprocess.run(system_cmd("status"), capture_output=True, text=True, timeout=60).stdout
        return json.loads(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def _image(entry: dict | None) -> dict:
    return ((entry or {}).get("image") or {}) if isinstance(entry, dict) else {}


def staged_info(status: dict) -> dict:
    """{'version':..., 'timestamp':..., 'digest':...} for an update waiting for a restart, else {}."""
    st = (status.get("status") or {}).get("staged")
    img = _image(st)
    if not img:
        return {}
    return {"version": img.get("version") or "", "timestamp": img.get("timestamp") or "",
            "digest": img.get("imageDigest") or ""}


def booted_info(status: dict) -> dict:
    img = _image((status.get("status") or {}).get("booted"))
    ref = (img.get("image") or {}).get("image", "") if isinstance(img.get("image"), dict) else ""
    return {"version": img.get("version") or "", "timestamp": img.get("timestamp") or "",
            "digest": img.get("imageDigest") or "", "image": ref}


# ---- the steps -------------------------------------------------------------------------------
CHECK_NONE, CHECK_AVAILABLE, CHECK_STAGED, CHECK_ERROR = "none", "available", "staged", "error"


LAST_CHECK: dict = {}


def check(log: Log) -> str:
    """Is there a newer Classic 7? Downloads only the image description, not the update."""
    lines: list[str] = []

    def keep(line):
        lines.append(line)
        log(line)
    rc = run_stream(system_cmd("check"), keep)
    text = "\n".join(lines)
    m = re.search(r"(sha256:[0-9a-f]{64})", text)
    LAST_CHECK.clear()
    LAST_CHECK["digest"] = m.group(1) if m else ""
    staged = staged_info(system_status())
    if rc != 0:
        return CHECK_STAGED if staged else CHECK_ERROR
    if re.search(r"No changes|No update available", text, re.I):
        return CHECK_STAGED if staged else CHECK_NONE
    if staged and staged.get("digest") and staged["digest"] in text:
        return CHECK_STAGED
    return CHECK_AVAILABLE


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def upgrade_system(log: Log, progress: Callable[[float, str], None] | None = None) -> bool:
    """Download and stage the newest image. True when it worked (or nothing was needed).
    progress(fraction 0..1, text) gets bootc's progress when it reports it (--progress-fd)."""
    def line(text: str):
        if text.startswith("{") and '"type"' in text:
            try:
                ev = json.loads(text)
            except ValueError:
                log(text)
                return
            if progress is None:
                return
            t = ev.get("type")
            if t == "ProgressBytes" and ev.get("bytesTotal"):
                done, total = ev.get("bytes", 0), ev["bytesTotal"]
                progress(min(1.0, done / total), f"downloading {_gb(done)} of {_gb(total)}")
            elif t == "ProgressSteps" and ev.get("stepsTotal"):
                what = "preparing the new version" if "stag" in str(ev.get("task", "")) else \
                    str(ev.get("description") or ev.get("task") or "working")
                progress(min(1.0, ev.get("steps", 0) / ev["stepsTotal"]),
                         f"{what} ({ev.get('steps', 0)} of {ev['stepsTotal']})")
            return
        log(text)
    rc = run_stream(system_cmd("upgrade"), line)
    if rc == 126 or rc == 127:
        log("The update was not allowed (authentication cancelled or failed).")
    return rc == 0


def update_apps(log: Log) -> bool:
    if not shutil.which("flatpak"):
        return True
    rc = run_stream(["flatpak", "update", "-y", "--noninteractive"], log)
    if rc == 0:
        run_stream(["flatpak", "uninstall", "--unused", "-y", "--noninteractive"], log)
    return rc == 0


def app_updates() -> list[str]:
    """Flatpak apps and runtimes with an update waiting (user and system installations)."""
    if not shutil.which("flatpak"):
        return []
    try:
        out = subprocess.run(["flatpak", "remote-ls", "--updates", "--columns=application"],
                             capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [x for x in out.split() if x and x != "Application"]


def restart_needed() -> bool:
    return bool(staged_info(system_status()))


# ---- step 3: this account's Classic 7 settings -----------------------------------------------
def _ini_read(path: Path) -> dict[str, dict[str, str]]:
    groups: dict[str, dict[str, str]] = {}
    group = None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return groups
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith(";"):
            continue
        if s.startswith("[") and s.endswith("]"):
            group = s[1:-1]
            groups.setdefault(group, {})
        elif "=" in s and group is not None:
            k, v = s.split("=", 1)
            groups[group][k.strip()] = v
    return groups


def merge_skel(log: Log, home: Path | None = None) -> int:
    """Add entries that are new in /etc/skel to this account's files. Existing keys, which
    may be the user's own choices, are left alone. Returns the number of added keys."""
    home = home or Path.home()
    added = 0
    if not shutil.which("kwriteconfig6"):
        log("  kwriteconfig6 is missing")
        return 0
    for rel in SKEL_MERGE:
        src, dst = SKEL / rel, home / rel
        if not src.exists():
            continue
        have = _ini_read(dst)
        for group, entries in _ini_read(src).items():
            for key, value in entries.items():
                if key in have.get(group, {}):
                    continue
                gargs = []
                # "[services][classic7-run.desktop]" -> --group services --group classic7-run.desktop
                for g in re.findall(r"\[?([^\[\]]+)\]?", f"[{group}]"):
                    gargs += ["--group", g]
                subprocess.run(["kwriteconfig6", "--file", str(dst), *gargs, "--key", key, "--", value],
                               check=False)
                added += 1
                log(f"  {Path(rel).name}: added [{group}] {key}")
    return added


def _startmenu_defaults() -> list[str]:
    xml = Path("/usr/share/plasma/plasmoids/org.classic7.startmenu/contents/config/main.xml")
    try:
        m = re.search(r'name="favoriteApps".*?<default>([^<]*)</default>', xml.read_text(), re.S)
        return [x for x in m.group(1).split(",") if x] if m else []
    except OSError:
        return []


def pin_script(pins: list[str]) -> str:
    """Plasma script: add pins to the Classic 7 Start menu (after Command Prompt)."""
    return """
var add = %s;
panels().forEach(function (panel) {
    panel.widgets("org.classic7.startmenu").forEach(function (w) {
        w.currentConfigGroup = ["General"];
        var favs = w.readConfig("favoriteApps", %s);
        if (typeof favs === "string") favs = favs.split(",");
        favs = favs.filter(function (f) { return String(f).length > 0; });
        var changed = false;
        add.forEach(function (id) {
            if (favs.indexOf(id) !== -1) return;
            var at = favs.indexOf("classic7-prompt.desktop");
            favs.splice(at === -1 ? Math.min(2, favs.length) : at + 1, 0, id);
            changed = true;
        });
        if (changed) { w.writeConfig("favoriteApps", favs); w.reloadConfig(); }
    });
});
""" % (json.dumps(pins), json.dumps(_startmenu_defaults()))


def plasma_running() -> bool:
    return subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "plasmashell"],
                          capture_output=True).returncode == 0


# ---- one-time changes for existing accounts -------------------------------------------------
def _kwrite(file: str, groups: list[str], key: str, value: str) -> bool:
    if not shutil.which("kwriteconfig6"):
        return False
    g = []
    for x in groups:
        g += ["--group", x]
    return subprocess.run(["kwriteconfig6", "--file", file, *g, "--key", key, "--", value],
                          capture_output=True).returncode == 0


def _no_autolock(log: Log) -> bool:
    """Lock only with Win+L (like Windows), not after a few idle minutes or after sleep."""
    ok = _kwrite("kscreenlockerrc", ["Daemon"], "Autolock", "false")
    ok &= _kwrite("kscreenlockerrc", ["Daemon"], "LockOnResume", "false")
    subprocess.run(["dbus-send", "--session", "--type=method_call", "--dest=org.freedesktop.ScreenSaver",
                    "/ScreenSaver", "org.kde.screensaver.configure"], capture_output=True)
    log("  the screen no longer locks by itself (Win+L still locks)")
    return ok


def _read_kdeglobals_lnf() -> str:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kdeglobals"
    return _ini_read(cfg).get("KDE", {}).get("LookAndFeelPackage", "").strip()


def _no_dark_mode(log: Log) -> bool:
    """The Dark Mode switch swaps the Global Theme to Breeze (Dark) and back to Breeze, not
    Classic 7. Point both of its themes at Classic 7, and bring Classic 7 back if the switch
    already replaced it. The colour scheme itself is re-applied by the next step."""
    ok = _kwrite("kdeglobals", ["KDE"], "DefaultLightLookAndFeel", "org.classic7.desktop")
    ok &= _kwrite("kdeglobals", ["KDE"], "DefaultDarkLookAndFeel", "org.classic7.desktop")
    ok &= _kwrite("kdeglobals", ["KDE"], "AutomaticLookAndFeel", "false")
    current = _read_kdeglobals_lnf()
    if current.startswith("org.kde.breeze") and shutil.which("plasma-apply-lookandfeel"):
        subprocess.run(["plasma-apply-lookandfeel", "-a", "org.classic7.desktop"], capture_output=True, timeout=60)
        log(f"  Global Theme {current} -> Classic 7")
        # the desktop background back to a plain colour (the Appearance step sets the colour)
        subprocess.run(["dbus-send", "--session", "--dest=org.kde.plasmashell", "--type=method_call",
                        "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                        'string:desktops().forEach(function (d) { d.wallpaperPlugin = "org.kde.color"; });'],
                       capture_output=True, timeout=30)
    log("  Dark Mode can no longer switch away from Classic 7")
    return ok


def _breeze_icons(log: Log) -> bool:
    """Classic 7's standard icons are Breeze (the Chicago95 set was removed from the image)."""
    ok = _kwrite("kdeglobals", ["Icons"], "Theme", "breeze")
    for gtk in ("gtk-3.0", "gtk-4.0"):
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / gtk / "settings.ini"
        if cfg.exists():
            _kwrite(str(cfg), ["Settings"], "gtk-icon-theme-name", "breeze")
    if shutil.which("gsettings"):
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", "breeze"],
                       capture_output=True)
    changer = "/usr/libexec/plasma-changeicons"
    if Path(changer).exists():
        subprocess.run([changer, "breeze"], capture_output=True, timeout=60)
    log("  icons: Breeze")
    return ok


def _small_desktop_icons(log: Log) -> bool:
    """Desktop icons at 32 px, like Windows (Plasma's default is 64 px)."""
    r = subprocess.run(["dbus-send", "--session", "--dest=org.kde.plasmashell", "--type=method_call",
                        "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                        'string:desktops().forEach(function (d) { d.currentConfigGroup = ["General"]; '
                        'd.writeConfig("iconSize", 1); d.reloadConfig(); });'],
                       capture_output=True, timeout=30)
    log("  desktop icons: 32 px")
    return r.returncode == 0


def _no_splash(log: Log) -> bool:
    """No "Plasma made by KDE" splash screen at login."""
    ok = _kwrite("ksplashrc", ["KSplash"], "Engine", "none")
    ok &= _kwrite("ksplashrc", ["KSplash"], "Theme", "None")
    log("  login splash screen: off")
    return ok


def _appletsrc() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "plasma-org.kde.plasma.desktop-appletsrc"


def _tray_plugins() -> tuple[bool, set[str]]:
    """(a system tray exists, plugins running inside the system trays) from the saved layout."""
    try:
        text = _appletsrc().read_text(errors="replace")
    except OSError:
        return False, set()
    groups: dict[str, dict[str, str]] = {}
    cur = None
    for line in text.splitlines():
        if line.startswith("["):
            cur = line.strip()
            groups.setdefault(cur, {})
        elif cur and "=" in line:
            k, v = line.split("=", 1)
            groups[cur][k.strip()] = v.strip()
    trays = {v["SystrayContainmentId"] for v in groups.values() if v.get("SystrayContainmentId")}
    plugins = set()
    for name, kv in groups.items():
        m = re.match(r"^\[Containments\]\[(\d+)\]\[Applets\]\[\d+\]$", name)
        if m and m.group(1) in trays and kv.get("plugin"):
            plugins.add(kv["plugin"])
    return bool(trays), plugins


def _network_tray(log: Log) -> bool:
    """Tray: the Classic 7 network icon (IP address shown at once) instead of Plasma's.
    Done only when the saved layout shows Plasma's icon gone, so it is retried at the next
    login if Plasma wasn't ready."""
    snippet = SHARE / "tray-network.js"
    try:
        js = snippet.read_text()
    except OSError:
        return False
    js += '\npanels().forEach(function (p) { p.widgets("org.kde.plasma.systemtray").forEach(classic7Tray); });\n'
    for _ in range(30):                      # the tray is created a moment after login
        has_tray, _plugins = _tray_plugins()
        if has_tray:
            break
        time.sleep(1)
    r = subprocess.run(["dbus-send", "--session", "--dest=org.kde.plasmashell", "--type=method_call",
                        "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", "string:" + js],
                       capture_output=True, timeout=30)
    if r.returncode != 0:
        return False
    for _ in range(20):                      # Plasma saves its layout a few seconds later
        has_tray, plugins = _tray_plugins()
        if has_tray and "org.kde.plasma.networkmanagement" not in plugins:
            log("  network icon: Classic 7 (shows the IP address)")
            return True
        time.sleep(1)
    log("  network icon: Plasma's icon is still in the tray; trying again at the next login")
    return False


def _explorer_layout_2(log: Log) -> bool:
    """Explorer (Dolphin) like Windows 7: no menu bar, only the navigation pane on the left
    (no Folders/Information/Terminal panels), no Recent/Search For/Tags sections."""
    import classic7appearance as backend
    res = backend.explorer_layout()
    log("  Explorer: Windows 7 layout (old files kept as .bak)")
    return res.ok


def _no_type_to_search(log: Log) -> bool:
    """Typing on the desktop selects the icon starting with that letter, like Windows,
    instead of opening KRunner's search bar (the desktop's "useTypeAhead" setting)."""
    r = subprocess.run(["dbus-send", "--session", "--dest=org.kde.plasmashell", "--type=method_call",
                        "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript",
                        'string:desktops().forEach(function (d) { d.currentConfigGroup = ["General"]; '
                        'd.writeConfig("useTypeAhead", true); d.reloadConfig(); });'],
                       capture_output=True, timeout=30)
    log("  desktop: typing selects icons (no search bar)")
    return r.returncode == 0


def _show_desktop_button(log: Log) -> bool:
    """The narrow Show desktop button at the right end of the taskbar, like Windows 7."""
    js = ('panels().forEach(function (p) {'
          ' if (p.widgets("org.kde.plasma.digitalclock").length > 0'
          ' && p.widgets("org.classic7.showdesktop").length === 0) { p.addWidget("org.classic7.showdesktop"); }'
          '});')
    r = subprocess.run(["dbus-send", "--session", "--dest=org.kde.plasmashell", "--type=method_call",
                        "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", "string:" + js],
                       capture_output=True, timeout=30)
    log("  taskbar: Show desktop button at the right end")
    return r.returncode == 0


META, KEY_UP, KEY_DOWN = 0x10000000, 0x01000013, 0x01000015
WIN7_KEYS = [  # (action, its name in the shortcut settings, keys)
    ("Window Quick Tile Top", "Quick Tile Window to the Top", []),
    ("Window Quick Tile Bottom", "Quick Tile Window to the Bottom", []),
    ("Classic7 Maximize", "Classic 7: Maximize the window (Win+Up)", [META | KEY_UP]),
    ("Classic7 Restore or Minimize", "Classic 7: Restore, or minimize (Win+Down)", [META | KEY_DOWN]),
]


def _kglobalaccel(method: str, action: str, friendly: str, keys: list[int] | None = None) -> str | None:
    argv = ["busctl", "--user", "call", "org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel",
            method, "as" + ("ai" if keys is not None else ""), "4", "kwin", action, "KWin", friendly]
    if keys is not None:
        argv += [str(len(keys))] + [str(k) for k in keys]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _win7_window_keys(log: Log) -> bool:
    """Win+Up maximizes and Win+Down restores or minimizes, like Windows 7 (KWin's default
    is quick-tiling to the top/bottom half). Needs the Classic 7 KWin script to be running,
    so it is tried again at the next login if it wasn't."""
    if not shutil.which("busctl"):
        return False
    for action, friendly, keys in WIN7_KEYS:
        _kglobalaccel("setForeignShortcut", action, friendly, keys)
    for action, friendly, keys in WIN7_KEYS:
        got = _kglobalaccel("shortcut", action, friendly)
        if got is None or (keys and str(keys[0]) not in got.split()):
            log(f"  {action}: not set yet (trying again at the next login)")
            return False
    log("  Win+Up maximizes, Win+Down restores or minimizes, Win+Home minimizes the other windows")
    return True


# (id, function) - each runs once per account, in this order. Add new ones at the end.
MIGRATIONS: list[tuple[str, Callable[[Log], bool]]] = [
    ("2026-10-12-no-autolock", _no_autolock),
    ("2026-10-12-no-dark-mode", _no_dark_mode),
    ("2026-10-12-breeze-icons", _breeze_icons),
    ("2026-10-12-small-desktop-icons", _small_desktop_icons),
    ("2026-10-12-no-splash", _no_splash),
    ("2026-10-12-network-tray", lambda log: True),          # replaced by the one below
    ("2026-10-12-network-tray-2", _network_tray),
    ("2026-10-12-explorer-2", _explorer_layout_2),
    ("2026-10-12-no-type-to-search", _no_type_to_search),
    ("2026-10-13-show-desktop-button", _show_desktop_button),
    ("2026-10-13-win7-window-keys", _win7_window_keys),
]


def run_migrations(log: Log, state: "UpdateState") -> list[str]:
    problems = []
    for mid, fn in MIGRATIONS:
        if mid in state.done_migrations:
            continue
        try:
            if fn(log):
                state.done_migrations.append(mid)
            else:
                problems.append(f"could not apply {mid}")
        except Exception as e:  # noqa: BLE001
            problems.append(f"{mid}: {e}")
    return problems


# ---- keyboard layout of the login screen ----------------------------------------------------
def session_keyboard() -> dict | None:
    """The layouts this account uses in Plasma (System Settings > Keyboard), first = primary."""
    cfg = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kxkbrc"
    kx = _ini_read(cfg).get("Layout", {})
    if kx.get("Use", "false").strip().lower() != "true" or not kx.get("LayoutList", "").strip():
        return None
    return {"layout": kx.get("LayoutList", "").strip(), "variant": _no_empty(kx.get("VariantList", "")),
            "model": kx.get("Model", "").strip(), "options": kx.get("Options", "").strip()}


def system_keyboard() -> dict:
    """The system layout (systemd-localed), which the login screen uses."""
    out = {"layout": "", "variant": "", "model": "", "options": ""}
    try:
        text = subprocess.run(["localectl", "status"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for line in text.splitlines():
        m = re.match(r"\s*X11 (Layout|Variant|Model|Options):\s*(.*)", line)
        if m:
            out[m.group(1).lower()] = m.group(2).strip()
    out["variant"] = _no_empty(out["variant"])
    return out


def _no_empty(v: str) -> str:
    """"," (no variant for two layouts) means the same as ""."""
    v = v.strip()
    return "" if not v.replace(",", "").strip() else v


def sync_keyboard(log: Log) -> bool:
    """Give the login screen the same keyboard layout(s) as this account's desktop.
    Allowed without a password for administrators at the computer (classic7.rules)."""
    want = session_keyboard()
    if want is None or not shutil.which("localectl"):
        return True
    have = system_keyboard()
    if (have["layout"], have["variant"]) == (want["layout"], want["variant"]):
        return True
    model = want["model"] or have["model"]
    options = want["options"] or have["options"]
    r = subprocess.run(["localectl", "--no-ask-password", "set-x11-keymap", want["layout"], model,
                        want["variant"], options], capture_output=True, text=True)
    if r.returncode == 0:
        log(f"  login screen keyboard: {have['layout'] or 'us'} -> {want['layout']}")
        return True
    log(f"  could not set the login screen keyboard: {(r.stderr or r.stdout).strip()[:200]}")
    return False


def refresh_account(log: Log) -> list[str]:
    """Give this account the current Classic 7 settings. Returns problems (empty = all fine)."""
    problems: list[str] = []
    state = UpdateState.load()

    log("Updating the program list")
    if shutil.which("kbuildsycoca6"):
        subprocess.run(["kbuildsycoca6"], capture_output=True, check=False)
    if shutil.which("update-desktop-database"):
        apps = Path.home() / ".local/share/applications"
        if apps.is_dir():
            subprocess.run(["update-desktop-database", str(apps)], capture_output=True, check=False)

    log("Keyboard layout of the login screen")
    if not sync_keyboard(log):
        problems.append("the login screen keyboard layout could not be set")

    log("Adding new keyboard shortcuts")
    if merge_skel(log) == 0:
        log("  nothing new")

    gui = plasma_running()
    if gui:
        log("One-time changes for this account")
        problems += run_migrations(log, state)

    log("Applying the Classic 7 look (colours, window borders, taskbar, Start button)")
    if gui:
        try:
            import classic7appearance as backend
            res = backend.apply(backend.State.load().palette)
            problems += [n for n in res.notes if not n.startswith("Restart open GTK apps")]
        except Exception as e:  # noqa: BLE001 - report, keep going with the other steps
            problems.append(f"Appearance: {e}")
    else:
        log("  skipped: the desktop is not running (it is done at the next login)")

    new_pins = [p for p in PIN_ADDITIONS if p not in state.seen_pins]
    if new_pins:
        if gui:
            log("Pinning new programs to the Start menu: " + ", ".join(p.removesuffix(".desktop") for p in new_pins))
            try:
                import classic7appearance as backend
                run = backend.Runner()
                backend.run_plasma_script(pin_script(new_pins), run)
                if run.failures:
                    problems += run.failures
                else:
                    state.seen_pins += new_pins
            except Exception as e:  # noqa: BLE001
                problems.append(f"Start menu: {e}")
    if Path("/usr/libexec/classic7-first-login").exists():
        subprocess.run(["/usr/libexec/classic7-first-login"], check=False)

    if gui and not problems:
        state.applied_build = current_build()
        state.applied_content = current_content()
    state.save()
    for p in problems:
        log(f"Problem: {p}")
    return problems


def needs_refresh() -> bool:
    """True when Classic 7 itself changed since this account's settings were last brought up to date."""
    return current_content() != UpdateState.load().applied_content


# ---- what's new ------------------------------------------------------------------------------
@dataclass
class Change:
    date: str           # YYYY-MM-DD
    title: str
    items: list[str]


def changes() -> list[Change]:
    """Entries of /usr/share/classic7/changes.txt, newest first:
        ## 2026-10-12  Title
        - item"""
    try:
        return parse_changes(CHANGES.read_text())
    except OSError:
        return []


def parse_changes(text: str) -> list[Change]:
    out: list[Change] = []
    for line in text.splitlines():
        m = re.match(r"##\s*(\d{4}-\d\d-\d\d)\s*(.*)", line)
        if m:
            out.append(Change(m.group(1), m.group(2).strip(), []))
        elif out and line.strip().startswith(("-", "*")):
            out[-1].items.append(line.strip()[1:].strip())
        elif out and line.startswith("  ") and out[-1].items:
            out[-1].items[-1] += " " + line.strip()
    return out


def changes_since(build: str) -> list[Change]:
    day = (build or "")[:10]
    return [c for c in changes() if not day or c.date >= day]


def _fetch(url: str, timeout: float = 15) -> bytes | None:
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "classic7-update", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (fixed https URLs)
            return r.read(2_000_000)
    except Exception:   # noqa: BLE001 - no network, no file yet: the caller says so
        return None


def published() -> dict:
    """What the newest published image is: {"digest", "sha", "built", "changes"} ({} if unknown)."""
    data = _fetch(PUBLISHED_URL)
    if not data:
        return {}
    try:
        info = json.loads(data)
    except ValueError:
        return {}
    return info if isinstance(info, dict) else {}


def pending_changes(log: Log | None = None) -> tuple[list[Change], dict]:
    """Changelog entries in the newest published Classic 7 that this computer doesn't have yet,
    and what is known about that image."""
    info = published()
    text = info.get("changes") if info else None
    if not text:
        raw = _fetch(MAIN_CHANGES_URL)
        text = raw.decode("utf-8", "replace") if raw else ""
        info = dict(info or {}, source="main")
    if not text:
        if log:
            log("The list of changes could not be downloaded.")
        return [], info
    have = {(c.date, c.title) for c in changes()}
    new = [c for c in parse_changes(text) if (c.date, c.title) not in have]
    if log:
        log(f"New in Classic 7: {len(new)} change entr{'y' if len(new) == 1 else 'ies'}")
    return new, info


def now() -> float:
    return time.time()
