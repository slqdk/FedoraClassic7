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
    property bool scrollable: true        // false: show what fits, no scroll bar (recent programs)
    property var hiddenIds: []            // favorite ids not to show (normalised, see key())
    property bool jumpable: false         // programs show their jump list when the mouse rests on them
    property string entryStyle: "classic" // the highlight: classic or light (see MenuEntry)

    function key(id) {
        return String(id || "").replace(/^applications:/, "").replace(/\.desktop$/, "").toLowerCase();
    }
    Layout.fillWidth: true
    clip: true
    interactive: scrollable && contentHeight > height
    boundsBehavior: Flickable.StopAtBounds
    keyNavigationEnabled: true
    highlightFollowsCurrentItem: false
    currentIndex: -1
    QQC2.ScrollBar.vertical: QQC2.ScrollBar { policy: list.scrollable && list.contentHeight > list.height ? QQC2.ScrollBar.AsNeeded : QQC2.ScrollBar.AlwaysOff }

    delegate: MenuEntry {
        id: row
        required property int index
        required property var model
        width: ListView.view.width
        visible: !(model.isSeparator ?? false) && list.hiddenIds.indexOf(list.key(model.favoriteId)) === -1
        height: visible ? implicitHeight : 0
        // without a scroll bar, rows that don't fit completely are left out
        opacity: (!list.scrollable && y + height > list.height) ? 0 : 1
        text: model.display ?? ""
        iconSource: model.decoration
        iconSize: list.iconSize
        style: list.entryStyle
        arrow: list.folders && (model.hasChildren ?? false)
        current: ListView.isCurrentItem && list.activeFocus
        // programs can be dragged to the Quick Launch icons on the taskbar (or the desktop)
        dragUrl: (model.hasChildren ?? false) ? "" : String(model.url ?? "")
        jumpArrow: list.jumpable && root.hasJump(list.key(model.favoriteId))
        onJumpRequested: {
            if (list.jumpable) {
                list.startMenu.showJump(jumpArrow ? list.key(model.favoriteId) : "", model.display ?? "");
            }
        }
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
            list.contextMenu.url = String(model.url ?? "");
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
