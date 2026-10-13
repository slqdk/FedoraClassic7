"""Disk Management: what is on the disks, which drive letters they have (no GUI code).

Drive letters work like on Windows: a volume with a letter is mounted at /var/mnt/<letter>
at every start-up, through an entry in /etc/fstab that Disk Management writes (with the
root helper, see classic7-disk-helper). C: is the system disk.

CLASSIC7_LSBLK_TREE, CLASSIC7_FSTAB and CLASSIC7_SWAPS can point at sample files for testing.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SECTOR = 512                      # lsblk START and sysfs always count 512-byte sectors
MIB = 1024 * 1024
ALIGN = MIB // SECTOR             # new partitions start on 1 MiB boundaries
LETTER_ROOT = "/var/mnt"          # /mnt is a link to /var/mnt on Fedora Atomic
LETTERS = "DEFGHIJKLMNOPQRSTUVWXY"
MARK = "# classic7-drive "       # comment line above an fstab entry Disk Management owns

COLUMNS = ("PATH,NAME,KNAME,TYPE,SIZE,START,PARTN,PTTYPE,PARTTYPE,PARTTYPENAME,PARTLABEL,"
           "FSTYPE,FSVER,LABEL,UUID,PARTUUID,MOUNTPOINTS,FSAVAIL,FSSIZE,RM,HOTPLUG,TRAN,"
           "MODEL,VENDOR,SERIAL,RO,LOG-SEC,PKNAME")

SYSTEM_MOUNTS = {"/", "/sysroot", "/usr", "/var", "/etc", "/home", "/var/home", "/ostree", "/sysroot/ostree"}
BOOT_MOUNTS = {"/boot", "/boot/efi", "/efi"}
EFI_TYPES = {"c12a7328-f81f-11d2-ba4b-00a0c93ec93b", "0xef"}
MSR_TYPE = "e3c9e316-0b5c-4db8-817d-f92df00215ae"
RECOVERY_TYPES = {"de94bba4-06d1-4d40-a16a-bfd50179d6ac", "0x27"}
BIOS_BOOT = "21686148-6453-6f6e-7420-6e6565644546"
EXTENDED_TYPES = {"0x5", "0xf", "0x85"}

# What a person sees in the File System column
FS_NAMES = {"ntfs": "NTFS", "ntfs3": "NTFS", "vfat": "FAT32", "exfat": "exFAT", "ext4": "ext4",
            "ext3": "ext3", "ext2": "ext2", "btrfs": "Btrfs", "xfs": "XFS", "f2fs": "F2FS",
            "iso9660": "CDFS", "udf": "UDF", "crypto_LUKS": "Encrypted", "LVM2_member": "LVM",
            "swap": "Swap", "BitLocker": "BitLocker", "hfsplus": "HFS+", "apfs": "APFS",
            "zfs_member": "ZFS"}
# File systems Windows can read as well (and why Proton may struggle on them)
WINDOWS_FS = {"ntfs", "ntfs3", "vfat", "exfat"}
# Formats offered by Format... and New Simple Volume, with the program that makes them
FORMATS = [("NTFS", "ntfs", "mkfs.ntfs"), ("exFAT", "exfat", "mkfs.exfat"), ("FAT32", "vfat", "mkfs.vfat"),
           ("ext4", "ext4", "mkfs.ext4"), ("Btrfs", "btrfs", "mkfs.btrfs")]
LABEL_MAX = {"ntfs": 32, "exfat": 15, "vfat": 11, "ext4": 16, "btrfs": 255}


@dataclass
class Region:
    key: str
    kind: str                     # "partition", "volume" (file system on the whole disk), "free"
    disk: "Disk"
    start: int                    # in 512-byte sectors
    sectors: int
    path: str | None = None
    number: int | None = None
    fstype: str | None = None     # the file system people use (inside LUKS/LVM if needed)
    raw_fstype: str | None = None # what is on the partition itself
    label: str | None = None
    uuid: str | None = None
    partuuid: str | None = None
    parttype: str | None = None
    parttypename: str | None = None
    mounts: list[str] = field(default_factory=list)
    fssize: int | None = None
    fsavail: int | None = None
    flags: set[str] = field(default_factory=set)
    letter: str | None = None     # "C", "D", ... or None
    fstab: "FstabEntry | None" = None
    in_extended: bool = False

    @property
    def size(self) -> int:
        return self.sectors * SECTOR

    @property
    def mounted(self) -> bool:
        return bool(self.mounts)

    @property
    def open_path(self) -> str | None:
        if "system" in self.flags:
            return "/"
        if not self.mounts:
            return None
        for m in self.mounts:
            if letter_of_mount(m):
                return m
        for pref in ("/var/home", "/home"):
            if pref in self.mounts:
                return pref
        return sorted(self.mounts, key=len)[0]

    @property
    def free_bytes(self) -> int | None:
        return self.fsavail

    @property
    def capacity(self) -> int:
        return self.fssize or self.size

    @property
    def protected(self) -> bool:
        """Partitions Windows' Disk Management won't let you delete or format either."""
        return bool(self.flags & {"system", "boot", "efi", "swap", "msr", "biosboot", "extended", "busy"})

    def name(self) -> str:
        """'Games (D:)', '(C:)', 'Local Disk' ... as in the Volume column."""
        if self.kind == "free":
            return "Unallocated" if not self.in_extended else "Free space"
        label = self.label or ""
        if self.letter:
            return f"{label} ({self.letter}:)".strip()
        if "efi" in self.flags:
            return label or "EFI System Partition"
        if "msr" in self.flags:
            return "Microsoft Reserved"
        if "recovery" in self.flags:
            return label or "Recovery Partition"
        return label or ""

    def fs_name(self) -> str:
        if self.kind == "free":
            return ""
        fs = self.fstype or self.raw_fstype
        if "msr" in self.flags or "extended" in self.flags:
            return ""
        return FS_NAMES.get(fs or "", (fs or "RAW").upper() if fs else "RAW")

    def status(self) -> str:
        if self.kind == "free":
            return ""
        bits = []
        if "system" in self.flags:
            bits += ["Boot", "System"]
        if "efi" in self.flags:
            bits.append("EFI System Partition")
        if "boot" in self.flags:
            bits.append("Boot Loader")
        if "recovery" in self.flags:
            bits.append("Recovery Partition")
        if "swap" in self.flags:
            bits.append("Page File")
        if "encrypted" in self.flags:
            bits.append("Encrypted")
        if self.kind == "partition" and not ({"efi", "msr", "recovery", "extended"} & self.flags):
            bits.append("Logical Drive" if "logical" in self.flags else "Primary Partition")
        if "extended" in self.flags:
            return "Extended Partition"
        if not bits and self.kind == "volume":
            bits.append("Removable" if self.disk.removable else "Volume")
        return "Healthy (" + ", ".join(bits) + ")" if bits else "Healthy"


@dataclass
class Disk:
    index: int
    path: str
    name: str
    model: str
    size: int
    pttype: str | None            # "gpt", "dos", None
    removable: bool
    tran: str | None
    readonly: bool
    kind: str = "disk"            # "disk" or "rom"
    regions: list[Region] = field(default_factory=list)
    system: bool = False          # holds the running system
    fstype: str | None = None     # set when the whole disk is one file system

    @property
    def sectors(self) -> int:
        return self.size // SECTOR

    @property
    def title(self) -> str:
        return f"CD-ROM {self.index}" if self.kind == "rom" else f"Disk {self.index}"

    @property
    def initialized(self) -> bool:
        return bool(self.pttype or self.fstype or self.kind == "rom")

    def layout(self) -> str:
        return "Removable" if self.removable else "Basic"

    def partition_style(self) -> str:
        return {"gpt": "GUID Partition Table (GPT)", "dos": "Master Boot Record (MBR)"}.get(
            self.pttype or "", "Not initialized" if not self.initialized else "None")


# ---- fstab -----------------------------------------------------------------------------------
@dataclass
class FstabEntry:
    spec: str
    file: str
    vfstype: str
    opts: str
    letter: str | None            # set for entries Disk Management owns
    line: int


def fstab_path() -> str:
    return os.environ.get("CLASSIC7_FSTAB", "/etc/fstab")


def unescape(s: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), s)


def read_fstab(text: str | None = None) -> list[FstabEntry]:
    if text is None:
        try:
            text = Path(fstab_path()).read_text()
        except OSError:
            return []
    out, pending = [], None
    for i, line in enumerate(text.splitlines()):
        s = line.strip()
        if s.startswith(MARK.strip()):
            m = re.match(r"#\s*classic7-drive\s+([A-Z])\b", s)
            pending = m.group(1) if m else None
            continue
        if not s or s.startswith("#"):
            pending = None
            continue
        f = s.split()
        if len(f) >= 3:
            out.append(FstabEntry(unescape(f[0]), unescape(f[1]), f[2], f[3] if len(f) > 3 else "defaults",
                                  pending, i))
        pending = None
    return out


def entry_matches(e: FstabEntry, r: Region) -> bool:
    spec = e.spec
    for key, val in (("UUID=", r.uuid), ("PARTUUID=", r.partuuid), ("LABEL=", r.label)):
        if spec.startswith(key) and val and spec[len(key):].strip('"').lower() == val.lower():
            return True
    for key, val in (("/dev/disk/by-uuid/", r.uuid), ("/dev/disk/by-partuuid/", r.partuuid)):
        if spec.startswith(key) and val and spec[len(key):].lower() == val.lower():
            return True
    return bool(r.path) and spec == r.path


def letter_of_mount(mp: str) -> str | None:
    m = re.fullmatch(r"/(?:var/)?mnt/([A-Za-z])", mp or "")
    root = os.environ.get("CLASSIC7_LETTER_ROOT")
    if not m and root:
        m = re.fullmatch(re.escape(root.rstrip("/")) + r"/([A-Za-z])", mp or "")
    return m.group(1).upper() if m else None


# ---- reading the disks -----------------------------------------------------------------------
def _lsblk() -> list[dict]:
    sample = os.environ.get("CLASSIC7_LSBLK_TREE")
    if sample:
        with open(sample) as f:
            return json.load(f).get("blockdevices", [])
    for cols in (COLUMNS, COLUMNS.replace("PARTN,", "")):
        res = subprocess.run(["lsblk", "-J", "-b", "-o", cols], capture_output=True, text=True)
        if res.returncode == 0:
            devs = json.loads(res.stdout or '{"blockdevices": []}').get("blockdevices", [])
            if not os.path.isdir("/run/udev/data") and os.geteuid() == 0:
                for d in devs:          # no udev (a container): ask blkid directly
                    for x in _walk(d):
                        _probe(x)
            return devs
    return []


def _probe(dev: dict):
    if dev.get("fstype") or dev.get("pttype") or not dev.get("path"):
        return
    res = subprocess.run(["blkid", "-p", "-o", "export", dev["path"]], capture_output=True, text=True)
    info = {k: re.sub(r"\\(.)", r"\1", v)
            for k, v in (l.split("=", 1) for l in res.stdout.splitlines() if "=" in l)}
    dev["fstype"], dev["label"], dev["uuid"] = info.get("TYPE"), info.get("LABEL"), info.get("UUID")
    dev["pttype"] = info.get("PTTYPE")
    if info.get("PART_ENTRY_TYPE"):
        dev["parttype"], dev["partuuid"] = info["PART_ENTRY_TYPE"], info.get("PART_ENTRY_UUID")


def _swaps() -> set[str]:
    path = os.environ.get("CLASSIC7_SWAPS", "/proc/swaps")
    try:
        lines = Path(path).read_text().splitlines()[1:]
    except OSError:
        return set()
    return {l.split()[0] for l in lines if l.split()}


def _b(v) -> bool:
    return v in (True, 1, "1", "true")


def _mounts(dev: dict) -> list[str]:
    return [m for m in (dev.get("mountpoints") or []) if m]


def _walk(dev: dict):
    yield dev
    for c in dev.get("children") or []:
        yield from _walk(c)


def _partnum(dev: dict) -> int | None:
    if dev.get("partn"):
        return int(dev["partn"])
    try:
        return int(Path(f"/sys/class/block/{dev.get('kname') or dev.get('name')}/partition").read_text())
    except (OSError, ValueError):
        m = re.search(r"(\d+)$", dev.get("name") or "")
        return int(m.group(1)) if m else None


def _fill(r: Region, dev: dict, swaps: set[str]):
    """Look through LUKS/LVM layers for the file system people actually use."""
    r.raw_fstype = dev.get("fstype")
    r.label, r.uuid = dev.get("label"), dev.get("uuid")
    r.partuuid, r.parttype = dev.get("partuuid"), (dev.get("parttype") or "").lower() or None
    r.parttypename = dev.get("parttypename")
    mounts, fs, label, size, avail = [], r.raw_fstype, r.label, dev.get("fssize"), dev.get("fsavail")
    for d in _walk(dev):
        mounts += _mounts(d)
        if d is not dev and d.get("fstype") and d.get("type") in ("crypt", "lvm"):
            fs, label = d.get("fstype"), d.get("label") or label
            size, avail = d.get("fssize") or size, d.get("fsavail") if d.get("fsavail") is not None else avail
        if d.get("path") in swaps:
            r.flags.add("swap")
    r.mounts = sorted(set(mounts), key=lambda m: (len(m), m))
    r.fstype, r.label = fs, label
    r.fssize = int(size) if size else None
    r.fsavail = int(avail) if avail is not None else None
    if r.raw_fstype == "crypto_LUKS":
        r.flags.add("encrypted")
    if r.raw_fstype == "swap":
        r.flags.add("swap")
    if any(m in SYSTEM_MOUNTS for m in r.mounts):
        r.flags.add("system")
    elif any(m in BOOT_MOUNTS for m in r.mounts):
        r.flags.add("efi" if r.parttype in EFI_TYPES else "boot")
    pt = r.parttype or ""
    if pt in EFI_TYPES:
        r.flags.add("efi")
    elif pt == MSR_TYPE:
        r.flags.add("msr")
    elif pt in RECOVERY_TYPES or (r.parttypename or "").lower().startswith("windows recovery"):
        r.flags.add("recovery")
    elif pt == BIOS_BOOT:
        r.flags.add("biosboot")
    elif pt in EXTENDED_TYPES:
        r.flags.add("extended")
    # Holds other block devices (an open LUKS volume, LVM, RAID): not something to format
    if any(d is not dev for d in _walk(dev)):
        r.flags.add("busy")
    if r.raw_fstype in ("crypto_LUKS", "LVM2_member", "linux_raid_member", "zfs_member"):
        r.flags.add("layered")


def list_disks() -> list[Disk]:
    swaps = _swaps()
    fstab = read_fstab()
    disks: list[Disk] = []
    counters = {"disk": 0, "rom": 0}
    kinds = ("disk", "rom", "loop") if os.environ.get("CLASSIC7_DISK_SHOW_LOOP") else ("disk", "rom")
    devices = [d for d in _lsblk()
               if d.get("type") in kinds and not (d.get("name") or "").startswith(("zram", "ram"))]
    for d in devices:
        if d.get("type") == "loop":
            d["type"] = "disk"
    devices.sort(key=lambda d: (d.get("type") == "rom", _b(d.get("rm")) or _b(d.get("hotplug")) or d.get("tran") == "usb",
                                d.get("name") or ""))
    for d in devices:
        kind = d.get("type")
        idx = counters[kind]
        counters[kind] += 1
        model = " ".join(x for x in ((d.get("vendor") or "").strip(), (d.get("model") or "").strip()) if x)
        disk = Disk(index=idx, path=d.get("path") or "/dev/" + d.get("name", ""), name=d.get("name") or "",
                    model=model, size=int(d.get("size") or 0), pttype=d.get("pttype"),
                    removable=_b(d.get("rm")) or _b(d.get("hotplug")) or d.get("tran") == "usb",
                    tran=d.get("tran"), readonly=_b(d.get("ro")), kind=kind)
        parts = [c for c in d.get("children") or [] if c.get("type") == "part"]
        if kind == "rom" or (not parts and d.get("fstype")):
            if d.get("fstype") or kind == "rom":
                r = Region(key=disk.path, kind="volume", disk=disk, start=0, sectors=disk.sectors, path=disk.path)
                _fill(r, d, swaps)
                disk.fstype = r.fstype
                if kind == "rom" and not disk.size:
                    r.flags.add("nomedia")
                disk.regions.append(r)
        else:
            if parts and not disk.pttype:
                disk.pttype = parts[0].get("pttype") or "unknown"
            regions = []
            for p in parts:
                start = int(p.get("start") or 0)
                r = Region(key=p.get("path") or p.get("name"), kind="partition", disk=disk, start=start,
                           sectors=int(p.get("size") or 0) // SECTOR, path=p.get("path"), number=_partnum(p))
                _fill(r, p, swaps)
                if disk.pttype == "dos" and (r.number or 0) > 4:
                    r.flags.add("logical")
                regions.append(r)
            regions.sort(key=lambda r: r.start)
            disk.regions = _with_free(disk, regions)
        for r in disk.regions:
            if "system" in r.flags:
                disk.system = True
                r.letter = "C"
            if r.kind == "free":
                continue
            for m in r.mounts:
                if letter_of_mount(m):
                    r.letter = r.letter or letter_of_mount(m)
            for e in fstab:
                if entry_matches(e, r):
                    r.fstab = e
                    if not r.letter:
                        r.letter = e.letter or letter_of_mount(e.file)
        disks.append(disk)
    return disks


def _with_free(disk: Disk, parts: list[Region]) -> list[Region]:
    """Partitions plus the unallocated space between them (only gaps of 1 MiB or more)."""
    total = disk.sectors
    last = total - 34 if disk.pttype == "gpt" else total
    out: list[Region] = []
    cursor = ALIGN
    ext = next((p for p in parts if "extended" in p.flags), None)
    logicals = [p for p in parts if "logical" in p.flags]
    ext_end = max((p.start + p.sectors for p in logicals), default=0) if ext else 0

    def gap(a: int, b: int):
        a = -(-a // ALIGN) * ALIGN
        size = (b - a) // ALIGN * ALIGN
        if size >= ALIGN:
            r = Region(key=f"free:{disk.path}:{a}", kind="free", disk=disk, start=a, sectors=size)
            r.in_extended = bool(ext and ext.start <= a < ext_end)
            out.append(r)

    for p in parts:
        if "extended" in p.flags:
            out.append(p)
            continue
        gap(cursor, p.start)
        out.append(p)
        cursor = max(cursor, p.start + p.sectors)
    gap(cursor, last)
    out.sort(key=lambda r: (r.start, "extended" not in r.flags))
    return out


def all_regions(disks: list[Disk]) -> list[Region]:
    return [r for d in disks for r in d.regions]


def volumes(disks: list[Disk]) -> list[Region]:
    """The rows of the volume list (Windows lists volumes, not empty space)."""
    out = [r for r in all_regions(disks) if r.kind != "free" and not ({"extended", "nomedia", "msr"} & r.flags)]
    out.sort(key=lambda r: (r.letter is None, r.letter or "", r.disk.kind, r.disk.index, r.start))
    return out


def used_letters(disks: list[Disk], extra: set[str] = frozenset()) -> set[str]:
    used = {"A", "B", "C"} | set(extra)
    for r in all_regions(disks):
        if r.letter:
            used.add(r.letter)
    for e in read_fstab():
        if e.letter:
            used.add(e.letter)
        elif letter_of_mount(e.file):
            used.add(letter_of_mount(e.file))
    try:
        import netdrive
        used |= {m.letter for m in netdrive.load()}
    except Exception:  # noqa: BLE001 - mapped network drives are optional here
        pass
    return used


def free_letters(disks: list[Disk], keep: str | None = None) -> list[str]:
    used = used_letters(disks)
    return [l for l in LETTERS if l not in used or l == keep]


def can_create_in(r: Region) -> tuple[bool, str]:
    d = r.disk
    if r.kind != "free":
        return False, ""
    if d.readonly:
        return False, "The disk is write-protected."
    if r.in_extended:
        return False, "Classic 7 can't create logical drives inside an extended partition."
    if d.pttype == "dos" and sum(1 for x in d.regions if x.kind == "partition" and "logical" not in x.flags) >= 4:
        return False, "This disk already has four partitions, which is the most an MBR disk can hold."
    if d.pttype not in ("gpt", "dos"):
        return False, "Initialize the disk first."
    return True, ""


def human(n: int | None) -> str:
    """Disk Management sizes: 465.76 GB, 100 MB, 931.51 GB."""
    if n is None:
        return ""
    for unit, div in (("TB", 1024 ** 4), ("GB", 1024 ** 3), ("MB", MIB), ("KB", 1024)):
        if n >= div:
            v = n / div
            return f"{v:.2f} {unit}" if unit in ("TB", "GB") else f"{v:.0f} {unit}"
    return f"{n} bytes"


def available_formats() -> list[tuple[str, str]]:
    import shutil
    return [(name, fs) for name, fs, prog in FORMATS if shutil.which(prog) or shutil.which(prog, path="/usr/sbin:/sbin")]


# ---- Steam ----------------------------------------------------------------------------------
def proton_risky(fstype: str | None) -> bool:
    return (fstype or "") in WINDOWS_FS


PROTON_NOTE = ("Windows games run through Proton keep a small Windows folder for each game (its "
               "\"compatdata\"). Proton needs Linux file features for it that {fs} drives don't have, "
               "so games installed there can refuse to start.\n\n"
               "When you set up a Steam library on this drive, Classic 7 keeps those folders on your "
               "system disk instead, and the games themselves on {name}. For a drive that only this "
               "computer uses, ext4 or Btrfs work best.")


def steam_root() -> Path:
    home = Path.home()
    for p in (home / ".local/share/Steam", home / ".steam/steam",
              home / ".var/app/com.valvesoftware.Steam/data/Steam"):
        if p.is_dir():
            return p.resolve()
    return home / ".local/share/Steam"


def setup_steam_library(mountpoint: str, fstype: str | None) -> tuple[Path, list[str]]:
    """Make <drive>/SteamLibrary ready for Steam's Add Drive. Returns (folder, notes)."""
    lib = Path(mountpoint) / "SteamLibrary"
    apps = lib / "steamapps"
    apps.mkdir(parents=True, exist_ok=True)
    notes = []
    if proton_risky(fstype):
        local = steam_root() / "steamapps" / "compatdata"
        local.mkdir(parents=True, exist_ok=True)
        link = apps / "compatdata"
        if link.is_symlink():
            if Path(os.readlink(link)) != local:
                link.unlink()
                link.symlink_to(local)
        elif link.exists():
            if any(link.iterdir()):
                notes.append(f"{link} already holds Proton folders; Classic 7 left it alone.")
            else:
                link.rmdir()
                link.symlink_to(local)
        else:
            try:
                link.symlink_to(local)
            except OSError:
                notes.append("This drive can't hold links (FAT32/exFAT), so Proton games may not start from it.")
        if link.is_symlink():
            notes.append(f"Proton folders stay on your system disk ({local}).")
    return lib, notes


def steam_knows(library: Path) -> bool:
    """True if Steam's libraryfolders.vdf already lists this folder."""
    vdf = steam_root() / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(errors="replace")
    except OSError:
        return False
    paths = re.findall(r'"path"\s+"([^"]+)"', text)
    want = os.path.realpath(library)
    return any(os.path.realpath(p.replace("\\\\", "\\")) == want for p in paths)
