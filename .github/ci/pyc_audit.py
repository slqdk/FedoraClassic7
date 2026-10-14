#!/usr/bin/python3
"""Which compiled Python files (.pyc) an installed Classic 7 can use.

An installed system is an ostree deployment: every file in /usr has the modification time 0
(1970-01-01). A .pyc made in "timestamp" mode records the time of its .py file; when that isn't 0,
Python finds it stale, compiles the .py again at every start and can't save the result (/usr is
read-only). A .pyc made in hash mode ("checked-hash"/"unchecked-hash") doesn't depend on times.

    pyc_audit.py ROOT...     one line per package: files, usable after install, stale, no .pyc
"""
import os
import struct
import sys
from collections import defaultdict
from importlib.util import MAGIC_NUMBER, cache_from_source


def group_of(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    parts = rel.split(os.sep)
    if "site-packages" in parts:
        i = parts.index("site-packages")
        name = parts[i + 1] if len(parts) > i + 1 else "?"
        return "site-packages/" + name.removesuffix(".py")
    if root.rstrip("/").endswith("classic7"):
        return "classic7"
    return "stdlib/" + (parts[0].removesuffix(".py") if len(parts) > 1 else "(top)")


def main(roots: list[str]) -> int:
    stats = defaultdict(lambda: {"py": 0, "lines": 0, "ok_installed": 0, "stale_installed": 0, "missing": 0,
                                 "hash": 0, "stamp0": 0, "wrong_magic": 0})
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("__pycache__", "test", "tests", "idlelib", "tkinter",
                                                             "turtledemo", "lib2to3")]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                src = os.path.join(dirpath, fn)
                g = stats[group_of(src, root)]
                g["py"] += 1
                try:
                    with open(src, "rb") as f:
                        g["lines"] += f.read().count(b"\n")
                except OSError:
                    pass
                pyc = cache_from_source(src)
                try:
                    with open(pyc, "rb") as f:
                        head = f.read(16)
                except OSError:
                    g["missing"] += 1
                    continue
                if head[:4] != MAGIC_NUMBER:
                    g["wrong_magic"] += 1
                    continue
                flags = struct.unpack("<I", head[4:8])[0]
                if flags & 1:
                    g["hash"] += 1
                    g["ok_installed"] += 1
                    continue
                mtime = struct.unpack("<I", head[8:12])[0]
                if mtime == 0:
                    g["stamp0"] += 1
                    g["ok_installed"] += 1
                else:
                    g["stale_installed"] += 1
    big = sorted(stats.items(), key=lambda kv: -kv[1]["lines"])
    tot = defaultdict(int)
    print(f"{'package':42} {'.py':>6} {'lines':>8} {'ok':>6} {'stale':>6} {'no pyc':>6} {'hash':>6} {'t=0':>6}")
    for name, s in big:
        for k, v in s.items():
            tot[k] += v
        if s["lines"] >= 2000 or name == "classic7" or name.startswith("site-packages/PySide6"):
            print(f"{name:42} {s['py']:6} {s['lines']:8} {s['ok_installed']:6} {s['stale_installed']:6} "
                  f"{s['missing']:6} {s['hash']:6} {s['stamp0']:6}")
    print(f"{'TOTAL':42} {tot['py']:6} {tot['lines']:8} {tot['ok_installed']:6} {tot['stale_installed']:6} "
          f"{tot['missing']:6} {tot['hash']:6} {tot['stamp0']:6}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
