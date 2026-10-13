/*
    One row of the Start menu: icon + text. The highlight follows the look: navy like a
    classic menu, Explorer's light blue in the white column of Aero and Basic, a glass
    button in Aero's right column.
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts

import org.kde.kirigami as Kirigami

MouseArea {
    id: entry

    property string text: ""
    property var iconSource: null
    property int iconSize: 0            // 0 = text only
    property bool bold: false
    property bool arrow: false          // "▸" at the right edge (All Programs, folders)
    property bool backArrow: false      // "◂" at the left edge (Back)
    property bool current: false        // keyboard highlight
    property string toolTip: ""
    property string dragUrl: ""         // a program's .desktop file: drag it to the taskbar
    property bool jumpArrow: false      // the program has a jump list (recent documents, tasks)
    property string style: "classic"    // classic, light (white column) or glass (Aero's right column)

    signal activated()
    signal contextMenuRequested(real x, real y)
    signal jumpRequested()              // the mouse rested on the entry: show (or hide) its jump list

    Timer {
        id: hoverTimer
        interval: 450
        onTriggered: entry.jumpRequested()
    }
    onContainsMouseChanged: containsMouse ? hoverTimer.restart() : hoverTimer.stop()

    readonly property bool highlighted: containsMouse || current

    implicitHeight: Math.max(iconSize + 4, label.implicitHeight + 6)
    Layout.fillWidth: true
    hoverEnabled: true
    acceptedButtons: Qt.LeftButton | Qt.RightButton
    cursorShape: Qt.ArrowCursor

    drag.target: dragUrl.endsWith(".desktop") ? dragProxy : null
    drag.threshold: 8
    onReleased: { dragProxy.x = 0; dragProxy.y = 0; }

    Item {
        id: dragProxy
        width: 1
        height: 1
        Drag.active: entry.drag.active
        Drag.dragType: Drag.Automatic
        Drag.supportedActions: Qt.CopyAction | Qt.LinkAction
        Drag.mimeData: ({ "text/uri-list": entry.dragUrl + "\r\n" })
        Drag.imageSource: entry.iconSource && typeof entry.iconSource === "string" && entry.iconSource.indexOf("/") === 0
                          ? "file://" + entry.iconSource : ""
    }

    onClicked: mouse => {
        if (mouse.button === Qt.RightButton) {
            entry.contextMenuRequested(mouse.x, mouse.y);
        } else {
            entry.activated();
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 2
        anchors.rightMargin: 2
        color: Kirigami.Theme.highlightColor
        visible: entry.highlighted && entry.style === "classic"
    }

    // Explorer's selection: light blue, rounded, with a border
    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 2
        anchors.rightMargin: 2
        radius: 3
        visible: entry.highlighted && entry.style === "light"
        border.color: "#7DA2CE"
        gradient: Gradient {
            GradientStop { position: 0; color: "#DCEBFC" }
            GradientStop { position: 1; color: "#C1DBFC" }
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 2
            color: "transparent"
            border.color: "#99FFFFFF"
        }
    }

    // a glass button on Aero's right column
    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 1
        anchors.rightMargin: 1
        radius: 3
        visible: entry.highlighted && entry.style === "glass"
        border.color: "#99000000"
        gradient: Gradient {
            GradientStop { position: 0; color: "#55FFFFFF" }
            GradientStop { position: 0.5; color: "#28FFFFFF" }
            GradientStop { position: 0.51; color: "#14FFFFFF" }
            GradientStop { position: 1; color: "#30FFFFFF" }
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 2
            color: "transparent"
            border.color: "#80FFFFFF"
        }
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        spacing: 6

        Text {
            visible: entry.backArrow
            text: "◂"
            color: entry.highlighted && entry.style === "classic" ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
            font.pixelSize: label.font.pixelSize
        }

        Kirigami.Icon {
            visible: entry.iconSize > 0
            source: entry.iconSource
            Layout.preferredWidth: entry.iconSize
            Layout.preferredHeight: entry.iconSize
            Layout.alignment: Qt.AlignVCenter
            selected: false
            animated: false
        }

        Text {
            id: label
            Layout.fillWidth: true
            text: entry.text
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            font.bold: entry.bold
            font.family: Kirigami.Theme.defaultFont.family
            font.pointSize: Kirigami.Theme.defaultFont.pointSize
            color: entry.highlighted && entry.style === "classic" ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
            textFormat: Text.PlainText
            // white text on glass gets a soft dark edge so it reads on any background
            style: entry.style === "glass" ? Text.Raised : Text.Normal
            styleColor: "#66000000"
        }

        Text {
            visible: entry.arrow || entry.jumpArrow
            text: "▸"
            color: entry.highlighted && entry.style === "classic" ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
            font.pixelSize: label.font.pixelSize + 2
        }
    }
}
