"""Control Panel items and categories (no GUI code), as in Windows 7.

Each item opens a KDE settings module in its own window (kcmshell6), or one of Classic 7's
own windows. Items whose module or program is missing on this system are left out.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class Task:
    text: str
    run: list[str]


@dataclass
class Item:
    id: str                       # canonical name, like Windows' "Microsoft.Mouse"
    title: str
    icon: str
    category: str                 # one of CATEGORIES (ids); the first is where the item lives
    run: list[str]
    tasks: list[Task] = field(default_factory=list)
    keywords: str = ""
    also: tuple[str, ...] = ()    # other categories that list it too
    needs: str | None = None      # kcm module or program that must exist (default: from run)
    cpl: tuple[str, ...] = ()     # names that open it from Run: "main.cpl", "mouse"


@dataclass
class Category:
    id: str
    title: str
    icon: str
    links: list[tuple[str, str]]  # (text, item id or "item:task index") shown on the home page
    keywords: str = ""


def kcm(name: str) -> list[str]:
    return ["kcmshell6", name]


CATEGORIES = [
    Category("system", "System and Security", "preferences-system",
             [("Review your computer's status", "Classic7.System"), ("Check for updates", "Classic7.Update"),
              ("Manage drives", "Classic7.DiskManagement")], "security firewall update power backup"),
    Category("network", "Network and Internet", "preferences-system-network",
             [("View network status and tasks", "Classic7.NetworkCenter"),
              ("Map a network drive", "Classic7.MapNetworkDrive")], "internet wifi network ethernet proxy"),
    Category("hardware", "Hardware and Sound", "preferences-desktop-peripherals",
             [("View devices and printers", "Classic7.DevicesAndPrinters"), ("Add a device", "Classic7.Bluetooth")],
             "printer mouse keyboard sound display audio device"),
    Category("programs", "Programs", "applications-other",
             [("Uninstall a program", "Classic7.ProgramsAndFeatures")], "software apps uninstall install default"),
    Category("users", "User Accounts and Family Safety", "system-users",
             [("Add or remove user accounts", "Classic7.UserAccounts")], "user account password login"),
    Category("appearance", "Appearance and Personalization", "preferences-desktop-theme",
             [("Change the theme", "Classic7.Personalization"), ("Change desktop background", "Classic7.Background"),
              ("Adjust screen resolution", "Classic7.Display")], "theme wallpaper colours fonts desktop"),
    Category("clock", "Clock, Language, and Region", "preferences-system-time",
             [("Change keyboards or other input methods", "Classic7.Keyboard#layout"),
              ("Change display language", "Classic7.RegionAndLanguage")], "time date language keyboard region"),
    Category("access", "Ease of Access", "preferences-desktop-accessibility",
             [("Let Classic 7 suggest settings", "Classic7.EaseOfAccess"),
              ("Optimize visual display", "Classic7.EaseOfAccess")], "accessibility"),
]


def _items() -> list[Item]:
    import programs_data
    steam_store = programs_data.store_command()
    return [
        # System and Security
        Item("Classic7.System", "System", "computer", "system", ["classic7-system"],
             [Task("View amount of RAM and processor speed", ["classic7-system"]),
              Task("See the name of this computer", ["classic7-system"]),
              Task("Device Manager", ["classic7-devmgmt"])],
             "computer name processor memory ram about version", cpl=("system",)),
        Item("Classic7.SystemProperties", "System Properties", "computer", "system", ["classic7-system", "--properties"],
             [Task("Change the computer name", ["classic7-system", "--properties", "0"]),
              Task("Environment variables", ["classic7-system", "--properties", "2"]),
              Task("Restore the previous version (System Restore)", ["classic7-system", "--properties", "3"])],
             "system properties computer name environment variables restore rollback", cpl=("sysdm.cpl",),
             needs="classic7-system"),
        Item("Classic7.DeviceManager", "Device Manager", "computer", "hardware", ["classic7-devmgmt"],
             [Task("Update device drivers", ["classic7-devmgmt"]), Task("View devices and drivers", ["classic7-devmgmt"])],
             "device manager hardware drivers pci usb", also=("system",), cpl=("devmgmt.msc", "hdwwiz.cpl")),
        Item("Classic7.ActionCenter", "Action Center", "flag", "system", ["classic7-actioncenter"],
             [Task("Review your computer's status and resolve issues", ["classic7-actioncenter"]),
              Task("View archived messages", ["classic7-actioncenter", "--archived"])],
             "action center security maintenance problems messages", cpl=("wscui.cpl",)),
        Item("Classic7.Firewall", "Firewall", "security-high", "system", kcm("kcm_firewall"),
             [Task("Check firewall status", kcm("kcm_firewall"))], "firewall security ports", cpl=("firewall.cpl",)),
        Item("Classic7.Update", "Classic 7 Update", "system-software-update", "system", ["classic7-update", "--gui"],
             [Task("Check for updates", ["classic7-update", "--gui"]),
              Task("View update history", ["classic7-update", "--gui"])],
             "windows update upgrade new version", cpl=("wuapp", "update")),
        Item("Classic7.PowerOptions", "Power Options", "preferences-system-power-management", "system",
             kcm("kcm_powerdevilprofilesconfig"),
             [Task("Change what the power buttons do", kcm("kcm_powerdevilprofilesconfig")),
              Task("Change when the computer sleeps", kcm("kcm_powerdevilprofilesconfig"))],
             "power sleep battery hibernate screen off", also=("hardware",), cpl=("powercfg.cpl",)),
        Item("Classic7.AdministrativeTools", "Administrative Tools", "preferences-system", "system",
             ["classic7-diskmgmt"],
             [Task("Disk Management", ["classic7-diskmgmt"]), Task("Task Manager", ["classic7-taskmgr"]),
              Task("View event logs", ["kjournaldbrowser"] if shutil.which("kjournaldbrowser") else
                   ["classic7-prompt", "journalctl", "-b", "-p", "warning"]),
              Task("System Information", ["kinfocenter"])],
             "administrative tools computer management event viewer services logs", cpl=("admintools",)),
        Item("Classic7.DiskManagement", "Disk Management", "drive-harddisk", "system", ["classic7-diskmgmt"],
             [Task("Create and format hard disk partitions", ["classic7-diskmgmt"]),
              Task("Give a drive a letter", ["classic7-diskmgmt"])],
             "disk partition format drive letter mount steam library ntfs", cpl=("diskmgmt.msc",)),
        Item("Classic7.TaskManager", "Task Manager", "utilities-system-monitor", "system", ["classic7-taskmgr"],
             [Task("See which programs are running", ["classic7-taskmgr"])],
             "task manager processes performance end task cpu memory", cpl=("taskmgr",)),
        # Network and Internet
        Item("Classic7.NetworkCenter", "Network and Sharing Center", "network-workgroup", "network",
             ["classic7-network"],
             [Task("View network status and tasks", ["classic7-network"]),
              Task("Change adapter settings", ["classic7-network"]),
              Task("Connect to a network", kcm("kcm_networkmanagement"))],
             "network internet wifi wireless ethernet adapter ip address dhcp", cpl=("ncpa.cpl", "netconnections")),
        Item("Classic7.MapNetworkDrive", "Map Network Drive", "network-server", "network", ["classic7-netdrive"],
             [Task("Map a network drive", ["classic7-netdrive"]),
              Task("Disconnect a network drive", ["classic7-netdrive", "--disconnect"])],
             "share smb samba nas server mapped drive"),
        Item("Classic7.InternetOptions", "Internet Options", "preferences-web-browser-shortcuts", "network",
             kcm("kcm_proxy"), [Task("Change proxy settings", kcm("kcm_proxy")),
                                Task("Change web search shortcuts", kcm("kcm_webshortcuts"))],
             "proxy internet options browser", cpl=("inetcpl.cpl",)),
        Item("Classic7.RemoteDesktop", "Remote Desktop", "krdc", "network", kcm("kcm_krdpserver"),
             [Task("Allow remote connections to this computer", kcm("kcm_krdpserver"))], "remote desktop rdp"),
        # Hardware and Sound
        Item("Classic7.DevicesAndPrinters", "Devices and Printers", "printer", "hardware", kcm("kcm_printer_manager"),
             [Task("Add a printer", kcm("kcm_printer_manager")), Task("Device Manager", ["classic7-devmgmt"])],
             "printer scanner devices print", cpl=("printers",)),
        Item("Classic7.Bluetooth", "Bluetooth Devices", "preferences-system-bluetooth", "hardware",
             kcm("kcm_bluetooth"), [Task("Add a device", kcm("kcm_bluetooth"))], "bluetooth headset pair"),
        Item("Classic7.AutoPlay", "AutoPlay", "media-optical", "hardware", kcm("kcm_device_automounter"),
             [Task("Change default settings for media or devices", kcm("kcm_solid_actions")),
              Task("Open removable drives automatically", kcm("kcm_device_automounter"))],
             "autoplay automount usb removable cd dvd"),
        Item("Classic7.Sound", "Sound", "preferences-desktop-sound", "hardware", kcm("kcm_pulseaudio"),
             [Task("Adjust system volume", ["classic7-mixer"]), Task("Change system sounds", kcm("kcm_soundtheme")),
              Task("Manage audio devices", kcm("kcm_pulseaudio"))],
             "sound audio volume speakers headphones microphone", cpl=("mmsys.cpl", "sound")),
        Item("Classic7.Display", "Display", "preferences-desktop-display", "appearance", kcm("kcm_kscreen"),
             [Task("Adjust screen resolution", kcm("kcm_kscreen")),
              Task("Make text and other items larger or smaller", kcm("kcm_kscreen")),
              Task("Reduce blue light at night", kcm("kcm_nightlight")),
              Task("Calibrate colour", kcm("kcm_colord"))],
             "display screen resolution monitor refresh rate scale hdr", also=("hardware",), cpl=("desk.cpl",)),
        Item("Classic7.Mouse", "Mouse", "input-mouse", "hardware", kcm("kcm_mouse"),
             [Task("Change mouse settings", kcm("kcm_mouse")), Task("Change the mouse pointers", kcm("kcm_cursortheme"))],
             "mouse pointer cursor speed double-click", cpl=("main.cpl", "mouse")),
        Item("Classic7.Keyboard", "Keyboard", "input-keyboard", "hardware", kcm("kcm_keyboard"),
             [Task("Change keyboards or other input methods", kcm("kcm_keyboard")),
              Task("Keyboard shortcuts", kcm("kcm_keys"))],
             "keyboard layout repeat shortcuts", also=("clock",), cpl=("keyboard",)),
        Item("Classic7.Touchpad", "Touchpad", "input-touchpad", "hardware", kcm("kcm_touchpad"),
             [Task("Change touchpad settings", kcm("kcm_touchpad"))], "touchpad trackpad tap scroll"),
        Item("Classic7.GameControllers", "Game Controllers", "input-gaming", "hardware", kcm("kcm_gamecontroller"),
             [Task("Set up USB game controllers", kcm("kcm_gamecontroller"))],
             "joystick gamepad controller xbox playstation", cpl=("joy.cpl",)),
        Item("Classic7.PenAndTouch", "Pen and Touch", "input-tablet", "hardware", kcm("kcm_tablet"),
             [Task("Change tablet pen settings", kcm("kcm_tablet"))], "pen tablet drawing wacom touch"),
        Item("Classic7.GraphicsCard", "Graphics Card (LACT)", "video-display", "hardware", ["lact", "gui"],
             [Task("Fan curve, power limit and clocks", ["lact", "gui"])], "gpu graphics amd radeon fan overclock",
             needs="lact"),
        # Programs
        Item("Classic7.ProgramsAndFeatures", "Programs and Features", "system-software-install", "programs",
             ["classic7-programs"], [Task("Uninstall a program", ["classic7-programs"])]
             + ([Task("Install a program", steam_store)] if steam_store else []),
             "uninstall install programs software apps store steam games remove", cpl=("appwiz.cpl",)),
        Item("Classic7.DefaultPrograms", "Default Programs", "preferences-desktop-default-applications", "programs",
             kcm("kcm_componentchooser"),
             [Task("Set your default programs", kcm("kcm_componentchooser")),
              Task("Always use a specific program to open this file type", kcm("kcm_filetypes"))],
             "default programs browser email file types associations open with"),
        Item("Classic7.StartupPrograms", "Startup Programs", "system-run", "programs",
             ["classic7-msconfig", "--tab", "startup"],
             [Task("Choose programs that start with Classic 7", ["classic7-msconfig", "--tab", "startup"])],
             "startup autostart login", needs="classic7-msconfig"),
        Item("Classic7.SystemConfiguration", "System Configuration", "preferences-system", "system",
             ["classic7-msconfig"],
             [Task("Choose the programs and services that start", ["classic7-msconfig", "--tab", "startup"]),
              Task("Turn services on or off", ["classic7-msconfig", "--tab", "services"])],
             "msconfig startup services boot administrative tools", cpl=("msconfig",)),
        Item("Classic7.EventViewer", "Event Viewer", "utilities-log-viewer", "system", ["classic7-eventvwr"],
             [Task("View event logs", ["classic7-eventvwr"]),
              Task("View problem reports", ["classic7-eventvwr", "--problems"])],
             "event viewer logs journal errors crash problem reports administrative tools",
             cpl=("eventvwr", "eventvwr.msc")),
        Item("Classic7.Games", "Games", "applications-games", "programs", ["steam", "steam://open/games"],
             [Task("Open your game library", ["steam", "steam://open/games"])], "steam games library", needs="steam"),
        # User Accounts
        Item("Classic7.UserAccounts", "User Accounts", "system-users", "users", kcm("kcm_users"),
             [Task("Change your account picture", kcm("kcm_users")), Task("Add or remove user accounts", kcm("kcm_users")),
              Task("Change your password", kcm("kcm_users"))],
             "user account password picture administrator", cpl=("userpasswords",)),
        Item("Classic7.CredentialManager", "Credential Manager", "kwalletmanager", "users", kcm("kcm_kwallet5"),
             [Task("Manage saved passwords", kcm("kcm_kwallet5"))], "passwords wallet credentials keyring"),
        Item("Classic7.OnlineAccounts", "Online Accounts", "applications-internet", "users", kcm("kcm_kaccounts"),
             [Task("Add an online account", kcm("kcm_kaccounts"))], "google nextcloud accounts online"),
        Item("Classic7.LoginScreen", "Login Screen", "preferences-system-login", "users", kcm("kcm_sddm"),
             [Task("Change the login screen", kcm("kcm_sddm"))], "login screen sddm welcome", needs="kcm_sddm"),
        # Appearance and Personalization
        Item("Classic7.Personalization", "Personalization", "preferences-desktop-theme", "appearance",
             ["classic7-appearance"],
             [Task("Change window colours", ["classic7-appearance"]),
              Task("Change the theme", kcm("kcm_lookandfeel")),
              Task("Change sound effects", kcm("kcm_soundtheme")),
              Task("Change screen saver", kcm("kcm_screenlocker"))],
             "personalization theme colours window color appearance", cpl=("desktop", "color")),
        Item("Classic7.Background", "Desktop Background", "preferences-desktop-wallpaper", "appearance",
             kcm("kcm_wallpaper"), [Task("Change desktop background", kcm("kcm_wallpaper"))],
             "wallpaper background desktop picture"),
        Item("Classic7.Fonts", "Fonts", "preferences-desktop-font", "appearance", kcm("kcm_fontinst"),
             [Task("Preview, delete, or show and hide fonts", kcm("kcm_fontinst")),
              Task("Change font settings", kcm("kcm_fonts"))], "fonts typeface install", cpl=("fonts",)),
        Item("Classic7.Notifications", "Notification Area Icons", "preferences-desktop-notification", "appearance",
             kcm("kcm_notifications"), [Task("Customize notifications", kcm("kcm_notifications"))],
             "notifications tray popups"),
        Item("Classic7.ScreenLock", "Screen Saver and Lock", "preferences-desktop-screensaver", "appearance",
             kcm("kcm_screenlocker"), [Task("Change screen saver", kcm("kcm_screenlocker"))],
             "screen saver lock password wake"),
        Item("Classic7.WindowBehavior", "Window Behavior", "preferences-system-windows", "appearance",
             kcm("kcm_kwinoptions"),
             [Task("Change how windows are focused and moved", kcm("kcm_kwinoptions")),
              Task("Snap windows to screen edges", kcm("kcm_kwinscreenedges")),
              Task("Change the Alt+Tab window switcher", kcm("kcm_kwintabbox"))],
             "windows snap aero shake alt tab focus"),
        Item("Classic7.FolderOptions", "Folder Options", "folder", "appearance", kcm("kcm_desktoppaths"),
             [Task("Change the location of Documents, Pictures and other folders", kcm("kcm_desktoppaths")),
              Task("Recent files", kcm("kcm_recentFiles"))], "folders documents location paths explorer",
             cpl=("folders",)),
        # Clock, Language, and Region
        Item("Classic7.DateAndTime", "Date and Time", "preferences-system-time", "clock", ["classic7-timedate"],
             [Task("Set the time and date", ["classic7-timedate"]),
              Task("Change the time zone", ["classic7-timedate", "--zone"])],
             "clock date time zone ntp internet time", cpl=("timedate.cpl", "date/time")),
        Item("Classic7.RegionAndLanguage", "Region and Language", "preferences-desktop-locale", "clock",
             kcm("kcm_regionandlang"),
             [Task("Change the date, time, or number format", kcm("kcm_regionandlang")),
              Task("Change display language", kcm("kcm_regionandlang")),
              Task("Spelling", kcm("kcmspellchecking"))],
             "language region format currency locale", cpl=("intl.cpl", "international")),
        # Ease of Access
        Item("Classic7.EaseOfAccess", "Ease of Access Center", "preferences-desktop-accessibility", "access",
             kcm("kcm_access"),
             [Task("Optimize visual display", kcm("kcm_access")),
              Task("Change how your mouse works", kcm("kcm_access")),
              Task("Change how your keyboard works", kcm("kcm_access")),
              Task("Use the on-screen keyboard", kcm("kcm_virtualkeyboard"))],
             "accessibility magnifier sticky keys screen reader high contrast", cpl=("access.cpl",)),
    ]


@lru_cache(maxsize=1)
def _kcm_names() -> frozenset[str]:
    names = set()
    roots = {"/usr/lib64/qt6/plugins", "/usr/lib/qt6/plugins", "/usr/lib/x86_64-linux-gnu/qt6/plugins"}
    try:
        from PySide6.QtCore import QLibraryInfo
        roots.add(QLibraryInfo.path(QLibraryInfo.PluginsPath))
    except Exception:  # noqa: BLE001 - fine without Qt
        pass
    for root in roots:
        base = os.path.join(root, "plasma", "kcms")
        for dirpath, _dirs, files in os.walk(base):
            names |= {f[:-3] for f in files if f.endswith(".so")}
    for d in ("/usr/share/applications",):
        try:
            names |= {f[:-8] for f in os.listdir(d) if f.startswith("kcm") and f.endswith(".desktop")}
        except OSError:
            pass
    return frozenset(names)


def available(argv: list[str], needs: str | None = None) -> bool:
    if os.environ.get("CLASSIC7_CONTROL_ALL"):
        return True
    need = needs or (argv[1] if argv and argv[0] == "kcmshell6" and len(argv) > 1 else argv[0] if argv else "-")
    if need == "-":
        return False
    if need.startswith("kcm"):
        return need in _kcm_names() and bool(shutil.which("kcmshell6"))
    return shutil.which(need) is not None


@lru_cache(maxsize=1)
def items() -> tuple[Item, ...]:
    out = []
    for it in _items():
        if not available(it.run, it.needs):
            continue
        it.tasks = [t for t in it.tasks if available(t.run)]
        out.append(it)
    return tuple(out)


def by_id(item_id: str) -> Item | None:
    base = item_id.split("#")[0]
    return next((i for i in items() if i.id == base), None)


def in_category(cat: str) -> list[Item]:
    return [i for i in items() if i.category == cat or cat in i.also]


def category(cat_id: str) -> Category | None:
    return next((c for c in CATEGORIES if c.id == cat_id), None)


def search(text: str) -> list[tuple[Item, list[Task]]]:
    words = [w for w in text.lower().split() if w]
    if not words:
        return []
    out = []
    for it in items():
        hay = " ".join([it.title, it.keywords, it.id]).lower()
        tasks = [t for t in it.tasks if all(w in t.text.lower() for w in words)]
        if all(w in hay for w in words) or tasks:
            out.append((it, tasks or it.tasks[:3]))
    return out


def resolve(arg: str):
    """What `control ARG` opens: ("item", Item), ("category", id), ("all", None) or (None, None)."""
    a = arg.strip().lower()
    if a.startswith("/name "):
        a = a[6:].strip()
    a = a.removeprefix("microsoft.")
    if a in ("", "panel", "control panel"):
        return "home", None
    if a in ("all", "allitems", "all control panel items"):
        return "all", None
    for c in CATEGORIES:
        if a in (c.id, c.title.lower()):
            return "category", c.id
    for it in items():
        if a in (it.id.lower(), it.id.lower().removeprefix("classic7."), it.title.lower()) or a in it.cpl:
            return "item", it
    return None, None


def launch(argv: list[str]) -> bool:
    if not argv or not shutil.which(argv[0]):
        return False
    try:
        subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False
