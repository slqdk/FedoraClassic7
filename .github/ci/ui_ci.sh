# Control Panel, Task Manager and the Ctrl+Alt+Del screen in the image, under a headless
# KWin (Wayland, virtual backend) so Task Manager's window list can be checked too.
set -x
exec 2>/out/script.log
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
for b in classic7-control classic7-taskmgr classic7-security classic7-diskmgmt classic7-run; do
    cp $S/usr/bin/$b /usr/bin/ && chmod +x /usr/bin/$b
done
cp $S/usr/share/applications/classic7-*.desktop /usr/share/applications/
getent passwd 1000 >/dev/null || useradd -m -u 1000 tester
mkdir -p /out && chmod 777 /out
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-tester; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6
cp -an /etc/skel/. $HOME/ 2>/dev/null
kwin_wayland --virtual --no-lockscreen --width 1200 --height 800 --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
ls -la $XDG_RUNTIME_DIR >> /out/kwin.log
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
plasma-apply-colorscheme Classic7 >/dev/null 2>&1
classic7-control --list > /out/control-list.txt 2>&1
CLASSIC7_LIB=/usr/lib/classic7 timeout 300 python3 /src/.github/ci/ui_test.py /out > /out/ui.log 2>&1
echo "exit $?" >> /out/ui.log
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
grep -E "^(OK|FAIL|FAILURES|exit|Traceback|[A-Za-z]+Error)" /out/ui.log > /out/notices.txt
echo "items: $(wc -l < /out/control-list.txt)" >> /out/notices.txt
tail -3 /out/kwin.log | sed 's/^/kwin: /' >> /out/notices.txt
