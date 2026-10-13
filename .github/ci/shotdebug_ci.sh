# Why does KWin's ScreenShot2 not answer in the nested session?
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb >/dev/null 2>&1 || true
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out
cat /usr/lib/systemd/user/plasma-kwin_wayland.service /usr/lib/systemd/user/plasma-plasmashell.service > /out/units.txt 2>&1
ls /usr/lib64/qt6/plugins/kwin/plugins/ /usr/lib64/qt6/plugins/kwin/effects/plugins 2>&1 >> /out/units.txt
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
sleep 8
export WAYLAND_DISPLAY=wayland-c7
{
busctl --user list | grep -i -E "kwin|screenshot"
busctl --user introspect org.kde.KWin /org/kde/KWin/ScreenShot2 2>&1 | head -20
busctl --user introspect org.kde.KWin.ScreenShot2 /org/kde/KWin/ScreenShot2 2>&1 | head -20
python3 - <<'EOP'
import dbus, os, traceback
bus = dbus.SessionBus()
for name in ("org.kde.KWin.ScreenShot2", "org.kde.KWin"):
    try:
        obj = bus.get_object(name, "/org/kde/KWin/ScreenShot2")
        iface = dbus.Interface(obj, "org.kde.KWin.ScreenShot2")
        r, w = os.pipe()
        res = iface.CaptureWorkspace({"native-resolution": True}, dbus.types.UnixFd(w), timeout=10)
        os.close(w)
        data = b""
        while True:
            b = os.read(r, 1 << 20)
            if not b: break
            data += b
        print(name, "OK", dict(res), len(data))
    except Exception:
        print(name, "FAILED"); traceback.print_exc()
EOP
} > /out/debug.txt 2>&1
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
tail -30 /out/debug.txt > /out/notices.txt
