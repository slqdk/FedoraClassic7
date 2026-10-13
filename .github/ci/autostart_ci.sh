# What starts at login in the image: every /etc/xdg/autostart entry with its package, and the units
# systemd's XDG autostart generator makes from them for a Plasma session (what really runs).
set -x
exec 2>/out/script.log
mkdir -p /out && chmod 777 /out
{
    for f in /etc/xdg/autostart/*.desktop /etc/skel/.config/autostart/*.desktop; do
        [ -f "$f" ] || continue
        echo "=== $f ($(rpm -qf "$f" 2>/dev/null | head -1))"
        grep -vE '^(Name|Comment|GenericName|Keywords)\[' "$f"
    done
} > /out/autostart.txt 2>&1
G=/tmp/gen; mkdir -p $G
XDG_CURRENT_DESKTOP=KDE /usr/lib/systemd/user-generators/systemd-xdg-autostart-generator $G $G $G > /out/generator.log 2>&1
{
    for u in $G/*.service; do echo "=== $u"; grep -E "^(Description|ExecStart|ExecCondition|After|PartOf)=" "$u"; done
    ls -la $G/xdg-desktop-autostart.target.wants/ 2>/dev/null
} > /out/units.txt 2>&1
ls /usr/lib/systemd/user/*.service | grep -iE "kdeconnect|unifiedpush|announce|geoclue|vdagent|vmware|vbox|remapper|xwaylandvideo" > /out/user-units.txt 2>&1
for b in /usr/libexec/bazzite-announcement /usr/bin/bazzite-steam /usr/libexec/xapps/xapp-sn-watcher; do
    echo "=== $b"; file "$b"; head -c 1500 "$b" 2>/dev/null | grep -a -v "^\s*$" | head -40
done > /out/scripts.txt 2>&1
rpm -qa | grep -iE "geoclue|xapp|spice-vdagent|open-vm|virtualbox|kdeconnect|kunifiedpush|input-remapper|xwaylandvideo" | sort > /out/packages.txt
ls /usr/share/dbus-1/services/ | grep -iE "kdeconnect|unifiedpush" >> /out/packages.txt
{ cat /out/packages.txt; grep -c . /out/autostart.txt; ls $G | head -40; } > /out/notices.txt 2>&1
