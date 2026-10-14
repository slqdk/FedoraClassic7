# Performance: where the time goes on an installed Classic 7.
#  1. Which compiled Python files (.pyc) an installed system can use (pyc_audit.py). An installed
#     system is an ostree deployment: every file in /usr has the time 0, so .pyc files made in
#     timestamp mode count as stale and Python compiles the code again at every start.
#  2. Every Classic 7 program's start-up until its first window is drawn (perf_run.py), in a nested
#     Plasma session (KWin in Xvfb, QPainter): A = as installed (all times 0, nothing saved);
#     B = our own code compiled in hash mode; C = everything (Python's library, PySide6...) too.
#  3. The helpers the taskbar runs now and then, and those that run at login.
#  4. The desktop left alone for a minute: CPU per process, programs it starts, memory.
# Measures the released image as it is (nothing copied from the branch but the scripts).
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb >/out/dnf.log 2>&1 || true
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
ROOTS="/usr/lib/classic7 /usr/lib64/python$PYV /usr/lib/python$PYV"
{ echo "python $PYV"; rpm -q python3 python3-pyside6 plasma-workspace kwin kvantum; nproc
  grep -m1 'model name' /proc/cpuinfo; free -m; } > /out/versions.txt 2>&1
python3 /src/.github/ci/pyc_audit.py $ROOTS > /out/pyc-image.txt 2>&1
# an installed system: every file has the time 0
find $ROOTS -xdev \( -type f -o -type l \) -exec touch -h -d @0 {} + 2>/dev/null
useradd -m -u 1000 tester 2>/dev/null
chown -R tester $ROOTS          # so the session can compile them in hash mode for B and C
cp -an /etc/skel/. /home/tester/ && chown -R tester /home/tester
mkdir -p /out && chmod 777 /out
cp /src/.github/ci/perf_run.py /src/.github/ci/perf_idle.py /src/.github/ci/perf_report.py /tmp/
cat > /tmp/ptime.py <<'EOP'
# ptime.py OUT COND LABEL CMD...: wall, user and system CPU, peak memory of CMD (and its children)
import os, resource, subprocess, sys, time
out, cond, label, cmd = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
t = time.monotonic()
try:
    rc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=float(os.environ.get("PT_TIMEOUT", "60"))).returncode
except subprocess.TimeoutExpired:
    rc = "timeout"
wall = time.monotonic() - t
r = resource.getrusage(resource.RUSAGE_CHILDREN)
with open(out, "a") as f:
    f.write(f"{cond} {label} {wall:.3f} {r.ru_utime:.3f} {r.ru_stime:.3f} {r.ru_maxrss} {rc}\n")
EOP
chmod 755 /tmp/perf_*.py /tmp/ptime.py
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
export XDG_MENU_PREFIX=plasma- PYTHONDONTWRITEBYTECODE=1
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
ms() { echo $(( ($(date +%s%N) - $1) / 1000000 )); }
Xvfb :99 -screen 0 1280x860x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1260 --height 840 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME PYTHONDONTWRITEBYTECODE >> /out/sycoca.log 2>&1
for p in /usr/libexec/kactivitymanagerd /usr/lib64/libexec/kactivitymanagerd; do [ -x $p ] && { $p > /out/kamd.log 2>&1 & break; }; done
H() { python3 /tmp/ptime.py /out/helpers.txt "$@"; }
has_name() { dbus-send --session --print-reply --dest=org.freedesktop.DBus / org.freedesktop.DBus.NameHasOwner "string:$1" 2>/dev/null | grep -q true; }
start_sessiond() {   # $1 condition: time until Plasma could go on (the D-Bus name is there)
    local t0=$(date +%s%N)
    /usr/libexec/classic7-sessiond >> /out/sessiond.log 2>&1 &
    for i in $(seq 1 500); do has_name org.classic7.Session && break; sleep 0.01; done
    echo "$1 sessiond: D-Bus name after $(ms $t0) ms" >> /out/milestones.txt
}
APPS=(
  "notepad|/usr/bin/classic7-notepad" "calc|/usr/bin/classic7-calc" "charmap|/usr/bin/classic7-charmap"
  "paint|/usr/bin/classic7-paint" "stickynotes|/usr/bin/classic7-stickynotes" "write|/usr/bin/classic7-write"
  "sheet|/usr/bin/classic7-sheet" "show|/usr/bin/classic7-show" "mail|/usr/bin/classic7-mail"
  "photos|/usr/bin/classic7-photos PIC" "prompt|/usr/bin/classic7-prompt" "run|/usr/bin/classic7-run"
  "computer|/usr/bin/classic7-computer" "recyclebin|/usr/bin/classic7-recyclebin"
  "properties|/usr/bin/classic7-properties /usr/bin" "control|/usr/bin/classic7-control"
  "appearance|/usr/bin/classic7-appearance" "taskbar-props|/usr/bin/classic7-taskbar-properties"
  "taskmgr|/usr/bin/classic7-taskmgr" "security|/usr/bin/classic7-security" "system|/usr/bin/classic7-system"
  "devmgmt|/usr/bin/classic7-devmgmt" "diskmgmt|/usr/bin/classic7-diskmgmt" "eventvwr|/usr/bin/classic7-eventvwr"
  "msconfig|/usr/bin/classic7-msconfig" "resmon|/usr/bin/classic7-resmon" "firewall|/usr/bin/classic7-firewall"
  "programs|/usr/bin/classic7-programs" "network|/usr/bin/classic7-network" "timedate|/usr/bin/classic7-timedate"
  "mixer|/usr/bin/classic7-mixer" "actioncenter|/usr/bin/classic7-actioncenter" "update|/usr/bin/classic7-update --gui"
  "mstsc|/usr/bin/classic7-mstsc" "screensaver|/usr/bin/classic7-screensaver --settings"
)
PIC=$(find /usr/share/wallpapers -name '*.jpg' 2>/dev/null | head -1)
run_one() {   # condition name command... (prints nothing; one JSON line in apps.jsonl)
    local cond=$1 name=$2; shift 2
    C7_T0=$(date +%s%N) timeout 30 python3 $IMPORTTIME /tmp/perf_run.py ${OUT:-/out/apps.jsonl} "$cond:$name" "$@" \
        > /dev/null 2>> ${ERR:-/out/apps-$cond.log}
    local rc=$?
    [ $rc -ne 0 ] && echo "$cond $name rc=$rc" >> /out/apps-$cond.log
    [ $rc -eq 124 ] && echo "$cond:$name" >> /tmp/skip
    pkill -u tester -P 1 2>/dev/null      # what the program left behind (orphans of PID 1)
    sleep 0.3
}
run_apps() {   # condition rounds
    for round in $(seq 1 $2); do
        for spec in "${APPS[@]}"; do
            local name=${spec%%|*} cmd=${spec#*|}
            grep -qx "$1:$name" /tmp/skip 2>/dev/null && continue
            run_one $1 $name ${cmd//PIC/$PIC}
        done
    done
}
importtimes() {   # condition: -X importtime for the bigger programs
    for name in write sheet show mail photos control taskmgr computer appearance prompt notepad properties; do
        for spec in "${APPS[@]}"; do
            [[ "${spec%%|*}" == "$name" ]] || continue
            local cmd=${spec#*|}
            IMPORTTIME="-X importtime" OUT=/tmp/imp.jsonl ERR=/out/importtime-$1-$name.txt run_one $1 $name ${cmd//PIC/$PIC}
        done
    done
}
helpers() {   # condition
    H $1 python-empty python3 -c pass
    H $1 python-stdlib python3 -c "import json, subprocess, pathlib, re, dataclasses, typing, shutil"
    H $1 pyside6-import python3 -c "from PySide6 import QtCore, QtGui, QtWidgets"
    H $1 network--json classic7-network --json
    H $1 actioncenter--json classic7-actioncenter --json
    H $1 taskbar-pin--list classic7-taskbar-pin --list
    H $1 jumplist--json classic7-jumplist --json
    H $1 tray-fix /usr/libexec/classic7-tray-fix
    H $1 first-login /usr/libexec/classic7-first-login
    H $1 netdrive--reconnect classic7-netdrive --reconnect
    H $1 appearance--login-screen classic7-appearance --login-screen
    H $1 update--after-login classic7-update --after-login
    H $1 run-dialog-cmd classic7-run --help
    H $1 control--list classic7-control --list
    H $1 computer--list classic7-computer --list
}

# ---- condition A: as installed ------------------------------------------------------------
H A first-login-new-account /usr/libexec/classic7-first-login
start_sessiond A
H A tray-fix-new-account /usr/libexec/classic7-tray-fix
t0=$(date +%s%N)
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
for i in $(seq 1 600); do
    n=$(dbus-send --session --print-reply --dest=org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
        'string:print(panels().length)' 2>/dev/null | grep -o 'string "[0-9]*' | grep -o '[0-9]*$')
    [ -n "$n" ] && [ "$n" -gt 0 ] && break; sleep 0.1
done
echo "A plasmashell: taskbar after $(ms $t0) ms" >> /out/milestones.txt
run_one A quickshot-tray mod:quickshot_app --background
classic7-quickshot --background > /out/quickshot.log 2>&1 &
H A netdrive--reconnect classic7-netdrive --reconnect
sleep 45
python3 /tmp/perf_idle.py 60 /out/idle.txt
run_apps A 3
importtimes A
PT_TIMEOUT=300 H A update--settings classic7-update --settings
helpers A
# ---- condition B: our own code in hash mode -------------------------------------------------
python3 -m compileall -q -f --invalidation-mode checked-hash /usr/lib/classic7 > /out/compile-B.log 2>&1
run_apps B 2
helpers B
# ---- condition C: Python's library and the packages too --------------------------------------
t0=$(date +%s%N)
python3 -m compileall -q -f -j0 --invalidation-mode checked-hash /usr/lib64/python$PYV /usr/lib/python$PYV > /out/compile-C.log 2>&1
echo "C compileall of the library: $(ms $t0) ms" >> /out/milestones.txt
pkill -u tester -f classic7-sessiond; sleep 1
start_sessiond C
pkill -u tester -f "quickshot_app"; sleep 1
run_one C quickshot-tray mod:quickshot_app --background
classic7-quickshot --background >> /out/quickshot.log 2>&1 &
run_apps C 3
importtimes C
helpers C
# Kvantum (Aero, Basic) against Qt's Windows style (Classic), everything in hash mode
for name in notepad write sheet control taskmgr; do
    for spec in "${APPS[@]}"; do
        [[ "${spec%%|*}" == "$name" ]] || continue
        cmd=${spec#*|}
        for r in 1 2 3; do QT_STYLE_OVERRIDE=Windows run_one W $name $cmd; done
    done
done
sleep 5
python3 /tmp/perf_idle.py 30 /out/idle-C.txt
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh" > /out/inner.log 2>&1
python3 /src/.github/ci/pyc_audit.py $ROOTS > /out/pyc-after.txt 2>&1
python3 /tmp/perf_report.py /out/apps.jsonl /out/helpers.txt A B C W > /out/report.txt 2>&1
{ cat /out/milestones.txt; tail -1 /out/pyc-image.txt; cat /out/report.txt; head -20 /out/idle.txt; } > /out/notices.txt 2>&1
