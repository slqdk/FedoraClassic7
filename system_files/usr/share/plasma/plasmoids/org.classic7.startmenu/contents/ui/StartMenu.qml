/*
    The menu itself, laid out like the Windows 7 Start menu in the Classic theme:

      +---------------------------+-------------------+
      | pinned programs           | user name         |
      | ------------------------- | Documents         |
      | recently used programs    | Pictures          |
      |                           | Music             |
      |                           | Games             |
      |                           | ----------------- |
      |                           | Computer          |
      |                           | ----------------- |
      | ------------------------- | Control Panel     |
      | All Programs           >  | Devices and Pr... |
      | [Search programs and fil] | Default Programs  |
      |                           | Help and Support  |
      |                           | ----------------- |
      |                           | Run...            |
      |                           | [Shut down][>]    |
      +---------------------------+-------------------+

    SPDX-License-Identifier: GPL-2.0-or-later
*/
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtCore

import org.kde.plasma.plasmoid
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import org.kde.plasma.private.kicker as Kicker

FocusScope {
    id: menu

    readonly property int leftWidth: Math.round(Kirigami.Units.gridUnit * 15)
    readonly property int rightWidth: Math.round(Kirigami.Units.gridUnit * 9.5)
    readonly property int menuHeight: Math.round(Kirigami.Units.gridUnit * 27)
    readonly property int bigIcon: Kirigami.Units.iconSizes.medium      // 32 px like Windows
    readonly property int smallIcon: Kirigami.Units.iconSizes.small     // 16 px in All Programs

    // All Programs navigation: a stack of folder models, [] = not in All Programs
    property var folderStack: []
    property var folderTitles: []
    readonly property bool inPrograms: folderStack.length > 0
    readonly property bool searching: searchField.text.length > 0
    readonly property var searchResults: root.runnerModel.count > 0 ? root.runnerModel.modelForRow(0) : null

    Layout.minimumWidth: leftWidth + rightWidth
    Layout.maximumWidth: leftWidth + rightWidth
    Layout.preferredWidth: leftWidth + rightWidth
    Layout.minimumHeight: menuHeight
    Layout.maximumHeight: menuHeight
    Layout.preferredHeight: menuHeight

    function close() {
        root.expanded = false;
    }

    function trigger(model, index) {
        if (!model) {
            return;
        }
        model.trigger(index, "", null);
        close();
    }

    function openFolder(model, index, title) {
        const child = model.modelForRow(index);
        if (child) {
            folderStack = folderStack.concat([child]);
            folderTitles = folderTitles.concat([title]);
        }
    }

    function back() {
        folderStack = folderStack.slice(0, -1);
        folderTitles = folderTitles.slice(0, -1);
    }

    function resetMenu() {
        folderStack = [];
        folderTitles = [];
        searchField.text = "";
    }

    Connections {
        target: root
        function onReset() { menu.resetMenu(); }
        function onExpandedChanged() {
            if (root.expanded) {
                menu.resetMenu();
                searchField.forceActiveFocus();
            }
        }
    }

    Keys.onEscapePressed: {
        if (searching) {
            searchField.text = "";
        } else if (inPrograms) {
            back();
        } else {
            close();
        }
    }

    // ---- small building blocks ------------------------------------------------------
    component Etched: Item {
        Layout.fillWidth: true
        Layout.leftMargin: 6
        Layout.rightMargin: 6
        Layout.topMargin: 3
        Layout.bottomMargin: 3
        implicitHeight: 2
        Rectangle { width: parent.width; height: 1; y: 0; color: Qt.darker(Kirigami.Theme.backgroundColor, 1.45) }
        Rectangle { width: parent.width; height: 1; y: 1; color: Qt.lighter(Kirigami.Theme.backgroundColor, 1.6) }
    }

    PlasmaExtras.Menu {
        id: pinMenu
        property string favoriteId: ""
        PlasmaExtras.MenuItem {
            text: root.isPinned(pinMenu.favoriteId) ? i18n("Unpin from Start Menu") : i18n("Pin to Start Menu")
            icon: root.isPinned(pinMenu.favoriteId) ? "window-unpin" : "window-pin"
            onClicked: root.isPinned(pinMenu.favoriteId) ? root.unpin(pinMenu.favoriteId) : root.pin(pinMenu.favoriteId)
        }
    }

    // ---- layout ---------------------------------------------------------------------------
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Left column: white, like a list view
        Rectangle {
            Layout.preferredWidth: menu.leftWidth
            Layout.fillHeight: true
            Kirigami.Theme.colorSet: Kirigami.Theme.View
            Kirigami.Theme.inherit: false
            color: Kirigami.Theme.backgroundColor
            border.color: Qt.darker(Kirigami.Theme.backgroundColor, 1.6)
            border.width: 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 3
                spacing: 0

                // --- home: pinned + recent ---
                ColumnLayout {
                    visible: !menu.searching && !menu.inPrograms
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    EntryList {
                        startMenu: menu
                        contextMenu: pinMenu
                        id: pinnedList
                        model: root.pinnedModel
                        pinnable: true
                        Layout.preferredHeight: contentHeight
                        Layout.maximumHeight: contentHeight
                    }
                    Etched { visible: root.pinnedModel.count > 0 }
                    EntryList {
                        startMenu: menu
                        contextMenu: pinMenu
                        id: recentList
                        model: root.recentModel
                        pinnable: true
                        interactive: false
                        Layout.fillHeight: true
                    }
                }

                // --- All Programs: folders open in place, Back returns ---
                ColumnLayout {
                    visible: !menu.searching && menu.inPrograms
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    Text {
                        Layout.fillWidth: true
                        Layout.leftMargin: 8
                        Layout.topMargin: 2
                        Layout.bottomMargin: 2
                        text: menu.folderTitles.length > 1 ? menu.folderTitles[menu.folderTitles.length - 1] : i18n("All Programs")
                        font.bold: true
                        color: Kirigami.Theme.textColor
                        elide: Text.ElideRight
                    }
                    EntryList {
                        startMenu: menu
                        contextMenu: pinMenu
                        id: programsList
                        model: menu.inPrograms ? menu.folderStack[menu.folderStack.length - 1] : null
                        iconSize: menu.smallIcon
                        folders: true
                        pinnable: true
                        Layout.fillHeight: true
                    }
                }

                // --- search results ---
                ColumnLayout {
                    visible: menu.searching
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    Text {
                        Layout.leftMargin: 8
                        Layout.topMargin: 2
                        text: root.runnerModel.querying && !menu.searchResults ? i18n("Searching…")
                              : (menu.searchResults ? i18n("Programs and files") : i18n("No items match your search."))
                        font.bold: menu.searchResults !== null
                        color: Kirigami.Theme.textColor
                    }
                    EntryList {
                        startMenu: menu
                        contextMenu: pinMenu
                        id: resultsList
                        model: menu.searchResults
                        iconSize: menu.smallIcon
                        Layout.fillHeight: true
                    }
                }

                Etched {}

                MenuEntry {
                    text: menu.inPrograms ? i18n("Back") : i18n("All Programs")
                    arrow: !menu.inPrograms
                    backArrow: menu.inPrograms
                    bold: false
                    visible: !menu.searching
                    onActivated: {
                        if (menu.inPrograms) {
                            menu.back();
                        } else {
                            menu.openFolderRoot();
                        }
                    }
                }

                QQC2.TextField {
                    id: searchField
                    Layout.fillWidth: true
                    Layout.margins: 4
                    placeholderText: i18n("Search programs and files")
                    focus: true
                    onTextChanged: root.runnerModel.query = text
                    Keys.onReturnPressed: {
                        if (menu.searchResults && menu.searchResults.count > 0) {
                            menu.trigger(menu.searchResults, 0);
                        }
                    }
                    Keys.onDownPressed: {
                        const list = menu.searching ? resultsList : (menu.inPrograms ? programsList : pinnedList);
                        list.forceActiveFocus();
                        list.currentIndex = 0;
                    }
                }
            }
        }

        // Right column: grey, text only
        Rectangle {
            Layout.preferredWidth: menu.rightWidth
            Layout.fillHeight: true
            Kirigami.Theme.colorSet: Kirigami.Theme.Window
            Kirigami.Theme.inherit: false
            color: Kirigami.Theme.backgroundColor

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 4
                spacing: 0

                MenuEntry {
                    text: root.kuser.loginName
                    bold: true
                    toolTip: root.kuser.fullName
                    onActivated: {
                        Qt.openUrlExternally(root.folderUrl(StandardPaths.HomeLocation));
                        menu.close();
                    }
                }
                Repeater {
                    model: root.placesModel
                    delegate: MenuEntry {
                        required property int index
                        required property var model
                        text: model.display ?? ""
                        onActivated: menu.trigger(root.placesModel, index)
                    }
                }
                Etched {}
                Repeater {
                    model: root.computerModel
                    delegate: MenuEntry {
                        required property int index
                        required property var model
                        text: model.display ?? ""
                        onActivated: menu.trigger(root.computerModel, index)
                    }
                }
                Etched {}
                Repeater {
                    model: root.settingsModel
                    delegate: MenuEntry {
                        required property int index
                        required property var model
                        text: model.display ?? ""
                        onActivated: menu.trigger(root.settingsModel, index)
                    }
                }
                Etched {}
                Repeater {
                    model: root.runModel
                    delegate: MenuEntry {
                        required property int index
                        required property var model
                        text: model.display ?? ""
                        onActivated: menu.trigger(root.runModel, index)
                    }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.margins: 2
                    spacing: 0

                    QQC2.Button {
                        Layout.fillWidth: true
                        text: i18n("Shut down")
                        onClicked: menu.trigger(root.shutdownModel, 0)
                    }
                    QQC2.Button {
                        id: optionsButton
                        Layout.preferredWidth: height
                        text: "▸"
                        Accessible.name: i18n("Shut down options")
                        onClicked: sessionMenu.openRelative()
                    }
                }
            }
        }
    }

    // Shut down options, like the arrow next to "Shut down"
    component SessionAction: Kicker.SimpleFavoritesModel {}
    readonly property list<QtObject> sessionActions: [
        SessionAction { id: switchUser; favorites: ["switch-user"] },
        SessionAction { id: logOff; favorites: ["logout"] },
        SessionAction { id: lock; favorites: ["lock-screen"] },
        SessionAction { id: restart; favorites: ["reboot"] },
        SessionAction { id: sleep; favorites: ["suspend"] },
        SessionAction { id: hibernate; favorites: ["hibernate"] }
    ]

    PlasmaExtras.Menu {
        id: sessionMenu
        visualParent: optionsButton
        placement: PlasmaExtras.Menu.RightPosedBottomAlignedPopup
        PlasmaExtras.MenuItem { text: i18n("Switch user"); visible: switchUser.count > 0; onClicked: menu.trigger(switchUser, 0) }
        PlasmaExtras.MenuItem { text: i18n("Log off"); visible: logOff.count > 0; onClicked: menu.trigger(logOff, 0) }
        PlasmaExtras.MenuItem { text: i18n("Lock"); visible: lock.count > 0; onClicked: menu.trigger(lock, 0) }
        PlasmaExtras.MenuItem { separator: true }
        PlasmaExtras.MenuItem { text: i18n("Restart"); visible: restart.count > 0; onClicked: menu.trigger(restart, 0) }
        PlasmaExtras.MenuItem { text: i18n("Sleep"); visible: sleep.count > 0; onClicked: menu.trigger(sleep, 0) }
        PlasmaExtras.MenuItem { text: i18n("Hibernate"); visible: hibernate.count > 0; onClicked: menu.trigger(hibernate, 0) }
    }

    function openFolderRoot() {
        folderStack = [root.appsModel];
        folderTitles = [i18n("All Programs")];
    }
}
