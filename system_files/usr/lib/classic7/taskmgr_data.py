"""Task Manager data (no GUI code): processes, CPU, memory, network, services, users."""
from __future__ import annotations

import json
import os
import pwd
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil


@dataclass
class Proc:
    pid: int
    name: str
    user: str
    uid: int
    cpu: float          # percent of the whole computer, like Windows
    private: int        # bytes (resident minus shared: Windows' "private working set")
    description: str
    exe: str
    cmdline: list[str]
    ppid: int
    nice: int
    threads: int
    status: str


@dataclass
class Snapshot:
    when: float
    procs: list[Proc]
    cpu_total: float
    cpu_per: list[float]
    mem: dict
    system: dict
    nets: dict = field(default_factory=dict)   # name -> (bytes per second, link speed bits/s, up)
    kernel_per: list[float] = field(default_factory=list)


def _meminfo() -> dict[str, int]:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, _, v = line.partition(":")
            parts = v.split()
            if parts:
                out[k] = int(parts[0]) * 1024
    except OSError:
        pass
    return out


def _handles() -> int:
    try:
        return int(Path("/proc/sys/fs/file-nr").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return 0


class Descriptions:
    """Program names from .desktop files: 'firefox' -> 'Firefox', 'steam' -> 'Steam'."""

    def __init__(self):
        self.by_exe: dict[str, str] = {}
        self.by_wmclass: dict[str, str] = {}
        self.icons: dict[str, str] = {}
        dirs = [Path.home() / ".local/share/applications", Path("/usr/share/applications"),
                Path("/var/lib/flatpak/exports/share/applications"),
                Path.home() / ".local/share/flatpak/exports/share/applications"]
        for d in dirs:
            if not d.is_dir():
                continue
            for f in d.glob("*.desktop"):
                self._read(f)

    def _read(self, f: Path):
        name = exe = wm = icon = None
        nodisplay = False
        try:
            text = f.read_text(errors="replace")
        except OSError:
            return
        in_main = False
        for line in text.splitlines():
            if line.startswith("["):
                in_main = line.strip() == "[Desktop Entry]"
                continue
            if not in_main or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k == "Name" and name is None:
                name = v.strip()
            elif k == "Exec" and exe is None:
                try:
                    argv = [a for a in shlex.split(v) if not a.startswith("%")]
                except ValueError:
                    argv = v.split()
                # flatpak run --branch=... org.app.Name
                if argv and os.path.basename(argv[0]) == "flatpak" and "run" in argv:
                    rest = [a for a in argv[argv.index("run") + 1:] if not a.startswith("-")]
                    exe = rest[0] if rest else None
                elif argv and os.path.basename(argv[0]) == "env":
                    rest = [a for a in argv[1:] if "=" not in a]
                    exe = os.path.basename(rest[0]) if rest else None
                elif argv:
                    exe = os.path.basename(argv[0])
            elif k == "StartupWMClass":
                wm = v.strip()
            elif k == "Icon":
                icon = v.strip()
            elif k == "NoDisplay" and v.strip().lower() == "true":
                nodisplay = True
        if not name:
            return
        for key, table in ((exe, self.by_exe), (wm, self.by_wmclass), (f.stem, self.by_wmclass)):
            if key and (key.lower() not in table or not nodisplay):
                table[key.lower()] = name
                if icon:
                    self.icons[key.lower()] = icon

    def describe(self, name: str, exe: str, cmdline: list[str]) -> str:
        for key in (os.path.basename(exe), name, os.path.basename(cmdline[0]) if cmdline else ""):
            if key and key.lower() in self.by_exe:
                return self.by_exe[key.lower()]
        for key in (name,):
            if key and key.lower() in self.by_wmclass:
                return self.by_wmclass[key.lower()]
        # python3 /usr/bin/classic7-write -> the script's name
        if name.startswith("python") and len(cmdline) > 1:
            base = os.path.basename(cmdline[1])
            if base.lower() in self.by_exe:
                return self.by_exe[base.lower()]
            return base
        return KNOWN.get(name, "")

    def icon_for(self, name: str, exe: str) -> str | None:
        for key in (os.path.basename(exe), name):
            if key and key.lower() in self.icons:
                return self.icons[key.lower()]
        return None


KNOWN = {
    "systemd": "System and Service Manager", "kwin_wayland": "Window Manager",
    "plasmashell": "Desktop and Taskbar", "Xwayland": "X11 Compatibility", "pipewire": "Audio and Video",
    "wireplumber": "Audio Session Manager", "pipewire-pulse": "Audio (PulseAudio compatible)",
    "dbus-broker": "Message Bus", "dbus-daemon": "Message Bus", "kded6": "KDE Background Services",
    "ksmserver": "Session Manager", "sddm": "Login Screen", "NetworkManager": "Network Connections",
    "polkitd": "Permissions", "bash": "Command Shell", "sshd": "Secure Shell Server",
    "gamescope": "Game Session", "steamwebhelper": "Steam Client Web Helper", "steam": "Steam",
    "xdg-desktop-portal": "Desktop Portal", "kwalletd6": "Wallet (saved passwords)",
    "baloo_file": "File Indexing", "krunner": "Run Command", "upowerd": "Power Status",
    "udisksd": "Disk Manager", "rtkit-daemon": "Realtime Scheduling", "chronyd": "Time Synchronization",
    "firewalld": "Firewall", "cupsd": "Printing", "bluetoothd": "Bluetooth", "lactd": "Graphics Card Control",
}


class Sampler:
    def __init__(self):
        self.prev: dict[int, tuple[float, float]] = {}   # pid -> (cpu seconds, time)
        self.users: dict[int, str] = {}
        self.desc = Descriptions()
        self.ncpu = psutil.cpu_count() or 1
        psutil.cpu_percent(percpu=True)
        psutil.cpu_times_percent(percpu=True)
        self.net_prev: dict[str, tuple[int, float]] = {}
        self.boot = psutil.boot_time()

    def _user(self, uid: int) -> str:
        if uid not in self.users:
            try:
                self.users[uid] = pwd.getpwuid(uid).pw_name
            except KeyError:
                self.users[uid] = str(uid)
        return self.users[uid]

    def sample(self, with_procs: bool = True) -> Snapshot:
        now = time.monotonic()
        procs: list[Proc] = []
        threads = 0
        seen = set()
        attrs = ["pid", "name", "uids", "cpu_times", "memory_info", "exe", "cmdline", "ppid", "nice",
                 "num_threads", "status"]
        for p in psutil.process_iter(attrs, ad_value=None):
            info = p.info
            pid = info["pid"]
            seen.add(pid)
            threads += info["num_threads"] or 0
            if not with_procs:
                continue
            ct = info["cpu_times"]
            secs = (ct.user + ct.system) if ct else 0.0
            cpu = 0.0
            if pid in self.prev:
                ps, pt = self.prev[pid]
                if now > pt:
                    cpu = max(0.0, (secs - ps) / (now - pt) / self.ncpu * 100)
            self.prev[pid] = (secs, now)
            mi = info["memory_info"]
            private = max(0, mi.rss - getattr(mi, "shared", 0)) if mi else 0
            uid = info["uids"].real if info["uids"] else -1
            name = info["name"] or ""
            exe = info["exe"] or ""
            cmd = info["cmdline"] or []
            procs.append(Proc(pid, name, self._user(uid) if uid >= 0 else "", uid, cpu, private,
                              self.desc.describe(name, exe, cmd), exe, cmd, info["ppid"] or 0,
                              info["nice"] if info["nice"] is not None else 0, info["num_threads"] or 0,
                              info["status"] or ""))
        for pid in list(self.prev):
            if pid not in seen:
                del self.prev[pid]
        per = psutil.cpu_percent(percpu=True)
        total = sum(per) / len(per) if per else 0.0
        vm = psutil.virtual_memory()
        mi = _meminfo()
        mem = {"total": vm.total, "available": vm.available, "free": vm.free,
               "cached": mi.get("Cached", 0) + mi.get("Buffers", 0) + mi.get("SReclaimable", 0),
               "used": vm.total - vm.available, "percent": vm.percent,
               "paged": mi.get("SReclaimable", 0), "nonpaged": mi.get("SUnreclaim", 0),
               "commit": mi.get("Committed_AS", 0), "commit_limit": mi.get("CommitLimit", 0),
               "swap_total": mi.get("SwapTotal", 0), "swap_free": mi.get("SwapFree", 0)}
        system = {"handles": _handles(), "threads": threads, "processes": len(seen),
                  "uptime": time.time() - self.boot}
        try:
            kern = [t.system + getattr(t, "irq", 0) + getattr(t, "softirq", 0)
                    for t in psutil.cpu_times_percent(percpu=True)]
        except OSError:
            kern = []
        return Snapshot(time.time(), procs, total, per, mem, system, self._nets(now), kern)

    def _nets(self, now: float) -> dict:
        out = {}
        try:
            counters = psutil.net_io_counters(pernic=True)
            stats = psutil.net_if_stats()
        except OSError:
            return out
        for name, c in counters.items():
            if name == "lo" or name.startswith(("veth", "docker", "virbr", "br-", "podman", "tun", "wg-", "ifb")):
                continue
            total = c.bytes_sent + c.bytes_recv
            rate = 0.0
            if name in self.net_prev:
                pb, pt = self.net_prev[name]
                if now > pt:
                    rate = max(0.0, (total - pb) / (now - pt))
            self.net_prev[name] = (total, now)
            st = stats.get(name)
            speed = (st.speed if st and st.speed and st.speed > 0 else 0) * 1_000_000
            out[name] = (rate, speed, bool(st and st.isup))
        return out


def adapter_name(dev: str) -> str:
    """'wlp4s0' -> 'Wireless Network Connection', 'enp3s0' -> 'Local Area Connection'."""
    if dev.startswith(("wl", "wlan")):
        return "Wireless Network Connection"
    if dev.startswith(("en", "eth")):
        return "Local Area Connection"
    return dev


# ---- services ---------------------------------------------------------------------------------
@dataclass
class Service:
    name: str
    pid: int
    description: str
    status: str            # "Running" or "Stopped"
    group: str             # "system" or "user"
    sub: str


def services(user: bool = False) -> list[Service]:
    base = ["systemctl"] + (["--user"] if user else []) + ["--no-pager"]
    try:
        res = subprocess.run(base + ["list-units", "--type=service", "--all", "-o", "json"],
                             capture_output=True, text=True, timeout=8)
        units = json.loads(res.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    names = [u["unit"] for u in units if u.get("load") == "loaded"]
    pids: dict[str, int] = {}
    if names:
        try:
            res = subprocess.run(base + ["show", "-p", "Id,MainPID", "--"] + names, capture_output=True, text=True,
                                 timeout=8)
            cur = None
            for line in res.stdout.splitlines():
                if line.startswith("Id="):
                    cur = line[3:]
                elif line.startswith("MainPID=") and cur:
                    pids[cur] = int(line[8:] or 0)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    out = []
    for u in units:
        if u.get("load") != "loaded":
            continue
        name = u["unit"]
        out.append(Service(name.removesuffix(".service"), pids.get(name, 0), u.get("description", ""),
                           "Running" if u.get("active") == "active" else "Stopped", "user" if user else "system",
                           u.get("sub", "")))
    return out


# ---- users ------------------------------------------------------------------------------------
def sessions() -> list[dict]:
    try:
        res = subprocess.run(["loginctl", "list-sessions", "-o", "json", "--no-pager"], capture_output=True,
                             text=True, timeout=5)
        rows = json.loads(res.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    out = []
    for r in rows:
        sid = str(r.get("session", ""))
        state = r.get("state") or ""
        if not state:
            try:
                show = subprocess.run(["loginctl", "show-session", sid, "-p", "State", "--value"],
                                      capture_output=True, text=True, timeout=3).stdout.strip()
                state = show
            except (OSError, subprocess.SubprocessError):
                pass
        out.append({"id": sid, "user": r.get("user", ""), "uid": r.get("uid", 0), "seat": r.get("seat") or "",
                    "tty": r.get("tty") or "", "state": state, "class": r.get("class", "")})
    return out


def fmt_k(n: int) -> str:
    return f"{n // 1024:,} K"


def fmt_uptime(secs: float) -> str:
    s = int(secs)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{d}:{h:02d}:{m:02d}:{s:02d}"


def safe_unit(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9@_.:\\-]+", name))
