# Hover latency without 3D graphics: the time from moving the pointer to the next row until that
# row's highlight is on the screen, in the Start menu (Plasma, Qt Quick) and in Notepad's File menu
# (Qt Widgets, Kvantum). Plasma first as it starts (which Qt Quick backend it picks is in
# plasmashell-*.log, QSG_INFO), then with Qt Quick's software renderer (QT_QUICK_BACKEND=software).
# This nested KWin composites with QPainter, as in a virtual machine without 3D.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool python3-xlib >/out/dnf.log 2>&1 || true
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
  nproc; grep -m1 'model name' /proc/cpuinfo; python3 -c "import Xlib; print('python3-xlib', Xlib.__version__)"
  for f in /usr/lib64/libKF6*.so.6 /usr/lib64/libPlasma*.so.6 /usr/bin/plasmashell; do
      k=$(grep -a -o 'QtQuickRendererSettings\|SceneGraphBackend\|RenderLoop' $f 2>/dev/null | sort -u | tr '\n' ' ')
      [ -n "$k" ] && echo "$f: $k"
  done; } > /out/versions.txt 2>&1
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
export XDG_MENU_PREFIX=plasma-
cp -an /etc/skel/. $HOME/
Xvfb :99 -screen 0 1280x860x24 >/dev/null 2>&1 &
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
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
kw() { python3 /tmp/kwjs.py "$1" >> /out/kwjs.log 2>&1; }
cpu() { [ -r /proc/$1/stat ] && sed 's/^.*) //' /proc/$1/stat | awk '{print $12+$13}' || echo 0; }
P() { python3 /src/.github/ci/latency_probe.py "$@"; }
start_plasma() {   # label, then environment for plasmashell
    local label=$1; shift
    pkill -x plasmashell; sleep 2
    env QSG_INFO=1 QT_FORCE_STDERR_LOGGING=1 "$@" plasmashell --no-respawn > /out/plasmashell-$label.log 2>&1 &
    PLASMA=$!
    sleep 25
}
start_menu() {   # label: open the Start menu, find two rows, measure moving between them
    local label=$1
    X mousemove 30 820 click 1; sleep 2.5
    shot "start-$label"
    local box=none y
    for y in 160 214 268 322 376; do
        box=$(P find 200 $y)
        echo "$label: row at $y = $box" >> /out/rows.txt
        [ "$box" != "none" ] && [ -n "$box" ] && break
    done
    if [ "$box" = "none" ] || [ -z "$box" ]; then X key Escape; return; fi
    read top bottom left right <<< "$box"
    local h=$(( bottom - top + 1 )) a=$(( (top + bottom) / 2 ))
    local b=$(( a + h ))
    local box2=$(P find 200 $b)
    echo "$label: next row at $b = $box2" >> /out/rows.txt
    [ "$box2" != "none" ] && { read t2 b2 l2 r2 <<< "$box2"; b=$(( (t2 + b2) / 2 )); }
    local px=$(( left + (right - left) * 3 / 4 ))
    local p0=$(cpu $PLASMA) k0=$(cpu $KWIN)
    P measure "$label" 200 $a $b $px 40 /out/latency.jsonl >> /out/probe.log 2>&1
    echo "$label: Plasma CPU $(( ($(cpu $PLASMA) - p0) * 10 )) ms, KWin CPU $(( ($(cpu $KWIN) - k0) * 10 )) ms for 40 moves" >> /out/rows.txt
    X key Escape; sleep 1
}
start_plasma default
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
start_menu start-menu-default
start_menu start-menu-default-again
# Notepad's File menu (Qt Widgets, Kvantum in Aero)
classic7-notepad > /dev/null 2>&1 &
sleep 6
kw "for (const w of workspace.windowList()) { if (w.normalWindow && w.caption.indexOf('Notepad') >= 0) {
    w.setMaximize(false, false); w.frameGeometry = {x: 100, y: 120, width: 700, height: 480};
    workspace.activeWindow = w; } }"
sleep 2
NP=$(pgrep -u tester -f classic7-notepad | head -1)
X mousemove 128 164 click 1; sleep 1.5
shot notepad-menu
box=$(P find 170 200)
echo "notepad: row at 200 = $box" >> /out/rows.txt
if [ "$box" != "none" ]; then
    read top bottom left right <<< "$box"
    h=$(( bottom - top + 1 )); a=$(( (top + bottom) / 2 )); b=$(( a + h ))
    px=$(( left + (right - left) * 3 / 4 ))
    n0=$(cpu $NP); k0=$(cpu $KWIN)
    P measure notepad-file-menu 170 $a $b $px 40 /out/latency.jsonl >> /out/probe.log 2>&1
    echo "notepad: program CPU $(( ($(cpu $NP) - n0) * 10 )) ms, KWin CPU $(( ($(cpu $KWIN) - k0) * 10 )) ms" >> /out/rows.txt
fi
X key Escape; sleep 0.5; pkill -f classic7-notepad; sleep 1
# Plasma with Qt Quick's software renderer
start_plasma software QT_QUICK_BACKEND=software
start_menu start-menu-software
start_menu start-menu-software-again
grep -iE "scenegraph|backend|renderer|GL_|rhi|software|opengl" /out/plasmashell-default.log | head -12 > /out/qsg-default.txt
grep -iE "scenegraph|backend|renderer|GL_|rhi|software|opengl" /out/plasmashell-software.log | head -12 > /out/qsg-software.txt
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh" > /out/inner.log 2>&1
{ cat /out/rows.txt; cat /out/latency.jsonl; echo "-- default:"; cat /out/qsg-default.txt; echo "-- software:"; cat /out/qsg-software.txt; } > /out/notices.txt 2>&1
