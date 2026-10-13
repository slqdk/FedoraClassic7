"""Sheet (the Excel clone) end to end: typing, formulas, undo, clipboard, fill, sort, file formats
(xlsx/xls/csv round trips, against LibreOffice when it is there), printing, the full window."""
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, os.environ.get("C7LIB", "/usr/lib/classic7"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
OUT = Path(os.environ.get("OUT", tempfile.mkdtemp()))
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtCore import Qt                      # noqa: E402
from PySide6.QtGui import QIcon                    # noqa: E402
from PySide6.QtTest import QTest                   # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

app = QApplication([])
QIcon.setThemeName(os.environ.get("ICON_THEME", QIcon.themeName() or "breeze"))
QDialog.exec = lambda self: QDialog.Rejected
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.No)
QMessageBox.warning = QMessageBox.information = QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.Ok)

import sheet_app as A          # noqa: E402
import sheet_io as IO          # noqa: E402
import sheet_ops as OPS        # noqa: E402
import sheet_print as PR       # noqa: E402

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)


def step(name):
    def deco(f):
        try:
            f()
        except Exception:
            check(name, False, traceback.format_exc()[-800:])
        return f
    return deco


w = A.SheetWindow(None)
w.resize(1280, 760)
w.show()
app.processEvents()
wb = w.wb
g = w.grid


def type_cell(r, c, text):
    g.select(r, c)
    g.setFocus()
    app.processEvents()
    QTest.keyClicks(app.focusWidget() or g, text[:1])
    app.processEvents()
    QTest.keyClicks(app.focusWidget(), text[1:])
    QTest.keyClick(app.focusWidget(), Qt.Key_Return)
    app.processEvents()


def val(ref):
    from sheet_ref import parse_cell
    r, c = parse_cell(ref)[:2]
    return wb.value(wb.ws.name, r, c)


@step("typing")
def _():
    type_cell(0, 0, "Item")
    type_cell(0, 1, "Price")
    for i, (n, p) in enumerate([("Pear", "12,5" if A.NF.DEC == "," else "12.5"), ("Apple", "7"), ("Fig", "30")], 1):
        type_cell(i, 0, n)
        type_cell(i, 1, p)
    type_cell(4, 1, "=sum(B2:B4)")
    check("typed text", val("A2") == "Pear", repr(val("A2")))
    check("typed number", val("B2") == 12.5, repr(val("B2")))
    check("formula", val("B5") == 49.5, repr(val("B5")))
    check("formula normalized", wb.ws.cells[(4, 1)].formula == "=SUM(B2:B4)", wb.ws.cells[(4, 1)].formula)
    type_cell(1, 1, "100")
    check("recalc", val("B5") == 137.0, repr(val("B5")))
    w.undo()
    check("undo", val("B2") == 12.5 and val("B5") == 49.5, f"{val('B2')} {val('B5')}")
    w.redo()
    check("redo", val("B5") == 137.0, repr(val("B5")))
    w.undo()
    g.select(9, 3)
    g.setFocus()
    QTest.keyClicks(g, "=")
    QTest.keyClicks(app.focusWidget(), "a1")
    QTest.keyClick(app.focusWidget(), Qt.Key_F4)
    QTest.keyClick(app.focusWidget(), Qt.Key_Return)
    app.processEvents()
    check("F4 makes $A$1", wb.ws.cells[(9, 3)].formula == "=$A$1", wb.ws.cells[(9, 3)].formula)
    wb.set_input(wb.ws, 9, 3, "")


@step("ops")
def _():
    ws = wb.ws
    clip = OPS.copy_range(wb, ws, 4, 1, 4, 1)
    OPS.paste(wb, ws, clip, 4, 2)
    check("relative paste", ws.cells[(4, 2)].formula == "=SUM(C2:C4)", ws.cells[(4, 2)].formula)
    wb.set_input(ws, 6, 0, "1")
    wb.set_input(ws, 7, 0, "2")
    OPS.fill(wb, ws, (6, 0, 7, 0), (6, 0, 11, 0))
    check("fill series", val("A12") == 6.0, repr(val("A12")))
    OPS.sort_range(wb, ws, (1, 0, 3, 1), [(1, False)])
    check("sort", [val(f"A{i}") for i in (2, 3, 4)] == ["Fig", "Pear", "Apple"], str([val(f"A{i}") for i in (2, 3, 4)]))
    check("sum after sort", val("B5") == 49.5, repr(val("B5")))


@step("functions")
def _():
    ws = wb.sheets[1]
    cases = {
        "=VLOOKUP(\"b\",{\"a\",1;\"b\",2},2,FALSE)": 2.0, "=IFERROR(1/0,\"x\")": "x", "=ROUND(2.345,2)": 2.35,
        "=TEXT(0.5,\"0%\")": "50%", "=DATE(2024,2,29)+1": 45352.0, "=SUMPRODUCT({1,2},{3,4})": 11.0,
        "=LEFT(\"Classic\",4)&\"7\"": "Clas7", "=AND(TRUE,1>0)": True, "=-2^2": 4.0, "=IFNA()": None,
    }
    for i, (f, want) in enumerate(cases.items()):
        wb.set_input(ws, i, 0, f)
        got = wb.value(ws.name, i, 0)
        if want is None:
            check(f"fn {f}", isinstance(got, A.F.XLError), repr(got))
        else:
            check(f"fn {f}", got == want, repr(got))


@step("files")
def _():
    d = OUT / "files"
    d.mkdir(exist_ok=True)
    wb.ws.charts.append(A.CH.from_selection(wb, wb.ws, 0, 0, 3, 1, "col")) if hasattr(A, "CH") else None
    for ext in ("xlsx", "csv"):
        p = str(d / f"book.{ext}")
        IO.save_any(wb, p)
        back = IO.open_any(p)
        ws2 = back.sheets[0]
        check(f"roundtrip {ext}", back.value(ws2.name, 4, 1) == 49.5 and back.value(ws2.name, 1, 0) == "Fig",
              f"{back.value(ws2.name, 4, 1)!r} {back.value(ws2.name, 1, 0)!r}")
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        subprocess.run([soffice, "--headless", "--convert-to", "xls", "--outdir", str(d), str(d / "book.xlsx")],
                       capture_output=True, timeout=180)
        if (d / "book.xls").exists():
            back = IO.open_any(str(d / "book.xls"))
            check("xls via LibreOffice", back.value(back.sheets[0].name, 4, 1) == 49.5)
    for sample in sorted(Path(os.environ.get("SAMPLES", "/nonexistent")).glob("*.xls*"))[:80]:
        try:
            IO.open_any(str(sample))
            ok = True
        except IO.OpenError:
            ok = True       # protected/corrupt files are refused with a message, which is right
        except Exception as e:
            ok, err = False, repr(e)
        check(f"open sample {sample.name}", ok, "" if ok else err)


@step("print")
def _():
    p = OUT / "print.pdf"
    n = PR.export_pdf(wb, str(p))
    check("pdf pages", n >= 1 and p.stat().st_size > 1000, f"{n} pages, {p.stat().st_size if p.exists() else 0} bytes")


@step("window")
def _():
    w.switch_sheet(0)
    g.select(1, 1)
    g.select(4, 1, extend=True)
    app.processEvents()
    w.grab().save(str(OUT / "sheet.png"))
    w.toggle_formulas(True)
    app.processEvents()
    w.grab().save(str(OUT / "sheet-formulas.png"))
    w.toggle_formulas(False)
    for i in range(w.ribbon.count()):
        w.ribbon.setCurrentIndex(i)
        app.processEvents()
        w.ribbon_top.grab().save(str(OUT / f"ribbon-{i}.png"))
    check("window rendered", (OUT / "sheet.png").stat().st_size > 5000)


fails = [r for r in results if not r[1]]
print(f"{len(results) - len(fails)}/{len(results)} passed")
with open(OUT / "notices.txt", "a") as f:
    f.write(f"sheet: {len(results) - len(fails)}/{len(results)} passed\n")
    for name, _ok, detail in fails[:20]:
        f.write(f"FAIL {name}: {detail.splitlines()[-1] if detail else ''}\n")
sys.exit(1 if fails else 0)
