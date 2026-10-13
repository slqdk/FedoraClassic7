# Remote Desktop: the image's KRdp server and a FreeRDP client in one container. Logs in with a
# KRdp user and with the system user (PAM), first with the packaged KRdp library, then with the one
# build_files/krdp/fix-krdp.sh builds. Results in /out/result.txt.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/dev/null 2>&1 || true
mkdir -p /out && chmod 777 /out
{ rpm -q krdp freerdp-libs libwinpr kpipewire krdc remmina; rpm -qa 'krdp*' 'freerdp*' | sort
  rpm -ql $(rpm -qa 'krdp*') | grep -E "bin/|\.so|\.service|\.desktop"; } > /out/versions.txt 2>&1
dnf5 -y install --setopt=install_weak_deps=False freerdp $(bash /src/build_files/krdp/fix-krdp.sh deps) > /out/dnf.log 2>&1
{ echo "== after dnf"; rpm -q krdp freerdp freerdp-libs; rpm -ql freerdp | grep bin/; } >> /out/versions.txt 2>&1
bash /src/build_files/krdp/fix-krdp.sh check >> /out/versions.txt 2>&1
useradd -m -u 1000 tester 2>/dev/null
echo 'tester:Classic7pass!' | chpasswd
cp -a /src/system_files/etc/skel/. /etc/skel/ 2>/dev/null
cat > /tmp/inner.sh <<'EOI'
round=$1
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
cp -an /etc/skel/. $HOME/
Xvfb :99 -screen 0 1200x820x24 >/dev/null 2>&1 &
sleep 2
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1180 --height 800 --no-lockscreen --socket wayland-c7 > /out/kwin-$round.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
kbuildsycoca6 --noincremental > /dev/null 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME PATH > /dev/null 2>&1
export QT_LOGGING_RULES="org.kde.krdp*=true"
CLIENT=$(for c in xfreerdp3 xfreerdp sdl-freerdp3 sdl-freerdp; do command -v $c && break; done | head -1)
echo "round $round: client $CLIENT" >> /out/result.txt
# connect: name port user password extra-args...; a client still connected after 20 s logged in
try() {
    local name=$1 port=$2 user=$3 pass=$4; shift 4
    DISPLAY=:99 timeout 20 $CLIENT /v:127.0.0.1:$port "/u:$user" "/p:$pass" /cert:ignore /size:640x400 "$@" \
        > /out/client-$round-$name.log 2>&1
    local code=$?
    local verdict="FAILED (exit $code: $(grep -oE 'ERRCONNECT_[A-Z_]+|ERRINFO_[A-Z_]+|LOGON_[A-Z_]+' /out/client-$round-$name.log | sort -u | tr '\n' ' '))"
    [ $code = 124 ] && verdict="logged in"
    echo "round $round $name: $verdict" >> /out/result.txt
}
# 1) a KRdp user (what Remote Desktop settings' user list gives)
krdpserver --plasma --port 3390 -u rdpuser -p 'Rdp pass1' > /out/krdp-$round-users.log 2>&1 &
K=$!
sleep 5
try users-default 3390 rdpuser 'Rdp pass1'
sleep 1
try users-tls 3390 rdpuser 'Rdp pass1' /sec:tls
sleep 1
try users-wrongpw 3390 rdpuser 'nope' /sec:tls
kill $K; sleep 1
# 2) the system user's own password (PAM)
mkdir -p $HOME/.config
printf '[General]\nSystemUserEnabled=true\n' > $HOME/.config/krdpserverrc
krdpserver --plasma --port 3391 > /out/krdp-$round-pam.log 2>&1 &
K=$!
sleep 5
try pam-default 3391 tester 'Classic7pass!'
DISPLAY=:99 import -window root /out/screen-$round.png 2>/dev/null
kill $K; sleep 1
grep -hE "authenticated|PAM|New client|failure|SAM|NLA|security" /out/krdp-$round-*.log | head -20 >> /out/result.txt
EOI
chown tester /tmp/inner.sh
su tester -c "timeout 300 dbus-run-session -- bash /tmp/inner.sh packaged"
pkill -x krdpserver; pkill -x kwin_wayland; pkill -x Xvfb; sleep 3
# Classic 7's fix
bash /src/build_files/krdp/fix-krdp.sh build > /out/fix.log 2>&1; echo "fix exit $?" >> /out/fix.log
su tester -c "timeout 300 dbus-run-session -- bash /tmp/inner.sh fixed"
{ cat /out/versions.txt; tail -n 5 /out/fix.log; cat /out/result.txt; } > /out/notices.txt 2>&1
