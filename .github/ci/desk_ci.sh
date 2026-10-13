# The taskbar and windows in a nested Plasma session (KWin's X11-windowed backend inside Xvfb,
# so the whole screen can be photographed): Show desktop button, Alt+Tab, Aero Shake,
# Win+Up/Down, the Start menu jump list, Ctrl+Alt+Del.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/share/plasma/. /usr/share/plasma/
cp -a $S/usr/share/kwin-wayland/. /usr/share/kwin-wayland/
cp -a $S/usr/share/applications/. /usr/share/applications/
cp -a $S/usr/share/classic7/. /usr/share/classic7/
cp -a $S/usr/share/desktop-directories/. /usr/share/desktop-directories/
cp -a $S/etc/xdg/menus/. /etc/xdg/menus/
cp -a $S/etc/skel/. /etc/skel/
while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" == \#* ]] && continue
    if [[ "$line" =~ ^\[(.*)\]$ ]]; then group="${BASH_REMATCH[1]}"; continue; fi
    kwriteconfig6 --file /etc/xdg/kwinrc --group "$group" --key "${line%%=*}" -- "${line#*=}"
done < /usr/share/classic7/xdg-defaults/kwinrc
cat /etc/xdg/kwinrc > /out/kwinrc.txt
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
export XDG_MENU_PREFIX=plasma-
cp -an /etc/skel/. $HOME/
mkdir -p $HOME/Documents && cd $HOME/Documents && touch "Budget 2026.docx" "Letter to Anna.docx" "Holiday.pptx"
python3 -c "
from PySide6.QtCore import QSettings
s = QSettings('Classic7', 'Write'); s.setValue('recent', ['$HOME/Documents/Budget 2026.docx', '$HOME/Documents/Letter to Anna.docx']); s.sync()
"
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
# services started over D-Bus (activity manager, portals) must find the nested session too
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME >> /out/sycoca.log 2>&1
for p in /usr/libexec/kactivitymanagerd /usr/lib64/libexec/kactivitymanagerd; do [ -x $p ] && { $p > /out/kamd.log 2>&1 & break; }; done
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 30
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1); echo "kwin window: $WIN" >> /out/kwin.log
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
shot 01-desktop
# three windows
(DISPLAY= classic7-control >/dev/null 2>&1 &)
(DISPLAY= classic7-computer >/dev/null 2>&1 &)
(DISPLAY= classic7-taskmgr --performance >/dev/null 2>&1 &)
sleep 8
shot 02-windows
# Alt+Tab (held)
X keydown alt; X key Tab; sleep 1.2; shot 03-alt-tab; X key Tab; sleep 0.6; shot 04-alt-tab-2; X keyup alt
sleep 1
# pin Write, Mail and Show like the updater does, so the Start menu has jump lists to show
CLASSIC7_LIB=/usr/lib/classic7 python3 -c "
import sys; sys.path.insert(0, '/usr/lib/classic7')
import update_core as u, classic7appearance as b
r = b.Runner(); b.run_plasma_script(u.pin_script(u.PIN_ADDITIONS), r); print(r.failures)" >> /out/kwin.log 2>&1
sleep 2
# the Start menu
X mousemove 30 790 click 1; sleep 3; shot 05-start
CLASSIC7_LIB=/usr/lib/classic7 timeout 200 python3 /src/.github/ci/desk_test.py /out > /out/desk.log 2>&1
echo "exit $?" >> /out/desk.log
# All Programs, and Windows 7's Accessories folder in it (the first folder)
X key Escape; sleep 1
X mousemove 30 790 click 1; sleep 3
X mousemove 60 713 click 1; sleep 2; shot 14-all-programs
X mousemove 80 314 click 1; sleep 2; shot 15-accessories
X key Escape; sleep 1
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
grep -E "^(OK|FAIL|FAILURES|exit|Traceback|[A-Za-z]+Error)" /out/desk.log > /out/notices.txt
grep -iE "error|qml|warning" /out/plasmashell.log | grep -iE "classic7|showdesktop|startmenu" | head -8 | sed 's/^/plasma: /' >> /out/notices.txt
grep -iE "classic7|tabbox|script" /out/kwin.log | head -8 | sed 's/^/kwin: /' >> /out/notices.txt
