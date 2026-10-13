# Sheet (the Excel clone) in the image: typing, formulas, files (plus a batch of Apache POI's
# test spreadsheets), printing to PDF and screenshots, under a headless KWin.
set -x
exec 2>/out/script.log
S=/src/system_files
python3 -c "import openpyxl, xlrd" 2>/dev/null || dnf5 -y install python3-openpyxl python3-xlrd >/out/dnf.log 2>&1 \
    || pip install openpyxl xlrd >>/out/dnf.log 2>&1
cp -a $S/usr/lib/classic7/. /usr/lib/classic7/
cp $S/usr/bin/classic7-sheet /usr/bin/ && chmod +x /usr/bin/classic7-sheet
cp $S/usr/share/applications/classic7-sheet.desktop /usr/share/applications/
# sample workbooks from Apache POI's test data (xls, xlsx), shallow and sparse
if timeout 300 git clone -q --depth 1 --filter=blob:none --sparse https://github.com/apache/poi /tmp/poi; then
    (cd /tmp/poi && timeout 300 git sparse-checkout set test-data/spreadsheet)
fi
mkdir -p /tmp/samples && find /tmp/poi/test-data/spreadsheet -maxdepth 1 -name "*.xls*" -size -3M 2>/dev/null \
    | sort | awk 'NR % 4 == 0' | head -120 | xargs -r cp -t /tmp/samples
getent passwd 1000 >/dev/null || useradd -m -u 1000 tester
mkdir -p /out && chmod 777 /out
cat > /tmp/inner.sh <<'EOI'
export XDG_RUNTIME_DIR=/tmp/xdg-tester; mkdir -p $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
export HOME=/home/tester XDG_CURRENT_DESKTOP=KDE KDE_FULL_SESSION=true KDE_SESSION_VERSION=6
cp -an /etc/skel/. $HOME/ 2>/dev/null
kwin_wayland --virtual --no-lockscreen --width 1400 --height 900 --socket wayland-c7 > /out/kwin.log 2>&1 &
for i in $(seq 1 40); do [ -S $XDG_RUNTIME_DIR/wayland-c7 ] && break; sleep 0.5; done
export WAYLAND_DISPLAY=wayland-c7 QT_QPA_PLATFORM=wayland
plasma-apply-colorscheme Classic7 >/dev/null 2>&1
classic7-sheet --help > /out/help.txt 2>&1
# first offscreen (no compositor needed), then the same under KWin for real-looking screenshots
mkdir -p /out/offscreen
OUT=/out/offscreen SAMPLES=/tmp/samples C7LIB=/usr/lib/classic7 QT_QPA_PLATFORM=offscreen timeout 900 \
    python3 -X faulthandler /src/.github/ci/sheet_test.py > /out/sheet-offscreen.log 2>&1
echo "exit $?" >> /out/sheet-offscreen.log
ls -la $XDG_RUNTIME_DIR > /out/runtime.txt
OUT=/out C7LIB=/usr/lib/classic7 QT_DEBUG_PLUGINS=0 timeout 600 python3 -X faulthandler /src/.github/ci/sheet_test.py > /out/sheet.log 2>&1
echo "exit $?" >> /out/sheet.log
EOI
chown tester /tmp/inner.sh
su tester -c "dbus-run-session -- bash /tmp/inner.sh"
echo "samples: $(ls /tmp/samples | wc -l)" >> /out/notices.txt
for f in /out/sheet-offscreen.log /out/sheet.log; do
    echo "== $(basename $f): $(grep -c '^PASS' $f) passed" >> /out/notices.txt
    grep -E "^(FAIL|exit|Traceback|Fatal|[A-Za-z]+Error|  File)" $f | head -30 >> /out/notices.txt
done
tail -1 /out/dnf.log 2>/dev/null | sed 's/^/dnf: /' >> /out/notices.txt
