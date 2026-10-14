# Dragging windows without 3D graphics: what KWin's CPU does while a window is dragged by its title
# bar, per look and per window border. This nested KWin composites with QPainter (on the CPU), as in
# a virtual machine without 3D. Same window, same path each time: KWin's, Xvfb's (it shows KWin's
# picture), Plasma's and the program's CPU time during the drag.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/out/dnf.log 2>&1 || true
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
for d in plasma kwin kwin-wayland applications classic7 desktop-directories aurorae color-schemes Kvantum themes wallpapers; do
    mkdir -p /usr/share/$d && cp -a $S/usr/share/$d/. /usr/share/$d/
done
cp -a $S/etc/xdg/. /etc/xdg/
cp -a $S/etc/skel/. /etc/skel/
rm -f /usr/share/dbus-1/services/org.bluez.obex.service     # fails and restarts over and over in a container
merge() {
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" =~ ^\[(.*)\]$ ]]; then group="${BASH_REMATCH[1]}"; continue; fi
        kwriteconfig6 --file "$2" --group "$group" --key "${line%%=*}" -- "${line#*=}"
    done < "$1"
}
merge /usr/share/classic7/xdg-defaults/kwinrc /etc/xdg/kwinrc
merge /usr/share/classic7/xdg-defaults/kdeglobals /etc/xdg/kdeglobals
{ rpm -q kwin aurorae plasma-workspace; ls /usr/share/kwin/decorations /usr/share/aurorae/themes
  for f in /usr/lib64/libkwin.so.6*; do echo "$f: $(grep -a -o 'KWIN_[A-Z_]*PERF[A-Z_]*' $f | sort -u | tr '\n' ' ')"; done
  nproc; grep -m1 'model name' /proc/cpuinfo; } > /out/versions.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out
cat > /tmp/kwjs.py <<'EOP'
# run a KWin script (argv[1]), or list the windows (--list)
import sys
sys.path.insert(0, "/usr/lib/classic7")
from PySide6.QtCore import QCoreApplication, QTimer
from kwin_bridge import KWinBridge
app = QCoreApplication([])
b = KWinBridge("CI")
if sys.argv[1] == "--list":
    def show(ws):
        for w in ws:
            print(f"  {w['caption']!r} {w['x']},{w['y']} {w['w']}x{w['h']}" + (" active" if w["active"] else ""))
        app.quit()
    b.windowsChanged.connect(show)
    b.refresh()
else:
    b.script(sys.argv[1])
QTimer.singleShot(2500, app.quit)
app.exec()
EOP
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
export XDG_MENU_PREFIX=plasma- KWIN_LOG_PERFORMANCE=1 KWIN_PERF_LOG=1
cp -an /etc/skel/. $HOME/
Xvfb :99 -screen 0 1280x860x24 >/dev/null 2>&1 &
XVFB=$!
sleep 2
cd /tmp
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1260 --height 840 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
KWIN=$!
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME >> /out/sycoca.log 2>&1
for p in /usr/libexec/kactivitymanagerd /usr/lib64/libexec/kactivitymanagerd; do [ -x $p ] && { $p > /out/kamd.log 2>&1 & break; }; done
/usr/libexec/classic7-first-login > /out/first-login.log 2>&1
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
PLASMA=$!
sleep 30
dbus-send --session --print-reply --dest=org.kde.KWin /Compositor org.freedesktop.DBus.Properties.Get \
    string:org.kde.kwin.Compositing string:compositingType > /out/compositing.txt 2>&1
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
kw() { python3 /tmp/kwjs.py "$1" >> /out/kwjs.log 2>&1; }
windows() { echo "== $1" >> /out/windows.txt; python3 /tmp/kwjs.py --list >> /out/windows.txt 2>&1; }
cpu() { [ -r /proc/$1/stat ] && sed 's/^.*) //' /proc/$1/stat | awk '{print $12+$13}' || echo 0; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
open_window() {   # Notepad at 100,120, 700x480, in front
    pkill -u tester -f classic7-notepad; sleep 1
    classic7-notepad /usr/share/classic7/changes.txt > /dev/null 2>&1 &
    sleep 6
    APP=$(pgrep -u tester -f "classic7-notepad" | head -1)
    kw "for (const w of workspace.windowList()) { if (w.normalWindow && w.caption.indexOf('Notepad') >= 0) {
        w.setMaximize(false, false); w.frameGeometry = {x: 100, y: 120, width: 700, height: 480};
        workspace.activeWindow = w; } }"
    sleep 2
}
legs() {   # xdotool commands: $1 legs of 50 steps of 6 px, a pause between legs
    local a=""
    for leg in $(seq 1 $1); do
        local d=6; [ $((leg % 2)) -eq 0 ] && d=-6
        for i in $(seq 1 50); do a="$a mousemove_relative -- $d 0 sleep 0.01"; done
        a="$a sleep 0.35"
    done
    echo "$a"
}
LEGS=$(legs 6)
measure() {   # label, then xdotool commands
    local label=$1; shift
    local k0=$(cpu $KWIN) x0=$(cpu $XVFB) p0=$(cpu $PLASMA) a0=$(cpu $APP) t0=$(date +%s%N)
    X "$@"
    local t=$(( ($(date +%s%N) - t0) / 1000000 ))
    local k=$(( ($(cpu $KWIN) - k0) * 10 )) x=$(( ($(cpu $XVFB) - x0) * 10 )) p=$(( ($(cpu $PLASMA) - p0) * 10 )) a=$(( ($(cpu $APP) - a0) * 10 ))
    printf "%-34s %6d ms   KWin %5d ms (%3d%% of a core)   Xvfb %5d   Plasma %4d   program %4d\n" \
        "$label" $t $k $(( k * 100 / (t > 0 ? t : 1) )) $x $p $a >> /out/drag.txt
}
run_look() {   # label: idle, pointer only, drag by the title (twice), a picture in the middle of a drag
    open_window
    windows "$1"
    grep -E "^(library|theme)=" $HOME/.config/kwinrc | tr '\n' ' ' >> /out/drag.txt; echo >> /out/drag.txt
    measure "$1: nothing (3 s)" sleep 3
    measure "$1: pointer only" mousemove 400 140 sleep 0.2 $LEGS
    measure "$1: drag" mousemove 400 134 sleep 0.3 mousedown 1 sleep 0.3 $LEGS mouseup 1
    sleep 1
    measure "$1: drag again" mousemove 400 134 sleep 0.3 mousedown 1 sleep 0.3 $LEGS mouseup 1
    windows "$1 after the drags"
    X mousemove 400 134 sleep 0.3 mousedown 1 sleep 0.3 mousemove_relative -- 150 0 sleep 0.5
    shot "drag-$1"; X mouseup 1; sleep 1
}
deco() {   # library theme
    kwriteconfig6 --file kwinrc --group org.kde.kdecoration2 --key library "$1"
    kwriteconfig6 --file kwinrc --group org.kde.kdecoration2 --key theme "$2"
    dbus-send --session --type=method_call --dest=org.kde.KWin /KWin org.kde.KWin.reconfigure
    sleep 3
}
look() { timeout 120 classic7-appearance --look "$1" > /out/apply-$1.log 2>&1; sleep 5; }

run_look aero
deco org.kde.kwin.aurorae __aurorae__svg__Classic7Aero; run_look aero-svg-border
deco org.kde.breeze Breeze; run_look aero-breeze-border
look aero
run_look aero-again            # the same as the first: how much the numbers vary
look basic; run_look basic
look classic; run_look classic
deco org.kde.breeze Breeze; run_look classic-breeze-border
ls -la /tmp $HOME $XDG_RUNTIME_DIR > /out/files-after.txt 2>&1
find / -xdev -newer /tmp/kwjs.py -iname '*perf*' -not -path '/proc/*' -not -path '/sys/*' 2>/dev/null | head -20 >> /out/files-after.txt
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh" > /out/inner.log 2>&1
for f in /tmp/kwin*perf* /home/tester/kwin*perf* /tmp/xdg-t/kwin*perf*; do [ -f "$f" ] && cp "$f" /out/; done
{ cat /out/compositing.txt | tail -1; cat /out/drag.txt; } > /out/notices.txt 2>&1
