# Performance, part 3: part 2 (perf2_ci.sh: start-up profiles with every .pyc usable, idle desktop)
# with this branch's code, to compare the start-up times with part 2's (the released code).
# Part 1 is perf_ci.sh (start-up times as installed and fixed, helpers, .pyc audit).
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick >/out/dnf.log 2>&1 || true
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
ROOTS="/usr/lib/classic7 /usr/lib64/python$PYV /usr/lib/python$PYV"
{ echo "python $PYV"; rpm -q python3 python3-pyside6 plasma-workspace kwin kvantum; nproc
  grep -m1 'model name' /proc/cpuinfo; free -m; } > /out/versions.txt 2>&1
rm -f /usr/share/dbus-1/services/org.bluez.obex.service
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
for d in plasma kwin kwin-wayland applications classic7; do cp -a $S/usr/share/$d/. /usr/share/$d/; done
# an installed system: every file has the time 0; everything compiled in hash mode (the fix)
find $ROOTS -xdev \( -type f -o -type l \) -exec touch -h -d @0 {} + 2>/dev/null
python3 -m compileall -q -f -j0 --invalidation-mode checked-hash $ROOTS > /out/compile.log 2>&1
useradd -m -u 1000 tester 2>/dev/null
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
/usr/libexec/classic7-first-login > /out/first-login.log 2>&1
/usr/libexec/classic7-sessiond > /out/sessiond.log 2>&1 &
sleep 1
/usr/libexec/classic7-tray-fix > /out/tray-fix.log 2>&1
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 5
classic7-quickshot --background > /out/quickshot.log 2>&1 &
sleep 50
python3 /tmp/perf_idle.py 90 /out/idle.txt
PIC=$(find /usr/share/wallpapers -name '*.jpg' 2>/dev/null | head -1)
prof() {   # name command...: a profile of the start-up, then three plain runs
    local name=$1; shift
    C7_PROFILE=/out/profile-$name.txt C7_T0=$(date +%s%N) timeout 40 python3 /tmp/perf_run.py /out/prof.jsonl "P:$name" "$@" \
        > /dev/null 2>> /out/prof-errors.log
    pkill -u tester -P 1 2>/dev/null; sleep 0.3
    for r in 1 2 3; do
        C7_T0=$(date +%s%N) timeout 40 python3 /tmp/perf_run.py /out/apps.jsonl "C:$name" "$@" > /dev/null 2>> /out/prof-errors.log
        pkill -u tester -P 1 2>/dev/null; sleep 0.3
    done
}
prof write /usr/bin/classic7-write
prof sheet /usr/bin/classic7-sheet
prof show /usr/bin/classic7-show
prof paint /usr/bin/classic7-paint
prof mail /usr/bin/classic7-mail
prof appearance /usr/bin/classic7-appearance
prof control /usr/bin/classic7-control
prof taskmgr /usr/bin/classic7-taskmgr
prof firewall /usr/bin/classic7-firewall
prof prompt /usr/bin/classic7-prompt
prof computer /usr/bin/classic7-computer
prof photos /usr/bin/classic7-photos $PIC
prof notepad /usr/bin/classic7-notepad
prof run /usr/bin/classic7-run
# what the Action Center's check runs
H C firewall-cmd--state firewall-cmd --state
H C rpm-ostree-status rpm-ostree status --json
H C coredumpctl-list coredumpctl --no-pager --json=short --since=-7d list
H C actioncenter--json classic7-actioncenter --json
H C network--json classic7-network --json
H C nmcli-device-status nmcli -t -f DEVICE,TYPE,STATE,CON-UUID,CONNECTION device status
# what the programs fill in after their window is up (spelling, firewall settings, process list,
# Personalization's pictures, Mail's web view): a picture after 6 s, and their messages
for spec in "write|classic7-write" "show|classic7-show" "firewall|classic7-firewall" "taskmgr|classic7-taskmgr" \
            "appearance|classic7-appearance" "mail|classic7-mail"; do
    name=${spec%%|*}; cmd=${spec#*|}
    $cmd > /out/run-$name.log 2>&1 &
    sleep 6
    DISPLAY=:99 import -window root /out/later-$name.png
    pkill -u tester -f "$cmd"; sleep 0.5; pkill -u tester -P 1; sleep 1
done
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh" > /out/inner.log 2>&1
python3 /tmp/perf_report.py /out/apps.jsonl /out/helpers.txt C > /out/report.txt 2>&1
{ cat /out/report.txt; head -16 /out/idle.txt; } > /out/notices.txt 2>&1
