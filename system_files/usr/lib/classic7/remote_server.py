"""Remote Desktop to this computer (KDE's KRdp server), set the way Windows 7's System Properties >
Remote sets it (no GUI code here; the Remote tab in system_app.py uses it):

 * on or off for the account that is logged in, started at every login (KRdp's user service
   app-org.kde.krdpserver.service);
 * logging in with that account's own Classic 7 password (KRdp's "system user", through PAM);
 * no question on this computer's screen when someone connects, as in Windows (KRdp's --plasma mode,
   which KWin allows for krdpserver);
 * a TLS certificate that lasts ten years, so clients can remember it (KDE's settings page makes one
   that lasts a day);
 * the firewall exception (firewalld's "rdp" service) through classic7-firewall-helper.

Remote Desktop shows the session of the account logged in here; nobody can connect while the
computer waits at the login screen."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

UNIT = "app-org.kde.krdpserver.service"
CONFIG_FILE = "krdpserverrc"
HOME = Path.home()
DROPIN = (Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "systemd" / "user" /
          f"{UNIT}.d" / "classic7.conf")
CERT_DIR = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local" / "share") / "krdpserver"
FIREWALL_HELPER = "/usr/libexec/classic7-firewall-helper"
PORT = 3389


def _run(*args: str, timeout: float = 20) -> tuple[int, str]:
    try:
        r = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def available() -> bool:
    return bool(shutil.which("krdpserver"))


def read_config(key: str, default: str = "") -> str:
    code, out = _run("kreadconfig6", "--file", CONFIG_FILE, "--group", "General", "--key", key,
                     "--default", default)
    return out if code == 0 else default


def write_config(key: str, value: str) -> None:
    _run("kwriteconfig6", "--file", CONFIG_FILE, "--group", "General", "--key", key, value)


def systemctl(*args: str) -> tuple[int, str]:
    return _run("systemctl", "--user", *args)


def state() -> dict:
    enabled = systemctl("is-enabled", UNIT)[1].splitlines()[:1] == ["enabled"]
    active = systemctl("is-active", UNIT)[1].splitlines()[:1] == ["active"]
    try:
        port = int(read_config("ListenPort", str(PORT)))
    except ValueError:
        port = PORT
    users = [u for u in read_config("Users", "").split(",") if u.strip()]
    return {"enabled": enabled, "active": active, "system_user": read_config("SystemUserEnabled") == "true",
            "users": users, "port": port, "unattended": DROPIN.exists()}


def _certificate_ok(cert: str, key: str) -> bool:
    if not (cert and key and Path(cert).is_file() and Path(key).is_file()):
        return False
    # still valid for at least a week
    return _run("openssl", "x509", "-checkend", str(7 * 86400), "-noout", "-in", cert)[0] == 0


def ensure_certificate() -> tuple[bool, str]:
    cert, key = read_config("Certificate"), read_config("CertificateKey")
    if _certificate_ok(cert, key):
        return True, ""
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert, key = str(CERT_DIR / "classic7.crt"), str(CERT_DIR / "classic7.key")
    name = socket.gethostname() or "classic7"
    code, out = _run("openssl", "req", "-nodes", "-new", "-x509", "-newkey", "rsa:2048", "-keyout", key, "-out", cert,
                     "-days", "3650", "-batch", "-subj", f"/CN={name}")
    if code != 0 or not Path(cert).is_file():
        return False, f"The certificate could not be made: {out}"
    os.chmod(key, 0o600)
    write_config("Certificate", cert)
    write_config("CertificateKey", key)
    return True, ""


def allow(unattended: bool = True) -> tuple[bool, str]:
    """Switch Remote Desktop on for this account; (worked, message)."""
    if not available():
        return False, "Remote Desktop (KRdp) is not installed."
    ok, msg = ensure_certificate()
    if not ok:
        return False, msg
    write_config("SystemUserEnabled", "true")
    write_config("Autostart", "true")
    if unattended:
        DROPIN.parent.mkdir(parents=True, exist_ok=True)
        DROPIN.write_text("# Classic 7 (System Properties > Remote): no question on the screen when someone connects\n"
                          "[Service]\nExecStart=\nExecStart=/usr/bin/krdpserver --plasma\n")
    elif DROPIN.exists():
        DROPIN.unlink()
    systemctl("daemon-reload")
    code, out = systemctl("enable", UNIT)
    if code != 0:
        return False, f"Remote Desktop could not be switched on: {out}"
    code, out = systemctl("restart", UNIT)
    if code != 0:
        return False, f"Remote Desktop could not be started: {out}\n\n{journal_tail()}"
    return True, ""


def disallow() -> tuple[bool, str]:
    write_config("Autostart", "false")
    code, out = systemctl("disable", "--now", UNIT)
    return (code == 0), (out if code else "")


def journal_tail(lines: int = 6) -> str:
    return _run("journalctl", "--user", "-u", UNIT, "-n", str(lines), "--no-pager", "-o", "cat")[1]


# ---- the firewall -------------------------------------------------------------------------------------
def _port_in(ports: list[str], port: int) -> bool:
    for p in ports:
        rng, _sep, proto = p.partition("/")
        if proto and proto != "tcp":
            continue
        lo, _dash, hi = rng.partition("-")
        try:
            if int(lo) <= port <= int(hi or lo):
                return True
        except ValueError:
            continue
    return False


def firewall_status(port: int = PORT) -> tuple[bool | None, str]:
    """(open?, zone): None when firewalld isn't running or can't be asked."""
    if _run("firewall-cmd", "--state")[0] != 0:
        return None, ""
    code, zone = _run("firewall-cmd", "--get-default-zone")
    if code != 0 or not zone:
        return None, ""
    zone = zone.splitlines()[0].strip()
    code, target = _run("firewall-cmd", f"--zone={zone}", "--get-target")
    if code == 0 and target.strip() == "ACCEPT":
        return True, zone
    services = _run("firewall-cmd", f"--zone={zone}", "--list-services")[1].split()
    ports = _run("firewall-cmd", f"--zone={zone}", "--list-ports")[1].split()
    if "rdp" in services and port == PORT:
        return True, zone
    return _port_in(ports, port), zone


def open_firewall(zone: str, port: int = PORT) -> tuple[bool, str]:
    """Through pkexec (an administrator's password); a port other than 3389 opens as a port."""
    change = ({"op": "service", "zone": zone, "name": "rdp", "on": True} if port == PORT
              else {"op": "port", "zone": zone, "port": f"{port}/tcp", "on": True})
    code, out = _run("pkexec", FIREWALL_HELPER, json.dumps([change]), timeout=180)
    return code == 0, out


# ---- how to reach this computer ---------------------------------------------------------------------------
def addresses() -> list[str]:
    code, out = _run("ip", "-4", "-o", "addr", "show", "scope", "global")
    found = []
    if code == 0:
        for line in out.splitlines():
            parts = line.split()
            if "inet" in parts:
                addr = parts[parts.index("inet") + 1].split("/")[0]
                dev = parts[1]
                if not dev.startswith(("docker", "virbr", "veth", "podman", "br-")):
                    found.append(addr)
    return found
