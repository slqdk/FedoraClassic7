# What the Start menu's All Programs folders come from: the XDG menu files and directory entries
mkdir -p /out
{
echo "== menus"; ls -la /etc/xdg/menus/ /etc/xdg/menus/applications-merged/ 2>&1
for f in /etc/xdg/menus/*.menu; do echo "===== $f"; cat "$f"; done
echo "== desktop-directories"; ls /usr/share/desktop-directories/ 2>&1 | head -80
echo "== XDG_MENU_PREFIX in plasma"; grep -rn "XDG_MENU_PREFIX" /usr/bin/startplasma* /usr/lib/systemd/user/plasma* /usr/share/wayland-sessions/ /etc/xdg/plasma-workspace/env/ 2>/dev/null | head
strings /usr/bin/startplasma-wayland 2>/dev/null | grep -i "menu_prefix\|plasma-" | head
echo "== Utility apps"; grep -l "^Categories=.*Utility" /usr/share/applications/*.desktop | head -40
} > /out/notices.txt 2>&1
cp /out/notices.txt /out/menus.txt
