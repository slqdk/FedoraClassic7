"""Remote Desktop Connection, as in Windows 7 (mstsc): use another computer (Windows, or anything
with Remote Desktop / RDP switched on) in a window or full screen.

    classic7-mstsc [FILE.rdp] [/v:computer[:port]] [/f] [/w:width /h:height] [/edit FILE.rdp]

The connection itself is FreeRDP's client (sdl-freerdp, else xfreerdp). It gets every setting and
the password on its standard input (/args-from:stdin), never on its command line where other
programs could read them. Settings are kept the way Windows keeps them, in .rdp files that Windows
opens too: the last connection in ~/.config/classic7/Default.rdp, the computers used before in
~/.config/classic7/mstsc.json. "Remember my credentials" keeps the password in the keyring
(KWallet). Ctrl+Alt+Enter switches between full screen and a window."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QRadioButton, QSizePolicy, QSlider, QTabWidget,
                               QVBoxLayout, QWidget)

APP = "Remote Desktop Connection"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "classic7"
DEFAULT_RDP = CONFIG / "Default.rdp"
HISTORY = CONFIG / "mstsc.json"
KEYRING = "classic7-mstsc"
ICONS = ("preferences-desktop-remote-desktop", "krdc", "network-workgroup", "computer")
HELP_URL = "https://github.com/slqdk/FedoraClassic7#remote-desktop"

# Windows' .rdp settings this window knows, with mstsc's defaults (type s = text, i = number)
DEFAULTS: dict[str, tuple[str, object]] = {
    "full address": ("s", ""),
    "username": ("s", ""),
    "screen mode id": ("i", 2),            # 1 window, 2 full screen
    "desktopwidth": ("i", 1280),
    "desktopheight": ("i", 800),
    "session bpp": ("i", 32),
    "use multimon": ("i", 0),
    "displayconnectionbar": ("i", 1),
    "audiomode": ("i", 0),                 # 0 play on this computer, 1 on the remote computer, 2 not at all
    "audiocapturemode": ("i", 0),          # 1 record from this computer
    "keyboardhook": ("i", 2),              # Windows keys: 0 this computer, 1 remote, 2 only in full screen
    "redirectprinters": ("i", 1),
    "redirectclipboard": ("i", 1),
    "drivestoredirect": ("s", ""),         # "*" all, else names: Home, Media, DynamicDrives
    "connection type": ("i", 7),           # 7 detect automatically, 6 LAN ... 1 modem
    "networkautodetect": ("i", 1),
    "disable wallpaper": ("i", 0),
    "allow font smoothing": ("i", 1),
    "allow desktop composition": ("i", 1),
    "disable full window drag": ("i", 0),
    "disable menu anims": ("i", 0),
    "disable themes": ("i", 0),
    "bitmapcachepersistenable": ("i", 1),
    "autoreconnection enabled": ("i", 1),
    "authentication level": ("i", 2),      # 0 connect and don't warn, 1 do not connect, 2 warn me
    "prompt for credentials": ("i", 0),
    "gatewayhostname": ("s", ""),
    "gatewayusagemethod": ("i", 4),
}
SIZES = [(640, 480), (800, 600), (1024, 768), (1152, 864), (1280, 720), (1280, 800), (1280, 1024), (1366, 768),
         (1440, 900), (1600, 900), (1680, 1050), (1920, 1080), (1920, 1200), (2560, 1440)]
SPEEDS = [(7, "Detect connection quality automatically"), (1, "Modem (56 Kbps)"),
          (2, "Low-speed broadband (256 Kbps - 2 Mbps)"), (3, "Satellite (2 Mbps - 16 Mbps with high latency)"),
          (4, "High-speed broadband (2 Mbps - 10 Mbps)"), (5, "WAN (10 Mbps or higher with high latency)"),
          (6, "LAN (10 Mbps or higher)")]
NETWORK = {7: "auto", 6: "lan", 5: "wan", 4: "broadband-high", 3: "wan", 2: "broadband-low", 1: "modem"}
COLORS = [(32, "Highest Quality (32 bit)"), (24, "True Color (24 bit)"), (16, "High Color (16 bit)"),
          (15, "High Color (15 bit)")]


# ---- .rdp files -------------------------------------------------------------------------------
class RdpFile:
    """The settings of one connection, read from and written to Windows' .rdp format; settings this
    window doesn't know are kept as they were."""

    def __init__(self, path: Path | None = None):
        self.values: dict[str, tuple[str, object]] = dict(DEFAULTS)
        self.path = path
        if path is not None and path.exists():
            self.load(path)

    def load(self, path: Path):
        raw = path.read_bytes()
        if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
            text = raw.decode("utf-16")
        else:
            text = raw.decode("utf-8-sig", errors="replace")
        for line in text.splitlines():
            parts = line.strip().split(":", 2)
            if len(parts) != 3 or parts[1] not in ("s", "i", "b"):
                continue
            key, kind, value = parts[0].strip().lower(), parts[1], parts[2]
            if kind == "i":
                try:
                    self.values[key] = ("i", int(value))
                except ValueError:
                    continue
            else:
                self.values[key] = (kind, value)
        self.path = path

    def save(self, path: Path | None = None):
        path = path or self.path
        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{k}:{t}:{v}" for k, (t, v) in self.values.items()]
        # as mstsc writes them: UTF-16 with a byte order mark, Windows line ends
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-16"))
        self.path = path

    def get(self, key: str):
        return self.values.get(key, DEFAULTS.get(key, ("s", "")))[1]

    def set(self, key: str, value):
        kind = DEFAULTS.get(key, ("i" if isinstance(value, int) else "s", ""))[0]
        self.values[key] = (kind, int(value) if kind == "i" else str(value))

    def int(self, key: str) -> int:
        try:
            return int(self.get(key))
        except (TypeError, ValueError):
            return int(DEFAULTS.get(key, ("i", 0))[1])


def split_user(text: str) -> tuple[str, str]:
    """"DOMAIN\\user" -> (user, DOMAIN); "user" and "user@domain" stay as they are."""
    if "\\" in text:
        domain, user = text.split("\\", 1)
        return user, ("" if domain in (".", "") else domain)
    return text, ""


def client_program() -> str | None:
    for name in ("sdl-freerdp3", "sdl-freerdp", "xfreerdp3", "xfreerdp"):
        path = shutil.which(name)
        if path:
            return path
    return None


def freerdp_args(rdp: RdpFile, user: str, password: str | None, program: str) -> list[str]:
    """FreeRDP's command line for these settings, one argument per item (sent on stdin)."""
    host = str(rdp.get("full address")).strip()
    sdl = "sdl-freerdp" in os.path.basename(program)
    a = [f"/v:{host}"]
    name, domain = split_user(user)
    if name:
        a.append(f"/u:{name}")
    if domain:
        a.append(f"/d:{domain}")
    if password is not None:
        a.append(f"/p:{password}")
    if rdp.int("screen mode id") == 2:
        a.append("/f")
        if rdp.int("use multimon"):
            a.append("/multimon")
    else:
        a.append(f"/size:{rdp.int('desktopwidth')}x{rdp.int('desktopheight')}")
        a.append("/dynamic-resolution")
    a.append(f"/bpp:{rdp.int('session bpp')}")
    audio = rdp.int("audiomode")
    a.append("/sound" if audio == 0 else f"/audio-mode:{1 if audio == 1 else 2}")
    if rdp.int("audiocapturemode") == 1:
        a.append("/microphone")
    a.append("+clipboard" if rdp.int("redirectclipboard") else "-clipboard")
    if rdp.int("redirectprinters") and shutil.which("lpstat"):
        a.append("/printer")
    drives = str(rdp.get("drivestoredirect") or "")
    if drives.strip() == "*":
        a.append("+drives")
    else:
        for item in filter(None, (d.strip() for d in drives.split(";"))):
            if item.lower() == "home":
                a.append(f"/drive:Home,{Path.home()}")
            elif item.lower() == "media":
                media = Path("/run/media") / os.environ.get("USER", "")
                a.append(f"/drive:Removable,{media if media.exists() else '/run/media'}")
            elif item.lower() == "dynamicdrives":
                a.append("/drive:hotplug,*")
    hook = rdp.int("keyboardhook")
    if hook == 0:
        a.append("-grab-keyboard")
    elif hook == 1:
        a.append("+grab-keyboard")
    a.append(f"/network:{NETWORK.get(rdp.int('connection type'), 'auto')}")
    if rdp.int("connection type") != 7:
        a.append("-wallpaper" if rdp.int("disable wallpaper") else "+wallpaper")
        a.append("+fonts" if rdp.int("allow font smoothing") else "-fonts")
        a.append("+aero" if rdp.int("allow desktop composition") else "-aero")
        a.append("-window-drag" if rdp.int("disable full window drag") else "+window-drag")
        a.append("-menu-anims" if rdp.int("disable menu anims") else "+menu-anims")
        a.append("-themes" if rdp.int("disable themes") else "+themes")
    if rdp.int("bitmapcachepersistenable"):
        a.append("/cache:persist")
    if rdp.int("autoreconnection enabled"):
        a.append("+auto-reconnect")
    level = rdp.int("authentication level")
    if level == 0:
        a.append("/cert:ignore")
    elif level == 1:
        a.append("/cert:deny")
    elif not sdl:
        a.append("/cert:tofu")      # only the SDL client can ask in a window
    gateway = str(rdp.get("gatewayhostname") or "").strip()
    if gateway:
        a.append(f"/gateway:g:{gateway}")
    a.append(f"/title:{host} - {APP}")
    if not sdl and rdp.int("displayconnectionbar"):
        a.append("/floatbar:sticky:off,default:visible,show:fullscreen")
    a.append("/log-level:WARN")
    return a


# ---- what went wrong -----------------------------------------------------------------------------
CANT_CONNECT = ("Remote Desktop can't connect to the remote computer for one of these reasons:\n\n"
                "1) Remote access to the server is not enabled\n"
                "2) The remote computer is turned off\n"
                "3) The remote computer is not available on the network\n\n"
                "Make sure the remote computer is turned on and connected to the network, and that remote access "
                "is enabled.")
ERRORS = [
    (("DNS_NAME_NOT_FOUND", "DNS_ERROR"), "find",
     'Remote Desktop can\'t find the computer "{host}". This might mean that "{host}" does not belong to the '
     "specified network. Verify the computer name and domain that you are trying to connect to."),
    (("AUTHENTICATION_FAILED", "LOGON_FAILURE", "WRONG_PASSWORD", "STATUS_LOGON_FAILURE", "ERRCONNECT_AUTH",
      "NO_OR_MISSING_CREDENTIALS"), "logon", "The logon attempt failed"),
    (("ACCOUNT_LOCKED_OUT",), "fatal",
     "As a security precaution, the user account has been locked because there were too many logon attempts "
     "or password change attempts. Wait a while before trying again, or contact your system administrator."),
    (("PASSWORD_EXPIRED", "PASSWORD_MUST_CHANGE", "PASSWORD_CERTAINLY_EXPIRED"), "fatal",
     "You must change your password before logging on. Log on to the remote computer directly, change the "
     "password, and then connect again."),
    (("ACCOUNT_DISABLED",), "fatal", "Your account has been disabled. Please see your system administrator."),
    (("ACCOUNT_EXPIRED",), "fatal", "Your account has expired. Please see your system administrator."),
    (("INSUFFICIENT_PRIVILEGES", "LOGON_TYPE_NOT_GRANTED", "SERVER_INSUFFICIENT_PRIVILEGES"), "fatal",
     "The connection was denied because the user account is not authorized for remote login."),
    (("CONNECT_CANCELLED",), "quiet", ""),
    (("DISCONNECTED_BY_OTHERCONNECTION", "DISCONNECTED_BY_OTHER_CONNECTION"), "fatal",
     "Your Remote Desktop Services session has ended. Another user connected to the remote computer, so your "
     "connection was lost. Try connecting again, or contact your network administrator or technical support "
     "group."),
    (("SECURITY_NEGO_CONNECT_FAILED", "TLS_CONNECT_FAILED", "NEGO"), "fatal",
     "An authentication error has occurred. The remote computer's security settings don't match this "
     "computer's, or its certificate couldn't be checked."),
    (("CONNECT_FAILED", "CONNECT_TRANSPORT_FAILED", "CONNECTION_REFUSED", "TRANSPORT"), "fatal", CANT_CONNECT),
]
NORMAL_EXITS = {0, 1, 2, 11, 12}       # success, disconnect, logoff, disconnected or logged off by the user


def explain(output: str, code: int, host: str) -> tuple[str, str]:
    """(kind, message) for FreeRDP's output and exit code: kind is ok, logon, quiet or fatal."""
    for marks, kind, message in ERRORS:
        if any(m in output for m in marks):
            return kind, message.format(host=host)
    if code in NORMAL_EXITS:
        return "ok", ""
    if code in (131, 141, 147):
        return "fatal", CANT_CONNECT
    if code in (132, 134):
        return "logon", "The logon attempt failed"
    if code in (139, 140):
        return "find", ERRORS[0][2].format(host=host)
    return "fatal", ("The remote session was disconnected because of an error"
                     f" (FreeRDP exit code {code}).")


# ---- saved credentials ------------------------------------------------------------------------------
def _keyring():
    try:
        import keyring
        return keyring
    except Exception:  # noqa: BLE001 - no keyring: credentials are asked every time
        return None


def saved_credentials(host: str) -> dict | None:
    kr = _keyring()
    if not kr or not host:
        return None
    try:
        data = kr.get_password(KEYRING, f"TERMSRV/{host.lower()}")
        return json.loads(data) if data else None
    except Exception:  # noqa: BLE001
        return None


def save_credentials(host: str, user: str, password: str) -> bool:
    kr = _keyring()
    if not kr:
        return False
    try:
        kr.set_password(KEYRING, f"TERMSRV/{host.lower()}", json.dumps({"user": user, "password": password}))
        return True
    except Exception:  # noqa: BLE001
        return False


def delete_credentials(host: str):
    kr = _keyring()
    if kr:
        try:
            kr.delete_password(KEYRING, f"TERMSRV/{host.lower()}")
        except Exception:  # noqa: BLE001
            pass


def load_history() -> list[str]:
    try:
        return [h for h in json.loads(HISTORY.read_text()).get("computers", []) if isinstance(h, str)][:10]
    except (OSError, ValueError, AttributeError):
        return []


def remember_computer(host: str):
    hosts = [host] + [h for h in load_history() if h.lower() != host.lower()]
    try:
        CONFIG.mkdir(parents=True, exist_ok=True)
        HISTORY.write_text(json.dumps({"computers": hosts[:10]}, indent=1))
    except OSError:
        pass


def app_icon() -> QIcon:
    for name in ICONS:
        ic = QIcon.fromTheme(name)
        if not ic.isNull():
            return ic
    return QIcon()


# ---- the window --------------------------------------------------------------------------------------
class Banner(QWidget):
    """mstsc's blue band: "Remote Desktop / Connection" and a computer."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(68)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0, QColor("#1b4f8f"))
        g.setColorAt(0.55, QColor("#2f74c0"))
        g.setColorAt(1, QColor("#7fb6ea"))
        p.fillRect(self.rect(), g)
        wave = QPainterPath()
        wave.moveTo(w * 0.35, h)
        wave.cubicTo(w * 0.55, h * 0.35, w * 0.8, h * 0.9, w, h * 0.2)
        wave.lineTo(w, h)
        wave.closeSubpath()
        p.fillPath(wave, QColor(255, 255, 255, 38))
        p.setPen(QPen(QColor(255, 255, 255, 90), 1.2))
        p.drawLine(0, h - 1, w, h - 1)
        app_icon().paint(p, 14, 10, 48, 48)
        p.setPen(QColor("white"))
        f = QFont(self.font())
        f.setPixelSize(13)
        p.setFont(f)
        p.drawText(QRectF(72, 10, w - 80, 20), Qt.AlignLeft | Qt.AlignVCenter, "Remote Desktop")
        f.setPixelSize(24)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(72, 28, w - 80, 32), Qt.AlignLeft | Qt.AlignVCenter, "Connection")


class CredentialsDialog(QDialog):
    """Windows Security: "Enter your credentials"."""

    def __init__(self, parent, host: str, user: str, error: str = "", remember: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Windows Security")
        self.setWindowIcon(QIcon.fromTheme("dialog-password"))
        v = QVBoxLayout(self)
        head = QLabel("Enter your credentials")
        f = head.font()
        f.setPointSizeF(f.pointSizeF() * 1.45)
        head.setFont(f)
        head.setStyleSheet("color: #1e395b;")
        v.addWidget(head)
        v.addWidget(QLabel(f"These credentials will be used to connect to {host}."))
        tile = QFrame()
        tile.setFrameShape(QFrame.StyledPanel)
        tl = QHBoxLayout(tile)
        pic = QLabel()
        pic.setPixmap(QIcon.fromTheme("user-identity", QIcon.fromTheme("system-users")).pixmap(48, 48))
        tl.addWidget(pic, 0, Qt.AlignTop)
        fields = QVBoxLayout()
        self.user = QLineEdit(user)
        self.user.setPlaceholderText("User name")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.Password)
        fields.addWidget(self.user)
        fields.addWidget(self.password)
        hint = QLabel("For a domain account: DOMAIN\\user name")
        hint.setStyleSheet("color: #555;")
        fields.addWidget(hint)
        tl.addLayout(fields, 1)
        v.addWidget(tile)
        self.remember = QCheckBox("Remember my credentials")
        self.remember.setChecked(remember)
        if _keyring() is None:
            self.remember.setChecked(False)
            self.remember.setEnabled(False)
        v.addWidget(self.remember)
        if error:
            e = QLabel(error)
            e.setStyleSheet("color: #c00000;")
            v.addWidget(e)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        (self.password if user else self.user).setFocus()
        self.setMinimumWidth(420)


class AudioDialog(QDialog):
    def __init__(self, parent, rdp: RdpFile):
        super().__init__(parent)
        self.setWindowTitle("Remote Desktop Connection")
        v = QVBoxLayout(self)
        box = QGroupBox("Remote audio playback")
        bl = QVBoxLayout(box)
        self.play = QButtonGroup(self)
        for i, text in ((0, "Play on this computer"), (2, "Do not play"), (1, "Play on remote computer")):
            r = QRadioButton(text)
            self.play.addButton(r, i)
            bl.addWidget(r)
        (self.play.button(rdp.int("audiomode")) or self.play.button(0)).setChecked(True)
        v.addWidget(box)
        box2 = QGroupBox("Remote audio recording")
        bl2 = QVBoxLayout(box2)
        self.record = QButtonGroup(self)
        for i, text in ((1, "Record from this computer"), (0, "Do not record")):
            r = QRadioButton(text)
            self.record.addButton(r, i)
            bl2.addWidget(r)
        (self.record.button(rdp.int("audiocapturemode")) or self.record.button(0)).setChecked(True)
        v.addWidget(box2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class DrivesDialog(QDialog):
    def __init__(self, parent, rdp: RdpFile):
        super().__init__(parent)
        self.setWindowTitle("Remote Desktop Connection")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Local devices and resources\n\nChoose the devices and resources on this computer that "
                           "you want to use in your remote session."))
        current = str(rdp.get("drivestoredirect") or "")
        names = {d.strip().lower() for d in current.split(";")}
        self.all = QCheckBox("Drives (every drive this computer has)")
        self.all.setChecked(current.strip() == "*")
        self.home = QCheckBox(f"Home folder ({Path.home()})")
        self.home.setChecked("home" in names)
        self.media = QCheckBox("Removable drives (USB sticks and the like)")
        self.media.setChecked("media" in names)
        self.later = QCheckBox("Drives that I plug in later")
        self.later.setChecked("dynamicdrives" in names)
        for c in (self.all, self.home, self.media, self.later):
            v.addWidget(c)
        self.all.toggled.connect(lambda on: [c.setEnabled(not on) for c in (self.home, self.media, self.later)])
        self.all.toggled.emit(self.all.isChecked())
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def value(self) -> str:
        if self.all.isChecked():
            return "*"
        return ";".join(n for c, n in ((self.home, "Home"), (self.media, "Media"), (self.later, "DynamicDrives"))
                        if c.isChecked())


class RemoteDesktop(QDialog):
    def __init__(self, rdp: RdpFile, edit_only: bool = False):
        super().__init__()
        self.rdp = rdp
        self.edit_only = edit_only
        self.proc: QProcess | None = None
        self.output = ""
        self.session_user = ""
        self.session_password: str | None = None
        self.remember_after_login = False
        self.setWindowTitle(APP)
        self.setWindowIcon(app_icon())
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)
        outer.addWidget(Banner())
        body = QVBoxLayout()
        body.setContentsMargins(12, 10, 12, 0)
        outer.addLayout(body, 1)

        # the short form
        self.short = QWidget()
        sg = QGridLayout(self.short)
        sg.setContentsMargins(0, 0, 0, 0)
        sg.addWidget(QLabel("Computer:"), 0, 0)
        self.computer = QComboBox()
        self.computer.setEditable(True)
        self.computer.addItems(load_history())
        self.computer.setCurrentText(str(rdp.get("full address")))
        self.computer.lineEdit().setPlaceholderText("Example: computer.fabrikam.com")
        sg.addWidget(self.computer, 0, 1)
        sg.addWidget(QLabel("User name:"), 1, 0)
        self.user_label = QLabel()
        sg.addWidget(self.user_label, 1, 1)
        self.cred_note = QLabel()
        self.cred_note.setWordWrap(True)
        self.cred_note.setOpenExternalLinks(False)
        self.cred_note.linkActivated.connect(self._cred_link)
        sg.addWidget(self.cred_note, 2, 0, 1, 2)
        sg.setColumnStretch(1, 1)
        body.addWidget(self.short)

        # Options: the tabs
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._display_tab(), "Display")
        self.tabs.addTab(self._local_tab(), "Local Resources")
        self.tabs.addTab(self._experience_tab(), "Experience")
        self.tabs.addTab(self._advanced_tab(), "Advanced")
        self.tabs.setUsesScrollButtons(False)       # the dialog is as wide as the tabs, as in Windows
        self.tabs.hide()
        body.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(12, 10, 12, 0)
        self.options_btn = QPushButton()
        self.options_btn.setFlat(True)
        self.options_btn.clicked.connect(self._toggle_options)
        buttons.addWidget(self.options_btn)
        buttons.addStretch(1)
        self.connect_btn = QPushButton("Save" if edit_only else "Co&nnect")
        self.connect_btn.setDefault(True)
        self.connect_btn.clicked.connect(self._save_and_close if edit_only else self.connect_now)
        buttons.addWidget(self.connect_btn)
        help_btn = QPushButton("&Help")
        help_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
        buttons.addWidget(help_btn)
        outer.addLayout(buttons)

        self.computer.currentTextChanged.connect(self._computer_changed)
        self.general_computer.currentTextChanged.connect(self._computer_changed)
        self.user_edit.textChanged.connect(lambda _t: self._update_cred_note())
        self._set_options(edit_only)
        self._update_cred_note()
        self.setMinimumWidth(440)

    # ---- tabs ----
    def _general_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        box = QGroupBox("Logon settings")
        g = QGridLayout(box)
        pic = QLabel()
        pic.setPixmap(app_icon().pixmap(40, 40))
        g.addWidget(pic, 0, 0, 3, 1, Qt.AlignTop)
        g.addWidget(QLabel("Enter the name of the remote computer."), 0, 1, 1, 2)
        g.addWidget(QLabel("Computer:"), 1, 1)
        self.general_computer = QComboBox()
        self.general_computer.setEditable(True)
        self.general_computer.addItems(load_history())
        self.general_computer.setCurrentText(str(self.rdp.get("full address")))
        g.addWidget(self.general_computer, 1, 2)
        g.addWidget(QLabel("User name:"), 2, 1)
        self.user_edit = QLineEdit(str(self.rdp.get("username")))
        g.addWidget(self.user_edit, 2, 2)
        self.general_note = QLabel()
        self.general_note.setWordWrap(True)
        self.general_note.linkActivated.connect(self._cred_link)
        g.addWidget(self.general_note, 3, 1, 1, 2)
        self.allow_save = QCheckBox("Allow me to save credentials")
        self.allow_save.setChecked(self.rdp.int("prompt for credentials") == 0)
        g.addWidget(self.allow_save, 4, 1, 1, 2)
        g.setColumnStretch(2, 1)
        v.addWidget(box)
        box2 = QGroupBox("Connection settings")
        b2 = QGridLayout(box2)
        pic2 = QLabel()
        pic2.setPixmap(QIcon.fromTheme("document-save").pixmap(32, 32))
        b2.addWidget(pic2, 0, 0, 2, 1, Qt.AlignTop)
        t = QLabel("Save the current connection settings to an RDP file or open a saved connection.")
        t.setWordWrap(True)
        b2.addWidget(t, 0, 1, 1, 3)
        for col, (text, slot) in enumerate((("Save", self._save), ("Save As...", self._save_as),
                                            ("Open...", self._open)), start=1):
            b = QPushButton(text)
            b.clicked.connect(slot)
            b2.addWidget(b, 1, col)
        v.addWidget(box2)
        v.addStretch(1)
        return w

    def _display_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        box = QGroupBox("Display configuration")
        bl = QVBoxLayout(box)
        t = QLabel("Choose the size of your remote desktop. Drag the slider all the way to the right to use the "
                   "full screen.")
        t.setWordWrap(True)
        bl.addWidget(t)
        row = QHBoxLayout()
        row.addWidget(QLabel("Small"))
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(0, len(SIZES))
        self.size_slider.setTickPosition(QSlider.TicksBelow)
        self.size_slider.setPageStep(1)
        row.addWidget(self.size_slider, 1)
        row.addWidget(QLabel("Large"))
        bl.addLayout(row)
        self.size_label = QLabel()
        self.size_label.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.size_label)
        self.multimon = QCheckBox("Use all my monitors for the remote session")
        self.multimon.setChecked(bool(self.rdp.int("use multimon")))
        bl.addWidget(self.multimon)
        if self.rdp.int("screen mode id") == 2:
            self.size_slider.setValue(len(SIZES))
        else:
            want = (self.rdp.int("desktopwidth"), self.rdp.int("desktopheight"))
            self.size_slider.setValue(min(range(len(SIZES)), key=lambda i: abs(SIZES[i][0] - want[0])
                                          + abs(SIZES[i][1] - want[1])))
        self.size_slider.valueChanged.connect(self._size_changed)
        self._size_changed(self.size_slider.value())
        v.addWidget(box)
        box2 = QGroupBox("Colors")
        b2 = QVBoxLayout(box2)
        b2.addWidget(QLabel("Choose the color depth of the remote session."))
        self.colors = QComboBox()
        for bpp, text in COLORS:
            self.colors.addItem(text, bpp)
        self.colors.setCurrentIndex(max(0, self.colors.findData(self.rdp.int("session bpp"))))
        b2.addWidget(self.colors)
        v.addWidget(box2)
        self.conn_bar = QCheckBox("Display the connection bar when I use the full screen")
        self.conn_bar.setChecked(bool(self.rdp.int("displayconnectionbar")))
        v.addWidget(self.conn_bar)
        tip = QLabel("Ctrl+Alt+Enter switches between full screen and a window.")
        tip.setStyleSheet("color: #555;")
        v.addWidget(tip)
        v.addStretch(1)
        return w

    def _size_changed(self, value: int):
        if value >= len(SIZES):
            self.size_label.setText("<b>Full Screen</b>")
            self.multimon.setEnabled(True)
        else:
            self.size_label.setText(f"{SIZES[value][0]} by {SIZES[value][1]} pixels")
            self.multimon.setEnabled(False)

    def _local_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        box = QGroupBox("Remote audio")
        bl = QHBoxLayout(box)
        bl.addWidget(QLabel("Configure remote audio settings."), 1)
        b = QPushButton("Settings...")
        b.clicked.connect(self._audio)
        bl.addWidget(b)
        v.addWidget(box)
        box2 = QGroupBox("Keyboard")
        b2 = QVBoxLayout(box2)
        b2.addWidget(QLabel("Apply Windows key combinations:\nExample: Alt+Tab"))
        self.keys = QComboBox()
        for i, text in ((0, "On this computer"), (1, "On the remote computer"), (2, "Only when using the full screen")):
            self.keys.addItem(text, i)
        self.keys.setCurrentIndex(max(0, self.keys.findData(self.rdp.int("keyboardhook"))))
        b2.addWidget(self.keys)
        v.addWidget(box2)
        box3 = QGroupBox("Local devices and resources")
        b3 = QVBoxLayout(box3)
        b3.addWidget(QLabel("Choose the devices and resources that you want to use in\nyour remote session."))
        row = QHBoxLayout()
        self.printers = QCheckBox("Printers")
        self.printers.setChecked(bool(self.rdp.int("redirectprinters")))
        self.clipboard = QCheckBox("Clipboard")
        self.clipboard.setChecked(bool(self.rdp.int("redirectclipboard")))
        row.addWidget(self.printers)
        row.addWidget(self.clipboard)
        row.addStretch(1)
        more = QPushButton("More...")
        more.clicked.connect(self._drives)
        row.addWidget(more)
        b3.addLayout(row)
        v.addWidget(box3)
        v.addStretch(1)
        return w

    def _experience_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Choose your connection speed to optimize performance."))
        self.speed = QComboBox()
        for value, text in SPEEDS:
            self.speed.addItem(text, value)
        self.speed.setCurrentIndex(max(0, self.speed.findData(self.rdp.int("connection type"))))
        v.addWidget(self.speed)
        v.addWidget(QLabel("Allow the following:"))
        self.exp = {}
        for key, text, inverted in (("disable wallpaper", "Desktop background", True),
                                    ("allow font smoothing", "Font smoothing", False),
                                    ("allow desktop composition", "Desktop composition", False),
                                    ("disable full window drag", "Show window contents while dragging", True),
                                    ("disable menu anims", "Menu and window animation", True),
                                    ("disable themes", "Visual styles", True),
                                    ("bitmapcachepersistenable", "Persistent bitmap caching", False)):
            c = QCheckBox(text)
            c.setChecked(bool(self.rdp.int(key)) != inverted)
            self.exp[key] = (c, inverted)
            v.addWidget(c)
        self.reconnect = QCheckBox("Reconnect if the connection is dropped")
        self.reconnect.setChecked(bool(self.rdp.int("autoreconnection enabled")))
        v.addSpacing(8)
        v.addWidget(self.reconnect)
        self.speed.currentIndexChanged.connect(self._speed_changed)
        self._speed_changed()
        v.addStretch(1)
        return w

    def _speed_changed(self, *_):
        auto = self.speed.currentData() == 7
        for c, _inv in self.exp.values():
            c.setEnabled(not auto)

    def _advanced_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        box = QGroupBox("Server authentication")
        bl = QVBoxLayout(box)
        t = QLabel("Server authentication verifies that you are connecting to the intended remote computer. The "
                   "strength of the verification required to connect is set by your system security policy.")
        t.setWordWrap(True)
        bl.addWidget(t)
        bl.addWidget(QLabel("If server authentication fails:"))
        self.auth = QComboBox()
        for i, text in ((0, "Connect and don't warn me"), (2, "Warn me"), (1, "Do not connect")):
            self.auth.addItem(text, i)
        self.auth.setCurrentIndex(max(0, self.auth.findData(self.rdp.int("authentication level"))))
        bl.addWidget(self.auth)
        v.addWidget(box)
        box2 = QGroupBox("Connect from anywhere")
        b2 = QGridLayout(box2)
        t2 = QLabel("Configure settings for connecting through a Remote Desktop Gateway when I am working remotely.")
        t2.setWordWrap(True)
        b2.addWidget(t2, 0, 0, 1, 2)
        b2.addWidget(QLabel("Gateway server:"), 1, 0)
        self.gateway = QLineEdit(str(self.rdp.get("gatewayhostname") or ""))
        self.gateway.setPlaceholderText("(none)")
        b2.addWidget(self.gateway, 1, 1)
        v.addWidget(box2)
        v.addStretch(1)
        return w

    # ---- dialogs ----
    def _audio(self):
        d = AudioDialog(self, self.rdp)
        if d.exec() == QDialog.Accepted:
            self.rdp.set("audiomode", d.play.checkedId())
            self.rdp.set("audiocapturemode", d.record.checkedId())

    def _drives(self):
        d = DrivesDialog(self, self.rdp)
        if d.exec() == QDialog.Accepted:
            self.rdp.set("drivestoredirect", d.value())

    # ---- state ----
    def host(self) -> str:
        return (self.general_computer if self.tabs.isVisible() else self.computer).currentText().strip()

    def _computer_changed(self, text: str):
        for box in (self.computer, self.general_computer):
            if box.currentText() != text:
                box.blockSignals(True)
                box.setCurrentText(text)
                box.blockSignals(False)
        self._update_cred_note()

    def _update_cred_note(self):
        host = self.host()
        saved = saved_credentials(host) if host else None
        user = self.user_edit.text().strip() or (saved or {}).get("user", "")
        self.user_label.setText(user or "None specified")
        if saved:
            text = ("Saved credentials will be used to connect to this computer. You can <a href='edit'>edit</a> "
                    "or <a href='delete'>delete</a> these credentials.")
        else:
            text = "You will be asked for credentials when you connect."
        self.cred_note.setText(text)
        self.general_note.setText(text)

    def _cred_link(self, link: str):
        host = self.host()
        if link == "delete":
            delete_credentials(host)
        elif link == "edit":
            saved = saved_credentials(host) or {}
            d = CredentialsDialog(self, host, saved.get("user", self.user_edit.text()))
            if d.exec() == QDialog.Accepted and d.user.text().strip():
                save_credentials(host, d.user.text().strip(), d.password.text())
                self.user_edit.setText(d.user.text().strip())
        self._update_cred_note()

    def _set_options(self, shown: bool):
        self.tabs.setVisible(shown)
        self.short.setVisible(not shown)
        self.options_btn.setText("▲  Hide &Options" if shown else "▼  Show &Options")
        self.adjustSize()

    def _toggle_options(self):
        self._set_options(not self.tabs.isVisible())

    def collect(self) -> RdpFile:
        """The window's choices into the .rdp settings."""
        r = self.rdp
        r.set("full address", self.host())
        r.set("username", self.user_edit.text().strip())
        full = self.size_slider.value() >= len(SIZES)
        r.set("screen mode id", 2 if full else 1)
        if not full:
            r.set("desktopwidth", SIZES[self.size_slider.value()][0])
            r.set("desktopheight", SIZES[self.size_slider.value()][1])
        r.set("use multimon", int(self.multimon.isChecked() and full))
        r.set("session bpp", self.colors.currentData())
        r.set("displayconnectionbar", int(self.conn_bar.isChecked()))
        r.set("keyboardhook", self.keys.currentData())
        r.set("redirectprinters", int(self.printers.isChecked()))
        r.set("redirectclipboard", int(self.clipboard.isChecked()))
        r.set("connection type", self.speed.currentData())
        r.set("networkautodetect", int(self.speed.currentData() == 7))
        for key, (c, inverted) in self.exp.items():
            r.set(key, int(c.isChecked() != inverted))
        r.set("autoreconnection enabled", int(self.reconnect.isChecked()))
        r.set("authentication level", self.auth.currentData())
        r.set("gatewayhostname", self.gateway.text().strip())
        r.set("prompt for credentials", int(not self.allow_save.isChecked()))
        return r

    # ---- files ----
    def _save(self):
        self.collect().save(self.rdp.path or DEFAULT_RDP)

    def _save_as(self):
        start = str(self.rdp.path or (Path.home() / "Documents" / f"{self.host() or 'Connection'}.rdp"))
        path, _f = QFileDialog.getSaveFileName(self, "Save As", start, "Remote Desktop Files (*.rdp)")
        if path:
            if not path.lower().endswith(".rdp"):
                path += ".rdp"
            self.collect().save(Path(path))

    def _open(self):
        path, _f = QFileDialog.getOpenFileName(self, "Open", str(Path.home() / "Documents"),
                                               "Remote Desktop Files (*.rdp)")
        if path:
            app = QApplication.instance()
            w = RemoteDesktop(RdpFile(Path(path)))
            w.rejected.connect(app.quit)
            w.accepted.connect(app.quit)
            app._remote_window = w          # keep it alive
            w._set_options(True)
            w.show()
            self.rejected.disconnect()
            self.accepted.disconnect()
            self.close()

    def _save_and_close(self):
        self._save()
        self.accept()

    # ---- connecting ----
    def connect_now(self):
        host = self.host()
        if not host:
            QMessageBox.warning(self, APP, "Enter the name of the remote computer.")
            return
        program = client_program()
        if not program:
            QMessageBox.critical(self, APP, "The Remote Desktop client (FreeRDP) is not installed.")
            return
        rdp = self.collect()
        remember_computer(host)
        try:
            rdp.save(DEFAULT_RDP if rdp.path is None or rdp.path == DEFAULT_RDP else rdp.path)
        except OSError:
            pass
        saved = saved_credentials(host) if self.allow_save.isChecked() else None
        user = rdp.get("username") or (saved or {}).get("user", "")
        if saved and (not rdp.get("username") or saved.get("user") == rdp.get("username")):
            self.start(program, rdp, saved.get("user", user), saved.get("password", ""), remember=False)
        else:
            self.ask_and_start(program, rdp, str(user))

    def ask_and_start(self, program: str, rdp: RdpFile, user: str, error: str = ""):
        host = str(rdp.get("full address"))
        d = CredentialsDialog(self, host, user, error, remember=self.allow_save.isChecked())
        if d.exec() != QDialog.Accepted:
            self.show()
            return
        self.start(program, rdp, d.user.text().strip(), d.password.text(), remember=d.remember.isChecked())

    def start(self, program: str, rdp: RdpFile, user: str, password: str, remember: bool):
        self.session_user, self.session_password = user, password
        self.remember_after_login = remember
        self.output = ""
        args = freerdp_args(rdp, user, password, program)
        self.proc = QProcess(self)
        self.proc.setProgram(program)
        self.proc.setArguments(["/args-from:stdin"])
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(lambda code, _status: self._finished(program, rdp, code))
        self.proc.started.connect(lambda: self._send_args(args))
        self.hide()
        self.proc.start()
        # once the session has lasted a little, the password worked: keep it if asked to
        QTimer.singleShot(8000, self._logged_in)

    def _send_args(self, args: list[str]):
        if self.proc is None:
            return
        self.proc.write(("\n".join(args) + "\n").encode())
        self.proc.closeWriteChannel()

    def _read(self):
        if self.proc is not None:
            self.output += bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
            self.output = self.output[-20000:]

    def _logged_in(self):
        if self.proc is not None and self.proc.state() != QProcess.NotRunning and self.remember_after_login:
            host = str(self.rdp.get("full address"))
            if save_credentials(host, self.session_user, self.session_password or ""):
                self.remember_after_login = False

    def _finished(self, program: str, rdp: RdpFile, code: int):
        self._read()
        proc, self.proc = self.proc, None
        if proc is not None:
            proc.deleteLater()
        host = str(rdp.get("full address"))
        kind, message = explain(self.output, code, host)
        if os.environ.get("CLASSIC7_MSTSC_LOG"):
            Path(os.environ["CLASSIC7_MSTSC_LOG"]).write_text(f"exit {code}: {kind}\n{self.output}")
        if kind == "ok":
            QApplication.instance().quit()
            return
        if kind == "quiet":
            self.show()
            return
        if kind == "logon":
            if saved_credentials(host):
                delete_credentials(host)
            self.ask_and_start(program, rdp, self.session_user, "The logon attempt failed")
            return
        QMessageBox.critical(None, APP, message)
        self.show()


# ---- command line --------------------------------------------------------------------------------------
def parse_args(argv: list[str]) -> tuple[RdpFile, bool, bool]:
    """mstsc's own switches: FILE.rdp, /v:computer, /f, /w: /h:, /edit FILE."""
    rdp = RdpFile(DEFAULT_RDP if DEFAULT_RDP.exists() else None)
    rdp.path = None if not DEFAULT_RDP.exists() else DEFAULT_RDP
    edit = False
    direct = False
    i = 0
    while i < len(argv):
        a = argv[i]
        low = a.lower()
        if low == "/edit" and i + 1 < len(argv):
            rdp = RdpFile(Path(argv[i + 1]))
            edit = True
            i += 1
        elif low.endswith(".rdp") and not low.startswith("/"):
            path = Path(QUrl(a).toLocalFile()) if a.startswith("file://") else Path(a)
            rdp = RdpFile(path)
            direct = True
        elif low.startswith("/v:"):
            rdp.set("full address", a[3:])
            direct = True
        elif low == "/f":
            rdp.set("screen mode id", 2)
        elif low.startswith("/w:"):
            rdp.set("screen mode id", 1)
            rdp.set("desktopwidth", int(re.sub(r"\D", "", a[3:]) or 1024))
        elif low.startswith("/h:"):
            rdp.set("screen mode id", 1)
            rdp.set("desktopheight", int(re.sub(r"\D", "", a[3:]) or 768))
        i += 1
    return rdp, edit, direct


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "/?"):
        print(__doc__.split("\n\n")[1].strip())
        return 0
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-mstsc")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-mstsc")
    app.setQuitOnLastWindowClosed(False)
    rdp, edit, direct = parse_args(argv)
    w = RemoteDesktop(rdp, edit_only=edit)
    w.rejected.connect(app.quit)
    w.accepted.connect(app.quit)
    if direct and not edit and str(rdp.get("full address")).strip():
        QTimer.singleShot(0, w.connect_now)
    else:
        w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
