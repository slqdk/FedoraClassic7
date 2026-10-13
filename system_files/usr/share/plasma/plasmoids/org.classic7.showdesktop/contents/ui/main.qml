/*
    Show desktop: the narrow button at the right end of the Windows 7 taskbar. A click shows the
    desktop; another click brings the windows back. Classic look: a raised button. Aero and
    Basic: a slim glass strip, and with Aero Peek the desktop shows while the mouse rests on it.

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

    readonly property string look: Plasmoid.configuration.look
    readonly property bool modern: look === "aero" || look === "basic"
    readonly property int buttonWidth: modern ? Math.max(12, Math.round(Kirigami.Units.gridUnit * 0.9))
                                              : Math.max(10, Math.round(Kirigami.Units.gridUnit * 0.75))
    Layout.minimumWidth: buttonWidth
    Layout.maximumWidth: buttonWidth
    Layout.preferredWidth: buttonWidth
    Layout.fillHeight: true

    property bool peeking: false

    function run(cmd) {
        shell.connectSource(cmd + " # " + Date.now());
    }
    function toggle() {
        // KWin's own "Show Desktop" shortcut action toggles, the same as Win+D
        run("for q in qdbus6 qdbus-qt6 qdbus; do command -v $q >/dev/null && exec $q "
            + "org.kde.kglobalaccel /component/kwin org.kde.kglobalaccel.Component.invokeShortcut "
            + "'Show Desktop'; done");
    }
    function showDesktop(on) {
        run("for q in qdbus6 qdbus-qt6 qdbus; do command -v $q >/dev/null && exec $q "
            + "org.kde.KWin /KWin org.kde.KWin.showDesktop " + (on ? "true" : "false") + "; done");
    }

    P5Support.DataSource {
        id: shell
        engine: "executable"
        connectedSources: []
        onNewData: source => disconnectSource(source)
    }

    Timer {
        id: peekTimer
        interval: 500
        onTriggered: {
            root.peeking = true;
            root.showDesktop(true);
        }
    }

    fullRepresentation: MouseArea {
        id: area
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton
        Layout.minimumWidth: root.buttonWidth
        Layout.preferredWidth: root.buttonWidth

        onContainsMouseChanged: {
            if (!root.modern || !Plasmoid.configuration.peek) {
                return;
            }
            if (containsMouse) {
                peekTimer.restart();
            } else {
                peekTimer.stop();
                if (root.peeking) {
                    root.peeking = false;
                    root.showDesktop(false);
                }
            }
        }
        onClicked: {
            peekTimer.stop();
            if (root.peeking) {
                root.peeking = false;      // the desktop stays shown
            } else {
                root.toggle();
            }
        }

        readonly property color face: Kirigami.Theme.backgroundColor
        readonly property color light: Qt.lighter(face, 1.6)
        readonly property color shadow: Qt.darker(face, 1.5)
        readonly property color dark: Qt.darker(face, 3.0)

        // classic 3D bevel: raised, sunken while pressed
        Rectangle {
            visible: !root.modern
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

        // glass strip: a dark and a light line on its left, lit under the mouse
        Item {
            visible: root.modern
            anchors.fill: parent
            Rectangle {
                anchors.fill: parent
                anchors.leftMargin: 2
                visible: area.containsMouse || area.pressed
                gradient: Gradient {
                    GradientStop { position: 0; color: area.pressed ? "#30000000" : "#66FFFFFF" }
                    GradientStop { position: 0.5; color: area.pressed ? "#20000000" : "#33FFFFFF" }
                    GradientStop { position: 1; color: area.pressed ? "#10000000" : "#4DFFFFFF" }
                }
                border.color: root.look === "aero" ? "#59FFFFFF" : "#8098AFCB"
            }
            Rectangle { x: 0; y: 2; width: 1; height: parent.height - 2; color: root.look === "aero" ? "#80000000" : "#8098AFCB" }
            Rectangle { x: 1; y: 2; width: 1; height: parent.height - 2; color: root.look === "aero" ? "#4DFFFFFF" : "#CCFFFFFF" }
        }
    }
}
