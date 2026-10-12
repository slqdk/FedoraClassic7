/*
    One row of the Start menu: icon + text, navy highlight like a classic menu.
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

    signal activated()
    signal contextMenuRequested(real x, real y)

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
        visible: entry.highlighted
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        spacing: 6

        Text {
            visible: entry.backArrow
            text: "◂"
            color: entry.highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
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
            color: entry.highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
            textFormat: Text.PlainText
        }

        Text {
            visible: entry.arrow
            text: "▸"
            color: entry.highlighted ? Kirigami.Theme.highlightedTextColor : Kirigami.Theme.textColor
            font.pixelSize: label.font.pixelSize + 2
        }
    }
}
