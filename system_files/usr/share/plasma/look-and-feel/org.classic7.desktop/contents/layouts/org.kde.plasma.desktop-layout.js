// Classic 7 desktop layout: classic blue desktop and one bottom taskbar
// Start | quick launch | task buttons with text | tray | clock

var desktopsArray = desktopsForActivity(currentActivity());
for (var j = 0; j < desktopsArray.length; j++) {
    var desk = desktopsArray[j];
    desk.wallpaperPlugin = "org.kde.color";
    desk.currentConfigGroup = ["Wallpaper", "org.kde.color", "General"];
    desk.writeConfig("Color", "58,110,165");
}

var panel = new Panel;
panel.location = "bottom";
panel.height = 30;
panel.hiding = "none";
panel.floating = false;

// Start button: the cascading Application Menu with a "Start" image
var start = panel.addWidget("org.kde.plasma.kicker");
if (start) {
    start.currentConfigGroup = ["General"];
    start.writeConfig("useCustomButtonImage", true);
    start.writeConfig("customButtonImage", "file:///usr/share/classic7/start-button.svg");
    start.writeConfig("showRecentApps", false);
    start.writeConfig("showRecentDocs", false);
    start.writeConfig("alphaSort", true);
    // Pinned items at the top of the Start menu
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
}

panel.addWidget("org.kde.plasma.marginsseparator");
panel.addWidget("org.kde.plasma.systemtray");

var clock = panel.addWidget("org.kde.plasma.digitalclock");
if (clock) {
    clock.currentConfigGroup = ["Appearance"];
    clock.writeConfig("showDate", false);
}

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
