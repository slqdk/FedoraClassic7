"""Action Center's checks, as in Windows 7 (no GUI code, so the notification-area flag can ask
quickly): the firewall, updates waiting for a restart or not looked for in a while, drives that
are nearly full, and programs that stopped working (crash reports in the journal).

    classic7-actioncenter --json     the current messages, for the notification area
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

ARCHIVE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "classic7" / "actioncenter.json"
LOW_SPACE = 0.10            # nearly full: less than a tenth free
UPDATE_AGE = 14 * 86400     # look for updates at least every two weeks


def _run(cmd: list[str], timeout: float = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return -1, ""


def msg(mid: str, section: str, title: str, text: str, important: bool, fix_text: str, fix: list[str]) -> dict:
    key = hashlib.sha1(f"{mid}|{title}|{text}".encode()).hexdigest()[:12]
    return {"id": mid, "key": key, "section": section, "title": title, "text": text, "important": important,
            "fix_text": fix_text, "fix": fix}


# ---- the checks -------------------------------------------------------------------------------
def firewall() -> tuple[str, dict | None]:
    """('On' | 'Off' | 'Not installed', message)."""
    if not shutil.which("firewall-cmd"):
        return "Not installed", None
    code, out = _run(["firewall-cmd", "--state"], 5)
    if code == 0 and out.strip() == "running":
        return "On", None
    return "Off", msg("firewall", "Security", "Turn on the firewall",
                      "The firewall is turned off. Programs on the network can reach this computer freely.",
                      True, "Turn on now", ["classic7-firewall"])


def updates() -> tuple[str, list[dict]]:
    out = []
    status = "Up to date"
    code, text = _run(["rpm-ostree", "status", "--json"], 15)
    staged = False
    if code == 0:
        try:
            staged = any(d.get("staged") for d in json.loads(text).get("deployments", []))
        except (ValueError, AttributeError):
            staged = False
    if staged:
        status = "Restart needed"
        out.append(msg("restart", "Security", "Restart to finish installing updates",
                       "A new version of Classic 7 has been downloaded. Restart the computer to start using it.",
                       True, "Restart now", ["classic7-update", "--gui"]))
    try:
        state = json.loads((Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
                            / "classic7" / "update.json").read_text())
        last = float(state.get("last_check") or 0)
    except (OSError, ValueError, TypeError):
        last = 0
    if not staged and (not last or time.time() - last > UPDATE_AGE):
        status = "Not checked recently"
        out.append(msg("updates", "Security", "Check for updates",
                       "Classic 7 hasn't looked for updates in a while." if last else
                       "Classic 7 hasn't looked for updates yet.",
                       False, "Check for updates", ["classic7-update", "--gui"]))
    return status, out


def disk_space() -> list[dict]:
    out = []
    try:
        import drives as dr
        drives = [d for d in dr.list_drives() if d.mounted and d.total and d.kind in ("Local Disk", "System")]
    except Exception:  # noqa: BLE001 - the drive list is optional
        drives = []
    seen = set()
    for d in drives:
        if not d.free or d.total in seen:
            continue
        if d.free / d.total < LOW_SPACE:
            seen.add(d.total)
            name = d.name if not d.letter else f"{d.name} ({d.letter}:)" if f"({d.letter}:)" not in d.name else d.name
            out.append(msg(f"space:{d.key}", "Maintenance", f"Free up disk space on {name}",
                           f"Only {d.free * 100 // d.total}% of {name} is free. Remove programs or files you don't "
                           "need, or empty the Recycle Bin.",
                           False, "Open Computer", ["classic7-computer"]))
    return out


def problem_reports() -> tuple[int, dict | None]:
    if not shutil.which("coredumpctl"):
        return 0, None
    code, text = _run(["coredumpctl", "--no-pager", "--json=short", "--since=-7d", "list"], 10)
    if code != 0 or not text.strip():
        return 0, None
    try:
        rows = json.loads(text)
    except ValueError:
        return 0, None
    progs = sorted({os.path.basename(r.get("exe") or r.get("comm") or "?") for r in rows if isinstance(r, dict)})
    if not progs:
        return 0, None
    names = ", ".join(progs[:3]) + (f" and {len(progs) - 3} more" if len(progs) > 3 else "")
    return len(rows), msg("problems", "Maintenance", "Check for solutions to problem reports",
                          f"{len(progs)} program{'s' if len(progs) != 1 else ''} stopped working in the last week "
                          f"({names}).", False, "View problem reports", ["classic7-eventvwr", "--problems"])


# ---- archiving ----------------------------------------------------------------------------------
def archived() -> set[str]:
    try:
        return set(json.loads(ARCHIVE.read_text()).get("archived", []))
    except (OSError, ValueError, AttributeError):
        return set()


def archive(key: str, on: bool = True):
    keys = archived()
    keys.add(key) if on else keys.discard(key)
    try:
        ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVE.write_text(json.dumps({"archived": sorted(keys)}, indent=1) + "\n")
    except OSError:
        pass


def collect() -> dict:
    fw_state, fw_msg = firewall()
    up_state, up_msgs = updates()
    crashes, crash_msg = problem_reports()
    msgs = [m for m in [fw_msg, *up_msgs, *disk_space(), crash_msg] if m]
    arch = archived()
    for m in msgs:
        m["archived"] = m["key"] in arch
    current = [m for m in msgs if not m["archived"]]
    return {"messages": msgs, "count": len(current), "important": sum(1 for m in current if m["important"]),
            "firewall": fw_state, "updates": up_state, "crashes": crashes}


def main_json() -> int:
    print(json.dumps(collect()))
    return 0
