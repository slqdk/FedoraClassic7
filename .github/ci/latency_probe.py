#!/usr/bin/python3
"""How long the screen takes to show a hover highlight after the pointer moves (on X display :99,
where the nested KWin shows its picture).

    latency_probe.py find X Y            print the highlighted box around (X, Y): "top bottom left right"
    latency_probe.py measure LABEL X YA YB PX N OUT     N moves between rows YA and YB (pointer at X);
                                         the time until the pixel at (PX, row) changes, in ms -> OUT

The pointer is moved with XTest (no extra process per move); pixels are read with XGetImage, so a
change is seen within about a millisecond of reaching the screen.
"""
import json
import statistics
import sys
import time

from Xlib import X, display
from Xlib.ext import xtest

d = display.Display(":99")
root = d.screen().root


def move(x: int, y: int):
    xtest.fake_input(d, X.MotionNotify, x=x, y=y)
    d.sync()


def pixel(x: int, y: int) -> tuple:
    raw = root.get_image(x, y, 1, 1, X.ZPixmap, 0xFFFFFFFF).data
    return raw[2], raw[1], raw[0]          # BGRx -> RGB


def column(x: int, y0: int, y1: int) -> list:
    raw = root.get_image(x, y0, 1, y1 - y0, X.ZPixmap, 0xFFFFFFFF).data
    return [(raw[i + 2], raw[i + 1], raw[i]) for i in range(0, len(raw), 4)]


def row(y: int, x0: int, x1: int) -> list:
    raw = root.get_image(x0, y, x1 - x0, 1, X.ZPixmap, 0xFFFFFFFF).data
    return [(raw[i + 2], raw[i + 1], raw[i]) for i in range(0, len(raw), 4)]


def differs(a: tuple, b: tuple, tol: int = 12) -> bool:
    return any(abs(p - q) > tol for p, q in zip(a, b))


def find(x: int, y: int):
    """The box that changed colour when the pointer came to (x, y): compare with the pointer away."""
    move(x + 600, y)
    time.sleep(0.6)
    col_off, row_off = column(x, 0, 840), row(y, 0, 1260)
    move(x, y)
    time.sleep(0.6)
    col_on, row_on = column(x, 0, 840), row(y, 0, 1260)
    ys = [i for i in range(len(col_on)) if differs(col_on[i], col_off[i])]
    xs = [i for i in range(len(row_on)) if differs(row_on[i], row_off[i])]
    if not ys or not xs:
        print("none")
        return
    # the run of changed pixels that contains (x, y)
    top = bottom = y
    while top - 1 in ys:
        top -= 1
    while bottom + 1 in ys:
        bottom += 1
    left = right = x
    while left - 1 in xs:
        left -= 1
    while right + 1 in xs:
        right += 1
    print(top, bottom, left, right)


def wait_change(px: int, py: int, base: tuple, limit: float = 3.0) -> float | None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit:
        if differs(pixel(px, py), base):
            return (time.monotonic() - t0) * 1000
        time.sleep(0.0005)
    return None


def measure(label: str, x: int, ya: int, yb: int, px: int, n: int, out: str):
    ins, outs, missed = [], [], 0
    move(x, ya)
    time.sleep(0.8)
    for i in range(n):
        # from row A to row B: B lights up (in), A goes back (out)
        a, b = (ya, yb) if i % 2 == 0 else (yb, ya)
        time.sleep(0.25 + (i % 3) * 0.1)            # settled, at slightly different times
        base_b, lit_a = pixel(px, b), pixel(px, a)
        t0 = time.monotonic()
        move(x, b)
        t_in = wait_change(px, b, base_b)
        t_out = None
        if t_in is not None:
            while time.monotonic() - t0 < 3.0:
                if differs(pixel(px, a), lit_a):
                    t_out = (time.monotonic() - t0) * 1000
                    break
                time.sleep(0.0005)
        if t_in is None:
            missed += 1
        else:
            ins.append(t_in)
        if t_out is not None:
            outs.append(t_out)
    def stats(v):
        if not v:
            return {}
        v = sorted(v)
        return {"median": round(statistics.median(v), 1), "p90": round(v[int(len(v) * 0.9) - 1], 1),
                "min": round(v[0], 1), "max": round(v[-1], 1)}
    rec = {"label": label, "moves": n, "missed": missed, "highlight_on_ms": stats(ins), "highlight_off_ms": stats(outs)}
    with open(out, "a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


if __name__ == "__main__":
    if sys.argv[1] == "find":
        find(int(sys.argv[2]), int(sys.argv[3]))
    else:
        measure(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]),
                int(sys.argv[7]), sys.argv[8])
