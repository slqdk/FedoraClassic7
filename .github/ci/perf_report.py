#!/usr/bin/python3
"""Tables from perf_ci.sh's measurements.

    perf_report.py APPS.jsonl HELPERS.txt CONDITION...

APPS.jsonl: perf_run.py lines, label "CONDITION:program". HELPERS.txt: lines
"CONDITION label wall_s user_s sys_s maxrss_kb exit".
"""
import json
import statistics
import sys
from collections import defaultdict


def main(apps_path: str, helpers_path: str, conds: list[str]) -> int:
    runs = defaultdict(list)
    info = {}
    for line in open(apps_path):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        cond, _, app = r["label"].partition(":")
        if r.get("kind") == "exited":
            info.setdefault(app, {})["note"] = f"exited ({r.get('code')})"
            continue
        runs[(cond, app)].append(r)
        info.setdefault(app, {}).update(rss=r.get("rss_mb"), pss=r.get("pss_mb"), modules=r.get("modules"))
    apps = sorted({a for _c, a in runs}, key=lambda a: -statistics.median(
        x["total_ms"] for x in runs.get((conds[0], a), runs.get((conds[-1], a), [{"total_ms": 0}]))))
    print("Start-up until the first window is drawn, median of the runs (ms)")
    head = f"{'program':22}" + "".join(f"{c:>10}" for c in conds) + f"{'PySide6':>9}{'saved':>8}{'MB':>7}{'mods':>6}"
    print(head)
    sums = defaultdict(float)
    for a in apps:
        cells = []
        for c in conds:
            xs = runs.get((c, a))
            if xs:
                m = statistics.median(x["total_ms"] for x in xs)
                sums[c] += m
                cells.append(f"{m:10.0f}")
            else:
                cells.append(f"{'-':>10}")
        first, last = runs.get((conds[0], a)), runs.get((conds[-1], a))
        saved = (statistics.median(x["total_ms"] for x in first) - statistics.median(x["total_ms"] for x in last)
                 if first and last else 0)
        py = statistics.median(x.get("pyside_import", 0) for x in (last or first))
        i = info.get(a, {})
        print(f"{a:22}" + "".join(cells) + f"{py:9.0f}{saved:8.0f}{(i.get('pss') or 0):7.0f}{(i.get('modules') or 0):6}")
    print(f"{'sum':22}" + "".join(f"{sums[c]:10.0f}" for c in conds))
    notes = {a: i["note"] for a, i in info.items() if "note" in i}
    if notes:
        print("not measured: " + ", ".join(f"{a} {n}" for a, n in sorted(notes.items())))
    print()
    print("Helpers (wall s / CPU s / max memory MB)")
    rows = defaultdict(dict)
    for line in open(helpers_path):
        p = line.split()
        if len(p) < 7:
            continue
        cond, label = p[0], p[1]
        try:
            wall, user, sys_, rss = float(p[2]), float(p[3]), float(p[4]), int(p[5]) / 1024
        except ValueError:
            continue
        rows[label][cond] = f"{wall:5.2f}/{user + sys_:4.2f}/{rss:4.0f}" + ("" if p[6] == "0" else f" x{p[6]}")
    print(f"{'helper':28}" + "".join(f"{c:>22}" for c in conds))
    for label, by in rows.items():
        print(f"{label:28}" + "".join(f"{by.get(c, '-'):>22}" for c in conds))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3:]))
