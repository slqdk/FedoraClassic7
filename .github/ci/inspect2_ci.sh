# KWin details for the taskbar/window work: tabbox QML, D-Bus methods, shortcut names.
exec 2>/out/script.log
{
for f in /usr/share/kwin/tabbox/compact/metadata.json /usr/share/kwin/tabbox/compact/contents/ui/main.qml \
         /usr/share/kwin/tabbox/big_icons/contents/ui/main.qml /usr/share/kwin-wayland/tabbox/thumbnail_grid/metadata.json; do
    echo "===== $f"; cat "$f"
done
echo "===== find tabbox dirs"; find / -xdev -type d -name tabbox 2>/dev/null
echo "===== showdesktop qml"; find /usr/lib64/qt6/qml -ipath "*showdesktop*" 2>/dev/null; find /usr/lib64/qt6/plugins -iname "*showdesktop*" 2>/dev/null
echo "===== kwin scripts dirs"; ls /usr/share/kwin/scripts /usr/share/kwin-wayland/scripts 2>/dev/null
find /usr/share/kwin*/scripts -name metadata.json | head -3 | xargs -r cat
} > /out/inspect2.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester
kwin_wayland --virtual --no-lockscreen --width 1000 --height 700 --socket wayland-c7 > /out/kwin2.log 2>&1 &
sleep 8
{
echo "===== kglobalaccel"; qdbus org.kde.kglobalaccel /kglobalaccel
echo "===== component kwin"; qdbus org.kde.kglobalaccel /component/kwin
echo "===== shortcut names"; qdbus org.kde.kglobalaccel /component/kwin org.kde.kglobalaccel.Component.shortcutNames
echo "===== allShortcutInfos"; qdbus org.kde.kglobalaccel /component/kwin org.kde.kglobalaccel.Component.allShortcutInfos 2>&1 | head -50
echo "===== KWin"; qdbus org.kde.KWin /KWin
echo "===== Scripting"; qdbus org.kde.KWin /Scripting
echo "===== services"; qdbus | head -40
} > /out/dbus.txt 2>&1
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
echo "inspect2: $(wc -l < /out/inspect2.txt) lines, dbus: $(wc -l < /out/dbus.txt) lines" > /out/notices.txt
