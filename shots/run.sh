set -x
dnf5 -y -q install xorg-x11-server-Xvfb ImageMagick python3-pip >/dev/null 2>&1 || true
# /usr/local doesn't exist on a bootc image: install the test servers into /tmp
python3 -m pip install -q --target /tmp/pylib pymap aiosmtpd
export PYTHONPATH=/tmp/pylib
export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/xdg; mkdir -p $HOME $XDG_RUNTIME_DIR; chmod 700 $XDG_RUNTIME_DIR
Xvfb :99 -screen 0 1300x820x24 >/dev/null 2>&1 & sleep 2
export DISPLAY=:99 QT_QPA_PLATFORM=xcb QTWEBENGINE_DISABLE_SANDBOX=1 QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu"
export CLASSIC7_LIB=/src/system_files/usr/lib/classic7
(cd /tmp && python3 -c "import sys; from pymap.main import main; sys.argv[0]='pymap'; sys.exit(main())" --port 1143 --no-tls dict --demo-data > /out/pymap.log 2>&1 &) ; sleep 3
cd /out && timeout 400 dbus-run-session -- python3 /src/.github/ci/mail_test.py /out > /out/test.log 2>&1
echo "exit $?" >> /out/test.log
