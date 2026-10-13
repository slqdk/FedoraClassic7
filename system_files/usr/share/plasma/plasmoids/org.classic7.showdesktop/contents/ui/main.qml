/*
    Show desktop: the narrow raised button at the right end of the Windows 7 taskbar
    (Classic theme). A click shows the desktop; another click brings the windows back.

    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts

import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    preferredRepresentation: fullRepresentation
    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    Plasmoid.icon: "user-desktop"
    toolTipMainText: i18n("Show desktop")
    toolTipSubText: ""

    readonly property int buttonWidth: Math.max(10, Math.round(Kirigami.Units.gridUnit * 0.75))
    Layout.minimumWidth: buttonWidth
    Layout.maximumWidth: buttonWidth
    Layout.preferredWidth: buttonWidth
    Layout.fillHeight: true

    function toggle() {
        // KWin's own "Show Desktop" shortcut action toggles, the same as Win+D
        shell.connectSource("for q in qdbus6 qdbus-qt6 qdbus; do command -v $q >/dev/null && exec $q "
                            + "org.kde.kglobalaccel /component/kwin org.kde.kglobalaccel.Component.invokeShortcut "
                            + "'Show Desktop'; done # " + Date.now());
    }

    P5Support.DataSource {
        id: shell
        engine: "executable"
        connectedSources: []
        onNewData: source => disconnectSource(source)
    }

    fullRepresentation: MouseArea {
        id: area
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        onClicked: root.toggle()
        Layout.minimumWidth: root.buttonWidth
        Layout.preferredWidth: root.buttonWidth

        readonly property color face: Kirigami.Theme.backgroundColor
        readonly property color light: Qt.lighter(face, 1.6)
        readonly property color shadow: Qt.darker(face, 1.5)
        readonly property color dark: Qt.darker(face, 3.0)

        // classic 3D bevel: raised, sunken while pressed
        Rectangle {
            anchors.fill: parent
            anchors.topMargin: 2
            anchors.bottomMargin: 1
            color: area.face
            Rectangle { x: 0; y: 0; width: parent.width; height: 1; color: area.pressed ? area.dark : area.light }
            Rectangle { x: 0; y: 0; width: 1; height: parent.height; color: area.pressed ? area.dark : area.light }
            Rectangle { x: 0; y: parent.height - 1; width: parent.width; height: 1; color: area.pressed ? area.light : area.dark }
            Rectangle { x: parent.width - 1; y: 0; width: 1; height: parent.height; color: area.pressed ? area.light : area.dark }
            Rectangle { x: 1; y: parent.height - 2; width: parent.width - 2; height: 1; color: area.pressed ? area.face : area.shadow }
            Rectangle { x: parent.width - 2; y: 1; width: 1; height: parent.height - 2; color: area.pressed ? area.face : area.shadow }
        }
    }
}
