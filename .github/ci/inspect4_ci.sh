# Groundwork for tray pop-ups, accessories, Explorer, system tools, boot splash, screensaver.
exec 2>/out/script.log
{
echo "===== plasma-pa qml"; ls -R /usr/lib64/qt6/qml/org/kde/plasma/private/volume 2>&1 | head -20
cat /usr/lib64/qt6/qml/org/kde/plasma/private/volume/qmldir 2>/dev/null
echo "===== kded modules"; ls /usr/lib64/qt6/plugins/kf6/kded/ 2>&1
echo "===== tools"; for t in spectacle pactl wpctl pw-dump firewall-cmd firewall-offline-cmd firewall-config plymouth-set-default-theme plymouth dracut lsinitrd kwrite kate kolourpaint kcharselect knotes ktrash6 kioclient5 kioclient gio plasma-apply-wallpaperimage qdbus6 qdbus journalctl smartctl loginctl setsid kstart kstart6 xdg-open notify-send; do printf '%-28s %s\n' "$t" "$(command -v $t || echo -)"; done
echo "===== python"; for m in dbus gi systemd PIL psutil pulsectl numpy cairo; do python3 -c "import $m; print('$m', getattr($m,'__version__', getattr($m,'__file__','')))" 2>&1 | tail -1; done
echo "===== plymouth"; cat /etc/plymouth/plymouthd.conf 2>&1; plymouth-set-default-theme 2>&1; ls /usr/share/plymouth/themes 2>&1
echo "===== kargs"; ls /usr/lib/bootc/kargs.d 2>&1; cat /usr/lib/bootc/kargs.d/* 2>&1 | head -40
echo "===== initramfs"; ls -la /usr/lib/modules/*/initramfs.img 2>&1; KV=$(ls /usr/lib/modules | head -1); echo "kver $KV"
lsinitrd /usr/lib/modules/$KV/initramfs.img 2>/dev/null | grep -iE "plymouth|^Arguments|dracut modules" | head -30
lsinitrd -m /usr/lib/modules/$KV/initramfs.img 2>/dev/null | head -80
echo "===== dracut conf"; ls /usr/lib/dracut/dracut.conf.d /etc/dracut.conf.d 2>&1; cat /usr/lib/dracut/dracut.conf.d/*.conf /etc/dracut.conf.d/*.conf 2>/dev/null | grep -v "^#" | head -60
echo "===== firewalld"; systemctl is-enabled firewalld 2>&1; grep -E "^DefaultZone" /etc/firewalld/firewalld.conf 2>&1; firewall-offline-cmd --get-default-zone 2>&1; firewall-offline-cmd --get-zones 2>&1; ls /usr/lib/firewalld/zones 2>&1 | head -30; firewall-offline-cmd --zone=FedoraWorkstation --list-all 2>&1 | head -20; firewall-offline-cmd --zone=public --list-all 2>&1 | head -20
echo "===== polkit firewalld"; ls /usr/share/polkit-1/actions | grep -i -E "firewall|systemd1|login1|journal"
echo "===== devel pkgs"; dnf5 -q repoquery --available kf6-kidletime-devel plasma-workspace-devel kf6-kjobwidgets-devel 2>&1 | head
echo "===== dbus interfaces"; ls /usr/share/dbus-1/interfaces 2>&1 | grep -iE "shutdown|logout|jobview|kuiserver|screensaver|ksmserver|notification|LauncherEntry"
echo "===== plasmanotifyrc defaults"; find /usr/share /etc/xdg -name "plasmanotifyrc*" 2>/dev/null; ls /usr/share/config.kcfg 2>/dev/null | grep -i notif
cat /usr/share/config.kcfg/notificationmanager.kcfg 2>/dev/null | head -120
echo "===== text editor defaults"; grep -h "text/plain" /usr/share/applications/mimeapps.list /usr/share/applications/kde-mimeapps.list /etc/xdg/mimeapps.list /etc/xdg/kde-mimeapps.list 2>/dev/null
ls /usr/share/applications | grep -iE "kwrite|kate|gedit|text|calc|paint|charselect|notes|spectacle|snip"
echo "===== spectacle help"; spectacle --help 2>&1 | head -60
echo "===== screen locker"; cat /usr/share/kservices6/*screenlocker* 2>/dev/null | head; ls /usr/lib64/qt6/plugins/plasma/kcms/systemsettings | grep -iE "screenlock|powerdevil|firewall"
echo "===== kidletime"; ls /usr/lib64/qt6/plugins/kf6/org.kde.kidletime.platforms/ 2>&1; rpm -q kf6-kidletime
echo "===== trash"; ls /etc/skel/Desktop 2>&1; cat /etc/skel/Desktop/*.desktop 2>/dev/null | head -40
echo "===== dolphin"; rpm -q dolphin plasma-workspace kf6-kio libplasma plasma-pa 2>&1
echo "===== cursor/sounds"; ls /usr/share/sounds 2>&1 | head; ls /usr/share/sounds/ocean/stereo 2>/dev/null | head
echo "===== sddm theme"; ls /usr/share/sddm/themes 2>&1
} > /out/inspect4.txt 2>&1
echo "inspect4 written" > /out/notices.txt
