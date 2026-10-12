// Classic 7 desktop layout: classic blue desktop and one bottom taskbar
// Start | quick launch | task buttons with text | tray | clock

var desktopsArray = desktopsForActivity(currentActivity());
for (var j = 0; j < desktopsArray.length; j++) {
    var desk = desktopsArray[j];
    desk.wallpaperPlugin = "org.kde.color";
    desk.currentConfigGroup = ["Wallpaper", "org.kde.color", "General"];
    desk.writeConfig("Color", "58,110,165");
    // desktop icons at 32 px (0=22, 1=32, 2=48, 3=64 = Plasma default), like Windows
    desk.currentConfigGroup = ["General"];
    desk.writeConfig("iconSize", 1);
}

// BEGIN TASKBAR (classic7-appearance --taskbar runs this part again; keep it self-contained)
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
panel.addWidget("org.kde.plasma.systemtray");

var clock = panel.addWidget("org.kde.plasma.digitalclock");
if (clock) {
    clock.currentConfigGroup = ["Appearance"];
    clock.writeConfig("showDate", false);
}
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
