"""Programs and Features: what is installed and how to remove it.

Three kinds of programs on Classic 7 (Bazzite):
  * Flatpak apps (the app store, Bazaar) - removed with `flatpak uninstall`
  * Steam games and tools - removed by Steam itself (steam://uninstall/<appid>)
  * packages added to the system image with rpm-ostree - removed with `rpm-ostree uninstall`
    (takes effect after a restart)
The programs that come with Classic 7 are part of the system image and can't be removed.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()
FLATPAK_DIRS = {"system": Path(os.environ.get("CLASSIC7_FLATPAK_SYSTEM", "/var/lib/flatpak")),
                "user": Path(os.environ.get("CLASSIC7_FLATPAK_USER", str(HOME / ".local/share/flatpak")))}
STEAM_ROOTS = [Path(p) for p in os.environ.get("CLASSIC7_STEAM_ROOTS", "").split(":") if p] or [
    HOME / ".local/share/Steam", HOME / ".steam/steam",
    HOME / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]


@dataclass
class Program:
    kind: str                     # flatpak, steam, rpm
    ident: str                    # app id, Steam appid, package name
    name: str
    publisher: str = ""
    installed: dt.date | None = None
    size: int = 0                 # bytes, 0 = unknown
    version: str = ""
    icon: str = ""                # icon theme name or file path
    where: str = ""               # "system"/"user" for flatpak, library path for Steam
    extra: dict = field(default_factory=dict)

    @property
    def source(self) -> str:
        return {"flatpak": f"App store (Flatpak, {'all users' if self.where == 'system' else 'this user'})",
                "steam": "Steam", "rpm": "Added to the system image"}.get(self.kind, self.kind)

    def uninstall_argv(self) -> list[str]:
        if self.kind == "flatpak":
            return ["flatpak", "uninstall", "--noninteractive", "-y", f"--{self.where}", self.ident]
        if self.kind == "steam":
            return ["steam", f"steam://uninstall/{self.ident}"]
        if self.kind == "rpm":
            return ["rpm-ostree", "uninstall", self.ident]
        return []

    def change_argv(self) -> list[str]:
        """'Change': the program's page in the app store (Flatpak) or its Steam properties."""
        if self.kind == "flatpak":
            return store_command()
        if self.kind == "steam":
            return ["steam", f"steam://nav/games/details/{self.ident}"]
        return []


def store_command() -> list[str]:
    """The app store: Bazaar (installed as a system program on Bazzite, or as a Flatpak), or Discover."""
    if shutil.which("bazaar"):
        return ["bazaar"]
    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", "io.github.kolunmi.Bazaar"],
                                                  capture_output=True).returncode == 0:
        return ["flatpak", "run", "io.github.kolunmi.Bazaar"]
    if shutil.which("plasma-discover"):
        return ["plasma-discover"]
    return []


# ---- sizes ------------------------------------------------------------------------------------
UNITS = {"b": 1, "bytes": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
         "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}


def parse_size(text: str) -> int:
    m = re.match(r"\s*([\d.,]+)\s*([A-Za-z]*)", text.replace("\xa0", " "))
    if not m:
        return 0
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        return 0
    return int(n * UNITS.get(m.group(2).lower() or "b", 1))


def fmt_size(n: int) -> str:
    """Like Windows: 512 KB, 41.2 MB, 1.85 GB."""
    if n <= 0:
        return ""
    if n < 1024 ** 2:
        return f"{max(1, round(n / 1024))} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def fmt_date(d: dt.date | None) -> str:
    return d.strftime("%d-%m-%Y") if d else ""


# ---- Flatpak ----------------------------------------------------------------------------------
def _flatpak_publisher(base: Path, app: str) -> str:
    for folder in ("metainfo", "appdata"):
        for name in (f"{app}.metainfo.xml", f"{app}.appdata.xml"):
            p = base / "files" / "share" / folder / name
            if not p.exists():
                continue
            try:
                root = ET.parse(p).getroot()
            except (ET.ParseError, OSError):
                continue
            for path in ("developer/name", "developer_name", "project_group"):
                for el in root.findall(path):
                    if el.text and not el.attrib.get("{http://www.w3.org/XML/1998/namespace}lang"):
                        return el.text.strip()
    return ""


def _flatpak_details(where: str, app: str) -> tuple[str, dt.date | None, str]:
    """(publisher, installed date, icon file) from the app's deployed files."""
    active = FLATPAK_DIRS[where] / "app" / app / "current" / "active"
    publisher, date, icon_file = "", None, ""
    try:
        real = active.resolve()
        date = dt.date.fromtimestamp((real / "deploy").stat().st_mtime if (real / "deploy").exists()
                                     else real.stat().st_mtime)
        publisher = _flatpak_publisher(real, app)
        for size in ("48x48", "64x64", "128x128", "scalable", "256x256"):
            hits = glob.glob(str(real / "export/share/icons/hicolor" / size / "apps" / f"{app}.*"))
            if hits:
                icon_file = hits[0]
                break
    except OSError:
        pass
    return publisher, date, icon_file


def flatpak_apps() -> list[Program]:
    if not shutil.which("flatpak"):
        return []
    try:
        r = subprocess.run(["flatpak", "list", "--app", "--columns=application,name,version,installation,size,origin"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in r.stdout.splitlines():
        cols = line.split("\t")
        if len(cols) < 6 or not cols[0] or cols[0] == "Application ID":
            continue
        app, name, version, where, size, origin = cols[:6]
        where = "user" if where.strip().lower() == "user" else "system"
        publisher, date, icon_file = _flatpak_details(where, app)
        out.append(Program("flatpak", app, name or app, publisher or origin.capitalize(), date, parse_size(size),
                           version, icon_file or app, where, {"origin": origin}))
    return out


# ---- Steam ------------------------------------------------------------------------------------
def parse_vdf(text: str) -> dict:
    """Valve's KeyValues text format ("key" "value" and "key" { ... })."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack: list[dict] = [{}]
    key = None
    for quoted, brace in tokens:
        if brace == "{":
            new: dict = {}
            stack[-1][key if key is not None else ""] = new
            stack.append(new)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted
        else:
            stack[-1][key] = quoted.replace('\\\\', '\\')
            key = None
    return stack[0]


def steam_libraries() -> list[Path]:
    seen, out = set(), []
    for root in STEAM_ROOTS:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        paths = [root]
        try:
            data = parse_vdf(vdf.read_text(errors="replace"))
            folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
            for v in folders.values():
                p = v.get("path") if isinstance(v, dict) else v
                if p:
                    paths.append(Path(p))
        except OSError:
            pass
        for p in paths:
            try:
                key = p.resolve()
            except OSError:
                continue
            if key not in seen and (p / "steamapps").is_dir():
                seen.add(key)
                out.append(p)
    return out


def steam_games() -> list[Program]:
    out, seen = [], set()
    for lib in steam_libraries():
        for acf in sorted((lib / "steamapps").glob("appmanifest_*.acf")):
            try:
                st = parse_vdf(acf.read_text(errors="replace")).get("AppState", {})
            except OSError:
                continue
            appid, name = st.get("appid", ""), st.get("name", "")
            if not appid or not name or appid in seen:
                continue
            seen.add(appid)
            try:
                size = int(st.get("SizeOnDisk") or 0)
            except ValueError:
                size = 0
            try:
                date = dt.date.fromtimestamp(int(st.get("LastUpdated") or 0)) if st.get("LastUpdated") else None
            except (ValueError, OSError):
                date = None
            out.append(Program("steam", appid, name, "Steam", date, size, "",
                               f"steam_icon_{appid}", str(lib)))
    return out


# ---- packages added to the image --------------------------------------------------------------
def layered_packages() -> list[Program]:
    if not shutil.which("rpm-ostree"):
        return []
    try:
        r = subprocess.run(["rpm-ostree", "status", "--json"], capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    booted = next((d for d in data.get("deployments", []) if d.get("booted")), None)
    if not booted:
        return []
    pending = next((d for d in data.get("deployments", []) if not d.get("booted") and d.get("staged")), None)
    names = list(dict.fromkeys(booted.get("requested-packages", []) + booted.get("requested-local-packages", [])))
    try:
        date = dt.date.fromtimestamp(int(booted.get("timestamp", 0))) if booted.get("timestamp") else None
    except (ValueError, OSError):
        date = None
    out = []
    for pkg in names:
        version, size, summary = "", 0, ""
        try:
            q = subprocess.run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}\t%{SIZE}\t%{VENDOR}\t%{SUMMARY}", pkg],
                               capture_output=True, text=True, timeout=10)
            if q.returncode == 0:
                version, size_s, vendor, summary = (q.stdout.split("\t") + ["", "", "", ""])[:4]
                size = int(size_s or 0)
            else:
                vendor = ""
        except (OSError, subprocess.SubprocessError, ValueError):
            vendor = ""
        removing = bool(pending and pkg not in pending.get("requested-packages", []))
        out.append(Program("rpm", pkg, pkg, vendor if vendor and vendor != "(none)" else "Fedora", date, size, version,
                           "package-x-generic", "", {"summary": summary, "removing": removing}))
    return out


def all_programs() -> list[Program]:
    progs = flatpak_apps() + steam_games() + layered_packages()
    return sorted(progs, key=lambda p: p.name.lower())
