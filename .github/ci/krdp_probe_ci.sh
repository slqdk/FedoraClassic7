# Remote Desktop: what KRdp (as packaged) answers at the start of a connection. A small Python client
# sends the X.224 Connection Request and prints the raw answer, then tries TLS; xfreerdp and the server
# log with FreeRDP's debug output. Results in /out/probe.txt.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
rpm -q krdp freerdp-libs openssl > /out/versions.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
echo 'tester:Classic7pass!' | chpasswd
cat > /tmp/probe.py <<'EOP'
import socket, ssl, struct, sys

port = int(sys.argv[1])
def cr(protocols):
    cookie = b"Cookie: mstshash=tester\r\n"
    neg = struct.pack("<BBHI", 1, 0, 8, protocols)
    body = bytes([0xE0, 0, 0, 0, 0, 0]) + cookie + neg
    x224 = bytes([len(body)]) + body
    return struct.pack(">BBH", 3, 0, 4 + len(x224)) + x224

for protocols in (0x01, 0x03, 0x0B):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(cr(protocols))
    try:
        data = s.recv(200)
    except OSError as e:
        data = b""
        print(f"requested 0x{protocols:02x}: recv error {e}")
    print(f"requested 0x{protocols:02x}: {len(data)} bytes: {data.hex(' ')}")
    if len(data) >= 19 and data[5] == 0xD0 and data[11] == 2:
        sel = struct.unpack("<I", data[15:19])[0]
        print(f"  CC, RDP_NEG_RSP flags 0x{data[12]:02x} selected 0x{sel:x}")
        if sel & 0x3:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                t = ctx.wrap_socket(s, server_hostname="localhost")
                print(f"  TLS ok: {t.version()} {t.cipher()}")
                cert = t.getpeercert(binary_form=True)
                print(f"  certificate {len(cert)} bytes")
                t.close()
            except Exception as e:
                print(f"  TLS failed: {e!r}")
    s.close()
EOP
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
C=$HOME/.local/share/krdpserver; mkdir -p $C
openssl req -nodes -new -x509 -keyout $C/krdp.key -out $C/krdp.crt -days 3650 -batch -subj /CN=classic7 > /out/openssl.log 2>&1
openssl x509 -in $C/krdp.crt -noout -text | grep -E "Public Key Algorithm|Public-Key|Signature Algorithm|Not After" >> /out/probe.txt 2>&1
head -1 $C/krdp.key >> /out/probe.txt
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
(pipewire > /out/pipewire.log 2>&1 &); sleep 1; (wireplumber > /out/wireplumber.log 2>&1 &); sleep 1
DISPLAY=:99 QT_FORCE_STDERR_LOGGING=1 QT_LOGGING_RULES="kwin_*=true;kwin_screencast*=true" \
    kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland QT_FORCE_STDERR_LOGGING=1 QT_LOGGING_RULES="org.kde.krdp*=true"
WLOG_LEVEL=DEBUG krdpserver --plasma --port 3390 -u rdpuser -p 'Rdp pass1' --certificate $C/krdp.crt --certificate-key $C/krdp.key > /out/krdp.log 2>&1 &
sleep 5
python3 /tmp/probe.py 3390 >> /out/probe.txt 2>&1
sleep 1
DISPLAY=:99 timeout 20 xfreerdp /v:127.0.0.1:3390 /u:rdpuser '/p:Rdp pass1' /cert:ignore /size:640x400 /log-level:DEBUG > /out/client-default.log 2>&1
echo "xfreerdp default: exit $?" >> /out/probe.txt
DISPLAY=:99 timeout 20 xfreerdp /v:127.0.0.1:3390 /u:rdpuser '/p:Rdp pass1' /cert:ignore /size:640x400 /sec:tls /log-level:DEBUG > /out/client-tls.log 2>&1
echo "xfreerdp /sec:tls: exit $?" >> /out/probe.txt
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 200 dbus-run-session -- bash /tmp/inner.sh"
{ cat /out/versions.txt /out/probe.txt; grep -hE "Security:|security" /out/krdp.log | head -12; grep -iE "screencast|pipewire|opengl|qpainter|egl|compositing" /out/kwin.log | head -20; } > /out/notices.txt 2>&1
