# The login screen: the Windows 7 Welcome screen theme (classic7aero) drawn by SDDM's greeter in
# test mode (one account; two accounts; the power menu; the Classic theme for comparison), the
# root helper that gives SDDM the theme and the desktop's screen settings, and the desktop side
# that calls it (classic7-appearance --login-screen, with a stand-in for pkexec).
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick xdotool >/out/dnf.log 2>&1 || true
mkdir -p /out && chmod 777 /out
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp -a $S/usr/bin/. /usr/bin/ && chmod +x /usr/bin/classic7-*
cp -a $S/usr/libexec/. /usr/libexec/ && chmod +x /usr/libexec/classic7-*
for d in sddm/themes classic7 wallpapers polkit-1; do mkdir -p /usr/share/$d && cp -a $S/usr/share/$d/. /usr/share/$d/; done
cp -a $S/etc/sddm.conf.d/. /etc/sddm.conf.d/
{ rpm -q sddm qt6-qtbase; getent passwd sddm; ls /usr/share/sddm/themes; } > /out/versions.txt 2>&1
# the helper, as root
{
    echo "== aero, screen settings"
    printf '[{"name": "outputs", "data": [{"connectorName": "Virtual-1", "mode": {"width": 1920, "height": 1080, "refreshRate": 60000}}]}]' \
        | /usr/libexec/classic7-login-screen aero; echo "exit $?"
    cat /etc/sddm.conf.d/classic7.look.conf
    ls -l "$(getent passwd sddm | cut -d: -f6)/.config/kwinoutputconfig.json"
    echo "== the same again"
    printf '[{"name": "outputs", "data": [{"connectorName": "Virtual-1", "mode": {"width": 1920, "height": 1080, "refreshRate": 60000}}]}]' \
        | /usr/libexec/classic7-login-screen aero; echo "exit $?"
    echo "== classic, no screen settings"
    /usr/libexec/classic7-login-screen classic < /dev/null; echo "exit $?"
    grep Current /etc/sddm.conf.d/classic7.look.conf
    echo "== not JSON"
    echo "nonsense" | /usr/libexec/classic7-login-screen keep; echo "exit $?"
    echo "== unknown look"
    /usr/libexec/classic7-login-screen fancy < /dev/null > /dev/null; echo "exit $?"
} > /out/helper.txt 2>&1
# accounts: one first (with a picture), a second one later
useradd -m -u 1000 -c "Søren Test" -G wheel tester 2>/dev/null
mkdir -p /var/lib/AccountsService/icons
convert -size 192x192 gradient:'#F7B733-#FC4A1A' -fill white -draw "circle 96,80 96,40" -draw "ellipse 96,190 70,60 0,360" \
    /var/lib/AccountsService/icons/tester
cat > /tmp/fakepkexec <<'EOF'
#!/bin/bash
# stands in for pkexec: records what the desktop asks for
{ echo "pkexec $*"; cat | head -c 200; echo; } >> /out/pkexec-calls.txt
echo "login screen: theme classic7aero, screen settings"
EOF
chmod +x /tmp/fakepkexec; mkdir -p /tmp/fakebin; cp /tmp/fakepkexec /tmp/fakebin/pkexec; chmod 777 /tmp/fakebin
cat > /tmp/inner.sh <<'EOI'
export HOME=/home/tester PATH=/tmp/fakebin:$PATH
mkdir -p $HOME/.config/classic7
printf '{"look": "aero"}\n' > $HOME/.config/classic7/appearance.json
printf '[{"name": "outputs"}]\n' > $HOME/.config/kwinoutputconfig.json
echo "== first: $(classic7-appearance --login-screen 2>&1; echo exit $?)"
echo "== nothing changed: $(classic7-appearance --login-screen 2>&1; echo exit $?)"
printf '[{"name": "outputs", "changed": true}]\n' > $HOME/.config/kwinoutputconfig.json
echo "== screen settings changed: $(classic7-appearance --login-screen 2>&1; echo exit $?)"
EOI
chmod 755 /tmp/inner.sh
su tester -c "bash /tmp/inner.sh" > /out/desktop-side.txt 2>&1
# the greeter in test mode on an X server
Xvfb :99 -screen 0 1280x800x24 >/dev/null 2>&1 &
sleep 2
export DISPLAY=:99 QT_QPA_PLATFORM=xcb
shot() { import -window root "/out/$1.png"; }
greeter() {   # $1 theme, $2 name of the log
    sddm-greeter-qt6 --test-mode --theme /usr/share/sddm/themes/$1 > /out/greeter-$2.log 2>&1 &
    G=$!
    sleep 8
}
greeter classic7aero one
shot 01-aero-one-account
xdotool type --delay 40 'secret'; sleep 0.5; shot 02-aero-password-typed
xdotool key Return; sleep 3; shot 03-aero-after-enter
# the power menu: the arrow beside the red button at the bottom right
xdotool mousemove 1239 754 click 1; sleep 1.5; shot 04-aero-power-menu
kill $G; sleep 1
useradd -m -u 1001 -c "Guest Player" player 2>/dev/null
greeter classic7aero two
shot 05-aero-two-accounts
xdotool mousemove 0 0; sleep 0.3
# click the second picture, then back with Switch User
xdotool key Right; sleep 0.5; xdotool key Return; sleep 1.5; shot 06-aero-chosen
kill $G; sleep 1
greeter classic7 classic
shot 07-classic
kill $G
{ cat /out/versions.txt; cat /out/helper.txt; cat /out/desktop-side.txt; cat /out/pkexec-calls.txt
  grep -hiE "qml|error|warning|ReferenceError|TypeError" /out/greeter-*.log | sort | uniq -c | sort -rn | head -15 | sed 's/^/greeter: /'; } > /out/notices.txt 2>&1
