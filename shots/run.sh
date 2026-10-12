set -x
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || dnf -y -q install xorg-x11-server-Xvfb ImageMagick xdotool
cp -a /src/system_files/usr/share/plasma/plasmoids/. /usr/share/plasma/plasmoids/
cp -a /src/system_files/usr/share/applications/. /usr/share/applications/
cp -a /src/system_files/usr/share/classic7/. /usr/share/classic7/
cp -a /src/system_files/usr/bin/classic7-run /src/system_files/usr/bin/classic7-taskbar-pin /usr/bin/
cat > /tmp/inner.sh <<'EOI'
export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/xdg-root DISPLAY=:99 QT_QPA_PLATFORM=xcb
mkdir -p $HOME $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
mkdir -p ~/Documents ~/Pictures ~/Music
Xvfb :99 -screen 0 1024x768x24 >/dev/null 2>&1 &
sleep 2
mkdir -p ~/.cache ~/.config ~/.local/share
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
plasma-apply-colorscheme Classic7 >> /out/sycoca.log 2>&1
plasma-apply-desktoptheme classic7 >> /out/sycoca.log 2>&1
kreadconfig6 --file kdeglobals --group KDE --key widgetStyle >> /out/sycoca.log 2>&1
ls /usr/share/applications | grep -E "classic7|dolphin|steam" >> /out/sycoca.log
export XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6
export QT_LOGGING_RULES="kf.service.*=true;org.kde.plasma.kicker*=true;qml=true;js=true"
plasmawindowed org.classic7.startmenu > /out/plasmawindowed.log 2>&1 &
sleep 15
import -window root /out/button.png
# open the menu with a click on the Start button
xdotool mousemove 60 40 click 1
sleep 5
import -window root /out/startmenu.png
# right-click a pinned program: Pin to Taskbar / Unpin from Start Menu
xdotool mousemove 100 221 click 3
sleep 2
import -window root /out/pinmenu.png
xdotool key Escape
sleep 1
# type a search (the search field has focus)
xdotool type --delay 80 "term"
sleep 5
import -window root /out/search.png
xdotool key ctrl+a BackSpace
sleep 1
# click "All Programs" if its position is given (APX/APY), then screenshot
xdotool mousemove 50 604 click 1
sleep 3
import -window root /out/programs.png
xdotool mousemove 60 200 click 1
sleep 3
import -window root /out/folder.png
pkill plasmawindowed
sleep 1
EOI
mkdir -p /out && chmod 777 /out
dbus-run-session -- bash /tmp/inner.sh
