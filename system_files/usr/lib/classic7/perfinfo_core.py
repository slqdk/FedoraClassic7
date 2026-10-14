"""Performance Information and Tools (no GUI code): what someone helping with a problem needs to
know about this computer, the performance problems Classic 7 can see, and the report that puts
both together. The assessment (the scores) is in perfinfo_assess.py.

Nothing here needs root or asks for a password. The report leaves out passwords, keys, serial
numbers and network hardware (MAC) addresses.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import sysinfo as si

HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or HOME / ".cache")
SCORES = DATA / "classic7" / "perfinfo.json"

# OpenGL drawn by the processor (Mesa's software renderers, also behind virgl)
SOFTWARE_GL = re.compile(r"llvmpipe|softpipe|swrast|lavapipe|software rasteri[sz]er", re.I)


def run(cmd: list[str], timeout: float = 10, env: dict | None = None) -> tuple[int, str]:
    """(exit code, output) of a command; (-1, "") when it can't run."""
    if not shutil.which(cmd[0]):
        return -1, ""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           env=env)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def read(path: Path | str, default: str = "") -> str:
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return default


def ini_group(path: Path, group: str) -> dict[str, str]:
    """One group of a KDE-style config file (the last value of a key wins)."""
    cur, out = None, {}
    for line in read(path).splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            cur = line[1:-1]
        elif cur == group and "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def ini_value(path: Path, group: str, key: str) -> str:
    """One value from a KDE-style config file, "" if not set."""
    return ini_group(path, group).get(key, "")


# environment variables that change how programs draw (names only from these families)
_GFX_ENV = re.compile(r"^(QT_QUICK_BACKEND|QSG_\w+|QT_QPA_PLATFORM\w*|QT_SCALE_FACTOR\w*|QT_SCREEN_SCALE_FACTORS|"
                      r"QT_ENABLE_HIGHDPI_SCALING|KWIN_\w+|LIBGL_\w+|MESA_\w+|GALLIUM_\w+|__GLX_VENDOR_LIBRARY_NAME|"
                      r"__EGL_VENDOR_LIBRARY_\w+|__NV_\w+|VK_\w+|DRI_PRIME|GDK_BACKEND|SDL_VIDEODRIVER|"
                      r"XCURSOR_SIZE|PLASMA_\w+|KDE_\w+)$")


def graphics_environment() -> list[str]:
    return sorted(f"{k}={v[:120]}" for k, v in os.environ.items()
                  if _GFX_ENV.match(k) and not re.search(r"TOKEN|KEY|PASS|SECRET|COOKIE", k))


def human_bytes(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("bytes", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


# =============================================================================================
# KWin and the graphics stack
# =============================================================================================
def kwin_support_info() -> str:
    """KWin's own description of how it draws (compositing type, OpenGL renderer, effects)."""
    try:
        import dbus
        bus = dbus.SessionBus()
        kwin = dbus.Interface(bus.get_object("org.kde.KWin", "/KWin"), "org.kde.KWin")
        return str(kwin.supportInformation())
    except Exception:  # noqa: BLE001 - no session bus, or KWin isn't running
        code, out = run(["dbus-send", "--session", "--print-reply=literal", "--dest=org.kde.KWin", "/KWin",
                         "org.kde.KWin.supportInformation"], 8)
        return out if code == 0 else ""


def kwin_loaded_effects() -> list[str]:
    try:
        import dbus
        bus = dbus.SessionBus()
        props = dbus.Interface(bus.get_object("org.kde.KWin", "/Effects"), "org.freedesktop.DBus.Properties")
        return sorted(str(e) for e in props.Get("org.kde.kwin.Effects", "loadedEffects"))
    except Exception:  # noqa: BLE001
        return []


def support_value(info: str, key: str) -> str:
    for line in info.splitlines():
        k, sep, v = line.strip().partition(":")
        if sep and k.strip() == key:
            return v.strip()
    return ""


@dataclass
class Graphics:
    compositing: str = ""          # "OpenGL", "QPainter", "" (unknown)
    vendor: str = ""
    renderer: str = ""
    version: str = ""
    driver: str = ""
    software: bool = False         # OpenGL drawn by the processor, or no OpenGL at all
    known: bool = False            # KWin answered
    effects: list[str] = field(default_factory=list)
    adapters: list[str] = field(default_factory=list)   # "AMD Radeon RX 7900 XTX (amdgpu)"
    vulkan: list[str] = field(default_factory=list)


def graphics() -> Graphics:
    g = Graphics()
    info = kwin_support_info()
    g.compositing = support_value(info, "Compositing Type")
    g.vendor = support_value(info, "OpenGL vendor string")
    g.renderer = support_value(info, "OpenGL renderer string")
    g.version = support_value(info, "OpenGL version string")
    g.driver = support_value(info, "Driver")
    g.software = bool(SOFTWARE_GL.search(g.renderer)) or g.compositing.lower() == "qpainter"
    g.known = bool(g.compositing)
    g.effects = kwin_loaded_effects()
    for d in si.pci_devices():
        if d.category == "Display adapters":
            g.adapters.append(f"{d.name} ({d.driver or 'no driver'})")
    code, out = run(["vulkaninfo", "--summary"], 15)
    if code == 0:
        g.vulkan = [ln.split("=", 1)[1].strip() for ln in out.splitlines() if ln.strip().startswith("deviceName")]
    return g


# =============================================================================================
# Displays
# =============================================================================================
@dataclass
class Display:
    name: str
    monitor: str = ""
    enabled: bool = True
    width: int = 0
    height: int = 0
    refresh: float = 0.0
    best_refresh: float = 0.0      # the highest refresh rate this monitor offers at this size
    scale: float = 1.0
    vrr: str = ""
    hdr: str = ""
    primary: bool = False


def displays() -> list[Display]:
    code, out = run(["kscreen-doctor", "-j"], 10)
    if code != 0:
        return []
    try:
        outputs = json.loads(out).get("outputs", [])
    except (ValueError, AttributeError):
        return []
    names = {}
    for m in si.monitors():
        names[m.location] = f"{m.manufacturer} {m.name}".strip()
    res = []
    for o in outputs:
        if not o.get("connected"):
            continue
        d = Display(str(o.get("name", "?")), names.get(str(o.get("name", "")), ""), bool(o.get("enabled")))
        modes = o.get("modes") or []
        cur = next((m for m in modes if str(m.get("id")) == str(o.get("currentModeId"))), None)
        if cur:
            size = cur.get("size") or {}
            d.width, d.height = int(size.get("width", 0)), int(size.get("height", 0))
            d.refresh = float(cur.get("refreshRate", 0) or 0)
            same = [float(m.get("refreshRate", 0) or 0) for m in modes
                    if (m.get("size") or {}) == size]
            d.best_refresh = max(same or [d.refresh])
        d.scale = float(o.get("scale", 1) or 1)
        vrr = o.get("vrrPolicy")
        d.vrr = {0: "never", 1: "always", 2: "automatic"}.get(vrr, str(vrr)) if vrr is not None else ""
        hdr = o.get("hdr")
        d.hdr = ("on" if hdr else "off") if isinstance(hdr, bool) else ""
        d.primary = o.get("priority") == 1
        res.append(d)
    return res


# =============================================================================================
# Processor, memory, disks
# =============================================================================================
def cpu_flags() -> set[str]:
    for line in read("/proc/cpuinfo").splitlines():
        if line.startswith("flags"):
            return set(line.split(":", 1)[1].split())
    return set()


def virtualization() -> str:
    """'kvm', 'vmware', 'oracle', ... or '' on real hardware."""
    code, out = run(["systemd-detect-virt", "--vm"], 5)
    out = out.strip()
    return "" if code != 0 or out in ("", "none") else out


def meminfo() -> dict[str, int]:
    out = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        parts = v.split()
        if parts and parts[0].isdigit():
            out[k] = int(parts[0]) * 1024
    return out


def power_profile() -> str:
    code, out = run(["powerprofilesctl", "get"], 5)
    if code == 0 and out.strip():
        return out.strip()
    code, out = run(["tuned-adm", "active"], 5)
    if code == 0 and ":" in out:
        return "tuned " + out.split(":", 1)[1].strip()
    return ""


@dataclass
class Mount:
    target: str
    source: str
    fstype: str
    size: int
    free: int


def mounts() -> list[Mount]:
    code, out = run(["findmnt", "-J", "-b", "-o", "TARGET,SOURCE,FSTYPE,SIZE,AVAIL", "--real"], 10)
    if code != 0:
        return []
    try:
        rows = json.loads(out).get("filesystems", [])
    except (ValueError, AttributeError):
        return []
    flat, stack = [], list(rows)
    while stack:
        r = stack.pop(0)
        flat.append(r)
        stack[0:0] = r.get("children") or []
    # the home folder, then /var and /, then the rest: the first of the same disk is the one shown
    order = {"/var/home": 0, "/home": 0, "/var": 1, "/": 2}
    flat.sort(key=lambda r: order.get(str(r.get("target") or ""), 3))
    res, seen = [], set()
    for r in flat:
        t = str(r.get("target") or "")
        if not t or t in ("/sysroot", "/etc", "/usr", "/opt") or \
                t.startswith(("/boot", "/sysroot/", "/var/lib/containers", "/run/", "/snap")) or \
                r.get("fstype") in ("composefs", "overlay", "squashfs", "iso9660"):
            continue
        size, free = int(r.get("size") or 0), int(r.get("avail") or 0)
        key = (str(r.get("source") or "").split("[")[0], size)
        if size <= 0 or key in seen:
            continue
        seen.add(key)
        res.append(Mount(t, str(r.get("source") or ""), str(r.get("fstype") or ""), size, free))
    return res


def block_devices() -> list[str]:
    code, out = run(["lsblk", "-J", "-d", "-b", "-o", "NAME,MODEL,SIZE,ROTA,TRAN,TYPE"], 10)
    if code != 0:
        return []
    try:
        rows = json.loads(out).get("blockdevices", [])
    except (ValueError, AttributeError):
        return []
    res = []
    for d in rows:
        if d.get("type") != "disk" or str(d.get("name", "")).startswith(("zram", "loop", "ram")):
            continue
        kind = "hard disk" if d.get("rota") in (True, "1", 1) else "SSD"
        tran = (d.get("tran") or "").upper()
        res.append(f"{d.get('name')}: {(d.get('model') or '').strip() or 'disk'}, "
                   f"{human_bytes(int(d.get('size') or 0))}, {kind}{', ' + tran if tran else ''}")
    return res


# =============================================================================================
# Health: failed services, crashes, errors, busy programs
# =============================================================================================
def failed_units(user: bool) -> list[str]:
    cmd = ["systemctl"] + (["--user"] if user else []) + ["--failed", "--no-legend", "--plain", "--no-pager"]
    code, out = run(cmd, 10)
    return [ln.split()[0] for ln in out.splitlines() if ln.strip()] if code == 0 else []


def crashes(days: int = 7) -> list[str]:
    code, out = run(["coredumpctl", "--no-pager", "--json=short", f"--since=-{days}d", "list"], 15)
    if code != 0 or not out.strip():
        return []
    try:
        rows = json.loads(out)
    except ValueError:
        return []
    res = []
    for r in rows if isinstance(rows, list) else []:
        t = r.get("time")
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(t / 1e6)) if isinstance(t, (int, float)) else ""
        res.append(f"{when} {os.path.basename(str(r.get('exe') or r.get('comm') or '?'))} "
                   f"(signal {r.get('sig', '?')})".strip())
    return res[-20:]


def journal_errors(lines: int = 40) -> list[str]:
    """This boot's error messages (the system's, if this account may read them, and its own)."""
    code, out = run(["journalctl", "-b", "-p", "err", "--no-pager", "-o", "short-iso", "-q", "-n", "400"], 20)
    if code != 0:
        return []
    res, last = [], None
    for ln in out.splitlines():
        # the same message over and over only once
        msg = re.sub(r"^\S+\s+\S+\s+", "", ln)
        msg_key = re.sub(r"\[\d+\]", "", msg)
        if msg_key == last:
            continue
        last = msg_key
        res.append(ln[:300])
    return res[-lines:]


def classic7_log(lines: int = 30) -> list[str]:
    text = read(CACHE / "classic7" / "appearance.log")
    return text.splitlines()[-lines:] if text else []


def classic7_unit_errors() -> list[str]:
    code, out = run(["journalctl", "--user", "-b", "-p", "warning", "--no-pager", "-o", "short-iso", "-q", "-n", "60",
                     "-u", "classic7-sessiond", "-u", "classic7-tray-fix", "-u", "classic7-login-screen"], 15)
    return [ln[:300] for ln in out.splitlines()][-30:] if code == 0 else []


def remote_desktop_log(lines: int = 25) -> list[str]:
    """KRdp's own messages this boot (encoder, connections, logons)."""
    code, out = run(["journalctl", "--user", "-b", "--no-pager", "-o", "short-iso", "-q", "-n", str(lines),
                     "-u", "app-org.kde.krdpserver.service"], 15)
    return [ln[:300] for ln in out.splitlines()] if code == 0 else []


def busy_programs(seconds: float = 2.0, top: int = 6) -> tuple[float, list[str], list[str]]:
    """(the processor's use in %, the programs using most of it, the programs using most memory)."""
    def cpu_total():
        parts = read("/proc/stat").splitlines()[0].split()[1:]
        vals = [int(x) for x in parts]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return sum(vals), idle

    def procs():
        res = {}
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                st = Path(f"/proc/{pid}/stat").read_text()
                comm = st[st.index("(") + 1:st.rindex(")")]
                f = st[st.rindex(")") + 2:].split()
                res[pid] = (comm, int(f[11]) + int(f[12]), int(f[21]) * os.sysconf("SC_PAGE_SIZE"))
            except (OSError, ValueError, IndexError):
                pass
        return res

    t0, i0 = cpu_total()
    p0 = procs()
    time.sleep(seconds)
    t1, i1 = cpu_total()
    p1 = procs()
    busy = 100.0 * (1 - (i1 - i0) / max(1, t1 - t0))
    hz = os.sysconf("SC_CLK_TCK")
    use = []
    for pid, (comm, ticks, rss) in p1.items():
        if pid in p0:
            pct = (ticks - p0[pid][1]) / hz / seconds * 100
            if pct >= 1:
                use.append((pct, f"{comm} {pct:.0f}%"))
    use.sort(reverse=True)
    mem = sorted(((rss, f"{comm} ({human_bytes(rss)})") for comm, _t, rss in p1.values()), reverse=True)
    names = []
    for _r, text in mem:
        if text not in names:
            names.append(text)
    return busy, [t for _p, t in use[:top]], names[:top]


# =============================================================================================
# Classic 7's own state
# =============================================================================================
def deployments() -> dict:
    """The booted image, an update waiting for a restart, and the previous version (rpm-ostree)."""
    code, out = run(["rpm-ostree", "status", "--json"], 30)
    if code != 0:
        return {}
    try:
        deps = json.loads(out).get("deployments", [])
    except (ValueError, AttributeError):
        return {}
    res = {}
    for d in deps:
        role = "booted" if d.get("booted") else "staged" if d.get("staged") else "previous"
        if role in res:
            continue
        digest = str(d.get("container-image-reference-digest") or "")
        when = d.get("timestamp")
        res[role] = {
            "image": str(d.get("container-image-reference") or d.get("origin") or ""),
            "digest": digest.split(":")[-1][:16] if digest else "",
            "version": str(d.get("version") or ""),
            "date": time.strftime("%Y-%m-%d %H:%M", time.localtime(when)) if isinstance(when, (int, float)) else "",
            "layered": ", ".join(d.get("requested-packages") or []),
            "pinned": bool(d.get("pinned")),
        }
    return res


def appearance() -> dict:
    try:
        return json.loads(read(CONFIG / "classic7" / "appearance.json") or "{}")
    except ValueError:
        return {}


def versions() -> list[tuple[str, str]]:
    pkgs = ["plasma-workspace", "kwin", "qt6-qtbase", "mesa-dri-drivers", "python3", "python3-pyside6", "krdp",
            "freerdp-libs", "kvantum", "sddm", "steam", "gamemode"]
    code, out = run(["rpm", "-q", "--qf", "%{NAME} %{VERSION}-%{RELEASE}\\n", *pkgs], 15)
    res = []
    for ln in out.splitlines():
        if " " in ln and "not installed" not in ln:
            name, _, ver = ln.partition(" ")
            res.append((name, ver))
    return res


def startup() -> tuple[str, float, list[str]]:
    """(how long the last start took, seconds until the desktop could start, the slowest services)."""
    code, out = run(["systemd-analyze", "time", "--no-pager"], 15)
    text = " ".join(out.split()) if code == 0 else ""
    m = re.search(r"graphical\.target reached after ([\dhmin. s]+?) in userspace", text)
    secs = _duration(m.group(1)) if m else 0.0
    code, out = run(["systemd-analyze", "blame", "--no-pager"], 15)
    slow = [" ".join(ln.split()) for ln in out.splitlines()[:8]] if code == 0 else []
    return text, secs, slow


def _duration(text: str) -> float:
    """'1min 3.200s' -> 63.2"""
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)\s*(h|min|ms|s)", text):
        total += float(num) * {"h": 3600, "min": 60, "s": 1, "ms": 0.001}[unit]
    return total


def flatpaks() -> list[str]:
    code, out = run(["flatpak", "list", "--app", "--columns=application,version"], 15)
    return [" ".join(ln.split()) for ln in out.splitlines() if ln.strip()] if code == 0 else []


def remote_desktop() -> str:
    try:
        import remote_server as rs
        st = rs.state()
        return (f"{'on' if st.get('enabled') else 'off'}, server {'running' if st.get('active') else 'not running'}, "
                f"port {st.get('port')}, {'this account' if st.get('system_user') else 'Remote Desktop users'}"
                f"{', without anyone logged on (automatic login)' if st.get('unattended') else ''}")
    except Exception:  # noqa: BLE001
        code, out = run(["pgrep", "-u", str(os.getuid()), "-x", "krdpserver"], 3)
        return f"server running: {'yes' if code == 0 and out.strip() else 'no'}"


# =============================================================================================
# The facts, by section
# =============================================================================================
@dataclass
class Facts:
    sections: list[tuple[str, list[tuple[str, str]]]] = field(default_factory=list)
    graphics: Graphics = field(default_factory=Graphics)
    displays: list[Display] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    virt: str = ""
    mem: dict[str, int] = field(default_factory=dict)
    mounts: list[Mount] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    crashes: list[str] = field(default_factory=list)
    power: str = ""
    deploy: dict = field(default_factory=dict)
    look: dict = field(default_factory=dict)
    busy: float = 0.0
    boot_secs: float = 0.0
    boot_slow: list[str] = field(default_factory=list)


def collect(progress=lambda _text: None) -> Facts:
    """Everything the report shows. Takes a few seconds (it watches the processor for two)."""
    f = Facts()
    S = f.sections

    progress("Classic 7")
    rel = si.os_release()
    build = {}
    try:
        build = json.loads(read("/usr/share/classic7/build-info.json") or "{}")
    except ValueError:
        pass
    f.deploy = deployments()
    f.look = appearance()
    rows = [("Classic 7 build", f"{build.get('build', '?')} (content {build.get('content', '?')})"),
            ("Based on", f"{rel.get('PRETTY_NAME', '?')} {build.get('base', '')}".strip())]
    for role, label in (("booted", "Running image"), ("staged", "Downloaded, starts after a restart"),
                        ("previous", "Previous version (rollback)")):
        d = f.deploy.get(role)
        if d:
            rows.append((label, f"{d['image']} {d['version']} {d['date']} digest {d['digest']}".strip()
                         + (f"; added packages: {d['layered']}" if d.get("layered") else "")))
    try:
        import update_core as uc
        st = uc.UpdateState.load()
        rows.append(("This account's Classic 7 settings",
                     "up to date" if not uc.needs_refresh() else f"from an older version ({st.applied_build or 'never'})"))
        if st.last_check:
            rows.append(("Last looked for updates", time.strftime("%Y-%m-%d %H:%M", time.localtime(st.last_check))))
    except Exception:  # noqa: BLE001 - optional
        pass
    look = f.look
    glass = look.get("glass") or {}
    pal = look.get("palette") or {}
    rows += [("Look", f"{look.get('look', 'classic')}"
                      + (f", glass {glass.get('name', '')} {'see-through' if glass.get('transparency') else 'opaque'}"
                         if look.get("look") == "aero" else "")
                      + (", drawn solid (no blur here)" if look.get("solid") else "")),
             ("Classic colour scheme / font size", f"{pal.get('name', '?')} / {pal.get('font_size', look.get('font_size', '?'))}"),
             ("Window borders", f"{ini_value(CONFIG / 'kwinrc', 'org.kde.kdecoration2', 'library')} "
                                f"{ini_value(CONFIG / 'kwinrc', 'org.kde.kdecoration2', 'theme')}".strip() or "default"),
             ("Program controls", f"{ini_value(CONFIG / 'kdeglobals', 'KDE', 'widgetStyle') or 'default'}"
                                  f" (Kvantum theme {ini_value(CONFIG / 'Kvantum' / 'kvantum.kvconfig', 'General', 'theme') or '-'})"),
             ("Remote Desktop", remote_desktop())]
    S.append(("Classic 7", rows))

    progress("Computer")
    f.virt = virtualization()
    maker, model = si.manufacturer_model()
    host, _pretty = si.computer_name()
    up = float((read("/proc/uptime") or "0").split()[0])
    rows = [("Computer", f"{maker} {model}".strip() or "?"),
            ("Computer name", host),
            ("Virtual machine", f.virt or "no (real hardware)"),
            ("Kernel", f"{platform.release()} ({platform.machine()})"),
            ("Kernel options", read("/proc/cmdline")[:400]),
            ("Running for", f"{int(up // 86400)} days {int(up % 86400 // 3600)} h {int(up % 3600 // 60)} min"),
            ("Session", f"{os.environ.get('XDG_SESSION_TYPE', '?')} {os.environ.get('XDG_CURRENT_DESKTOP', '')}".strip()),
            ("Time zone", read("/etc/timezone") or (os.path.realpath("/etc/localtime").split("zoneinfo/")[-1]))]
    code, out = run(["localectl", "status"], 5)
    if code == 0:
        for ln in out.splitlines():
            k, _, v = ln.strip().partition(":")
            if k in ("System Locale", "VC Keymap", "X11 Layout", "X11 Variant"):
                rows.append((k, v.strip()))
    rows += [(name, ver) for name, ver in versions()]
    apps = flatpaks()
    rows.append(("Programs from Flathub", f"{len(apps)}: " + ", ".join(apps) if apps else "none"))
    S.append(("Computer and software", rows))

    progress("Startup")
    text, f.boot_secs, f.boot_slow = startup()
    S.append(("Startup", [("Last start", text or "?")] + [("Slowest", s) for s in f.boot_slow[:6]]))

    progress("Processor and memory")
    f.flags = cpu_flags()
    cores, threads = si.cpu_count()
    sets = [x for x in ("sse4_2", "avx", "avx2", "avx512f", "aes", "sha_ni") if x in f.flags]
    f.power = power_profile()
    gov = read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
    drv = read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_driver")
    f.mem = meminfo()
    zram = [p.name for p in Path("/sys/block").glob("zram*")] if Path("/sys/block").is_dir() else []
    S.append(("Processor and memory", [
        ("Processor", si.cpu_name() + (f" {si.cpu_ghz()}" if si.cpu_ghz() and si.cpu_ghz().split()[0] not in si.cpu_name()
                                        else "")),
        ("Cores / threads", f"{cores} / {threads}"),
        ("Instruction sets", ", ".join(sets) or "basic x86-64 only" if platform.machine() == "x86_64" else ", ".join(sets)),
        ("Frequency driver / governor", f"{drv or '-'} / {gov or '-'}"),
        ("Power mode", f.power or "-"),
        ("Load (1, 5, 15 min)", " ".join(read("/proc/loadavg").split()[:3])),
        ("Memory", f"{human_bytes(f.mem.get('MemTotal', 0))} total, {human_bytes(f.mem.get('MemAvailable', 0))} available"),
        ("Swap", f"{human_bytes(f.mem.get('SwapTotal', 0))} total, "
                 f"{human_bytes(f.mem.get('SwapTotal', 0) - f.mem.get('SwapFree', 0))} in use"
                 + (f" (zram: {', '.join(zram)})" if zram else "")),
    ]))

    progress("Graphics")
    f.graphics = g = graphics()
    plasma_backend = (ini_value(CONFIG / "plasmashellrc", "QtQuickRendererSettings", "SceneGraphBackend")
                      or ini_value(CONFIG / "kdeglobals", "QtQuickRendererSettings", "SceneGraphBackend") or "automatic")
    S.append(("Graphics", [
        ("Display adapters", "; ".join(g.adapters) or "?"),
        ("KWin draws with", g.compositing or "? (KWin didn't answer)"),
        ("OpenGL", f"{g.renderer} | {g.version} | driver {g.driver}".strip(" |") if g.renderer else "-"),
        ("3D drawn by", "?" if not g.known else "the processor (software)" if g.software else "the graphics card"),
        ("Vulkan devices", "; ".join(g.vulkan) or "-"),
        ("KWin effects running", ", ".join(g.effects) or "-"),
        ("Blur / background contrast (kwinrc)", f"{ini_value(CONFIG / 'kwinrc', 'Plugins', 'blurEnabled') or 'default'}"
                                                f" / {ini_value(CONFIG / 'kwinrc', 'Plugins', 'contrastEnabled') or 'default'}"),
        ("Animation speed factor", ini_value(CONFIG / "kdeglobals", "KDE", "AnimationDurationFactor")
         or ini_value(Path("/etc/xdg/kdeglobals"), "KDE", "AnimationDurationFactor") or "default"),
        ("Plasma's Qt Quick renderer", plasma_backend),
        ("KWin settings (kwinrc Compositing)", ", ".join(f"{k}={v}" for k, v in
                                                         ini_group(CONFIG / "kwinrc", "Compositing").items()) or "default"),
        ("Graphics settings in the environment", "; ".join(graphics_environment()) or "none"),
    ]))

    progress("Displays")
    f.displays = displays()
    rows = []
    for d in f.displays:
        rows.append((d.name, (f"{d.monitor}: " if d.monitor else "")
                     + (f"{d.width}x{d.height} at {d.refresh:.2f} Hz (up to {d.best_refresh:.2f} Hz), scale {d.scale:g}"
                        if d.enabled else "turned off")
                     + (f", adaptive sync {d.vrr}" if d.vrr else "") + (f", HDR {d.hdr}" if d.hdr else "")
                     + (", main display" if d.primary else "")))
    S.append(("Displays", rows or [("Displays", "? (kscreen-doctor didn't answer)")]))

    progress("Disks")
    f.mounts = mounts()
    rows = [("Disk", b) for b in block_devices()]
    for m in f.mounts:
        rows.append((m.target, f"{m.fstype} on {m.source}: {human_bytes(m.free)} free of {human_bytes(m.size)}"))
    letters = [ln.split("# classic7-drive", 1)[1].strip() + ": " + ln.split()[1]
               for ln in read("/etc/fstab").splitlines() if "# classic7-drive" in ln and not ln.lstrip().startswith("#")]
    if letters:
        rows.append(("Drive letters", ", ".join(letters)))
    S.append(("Disks", rows))

    progress("Network")
    rows = []
    code, out = run(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"], 8)
    for ln in out.splitlines() if code == 0 else []:
        parts = ln.replace("\\:", "\x00").split(":")
        if len(parts) >= 3 and parts[1] not in ("loopback",):
            rows.append(("Connection", f"{parts[0].replace(chr(0), ':')} ({parts[1]}, {parts[2]})"))
    code, out = run(["ip", "-4", "-br", "addr"], 5)
    for ln in out.splitlines() if code == 0 else []:
        p = ln.split()
        if p and p[0] != "lo":
            rows.append(("IPv4 " + p[0], " ".join(p[2:]) or p[1]))
    code, out = run(["ip", "route", "show", "default"], 5)
    if code == 0 and out.strip():
        rows.append(("Default gateway", out.split()[2] if len(out.split()) > 2 else out.strip()))
    code, out = run(["firewall-cmd", "--state"], 8)
    rows.append(("Firewall", out.strip() or ("not installed" if code == -1 else "not running")))
    S.append(("Network", rows))

    progress("Sound")
    rows = []
    code, out = run(["pactl", "get-default-sink"], 5)
    if code == 0:
        rows.append(("Default output", out.strip()))
    code, out = run(["pactl", "get-default-source"], 5)
    if code == 0:
        rows.append(("Default input", out.strip()))
    code, out = run(["pactl", "info"], 5)
    for ln in out.splitlines() if code == 0 else []:
        if ln.startswith("Server Name"):
            rows.append(("Sound server", ln.split(":", 1)[1].strip()))
    S.append(("Sound", rows or [("Sound", "? (pactl didn't answer)")]))

    progress("Problems")
    f.failed = failed_units(False) + [u + " (this account)" for u in failed_units(True)]
    f.crashes = crashes()
    S.append(("Services that failed", [("Service", u) for u in f.failed] or [("Services", "none")]))
    S.append(("Programs that stopped working (7 days)", [("Crash", c) for c in f.crashes] or [("Crashes", "none")]))

    progress("Busy programs")
    f.busy, cpu_users, mem_users = busy_programs()
    S.append(("What the computer is doing (2 seconds)", [
        ("Processor in use", f"{f.busy:.0f}%"),
        ("Using the processor (100% = one core)", "; ".join(cpu_users) or "nothing worth mentioning"),
        ("Using the most memory", "; ".join(mem_users)),
    ]))
    return f


# =============================================================================================
# Performance issues (what Windows 7 lists under Advanced tools)
# =============================================================================================
@dataclass
class Issue:
    title: str
    text: str
    important: bool = True
    fix_text: str = ""
    fix: list[str] = field(default_factory=list)


def issues(f: Facts, scores: dict | None = None) -> list[Issue]:
    out: list[Issue] = []
    g = f.graphics
    vm = f.virt
    if g.software:
        if g.compositing.lower() == "qpainter":
            what = "KWin draws the desktop without OpenGL"
        else:
            what = f"3D graphics are drawn by the processor ({g.renderer.split('(')[0].strip() or 'software'})"
        if vm:
            text = (f"{what}: this virtual machine ({vm}) has no 3D graphics card, so every picture of the desktop "
                    "is made by the processor. Moving windows, menus and hover highlights react more slowly. "
                    "Give the virtual machine a faster processor (in Proxmox: CPU type host), or 3D graphics "
                    "(VirGL) if its host has a graphics card.")
            out.append(Issue("Graphics are drawn by the processor", text, True))
        else:
            text = (f"{what}: the graphics card's 3D driver isn't in use ({'; '.join(g.adapters) or 'no display adapter found'}). "
                    "Moving windows and games are much slower than they should be. Check Device Manager for the "
                    "display adapter, and that the computer was started with the graphics card connected.")
            out.append(Issue("Graphics are drawn by the processor", text, True, "Open Device Manager",
                             ["classic7-devmgmt"]))
    for a in g.adapters:
        if a.endswith("(nouveau)"):
            out.append(Issue("NVIDIA graphics without NVIDIA's driver",
                             f"{a.rsplit(' (', 1)[0]} runs on the open-source nouveau driver: 3D and games are "
                             "slower than with NVIDIA's own driver, and GeForce 10 series and older cards run at a "
                             "low speed. Classic 7 is built on Bazzite's image for AMD and Intel graphics.", True,
                             "Open Device Manager", ["classic7-devmgmt"]))
    if platform.machine() == "x86_64" and "avx2" not in f.flags:
        if vm:
            out.append(Issue("The processor's AVX2 instructions are hidden from this virtual machine",
                             "Drawing on the processor (llvmpipe), video for Remote Desktop and many programs run at "
                             "about half speed without them. In Proxmox: Hardware > Processors > Type: host (then "
                             "shut the virtual machine down and start it again).", True))
        else:
            out.append(Issue("The processor has no AVX2 instructions",
                             "This is an older processor: drawing on the processor and video work run slower.", False))
    if g.software and any(e in g.effects for e in ("blur", "contrast")):
        out.append(Issue("Blur runs on the processor",
                         "KWin blurs the glass for every picture although 3D is drawn by the processor. Apply the "
                         "theme again to turn it off.", True, "Apply the theme again",
                         ["classic7-appearance", "--look", str(f.look.get("look") or "aero")]))
    for d in f.displays:
        if d.enabled and d.best_refresh - d.refresh > 1.5:
            out.append(Issue(f"{d.monitor or d.name} runs at {d.refresh:.0f} Hz",
                             f"It can show {d.best_refresh:.0f} pictures a second at this resolution: movement looks "
                             "smoother and reacts sooner at the higher rate.", True, "Change the refresh rate",
                             ["kcmshell6", "kcm_kscreen"]))
    for a in g.adapters:
        if a.endswith("(no driver)"):
            out.append(Issue(f"No driver for {a.rsplit(' (', 1)[0]}",
                             "This display adapter has no driver loaded.", True, "Open Device Manager", ["classic7-devmgmt"]))
    total, avail = f.mem.get("MemTotal", 0), f.mem.get("MemAvailable", 0)
    swap_used = f.mem.get("SwapTotal", 0) - f.mem.get("SwapFree", 0)
    if total and avail / total < 0.10:
        out.append(Issue("The computer is low on memory",
                         f"Only {human_bytes(avail)} of {human_bytes(total)} is free. Close programs you aren't using.",
                         True, "Open Task Manager", ["classic7-taskmgr"]))
    elif total and swap_used > total * 0.25:
        out.append(Issue("Memory is being moved to the swap space",
                         f"{human_bytes(swap_used)} of memory is swapped out, which slows programs down when they "
                         "need it again.", False, "Open Task Manager", ["classic7-taskmgr"]))
    for m in f.mounts:
        if m.size > 2 * 1024 ** 3 and m.free / m.size < 0.10:
            out.append(Issue(f"{m.target} is nearly full",
                             f"Only {human_bytes(m.free)} of {human_bytes(m.size)} is free.", True,
                             "Open Computer", ["classic7-computer"]))
    if f.failed:
        out.append(Issue("Services failed to start", ", ".join(f.failed[:6])
                         + (f" and {len(f.failed) - 6} more" if len(f.failed) > 6 else "")
                         + ". Event Viewer shows why.", True, "Open Event Viewer", ["classic7-eventvwr"]))
    if f.crashes:
        out.append(Issue("Programs stopped working",
                         f"{len(f.crashes)} crash{'es' if len(f.crashes) != 1 else ''} in the last week. "
                         "Event Viewer > Problem Reports has the details.", False, "View problem reports",
                         ["classic7-eventvwr", "--problems"]))
    if "power-saver" in f.power or "powersave" in f.power:
        out.append(Issue("Power saver mode is on", "The processor runs slower to save energy.", False,
                         "Change power settings", ["kcmshell6", "kcm_powerdevilprofilesconfig"]))
    if f.busy > 50:
        out.append(Issue("The processor is busy",
                         f"{f.busy:.0f}% of the processor was in use while nothing was being done. Task Manager shows "
                         "which program uses it.", True, "Open Task Manager", ["classic7-taskmgr"]))
    if f.boot_secs > 45:
        out.append(Issue("Starting the computer takes a long time",
                         f"The desktop could start {f.boot_secs:.0f} seconds after the system did. Slowest: "
                         + "; ".join(f.boot_slow[:3]) + ".", False, "Open System Configuration", ["classic7-msconfig"]))
    sc = scores if scores is not None else load_scores()
    raw = (sc.get("raw") or {}).get("graphics") or {}
    if not g.software and isinstance(raw.get("late_60"), (int, float)) and raw["late_60"] > 0.05 \
            and sc.get("hardware") == hardware_key():
        out.append(Issue("Moving pictures aren't smooth",
                         f"In the last assessment {raw['late_60'] * 100:.0f}% of the pictures of a window came "
                         f"too late (slowest {raw.get('slowest_ms', 0):.0f} ms). Close busy programs and run the "
                         "assessment again; if it stays, the graphics driver may need attention.", True,
                         "Open Task Manager", ["classic7-taskmgr"]))
    if f.deploy.get("staged"):
        out.append(Issue("A new version of Classic 7 is waiting",
                         "It was downloaded and starts the next time the computer starts.", False))
    if vm and not g.software:
        out.append(Issue("Classic 7 runs in a virtual machine",
                         f"({vm}) Its speed depends on the host and on the graphics given to it.", False))
    return out


# =============================================================================================
# Scores (stored by perfinfo_assess.py) and the report
# =============================================================================================
COMPONENTS = [("cpu", "Processor", "Calculations per second"),
              ("memory", "Memory (RAM)", "Memory operations per second"),
              ("graphics", "Graphics", "Desktop performance for Classic 7 Aero"),
              ("gaming", "Gaming graphics", "3D business and gaming graphics performance"),
              ("disk", "Primary hard disk", "Disk data transfer rate")]


def load_scores() -> dict:
    try:
        return json.loads(SCORES.read_text())
    except (OSError, ValueError):
        return {}


def save_scores(data: dict):
    SCORES.parent.mkdir(parents=True, exist_ok=True)
    SCORES.write_text(json.dumps(data, indent=2) + "\n")


def hardware_key() -> str:
    """Changes when the processor, memory or display adapters change (the scores are then old)."""
    total = meminfo().get("MemTotal", 0) // (256 * 1024 * 1024)
    gpus = sorted(d.name for d in si.pci_devices() if d.category == "Display adapters")
    return f"{si.cpu_name()}|{os.cpu_count()}|{total}|{'|'.join(gpus)}"


def base_score(scores: dict) -> float | None:
    subs = [scores.get("scores", {}).get(k) for k, _n, _w in COMPONENTS]
    subs = [s for s in subs if isinstance(s, (int, float))]
    return min(subs) if subs else None


def report(f: Facts, found: list[Issue], scores: dict | None = None) -> str:
    scores = load_scores() if scores is None else scores
    now = time.strftime("%Y-%m-%d %H:%M %Z")
    lines = ["Classic 7 system health report",
             f"Made {now} by Performance Information and Tools (classic7-perfinfo).",
             "Send this file to whoever helps you with a problem. It has no passwords, keys, serial numbers or",
             "network hardware (MAC) addresses.", ""]
    lines.append(f"== Performance issues ({len(found)})")
    for i in found:
        lines.append(f"{'!' if i.important else '-'} {i.title}")
        lines.append(f"  {i.text}")
    if not found:
        lines.append("  None found.")
    lines.append("")
    lines.append("== Classic 7 Experience Index")
    if scores.get("scores"):
        lines.append(f"  Assessed {scores.get('date', '?')}"
                     + ("  (the hardware changed since: run it again)" if scores.get("hardware") != hardware_key() else ""))
        for key, name, _what in COMPONENTS:
            s = scores["scores"].get(key)
            detail = scores.get("details", {}).get(key, "")
            lines.append(f"  {name:18} {s if s is not None else '-':>4}   {detail}")
        b = base_score(scores)
        lines.append(f"  {'Base score':18} {b if b is not None else '-':>4}   (the lowest subscore)")
    else:
        lines.append("  Not assessed yet (Performance Information and Tools > Rate this computer).")
    for title, rows in f.sections:
        lines.append("")
        lines.append(f"== {title}")
        for k, v in rows:
            lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("== Error messages this boot (newest last)")
    lines += ["  " + ln for ln in journal_errors()] or ["  none (or not readable for this account)"]
    lines.append("")
    lines.append("== Classic 7's own messages")
    lines += ["  " + ln for ln in classic7_unit_errors()] or ["  none"]
    lines.append("")
    lines.append("== Remote Desktop server (KRdp) this boot")
    lines += ["  " + ln for ln in remote_desktop_log()] or ["  no messages"]
    lines.append("")
    lines.append("== Personalization's last changes (appearance.log)")
    lines += ["  " + ln for ln in classic7_log()] or ["  none"]
    return "\n".join(lines) + "\n"


def facts_json(f: Facts) -> dict:
    d = asdict(f)
    d["flags"] = sorted(f.flags)
    return d


# =============================================================================================
# Without a window (a terminal, SSH, or a desktop that won't draw)
# =============================================================================================
def main_cli(argv: list[str]) -> int:
    """--report-text [FILE], --issues, --json; returns the exit code."""
    def say(text):
        print(text, file=sys.stderr, flush=True)
    f = collect(lambda text: say(f"Collecting information: {text}..."))
    scores = load_scores()
    found = issues(f, scores)
    if "--issues" in argv:
        for i in found:
            print(f"{'!' if i.important else '-'} {i.title}\n  {i.text}"
                  + (f"\n  ({i.fix_text}: {' '.join(i.fix)})" if i.fix else ""))
        if not found:
            print("No performance issues were found.")
        return 0
    if "--json" in argv:
        print(json.dumps({"facts": facts_json(f), "issues": [asdict(i) for i in found], "scores": scores},
                         indent=1, default=str))
        return 0
    text = report(f, found, scores)
    rest = argv[argv.index("--report-text") + 1:] if "--report-text" in argv else []
    if rest and not rest[0].startswith("-"):
        Path(rest[0]).expanduser().write_text(text)
        say(f"Saved as {Path(rest[0]).expanduser()}")
    else:
        sys.stdout.write(text)
    return 0
