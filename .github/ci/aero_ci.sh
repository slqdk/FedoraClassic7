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
layout() {   # what the taskbar holds now
    dbus-send --session --print-reply --dest=org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
      'string:panels().forEach(function (p) { print(p.location + " " + p.height + ": " + p.widgets().map(function (w) {
          w.currentConfigGroup = ["General"]; var l = w.readConfig("look", ""); return w.type + (l ? "(" + l + ")" : ""); }).join(", ") + "\n"); });' \
      2>&1 | tail -n +2 | sed '1s/^ *string "//; $s/"$//' | grep -v '^$'
}
echo "== new account: $(layout)" >> /out/result.txt
(DISPLAY= classic7-control >/dev/null 2>&1 &)
(DISPLAY= classic7-notepad >/dev/null 2>&1 &)
sleep 7
shot 02-windows
X mousemove 26 780 click 1; sleep 3; shot 03-start
X key Escape; sleep 1
X keydown alt; X key Tab; sleep 1.2; shot 04-alt-tab; X keyup alt; sleep 1
(DISPLAY= classic7-appearance > /out/dialog.log 2>&1 &)
sleep 6; shot 05-personalization
X key ctrl+Tab; sleep 2; shot 06-window-color
X key Escape; sleep 1
apply() {  # $1 = name, rest = options
    local name=$1; shift
    timeout 120 classic7-appearance "$@" > /out/apply-$name.log 2>&1
    echo "== $name ($*): exit $? $(layout)" >> /out/result.txt
    sleep 6
}
apply basic --look basic; shot 07-basic
apply classic --look classic; shot 08-classic
apply ruby --look aero --glass ruby --intensity 70; shot 09-aero-ruby
apply opaque --transparency off; shot 10-aero-opaque
(DISPLAY= classic7-computer >/dev/null 2>&1 &)
sleep 6; shot 11-windows-opaque
cat $HOME/.config/classic7/appearance.json >> /out/result.txt
{ grep -E "^\[|theme=|LayoutName|BorderSize" $HOME/.config/kwinrc; grep -E "widgetStyle|ColorScheme|LookAndFeel" $HOME/.config/kdeglobals
  cat $HOME/.config/plasmarc; cat $HOME/.config/Kvantum/kvantum.kvconfig; gsettings get org.gnome.desktop.interface gtk-theme
  ls $HOME/.local/share/aurorae/themes $HOME/.local/share/plasma/desktoptheme 2>&1; } > /out/settings.txt 2>&1
cp $HOME/.cache/classic7/appearance.log /out/ 2>/dev/null
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/versions.txt; cat /out/result.txt; cat /out/first-login.log
  grep -iE "error|warning" /out/plasmashell.log | grep -iE "classic7|startmenu|showdesktop|clock|desktoptheme" | head -10 | sed 's/^/plasma: /'
  grep -iE "classic7|aurorae|tabbox" /out/kwin.log | head -8 | sed 's/^/kwin: /'
  grep -h "rc=[1-9]\|MISSING\|TIMEOUT\|ERROR" /out/appearance.log 2>/dev/null | head -10; } > /out/notices.txt 2>&1
