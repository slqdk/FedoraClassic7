"""CI: Photo Viewer in the image - open pictures of many types, next/previous with the keys,
turn a picture (saved when leaving it), slide show. Screenshots in OUT."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("CLASSIC7_LIB", "/usr/lib/classic7"))
OUT = sys.argv[1]
PICS = Path(sys.argv[2])

from PySide6.QtCore import Qt, QTimer   # noqa: E402
from PySide6.QtTest import QTest        # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
import photos_app as pa   # noqa: E402

failures = []


def check(name, cond):
    print(("OK   " if cond else "FAIL ") + name, flush=True)
    if not cond:
        failures.append(name)


def run():
    try:
        files = sorted(p for p in PICS.iterdir() if p.is_file())
        for f in files:
            w = pa.PhotoViewer(f)
            w.resize(1000, 700)
            w.show()
            for _i in range(40):
                QTest.qWait(100)
                if w.current is not None:
                    break
            ok = w.current is not None and not w.current.error
            check(f"open {f.name}" + ("" if ok else f": {w.current.error if w.current else 'not loaded'}"), ok)
            w.grab().save(os.path.join(OUT, "type-" + f.name.replace(".", "_") + ".png"))
            w.close()
        first = PICS / "01-photo.jpg"
        w = pa.PhotoViewer(first)
        w.resize(1000, 700)
        w.show()
        w.activateWindow()
        print("window active:", QTest.qWaitForWindowActive(w, 5000), flush=True)
        QTest.qWait(800)
        QTest.keyClick(w.canvas, Qt.Key_Right)
        QTest.keyClick(w.canvas, Qt.Key_Right)
        QTest.qWait(600)
        check("Right Right moves two pictures", w.index == 2)
        QTest.keyClick(w.canvas, Qt.Key_Left)
        QTest.keyClick(w.canvas, Qt.Key_Left)
        QTest.qWait(600)
        QTest.keyClick(w.canvas, Qt.Key_Period, Qt.ControlModifier)
        QTest.qWait(300)
        w.grab().save(os.path.join(OUT, "rotate.png"))
        w.close()
        from PIL import Image
        with Image.open(first) as im:
            check("turn saved as EXIF orientation 6", im.getexif().get(274) == 6)
        w = pa.PhotoViewer(first)
        w.resize(1000, 700)
        w.show()
        QTest.qWait(600)
        w.start_slideshow()
        QTest.qWait(1500)
        if w.slideshow is not None:
            w.slideshow.grab().save(os.path.join(OUT, "slideshow.png"))
            check("slide show is full screen", w.slideshow.isFullScreen())
            w.slideshow.close()
        w.close()
    except Exception as e:   # noqa: BLE001
        import traceback
        traceback.print_exc()
        failures.append(str(e))
    print("FAILURES:", failures, flush=True)
    app.exit(1 if failures else 0)


QTimer.singleShot(500, run)
sys.exit(app.exec())
