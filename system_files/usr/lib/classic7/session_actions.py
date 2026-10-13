"""Lock, switch user, log off, sleep, restart, shut down: the commands behind Task Manager's
Shut Down menu and the Ctrl+Alt+Del screen (Plasma 6 on Wayland, SDDM)."""
from __future__ import annotations

import os
import shutil
import subprocess


def _qdbus() -> str | None:
    return shutil.which("qdbus6") or shutil.which("qdbus-qt6") or shutil.which("qdbus")


def _run(argv: list[str]) -> bool:
    if not argv or not shutil.which(argv[0]):
        return False
    try:
        subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _session() -> list[str]:
    sid = os.environ.get("XDG_SESSION_ID")
    return [sid] if sid else []


def lock() -> bool:
    return _run(["loginctl", "lock-session", *_session()])


def switch_user() -> bool:
    q = _qdbus()
    if q and _run([q, "org.kde.ksmserver", "/KSMServer", "org.kde.KSMServerInterface.openSwitchUserDialog"]):
        return True
    seat = os.environ.get("XDG_SEAT_PATH", "/org/freedesktop/DisplayManager/Seat0")
    return _run(["dbus-send", "--system", "--print-reply", "--dest=org.freedesktop.DisplayManager", seat,
                 "org.freedesktop.DisplayManager.Seat.SwitchToGreeter"])


def log_off(confirm: bool = False) -> bool:
    q = _qdbus()
    if q:
        if confirm:
            return _run([q, "org.kde.LogoutPrompt", "/LogoutPrompt", "org.kde.LogoutPrompt.promptLogout"])
        return _run([q, "org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown.logout"])
    return _run(["loginctl", "terminate-session", *_session()])


def restart() -> bool:
    q = _qdbus()
    if q and _run([q, "org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown.logoutAndReboot"]):
        return True
    return _run(["systemctl", "reboot"])


def shut_down() -> bool:
    q = _qdbus()
    if q and _run([q, "org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown.logoutAndShutdown"]):
        return True
    return _run(["systemctl", "poweroff"])


def sleep() -> bool:
    return _run(["systemctl", "suspend"])


def hibernate() -> bool:
    return _run(["systemctl", "hibernate"])


def can_hibernate() -> bool:
    try:
        out = subprocess.run(["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                              "org.freedesktop.login1.Manager", "CanHibernate"],
                             capture_output=True, text=True, timeout=2).stdout
        return '"yes"' in out
    except (OSError, subprocess.SubprocessError):
        return False


def task_manager() -> bool:
    return _run(["classic7-taskmgr"]) or _run(["plasma-systemmonitor"])


def run_dialog() -> bool:
    return _run(["classic7-run"])
