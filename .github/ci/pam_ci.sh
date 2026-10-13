# Can a program running as the user check that user's password through PAM's "login" service, as
# KRdp's system-user login does? pam_unix needs the unix_chkpwd helper for that (setuid or file
# capabilities, which a container image can lose).
set -x
exec 2>/out/script.log
mkdir -p /out && chmod 777 /out
# PAM modules log to syslog: catch what they say (there is no journal in the container)
python3 - <<'EOP' &
import socket, os
try: os.unlink("/dev/log")
except OSError: pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM); s.bind("/dev/log"); os.chmod("/dev/log", 0o666)
with open("/out/syslog.txt", "a", buffering=1) as f:
    while True: f.write(s.recv(4096).decode(errors="replace") + "\n")
EOP
sleep 1
useradd -m -u 1000 tester
# the image has no /etc/shadow (accounts are made at install time): make it, or PAM finds no password
[ -f /etc/shadow ] || pwconv
echo 'tester:Classic7pass!' | chpasswd
{ ls -l /etc/shadow /etc/passwd; getent passwd tester; getent shadow tester | cut -c1-24; grep -c . /etc/shadow
  ls -ld /sys/fs/selinux 2>&1; python3 -c "import ctypes; print('selinux enabled:', ctypes.CDLL('libselinux.so.1').is_selinux_enabled())"
  grep -E '^(passwd|shadow)' /etc/nsswitch.conf; grep -E '^ENCRYPT|^YESCRYPT' /etc/login.defs
  rpm -q pam libxcrypt shadow-utils; } > /out/shadow.txt 2>&1
# the same check with pam_unix's debug output
printf 'auth required pam_unix.so debug\naccount required pam_unix.so debug\n' > /etc/pam.d/c7debug
{
    ls -l /usr/sbin/unix_chkpwd /usr/bin/su /usr/bin/passwd /usr/bin/sudo 2>&1
    getcap /usr/sbin/unix_chkpwd /usr/bin/passwd 2>&1
    getfattr -d -m - /usr/sbin/unix_chkpwd 2>&1
    rpm -V pam 2>&1 | head
    cat /etc/pam.d/login; echo ---; cat /etc/pam.d/system-auth; echo ---
    authselect current 2>&1 | head -5
    ls -la /run/nologin /etc/nologin 2>&1
} > /out/pam.txt 2>&1
cat > /tmp/pamtest.py <<'EOP'
import ctypes, ctypes.util, sys
libpam = ctypes.CDLL(ctypes.util.find_library("pam"))
libc = ctypes.CDLL(ctypes.util.find_library("c"))
class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]
class PamResponse(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_char_p), ("resp_retcode", ctypes.c_int)]
CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(PamMessage)),
                        ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)
class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV), ("appdata_ptr", ctypes.c_void_p)]
libc.calloc.restype = ctypes.c_void_p
libc.strdup.restype = ctypes.c_void_p
password = sys.argv[2].encode()
def conv(n, msgs, resp, _data):
    arr = libc.calloc(n, ctypes.sizeof(PamResponse))
    r = ctypes.cast(arr, ctypes.POINTER(PamResponse))
    for i in range(n):
        if msgs[i].contents.msg_style == 1:      # PAM_PROMPT_ECHO_OFF
            r[i].resp = ctypes.cast(libc.strdup(password), ctypes.c_char_p)
    resp[0] = r
    return 0
c = PamConv(CONV(conv), None)
h = ctypes.c_void_p()
libpam.pam_strerror.restype = ctypes.c_char_p
service = sys.argv[3].encode() if len(sys.argv) > 3 else b"login"
rc = libpam.pam_start(service, sys.argv[1].encode(), ctypes.byref(c), ctypes.byref(h))
rc = libpam.pam_authenticate(h, 0)
print("pam_authenticate:", rc, libpam.pam_strerror(h, rc).decode())
rc2 = libpam.pam_acct_mgmt(h, 0)
print("pam_acct_mgmt:", rc2, libpam.pam_strerror(h, rc2).decode())
EOP
{
    echo "as root, right password:"; python3 /tmp/pamtest.py tester 'Classic7pass!'
    echo "as tester, right password:"; su tester -c "python3 /tmp/pamtest.py tester 'Classic7pass!'"
    echo "as tester, wrong password:"; su tester -c "python3 /tmp/pamtest.py tester 'nope'"
    echo "as root, debug service:"; python3 /tmp/pamtest.py tester 'Classic7pass!' c7debug
    echo "as tester, debug service:"; su tester -c "python3 /tmp/pamtest.py tester 'Classic7pass!' c7debug"
    echo "unix_chkpwd directly:"; printf 'Classic7pass!\0' | su tester -c "/usr/sbin/unix_chkpwd tester nullok; echo exit \$?"
} > /out/result.txt 2>&1
sleep 1
{ grep -v '^+' /out/result.txt; echo "--- syslog"; tail -n 25 /out/syslog.txt; echo "--- shadow"; cat /out/shadow.txt; } > /out/notices.txt
