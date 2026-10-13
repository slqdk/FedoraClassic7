/*
    The Start button: a raised classic button or the round orb, drawn pressed while the menu is
    open; the orb also glows under the mouse (a -hover.svg next to the image).
    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts

import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore

MouseArea {
    id: button

    readonly property string imagePath: Plasmoid.configuration.buttonImage
    readonly property string pressedPath: imagePath.replace(/\.svg$/, "-pressed.svg")
    readonly property string hoverPath: imagePath.replace(/\.svg$/, "-hover.svg")
    readonly property bool down: root.expanded || (button.pressed && button.containsMouse)
    readonly property bool vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
    // keep the image's aspect ratio at the panel's thickness
    readonly property real ratio: normal.implicitHeight > 0 ? normal.implicitWidth / normal.implicitHeight : 58 / 24

    property bool wasExpanded: false

    Layout.minimumWidth: vertical ? -1 : Math.round(height * ratio)
    Layout.maximumWidth: vertical ? -1 : Math.round(height * ratio)
    Layout.minimumHeight: vertical ? Math.round(width / ratio) : -1
    Layout.maximumHeight: vertical ? Math.round(width / ratio) : -1

    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: i18n("Start")
    Accessible.role: Accessible.Button

    onPressed: wasExpanded = root.expanded
    onClicked: root.expanded = !wasExpanded
    Keys.onReturnPressed: root.expanded = !root.expanded
    Keys.onSpacePressed: root.expanded = !root.expanded

    Image {
        id: normal
        anchors.fill: parent
        source: "file://" + button.imagePath
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: false
        sourceSize.height: Math.max(1, button.height)
        visible: !pressedImage.visible && !hoverImage.visible
    }

    Image {
        id: hoverImage
        anchors.fill: parent
        source: "file://" + button.hoverPath
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: false
        sourceSize.height: Math.max(1, button.height)
        visible: status === Image.Ready && button.containsMouse && !button.down
    }

    Image {
        id: pressedImage
        anchors.fill: parent
        source: "file://" + button.pressedPath
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: false
        sourceSize.height: Math.max(1, button.height)
        visible: status === Image.Ready && button.down
    }
}
