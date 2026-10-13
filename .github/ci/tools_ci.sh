# System tools in a nested Plasma session: System Configuration (Startup, Services), Event Viewer
# (a journal with a few events of each level), Resource Monitor and Firewall (firewalld on its own
# system bus in the container), plus Date and Time.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
cp -a $S/usr/share/plasma/. /usr/share/plasma/
cp -a $S/usr/share/kwin-wayland/. /usr/share/kwin-wayland/
cp -a $S/usr/share/applications/. /usr/share/applications/
cp -a $S/usr/share/classic7/. /usr/share/classic7/
cp -a $S/usr/share/polkit-1/. /usr/share/polkit-1/
cp -a $S/etc/skel/. /etc/skel/
useradd -m -u 1000 -G systemd-journal,wheel tester 2>/dev/null
# a journal and a system bus with firewalld, as far as a container allows
mkdir -p /run/systemd/journal /run/log/journal /run/dbus
(/usr/lib/systemd/systemd-journald > /out/journald.log 2>&1 &)
dbus-daemon --system --fork > /out/sysbus.log 2>&1
sleep 2
for p in 0 2 3 4 6; do logger -p "user.$( echo emerg alert crit err warning notice info debug | cut -d' ' -f$((p + 1)) )" -t classic7-test "Test message at priority $p"; done
logger -p auth.info -t sudo "tester : TTY=pts/0 ; PWD=/home/tester ; USER=root ; COMMAND=/usr/bin/true"
(firewalld --nofork --nopid > /out/firewalld.log 2>&1 &)
sleep 6
firewall-cmd --state > /out/firewall-state.txt 2>&1
firewall-cmd --get-default-zone >> /out/firewall-state.txt 2>&1
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
mkdir -p $HOME/.config/autostart
printf '[Desktop Entry]\nType=Application\nName=Steam\nExec=steam -silent\nIcon=steam\n' > $HOME/.config/autostart/steam.desktop
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
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 25
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
journalctl --no-pager -n 5 > /out/journal-check.txt 2>&1
run() { (DISPLAY= timeout 40 "$@" > /out/$(basename $1).log 2>&1 &); }
run classic7-msconfig --tab startup; sleep 6; shot 01-msconfig-startup
pkill -f classic7-msconfig; sleep 1
run classic7-msconfig --tab services; sleep 7; shot 02-msconfig-services
pkill -f classic7-msconfig; sleep 1
run classic7-eventvwr; sleep 7; shot 03-eventvwr
pkill -f classic7-eventvwr; sleep 1
run classic7-resmon; sleep 6; shot 04-resmon
pkill -f classic7-resmon; sleep 1
run classic7-resmon --tab memory; sleep 5; shot 05-resmon-memory
pkill -f classic7-resmon; sleep 1
run classic7-firewall; sleep 6; shot 06-firewall
pkill -f classic7-firewall; sleep 1
run classic7-firewall --allowed; sleep 6; shot 07-firewall-allowed
pkill -f classic7-firewall; sleep 1
run classic7-firewall --onoff; sleep 5; shot 08-firewall-onoff
pkill -f classic7-firewall; sleep 1
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 600 dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/firewall-state.txt; head -5 /out/journal-check.txt; tail -3 /out/journald.log /out/firewalld.log;
  for f in /out/classic7-*.log; do echo "== $f"; tail -5 "$f"; done; } > /out/notices.txt 2>&1
