# Explorer details in a nested Plasma session: the copy progress window (classic7-sessiond owning
# KDE's job service before the desktop starts, fed by a real KIO copy), the Recycle Bin window and
# desktop icon, and the Windows 7 Properties window opened from Dolphin through the KDE plugin.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
. /src/.github/ci/native_build.sh
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
cp -a $S/usr/lib/systemd/user/. /usr/lib/systemd/user/
cp -a $S/usr/share/plasma/. /usr/share/plasma/
cp -a $S/usr/share/kwin-wayland/. /usr/share/kwin-wayland/
cp -a $S/usr/share/applications/. /usr/share/applications/
cp -a $S/usr/share/classic7/. /usr/share/classic7/
cp -a $S/etc/skel/. /etc/skel/
useradd -m -u 1000 tester 2>/dev/null
ls /usr/lib64/qt6/plugins/kf6/propertiesdialog/ > /out/plugins.txt 2>&1
which kioclient kioclient6 dolphin >> /out/plugins.txt 2>&1
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
mkdir -p $HOME/Desktop $HOME/Documents $HOME/Downloads
cp /usr/share/classic7/desktop/*.desktop $HOME/Desktop/ && chmod +x $HOME/Desktop/*.desktop
printf 'quarterly numbers\n' > $HOME/Documents/report.txt
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
# the session helper first, as its unit is ordered before the desktop
/usr/libexec/classic7-sessiond > /out/sessiond.log 2>&1 &
for i in $(seq 1 20); do busctl --user status org.classic7.Session >/dev/null 2>&1 && break; sleep 0.5; done
busctl --user list 2>/dev/null | grep -E "kuiserver|JobViewServer|classic7" > /out/names.txt
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 25
busctl --user list 2>/dev/null | grep -E "kuiserver|JobViewServer|classic7" >> /out/names.txt
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
shot 01-desktop
# a real KIO copy, big enough to take a few seconds
head -c 1200M /dev/urandom > $HOME/Downloads/big.bin
(timeout 120 kioclient copy $HOME/Downloads/big.bin $HOME/Documents/ > /out/kioclient.log 2>&1 &)
sleep 2.5
shot 02-copying
sleep 30
# the Recycle Bin: delete through KIO, then look at the desktop icon and the window
timeout 30 kioclient move $HOME/Documents/report.txt trash:/ >> /out/kioclient.log 2>&1
sleep 3
grep -h "^Icon=" $HOME/Desktop/recycle-bin.desktop > /out/recycle-icon.txt
cat $HOME/.config/trashrc >> /out/recycle-icon.txt 2>&1
(DISPLAY= timeout 60 classic7-recyclebin > /out/recyclebin.log 2>&1 &)
sleep 6
shot 03-recyclebin
X key Escape; sleep 1
# Properties from Dolphin: select the copied file and press Alt+Enter (KDE's Properties, which the
# plugin turns into the Windows 7 window)
(DISPLAY= timeout 60 dolphin --new-window --select $HOME/Documents/big.bin > /out/dolphin.log 2>&1 &)
sleep 8
X key alt+Return
sleep 6
shot 04-properties
pgrep -a -f classic7-properties > /out/properties-process.txt 2>&1
(DISPLAY= timeout 30 classic7-properties $HOME/Documents > /out/props.log 2>&1 &)
sleep 5
shot 05-folder-properties
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 600 dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/names.txt; cat /out/plugins.txt; cat /out/recycle-icon.txt; cat /out/properties-process.txt;
  tail -5 /out/sessiond.log; tail -3 /out/kioclient.log; grep -i "jobviewserver\|kuiserver" /out/plasmashell.log | head -5; } > /out/notices.txt
