"""Network Connections: reading and changing network adapters through NetworkManager (nmcli).

Everything goes through nmcli, the same backend as Plasma's network applet, so changes made
here show up there and the other way round. Changing a system connection asks for the
administrator password only when NetworkManager's policy wants it (polkit dialog).
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

NMCLI = os.environ.get("CLASSIC7_NMCLI", "nmcli")
SYS_NET = Path(os.environ.get("CLASSIC7_SYS_NET", "/sys/class/net"))
HIDDEN_TYPES = {"loopback", "wifi-p2p", "tun", "dummy"}


class NetError(Exception):
    pass


def available() -> bool:
    return shutil.which(NMCLI) is not None


def run(*args: str, check: bool = True, timeout: int = 60) -> str:
    try:
        r = subprocess.run([NMCLI, *args], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "LC_ALL": "C"})
    except FileNotFoundError as e:
        raise NetError("NetworkManager's command-line tool (nmcli) is not installed.") from e
    except subprocess.TimeoutExpired as e:
        raise NetError("NetworkManager did not answer.") from e
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        msg = re.sub(r"^Error:\s*", "", msg)
        raise NetError(msg or f"nmcli {' '.join(args)} failed ({r.returncode})")
    return r.stdout


# ---- terse output parsing ---------------------------------------------------------------------
def split_terse(line: str) -> list[str]:
    """Split one `nmcli -t` line on unescaped colons and unescape the fields."""
    out, cur, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if ch == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    out.append("".join(cur))
    return out


def parse_fields(text: str) -> dict[str, list[str]]:
    """`nmcli -t ... show` output ("KEY:value" lines) -> {KEY: [values]} (indexed keys like
    IP4.ADDRESS[2] are collected under IP4.ADDRESS, in order)."""
    data: dict[str, list[str]] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.replace("\\:", ":").replace("\\\\", "\\")
        key = re.sub(r"\[\d+\]$", "", key)
        if value in ("", "--"):
            data.setdefault(key, [])
            continue
        data.setdefault(key, []).append(value)
    return data


def first(d: dict[str, list[str]], key: str, default: str = "") -> str:
    v = d.get(key) or []
    return v[0] if v else default


# ---- addresses --------------------------------------------------------------------------------
def prefix_to_mask(prefix: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{int(prefix)}").netmask)


def mask_to_prefix(mask: str) -> int:
    """255.255.255.0 -> 24; raises ValueError for masks with holes (255.0.255.0)."""
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def valid_ip(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
        return True
    except ValueError:
        return False


def classful_mask(ip: str) -> str:
    """What Windows fills in when the mask box gets focus: by address class."""
    try:
        a = int(ip.split(".")[0])
    except (ValueError, IndexError):
        return "255.255.255.0"
    if 1 <= a <= 126:
        return "255.0.0.0"
    if 128 <= a <= 191:
        return "255.255.0.0"
    return "255.255.255.0"


def same_subnet(ip: str, prefix: int, other: str) -> bool:
    try:
        return ipaddress.IPv4Address(other) in ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
    except ValueError:
        return False


# ---- adapters ---------------------------------------------------------------------------------
@dataclass
class Adapter:
    device: str                      # enp3s0
    type: str                        # ethernet, wifi, ...
    state: str                       # connected, disconnected, unavailable, unmanaged, connecting ...
    connection: str = ""             # profile name ("Wired connection 1")
    uuid: str = ""
    description: str = ""            # vendor/product of the network card
    mac: str = ""
    ipv4: list[tuple[str, int]] = field(default_factory=list)   # [(ip, prefix)]
    gateway: str = ""
    dns: list[str] = field(default_factory=list)
    ipv6: list[str] = field(default_factory=list)
    domain: str = ""
    dhcp: dict[str, str] = field(default_factory=dict)          # DHCP4 options
    speed_mbit: int = 0
    carrier: bool | None = None

    @property
    def title(self) -> str:
        return self.connection or {"ethernet": "Local Area Connection", "wifi": "Wireless Network Connection"}.get(
            self.type, self.device)

    @property
    def connected(self) -> bool:
        return self.state.startswith("connected")

    @property
    def disabled(self) -> bool:
        return self.state in ("unmanaged", "unavailable") and self.carrier is not False and not self.connected

    @property
    def status_text(self) -> str:
        if self.connected:
            return "Connected" + (f" · {self.ipv4[0][0]}" if self.ipv4 else "")
        if self.state.startswith("connecting"):
            return "Connecting…"
        if self.carrier is False or self.state == "unavailable":
            return "Network cable unplugged" if self.type == "ethernet" else "Not available"
        if self.state == "unmanaged":
            return "Not managed"
        return "Disabled" if self.state == "disconnected" else self.state.capitalize()

    @property
    def kind(self) -> str:
        return {"ethernet": "Ethernet", "wifi": "Wireless", "bridge": "Bridge", "bond": "Bond",
                "vlan": "VLAN", "wireguard": "WireGuard", "vpn": "VPN"}.get(self.type, self.type.capitalize())


def _read_sys(dev: str, name: str) -> str:
    try:
        return (SYS_NET / dev / name).read_text().strip()
    except OSError:
        return ""


def adapters() -> list[Adapter]:
    out = run("-t", "-f", "DEVICE,TYPE,STATE,CON-UUID,CONNECTION", "device", "status")
    result = []
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) < 5 or f[1] in HIDDEN_TYPES:
            continue
        a = Adapter(device=f[0], type=f[1], state=f[2], uuid=f[3], connection=f[4])
        fill_details(a)
        result.append(a)
    return result


def fill_details(a: Adapter):
    try:
        d = parse_fields(run("-t", "device", "show", a.device, check=False))
    except NetError:
        return
    a.mac = first(d, "GENERAL.HWADDR")
    vendor, product = first(d, "GENERAL.VENDOR"), first(d, "GENERAL.PRODUCT")
    a.description = " ".join(x for x in (vendor, product) if x) or first(d, "GENERAL.DRIVER") or a.kind
    a.ipv4 = []
    for addr in d.get("IP4.ADDRESS", []):
        ip, _, pre = addr.partition("/")
        a.ipv4.append((ip, int(pre or 32)))
    a.gateway = first(d, "IP4.GATEWAY")
    a.dns = list(d.get("IP4.DNS", []))
    a.domain = first(d, "IP4.DOMAIN")
    a.ipv6 = [x for x in d.get("IP6.ADDRESS", [])]
    a.dhcp = {}
    for opt in d.get("DHCP4.OPTION", []):
        k, _, v = opt.partition("=")
        a.dhcp[k.strip()] = v.strip()
    carrier = first(d, "WIRED-PROPERTIES.CARRIER")
    a.carrier = None if not carrier else carrier == "on"
    speed = _read_sys(a.device, "speed")
    a.speed_mbit = int(speed) if speed.lstrip("-").isdigit() and int(speed) > 0 else 0
    if not a.uuid:
        a.uuid = first(d, "GENERAL.CON-UUID")


def statistics(dev: str) -> dict[str, int]:
    keys = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets")
    out = {}
    for k in keys:
        v = _read_sys(dev, f"statistics/{k}")
        out[k] = int(v) if v.isdigit() else 0
    return out


def connectivity() -> str:
    """full, limited, portal, none or unknown."""
    try:
        return run("networking", "connectivity", "check", check=False, timeout=15).strip() or "unknown"
    except NetError:
        return "unknown"


# ---- IPv4 settings of a connection profile ----------------------------------------------------
@dataclass
class IPv4Settings:
    method: str = "auto"                                     # auto, manual, disabled, link-local, shared
    addresses: list[tuple[str, int]] = field(default_factory=list)
    gateway: str = ""
    dns: list[str] = field(default_factory=list)
    ignore_auto_dns: bool = False
    ipv6_method: str = "auto"

    @property
    def dhcp(self) -> bool:
        return self.method == "auto"

    @property
    def manual_dns(self) -> bool:
        return self.method == "manual" or self.ignore_auto_dns


def read_ipv4(uuid: str) -> IPv4Settings:
    d = parse_fields(run("-t", "-f", "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns,ipv4.ignore-auto-dns,"
                         "ipv6.method", "connection", "show", "uuid", uuid))
    s = IPv4Settings()
    s.method = first(d, "ipv4.method", "auto")
    for item in ",".join(d.get("ipv4.addresses", [])).split(","):
        item = item.strip()
        if item:
            ip, _, pre = item.partition("/")
            s.addresses.append((ip, int(pre or 24)))
    s.gateway = first(d, "ipv4.gateway")
    s.dns = [x.strip() for x in ",".join(d.get("ipv4.dns", [])).split(",") if x.strip()]
    s.ignore_auto_dns = first(d, "ipv4.ignore-auto-dns", "no") == "yes"
    s.ipv6_method = first(d, "ipv6.method", "auto")
    return s


def ipv4_modify_args(s: IPv4Settings) -> list[str]:
    """nmcli `connection modify` arguments for these settings."""
    if s.method == "manual":
        args = ["ipv4.method", "manual",
                "ipv4.addresses", ", ".join(f"{ip}/{pre}" for ip, pre in s.addresses),
                "ipv4.gateway", s.gateway or "",
                "ipv4.dns", ",".join(s.dns),
                "ipv4.ignore-auto-dns", "yes"]
    else:
        args = ["ipv4.method", "auto", "ipv4.addresses", "", "ipv4.gateway", ""]
        if s.dns:
            args += ["ipv4.dns", ",".join(s.dns), "ipv4.ignore-auto-dns", "yes"]
        else:
            args += ["ipv4.dns", "", "ipv4.ignore-auto-dns", "no"]
    return args


def write_ipv4(uuid: str, s: IPv4Settings, device: str = "", reconnect: bool = True):
    run("connection", "modify", "uuid", uuid, *ipv4_modify_args(s))
    if reconnect:
        if device:
            run("connection", "up", "uuid", uuid, "ifname", device, timeout=90)
        else:
            run("connection", "up", "uuid", uuid, timeout=90)


def set_ipv6_enabled(uuid: str, enabled: bool):
    run("connection", "modify", "uuid", uuid, "ipv6.method", "auto" if enabled else "disabled")


def ensure_profile(a: Adapter) -> str:
    """The connection profile of an adapter; makes one (like Windows' "Local Area Connection")
    if the adapter has none yet. Returns its UUID."""
    if a.uuid:
        return a.uuid
    out = run("-t", "-f", "NAME,UUID,DEVICE,TYPE", "connection", "show")
    for line in out.splitlines():
        f = split_terse(line)
        if len(f) >= 4 and f[2] == a.device:
            return f[1]
    if a.type != "ethernet":
        raise NetError(f"{a.device} has no connection settings yet. Connect it once first.")
    name = a.title if a.title != a.device else f"Local Area Connection ({a.device})"
    run("connection", "add", "type", "ethernet", "ifname", a.device, "con-name", name)
    for line in run("-t", "-f", "NAME,UUID", "connection", "show").splitlines():
        f = split_terse(line)
        if len(f) >= 2 and f[0] == name:
            return f[1]
    raise NetError("Could not create the connection settings.")


def disable(a: Adapter):
    run("device", "disconnect", a.device)


def enable(a: Adapter):
    if a.state == "unmanaged":
        run("device", "set", a.device, "managed", "yes")
    run("device", "connect", a.device, timeout=90)


def rename(uuid: str, name: str):
    run("connection", "modify", "uuid", uuid, "connection.id", name)


def human_bytes(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit == "bytes" else f"{n:,.1f} {unit}"
        n /= 1024
    return str(n)


def human_speed(mbit: int) -> str:
    if not mbit:
        return "—"
    return f"{mbit / 1000:g} Gbps" if mbit >= 1000 else f"{mbit} Mbps"
