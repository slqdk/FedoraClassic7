# Other programs' tray icons, as Steam's: a Qt program (StatusNotifierItem), a GTK program with an
# AppIndicator (libayatana-appindicator, like Steam's libappindicator) and an old XEmbed icon
# (Plasma shows those through xembedsniproxy and Xwayland). Are they in the notification area,
# and does a right-click give the program's own menu? Each icon is one plain colour, so it can be
# found in the picture and clicked.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool kvantum libayatana-appindicator-gtk3 >/out/dnf.log 2>&1 || true
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
for d in plasma kwin kwin-wayland applications classic7 desktop-directories aurorae color-schemes Kvantum themes wallpapers; do
    mkdir -p /usr/share/$d && cp -a $S/usr/share/$d/. /usr/share/$d/
done
cp -a $S/etc/xdg/. /etc/xdg/
cp -a $S/etc/skel/. /etc/skel/
{ rpm -q plasma-workspace libayatana-appindicator-gtk3 xorg-x11-server-Xwayland; command -v xembedsniproxy; } > /out/versions.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out /tmp/icons && chmod 777 /out /tmp/icons
for c in FF00FF:magenta 00FF00:green 00FFFF:cyan; do convert -size 22x22 "xc:#${c%%:*}" "/tmp/icons/c7${c##*:}.png"; done
chmod 644 /tmp/icons/*
cat > /tmp/qt_tray.py <<'EOP'
# a Qt program's tray icon (Qt uses StatusNotifierItem under Plasma) with a menu like Steam's
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
menu = QMenu()
for t in ("Store", "Library", "Community", "Friends", None, "Exit Qt test"):
    menu.addSeparator() if t is None else menu.addAction(t)
icon = QSystemTrayIcon(QIcon("/tmp/icons/c7magenta.png"))
icon.setToolTip("Qt test program")
icon.setContextMenu(menu)
icon.show()
print("Qt tray available:", QSystemTrayIcon.isSystemTrayAvailable(), flush=True)
app.exec()
EOP
cat > /tmp/indicator.py <<'EOP'
# a GTK program's AppIndicator, as Steam's
import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AI, Gtk
ind = AI.Indicator.new("c7-indicator-test", "c7green", AI.IndicatorCategory.APPLICATION_STATUS)
ind.set_icon_theme_path("/tmp/icons")
ind.set_title("AppIndicator test")
ind.set_status(AI.IndicatorStatus.ACTIVE)
menu = Gtk.Menu()
for t in ("Store", "Library", "Community", "Exit AppIndicator test"):
    menu.append(Gtk.MenuItem(label=t))
menu.show_all()
ind.set_menu(menu)
print("indicator up", flush=True)
Gtk.main()
EOP
cat > /tmp/xembed.py <<'EOP'
# an old XEmbed tray icon (Gtk.StatusIcon on X11)
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk
icon = Gtk.StatusIcon.new_from_file("/tmp/icons/c7cyan.png")
icon.set_tooltip_text("XEmbed test")
menu = Gtk.Menu()
for t in ("Store", "Library", "Exit XEmbed test"):
    menu.append(Gtk.MenuItem(label=t))
menu.show_all()
icon.connect("popup-menu", lambda i, button, time: menu.popup(None, None, None, None, button, time))
print("xembed icon up, embedded:", icon.is_embedded(), flush=True)
Gtk.main()
EOP
cat > /tmp/find.py <<'EOP'
# where is a colour in the picture? prints the middle "x y" of its pixels (or nothing)
import re, subprocess, sys
pic, colour = sys.argv[1], sys.argv[2].upper()
txt = subprocess.run(["convert", pic, "-crop", "1180x60+0+740", "+repage", "txt:-"],
                     capture_output=True, text=True).stdout
pts = [(int(m.group(1)), int(m.group(2))) for m in re.finditer(r"^(\d+),(\d+):.*#" + colour + r"\b", txt, re.M)]
if pts:
    xs, ys = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
    print(xs[len(xs) // 2], ys[len(ys) // 2] + 740, len(pts))
EOP
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
export XDG_MENU_PREFIX=plasma-
cp -an /etc/skel/. $HOME/
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
ls -la /tmp/.X11-unix > /out/x-before.txt 2>&1
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --xwayland --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
sleep 3
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
# Xwayland's display and its key, as KWin made them
XW=$(ls /tmp/.X11-unix | grep -v '^X99$' | sed -n 's/^X\([0-9]*\)$/:\1/p' | head -1)
XA=$(ls -t $XDG_RUNTIME_DIR/xauth_* 2>/dev/null | head -1)
{ ls -la /tmp/.X11-unix $XDG_RUNTIME_DIR; echo "Xwayland display: $XW auth: $XA"; } > /out/xwayland.txt 2>&1
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME >> /out/sycoca.log 2>&1
for p in /usr/libexec/kactivitymanagerd /usr/lib64/libexec/kactivitymanagerd; do [ -x $p ] && { $p > /out/kamd.log 2>&1 & break; }; done
/usr/libexec/classic7-first-login > /out/first-login.log 2>&1
sleep 2
QT_FORCE_STDERR_LOGGING=1 plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 25
# what Plasma's session starts for old tray icons
(DISPLAY=$XW XAUTHORITY=$XA xembedsniproxy > /out/xembedsniproxy.log 2>&1 &)
sleep 3
export DISPLAY=:99
X() { DISPLAY=:99 xdotool "$@"; }
shot() { DISPLAY=:99 import -window root "/out/$1.png"; }
traypic() { convert "/out/$1.png" -crop "420x40+760+760" +repage -filter point -resize 300% "/out/$1-tray.png"; }
WIN=$(X search --name "KWin" | head -1)
X windowactivate --sync $WIN 2>/dev/null; X windowmove $WIN 0 0 2>/dev/null
shot 01-before; traypic 01-before
(DISPLAY= python3 /tmp/qt_tray.py > /out/qt_tray.log 2>&1 &)
(DISPLAY= GDK_BACKEND=wayland python3 /tmp/indicator.py > /out/indicator.log 2>&1 &)
(DISPLAY=$XW XAUTHORITY=$XA GDK_BACKEND=x11 python3 /tmp/xembed.py > /out/xembed.log 2>&1 &)
sleep 10
shot 02-icons; traypic 02-icons
dbus-send --session --print-reply --dest=org.kde.StatusNotifierWatcher /StatusNotifierWatcher \
    org.freedesktop.DBus.Properties.Get string:org.kde.StatusNotifierWatcher string:RegisteredStatusNotifierItems \
    > /out/sni-items.txt 2>&1
grep -A6 "systemtray" $HOME/.config/plasma-org.kde.plasma.desktop-appletsrc | head -40 > /out/tray-config.txt 2>&1
n=3
for c in FF00FF:qt 00FF00:indicator 00FFFF:xembed; do
    pos=$(python3 /tmp/find.py /out/02-icons.png "${c%%:*}")
    echo "${c##*:}: ${pos:-not in the taskbar}" >> /out/result.txt
    if [ -n "$pos" ]; then
        set -- $pos
        X mousemove $1 $2 click 3; sleep 2.5
        shot "0$n-menu-${c##*:}"; n=$((n + 1))
        X key Escape; sleep 1
    fi
done
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/versions.txt; cat /out/xwayland.txt | tail -1; cat /out/result.txt; grep -o '"[^"]*"' /out/sni-items.txt | head -6
  cat /out/qt_tray.log /out/indicator.log /out/xembed.log 2>/dev/null | head -8; head -5 /out/xembedsniproxy.log; } > /out/notices.txt 2>&1
