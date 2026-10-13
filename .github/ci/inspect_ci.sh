# What the image has, for Control Panel / Task Manager / System / Device Manager work.
exec 2>/out/script.log
{
echo "== kcms"; find /usr/lib64/qt6/plugins/plasma/kcms -name '*.so' | sed 's|.*/plasma/kcms/||' | sort
echo "== kcm desktop files"; ls /usr/share/applications | grep -i kcm
echo "== kinfocenter"; ls /usr/lib64/qt6/plugins/plasma/kcms/kinfocenter 2>/dev/null
echo "== programs"; for p in kcmshell6 systemsettings kinfocenter plasma-systemmonitor ksysguard qdbus qdbus6 kwin_wayland kwin_x11 lspci lsusb udevadm dmidecode inxi hwinfo nvidia-smi sensors upower loginctl kscreen-doctor fwupdmgr smartctl ujust steam lact pkexec qdbus-qt6 xdg-open busctl systemd-analyze journalctl gamescope; do printf '%s: %s\n' $p "$(command -v $p || echo -)"; done
echo "== python"; python3 -c "import sys; print(sys.version)"; python3 -c "import psutil; print('psutil', psutil.__version__)" 2>&1; python3 -c "import dbus; print('dbus-python ok')" 2>&1; python3 -c "import gi; print('gi ok')" 2>&1; python3 -c "from PySide6 import QtDBus; print('QtDBus ok')" 2>&1; python3 -c "import openpyxl; print('openpyxl', openpyxl.__version__)" 2>&1; python3 -c "import xlrd; print('xlrd', xlrd.__version__)" 2>&1; python3 -c "import PySide6; print('PySide6', PySide6.__version__)"
echo "== pci.ids"; ls -la /usr/share/hwdata/ 2>&1 | head; ls /usr/share/misc/ 2>/dev/null | head
echo "== kwin effects/scripts"; ls /usr/share/kwin/effects /usr/share/kwin/scripts /usr/share/kwin/tabbox /usr/share/kwin-wayland/tabbox 2>/dev/null; find /usr/lib64/qt6/plugins/kwin -name '*.so' 2>/dev/null | sed 's|.*/kwin/||' | sort
echo "== kwinrc"; cat /etc/xdg/kwinrc
echo "== plasma version"; rpm -q plasma-workspace kwin plasma-desktop libplasma kf6-kio qt6-qtbase
echo "== applets"; ls /usr/share/plasma/plasmoids | head -80
echo "== sddm/lock"; ls /usr/share/plasma/look-and-feel/ ; ls /usr/share/plasma/look-and-feel/org.classic7.desktop/contents 2>/dev/null
echo "== ksmserver logout"; ls /usr/lib64/qt6/qml/org/kde/plasma/private/sessions 2>/dev/null; rpm -ql plasma-workspace | grep -i -E "logout|ksmserver-logout|lockscreen" | head -20
} > /out/inspect.txt 2>&1
head -c 0 /dev/null
echo "lines: $(wc -l < /out/inspect.txt)" > /out/notices.txt
