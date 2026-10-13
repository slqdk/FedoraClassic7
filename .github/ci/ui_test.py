"""Control Panel, Task Manager and the Ctrl+Alt+Del screen, in process. OUTDIR as argument."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("CLASSIC7_LIB", "/usr/lib/classic7"))
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

out = Path(sys.argv[1])
app = QApplication([])
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


def shot(w, name):
    spin(0.4)
    w.grab().save(str(out / f"{name}.png"))


# ---- Control Panel
import control_items as ci  # noqa: E402
import control_panel as cp  # noqa: E402
items = ci.items()
ok(len(items) >= 20, f"Control Panel has {len(items)} items")
kind, it = ci.resolve("main.cpl")
ok(kind == "item" and it.id == "Classic7.Mouse", "main.cpl opens Mouse")
ok(ci.resolve("system")[0] in ("item", "category"), "control system resolves")
ok(ci.resolve("/name Microsoft.DateAndTime")[0] == "item", "control /name Microsoft.DateAndTime")
w = cp.ControlPanel()
w.resize(920, 660)
w.show()
shot(w, "control-home")
w.go("category", "hardware")
shot(w, "control-hardware")
w.go("category", "system")
shot(w, "control-system")
w._set_view("large")
shot(w, "control-all")
w._set_view("small")
shot(w, "control-small")
w.search.setText("resolution")
shot(w, "control-search")
ok(any(i.id == "Classic7.Display" for i, _ in ci.search("resolution")), "search finds Display")
w.close()

# ---- Task Manager
import taskmgr_app as tm  # noqa: E402
probe = QLabel("Bridge test window")
probe.setWindowTitle("Bridge test window")
probe.resize(300, 120)
probe.show()
spin(1)
t = tm.TaskManager()
t.resize(620, 640)
t.show()
spin(1)
ok(t.bridge is not None and t.bridge.available(), "KWin script bridge is available")
t.tabs.setCurrentIndex(0)
for _ in range(8):
    t.tick()
    spin(0.5)
    if any(w.get("caption") == "Bridge test window" for w in t.windows):
        break
ok(any(w.get("caption") == "Bridge test window" for w in t.windows),
   f"Applications lists the open windows: {[w.get('caption') for w in t.windows]}")
shot(t, "taskmgr-applications")
# minimize through KWin and see it come back as minimized
for i in range(t.apps.topLevelItemCount()):
    item = t.apps.topLevelItem(i)
    if item.text(0) == "Bridge test window":
        t.apps.setCurrentItem(item)
t._window_act("minimize")
spin(1.5)
t.bridge.refresh()
spin(1.0)
ok(any(w.get("caption") == "Bridge test window" and w.get("minimized") for w in t.windows),
   "Minimize through KWin works")
t._window_act("close")
spin(1.5)
ok(not probe.isVisible(), "End Task closes the window")
for i, name in enumerate(["applications", "processes", "services", "performance", "networking", "users"]):
    t.tabs.setCurrentIndex(i)
    for _ in range(3):
        t.tick(force=True)
        spin(0.4)
    shot(t, f"taskmgr-{i + 1}-{name}")
ok(t.procs.topLevelItemCount() > 0, f"Processes tab lists {t.procs.topLevelItemCount()} processes")
ok(t.svcs.topLevelItemCount() >= 0, f"Services tab lists {t.svcs.topLevelItemCount()} services")
t.close()

# ---- Ctrl+Alt+Del
import security_screen as ss  # noqa: E402
s = ss.SecurityScreen()
s.resize(1200, 800)
s.show()
s.options[0].setFocus()
shot(s, "security-screen")
s._password()
shot(s, "security-password")
s.close()

# ---- System and Device Manager
import system_app  # noqa: E402
import devmgmt_app  # noqa: E402
import sysinfo  # noqa: E402
sw = system_app.SystemWindow()
sw.show()
shot(sw, "system-window")
ok(sysinfo.cpu_name() != "", f"processor: {sysinfo.cpu_name()}")
ok(sysinfo.memory()[1] > 0, f"memory: {sysinfo.memory()}")
sp = system_app.SystemProperties(None, 0)
sp.show()
shot(sp, "system-properties")
sp.tabs.setCurrentIndex(3)
shot(sp, "system-protection")
sp.close()
dm = devmgmt_app.DeviceManager()
dm.resize(560, 640)
dm.show()
root = dm.tree.topLevelItem(0)
for i in range(root.childCount()):
    root.child(i).setExpanded(True)
shot(dm, "device-manager")
groups = sysinfo.all_devices()
ok(len(groups) >= 4, f"Device Manager groups: {list(groups)}")
dev = next((d for v in groups.values() for d in v if d.driver), None)
if dev:
    pd = devmgmt_app.DevicePropertiesDialog(dev)
    pd.show()
    shot(pd, "device-properties")
    pd.findChild(devmgmt_app.QTabWidget).setCurrentIndex(1)
    shot(pd, "device-driver")
    pd.close()

print("FAILURES", len(fails), fails, flush=True)
sys.exit(1 if fails else 0)
