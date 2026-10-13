"""
Drive discovery for the Classic 7 Computer window (no GUI code).

Uses `lsblk` for disks and partitions and /proc/self/mountinfo for network shares.
CLASSIC7_LSBLK_JSON and CLASSIC7_MOUNTINFO can point at sample files for testing.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

HARD_DISK, REMOVABLE, NETWORK = "Hard Disk Drives", "Devices with Removable Storage", "Network Location"
GROUP_ORDER = [HARD_DISK, REMOVABLE, NETWORK]

LSBLK_COLUMNS = "PATH,NAME,LABEL,FSTYPE,MOUNTPOINTS,SIZE,FSAVAIL,FSSIZE,RM,HOTPLUG,TYPE,TRAN,PKNAME,PARTTYPENAME,MODEL,UUID,PARTUUID"

# Filesystems that are not something a user browses
SKIP_FSTYPES = {"swap", "crypto_LUKS", "LVM2_member", "linux_raid_member", "zfs_member", "BitLocker",
                "squashfs", "erofs", "iso9660_hidden"}
SKIP_PARTTYPES = {"EFI System", "BIOS boot", "Microsoft reserved", "Microsoft basic data (recovery)",
                  "Windows recovery environment", "Linux swap"}
BOOT_MOUNTS = ("/boot", "/boot/efi", "/efi")
SYSTEM_MOUNTS = ("/", "/sysroot")
NETWORK_FSTYPES = {"cifs", "smb3", "smbfs", "nfs", "nfs4", "fuse.sshfs", "sshfs", "9p", "fuse.rclone", "davfs"}


@dataclass
class Drive:
    key: str                 # stable id (device path or mount point)
    name: str                # "Local Disk (Games)"
    group: str               # one of GROUP_ORDER
    kind: str                # "Local Disk", "Removable Disk", "CD Drive", "Network Drive", "System"
    icon: str                # freedesktop icon name
    device: str | None       # /dev/... (None for network shares)
    parent: str | None       # parent disk, for power-off
    mountpoint: str | None   # where to open it, None if not mounted
    fstype: str | None
    total: int | None
    free: int | None
    label: str | None
    letter: str | None = None   # "C", "D", ... (Disk Management drive letters)

    @property
    def mounted(self) -> bool:
        return self.mountpoint is not None

    @property
    def used_fraction(self) -> float | None:
        if self.total and self.free is not None and self.total > 0:
            return max(0.0, min(1.0, 1 - self.free / self.total))
        return None


def human(n: int | None) -> str:
    if n is None:
        return "?"
    units = ["bytes", "KB", "MB", "GB", "TB", "PB"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            if u == "bytes":
                return f"{int(v)} bytes"
            return f"{v:.0f} {u}" if v >= 100 else f"{v:.1f} {u}" if v >= 10 else f"{v:.2f} {u}"
        v /= 1024
    return f"{n} bytes"


def free_text(d: Drive) -> str:
    if d.kind == "CD Drive" and not d.total:
        return "No disc"
    if not d.mounted:
        return f"Not opened yet · {human(d.total)}" if d.total else "Not opened yet"
    if d.total is None:
        return ""
    return f"{human(d.free)} free of {human(d.total)}"


def _bool(v) -> bool:
    return v in (True, 1, "1", "true")


def _lsblk() -> list[dict]:
    sample = os.environ.get("CLASSIC7_LSBLK_JSON")
    if sample:
        with open(sample) as f:
            data = json.load(f)
    else:
        out = subprocess.run(["lsblk", "-J", "-l", "-b", "-o", LSBLK_COLUMNS],
                             capture_output=True, text=True, check=False).stdout
        data = json.loads(out or '{"blockdevices": []}')
    return data.get("blockdevices", [])


def _mountinfo() -> list[tuple[str, str, str]]:
    """(source, mountpoint, fstype) for every mount."""
    path = os.environ.get("CLASSIC7_MOUNTINFO", "/proc/self/mountinfo")
    out = []
    try:
        with open(path) as f:
            for line in f:
                left, _, right = line.partition(" - ")
                fields = left.split()
                rfields = right.split()
                if len(fields) >= 5 and len(rfields) >= 2:
                    mp = fields[4].encode().decode("unicode_escape")
                    out.append((rfields[1], mp, rfields[0]))
    except OSError:
        pass
    return out


def _usage(path: str) -> tuple[int | None, int | None]:
    try:
        u = shutil.disk_usage(path)
        return u.total, u.free
    except OSError:
        return None, None


def _pick_mount(mounts: list[str]) -> tuple[str | None, bool]:
    """Choose where to open a device. Returns (path, is_system)."""
    mounts = [m for m in mounts if m]
    if not mounts:
        return None, False
    if any(m in SYSTEM_MOUNTS for m in mounts):
        return "/", True
    for preferred in ("/home", "/var/home"):
        if preferred in mounts:
            return preferred, False
    return sorted(mounts, key=len)[0], False


def _letters():
    """Drive letters from Disk Management: (fstab entries, function mountpoint -> letter)."""
    try:
        import disks
        return disks.read_fstab(), disks.letter_of_mount
    except Exception:  # noqa: BLE001 - letters are a nicety
        return [], lambda _mp: None


def _fstab_letter(entries, d: dict) -> str | None:
    for e in entries:
        if not e.letter:
            continue
        spec = e.spec.strip('"')
        for key, val in (("UUID=", d.get("uuid")), ("PARTUUID=", d.get("partuuid"))):
            if val and spec.lower() == (key + val).lower():
                return e.letter
    return None


def list_drives() -> list[Drive]:
    devices = _lsblk()
    entries, letter_of_mount = _letters()
    by_name = {d.get("name"): d for d in devices}
    drives: list[Drive] = []

    for d in devices:
        dtype = d.get("type")
        name = d.get("name") or ""
        fstype = d.get("fstype")
        mounts = [m for m in (d.get("mountpoints") or []) if m]
        if name.startswith(("loop", "zram", "ram")) or dtype not in ("part", "disk", "crypt", "lvm", "rom"):
            continue
        if fstype in SKIP_FSTYPES or d.get("parttypename") in SKIP_PARTTYPES:
            continue
        if mounts and all(m.startswith(BOOT_MOUNTS) for m in mounts):
            continue
        if not mounts and (d.get("label") or "").upper() in ("EFI", "BOOT", "SYSTEM RESERVED", "RECOVERY"):
            continue

        parent = by_name.get(d.get("pkname")) or {}
        # removable if the device or the disk it sits on says so, or it is USB
        removable = (_bool(d.get("rm")) or _bool(d.get("hotplug")) or _bool(parent.get("rm"))
                     or _bool(parent.get("hotplug")) or (d.get("tran") or parent.get("tran")) == "usb")

        if dtype == "rom":
            kind, group, icon = "CD Drive", REMOVABLE, "media-optical"
            if not fstype:
                mounts = []
        elif not fstype:
            continue  # whole disk with partitions, or empty space
        elif removable:
            kind, group, icon = "Removable Disk", REMOVABLE, "drive-removable-media-usb"
        else:
            kind, group, icon = "Local Disk", HARD_DISK, "drive-harddisk"

        mountpoint, is_system = _pick_mount(mounts)
        letter = None
        for m in mounts:
            letter = letter or letter_of_mount(m)
        if letter:
            mountpoint = next(m for m in mounts if letter_of_mount(m) == letter)
        letter = letter or _fstab_letter(entries, d)
        label = d.get("label")
        size = d.get("fssize") or d.get("size")
        if is_system:
            icon = "drive-harddisk-system"
            letter = "C"
            display = "Local Disk (C:)"
        elif kind == "CD Drive":
            display = f"DVD Drive ({label})" if label else "DVD Drive"
        elif letter:
            display = f"{label or kind} ({letter}:)"
        else:
            # Without a drive letter, the label stands in for it
            display = f"{kind} ({label or human(int(size) if size else None)})"

        total = size
        free = d.get("fsavail")
        if mountpoint and (free is None or total is None):
            t, f = _usage(mountpoint if not is_system else "/sysroot" if os.path.isdir("/sysroot") else "/")
            total, free = t or total, f
        drives.append(Drive(
            key=d.get("path") or name, name=display, group=group, kind=kind, icon=icon,
            device=d.get("path"), parent=parent.get("path"), mountpoint=mountpoint, fstype=fstype,
            total=int(total) if total else None, free=int(free) if free is not None else None, label=label,
            letter=letter))

    # Network shares (mapped drives get their letter, like "Data (\\30.11.0.2) (Z:)")
    mappings = _mappings()
    by_folder = {os.path.realpath(m.folder): m for m in mappings}
    seen = set()
    for source, mp, fstype in _mountinfo():
        if fstype not in NETWORK_FSTYPES or mp in seen:
            continue
        seen.add(mp)
        total, free = _usage(mp)
        share = source.replace("\\", "/").rstrip("/")
        title = share.split("/")[-1] or share
        host = share.split("//")[-1].split("/")[0].split(":")[0] if "//" in share or ":" in share else ""
        m = by_folder.get(os.path.realpath(mp))
        name = m.label if m else (f"{title} ({host})" if host else title)
        drives.append(Drive(
            key=mp, name=name, group=NETWORK, kind="Network Drive",
            icon="network-server", device=None, parent=None, mountpoint=mp, fstype=fstype,
            total=total, free=free, label=title))
    # mapped drives that are not connected right now (Windows shows them with a red X)
    mounted = {os.path.realpath(mp) for mp in seen}
    for m in mappings:
        if os.path.realpath(m.folder) not in mounted:
            drives.append(Drive(
                key=f"netdrive:{m.letter}", name=m.label, group=NETWORK, kind="Disconnected Network Drive",
                icon="network-server", device=None, parent=None, mountpoint=None, fstype="cifs",
                total=None, free=None, label=m.letter))

    drives.sort(key=lambda x: (GROUP_ORDER.index(x.group), x.letter is None, x.letter or "", x.name.lower()))
    return drives


def _mappings():
    try:
        import netdrive
        return netdrive.load()
    except Exception:  # noqa: BLE001 - the Computer window works without mapped drives
        return []


def mapping_for(drive: Drive):
    """The Map Network Drive entry behind a network tile, or None."""
    for m in _mappings():
        if drive.key == f"netdrive:{m.letter}" or (
                drive.mountpoint and os.path.realpath(drive.mountpoint) == os.path.realpath(m.folder)):
            return m
    return None


# --- actions -------------------------------------------------------------------------
def mount(drive: Drive) -> tuple[bool, str]:
    """Mount via UDisks (may show a password prompt for internal disks)."""
    if not drive.device:
        return False, "Nothing to mount"
    res = subprocess.run(["udisksctl", "mount", "-b", drive.device], capture_output=True, text=True)
    if res.returncode != 0:
        return False, (res.stderr or res.stdout).strip()
    # "Mounted /dev/sdb1 at /run/media/user/LABEL"
    out = res.stdout.strip()
    return True, out.split(" at ", 1)[1].rstrip(".") if " at " in out else ""


def eject(drive: Drive) -> tuple[bool, str]:
    """Unmount, then power off removable disks (like "Safely Remove")."""
    if not drive.device:
        m = mapping_for(drive)
        if m is not None:
            import netdrive
            try:
                netdrive.disconnect(m)
                return True, ""
            except netdrive.DriveError as e:
                return False, str(e)
        res = subprocess.run(["umount", drive.mountpoint or ""], capture_output=True, text=True)
        return res.returncode == 0, res.stderr.strip()
    if drive.kind == "CD Drive":
        res = subprocess.run(["eject", drive.device], capture_output=True, text=True)
        return res.returncode == 0, res.stderr.strip()
    if drive.mounted:
        res = subprocess.run(["udisksctl", "unmount", "-b", drive.device], capture_output=True, text=True)
        if res.returncode != 0:
            return False, (res.stderr or res.stdout).strip()
    if drive.kind == "Removable Disk" and drive.parent:
        subprocess.run(["udisksctl", "power-off", "-b", drive.parent], capture_output=True, text=True)
    return True, ""


def system_summary() -> dict[str, str]:
    info = {"name": os.uname().nodename, "cpu": "", "memory": ""}
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    info["cpu"] = " ".join(line.split(":", 1)[1].split())
                    break
    except OSError:
        pass
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    kb = int(line.split()[1])
                    info["memory"] = f"{kb / 1024 / 1024:.1f} GB"
                    break
    except OSError:
        pass
    return info
