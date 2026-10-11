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

    onExpandedChanged: {
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
