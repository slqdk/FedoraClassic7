// Classic 7 Aero desktop layout: the Aero wallpaper and one glass taskbar
// Start orb | pinned and running programs (icons) | tray | clock and date | Show desktop

var desktopsArray = desktopsForActivity(currentActivity());
for (var j = 0; j < desktopsArray.length; j++) {
    var desk = desktopsArray[j];
    desk.wallpaperPlugin = "org.kde.image";
    desk.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"];
    desk.writeConfig("Image", "file:///usr/share/wallpapers/Classic7Aero/");
    desk.writeConfig("FillMode", 2);
    desk.writeConfig("Color", "#1c5a9e");
    // desktop icons at 32 px (0=22, 1=32, 2=48, 3=64 = Plasma default), like Windows
    desk.currentConfigGroup = ["General"];
    desk.writeConfig("iconSize", 1);
    desk.writeConfig("useTypeAhead", true);     // typing selects an icon, like Windows (not KRunner)
}

// BEGIN TASKBAR (classic7-appearance --taskbar runs this part again; keep it self-contained)
// Taskbar right-click menu like Windows 7 (Cascade windows... Start Task Manager)
var taskbarActions = ConfigFile(ConfigFile("plasma-org.kde.plasma.desktop-appletsrc", "ActionPlugins"), "1");
taskbarActions.writeEntry("RightButton;NoModifier", "org.classic7.taskbarmenu");
var panel = new Panel;
panel.location = "bottom";
panel.height = 40;
panel.hiding = "none";
panel.floating = false;

// the Start orb + Windows 7 style Start menu (Kicker as a fallback)
var start = panel.addWidget("org.classic7.startmenu");
if (start) {
    start.currentConfigGroup = ["General"];
    start.writeConfig("buttonImage", "/usr/share/classic7/start-orb.svg");
    start.writeConfig("look", "aero");
    start.writeConfig("favoriteApps", [
        "org.mozilla.firefox.desktop",
        "firefox.desktop",
        "classic7-prompt.desktop",
        "steam.desktop",
        "org.kde.dolphin.desktop"
    ]);
} else {
    start = panel.addWidget("org.kde.plasma.kicker");
    start.currentConfigGroup = ["General"];
    start.writeConfig("useCustomButtonImage", true);
    start.writeConfig("customButtonImage", "/usr/share/classic7/start-orb.svg");
    start.writeConfig("showIconsRootLevel", true);
}

// Windows 7 task buttons: icons, one button per program, programs pinned to the taskbar
var tasks = panel.addWidget("org.kde.plasma.icontasks");
if (tasks) {
    tasks.currentConfigGroup = ["General"];
    tasks.writeConfig("launchers", [
        "file:///usr/share/applications/org.kde.dolphin.desktop",
        "file:///var/lib/flatpak/exports/share/applications/org.mozilla.firefox.desktop",
        "file:///usr/share/applications/steam.desktop",
        "file:///usr/share/applications/classic7-prompt.desktop"
    ]);
    tasks.writeConfig("groupingStrategy", 1);
    tasks.writeConfig("onlyGroupWhenFull", false);
}

panel.addWidget("org.kde.plasma.marginsseparator");
// The notification area of Windows 7 (see the Classic layout for the details)
function classic7Tray(tray) {
    if (!tray) return;
    var swaps = {"org.kde.plasma.networkmanagement": "org.classic7.network",
                 "org.kde.plasma.volume": "org.classic7.volume"};
    var adds = ["org.classic7.actioncenter"];
    function fixLists(obj) {
        obj.currentConfigGroup = ["General"];
        function list(k) {
            var v = obj.readConfig(k, []);
            if (typeof v === "string") v = v ? v.split(",") : [];
            return v;
        }
        var extra = list("extraItems").filter(function (x) { return !(x in swaps); });
        var known = list("knownItems");
        var ours = Object.keys(swaps).map(function (k) { return swaps[k]; }).concat(adds);
        ours.forEach(function (x) { if (extra.indexOf(x) === -1) extra.push(x); });
        Object.keys(swaps).concat(ours).forEach(function (x) { if (known.indexOf(x) === -1) known.push(x); });
        obj.writeConfig("extraItems", extra);
        obj.writeConfig("knownItems", known);
    }
    tray.currentConfigGroup = [];
    var id = tray.readConfig("SystrayContainmentId");
    var c = id ? desktopById(id) : null;
    if (c) {
        Object.keys(swaps).forEach(function (x) { c.widgets(x).forEach(function (w) { w.remove(); }); });
        fixLists(c);
        c.reloadConfig();
    } else {
        fixLists(tray);
        tray.reloadConfig();
    }
}
classic7Tray(panel.addWidget("org.kde.plasma.systemtray"));

// the Windows 7 clock: time and date on the tall taskbar
var clock = panel.addWidget("org.classic7.clock");
if (!clock) {
    clock = panel.addWidget("org.kde.plasma.digitalclock");
}
// the Show desktop strip at the right end, with Aero Peek
var show = panel.addWidget("org.classic7.showdesktop");
if (show) {
    show.currentConfigGroup = ["General"];
    show.writeConfig("look", "aero");
}
// END TASKBAR

// Desktop right-click menu: keep Display Configuration ("Screen resolution") and
// Configure Desktop and Wallpaper ("Personalize"); drop Edit Mode and Activities.
var actionPlugins = ConfigFile("plasma-org.kde.plasma.desktop-appletsrc", "ActionPlugins");
var desktopActions = ConfigFile(actionPlugins, "0");
desktopActions.writeEntry("RightButton;NoModifier", "org.kde.contextmenu");
desktopActions.writeEntry("MiddleButton;NoModifier", "org.kde.paste");
var desktopMenu = ConfigFile(desktopActions, "RightButton;NoModifier");
desktopMenu.writeEntry("desktop edit mode", false);
desktopMenu.writeEntry("manage activities", false);
desktopMenu.writeEntry("add widgets", false);
desktopMenu.writeEntry("_display_settings", true);
desktopMenu.writeEntry("configure", true);
