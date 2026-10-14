# Window titles in Aero and Basic (the QML decoration: buttons hang from the top edge, the icon
# and title sit lower, a light behind the title on glass), glass drawn solid when KWin can't blur
# (this nested KWin composites with QPainter, like a virtual machine without 3D), the title font
# after switching looks without logging out, and Computer > Properties opening System.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool kvantum >/out/dnf.log 2>&1 || true
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
for d in plasma kwin kwin-wayland applications classic7 desktop-directories aurorae color-schemes Kvantum themes wallpapers; do
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
{ rpm -q kwin aurorae plasma-workspace; ls /usr/share/kwin/decorations; } > /out/versions.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out
cat > /tmp/kwjs.py <<'EOP'
# run a KWin script (argv[1]), or list the windows (--list)
import sys
sys.path.insert(0, "/usr/lib/classic7")
from PySide6.QtCore import QCoreApplication, QTimer
from kwin_bridge import KWinBridge
app = QCoreApplication([])
b = KWinBridge("CI")
if sys.argv[1] == "--list":
    def show(ws):
        for w in ws:
            print(f"  {w['caption']!r} {w['x']},{w['y']} {w['w']}x{w['h']}" + (" active" if w["active"] else ""))
        app.quit()
    b.windowsChanged.connect(show)
    b.refresh()
else:
    b.script(sys.argv[1])
QTimer.singleShot(2500, app.quit)
app.exec()
EOP
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
export XDG_MENU_PREFIX=plasma-
cp -an /etc/skel/. $HOME/
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
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 30
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
zoom() {   # $1 picture, $2 part (WxH+X+Y), $3 name: the part three times as large
    convert "/out/$1.png" -crop "$2" +repage -filter point -resize 300% "/out/$3.png"; }
kw() { DISPLAY= python3 /tmp/kwjs.py "$1" >> /out/kwjs.log 2>&1; }
windows() { echo "== $1" >> /out/windows.txt; DISPLAY= python3 /tmp/kwjs.py --list >> /out/windows.txt 2>&1; }
place() {   # part of the caption, x y w h: move and size the window, make it the active one
    kw "for (const w of workspace.windowList()) { if (w.normalWindow && w.caption.indexOf('$1') >= 0) {
        w.setMaximize(false, false); w.frameGeometry = {x: $2, y: $3, width: $4, height: $5};
        workspace.activeWindow = w; } }"
}
maximize() {
    kw "for (const w of workspace.windowList()) { if (w.normalWindow && w.caption.indexOf('$1') >= 0) {
        w.setMaximize($2, $2); workspace.activeWindow = w; } }"
}
apply() {   # $1 = name, rest = options
    local name=$1; shift
    timeout 120 classic7-appearance "$@" > /out/apply-$name.log 2>&1
    echo "== $name ($*): exit $? $(tr -d '\n ' < $HOME/.config/classic7/appearance.json | grep -o '"look":"[a-z]*"\|"solid":[a-z]*' | tr '\n' ' ') $(grep '^theme=' $HOME/.config/kwinrc)" >> /out/result.txt
    sleep 4
}
two_windows() {   # Control Panel at the back, the dialog in front of it (its title over text)
    place "Control Panel" 40 30 760 480
    place "$DIALOG" 300 200 600 360
    sleep 2
}
titles() {   # $1 picture: the two title bars, enlarged
    zoom $1 "620x40+290+194" $1-front
    zoom $1 "480x40+34+24" $1-back
}
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
grep -E "theme|library" $HOME/.config/kwinrc > /out/kwinrc-new-account.txt
# a new account: Aero from /etc/skel, before anything is applied (see-through, not blurred here)
(DISPLAY= classic7-control >/dev/null 2>&1 &)
if command -v kcmshell6 >/dev/null && ls /usr/lib64/qt6/plugins/plasma/kcms/systemsettings/kcm_bluetooth.so >/dev/null 2>&1; then
    DIALOG=Bluetooth; (DISPLAY= kcmshell6 kcm_bluetooth > /out/bluetooth.log 2>&1 &)
else
    DIALOG=Notepad; (DISPLAY= classic7-notepad >/dev/null 2>&1 &)
fi
sleep 10
windows "new account"
two_windows
shot 01-new-account; titles 01-new-account
# the close button when the pointer is on it; the window menu from the icon
X mousemove 870 211; sleep 1.5; shot 02-hover-close; zoom 02-hover-close "220x40+700+194" 02-hover-close-zoom
X mousemove 316 215 click 1; sleep 2; shot 03-window-menu
X key Escape; sleep 1
# maximized, by the Maximize button; then Restore (now at the top right)
X mousemove 833 211 click 1; sleep 2; shot 04-maximized; zoom 04-maximized "1180x30+0+0" 04-maximized-top
windows "maximized by the button"
X mousemove 1117 10 click 1; sleep 2
windows "restored by the button"
two_windows
# the other window active
place "Control Panel" 40 30 760 480; sleep 1.5; shot 05-back-active; titles 05-back-active
# Aero applied: this KWin can't blur, so the glass is drawn solid
place "$DIALOG" 300 200 600 360
apply aero-solid --look aero; two_windows; shot 06-solid; titles 06-solid
# see-through as with a 3D driver (CLASSIC7_BLUR=1), though this KWin doesn't blur it
CLASSIC7_BLUR=1 apply aero-glass --look aero; two_windows; shot 07-glass; titles 07-glass
# Classic, then back to Aero without logging out: the titles bold, then plain again
apply classic --look classic; two_windows; shot 08-classic; titles 08-classic
grep -A3 "^\[WM\]" $HOME/.config/kdeglobals > /out/fonts-classic.txt
apply aero-again --look aero; two_windows; shot 09-aero-after-classic; titles 09-aero-after-classic
grep -A3 "^\[WM\]" $HOME/.config/kdeglobals > /out/fonts-aero.txt
apply basic --look basic; two_windows; shot 10-basic; titles 10-basic
apply ruby --look aero --glass ruby --intensity 70; two_windows; shot 11-ruby; titles 11-ruby
X mousemove 833 211 click 1; sleep 2; shot 12-ruby-maximized; zoom 12-ruby-maximized "1180x30+0+0" 12-ruby-maximized-top
X mousemove 1117 10 click 1; sleep 2
# Personalization > Window Color says why the glass is solid
(DISPLAY= classic7-appearance --page color > /out/window-color.log 2>&1 &)
sleep 7; shot 13-window-color
X key Escape; sleep 1
# Computer > Properties is the System window
ls -la $HOME/Desktop > /out/desktop.txt 2>&1
(DISPLAY= classic7-properties "$HOME/Desktop/Computer.desktop" > /out/properties.log 2>&1 &)
sleep 7; shot 14-computer-properties
windows "after Computer > Properties"
pgrep -af "classic7-system|system_app|classic7-properties" > /out/processes.txt 2>&1
cp $HOME/.cache/classic7/appearance.log /out/ 2>/dev/null
ls -la $HOME/.local/share/kwin/decorations $HOME/.local/share/aurorae/themes > /out/user-themes.txt 2>&1
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/versions.txt; cat /out/kwinrc-new-account.txt; cat /out/result.txt; cat /out/fonts-classic.txt /out/fonts-aero.txt
  cat /out/windows.txt; cat /out/processes.txt
  grep -iE "qml|aurorae|decoration|CaptionButton|classic7" /out/kwin.log | sort | uniq -c | sort -rn | head -12 | sed 's/^/kwin: /'
  grep -h "rc=[1-9]\|MISSING\|TIMEOUT" /out/appearance.log 2>/dev/null | head -8; } > /out/notices.txt 2>&1
