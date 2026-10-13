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

    The look follows Plasmoid.configuration.look: "classic" (as drawn above), "aero" (a white
    column and the search box on glass, white text on the glass at the right, the account
    picture on top) or "basic" (the same layout on light blue).

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
    readonly property string look: Plasmoid.configuration.look
    readonly property bool modern: look === "aero" || look === "basic"
    readonly property bool glass: look === "aero"
    readonly property string rightStyle: glass ? "glass" : (modern ? "light" : "classic")
    readonly property int bigIcon: Plasmoid.configuration.largeIcons ? Kirigami.Units.iconSizes.medium   // 32 px like Windows
                                                                      : Kirigami.Units.iconSizes.small
    readonly property int smallIcon: Kirigami.Units.iconSizes.small     // 16 px in All Programs

    // All Programs navigation: a stack of folder models, [] = not in All Programs
    property var folderStack: []
    property var folderTitles: []
    readonly property bool inPrograms: folderStack.length > 0
    readonly property bool searching: searchField.text.length > 0
    readonly property var searchResults: root.runnerModel.count > 0 ? root.runnerModel.modelForRow(0) : null

    // Jump list shown in the right column: "" = none
    property string jumpKey: ""
    property string jumpTitle: ""
    readonly property var jump: jumpKey !== "" && root.jumpLists[jumpKey] ? root.jumpLists[jumpKey]
                                                                         : ({ recent: [], tasks: [] })
    function showJump(key, title) {
        jumpKey = (searching || inPrograms || !Plasmoid.configuration.showJumpLists) ? "" : key;
        jumpTitle = title;
    }

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
        jumpKey = "";
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
        property bool inRight: false     // in the right column (glass in Aero)
        Layout.fillWidth: true
        Layout.leftMargin: 6
        Layout.rightMargin: 6
        Layout.topMargin: 3
        Layout.bottomMargin: 3
        implicitHeight: 2
        Rectangle {
            width: parent.width; height: 1; y: 0
            color: !menu.modern ? Qt.darker(Kirigami.Theme.backgroundColor, 1.45)
                   : (parent.inRight && menu.glass ? "#59000000" : (parent.inRight ? "#A9BDD6" : "#DCE3EA"))
        }
        Rectangle {
            width: parent.width; height: 1; y: 1
            color: !menu.modern ? Qt.lighter(Kirigami.Theme.backgroundColor, 1.6)
                   : (parent.inRight && menu.glass ? "#33FFFFFF" : "#FFFFFF")
        }
    }

    // Aero and Basic: the Shut down button and its arrow, one glass (or light) button in two parts
    component PowerPart: MouseArea {
        id: part
        property string label: ""
        property bool first: true
        hoverEnabled: true
        implicitHeight: 24
        implicitWidth: label.length > 0 ? caption.implicitWidth + 24 : 20
        Rectangle {
            anchors.fill: parent
            anchors.leftMargin: part.first ? 0 : -1
            radius: 3
            border.color: menu.glass ? "#B3000000" : "#6B84A3"
            gradient: Gradient {
                GradientStop { position: 0; color: part.pressed ? "#3A6E9E" : (part.containsMouse ? (menu.glass ? "#99D8F4FF" : "#F1F8FF") : (menu.glass ? "#59FFFFFF" : "#FBFDFF")) }
                GradientStop { position: 0.5; color: part.pressed ? "#2B5C8C" : (part.containsMouse ? (menu.glass ? "#6699D8FF" : "#DCEBFA") : (menu.glass ? "#26FFFFFF" : "#E5EEF8")) }
                GradientStop { position: 0.51; color: part.pressed ? "#1D4A78" : (part.containsMouse ? (menu.glass ? "#552C8FD8" : "#C5DDF6") : (menu.glass ? "#0DFFFFFF" : "#D6E3F1")) }
                GradientStop { position: 1; color: part.pressed ? "#2F6AA6" : (part.containsMouse ? (menu.glass ? "#7745B8FF" : "#D9E9FA") : (menu.glass ? "#2BFFFFFF" : "#E3ECF6")) }
            }
            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 2
                color: "transparent"
                border.color: menu.glass ? "#73FFFFFF" : "#CCFFFFFF"
            }
        }
        Text {
            id: caption
            anchors.centerIn: parent
            text: part.label.length > 0 ? part.label : "▸"
            color: menu.glass || part.pressed ? "#FFFFFF" : "#000000"
            style: menu.glass ? Text.Raised : Text.Normal
            styleColor: "#80000000"
            font.family: Kirigami.Theme.defaultFont.family
            font.pointSize: Kirigami.Theme.defaultFont.pointSize
        }
    }

    PlasmaExtras.Menu {
        id: pinMenu
        property string favoriteId: ""
        property string url: ""          // the program's .desktop file
        readonly property bool program: url.endsWith(".desktop")
        PlasmaExtras.MenuItem {
            text: root.isOnTaskbar(pinMenu.url) ? i18n("Unpin from Taskbar") : i18n("Pin to Taskbar")
            icon: root.isOnTaskbar(pinMenu.url) ? "window-unpin" : "window-pin"
            visible: pinMenu.program
            onClicked: root.pinToTaskbar(pinMenu.url, !root.isOnTaskbar(pinMenu.url))
        }
        PlasmaExtras.MenuItem {
            text: root.isPinned(pinMenu.favoriteId) ? i18n("Unpin from Start Menu") : i18n("Pin to Start Menu")
            icon: root.isPinned(pinMenu.favoriteId) ? "window-unpin" : "window-pin"
            onClicked: root.isPinned(pinMenu.favoriteId) ? root.unpin(pinMenu.favoriteId) : root.pin(pinMenu.favoriteId)
        }
    }

    // ---- layout ---------------------------------------------------------------------------
    RowLayout {
        anchors.fill: parent
        spacing: menu.modern ? 6 : 0

        // Left column: white, like a list view (Aero, Basic: a white pane with the search box under it)
        Rectangle {
            Layout.preferredWidth: menu.leftWidth
            Layout.fillHeight: true
            Kirigami.Theme.colorSet: Kirigami.Theme.View
            Kirigami.Theme.inherit: false
            color: menu.modern ? "transparent" : Kirigami.Theme.backgroundColor
            border.color: Qt.darker(Kirigami.Theme.backgroundColor, 1.6)
            border.width: menu.modern ? 0 : 1

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: menu.modern ? 0 : 3
                spacing: menu.modern ? 6 : 0

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: menu.modern ? Kirigami.Theme.backgroundColor : "transparent"
                    radius: menu.modern ? 4 : 0
                    border.width: menu.modern ? 1 : 0
                    border.color: menu.glass ? "#A6000000" : "#8EA1B8"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: menu.modern ? 4 : 0
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
                                jumpable: Plasmoid.configuration.showJumpLists
                                entryStyle: menu.modern ? "light" : "classic"
                                Layout.preferredHeight: contentHeight
                                Layout.maximumHeight: contentHeight
                            }
                            Etched { visible: root.pinnedModel.count > 0 && Plasmoid.configuration.showRecentPrograms }
                            EntryList {
                                startMenu: menu
                                contextMenu: pinMenu
                                id: recentList
                                model: Plasmoid.configuration.showRecentPrograms ? root.recentModel : null
                                pinnable: true
                                jumpable: Plasmoid.configuration.showJumpLists
                                scrollable: false
                                maxRows: Plasmoid.configuration.recentCount
                                entryStyle: menu.modern ? "light" : "classic"
                                // like Windows: no pinned programs and no right-column items in the recent list
                                hiddenIds: root.pinnedKeys.concat(["classic7-control-panel", "classic7-games", "classic7-devices",
                                           "classic7-default-programs", "classic7-help", "classic7-run",
                                           "classic7-computer", "systemsettings", "classic7-logoff", "classic7-restart",
                                           "classic7-shutdown"])
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
                                entryStyle: menu.modern ? "light" : "classic"
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
                                entryStyle: menu.modern ? "light" : "classic"
                                Layout.fillHeight: true
                            }
                        }

                        Etched {}

                        MenuEntry {
                            text: menu.inPrograms ? i18n("Back") : i18n("All Programs")
                            arrow: !menu.inPrograms
                            backArrow: menu.inPrograms
                            bold: false
                            style: menu.modern ? "light" : "classic"
                            visible: !menu.searching
                            onActivated: {
                                if (menu.inPrograms) {
                                    menu.back();
                                } else {
                                    menu.openFolderRoot();
                                }
                            }
                        }
                    }
                }

                QQC2.TextField {
                    id: searchField
                    Layout.fillWidth: true
                    Layout.margins: menu.modern ? 2 : 4
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

        // Right column: grey and text only (Classic), white text on glass (Aero), light blue (Basic)
        Rectangle {
            Layout.preferredWidth: menu.rightWidth
            Layout.fillHeight: true
            Kirigami.Theme.colorSet: Kirigami.Theme.Window
            Kirigami.Theme.inherit: false
            color: menu.glass ? "transparent" : (menu.modern ? "#DCE7F4" : Kirigami.Theme.backgroundColor)
            radius: menu.modern ? 4 : 0
            border.width: menu.look === "basic" ? 1 : 0
            border.color: "#A9BDD6"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 4
                spacing: 0

                // Aero, Basic: the account picture on top of the column
                Item {
                    visible: menu.modern
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 2
                    Layout.bottomMargin: 4
                    implicitWidth: 56
                    implicitHeight: 56
                    Rectangle {
                        anchors.fill: parent
                        radius: 6
                        border.color: menu.glass ? "#B3000000" : "#6B84A3"
                        gradient: Gradient {
                            GradientStop { position: 0; color: menu.glass ? "#88FFFFFF" : "#FFFFFF" }
                            GradientStop { position: 1; color: menu.glass ? "#33FFFFFF" : "#D5E3F3" }
                        }
                    }
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 4
                        color: "#FFFFFF"
                        border.color: "#80000000"
                        clip: true
                        Image {
                            id: face
                            anchors.fill: parent
                            anchors.margins: 1
                            source: root.kuser.faceIconUrl
                            sourceSize.width: 96
                            sourceSize.height: 96
                            fillMode: Image.PreserveAspectCrop
                            smooth: true
                            visible: status === Image.Ready
                        }
                        Kirigami.Icon {
                            anchors.fill: parent
                            anchors.margins: 3
                            source: "user-identity"
                            visible: face.status !== Image.Ready
                        }
                    }
                }

                ColumnLayout {
                    visible: menu.jumpKey === ""
                    Layout.fillWidth: true
                    spacing: 0

                    MenuEntry {
                        visible: Plasmoid.configuration.showPersonalFolder
                        text: root.kuser.loginName
                        bold: true
                        style: menu.rightStyle
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
                            style: menu.rightStyle
                            onActivated: menu.trigger(root.placesModel, index)
                        }
                    }
                    Etched {
                        inRight: true
                        visible: (root.placesModel.count > 0 || Plasmoid.configuration.showPersonalFolder)
                                 && (root.computerModel.count + root.settingsModel.count + root.runModel.count) > 0
                    }
                    Repeater {
                        model: root.computerModel
                        delegate: MenuEntry {
                            required property int index
                            required property var model
                            text: model.display ?? ""
                            style: menu.rightStyle
                            onActivated: menu.trigger(root.computerModel, index)
                        }
                    }
                    Etched {
                        inRight: true
                        visible: root.computerModel.count > 0 && (root.settingsModel.count + root.runModel.count) > 0
                    }
                    Repeater {
                        model: root.settingsModel
                        delegate: MenuEntry {
                            required property int index
                            required property var model
                            text: model.display ?? ""
                            style: menu.rightStyle
                            onActivated: menu.trigger(root.settingsModel, index)
                        }
                    }
                    Etched {
                        inRight: true
                        visible: root.settingsModel.count > 0 && root.runModel.count > 0
                    }
                    Repeater {
                        model: root.runModel
                        delegate: MenuEntry {
                            required property int index
                            required property var model
                            text: model.display ?? ""
                            style: menu.rightStyle
                            onActivated: menu.trigger(root.runModel, index)
                        }
                    }
                }

                // Jump list: the program's recent documents and tasks, like Windows 7
                ColumnLayout {
                    visible: menu.jumpKey !== ""
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    Text {
                        Layout.leftMargin: 6
                        Layout.topMargin: 2
                        Layout.bottomMargin: 2
                        visible: (menu.jump.recent || []).length > 0
                        text: i18n("Recent")
                        font.bold: true
                        color: Kirigami.Theme.textColor
                    }
                    Repeater {
                        model: menu.jump.recent || []
                        delegate: MenuEntry {
                            required property int index
                            required property var modelData
                            text: modelData.name
                            toolTip: modelData.path
                            iconSource: modelData.icon
                            iconSize: menu.smallIcon
                            style: menu.rightStyle
                            onActivated: {
                                root.runJump("open", menu.jumpKey, index);
                                menu.close();
                            }
                        }
                    }
                    Etched { inRight: true; visible: (menu.jump.recent || []).length > 0 && (menu.jump.tasks || []).length > 0 }
                    Text {
                        Layout.leftMargin: 6
                        Layout.topMargin: 2
                        Layout.bottomMargin: 2
                        visible: (menu.jump.tasks || []).length > 0
                        text: i18n("Tasks")
                        font.bold: true
                        color: Kirigami.Theme.textColor
                    }
                    Repeater {
                        model: menu.jump.tasks || []
                        delegate: MenuEntry {
                            required property int index
                            required property var modelData
                            text: modelData.name
                            style: menu.rightStyle
                            onActivated: {
                                root.runJump("task", menu.jumpKey, index);
                                menu.close();
                            }
                        }
                    }
                    Item { Layout.fillHeight: true }
                }

                Item { Layout.fillHeight: true }

                RowLayout {
                    visible: !menu.modern
                    Layout.fillWidth: true
                    Layout.margins: 2
                    spacing: 0

                    QQC2.Button {
                        Layout.fillWidth: true
                        text: menu.powerText
                        onClicked: menu.power()
                    }
                    QQC2.Button {
                        id: optionsButton
                        Layout.preferredWidth: height
                        text: "▸"
                        Accessible.name: i18n("Shut down options")
                        onClicked: {
                            sessionMenu.visualParent = optionsButton;
                            sessionMenu.openRelative();
                        }
                    }
                }
                RowLayout {
                    visible: menu.modern
                    Layout.alignment: Qt.AlignRight
                    Layout.margins: 2
                    spacing: 0

                    PowerPart {
                        label: menu.powerText
                        onClicked: menu.power()
                    }
                    PowerPart {
                        id: optionsArrow
                        first: false
                        Accessible.name: i18n("Shut down options")
                        onClicked: {
                            sessionMenu.visualParent = optionsArrow;
                            sessionMenu.openRelative();
                        }
                    }
                }
            }
        }
    }

    // What the power button does (Taskbar and Start Menu Properties > Start Menu)
    readonly property var powerTexts: ({ "shutdown": i18n("Shut down"), "switch-user": i18n("Switch user"),
                                         "logout": i18n("Log off"), "lock": i18n("Lock"), "reboot": i18n("Restart"),
                                         "suspend": i18n("Sleep"), "hibernate": i18n("Hibernate") })
    readonly property string powerText: powerTexts[Plasmoid.configuration.powerAction] || i18n("Shut down")
    function power() {
        switch (Plasmoid.configuration.powerAction) {
        case "switch-user": trigger(switchUser, 0); break;
        case "logout": trigger(logOff, 0); break;
        case "lock": trigger(lock, 0); break;
        case "reboot": trigger(restart, 0); break;
        case "suspend": trigger(sleep, 0); break;
        case "hibernate": trigger(hibernate, 0); break;
        default: trigger(root.shutdownModel, 0);
        }
    }

    // Shut down options, like the arrow next to "Shut down"
    component SessionAction: Kicker.SimpleFavoritesModel {}
    readonly property list<QtObject> sessionActions: [
        SessionAction { id: switchUser; favorites: ["switch-user"] },
        SessionAction { id: logOff; favorites: ["classic7-logoff.desktop"]; Component.onCompleted: if (count === 0) favorites = ["logout"] },
        SessionAction { id: lock; favorites: ["lock-screen"] },
        SessionAction { id: restart; favorites: ["classic7-restart.desktop"]; Component.onCompleted: if (count === 0) favorites = ["reboot"] },
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
