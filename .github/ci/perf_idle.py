#!/usr/bin/python3
"""A desktop left alone: CPU time per process over SECONDS (children that ended are counted
with their parent), the programs started meanwhile, and the memory of each process.

    perf_idle.py SECONDS OUT.txt
"""
import os
import sys
import time

HZ = os.sysconf("SC_CLK_TCK")
ME = os.getpid()


def snap() -> dict:
    out = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == ME:
            continue
        try:
            st = open(f"/proc/{pid}/stat").read()
            comm = st[st.index("(") + 1:st.rindex(")")]
            f = st[st.rindex(")") + 2:].split()
            own = int(f[11]) + int(f[12])
            kids = int(f[13]) + int(f[14])
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
            out[pid] = (comm, own, kids, cmd[:150], int(f[1]))
        except (OSError, ValueError, IndexError):
            pass
    return out


def pss(pid: str) -> float:
    try:
        for line in open(f"/proc/{pid}/smaps_rollup"):
            if line.startswith("Pss:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def main(seconds: float, out_path: str) -> int:
    a = snap()
    started = {}
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        s = snap()
        for pid, v in s.items():
            if pid not in a and pid not in started:
                started[pid] = (round(time.monotonic() - t0, 1), v[3] or v[0], v[4])
        time.sleep(0.1)
    b = snap()
    rows = []
    for pid, v in b.items():
        if pid in a:
            own = (v[1] - a[pid][1]) * 1000 / HZ
            kids = (v[2] - a[pid][2]) * 1000 / HZ
            rows.append((own + kids, own, kids, pid, v[0], v[3]))
    rows.sort(reverse=True)
    with open(out_path, "w") as f:
        f.write(f"CPU time used in {seconds:.0f} s with nobody at the desktop (ms; 'children' = programs it "
                f"started that ended)\n")
        f.write(f"{'total':>7} {'own':>7} {'children':>8}  process\n")
        for tot, own, kids, pid, comm, cmd in rows:
            if tot > 0:
                f.write(f"{tot:7.0f} {own:7.0f} {kids:8.0f}  {pid} {comm}: {cmd}\n")
        f.write(f"\nprograms started during those {seconds:.0f} s ({len(started)}):\n")
        for pid, (t, cmd, ppid) in sorted(started.items(), key=lambda kv: kv[1][0]):
            parent = b.get(str(ppid), a.get(str(ppid), ("?",)))[0]
            f.write(f"  {t:5.1f} s  {cmd}   (from {parent})\n")
        f.write("\nmemory (PSS, MB) of the desktop's processes:\n")
        mem = sorted(((pss(pid), v[0], v[3]) for pid, v in b.items()), reverse=True)
        for mb, comm, cmd in mem[:30]:
            if mb >= 1:
                f.write(f"  {mb:7.1f}  {comm}: {cmd[:100]}\n")
        f.write(f"  {sum(m for m, _c, _x in mem):7.1f}  in all\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]), sys.argv[2]))
