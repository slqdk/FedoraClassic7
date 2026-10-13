"""Disk Management on a real (loop) disk: initialize, new volumes with letters, Steam library,
change letter, format, check, delete. Run as root with the helper called directly.

    disks_test.py OUTDIR LOOPDEV
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.environ.get("CLASSIC7_LIB", "/usr/lib/classic7"))
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

out, loop = Path(sys.argv[1]), sys.argv[2]
app = QApplication([])
import diskmgmt_app as m  # noqa: E402
dk = m.dk
fails, shot_n = [], [0]
boxes = []


def ok(cond, what):
    print(("OK   " if cond else "FAIL ") + what, flush=True)
    if not cond:
        fails.append(what)


def shot(widget, name):
    app.processEvents()
    shot_n[0] += 1
    widget.grab().save(str(out / f"disk-{shot_n[0]:02d}-{name}.png"))


def closer():
    w = QApplication.activeModalWidget()
    if isinstance(w, QMessageBox):
        boxes.append(w.text())
        print("BOX  " + w.text().replace("\n", " | "), flush=True)
        shot(w, "message")
        w.reject() if w.escapeButton() else w.accept()


t = QTimer()
t.timeout.connect(closer)
t.start(300)


def wait(win, timeout=120):
    end = time.time() + timeout
    while win.proc is not None and time.time() < end:
        app.processEvents()
        time.sleep(0.05)
    for _ in range(10):
        app.processEvents()
        time.sleep(0.05)


def disk(win):
    win.refresh(force=True)
    return next((d for d in win.disks if d.path == loop), None)


def region(win, pred):
    d = disk(win)
    return next((r for r in d.regions if pred(r)), None) if d else None


def mounted_at(path):
    return os.path.ismount(path)


root = os.environ.get("CLASSIC7_LETTER_ROOT", "/var/mnt")
fstab = os.environ.get("CLASSIC7_FSTAB", "/etc/fstab")
w = m.DiskManagement()
w.resize(980, 680)
w.show()
d = disk(w)
ok(d is not None, f"the test disk {loop} is listed")
ok(d is not None and not d.initialized, "a blank disk shows as Not Initialized")
w._select(d)
shot(w, "blank-disk")
dlg = m.InitDialog([d], w)
dlg.show()
shot(dlg, "initialize-dialog")
dlg.close()

w.run_helper(["init", loop, "gpt"], "Initializing")
wait(w)
d = disk(w)
ok(d.pttype == "gpt", f"initialized as GPT ({d.pttype})")
free = region(w, lambda r: r.kind == "free")
ok(free is not None and free.size > 300 * dk.MIB, "the whole disk is unallocated")

wiz = m.NewVolumeWizard(w, free)
wiz.show()
for i in range(5):
    if i == 1:
        wiz.size.setValue(150)
    if i == 2:
        wiz.letter.setCurrentText("E")
    if i == 3:
        wiz.fs.setCurrentIndex(wiz.fs.findData("ext4"))
        wiz.label.setText("Linux Games")
    shot(wiz, f"wizard-page{i + 1}")
    wiz.next()
args = wiz.args()
wiz.close()
print("ARGS", args)
ok(args[-1] == "E" and args[4] == "ext4", "wizard settings")
w.run_helper(args, "New volume")
wait(w)
e = region(w, lambda r: r.letter == "E")
ok(e is not None and e.fstype == "ext4", "new ext4 volume E:")
ok(mounted_at(f"{root}/E"), f"E: is mounted at {root}/E")
ok(os.stat(f"{root}/E").st_uid == int(os.environ.get("PKEXEC_UID", "1000")), "E: belongs to the user")
text = Path(fstab).read_text()
ok("# classic7-drive E" in text and f"{root}/E" in text, "fstab entry for E:")

free = region(w, lambda r: r.kind == "free")
wiz = m.NewVolumeWizard(w, free)
wiz.letter.setCurrentText("F")
wiz.fs.setCurrentIndex(wiz.fs.findData("ntfs"))
wiz.label.setText("Games")
w.run_helper(wiz.args(), "New volume")
wait(w)
f = region(w, lambda r: r.letter == "F")
ok(f is not None and f.fstype in ("ntfs", "ntfs3"), "new NTFS volume F:")
ok(mounted_at(f"{root}/F"), f"F: is mounted at {root}/F")
print("FSTAB\n" + Path(fstab).read_text(), flush=True)
shot(w, "two-volumes")
if f and f.open_path:
    os.environ["HOME"] = os.environ.get("HOME", "/root")
    lib, notes = dk.setup_steam_library(f.open_path, f.fstype)
    link = lib / "steamapps" / "compatdata"
    ok(lib.is_dir(), "Steam library folder made")
    ok(link.is_symlink(), f"compatdata is kept on the system disk ({notes})")
    pd = m.PropertiesDialog(w, f)
    pd.show()
    pd.findChild(m.QTabWidget).setCurrentIndex(2)
    shot(pd, "properties-games")
    pd.close()

ld = m.LettersDialog(w, f)
ld.show()
shot(ld, "letters-dialog")
ld.close()
w.assign_letter(f, "G")
wait(w)
time.sleep(0.5)
app.processEvents()
g = region(w, lambda r: r.letter == "G")
ok(g is not None and mounted_at(f"{root}/G") and not os.path.exists(f"{root}/F"), "F: moved to G:")
ok("# classic7-drive F" not in Path(fstab).read_text(), "old F: entry is gone")

fd = m.FormatDialog(g, w)
fd.show()
shot(fd, "format-dialog")
fd.close()
fs = "exfat" if "exfat" in Path("/proc/filesystems").read_text() else "vfat"
label = "USB Data" if fs == "exfat" else "USB DATA"
w.run_helper(["format", g.path, fs, label], "Formatting")
wait(w)
g = region(w, lambda r: r.letter == "G")
ok(g is not None and g.fstype == fs and g.label == label, f"formatted as {fs} and kept G:")
ok(mounted_at(f"{root}/G"), "G: mounted again after format")

e = region(w, lambda r: r.letter == "E")
w.check(e)
wait(w)
ok(any("clean" in b.lower() or "linux games" in b.lower() or "files" in b.lower() for b in boxes),
   "Check for errors reports")
ok(mounted_at(f"{root}/E"), "E: mounted again after the check")

w._select(e)
shot(w, "before-delete")
w.run_helper(["delete", e.path], "Deleting")
wait(w)
ok(region(w, lambda r: r.letter == "E") is None, "E: deleted")
ok("# classic7-drive E" not in Path(fstab).read_text(), "E: entry removed from fstab")
ok(not mounted_at(f"{root}/E"), "E: no longer mounted")

g = region(w, lambda r: r.letter == "G")
w.run_helper(["unletter", g.path], "Removing letter")
wait(w)
g = region(w, lambda r: r.label == label)
ok(g is not None and g.letter is None and not mounted_at(f"{root}/G"), "letter G: removed")

# refusing to touch the running system
sysdev = next((r for r in dk.all_regions(w.disks) if "system" in r.flags), None)
if sysdev and sysdev.path:
    import subprocess
    res = subprocess.run(m.helper_argv(["format", sysdev.path, "ext4", "x"]), capture_output=True, text=True)
    ok(res.returncode != 0, f"refuses to format the system volume: {res.stderr.strip()[:80]}")
shot(w, "final")
print("FAILURES", len(fails), fails, flush=True)
sys.exit(1 if fails else 0)
