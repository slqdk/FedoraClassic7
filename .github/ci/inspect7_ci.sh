# Bazzite's terminal banner (user motd), and the user services behind some startup items.
set -x
exec 2>/out/script.log
mkdir -p /out && chmod 777 /out
{
    echo "### profile.d"; ls -la /etc/profile.d/ /usr/etc/profile.d/ 2>/dev/null
    for f in $(grep -rl -iE "motd|fastfetch|neofetch" /etc/profile.d/ /etc/bashrc /etc/bash.bashrc /etc/fish/conf.d/ /usr/share/fish/vendor_conf.d/ /etc/zshrc /usr/etc/profile.d 2>/dev/null); do
        echo "=== $f ($(rpm -qf "$f" 2>/dev/null))"; cat "$f"
    done
    echo "### motd programs"
    ls -la /usr/libexec/ublue-motd* /usr/bin/ublue-motd* /usr/share/ublue-os/motd /etc/user-motd /usr/share/ublue-os/user-motd 2>&1
    for f in /usr/libexec/ublue-motd /usr/bin/ublue-motd; do [ -f "$f" ] && { echo "=== $f"; head -80 "$f"; }; done
    ls -la /usr/share/ublue-os/motd/ 2>/dev/null; ls /usr/share/ublue-os/motd/* 2>/dev/null | head
    echo "### ujust toggle-user-motd"
    grep -rn -B2 -A14 "toggle-user-motd" /usr/share/ublue-os/just/ 2>/dev/null | head -60
    echo "### image-info"; cat /usr/share/ublue-os/image-info.json 2>/dev/null
} > /out/motd.txt 2>&1
{
    for u in kunifiedpush-distributor spice-vdagent; do
        echo "=== $u"; cat /usr/lib/systemd/user/$u.service; systemctl --global is-enabled $u.service
    done
    ls -la /usr/lib/systemd/user/*.wants/ 2>/dev/null | grep -iE "unifiedpush|vdagent|kdeconnect"
    ls /usr/share/dbus-1/system-services/ | grep -i remapper
    ls /usr/share/dbus-1/services/ | grep -iE "unifiedpush|kdeconnect"
    systemctl is-enabled input-remapper.service
    cat /usr/lib/systemd/system/input-remapper.service 2>/dev/null | head -20
} > /out/units.txt 2>&1
{ head -c 2500 /out/motd.txt; echo; cat /out/units.txt | grep -E "enabled|disabled|static|=== |remapper" | head -20; } > /out/notices.txt
