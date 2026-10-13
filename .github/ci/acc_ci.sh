# Accessories in a nested Plasma session: Quick Shot (KWin screenshot, area, toolbars), Notepad,
# Calculator, Character Map, Sticky Notes, Paint.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out
. /src/.github/ci/native_build.sh
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
sleep 25
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
# KWin's screenshot interface straight from Python (is it allowed without a desktop-file permission?)
CLASSIC7_LIB=/usr/lib/classic7 python3 -c "
import sys; sys.path.insert(0, '/usr/lib/classic7')
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
import quickshot_app as q
img = q._grab_kwin(); print('kwin grab', None if img is None else (img.width(), img.height(), img.format()))
img2 = q._grab_spectacle(); print('spectacle grab', None if img2 is None else (img2.width(), img2.height()))
" > /out/grab.log 2>&1
(DISPLAY= classic7-notepad /etc/os-release > /out/notepad.log 2>&1 &)
sleep 5
(DISPLAY= classic7-quickshot --background > /out/quickshot.log 2>&1 &)
sleep 5
busctl --user call org.classic7.QuickShot /QuickShot org.classic7.QuickShot Capture s region >> /out/quickshot.log 2>&1
sleep 3
shot 01-dark
X mousemove 200 150 mousedown 1; sleep 0.3; X mousemove 400 300; sleep 0.3; X mousemove 640 420; sleep 0.3; X mouseup 1
sleep 1.5
shot 02-area
X key Escape; sleep 1
(DISPLAY= classic7-calc > /dev/null 2>&1 &)
(DISPLAY= classic7-charmap > /dev/null 2>&1 &)
sleep 6
shot 03-calc-charmap
(DISPLAY= classic7-paint > /out/paint.log 2>&1 &)
(DISPLAY= classic7-stickynotes > /out/notes.log 2>&1 &)
sleep 8
shot 04-paint-notes
cat $HOME/.config/classic7/stickynotes.json > /out/notes.json 2>&1
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/grab.log; tail -5 /out/quickshot.log; tail -3 /out/paint.log; tail -3 /out/notes.log; } > /out/notices.txt
