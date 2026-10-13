# The published image after a release: start-up screen in the initramfs, Accessories menu,
# screen saver and goodbye programs, session helper
mkdir -p /out
{
echo "== image"; cat /usr/share/classic7/build-info.json
echo "== plymouth"; grep -h "^Theme" /etc/plymouth/plymouthd.conf
for img in /usr/lib/modules/*/initramfs.img; do
    echo "$img $(stat -c '%s %a' "$img")"
    lsinitrd "$img" 2>/dev/null | grep -c "plymouth/themes/classic7/" | sed 's/^/classic7 theme files in initramfs: /'
    lsinitrd "$img" 2>/dev/null | grep -E "ostree-prepare-root$" | head -2
done
echo "== menus"; ls /etc/xdg/menus/applications-merged/ /usr/share/desktop-directories/ | grep -i classic7
echo "== programs"; /usr/bin/classic7-screensaver --list | tr '\n' ' '; echo
/usr/bin/classic7-goodbye --help; echo "exit $?"
ls -la /usr/libexec/classic7-idle /usr/libexec/classic7-grab /usr/lib64/qt6/plugins/kf6/propertiesdialog/classic7_properties.so 2>&1
systemctl --global is-enabled classic7-sessiond.service
grep -c "IdleWatch" /usr/lib/classic7/sessiond.py
} > /out/notices.txt 2>&1
