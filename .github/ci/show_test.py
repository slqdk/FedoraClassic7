"""CI: Show (presentations) in the image - build a presentation with the editor's own functions,
save it, read it back, open real PowerPoint files (.pptx and .ppt) and take screenshots."""
import os
import sys
import traceback

sys.path.insert(0, os.environ.get("CLASSIC7_LIB", "/usr/lib/classic7"))
OUT = sys.argv[1] if len(sys.argv) > 1 else "/out"
SAMPLES = sys.argv[2] if len(sys.argv) > 2 else "/out/samples"

from PySide6.QtCore import QPointF, Qt, QTimer   # noqa: E402
from PySide6.QtTest import QTest                  # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402

app = QApplication(sys.argv[:1])
import show_app as sa      # noqa: E402
import show_model as sm    # noqa: E402
import show_pptx as spx    # noqa: E402

failures = []


def check(name, cond):
    print(("OK   " if cond else "FAIL ") + name, flush=True)
    if not cond:
        failures.append(name)


w = sa.ShowWindow(None)
w.resize(1280, 860)
w.show()
v = w.view


def at(x, y):
    return v.mapFromScene(QPointF(x, y))


def click(x, y):
    QTest.mouseClick(v.viewport(), Qt.LeftButton, Qt.NoModifier, at(x, y))


def drag(x0, y0, x1, y1):
    vp = v.viewport()
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, at(x0, y0))
    for i in range(1, 6):
        QTest.mouseMove(vp, at(x0 + (x1 - x0) * i / 5, y0 + (y1 - y0) * i / 5))
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, at(x1, y1))


def keys(text):
    QTest.keyClicks(v.viewport(), text)


def key(k, mods=Qt.NoModifier):
    QTest.keyClick(v.viewport(), k, mods)


def shot(name, widget=None):
    QApplication.processEvents()
    (widget or w).grab().save(os.path.join(OUT, name + ".png"))


def build():
    w.apply_design("horizon")
    click(360, 200)
    keys("Classic 7 Show")
    click(360, 330)
    keys("Made in the CI test")
    click(700, 525)
    w.new_slide(None)
    click(360, 60)
    keys("Agenda")
    click(100, 150)
    keys("First point")
    key(Qt.Key_Return)
    key(Qt.Key_Tab)
    keys("A sub point")
    key(Qt.Key_Return)
    key(Qt.Key_Tab, Qt.ShiftModifier)
    keys("Second point")
    click(700, 525)
    v.start_draw("roundRect")
    drag(430, 330, 650, 450)
    keys("A shape")
    click(700, 525)
    w.set_transition("push", "u")
    w.view.select([w.slide.shapes[-1]])
    w.set_animation("fly")
    shot("show-edit")
    w.new_slide(None)
    click(360, 60)
    keys("Numbers")
    click(700, 525)
    w.insert_table(3, 3)
    keys("Name")
    key(Qt.Key_Tab)
    keys("Value")
    click(700, 525)
    w.slide.notes = "Speaker notes for the table slide"
    shot("show-table")
    w.set_view("sorter")
    shot("show-sorter")
    w.set_view("normal")
    check("three slides", len(w.pres.slides) == 3)
    out = os.path.join(OUT, "made.pptx")
    check("save .pptx", w.write_to(out))
    check("save PDF", w.export_pdf(os.path.join(OUT, "made.pdf")))
    p = spx.read_pptx(out)
    check("read back: 3 slides", len(p.slides) == 3)
    texts = [s.text.plain() for sl in p.slides for s in sl.shapes if s.text is not None]
    check("read back: text", "Agenda" in texts and any("A sub point" in t for t in texts))
    check("read back: levels", any(par.level == 1 for sl in p.slides for s in sl.shapes if s.text
                                   for par in s.text.paragraphs))
    check("read back: table", any(s.kind == "table" for s in p.slides[2].shapes))
    check("read back: notes", "Speaker notes" in p.slides[2].notes)
    check("read back: transition", p.slides[1].transition.type == "push")
    check("read back: animation", any(s.anim for s in p.slides[1].shapes))
    w.modified = False


def samples():
    for f in sorted(os.listdir(SAMPLES)) if os.path.isdir(SAMPLES) else []:
        path = os.path.join(SAMPLES, f)
        try:
            win = sa.ShowWindow(None)
            win.resize(1280, 860)
            win.show()
            win.open_path(path)
            QApplication.processEvents()
            check(f"open {f}: {len(win.pres.slides)} slides", len(win.pres.slides) > 0)
            win.go_to(min(1, len(win.pres.slides) - 1))
            shot("open-" + f.replace(".", "_"), win)
            win.write_to(os.path.join(OUT, "resaved-" + os.path.splitext(f)[0] + ".pptx"))
            win.modified = False
            win.close()
        except Exception:   # noqa: BLE001
            traceback.print_exc()
            check(f"open {f}", False)


def slideshow():
    from show_slideshow import SlideShow
    ss = SlideShow(w.pres, 1)
    ss.start()
    QTest.qWait(400)
    shot("show-slideshow", ss)
    ss.next()
    QTest.qWait(250)
    shot("show-slideshow-anim", ss)
    ss.close()


def run():
    try:
        build()
        slideshow()
        samples()
    except Exception:   # noqa: BLE001
        traceback.print_exc()
        failures.append("exception")
    print("FAILURES:", failures, flush=True)
    app.exit(1 if failures else 0)


QTimer.singleShot(1200, run)
sys.exit(app.exec())
