"""Runs inside the nested Plasma session of desk_ci.sh: checks windows through the KWin
bridge, drives the mouse and keys with xdotool on the Xvfb display that shows the session."""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("CLASSIC7_LIB", "/usr/lib/classic7"))
from PySide6.QtWidgets import QApplication  # noqa: E402

out = Path(sys.argv[1])
app = QApplication([])
import kwin_bridge  # noqa: E402

fails = []


def ok(cond, what):
    print(("OK   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        fails.append(what)


def spin(secs):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.03)


def x(*args):
    subprocess.run(["xdotool", *map(str, args)], env={**os.environ, "DISPLAY": ":99"}, check=False)


def shot(name):
    subprocess.run(["import", "-window", "root", str(out / f"{name}.png")], env={**os.environ, "DISPLAY": ":99"})


bridge = kwin_bridge.KWinBridge("DeskTest")


def windows():
    bridge.windows = []
    bridge.refresh()
    for _ in range(60):
        spin(0.05)
        if bridge.windows:
            break
    return bridge.windows


def find(part):
    return next((w for w in windows() if part in (w.get("caption") or "")), None)


ws = windows()
print("WINDOWS", [(w["caption"], w["x"], w["y"], w["w"], w["h"], w["minimized"]) for w in ws], flush=True)
ok(len(ws) >= 3, f"{len(ws)} windows are open")

# ---- Start menu jump list: rest the mouse on the pinned programs one by one
x("key", "Escape")
spin(0.5)
x("mousemove", 30, 790, "click", 1)
spin(2.5)
for i, y in enumerate((300, 336, 372, 408, 444)):
    x("mousemove", 90, y)
    spin(1.2)
    shot(f"06-start-hover-{i + 1}")
x("key", "Escape")
spin(1)

# ---- Win+Up / Win+Down (after the update step that sets the keys)
import update_core  # noqa: E402
res = update_core._win7_window_keys(lambda m: print("LOG", m, flush=True))
ok(res, "Win+Up/Win+Down shortcuts set through kglobalaccel")
cp = find("Control Panel")
ok(cp is not None, "Control Panel window found")
if cp:
    bridge.act(cp["id"], "restore")
    spin(1)
    bridge.act(cp["id"], "activate")
    spin(1)
    before = find("Control Panel")
    x("key", "super+Up")
    spin(1.5)
    after = find("Control Panel")
    ok(after and after["w"] > before["w"] and after["w"] >= 1100, f"Win+Up maximizes ({before['w']} -> {after and after['w']})")
    shot("07-win-up")
    x("key", "super+Down")
    spin(1.5)
    restored = find("Control Panel")
    ok(restored and restored["w"] < after["w"] and not restored["minimized"], "Win+Down restores a maximized window")
    x("key", "super+Down")
    spin(1.5)
    mini = find("Control Panel")
    ok(mini and mini["minimized"], "Win+Down again minimizes")
    bridge.act(cp["id"], "activate")
    spin(1)

# ---- Aero Shake: grab the title bar and shake
cp = find("Control Panel")
if cp:
    tx, ty = int(cp["x"] + 120), int(cp["y"] + 10)
    x("mousemove", tx, ty)
    spin(0.3)
    x("mousedown", 1)
    spin(0.2)
    for i in range(10):
        x("mousemove", tx + (90 if i % 2 == 0 else -90), ty)
        time.sleep(0.07)
    x("mousemove", tx, ty)
    spin(0.2)
    x("mouseup", 1)
    spin(1.5)
    others = [w for w in windows() if "Control Panel" not in w["caption"]]
    ok(others and all(w["minimized"] for w in others), f"Aero Shake minimizes the other windows: {[(w['caption'], w['minimized']) for w in others]}")
    shot("08-after-shake")
    x("key", "super+Home")
    spin(1.5)
    others = [w for w in windows() if "Control Panel" not in w["caption"]]
    ok(others and not any(w["minimized"] for w in others), "Win+Home brings them back")
    shot("09-after-unshake")

# ---- Show desktop button at the right end of the taskbar
x("mousemove", 1176, 786, "click", 1)
spin(1.5)
shot("10-show-desktop")
x("mousemove", 1176, 786, "click", 1)
spin(1.5)
shot("11-windows-back")

# ---- Ctrl+Alt+Del
x("key", "ctrl+alt+Delete")
spin(4)
shot("12-ctrl-alt-del")
x("key", "Escape")
spin(1.5)
shot("13-after-cancel")

print("FAILURES", len(fails), fails, flush=True)
sys.exit(1 if fails else 0)
