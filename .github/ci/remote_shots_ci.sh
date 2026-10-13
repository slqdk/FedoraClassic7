# README pictures for Remote Desktop, in a nested KWin session with the image's look: System
# Properties > Remote with "Allow connections" chosen, and Remote Desktop Connection (short form,
# options, the Windows Security box).
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/share/applications/. /usr/share/applications/
cp -a $S/usr/share/classic7/. /usr/share/classic7/
cp -a $S/etc/skel/. /etc/skel/
hostname classic7-pc 2>/dev/null; echo classic7-pc > /etc/hostname
useradd -m -u 1000 tester > /out/useradd.log 2>&1
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
mkdir -p $HOME/.config/classic7
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME PATH >> /out/sycoca.log 2>&1
sleep 3
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
X mousemove 1170 790
# 1) System Properties > Remote, "Allow connections" chosen (not applied: this container has no user systemd)
cat > /tmp/remote_tab.py <<'EOP'
import sys
sys.path.insert(0, "/usr/lib/classic7")
from PySide6.QtWidgets import QApplication
app = QApplication(["classic7-system"])
app.setApplicationName("System")
app.setDesktopFileName("classic7-system")
import system_app
d = system_app.SystemProperties(None, 4)
d.remote_any.setChecked(True)
d.show()
app.exec()
EOP
(timeout 30 python3 /tmp/remote_tab.py > /out/remote_tab.log 2>&1 &)
sleep 8
shot 01-remote-settings
pkill -f remote_tab.py; sleep 2
# 2) Remote Desktop Connection
printf 'full address:s:office-pc\r\nusername:s:OFFICE\\anna\r\nscreen mode id:i:2\r\n' | iconv -t UTF-16 > $HOME/.config/classic7/Default.rdp
(timeout 90 classic7-mstsc > /out/mstsc.log 2>&1 &)
sleep 7
shot 02-mstsc
X key alt+o; sleep 3
shot 03-mstsc-general
X key ctrl+Tab; sleep 1; shot 04-mstsc-display
X key ctrl+Tab; sleep 1; shot 05-mstsc-local
X key ctrl+Tab; sleep 1; shot 06-mstsc-experience
X key ctrl+Tab; sleep 1; shot 07-mstsc-advanced
X key ctrl+Tab; sleep 1
X key alt+n; sleep 4
shot 08-credentials
X key Escape; sleep 2
shot 09-after-cancel
pkill -f classic7-mstsc
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 240 dbus-run-session -- bash /tmp/inner.sh"
{ echo "files: $(ls /out | tr '\n' ' ')"; tail -n 5 /out/remote_tab.log /out/mstsc.log; } > /out/notices.txt 2>&1
