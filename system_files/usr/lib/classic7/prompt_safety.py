"""Risk rating for shell commands, independent of the language model.

The model also rates its own suggestions; the higher of the two ratings wins, so a
model that calls `rm -rf ~` "safe" still triggers the red warning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SAFE, CAUTION, DANGER = 0, 1, 2
NAMES = {SAFE: "safe", CAUTION: "caution", DANGER: "danger"}
LEVELS = {v: k for k, v in NAMES.items()}


@dataclass
class Risk:
    level: int
    reasons: list[str]

    @property
    def name(self) -> str:
        return NAMES[self.level]


# (level, regex, reason). Matched against each simple command of the line.
RULES: list[tuple[int, str, str]] = [
    # destroys data
    (DANGER, r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)*-[a-zA-Z]*[rRf]", "deletes files without asking (rm -r/-f)"),
    (DANGER, r"\brm\b.*\s(/|/\*|~|~/|\$HOME|\$HOME/)\s*$", "deletes a whole top-level folder"),
    (DANGER, r"\b(dd)\b.*\bof=", "dd writes raw data to a file or disk"),
    (DANGER, r"\b(mkfs(\.\w+)?|wipefs|sgdisk|fdisk|sfdisk|parted|gdisk|cfdisk)\b", "changes partitions or formats a disk"),
    (DANGER, r">\s*/dev/(sd|nvme|vd|mmcblk|disk)", "writes directly to a disk device"),
    (DANGER, r"\bshred\b", "destroys file contents permanently"),
    (DANGER, r":\(\)\s*\{\s*:\|:&\s*\};:", "fork bomb"),
    (DANGER, r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "runs a script straight from the internet"),
    (DANGER, r"\bchmod\s+(-R\s+)?[0-7]*777\s+/(\s|$)", "makes the whole system writable for everyone"),
    (DANGER, r"\bchown\s+-R\b.*\s/(\s|$)", "changes the owner of the whole system"),
    (DANGER, r"\bfind\b.*\s-delete\b", "find -delete removes every match"),
    (DANGER, r"\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f)", "throws away uncommitted work"),
    (DANGER, r"\bflatpak\s+uninstall\b.*--all", "removes all Flatpak apps"),
    (DANGER, r"\bmv\b.*\s/dev/null\b", "moves files into /dev/null (deletes them)"),
    # changes the system
    (CAUTION, r"\b(sudo|pkexec|run0|su)\b", "runs with administrator rights"),
    (CAUTION, r"\b(rpm-ostree|bootc|ostree)\b\s+(install|uninstall|override|rebase|reset|rollback|switch|upgrade|kargs|initramfs|usroverlay|cleanup)",
     "changes the installed system image (takes effect after a restart)"),
    (CAUTION, r"\bujust\b", "runs a Bazzite system task"),
    (CAUTION, r"\bsystemctl\b\s+(stop|disable|mask|restart|kill|isolate|poweroff|reboot|halt)", "stops or changes a system service"),
    (CAUTION, r"\b(reboot|poweroff|shutdown|halt)\b", "restarts or turns off the PC"),
    (CAUTION, r"\b(kill|pkill|killall)\b", "ends running programs"),
    (CAUTION, r"\brm\b", "deletes files"),
    (CAUTION, r"\bmv\b", "moves or renames files (can overwrite)"),
    (CAUTION, r"\bchmod\b|\bchown\b", "changes file permissions or owner"),
    (CAUTION, r"(^|[^<>&|0-9])>\s*(?!/dev/null)[^&>|\s]", "overwrites a file with >"),
    (CAUTION, r"\b(flatpak|brew)\s+(uninstall|remove)\b", "uninstalls software"),
    (CAUTION, r"\bdistrobox\s+(rm|stop)\b", "removes or stops a Distrobox container"),
    (CAUTION, r"\b(firewall-cmd|nmcli\s+\w+\s+(delete|down|modify))\b", "changes network settings"),
    (CAUTION, r"\bgit\s+push\b.*(--force|-f\b)", "overwrites history on the server"),
    (CAUTION, r"\b(passwd|usermod|userdel|groupdel)\b", "changes user accounts"),
    (CAUTION, r"\b(dnf5?|yum|apt|apt-get)\s+(install|remove|erase|upgrade|update|reinstall)\b",
     "dnf/apt only work inside a Distrobox container, not on the system itself (use flatpak or brew there)"),
]
_COMPILED = [(lvl, re.compile(rx), why) for lvl, rx, why in RULES]


def rate(command: str) -> Risk:
    """Rate a command line; returns the highest level found and all reasons."""
    found: list[tuple[int, str]] = []
    text = command.strip()
    if not text:
        return Risk(SAFE, [])
    # Check the whole line and each part between ; && || | so rules anchored at the
    # start/end of a command also fire inside pipelines.
    parts = [text] + [p.strip() for p in re.split(r";|&&|\|\||\|", text) if p.strip()]
    for lvl, rx, why in _COMPILED:
        if any(rx.search(p) for p in parts):
            found.append((lvl, why))
    if not found:
        return Risk(SAFE, [])
    level = max(lvl for lvl, _ in found)
    # Show the reasons of the highest level; keep "administrator rights" as extra context
    reasons = [why for lvl, why in found if lvl == level or "administrator" in why]
    return Risk(level, reasons)


def combine(command: str, model_level: str | None) -> Risk:
    """Our rules plus the model's own rating; the stricter one wins."""
    risk = rate(command)
    m = LEVELS.get((model_level or "").lower().strip(), SAFE)
    if m > risk.level:
        risk.level = m
        risk.reasons.append("the assistant rated it as " + NAMES[m])
    return risk
