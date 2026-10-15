# Classic 7 Update's "settings for this account" step (classic7-update --settings) in a Plasma
# session: whether it finishes without problems (it must: otherwise Update offers "new settings"
# for ever), how long it takes, and what it writes to ~/.cache/classic7/settings-refresh.log.
# Run three times: as after an update from an older version (the network-tray migration still to
# do), then again, then with a problem that can't go away (to see it stop retrying).
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/out/dnf.log 2>&1 || true
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
for d in plasma kwin kwin-wayland applications classic7 desktop-directories aurorae color-schemes Kvantum themes wallpapers; do
    mkdir -p /usr/share/$d && cp -a $S/usr/share/$d/. /usr/share/$d/
done
cp -a $S/etc/xdg/. /etc/xdg/
cp -a $S/etc/skel/. /etc/skel/
rm -f /usr/share/dbus-1/services/org.bluez.obex.service
merge() {
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" =~ ^\[(.*)\]$ ]]; then group="${BASH_REMATCH[1]}"; continue; fi
        kwriteconfig6 --file "$2" --group "$group" --key "${line%%=*}" -- "${line#*=}"
    done < "$1"
}
merge /usr/share/classic7/xdg-defaults/kwinrc /etc/xdg/kwinrc
merge /usr/share/classic7/xdg-defaults/kdeglobals /etc/xdg/kdeglobals
python3 -m compileall -q -f --invalidation-mode checked-hash /usr/lib/classic7
useradd -m -u 1000 tester 2>/dev/null
mkdir -p /out && chmod 777 /out
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-t; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6 XDG_SESSION_TYPE=wayland
export XDG_MENU_PREFIX=plasma-
cp -an /etc/skel/. $HOME/
Xvfb :99 -screen 0 1280x860x24 >/dev/null 2>&1 &
sleep 2
cd /tmp
DISPLAY=:99 kwin_wayland --x11-display :99 --width 1260 --height 840 --no-lockscreen --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
unset DISPLAY
kbuildsycoca6 --noincremental > /out/sycoca.log 2>&1
dbus-update-activation-environment WAYLAND_DISPLAY QT_QPA_PLATFORM XDG_RUNTIME_DIR XDG_CURRENT_DESKTOP \
    KDE_FULL_SESSION KDE_SESSION_VERSION XDG_SESSION_TYPE HOME >> /out/sycoca.log 2>&1
# a login as on the installed system: the tray fix before Plasma, then Plasma, then the first-login step
/usr/libexec/classic7-tray-fix > /out/tray-fix-1.log 2>&1
plasmashell --no-respawn > /out/plasmashell.log 2>&1 &
sleep 25
/usr/libexec/classic7-first-login > /out/first-login.log 2>&1
sleep 5
cp $HOME/.config/plasma-org.kde.plasma.desktop-appletsrc /out/appletsrc-before.txt
# as on Søren's account: settings from an older version, the network-tray migration not done yet
python3 - <<'EOP'
import json, os
p = os.path.expanduser("~/.config/classic7/update.json")
try:
    d = json.load(open(p))
except Exception:
    d = {}
d["applied_content"] = "old"
d["applied_build"] = "2026-10-12T11:17Z"
d["done_migrations"] = [m for m in d.get("done_migrations", []) if m != "2026-10-12-network-tray-2"]
os.makedirs(os.path.dirname(p), exist_ok=True)
json.dump(d, open(p, "w"), indent=2)
EOP
for n in 1 2; do
    start=$(date +%s.%N)
    classic7-update --settings > /out/settings-$n.txt 2>&1
    rc=$?
    end=$(date +%s.%N)
    echo "run $n: exit $rc, $(python3 -c "print(round($end - $start, 1))") s, needs refresh: $(python3 -c "import sys; sys.path.insert(0, '/usr/lib/classic7'); import update_core as u; print(u.needs_refresh())")" >> /out/result.txt
    cp $HOME/.cache/classic7/settings-refresh.log /out/settings-refresh-$n.log 2>/dev/null
    cp $HOME/.config/classic7/update.json /out/update-$n.json
done
ls $HOME/.config/classic7/ >> /out/result.txt
# a problem that stays: the account's settings are still marked done after three tries
python3 - <<'EOP' >> /out/result.txt 2>&1
import sys
sys.path.insert(0, "/usr/lib/classic7")
import update_core as u
st = u.UpdateState.load(); st.applied_content = "old"; st.refresh_tries = 0; st.save()
u.MIGRATIONS.append(("ci-always-fails", lambda log: False))
for i in range(4):
    problems = u.refresh_account(lambda line: None)
    st = u.UpdateState.load()
    print(f"try {i + 1}: problems {problems}, tries {st.refresh_tries}, needs refresh {u.needs_refresh()}")
EOP
# the next login: the tray fix again (it was asked to), then the layout
/usr/libexec/classic7-tray-fix --force > /out/tray-fix-2.log 2>&1
cp $HOME/.config/plasma-org.kde.plasma.desktop-appletsrc /out/appletsrc-after.txt
DISPLAY=:99 import -window root /out/desktop.png
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh" > /out/inner.log 2>&1
{ cat /out/result.txt; tail -n 12 /out/settings-1.txt; echo ---; tail -n 6 /out/settings-2.txt
  grep -c "networkmanagement" /out/appletsrc-before.txt /out/appletsrc-after.txt; } > /out/notices.txt 2>&1
