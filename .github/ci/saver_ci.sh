# Screen savers and the "Shutting down..." screen in a nested Plasma session: Screen Saver
# Settings; a screen saver started by the session helper after a minute without input
# (classic7-idle, built here) and ended by moving the mouse; screen savers started by hand and
# ended with a key; the Shutting down screen as KWin shows it (--preview: the session goes on).
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
. /src/.github/ci/native_build.sh
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
cp -a $S/usr/share/plasma/. /usr/share/plasma/
cp -a $S/usr/share/kwin-wayland/. /usr/share/kwin-wayland/
cp -a $S/usr/share/applications/. /usr/share/applications/
cp -a $S/usr/share/classic7/. /usr/share/classic7/
mkdir -p /usr/share/sddm/themes && cp -a $S/usr/share/sddm/themes/. /usr/share/sddm/themes/
cp -a $S/etc/skel/. /etc/skel/
useradd -m -u 1000 tester 2>/dev/null
ls -la /usr/libexec/classic7-idle /usr/libexec/classic7-grab > /out/native.txt 2>&1
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
mkdir -p $HOME/.config/classic7 $HOME/Desktop
cp /usr/share/classic7/desktop/*.desktop $HOME/Desktop/ 2>/dev/null && chmod +x $HOME/Desktop/*.desktop
printf '{"saver": "pipes", "minutes": 1, "lock": false, "text": "Classic 7"}\n' > $HOME/.config/classic7/screensaver.json
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
/usr/libexec/classic7-sessiond > /out/sessiond.log 2>&1 &
T0=$(date +%s)
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 22
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
savers() { pgrep -af "classic7-screensaver --run" | grep -v pgrep; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
shot 01-desktop
(DISPLAY= timeout 25 classic7-screensaver --settings > /out/settings.log 2>&1 &)
sleep 6
shot 02-settings
pkill -f "screensaver --settings"
# nobody touches anything: the screen saver comes after a minute
while [ $(( $(date +%s) - T0 )) -lt 72 ]; do sleep 1; done
shot 03-pipes-after-a-minute
echo "after a minute without input: $(savers | wc -l) screen saver(s): $(savers | head -1)" >> /out/result.txt
sleep 6
shot 04-pipes-later
# the mouse moves: it goes
X mousemove 300 300; sleep 0.3; X mousemove 600 420; sleep 0.3; X mousemove 640 460
sleep 3
shot 05-after-mouse
echo "after moving the mouse: $(savers | wc -l) screen saver(s)" >> /out/result.txt
for s in mystify text ribbons bubbles; do
    (DISPLAY= timeout 30 classic7-screensaver --run $s > /out/run-$s.log 2>&1 &)
    sleep 6
    [ $s = bubbles ] && sleep 4         # it takes a picture of the desktop first
    shot 06-$s
    X key space
    sleep 2
    echo "$s: $( [ -z "$(savers)" ] && echo "ended by a key" || echo "still running")" >> /out/result.txt
    pkill -f "screensaver --run" ; sleep 1
done
(timeout 30 classic7-goodbye --shutdown --preview 8 > /out/goodbye.log 2>&1 &)
sleep 4
shot 07-shutting-down
sleep 8
shot 08-after-preview
(timeout 30 classic7-goodbye --logoff --preview 5 > /out/goodbye2.log 2>&1 &)
sleep 3
shot 09-logging-off
sleep 5
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 600 dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/native.txt; cat /out/result.txt; grep -i "screen saver" /out/sessiond.log; tail -n 3 /out/goodbye.log /out/settings.log;
  for f in /out/run-*.log; do echo "== $f"; tail -n 3 "$f"; done; grep -iE "goodbye|qml|error" /out/kwin.log | tail -n 8; } > /out/notices.txt 2>&1
