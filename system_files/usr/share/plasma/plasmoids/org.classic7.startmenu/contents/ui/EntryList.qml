/*
    A list of Start menu entries from one Kicker model.
    SPDX-License-Identifier: GPL-2.0-or-later
*/
pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2

ListView {
    id: list
    required property var startMenu   // the StartMenu (open folders, trigger, close)
    required property var contextMenu // context menu for pin/unpin
    property int iconSize: list.startMenu.bigIcon
    property bool folders: false          // folders open in place (All Programs)
    property bool pinnable: false         // right-click: pin to / unpin from Start menu
    Layout.fillWidth: true
    clip: true
    interactive: contentHeight > height
    boundsBehavior: Flickable.StopAtBounds
    keyNavigationEnabled: true
    highlightFollowsCurrentItem: false
    currentIndex: -1
    QQC2.ScrollBar.vertical: QQC2.ScrollBar { policy: list.contentHeight > list.height ? QQC2.ScrollBar.AsNeeded : QQC2.ScrollBar.AlwaysOff }

    delegate: MenuEntry {
        id: row
        required property int index
        required property var model
        width: ListView.view.width
        visible: !(model.isSeparator ?? false)
        height: visible ? implicitHeight : 0
        text: model.display ?? ""
        iconSource: model.decoration
        iconSize: list.iconSize
        arrow: list.folders && (model.hasChildren ?? false)
        current: ListView.isCurrentItem && list.activeFocus
        onActivated: {
            if (list.folders && (model.hasChildren ?? false)) {
                list.startMenu.openFolder(list.model, index, model.display);
            } else {
                list.startMenu.trigger(list.model, index);
            }
        }
        onContextMenuRequested: (x, y) => {
            if (!list.pinnable || !model.favoriteId) {
                return;
            }
            list.contextMenu.favoriteId = model.favoriteId;
            list.contextMenu.visualParent = row;
            list.contextMenu.open(x, y);
        }
    }
    Keys.onReturnPressed: {
        if (currentItem) {
            currentItem.activated();
        }
    }
}
