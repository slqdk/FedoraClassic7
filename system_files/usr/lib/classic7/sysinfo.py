"""What the System window and Device Manager show (no GUI code): the computer, its
processor, memory and graphics, and every device grouped like Windows 7's Device Manager.

CLASSIC7_SYSFS and CLASSIC7_PROC can point at sample trees for testing.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

SYS = Path(os.environ.get("CLASSIC7_SYSFS", "/sys"))
PROC = Path(os.environ.get("CLASSIC7_PROC", "/proc"))


def read(path: Path | str, default: str = "") -> str:
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return default


# ---- the computer ----------------------------------------------------------------------------
def os_release() -> dict[str, str]:
    out = {}
    for line in read("/etc/os-release").splitlines():
        k, _, v = line.partition("=")
        out[k] = v.strip().strip('"')
    return out


def classic7_version() -> str:
    try:
        info = json.loads(read("/usr/share/classic7/build-info.json") or "{}")
    except ValueError:
        info = {}
    return info.get("build", "")


def cpu_name() -> str:
    for line in read(PROC / "cpuinfo").splitlines():
        if line.startswith("model name"):
            return " ".join(line.split(":", 1)[1].split())
    return platform.processor() or platform.machine()


def cpu_count() -> tuple[int, int]:
    """(cores, threads)"""
    threads = os.cpu_count() or 1
    cores = set()
    phys = core = None
    for line in read(PROC / "cpuinfo").splitlines():
        if line.startswith("physical id"):
            phys = line.split(":")[1].strip()
        elif line.startswith("core id"):
            core = line.split(":")[1].strip()
        elif not line.strip() and core is not None:
            cores.add((phys, core))
            phys = core = None
    if core is not None:
        cores.add((phys, core))
    return len(cores) or threads, threads


def cpu_ghz() -> str:
    mhz = read(SYS / "devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    if mhz.isdigit():
        return f"{int(mhz) / 1e6:.2f} GHz"
    for line in read(PROC / "cpuinfo").splitlines():
        if line.startswith("cpu MHz"):
            return f"{float(line.split(':')[1]) / 1000:.2f} GHz"
    return ""


def memory() -> tuple[int, int]:
    """(installed bytes, usable bytes). Installed is MemTotal rounded up to whole GB, as the
    firmware keeps a little for itself."""
    total = 0
    for line in read(PROC / "meminfo").splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) * 1024
    gib = 1024 ** 3
    installed = -(-total // gib) * gib if total else 0
    # the DIMMs, if the firmware tables are readable (they usually are not without root)
    dimms = 0
    for f in (SYS / "firmware/dmi/entries").glob("17-*/raw") if (SYS / "firmware/dmi/entries").is_dir() else []:
        raw = b""
        try:
            raw = f.read_bytes()
        except OSError:
            continue
        if len(raw) > 0x0E:
            size = int.from_bytes(raw[0x0C:0x0E], "little")
            if size not in (0, 0xFFFF):
                dimms += (size & 0x7FFF) * (1024 if not size & 0x8000 else 1) * 1024
    return (dimms or installed), total


def graphics() -> list[str]:
    return [d.name for d in pci_devices() if d.category == "Display adapters"]


def computer_name() -> str:
    pretty = ""
    try:
        r = subprocess.run(["hostnamectl", "--pretty"], capture_output=True, text=True, timeout=3)
        pretty = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return socket.gethostname(), pretty


def workgroup() -> str:
    for line in read("/etc/samba/smb.conf").splitlines():
        m = re.match(r"\s*workgroup\s*=\s*(\S+)", line, re.I)
        if m:
            return m.group(1).upper()
    return "WORKGROUP"


def system_type() -> str:
    bits = "64-bit" if platform.architecture()[0] == "64bit" or platform.machine() in ("x86_64", "aarch64") else "32-bit"
    return f"{bits} Operating System"


def touch_input() -> str:
    pen = touch = False
    for block in read(PROC / "bus/input/devices").split("\n\n"):
        name = (re.search(r'N: Name="([^"]*)"', block) or [None, ""])[1].lower()
        if "pen" in name or "stylus" in name or "wacom" in name:
            pen = True
        if "touchscreen" in name or ("touch" in name and "touchpad" not in name):
            touch = True
    if pen and touch:
        return "Pen and Touch Input Available"
    if pen:
        return "Pen Input Available"
    if touch:
        return "Touch Input Available"
    return "No Pen or Touch Input is available for this Display"


def manufacturer_model() -> tuple[str, str]:
    vendor = read(SYS / "class/dmi/id/sys_vendor") or read(SYS / "class/dmi/id/board_vendor")
    product = read(SYS / "class/dmi/id/product_name") or read(SYS / "class/dmi/id/board_name")
    junk = {"To Be Filled By O.E.M.", "System manufacturer", "System Product Name", "Default string", "O.E.M."}
    return ("" if vendor in junk else vendor), ("" if product in junk else product)


# ---- devices ----------------------------------------------------------------------------------
@dataclass
class Device:
    name: str
    category: str
    manufacturer: str = ""
    location: str = ""
    driver: str = ""
    sysfs: str = ""
    ids: list[str] = field(default_factory=list)
    problem: str = ""          # "" = working properly
    extra: dict = field(default_factory=dict)

    @property
    def status(self) -> str:
        return self.problem or "This device is working properly."


# Windows 7's category names, with the icon Device Manager shows for each
CATEGORIES = {
    "Audio inputs and outputs": "audio-card",
    "Batteries": "battery",
    "Bluetooth Radios": "preferences-system-bluetooth",
    "Computer": "computer",
    "Disk drives": "drive-harddisk",
    "Display adapters": "video-display",
    "DVD/CD-ROM drives": "drive-optical",
    "Human Interface Devices": "input-gaming",
    "IDE ATA/ATAPI controllers": "drive-harddisk",
    "Keyboards": "input-keyboard",
    "Mice and other pointing devices": "input-mouse",
    "Monitors": "video-display",
    "Network adapters": "network-wired",
    "Other devices": "dialog-warning",
    "Ports (COM & LPT)": "network-wired",
    "Processors": "cpu",
    "Sound, video and game controllers": "audio-card",
    "Storage controllers": "drive-harddisk",
    "System devices": "computer",
    "Universal Serial Bus controllers": "drive-removable-media-usb",
}

PCI_CLASS = {
    0x01: "Storage controllers", 0x02: "Network adapters", 0x03: "Display adapters",
    0x04: "Sound, video and game controllers", 0x05: "System devices", 0x06: "System devices",
    0x07: "Ports (COM & LPT)", 0x08: "System devices", 0x09: "Human Interface Devices",
    0x0C: "Universal Serial Bus controllers", 0x0D: "Network adapters", 0x10: "System devices",
    0x11: "System devices", 0x12: "System devices", 0x13: "System devices",
}
PCI_SUBCLASS = {(0x01, 0x01): "IDE ATA/ATAPI controllers", (0x01, 0x06): "IDE ATA/ATAPI controllers",
                (0x0C, 0x03): "Universal Serial Bus controllers", (0x0C, 0x05): "System devices",
                (0x0C, 0x00): "System devices", (0x0C, 0x80): "System devices", (0x02, 0x80): "Network adapters",
                (0x0D, 0x11): "Bluetooth Radios"}


@lru_cache(maxsize=2)
def _ids(path: str) -> tuple[dict, dict]:
    """vendor names and (vendor, device) names from pci.ids / usb.ids."""
    vendors, devices = {}, {}
    cur = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip() or line.startswith("#"):
                    continue
                if line.startswith("C "):
                    break                         # device classes start here
                if not line.startswith("\t"):
                    vid, _, name = line.partition("  ")
                    cur = vid.strip().lower()
                    vendors[cur] = name.strip()
                elif not line.startswith("\t\t") and cur:
                    did, _, name = line.strip().partition("  ")
                    devices[(cur, did.strip().lower())] = name.strip()
    except OSError:
        pass
    return vendors, devices


def _ids_file(kind: str) -> str:
    for d in ("/usr/share/hwdata", "/usr/share/misc", "/usr/share"):
        p = os.path.join(d, f"{kind}.ids")
        if os.path.exists(p):
            return p
    return ""


def _short_vendor(v: str) -> str:
    """'Advanced Micro Devices, Inc. [AMD/ATI]' -> 'AMD', 'NVIDIA Corporation' -> 'NVIDIA'."""
    m = re.search(r"\[([^\]]+)\]", v)
    if m:
        return m.group(1).split("/")[0].strip()
    v = re.sub(r",?\s*\b(Inc|Corporation|Corp|Co\.,? Ltd|Ltd|Limited|GmbH|Technology|Technologies)\b\.?", "", v)
    return v.strip(" ,.")


def _driver(path: Path) -> str:
    link = path / "driver"
    return os.path.basename(os.readlink(link)) if link.is_symlink() else ""


def pci_devices() -> list[Device]:
    vendors, names = _ids(_ids_file("pci"))
    out = []
    base = SYS / "bus/pci/devices"
    for dev in sorted(base.iterdir()) if base.is_dir() else []:
        vid = read(dev / "vendor").removeprefix("0x").lower()
        did = read(dev / "device").removeprefix("0x").lower()
        cls = int(read(dev / "class", "0x0") or "0", 16)
        c, sc = cls >> 16, (cls >> 8) & 0xFF
        cat = PCI_SUBCLASS.get((c, sc)) or PCI_CLASS.get(c, "System devices")
        vendor = _short_vendor(vendors.get(vid, f"Vendor {vid}"))
        name = names.get((vid, did), f"PCI device {vid}:{did}")
        m = re.search(r"\[([^\]]+)\]", name)      # "Navi 31 [Radeon RX 7900 XT/7900 XTX]" -> the brackets
        if cat == "Display adapters" and m:
            name = f"{vendor.split()[0]} {m.group(1)}" if vendor else m.group(1)
        elif vendor and not name.lower().startswith(vendor.lower().split()[0]):
            name = f"{vendor} {name}"
        drv = _driver(dev)
        problem = "" if drv or cat == "System devices" else \
            "The drivers for this device are not installed. (Code 28)"
        bus, slot = dev.name.split(":")[1], dev.name.split(":")[2]
        out.append(Device(name, cat, vendor, f"PCI bus {int(bus, 16)}, device {int(slot.split('.')[0], 16)}, "
                                             f"function {int(slot.split('.')[1], 16)}", drv, str(dev),
                          [f"PCI\\VEN_{vid.upper()}&DEV_{did.upper()}", read(dev / "modalias")], problem))
    return out


def usb_devices() -> list[Device]:
    vendors, names = _ids(_ids_file("usb"))
    out = []
    base = SYS / "bus/usb/devices"
    for dev in sorted(base.iterdir()) if base.is_dir() else []:
        if ":" in dev.name:
            continue                               # interfaces
        vid, pid = read(dev / "idVendor").lower(), read(dev / "idProduct").lower()
        if not vid:
            continue
        product = read(dev / "product")
        maker = read(dev / "manufacturer") or _short_vendor(vendors.get(vid, ""))
        if dev.name.startswith("usb"):
            speed = read(dev / "speed")
            name = {"480": "USB 2.0 Root Hub", "5000": "USB 3.0 Root Hub", "10000": "USB 3.1 Root Hub",
                    "20000": "USB 3.2 Root Hub"}.get(speed, "USB Root Hub")
            out.append(Device(name, "Universal Serial Bus controllers", maker, f"Bus {read(dev / 'busnum')}",
                              "hub", str(dev), [f"USB\\VID_{vid.upper()}&PID_{pid.upper()}"]))
            continue
        classes = {read(i / "bInterfaceClass") for i in dev.glob(f"{dev.name}:*")}
        cls = read(dev / "bDeviceClass")
        name = product or names.get((vid, pid)) or f"USB device {vid}:{pid}"
        if "09" in (cls,) or classes == {"09"}:
            cat, name = "Universal Serial Bus controllers", "Generic USB Hub" if not product else product
        elif "e0" in classes:
            cat = "Bluetooth Radios"
        elif "01" in classes:
            cat = "Sound, video and game controllers"
        elif "08" in classes:
            cat = "Universal Serial Bus controllers"
            name = "USB Mass Storage Device"
        elif "03" in classes:
            cat = "Human Interface Devices"
            name = f"USB Input Device ({name})" if product else "USB Input Device"
        elif "02" in classes or "0a" in classes:
            cat = "Ports (COM & LPT)"
        elif "0e" in classes:
            cat = "Sound, video and game controllers"
        else:
            cat = "Universal Serial Bus controllers"
        drivers = {_driver(i) for i in dev.glob(f"{dev.name}:*")} - {""}
        out.append(Device(name, cat, maker, f"Port {dev.name}", ", ".join(sorted(drivers)), str(dev),
                          [f"USB\\VID_{vid.upper()}&PID_{pid.upper()}", read(dev / "serial")]))
    return out


def input_devices() -> list[Device]:
    out = []
    for block in read(PROC / "bus/input/devices").split("\n\n"):
        name = re.search(r'N: Name="([^"]*)"', block)
        handlers = re.search(r"H: Handlers=(.*)", block)
        phys = re.search(r"P: Phys=(.*)", block)
        sysfs = re.search(r"S: Sysfs=(.*)", block)
        if not name or not handlers:
            continue
        n, h = name.group(1), handlers.group(1)
        ev = re.search(r"B: EV=(\w+)", block)
        key = re.search(r"B: KEY=([\w ]+)", block)
        lname = n.lower()
        if "mouse" in h or "touchpad" in lname or "trackpoint" in lname:
            cat = "Mice and other pointing devices"
            pretty = "HID-compliant mouse" if "usb" in (phys.group(1) if phys else "") else n
        elif "kbd" in h and key and len(key.group(1).replace(" ", "")) > 20 and "leds" in h:
            cat, pretty = "Keyboards", "HID Keyboard Device" if "usb" in (phys.group(1) if phys else "") else n
        elif "js" in h or "gamepad" in lname or "controller" in lname:
            cat, pretty = "Human Interface Devices", f"Game controller ({n})"
        else:
            continue
        out.append(Device(pretty, cat, "", phys.group(1) if phys else "", "",
                          ("/sys" + sysfs.group(1)) if sysfs else "", [n], extra={"name": n, "events": ev.group(1) if ev else ""}))
    seen, uniq = set(), []
    for d in out:
        k = (d.category, d.ids[0])
        if k not in seen:
            seen.add(k)
            uniq.append(d)
    return uniq


def monitors() -> list[Device]:
    out = []
    base = SYS / "class/drm"
    for con in sorted(base.glob("card*-*")) if base.is_dir() else []:
        if read(con / "status") != "connected":
            continue
        name = "Generic PnP Monitor"
        maker = ""
        try:
            edid = (con / "edid").read_bytes()
        except OSError:
            edid = b""
        if len(edid) >= 128:
            code = int.from_bytes(edid[8:10], "big")
            maker = "".join(chr(((code >> s) & 0x1F) + 64) for s in (10, 5, 0))
            for i in range(54, 126, 18):
                if edid[i:i + 3] == b"\x00\x00\x00" and edid[i + 3] == 0xFC:
                    name = edid[i + 5:i + 18].split(b"\n")[0].decode(errors="replace").strip() or name
        out.append(Device(name, "Monitors", maker, con.name.split("-", 1)[1], "", str(con)))
    return out


def disks() -> list[Device]:
    out = []
    try:
        r = subprocess.run(["lsblk", "-J", "-d", "-o", "NAME,MODEL,VENDOR,TYPE,TRAN,SIZE,SERIAL"], capture_output=True,
                           text=True, timeout=5)
        rows = json.loads(r.stdout or "{}").get("blockdevices", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        rows = []
    for d in rows:
        if d.get("type") == "disk" and not str(d.get("name", "")).startswith(("zram", "loop", "ram")):
            vend = (d.get("vendor") or "").strip()
            vend = "" if vend.startswith("0x") or vend.upper() == "ATA" else vend
            model = " ".join(x for x in (vend, (d.get("model") or "").strip()) if x)
            name = model or d["name"]
            if d.get("tran") == "usb":
                name += " USB Device"
            out.append(Device(name, "Disk drives", (d.get("vendor") or "").strip(), f"/dev/{d['name']}",
                              "", f"/sys/block/{d['name']}", [d.get("serial") or ""], extra={"size": d.get("size")}))
        elif d.get("type") == "rom":
            out.append(Device((d.get("model") or "CD/DVD drive").strip(), "DVD/CD-ROM drives",
                              (d.get("vendor") or "").strip(), f"/dev/{d['name']}", "sr_mod"))
    return out


def processors() -> list[Device]:
    name = cpu_name()
    return [Device(name, "Processors", name.split()[0] if name else "", f"CPU {i}", "processor")
            for i in range(os.cpu_count() or 1)]


def batteries() -> list[Device]:
    out = []
    base = SYS / "class/power_supply"
    for ps in sorted(base.iterdir()) if base.is_dir() else []:
        typ = read(ps / "type")
        if typ == "Battery" and read(ps / "scope") != "Device":
            out.append(Device("Microsoft ACPI-Compliant Control Method Battery".replace("Microsoft ", ""),
                              "Batteries", read(ps / "manufacturer"), ps.name, "", str(ps)))
        elif typ == "Mains":
            out.append(Device("AC Adapter", "Batteries", "", ps.name, "", str(ps)))
    return out


def audio_endpoints() -> list[Device]:
    out = []
    for line in read(PROC / "asound/cards").splitlines():
        m = re.match(r"\s*(\d+)\s+\[(\S+)\s*\]:\s*(.*?)\s+-\s+(.*)", line)
        if m:
            out.append(Device(m.group(4).strip(), "Audio inputs and outputs", "", f"Card {m.group(1)}",
                              m.group(3).strip()))
    return out


def network_names() -> dict[str, str]:
    """PCI/USB sysfs device path -> interface name (enp3s0, wlan0)."""
    out = {}
    base = SYS / "class/net"
    for iface in base.iterdir() if base.is_dir() else []:
        dev = iface / "device"
        if dev.exists():
            out[os.path.realpath(dev)] = iface.name
    return out


def computer_device() -> Device:
    efi = (SYS / "firmware/efi").exists()
    return Device("ACPI x64-based PC" if not efi else "ACPI x64-based PC (UEFI)", "Computer")


def all_devices() -> dict[str, list[Device]]:
    devs = [computer_device()] + pci_devices() + usb_devices() + input_devices() + monitors() + disks() + \
        processors() + batteries() + audio_endpoints()
    nets = network_names()
    for d in devs:
        if d.category == "Network adapters" and d.sysfs:
            iface = nets.get(os.path.realpath(d.sysfs))
            if iface:
                d.extra["interface"] = iface
    groups: dict[str, list[Device]] = {}
    for d in devs:
        groups.setdefault(d.category, []).append(d)
    for k in groups:
        groups[k].sort(key=lambda d: d.name.lower())
    return dict(sorted(groups.items()))


def driver_info(driver: str) -> dict[str, str]:
    if not driver or not shutil.which("modinfo"):
        return {}
    try:
        r = subprocess.run(["modinfo", driver], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return {}
    out = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition(":")
        k = k.strip()
        if k in ("filename", "version", "license", "description", "author", "srcversion", "vermagic") and k not in out:
            out[k] = v.strip()
    return out
