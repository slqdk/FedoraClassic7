# The taskbar's right-click menu (the compiled Plasma plugin), Cascade/Stacked/Side by side,
# and Programs and Features, in a nested Plasma session (KWin in Xvfb, like desk_ci.sh).
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out
. /src/.github/ci/native_build.sh
grep -h "INTERFACE_LINK_LIBRARIES" /usr/lib64/cmake/Plasma/PlasmaTargets.cmake > /out/plasma-deps.txt 2>&1
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/share/plasma/. /usr/share/plasma/
cp -a $S/usr/share/kwin-wayland/. /usr/share/kwin-wayland/
cp -a $S/usr/share/applications/. /usr/share/applications/
cp -a $S/usr/share/classic7/. /usr/share/classic7/
cp -a $S/etc/skel/. /etc/skel/
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME PATH >> /out/sycoca.log 2>&1
for p in /usr/libexec/kactivitymanagerd /usr/lib64/libexec/kactivitymanagerd; do [ -x $p ] && { $p > /out/kamd.log 2>&1 & break; }; done
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 30
grep -A2 "ActionPlugins" $HOME/.config/plasma-org.kde.plasma.desktop-appletsrc > /out/actionplugins.txt
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
(DISPLAY= classic7-control >/dev/null 2>&1 &)
(DISPLAY= classic7-computer >/dev/null 2>&1 &)
(DISPLAY= classic7-programs >/dev/null 2>&1 &)
sleep 10
shot 01-windows
# right-click the empty part of the taskbar (right of the task buttons)
X mousemove 760 790 click 3; sleep 2; shot 02-taskbar-menu
X key Escape; sleep 1
DISPLAY= classic7-arrange side > /out/arrange.log 2>&1; sleep 2; shot 03-side-by-side
DISPLAY= classic7-arrange stacked >> /out/arrange.log 2>&1; sleep 2; shot 04-stacked
DISPLAY= classic7-arrange cascade >> /out/arrange.log 2>&1; sleep 2; shot 05-cascade
# the menu's Start Task Manager entry: open the menu again and pick it by its text
X mousemove 760 790 click 3; sleep 2
DISPLAY= classic7-programs --list > /out/programs.txt 2>&1
{ id; flatpak list --app --columns=application,name,version,installation,size,origin; } > /out/flatpak.txt 2>&1
CLASSIC7_LIB=/usr/lib/classic7 python3 - >> /out/menu.log 2>&1 <<'EOP'
import subprocess, time
# KWin bridge: list windows and find Task Manager after clicking the menu entry found by OCR-free means:
# the menu is a QMenu; walk it with the keyboard: Down until "Start Task Manager" (7th entry incl. separators skipped)
for _ in range(5):
    subprocess.run(["xdotool", "key", "Down"], env={"DISPLAY": ":99"})
    time.sleep(0.2)
EOP
shot 06-menu-keyboard
X key Return; sleep 6; shot 07-after-enter
CLASSIC7_LIB=/usr/lib/classic7 python3 -c "
import sys; sys.path.insert(0, '/usr/lib/classic7')
from PySide6.QtCore import QCoreApplication, QTimer
from kwin_bridge import KWinBridge
app = QCoreApplication([]); b = KWinBridge('T')
b.windowsChanged.connect(lambda ws: (print('WINDOWS', [w['caption'] for w in ws]), app.quit()))
b.refresh(); QTimer.singleShot(4000, app.quit); app.exec()" >> /out/menu.log 2>&1
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
{
    grep -iE 'error|taskbarmenu.so' /out/build.log | head -8 | sed 's/^/build: /'
    sed 's/^/deps: /' /out/plasma-deps.txt
    grep -c . /out/programs.txt | sed 's/^/programs listed: /'
    head -3 /out/flatpak.txt | sed 's/^/flatpak: /'
    cat /out/actionplugins.txt
    grep WINDOWS /out/menu.log
    cat /out/arrange.log
    grep -iE "taskbarmenu|containmentaction" /out/plasmashell.log | head -5 | sed 's/^/plasma: /'
} > /out/notices.txt
