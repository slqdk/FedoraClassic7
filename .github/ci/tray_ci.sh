# The Windows 7 notification area in a nested Plasma session: the tray with the Classic 7 network,
# volume and Action Center icons and the clock (from the layout), each applet's popup (rendered
# with plasmawindowed on the outer X server, where xdotool can click it), the Volume Mixer with a
# program playing sound (PipeWire with a virtual speaker), Date and Time, Action Center, and the
# login fix that converts an older saved layout.
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
cp -a $S/etc/skel/. /etc/skel/
useradd -m -u 1000 tester 2>/dev/null
# the login fix on an older layout (Plasma's network, volume and clock)
cat > /tmp/old-appletsrc <<'EOF'
[Containments][2]
formfactor=2
location=4
plugin=org.kde.panel

[Containments][2][Applets][7]
plugin=org.kde.plasma.systemtray

[Containments][2][Applets][7][Applets][17]
plugin=org.kde.plasma.networkmanagement

[Containments][2][Applets][7][Applets][18]
plugin=org.kde.plasma.volume

[Containments][2][Applets][7][General]
extraItems=org.kde.plasma.networkmanagement,org.kde.plasma.volume,org.kde.plasma.battery
knownItems=org.kde.plasma.volume,org.kde.plasma.battery

[Containments][2][Applets][8]
plugin=org.kde.plasma.digitalclock
EOF
mkdir -p /tmp/fixhome/.config && cp /tmp/old-appletsrc /tmp/fixhome/.config/plasma-org.kde.plasma.desktop-appletsrc
HOME=/tmp/fixhome XDG_CONFIG_HOME=/tmp/fixhome/.config /usr/libexec/classic7-tray-fix > /out/tray-fix.log 2>&1
cp /tmp/fixhome/.config/plasma-org.kde.plasma.desktop-appletsrc /out/fixed-appletsrc.txt
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
# sound: PipeWire with a virtual speaker, and a program playing
(pipewire > /out/pipewire.log 2>&1 &)
sleep 1
(wireplumber > /out/wireplumber.log 2>&1 &)
(pipewire-pulse > /out/pipewire-pulse.log 2>&1 &)
sleep 3
pactl load-module module-null-sink sink_name=speakers sink_properties=device.description=Speakers > /out/pactl.log 2>&1
pactl set-default-sink speakers >> /out/pactl.log 2>&1
pactl set-sink-volume speakers 65% >> /out/pactl.log 2>&1
python3 - <<'EOP'
import math, struct, wave
with wave.open("/tmp/tone.wav", "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(44100)
    w.writeframes(b"".join(struct.pack("<hh", int(3000 * math.sin(i / 20)), int(3000 * math.sin(i / 20))) for i in range(44100 * 60)))
EOP
(timeout 300 pw-play --media-name "Tone" --properties 'application.name=Music Player' /tmp/tone.wav > /out/pwplay.log 2>&1 &)
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
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 30
pactl list short sink-inputs > /out/sink-inputs.txt 2>&1
grep -A3 "Applets\]\[[0-9]*\]$" $HOME/.config/plasma-org.kde.plasma.desktop-appletsrc | grep -E "^\[|plugin|extraItems" > /out/layout.txt
grep -E "extraItems|knownItems" $HOME/.config/plasma-org.kde.plasma.desktop-appletsrc >> /out/layout.txt
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
shot 01-taskbar
DISPLAY=:99 import -window root -crop 420x40+780+770 /out/01b-tray.png
# each applet on the outer X server, where xdotool can click it
n=2
for a in clock volume actioncenter; do
    (DISPLAY=:99 QT_QPA_PLATFORM=xcb timeout 40 plasmawindowed org.classic7.$a > /out/windowed-$a.log 2>&1 &)
    sleep 8
    W=$(X search --pid $(pgrep -n plasmawindowed) 2>/dev/null | tail -1)
    X windowmove $W 700 300 2>/dev/null; X windowsize $W 80 40 2>/dev/null
    sleep 1
    shot 0$n-$a-button
    X mousemove 730 315 click 1
    sleep 3
    shot 0$n-$a-popup
    pkill -n plasmawindowed; sleep 1
    n=$((n + 1))
done
(DISPLAY= timeout 40 classic7-mixer > /out/mixer.log 2>&1 &)
sleep 6
shot 05-mixer
(DISPLAY= timeout 40 classic7-timedate > /out/timedate.log 2>&1 &)
sleep 5
shot 06-timedate
(DISPLAY= timeout 40 classic7-actioncenter > /out/actioncenter.log 2>&1 &)
sleep 6
shot 07-actioncenter
classic7-actioncenter --json > /out/actioncenter.json 2>&1
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 600 dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/tray-fix.log; grep -E "plugin=|extraItems" /out/fixed-appletsrc.txt; cat /out/layout.txt | head -30; cat /out/sink-inputs.txt;
  cat /out/pactl.log | head -5; grep -i "qml\|error\|warn" /out/plasmashell.log | grep -i classic7 | head -10;
  for a in clock volume actioncenter; do grep -i "error\|warn" /out/windowed-$a.log | head -4; done;
  tail -3 /out/mixer.log /out/timedate.log /out/actioncenter.log; } > /out/notices.txt 2>&1
