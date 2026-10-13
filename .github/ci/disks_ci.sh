# Disk Management in the image (run by test-any.yml with host_dev): a 600 MB loop disk gets
# initialized, partitioned, formatted, lettered and deleted through the real helper.
set -x
exec 2>/out/script.log
dnf5 -y -q install xorg-x11-server-Xvfb >/dev/null 2>&1 || true
S=/src/system_files
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp $S/usr/bin/classic7-diskmgmt /usr/bin/ && chmod +x /usr/bin/classic7-diskmgmt
cp $S/usr/libexec/classic7-disk-helper /usr/libexec/ && chmod +x /usr/libexec/classic7-disk-helper
getent passwd 1000 >/dev/null || useradd -m -u 1000 tester
for p in sfdisk partx wipefs blkid mkfs.ntfs mkfs.exfat mkfs.vfat mkfs.ext4 mkfs.btrfs ntfsfix fsck.exfat e2fsck mount.ntfs-3g; do
    printf '%s: %s\n' "$p" "$(command -v $p || echo MISSING)"
done > /out/tools.txt
grep -E "ntfs|exfat|vfat|btrfs|ext4" /proc/filesystems >> /out/tools.txt
modprobe ntfs3 exfat 2>>/out/tools.txt; grep -E "ntfs3|exfat" /proc/filesystems >> /out/tools.txt

truncate -s 600M /tmp/disk.img
L=$(losetup -fP --show /tmp/disk.img)
echo "loop: $L" >> /out/tools.txt

export XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export DISPLAY=:99 QT_QPA_PLATFORM=xcb XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6
export HOME=/tmp/home; mkdir -p $HOME; cp -a /etc/skel/. $HOME/
Xvfb :99 -screen 0 1100x760x24 >/dev/null 2>&1 & sleep 2
cat > /tmp/inner.sh <<EOI
kwin_x11 --replace >/out/kwin.log 2>&1 & sleep 3
plasma-apply-colorscheme Classic7 >/dev/null 2>&1
export CLASSIC7_DISK_HELPER=/usr/libexec/classic7-disk-helper PKEXEC_UID=1000 CLASSIC7_ALLOW_LOOP=1
export CLASSIC7_DISK_SHOW_LOOP=1 CLASSIC7_DISK_NO_INIT_PROMPT=1 CLASSIC7_LIB=/usr/lib/classic7
timeout 600 python3 /src/.github/ci/disks_test.py /out $L > /out/disks.log 2>&1
echo "exit \$?" >> /out/disks.log
EOI
dbus-run-session -- bash /tmp/inner.sh
cp /etc/fstab /out/fstab.txt
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS $L >> /out/tools.txt 2>&1
umount /var/mnt/* 2>/dev/null
losetup -d $L
grep -E "^(OK|FAIL|FAILURES|BOX|exit|Traceback|[A-Za-z]+Error)" /out/disks.log > /out/notices.txt
grep -E "MISSING|ntfs3|exfat" /out/tools.txt | sed 's/^/tools: /' >> /out/notices.txt
