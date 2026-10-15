# Performance Information and Tools in the image: the report and the issues without a window, the
# assessment (the graphics tests in a nested KWin, which composites with QPainter like a virtual
# machine without 3D; the 3D test draws off the screen with llvmpipe), and pictures of the pages and of
# the System window's rating.
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
python3 -m compileall -q -f --invalidation-mode checked-hash /usr/lib/classic7
rpm -q krdp kpipewire freerdp-libs ffmpeg-libs libavcodec-free x264-libs openh264 mesa-dri-drivers kwin > /out/versions.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out

# without a window, as root: the build's own checks
/usr/bin/classic7-perfinfo --help > /out/help.txt 2>&1
PYTHONPATH=/usr/lib/classic7 python3 -c "
import perfinfo_assess as a, perfinfo_core as c
assert a.scale(2, 2, 1000) == 1.0 and a.scale(1000, 2, 1000) == 7.9
assert c._duration('1min 3.200s') == 63.2
print('ok')" > /out/unit.txt 2>&1

cat > /tmp/kwjs.py <<'EOP'
import sys
sys.path.insert(0, "/usr/lib/classic7")
from PySide6.QtCore import QCoreApplication, QTimer
from kwin_bridge import KWinBridge
app = QCoreApplication([])
b = KWinBridge("CI")
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
DISPLAY=:99 KWIN_LOG_PERFORMANCE_DATA=1 kwin_wayland --x11-display :99 --width 1260 --height 840 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
KWIN=$!
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME >> /out/sycoca.log 2>&1
/usr/libexec/classic7-first-login > /out/first-login.log 2>&1
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
kw() { python3 /tmp/kwjs.py "$1" >> /out/kwjs.log 2>&1; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null

# the graphics tests on their own, then the whole assessment
for k in desktop 3d; do
    /usr/bin/time -f "$k: %e s, %P CPU" python3 /usr/lib/classic7/perfinfo_gfx.py $k > /out/gfx-$k.json 2>> /out/gfx-time.txt
done
/usr/bin/time -f "assessment: %e s" classic7-perfinfo --assess > /out/assess.txt 2>&1
# KWin's own record of its pictures (started with KWIN_LOG_PERFORMANCE_DATA=1, in /tmp)
classic7-perfinfo --kwin-perf > /out/kwin-perf.txt 2>&1
ls -la /tmp/kwin* >> /out/kwin-perf.txt 2>&1
for f in /tmp/kwin\ perf*; do head -3 "$f"; tail -3 "$f"; cp "$f" /out/; done > /out/kwin-perf-sample.txt 2>&1
cp $HOME/.local/share/classic7/perfinfo.json /out/perfinfo.json

# the report and the issues, as a user would make them
/usr/bin/time -f "report: %e s" classic7-perfinfo --report-text /out/report.txt > /out/report.log 2>&1
classic7-perfinfo --issues > /out/issues.txt 2>/dev/null
classic7-perfinfo --json > /out/facts.json 2>/dev/null
# as over SSH: no Wayland connection of its own (kscreen-doctor must use the desktop's socket, not crash)
env -u WAYLAND_DISPLAY -u QT_QPA_PLATFORM SSH_CONNECTION="10.0.0.1 5000 10.0.0.2 22" \
    classic7-perfinfo --report-text /out/report-ssh.txt > /out/report-ssh.log 2>&1
grep -A3 "== Displays" /out/report-ssh.txt >> /out/report-ssh.log
grep "Report made\|Sessions of" /out/report-ssh.txt >> /out/report-ssh.log
coredumpctl --no-pager list 2>/dev/null | tail -3 >> /out/report-ssh.log

# the pages
for page in home advanced report; do
    case $page in home) arg= ;; *) arg=--$page ;; esac
    classic7-perfinfo $arg > /out/gui-$page.log 2>&1 &
    sleep 14
    kw "for (const w of workspace.windowList()) { if (w.normalWindow && w.caption.indexOf('Performance') >= 0) {
        w.frameGeometry = {x: 20, y: 10, width: 940, height: 700}; workspace.activeWindow = w; } }"
    sleep 2
    shot perfinfo-$page
    pkill -f "classic7-perfinfo" ; sleep 1
done
classic7-system > /out/system.log 2>&1 &
sleep 8
shot system
pkill -f classic7-system; sleep 1
# the address bar: Small icons (the default) puts pages under All Control Panel Items, Category view
# under their category; the arrow after a part lists what is in it
classic7-control > /out/control.log 2>&1 &
sleep 8
shot control-small
pkill -f classic7-control; sleep 1
mkdir -p $HOME/.config/classic7 && echo '{"view": "category"}' > $HOME/.config/classic7/controlpanel.json
classic7-perfinfo --advanced > /out/gui-advanced-cat.log 2>&1 &
sleep 12
kw "for (const w of workspace.windowList()) { if (w.normalWindow && w.caption.indexOf('Performance') >= 0) {
    w.frameGeometry = {x: 20, y: 10, width: 940, height: 700}; workspace.activeWindow = w; } }"
sleep 2
X mousemove 330 54 click 1; sleep 1.5
shot perfinfo-address-menu
X key Escape; sleep 0.5
pkill -f classic7-perfinfo; sleep 1
rm -f $HOME/.config/classic7/controlpanel.json
# Rate this computer from the window (the dialog while it runs)
rm -f $HOME/.local/share/classic7/perfinfo.json
classic7-perfinfo --rate > /out/gui-rate.log 2>&1 &
sleep 9
shot perfinfo-rating
sleep 40
shot perfinfo-rated
pkill -f classic7-perfinfo
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh" > /out/inner.log 2>&1
{ cat /out/unit.txt; cat /out/gfx-time.txt; cat /out/gfx-desktop.json /out/gfx-3d.json; cat /out/assess.txt
  cat /out/kwin-perf.txt /out/kwin-perf-sample.txt
  cat /out/report.log; cat /out/issues.txt; grep -c . /out/report.txt; cat /out/report-ssh.log; cat /out/versions.txt
  grep -iE "error|traceback" /out/gui-*.log | head -8; } > /out/notices.txt 2>&1
