"""The Classic 7 Experience Index: short tests of the processor, memory, disk, desktop graphics and
3D graphics, each scored from 1.0 to 7.9 as Windows 7 did. The base score is the lowest subscore.

    run(progress) -> dict      the results (also saved for Performance Information and Tools)

The graphics tests open a window for a few seconds each (perfinfo_gfx.py, in its own process); without
a display they are left out. The processor test runs one process per processor thread.
"""
from __future__ import annotations

import json
import math
import multiprocessing
import os
import random
import subprocess
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import perfinfo_core as pc

LIB = Path(__file__).resolve().parent
_DATA = b""


def scale(value: float, low: float, high: float) -> float:
    """1.0 at low, 7.9 at high, logarithmic in between (Windows 7's scores grow that way too)."""
    if value <= 0:
        return 1.0
    s = 1.0 + 6.9 * math.log(value / low) / math.log(high / low)
    return round(max(1.0, min(7.9, s)), 1)


# ---- processor --------------------------------------------------------------------------------
def _text(size: int) -> bytes:
    rnd = random.Random(7)
    words = ["classic", "window", "taskbar", "start", "menu", "explorer", "glass", "aero", "notepad", "paint",
             "computer", "folder", "document", "picture", "music", "video", "network", "printer", "the", "and",
             "a", "of", "to", "in", "is", "it", "you", "that", "was", "for", "on", "are", "with", "as", "this"]
    parts, n = [], 0
    while n < size:
        line = " ".join(rnd.choice(words) for _ in range(12)) + f" {rnd.randint(0, 99999)}\n"
        parts.append(line)
        n += len(line)
    return "".join(parts).encode()[:size]


def _compress_for(seconds: float) -> int:
    done, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < seconds:
        zlib.compress(_DATA, 6)
        done += len(_DATA)
    return done


def test_cpu() -> tuple[float, str, dict]:
    global _DATA
    _DATA = _text(4 * 1024 * 1024)
    t0 = time.perf_counter()
    one = _compress_for(1.2)
    single = one / (time.perf_counter() - t0) / 1e6
    try:
        threads = len(os.sched_getaffinity(0)) or 1
    except (AttributeError, OSError):
        threads = os.cpu_count() or 1
    ctx = multiprocessing.get_context("fork")
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=threads, mp_context=ctx) as pool:
        total = sum(pool.map(_compress_for, [1.5] * threads))
    multi = total / (time.perf_counter() - t0) / 1e6
    # 7.9: a fast core of today (about 35 MB/s) and eight or more of them; 1.0: an old netbook
    score = round((scale(single, 2, 35) + 2 * scale(multi, 4, 300)) / 3, 1)
    return score, f"compression {single:.0f} MB/s on one core, {multi:.0f} MB/s on {threads} threads", \
        {"single_mb_s": round(single, 1), "multi_mb_s": round(multi, 1), "threads": threads}


# ---- memory -----------------------------------------------------------------------------------
def test_memory() -> tuple[float, str, dict]:
    total = pc.meminfo().get("MemTotal", 0)
    avail = pc.meminfo().get("MemAvailable", 0)
    size = int(min(256 * 1024 * 1024, max(32 * 1024 * 1024, avail // 8)))
    a = bytearray(os.urandom(1024 * 1024)) * (size // (1024 * 1024))
    b = bytearray(len(a))
    b[:] = a                               # touch every page once
    n, t0 = 0, time.perf_counter()
    while time.perf_counter() - t0 < 1.2:
        b[:] = a
        n += 1
    gbs = n * len(a) / (time.perf_counter() - t0) / 1e9
    score = scale(gbs, 0.5, 25)
    gib = total / 1024 ** 3
    if gib < 3.5:
        score = min(score, 4.5)
    elif gib < 7.5:
        score = min(score, 5.9)
    return score, f"copies {gbs:.1f} GB/s; {gib:.1f} GB installed", {"copy_gb_s": round(gbs, 2), "total_gib": round(gib, 1)}


# ---- disk -------------------------------------------------------------------------------------
def test_disk() -> tuple[float, str, dict]:
    folder = pc.CACHE / "classic7"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "perfinfo-disk.tmp"
    block = bytearray(os.urandom(4 * 1024 * 1024))
    count = 64                              # 256 MB
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        t0 = time.perf_counter()
        for i in range(count):
            block[:8] = i.to_bytes(8, "little")
            os.write(fd, block)
            if i >= 8 and time.perf_counter() - t0 > 6:      # a slow disk (a memory card): enough
                count = i + 1
                break
        os.fsync(fd)
        write = count * len(block) / (time.perf_counter() - t0) / 1e6
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.close(fd)

        fd = os.open(path, os.O_RDONLY)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_SEQUENTIAL)
        t0, got = time.perf_counter(), 0
        while True:
            chunk = os.read(fd, 4 * 1024 * 1024)
            if not chunk:
                break
            got += len(chunk)
        read = got / (time.perf_counter() - t0) / 1e6
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_RANDOM)
        pages = list(range(count * len(block) // 4096))
        random.Random(3).shuffle(pages)
        n, t0 = 0, time.perf_counter()
        for p in pages:
            os.pread(fd, 4096, p * 4096)
            n += 1
            if n % 64 == 0 and time.perf_counter() - t0 > 1.5:
                break
        iops = n / (time.perf_counter() - t0)
        os.close(fd)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    score = round((scale(read, 20, 3000) + scale(iops, 60, 60000)) / 2, 1)
    return score, f"reads {read:.0f} MB/s, writes {write:.0f} MB/s, {iops:.0f} random 4 KB reads/s", \
        {"read_mb_s": round(read), "write_mb_s": round(write), "random_iops": round(iops)}


# ---- graphics (in their own process, with a window) ------------------------------------------------
def graphics_test(kind: str, timeout: float = 40) -> dict:
    try:
        r = subprocess.run([sys.executable, str(LIB / "perfinfo_gfx.py"), kind], capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
        for line in reversed(r.stdout.splitlines()):
            if line.startswith("{"):
                return json.loads(line)
        return {"error": (r.stderr.strip().splitlines() or ["no result"])[-1][:200]}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"error": str(e)[:200]}


def test_desktop(software: bool) -> tuple[float | None, str, dict]:
    """A window redrawn for every picture the screen shows. Full marks for keeping up with 60 pictures
    a second (or the screen's own rate if it is lower) with hardly any coming late."""
    r = graphics_test("desktop")
    if "fps" not in r:
        return None, f"not measured ({r.get('error', '?')})", r
    refresh = float(r.get("refresh") or 60)
    target = min(60.0, max(30.0, refresh))
    ratio = min(1.0, r["fps"] / target)
    # share of pictures later than one and a half pictures at 60 a second (25 ms): what looks jerky
    late = float(r.get("late_60" if refresh >= 59 else "late", 0))
    score = 1.0 + 6.9 * ratio ** 2 * max(0.0, 1 - 2 * late)
    if software:
        score = min(score, 3.9)            # no Aero without a graphics driver, as in Windows 7
    score = round(max(1.0, min(7.9, score)), 1)
    return score, (f"{min(r['fps'], refresh):.0f} pictures a second while a window is redrawn "
                   f"(the screen shows {refresh:.0f}), {late * 100:.0f}% late, slowest {r.get('slowest_ms', 0):.0f} ms"), r


def test_3d() -> tuple[float | None, str, dict]:
    r = graphics_test("3d")
    if r.get("no_gl"):
        return 1.0, f"no 3D graphics ({r.get('error', '?')})", r     # Windows 7 gave 1.0 without a 3D driver
    if "fps" not in r:
        return None, f"not measured ({r.get('error', '?')})", r
    # about 2 for drawing on the processor (llvmpipe), 4-5 for a recent built-in graphics chip, 7.9 for
    # a fast graphics card
    score = scale(r["fps"], 2, 1000)
    return score, f"{r['fps']:.1f} pictures a second with 120 see-through layers (OpenGL: " \
                  f"{r.get('renderer') or '?'})", r


# ---- all of it ------------------------------------------------------------------------------
def run(progress=lambda _pct, _text: None) -> dict:
    g = pc.graphics()
    has_display = bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
    steps = [("cpu", "Assessing the processor", test_cpu, 10),
             ("memory", "Assessing memory", test_memory, 30),
             ("disk", "Assessing the primary hard disk", test_disk, 42)]
    if has_display:
        steps += [("graphics", "Assessing desktop graphics", lambda: test_desktop(g.software), 62),
                  ("gaming", "Assessing 3D graphics", test_3d, 80)]
    res = {"version": 1, "date": time.strftime("%Y-%m-%d %H:%M"), "hardware": pc.hardware_key(),
           "scores": {}, "details": {}, "raw": {}, "renderer": g.renderer, "software_3d": g.software}
    for key, text, fn, pct in steps:
        progress(pct, text)
        try:
            score, detail, raw = fn()
        except Exception as e:  # noqa: BLE001 - one test failing leaves the others
            score, detail, raw = None, f"not measured ({type(e).__name__}: {e})", {}
        res["scores"][key] = score
        res["details"][key] = detail
        res["raw"][key] = raw
    if not has_display:
        for key in ("graphics", "gaming"):
            res["scores"][key] = None
            res["details"][key] = "not measured (no display)"
    progress(100, "Done")
    return res


def main_cli(json_lines: bool) -> int:
    def progress(pct, text):
        if json_lines:
            print(f"progress {pct} {text}", flush=True)
        else:
            print(f"{pct:3d}%  {text}", flush=True)
    res = run(progress)
    pc.save_scores(res)
    if json_lines:
        print("result " + json.dumps(res), flush=True)
    else:
        for key, name, _what in pc.COMPONENTS:
            s = res["scores"].get(key)
            print(f"{name:18} {s if s is not None else '-':>4}   {res['details'].get(key, '')}")
        b = pc.base_score(res)
        print(f"{'Base score':18} {b if b is not None else '-':>4}")
    return 0


if __name__ == "__main__":
    # its own process group: Cancel in the window ends the tests that run in other processes too
    try:
        os.setpgrp()
    except OSError:
        pass
    sys.exit(main_cli("--json" in sys.argv[1:]))
