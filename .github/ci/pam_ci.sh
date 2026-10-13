# Can a program running as the user check that user's password through PAM's "login" service, as
# KRdp's system-user login does? pam_unix needs the unix_chkpwd helper for that (setuid or file
# capabilities, which a container image can lose).
set -x
exec 2>/out/script.log
mkdir -p /out && chmod 777 /out
useradd -m -u 1000 tester 2>/dev/null
# the image has no /etc/shadow (accounts are made at install time): make it, or PAM finds no password
[ -f /etc/shadow ] || pwconv
echo 'tester:Classic7pass!' | chpasswd
{ ls -l /etc/shadow; getent shadow tester | cut -d: -f1,3; } > /out/shadow.txt 2>&1
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
rc = libpam.pam_start(b"login", sys.argv[1].encode(), ctypes.byref(c), ctypes.byref(h))
rc = libpam.pam_authenticate(h, 0)
print("pam_authenticate:", rc, libpam.pam_strerror(h, rc).decode())
rc2 = libpam.pam_acct_mgmt(h, 0)
print("pam_acct_mgmt:", rc2, libpam.pam_strerror(h, rc2).decode())
EOP
{
    echo "as root, right password:"; python3 /tmp/pamtest.py tester 'Classic7pass!'
    echo "as tester, right password:"; su tester -c "python3 /tmp/pamtest.py tester 'Classic7pass!'"
    echo "as tester, wrong password:"; su tester -c "python3 /tmp/pamtest.py tester 'nope'"
} > /out/result.txt 2>&1
journalctl -n 20 --no-pager >> /out/result.txt 2>&1
{ cat /out/result.txt | head -12; head -4 /out/pam.txt; } > /out/notices.txt
