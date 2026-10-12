"""Map Network Drive: SMB/CIFS shares mounted as ordinary folders in ~/Network.

A mapped drive is mounted by the kernel (mount.cifs, through the root helper and pkexec),
so every program sees normal files, and Dolphin does not have to talk SMB itself.
Mappings live in ~/.config/classic7/netdrives.json; passwords, if any, in a 0600 file per
drive in ~/.config/classic7/netdrives/ (the format mount.cifs reads).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

HELPER = os.environ.get("CLASSIC7_NETDRIVE_HELPER", "/usr/libexec/classic7-netdrive-helper")
LETTERS = "ZYXWVUTSRQPONMLKJIHGFED"


class DriveError(Exception):
    pass


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "classic7"


def store() -> Path:
    return config_dir() / "netdrives.json"


def cred_dir() -> Path:
    return config_dir() / "netdrives"


def network_dir() -> Path:
    return Path.home() / "Network"


# ---- paths ------------------------------------------------------------------------------------
def to_unc(text: str) -> str:
    """\\\\server\\share\\dir, //server/share, smb://server/share -> //server/share/dir"""
    t = text.strip()
    t = re.sub(r"^smb:", "", t, flags=re.I)
    t = t.replace("\\", "/")
    t = "//" + t.lstrip("/")
    return t.rstrip("/")


def to_windows(unc: str) -> str:
    return "\\\\" + unc.lstrip("/").replace("/", "\\")


def split_unc(unc: str) -> tuple[str, str]:
    """//server/share/dir -> (server, share/dir)"""
    m = re.match(r"^//([^/]+)/(.+)$", unc)
    if not m:
        raise DriveError("Enter the folder as \\\\server\\share, for example \\\\30.11.0.2\\Data.")
    server, rest = m.groups()
    if not re.match(r"^[A-Za-z0-9._-]+$", server):
        raise DriveError(f"\"{server}\" is not a valid server name or address.")
    if "," in rest:
        raise DriveError("Share names with commas can't be mapped.")
    return server, rest


def safe_name(text: str) -> str:
    return re.sub(r"[^\w .()-]+", "_", text).strip() or "share"


# ---- mappings ---------------------------------------------------------------------------------
@dataclass
class Mapping:
    letter: str               # "Z"
    unc: str                  # //server/share
    folder: str               # /home/user/Network/Z - share (server)
    reconnect: bool = True
    user: str = ""            # empty = this computer's user / guest
    domain: str = ""

    @property
    def label(self) -> str:
        server, share = split_unc(self.unc)
        return f"{share.split('/')[-1]} ({to_windows('//' + server)}) ({self.letter}:)"

    @property
    def cred_file(self) -> Path:
        return cred_dir() / f"{self.letter}.cred"

    @property
    def connected(self) -> bool:
        return is_mounted(self.folder)


def load() -> list[Mapping]:
    try:
        data = json.loads(store().read_text())
        return [Mapping(**{k: v for k, v in d.items() if k in Mapping.__dataclass_fields__}) for d in data]
    except (OSError, ValueError, TypeError):
        return []


def save(maps: list[Mapping]):
    store().parent.mkdir(parents=True, exist_ok=True)
    store().write_text(json.dumps([asdict(m) for m in maps], indent=2) + "\n")


def free_letters(maps: list[Mapping] | None = None) -> list[str]:
    used = {m.letter for m in (maps if maps is not None else load())}
    return [l for l in LETTERS if l not in used]


def is_mounted(folder: str) -> bool:
    try:
        target = os.path.realpath(folder)
        with open(os.environ.get("CLASSIC7_MOUNTINFO", "/proc/self/mountinfo")) as f:
            for line in f:
                parts = line.split()
                mp = re.sub(r"\\([0-7]{3})", lambda o: chr(int(o.group(1), 8)), parts[4])
                if os.path.realpath(mp) == target:
                    return True
    except OSError:
        pass
    return False


# ---- credentials ------------------------------------------------------------------------------
def write_credentials(m: Mapping, password: str):
    cred_dir().mkdir(parents=True, exist_ok=True)
    os.chmod(cred_dir(), 0o700)
    lines = [f"username={m.user}", f"password={password}"]
    if m.domain:
        lines.append(f"domain={m.domain}")
    fd = os.open(m.cred_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(m.cred_file, 0o600)


def forget_credentials(m: Mapping):
    try:
        m.cred_file.unlink()
    except OSError:
        pass


# ---- mounting ---------------------------------------------------------------------------------
def _helper(*args: str) -> subprocess.CompletedProcess:
    cmd = [HELPER, *args] if os.geteuid() == 0 else ["pkexec", HELPER, *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as e:
        raise DriveError("The server did not answer in time.") from e
    except OSError as e:
        raise DriveError(str(e)) from e


def explain(stderr: str) -> str:
    """mount.cifs messages in plain words."""
    s = stderr.lower()
    if "permission denied" in s or "error(13)" in s:
        return "access-denied"
    if "no such file" in s or "error(2)" in s:
        return "The share doesn't exist on that server. Check the share name (Browse… lists them)."
    if "host is down" in s or "error(112)" in s or "no route" in s or "error(113)" in s or "timed out" in s:
        return "The server can't be reached. Check the address and that it is switched on and on the network."
    if "could not resolve" in s or "unable to find suitable address" in s:
        return "The server name can't be found. Try its IP address instead (\\\\30.11.0.2\\share)."
    if "error(95)" in s or "operation not supported" in s:
        return "The server's SMB version isn't supported (very old servers need SMB1, which is switched off)."
    if "not authorized" in s or "dismissed" in s or "error executing command as another user" in s:
        return "Connecting was not allowed."
    return stderr.strip().splitlines()[-1] if stderr.strip() else "The network drive could not be connected."


def connect(m: Mapping):
    folder = Path(m.folder)
    folder.mkdir(parents=True, exist_ok=True)
    if is_mounted(m.folder):
        return
    args = ["mount", m.unc, str(folder)]
    if m.cred_file.exists():
        args.append(str(m.cred_file))
    r = _helper(*args)
    if r.returncode != 0:
        raise DriveError(explain(r.stderr or r.stdout))


def disconnect(m: Mapping, forget: bool = True):
    if is_mounted(m.folder):
        r = _helper("umount", m.folder)
        if r.returncode != 0:
            raise DriveError(explain(r.stderr or r.stdout))
    if forget:
        maps = [x for x in load() if x.letter != m.letter]
        save(maps)
        forget_credentials(m)
        try:
            Path(m.folder).rmdir()          # only if empty (not mounted any more)
        except OSError:
            pass


def new_mapping(unc_text: str, letter: str, reconnect: bool = True, user: str = "", domain: str = "") -> Mapping:
    unc = to_unc(unc_text)
    server, share = split_unc(unc)
    name = safe_name(share.split("/")[-1])
    folder = network_dir() / f"{letter} - {name} ({safe_name(server)})"
    return Mapping(letter=letter, unc=unc, folder=str(folder), reconnect=reconnect, user=user, domain=domain)


def add(m: Mapping, password: str | None = None):
    """Connect a new mapping and remember it. With password=None, connect as guest / with a
    remembered password."""
    if password is not None:
        write_credentials(m, password)
    try:
        connect(m)
    except DriveError:
        if password is not None:
            forget_credentials(m)
        try:
            Path(m.folder).rmdir()
        except OSError:
            pass
        raise
    maps = [x for x in load() if x.letter != m.letter] + [m]
    maps.sort(key=lambda x: x.letter)
    save(maps)


def reconnect_all() -> list[tuple[Mapping, str]]:
    """At sign-in: connect every mapping marked "Reconnect at sign-in". Returns the failures."""
    failed = []
    for m in load():
        if not m.reconnect or m.connected:
            continue
        try:
            connect(m)
        except DriveError as e:
            failed.append((m, str(e)))
    return failed


# ---- browsing ---------------------------------------------------------------------------------
def list_shares(server: str, user: str = "", password: str = "", domain: str = "") -> list[tuple[str, str]]:
    """[(share, comment)] of the disk shares on a server (smbclient -L)."""
    if not shutil.which("smbclient"):
        raise DriveError("smbclient is not installed, so shares can't be listed. Type the share name instead.")
    if not re.match(r"^[A-Za-z0-9._-]+$", server):
        raise DriveError("Enter a server name or IP address.")
    cmd = ["smbclient", "-g", "-L", f"//{server}", "--option=client min protocol=SMB2"]
    env = dict(os.environ, LC_ALL="C")
    if user:
        cmd += ["-U", f"{domain + '/' if domain else ''}{user}"]
        env["PASSWD"] = password
    else:
        cmd += ["-N"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=env)
    except subprocess.TimeoutExpired as e:
        raise DriveError("The server did not answer.") from e
    out = r.stdout + r.stderr
    shares = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 2 and parts[0] == "Disk" and not parts[1].endswith("$"):
            shares.append((parts[1], parts[2] if len(parts) > 2 else ""))
    if not shares and r.returncode != 0:
        if "NT_STATUS_ACCESS_DENIED" in out or "NT_STATUS_LOGON_FAILURE" in out:
            raise DriveError("access-denied")
        if "NT_STATUS_HOST_UNREACHABLE" in out or "NT_STATUS_IO_TIMEOUT" in out or "Connection to" in out:
            raise DriveError("The server can't be reached.")
        raise DriveError(out.strip().splitlines()[-1] if out.strip() else "No shares found.")
    return sorted(shares, key=lambda s: s[0].lower())
