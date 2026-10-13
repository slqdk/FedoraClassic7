# Taskbar context menu and Programs and Features groundwork: where the task manager applet's
# QML lives, Bazaar/flatpak/rpm-ostree on the image.
exec 2>/out/script.log
{
echo "===== taskmanager package"; ls -la /usr/share/plasma/plasmoids/ | grep -i -E "taskmanager|panel|systemtray"
find /usr/share/plasma/plasmoids/org.kde.plasma.taskmanager -maxdepth 3 2>/dev/null | head -40
echo "===== applet plugins"; ls /usr/lib64/qt6/plugins/plasma/applets/ 2>/dev/null | head -80
echo "===== strings in taskmanager plugin"; f=$(ls /usr/lib64/qt6/plugins/plasma/applets/org.kde.plasma.taskmanager.so 2>/dev/null); [ -n "$f" ] && strings "$f" | grep -E "\.qml$|contextualActions|qrc:" | head -40
echo "===== containmentactions"; ls /usr/lib64/qt6/plugins/plasma/containmentactions/ 2>/dev/null
echo "===== panel containment"; find /usr/share/plasma/plasmoids/org.kde.panel -maxdepth 3 2>/dev/null | head; ls /usr/lib64/qt6/plugins/plasma/applets | grep -i panel
echo "===== bazaar"; ls /usr/share/applications | grep -i -E "bazaar|discover|store|software"; find / -xdev -iname "*bazaar*" -not -path "/proc/*" 2>/dev/null | head -20
echo "===== flatpak"; which flatpak; flatpak --version; flatpak remotes 2>&1; flatpak list --app --columns=application,name,version,origin,installation,size 2>&1 | head -20
cat /usr/share/ublue-os/bazzite/flatpak/install 2>/dev/null | head -30; ls /usr/share/ublue-os 2>/dev/null; find /usr/share/ublue-os -maxdepth 3 -iname "*flatpak*" 2>/dev/null | head
echo "===== rpm-ostree"; which rpm-ostree; rpm-ostree --version 2>&1 | head -3
echo "===== brew"; ls /home/linuxbrew 2>/dev/null; which brew
echo "===== appimage"; which gearlever 2>/dev/null
echo "===== flatpak metadata sample"; ls /var/lib/flatpak/app 2>/dev/null | head; ls /usr/share/flatpak 2>/dev/null
echo "===== polkit flatpak"; ls /usr/share/polkit-1/actions | grep -i -E "flatpak|rpm-ostree"
} > /out/inspect3.txt 2>&1
echo "inspect3 written" > /out/notices.txt
