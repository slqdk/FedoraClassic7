#!/usr/bin/python3
"""Start a Classic 7 program and report how long it took until its first window was drawn.

    perf_run.py OUT.jsonl LABEL PROGRAM [ARGS...]      PROGRAM: a script, or mod:NAME for main() of a module

C7_T0 (nanoseconds since the epoch, taken by the caller just before starting this) counts the
interpreter's own start-up too. The program runs in this process (runpy); its event loop is
stopped right after the first window has been painted, and one JSON line is appended to OUT:
total time, the PySide6 import, the time until the program called exec(), memory."""
import json
import os
import runpy
import sys
import time

OUT, LABEL, PROG = sys.argv[1], sys.argv[2], sys.argv[3]
T0 = int(os.environ.get("C7_T0", time.time_ns())) / 1e9
marks = {"start_interp": round((time.time() - T0) * 1000)}

t = time.time()
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
marks["pyside_import"] = round((time.time() - t) * 1000)


def mem() -> dict:
    out = {}
    try:
        for line in open("/proc/self/smaps_rollup"):
            k, v = line.split(":", 1)
            if k in ("Rss", "Pss"):
                out[k.lower() + "_mb"] = round(int(v.split()[0]) / 1024, 1)
    except OSError:
        pass
    return out


done = False


def finish(kind: str):
    global done
    if done:
        return
    done = True
    app = QtCore.QCoreApplication.instance()
    marks["exec_called"] = marks.get("exec_called", round((time.time() - T0) * 1000))
    for _ in range(3):
        app.processEvents()
    wins = []
    if isinstance(app, QtWidgets.QApplication):
        wins = [f"{w.windowTitle()} {w.width()}x{w.height()}" for w in app.topLevelWidgets() if w.isVisible()]
    rec = {"label": LABEL, "kind": kind, "total_ms": round((time.time() - T0) * 1000), **marks, **mem(),
           "modules": len(sys.modules), "windows": wins[:3]}
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")
    sys.stdout.flush()
    os._exit(0)


def app_exec(orig, kind):
    def patched(*_a, **_k):
        marks["exec_called"] = round((time.time() - T0) * 1000)
        QtCore.QTimer.singleShot(0, lambda: finish(kind))
        return orig()
    return patched


def dialog_exec(orig):
    def patched(self, *a, **k):
        marks["exec_called"] = round((time.time() - T0) * 1000)
        QtCore.QTimer.singleShot(0, lambda: finish("QDialog.exec"))
        return orig(self, *a, **k)
    return patched


for cls in (QtWidgets.QApplication, QtGui.QGuiApplication, QtCore.QCoreApplication):
    cls.exec = app_exec(cls.exec, cls.__name__ + ".exec")
QtWidgets.QDialog.exec = dialog_exec(QtWidgets.QDialog.exec)
QtWidgets.QMessageBox.exec = dialog_exec(QtWidgets.QMessageBox.exec)

sys.argv = [PROG] + sys.argv[4:]
try:
    if PROG.startswith("mod:"):
        sys.path.insert(0, os.environ.get("CLASSIC7_LIB", "/usr/lib/classic7"))
        mod = __import__(PROG[4:])
        sys.exit(mod.main(sys.argv[1:]))
    runpy.run_path(PROG, run_name="__main__")
except SystemExit as e:
    rec = {"label": LABEL, "kind": "exited", "code": str(e.code), "total_ms": round((time.time() - T0) * 1000),
           **marks, **mem()}
    with open(OUT, "a") as f:
        f.write(json.dumps(rec) + "\n")
