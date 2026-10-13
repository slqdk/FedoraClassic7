# Remote Desktop: the image's KRdp server and FreeRDP clients in one container. Logs in with a KRdp
# user and with the system user (PAM), first with the packaged KRdp library, then with the one
# build_files/krdp/fix-krdp.sh builds; then Classic 7's Remote Desktop Connection (classic7-mstsc)
# connects to the server. Results in /out/result.txt.
# The nested KWin here draws without OpenGL (Xvfb), and KWin's screencast needs OpenGL: KRdp would
# drop every connection at once when its screencast fails. So krdpserver doesn't get the screencast
# interface here; it then logs on as usual and the sessions stay black.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
{ rpm -q krdp freerdp freerdp-libs libwinpr kpipewire krdc; rpm -ql freerdp | grep bin/; } > /out/versions.txt 2>&1
# the build dependencies at the image's own versions where Fedora still has them
vl=/etc/dnf/versionlock.toml
dnf5 versionlock add $(rpm -qa --qf '%{NAME}\n' | sort -u) > /dev/null 2>&1
archive=(); dnf5 repo list --all 2>/dev/null | grep '^updates-archive ' >/dev/null && archive=(--enablerepo=updates-archive)
dnf5 -y install --setopt=install_weak_deps=False "${archive[@]}" $(bash /src/build_files/krdp/fix-krdp.sh deps) > /out/dnf.log 2>&1 \
    || { rm -f $vl; dnf5 -y install --setopt=install_weak_deps=False $(bash /src/build_files/krdp/fix-krdp.sh deps) >> /out/dnf.log 2>&1; }
rm -f $vl
bash /src/build_files/krdp/fix-krdp.sh check >> /out/versions.txt 2>&1
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/share/applications/. /usr/share/applications/
cp -a $S/etc/skel/. /etc/skel/ 2>/dev/null
sed -i 's/^X-KDE-Wayland-Interfaces=.*/X-KDE-Wayland-Interfaces=org_kde_kwin_fake_input/' /usr/share/applications/org.kde.krdpserver.desktop
cat > /tmp/probe.py <<'EOP'
import socket, struct, sys
# what the server picks when a client offers TLS, NLA and NLA with early user auth (as Windows does)
cookie = b"Cookie: mstshash=tester\r\n"
body = bytes([0xE0, 0, 0, 0, 0, 0]) + cookie + struct.pack("<BBHI", 1, 0, 8, 0x0B)
pdu = struct.pack(">BBH", 3, 0, 5 + len(body)) + bytes([len(body)]) + body
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=5)
s.sendall(pdu)
data = s.recv(64)
names = {1: "TLS", 2: "NLA", 8: "NLA with early user auth (HYBRID_EX)"}
if len(data) >= 19 and data[5] == 0xD0 and data[11] == 2:
    sel = struct.unpack("<I", data[15:19])[0]
    print(f"server picks {names.get(sel, hex(sel))}")
else:
    print(f"no negotiation answer: {data.hex(' ')}")
EOP
useradd -m -u 1000 tester 2>/dev/null
echo 'tester:Classic7pass!' | chpasswd
cat > /tmp/inner.sh <<'EOI'
round=$1
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
mkdir -p $HOME/.local/share/krdpserver $HOME/.config/classic7
C=$HOME/.local/share/krdpserver
[ -f $C/krdp.crt ] || openssl req -nodes -new -x509 -keyout $C/krdp.key -out $C/krdp.crt -days 3650 -batch -subj /CN=classic7 > /dev/null 2>&1
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
(pipewire > /out/pipewire-$round.log 2>&1 &); sleep 1; (wireplumber > /dev/null 2>&1 &)
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin-$round.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
kbuildsycoca6 --noincremental > /dev/null 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME PATH > /dev/null 2>&1
export QT_FORCE_STDERR_LOGGING=1 QT_LOGGING_RULES="org.kde.krdp*=true"
CERT="--certificate $C/krdp.crt --certificate-key $C/krdp.key"
CLIENT=$(command -v xfreerdp || command -v xfreerdp3)
echo "round $round: client $CLIENT" >> /out/result.txt
# connect: name port user password extra-args...
try() {
    local name=$1 port=$2 user=$3 pass=$4; shift 4
    DISPLAY=:99 timeout 20 $CLIENT /v:127.0.0.1:$port "/u:$user" "/p:$pass" /cert:ignore /size:640x400 "$@" \
        > /out/client-$round-$name.log 2>&1
    local code=$?
    local verdict="ended (exit $code: $(grep -oE 'ERRCONNECT_[A-Z_]+|ERRINFO_[A-Z_]+' /out/client-$round-$name.log | sort -u | tr '\n' ' '))"
    [ $code = 124 ] && verdict="still connected after 20 s"
    echo "round $round $name: $verdict" >> /out/result.txt
}
# 1) a KRdp user (what Remote Desktop settings' user list gives)
krdpserver --plasma --port 3390 -u rdpuser -p 'Rdp pass1' $CERT > /out/krdp-$round-users.log 2>&1 &
K=$!
sleep 5
echo "round $round negotiation: $(python3 /tmp/probe.py 3390 2>&1)" >> /out/result.txt
sleep 1
try users-default 3390 rdpuser 'Rdp pass1'
sleep 1
try users-wrongpw 3390 rdpuser 'nope'
kill $K 2>/dev/null; sleep 1
# 2) the system user's own password (PAM)
printf '[General]\nSystemUserEnabled=true\nCertificate=%s\nCertificateKey=%s\n' $C/krdp.crt $C/krdp.key > $HOME/.config/krdpserverrc
krdpserver --plasma --port 3391 > /out/krdp-$round-pam.log 2>&1 &
K=$!
sleep 5
try pam-default 3391 tester 'Classic7pass!'
if [ $round = fixed ]; then
    # 3) Classic 7's Remote Desktop Connection: the dialog, then a session to this same desktop
    printf 'full address:s:127.0.0.1:3391\r\nscreen mode id:i:1\r\ndesktopwidth:i:800\r\ndesktopheight:i:500\r\nauthentication level:i:0\r\n' \
        | iconv -t UTF-16 > $HOME/.config/classic7/Default.rdp
    (CLASSIC7_MSTSC_LOG=/out/mstsc-session.log timeout 60 classic7-mstsc > /out/mstsc.log 2>&1 &)
    sleep 6
    DISPLAY=:99 import -window root /out/10-mstsc.png
    DISPLAY=:99 xdotool key alt+o; sleep 2
    DISPLAY=:99 import -window root /out/11-mstsc-options.png
    DISPLAY=:99 xdotool key alt+n; sleep 3
    DISPLAY=:99 import -window root /out/12-credentials.png
    DISPLAY=:99 xdotool type --delay 60 'tester'; DISPLAY=:99 xdotool key Tab
    DISPLAY=:99 xdotool type --delay 60 'Classic7pass!'; DISPLAY=:99 xdotool key Return
    sleep 14
    DISPLAY=:99 import -window root /out/13-session.png
    echo "mstsc: $(pgrep -af 'freerdp' | grep -v pgrep | head -1)" >> /out/result.txt
    pkill -f "sdl-freerdp|xfreerdp|wlfreerdp"; sleep 3
fi
kill $K 2>/dev/null; sleep 1
grep -hiE "authenticated|PAM|New client|failure|SAM|NLA|security|certificate|Listening" /out/krdp-$round-*.log | head -24 >> /out/result.txt
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 300 dbus-run-session -- bash /tmp/inner.sh packaged"
pkill -x krdpserver; pkill -x kwin_wayland; pkill -x Xvfb; pkill -x pipewire; pkill -x wireplumber; sleep 3
bash /src/build_files/krdp/fix-krdp.sh build > /out/fix.log 2>&1; echo "fix exit $?" >> /out/fix.log
su tester -c "timeout 400 dbus-run-session -- bash /tmp/inner.sh fixed"
{ cat /out/versions.txt; tail -n 3 /out/fix.log; cat /out/result.txt; tail -n 5 /out/mstsc-session.log /out/mstsc.log; } > /out/notices.txt 2>&1
