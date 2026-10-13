// Classic 7 desktop layout: classic blue desktop and one bottom taskbar
// Start | quick launch | task buttons with text | tray | clock

var desktopsArray = desktopsForActivity(currentActivity());
for (var j = 0; j < desktopsArray.length; j++) {
    var desk = desktopsArray[j];
    desk.wallpaperPlugin = "org.kde.color";
    desk.currentConfigGroup = ["Wallpaper", "org.kde.color", "General"];
    desk.writeConfig("Color", "#3a6ea5");
    // desktop icons at 32 px (0=22, 1=32, 2=48, 3=64 = Plasma default), like Windows
    desk.currentConfigGroup = ["General"];
    desk.writeConfig("iconSize", 1);
    desk.writeConfig("useTypeAhead", true);     // typing selects an icon, like Windows (not KRunner)
}

// BEGIN TASKBAR (classic7-appearance --taskbar runs this part again; keep it self-contained)
// Taskbar right-click menu like Windows 7 (Cascade windows... Start Task Manager): the plugin is
// built into the image (build_files/taskbarmenu). [ActionPlugins][1] = panels; written before
// the panel exists, because a panel reads its menu plugin when it is created.
var taskbarActions = ConfigFile(ConfigFile("plasma-org.kde.plasma.desktop-appletsrc", "ActionPlugins"), "1");
taskbarActions.writeEntry("RightButton;NoModifier", "org.classic7.taskbarmenu");
var panel = new Panel;
panel.location = "bottom";
panel.height = 30;
panel.hiding = "none";
panel.floating = false;

// Start button + Windows 7 style Start menu (our own applet; Kicker as a fallback)
var start = panel.addWidget("org.classic7.startmenu");
if (start) {
    start.currentConfigGroup = ["General"];
    start.writeConfig("buttonImage", "/usr/share/classic7/start-button.svg");
    // Firefox by name: preferred://browser can resolve to a text editor when no default
    // browser is set; entries for programs that aren't installed are simply left out
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
    // A plain path (not file://): only then does kicker show a wide image at its real width
    start.writeConfig("customButtonImage", "/usr/share/classic7/start-button.svg");
    start.writeConfig("showIconsRootLevel", true);
    start.writeConfig("showRecentApps", false);
    start.writeConfig("showRecentDocs", false);
    start.writeConfig("alphaSort", true);
    start.writeConfig("favoritesPortedToKAstats", false);
    start.writeConfig("favoriteApps", [
        "preferred://browser",
        "classic7-computer.desktop",
        "org.kde.dolphin.desktop",
        "classic7-prompt.desktop",
        "steam.desktop",
        "classic7-appearance.desktop",
        "systemsettings.desktop"
    ]);
}

// Quick Launch (kdeplasma-addons); skipped if the widget is not installed
var quick = panel.addWidget("org.kde.plasma.quicklaunch");
if (quick) {
    quick.currentConfigGroup = ["General"];
    quick.writeConfig("launcherUrls", [
        "file:///usr/share/applications/org.kde.dolphin.desktop",
        "file:///usr/share/applications/steam.desktop",
        "file:///usr/share/applications/classic7-prompt.desktop"
    ]);
}

// Task buttons with titles (not the icons-only variant)
var tasks = panel.addWidget("org.kde.plasma.taskmanager");
if (tasks) {
    tasks.currentConfigGroup = ["General"];
    tasks.writeConfig("launchers", []);
    tasks.writeConfig("onlyGroupWhenFull", true);
    tasks.writeConfig("taskMaxWidth", 0);        // Narrow: classic ~160 px task buttons
    tasks.writeConfig("maxTextLines", 1);
    tasks.writeConfig("taskHoverEffect", false);
}

panel.addWidget("org.kde.plasma.marginsseparator");
// The notification area of Windows 7: Classic 7's network and volume icons instead of Plasma's,
// and the Action Center flag. Plasma's stay "known" so the tray doesn't add them back by itself.
// Plasma 6.7 keeps the tray's items in the tray applet itself; older Plasma in a containment of
// its own (SystrayContainmentId).
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
        // Plasma's icons may already be running in the tray: remove them, not only from the list
        Object.keys(swaps).forEach(function (x) { c.widgets(x).forEach(function (w) { w.remove(); }); });
        fixLists(c);
        c.reloadConfig();
    } else {
        fixLists(tray);
        tray.reloadConfig();
    }
}
classic7Tray(panel.addWidget("org.kde.plasma.systemtray"));

// the Windows 7 clock (time, and the date on a tall taskbar; calendar and clock face on click)
var clock = panel.addWidget("org.classic7.clock");
if (!clock) {
    clock = panel.addWidget("org.kde.plasma.digitalclock");
    if (clock) {
        clock.currentConfigGroup = ["Appearance"];
        clock.writeConfig("showDate", false);
    }
}
// the narrow Show desktop button at the right end, like Windows 7
panel.addWidget("org.classic7.showdesktop");
// END TASKBAR

// Desktop right-click menu: keep Display Configuration ("Screen resolution") and
// Configure Desktop and Wallpaper ("Personalize"); drop Edit Mode and Activities.
// Settings live in [ActionPlugins][0] (0 = desktop containments) of the applets config.
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
