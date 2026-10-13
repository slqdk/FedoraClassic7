# Does classic7-grab get a screen picture from KWin in the nested session? (KWin's own debug output
# for the permission lookup, the helper's error, and the same call with permission checks off)
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
. /src/.github/ci/native_build.sh
cp -a /src/system_files/usr/share/applications/. /usr/share/applications/
useradd -m -u 1000 tester 2>/dev/null
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
run_kwin() {
    DISPLAY=:99 QT_LOGGING_RULES="KWIN_UTILS.debug=true;kwin_screenshot*.debug=true" "$@" \
        kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin-$1.log 2>&1 &
}
grab() {
    timeout 20 /usr/libexec/classic7-grab > /tmp/grab.bin 2> /tmp/grab.err
    echo "$1: exit $? header: $(head -c 60 /tmp/grab.bin | head -1) bytes: $(stat -c %s /tmp/grab.bin) err: $(cat /tmp/grab.err)"
}
run_kwin env
sleep 8
export WAYLAND_DISPLAY=wayland-c7
{
grab "normal"
ls -la /proc/self/exe /usr/libexec/classic7-grab
grep -l "classic7-grab" ~/.cache/ksycoca6* 2>/dev/null
timeout 30 spectacle -b -n -f -o /tmp/spectacle.png > /tmp/spec.log 2>&1; echo "spectacle exit $? $(stat -c %s /tmp/spectacle.png 2>&1) $(tail -3 /tmp/spec.log | tr '\n' ' ')"
} > /out/debug.txt 2>&1
pkill -x kwin_wayland; sleep 3
run_kwin env KWIN_SCREENSHOT_NO_PERMISSION_CHECKS=1
sleep 8
grab "no permission checks" >> /out/debug.txt 2>&1
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 300 dbus-run-session -- bash /tmp/inner.sh"
grep -h -i "interfaces found\|could not find\|screenshot" /out/kwin-env.log | head -20 >> /out/debug.txt
tail -40 /out/debug.txt > /out/notices.txt
