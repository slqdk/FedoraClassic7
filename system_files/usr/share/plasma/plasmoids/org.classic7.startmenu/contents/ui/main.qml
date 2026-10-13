/*
    Classic 7 Start Menu: the Windows 7 Start menu layout in the Classic look.
    Data comes from Plasma's own launcher models (org.kde.plasma.private.kicker), so
    apps, search, recent items and session actions behave like the stock menus.

    SPDX-License-Identifier: GPL-2.0-or-later
*/
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtCore

import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami
import org.kde.coreaddons as KCoreAddons
import org.kde.plasma.private.kicker as Kicker
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    signal reset

    preferredRepresentation: compactRepresentation
    compactRepresentation: StartButton {}
    fullRepresentation: StartMenu {}

    Plasmoid.icon: "start-here"
    toolTipMainText: i18n("Start")
    toolTipSubText: ""

    // ---- data ------------------------------------------------------------------------
    function folderUrl(location) {
        return String(StandardPaths.writableLocation(location));
    }

    // Left column, top: pinned programs (configurable, right-click to pin/unpin)
    readonly property Kicker.SimpleFavoritesModel pinnedModel: Kicker.SimpleFavoritesModel {
        favorites: Plasmoid.configuration.favoriteApps
    }

    // Left column: recently used programs
    readonly property Kicker.RecentUsageModel recentModel: Kicker.RecentUsageModel {
        shownItems: Kicker.RecentUsageModel.OnlyApps
        ordering: Kicker.RecentUsageModel.Recent
    }

    // All Programs: the application categories as folders
    readonly property Kicker.AppsModel appsModel: Kicker.AppsModel {
        autoPopulate: true
        flat: false
        sorted: true
        showSeparators: false
        showTopLevelItems: true
        appNameFormat: 0
        appletInterface: root
    }

    // Search programs and files
    readonly property Kicker.RunnerModel runnerModel: Kicker.RunnerModel {
        appletInterface: root
        mergeResults: true
        runners: ["krunner_services", "krunner_systemsettings", "calculator", "unitconverter",
                  "baloosearch", "locations", "krunner_shell"]
    }

    // Right column, in the Windows 7 order
    readonly property Kicker.SimpleFavoritesModel placesModel: Kicker.SimpleFavoritesModel {
        favorites: [
            root.folderUrl(StandardPaths.DocumentsLocation),
            root.folderUrl(StandardPaths.PicturesLocation),
            root.folderUrl(StandardPaths.MusicLocation),
            "classic7-games.desktop"
        ]
    }
    readonly property Kicker.SimpleFavoritesModel computerModel: Kicker.SimpleFavoritesModel {
        favorites: ["classic7-computer.desktop"]
    }
    readonly property Kicker.SimpleFavoritesModel settingsModel: Kicker.SimpleFavoritesModel {
        favorites: ["classic7-control-panel.desktop", "classic7-devices.desktop",
                    "classic7-default-programs.desktop", "classic7-help.desktop"]
    }
    readonly property Kicker.SimpleFavoritesModel runModel: Kicker.SimpleFavoritesModel {
        favorites: ["classic7-run.desktop"]
    }

    // Shut down button and the options next to it
    readonly property Kicker.SimpleFavoritesModel shutdownModel: Kicker.SimpleFavoritesModel {
        favorites: ["shutdown"]
    }
    readonly property Kicker.SimpleFavoritesModel sessionModel: Kicker.SimpleFavoritesModel {
        favorites: ["switch-user", "logout", "lock-screen", "reboot", "suspend", "hibernate"]
    }

    readonly property KCoreAddons.KUser kuser: KCoreAddons.KUser {}

    readonly property var pinnedKeys: Plasmoid.configuration.favoriteApps.map(
        id => String(id).replace(/^applications:/, "").replace(/\.desktop$/, "").toLowerCase())

    function pin(favoriteId) {
        if (!favoriteId) {
            return;
        }
        const list = Plasmoid.configuration.favoriteApps.slice();
        if (list.indexOf(favoriteId) === -1) {
            list.push(favoriteId);
            Plasmoid.configuration.favoriteApps = list;
        }
    }

    function unpin(favoriteId) {
        Plasmoid.configuration.favoriteApps =
            Plasmoid.configuration.favoriteApps.filter(id => id !== favoriteId);
    }

    function isPinned(favoriteId) {
        return Plasmoid.configuration.favoriteApps.indexOf(favoriteId) !== -1;
    }

    // ---- jump lists: recent documents and tasks per program (classic7-jumplist) -------------
    property var jumpLists: ({})
    function hasJump(key) {
        const j = jumpLists[key];
        return !!j && ((j.recent || []).length > 0 || (j.tasks || []).length > 0);
    }
    function runJump(kind, key, index) {
        if (!/^[a-z0-9._-]+$/.test(key)) {
            return;
        }
        shell.connectSource("classic7-jumplist " + (kind === "task" ? "--task " : "--open ") + key + " "
                            + Number(index) + " # " + Date.now());
    }

    // ---- taskbar (Quick Launch) pins: "Pin to Taskbar" in the right-click menu ----------
    property var taskbarUrls: []
    function fileName(url) {
        return decodeURIComponent(String(url || "").split("/").pop());
    }
    function isOnTaskbar(url) {
        const name = fileName(url);
        return name !== "" && taskbarUrls.some(u => fileName(u) === name);
    }
    function pinToTaskbar(url, add) {
        if (!url) {
            return;
        }
        const name = fileName(url);
        taskbarUrls = add ? taskbarUrls.concat([String(url)]) : taskbarUrls.filter(u => fileName(u) !== name);
        shell.connectSource("classic7-taskbar-pin " + (add ? "--add" : "--remove") + " '"
                            + String(url).replace(/'/g, "") + "' # " + Date.now());
    }
    P5Support.DataSource {
        id: shell
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            if (source.indexOf("classic7-taskbar-pin --list") === 0) {
                root.taskbarUrls = String(data["stdout"] || "").split("\n").filter(u => u.length > 0);
            } else if (source.indexOf("classic7-jumplist --json") === 0) {
                try {
                    root.jumpLists = JSON.parse(String(data["stdout"] || "{}"));
                } catch (e) {
                    root.jumpLists = {};
                }
            }
            disconnectSource(source);
        }
    }

    onExpandedChanged: {
        if (expanded) {
            shell.connectSource("classic7-taskbar-pin --list # " + Date.now());
            shell.connectSource("classic7-jumplist --json # " + Date.now());
        }
        if (!expanded) {
            runnerModel.query = "";
            reset();
        }
    }

    Component.onCompleted: {
        if (Plasmoid.hasOwnProperty("activationTogglesExpanded")) {
            Plasmoid.activationTogglesExpanded = true;
        }
    }
}
