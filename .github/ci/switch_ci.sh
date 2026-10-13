# The Aero look in a nested Plasma session (KWin's X11-windowed backend inside Xvfb): a new
# account (Aero from /etc/skel), windows, the Start menu, Alt+Tab, Personalization, then the
# switches to Basic, Classic and back to Aero in another glass colour.
# The nested KWin composites with QPainter (no OpenGL here), so glass is see-through but not blurred.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool kvantum >/out/dnf.log 2>&1 || true
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/
for d in plasma kwin-wayland applications classic7 desktop-directories aurorae color-schemes Kvantum themes wallpapers; do
    mkdir -p /usr/share/$d && cp -a $S/usr/share/$d/. /usr/share/$d/
done
cp -a $S/etc/xdg/. /etc/xdg/
cp -a $S/etc/skel/. /etc/skel/
merge() {
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" =~ ^\[(.*)\]$ ]]; then group="${BASH_REMATCH[1]}"; continue; fi
        kwriteconfig6 --file "$2" --group "$group" --key "${line%%=*}" -- "${line#*=}"
    done < "$1"
}
merge /usr/share/classic7/xdg-defaults/kwinrc /etc/xdg/kwinrc
merge /usr/share/classic7/xdg-defaults/kdeglobals /etc/xdg/kdeglobals
{ rpm -q kvantum; ls /usr/lib64/qt6/plugins/styles/; ls -d /usr/share/icons/*reeze*; } > /out/versions.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
export XDG_MENU_PREFIX=plasma-
cp -an /etc/skel/. $HOME/
ls -la $HOME/.config > /out/home-config.txt
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME >> /out/sycoca.log 2>&1
for p in /usr/libexec/kactivitymanagerd /usr/lib64/libexec/kactivitymanagerd; do [ -x $p ] && { $p > /out/kamd.log 2>&1 & break; }; done
/usr/libexec/classic7-first-login > /out/first-login.log 2>&1
gsettings get org.gnome.desktop.interface gtk-theme >> /out/first-login.log 2>&1
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 30
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
shot 01-desktop
dump() {   # every panel's widgets with ids, in AppletOrder, plus what Plasma still lists
    dbus-send --session --print-reply --dest=org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
      'string:panels().forEach(function (p) { p.currentConfigGroup = ["General"]; var ws = p.widgets();
          print(p.location + " locked=" + p.locked + " order=" + p.readConfig("AppletOrder", "") + " widgets=" +
                ws.map(function (w) { return w.id + ":" + w.type.split(".").pop() + "@" + w.index; }).join(" ") + "\n"); });' \
      2>&1 | tail -n +2 | sed '1s/^ *string "//; $s/"$//' | grep -v '^$'
}
T() { echo "--- $1"; dump; sleep 3; echo "  +3s:"; dump; sleep 7; echo "  +10s:"; dump; }
{
T "aero account"
timeout 120 classic7-appearance --look classic > /out/apply1.log 2>&1; T "after --look classic (exit $?)"
timeout 120 classic7-appearance --look aero > /out/apply2.log 2>&1; T "after --look aero (exit $?)"
# the old order: remove the old task buttons first, then add the new kind
cat > /tmp/b.js <<'EOJ'
var p = panels()[0];
var tm = p.widgets("org.kde.plasma.icontasks")[0];
var idx = tm.index;
tm.remove();
var fresh = p.addWidget("org.kde.plasma.taskmanager");
fresh.index = idx;
print("B done " + fresh.id);
EOJ
dbus-send --session --print-reply --dest=org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "string:$(cat /tmp/b.js)" 2>&1 | tail -n 1
T "after script B (remove, then add)"
cat > /tmp/a.js <<'EOJ'
var p = panels()[0];
var tm = p.widgets("org.kde.plasma.taskmanager")[0];
var idx = tm.index;
var fresh = p.addWidget("org.kde.plasma.icontasks");
tm.remove();
fresh.index = idx;
print("A done " + fresh.id);
EOJ
dbus-send --session --print-reply --dest=org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "string:$(cat /tmp/a.js)" 2>&1 | tail -n 1
T "after script A (add, then remove)"
cat > /tmp/c.js <<'EOJ'
var p = panels()[0];
var tm = p.widgets("org.kde.plasma.icontasks")[0];
var fresh = p.addWidget("org.kde.plasma.taskmanager");
tm.remove();
print("C done (no index change) " + fresh.id);
EOJ
dbus-send --session --print-reply --dest=org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "string:$(cat /tmp/c.js)" 2>&1 | tail -n 1
T "after script C (add, remove, no index)"
} > /out/result.txt 2>&1
shot 02-end
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/result.txt; grep -iE "applet|remove|destroy|warning" /out/plasmashell.log | grep -viE "pipewire|kpipewire" | tail -20; } > /out/notices.txt 2>&1
