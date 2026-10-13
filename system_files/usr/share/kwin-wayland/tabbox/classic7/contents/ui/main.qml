/*
    Alt+Tab in the Windows 7 Classic theme: a raised grey box with the programs' icons,
    the chosen one framed, and its window title in a sunken field underneath.

    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts
import QtQuick.Window
import org.kde.kirigami as Kirigami
import org.kde.kwin as KWin

KWin.TabBoxSwitcher {
    id: tabBox
    currentIndex: (instantiator.object as SwitcherWindow)?.currentIndex ?? currentIndex

    Instantiator {
        id: instantiator
        active: tabBox.visible
        delegate: SwitcherWindow {}
    }

    component Bevel: Item {
        property bool sunken: false
        property color face: Kirigami.Theme.backgroundColor
        readonly property color light: Qt.lighter(face, 1.6)
        readonly property color shadow: Qt.darker(face, 1.5)
        readonly property color dark: Qt.darker(face, 3.2)
        Rectangle { anchors.fill: parent; color: parent.face }
        Rectangle { x: 0; y: 0; width: parent.width; height: 1; color: parent.sunken ? parent.shadow : parent.face }
        Rectangle { x: 0; y: 0; width: 1; height: parent.height; color: parent.sunken ? parent.shadow : parent.face }
        Rectangle { x: 1; y: 1; width: parent.width - 2; height: 1; color: parent.sunken ? parent.dark : parent.light }
        Rectangle { x: 1; y: 1; width: 1; height: parent.height - 2; color: parent.sunken ? parent.dark : parent.light }
        Rectangle { x: 0; y: parent.height - 1; width: parent.width; height: 1; color: parent.sunken ? parent.light : parent.dark }
        Rectangle { x: parent.width - 1; y: 0; width: 1; height: parent.height; color: parent.sunken ? parent.light : parent.dark }
        Rectangle { x: 1; y: parent.height - 2; width: parent.width - 2; height: 1; color: parent.sunken ? parent.face : parent.shadow }
        Rectangle { x: parent.width - 2; y: 1; width: 1; height: parent.height - 2; color: parent.sunken ? parent.face : parent.shadow }
    }

    component SwitcherWindow: Window {
        id: win
        property alias currentIndex: icons.currentIndex
        readonly property int cell: 43
        readonly property int perRow: Math.max(1, Math.min(7, icons.count))
        flags: Qt.Popup | Qt.X11BypassWindowManagerHint | Qt.FramelessWindowHint
        color: "transparent"
        visible: tabBox.visible
        width: perRow * cell + 2 * 14
        height: Math.max(1, Math.ceil(icons.count / perRow)) * cell + 14 + 10 + 26 + 14
        x: tabBox.screenGeometry.x + (tabBox.screenGeometry.width - width) / 2
        y: tabBox.screenGeometry.y + (tabBox.screenGeometry.height - height) / 2

        Kirigami.Theme.colorSet: Kirigami.Theme.Window
        Kirigami.Theme.inherit: false

        Bevel { anchors.fill: parent }

        GridView {
            id: icons
            x: 14
            y: 14
            width: win.perRow * win.cell
            height: Math.max(1, Math.ceil(count / win.perRow)) * win.cell
            cellWidth: win.cell
            cellHeight: win.cell
            interactive: false
            keyNavigationWraps: true
            focus: true
            model: tabBox.model
            currentIndex: tabBox.currentIndex
            highlightMoveDuration: 0
            highlight: Rectangle {
                width: win.cell
                height: win.cell
                color: "transparent"
                border.color: Kirigami.Theme.highlightColor
                border.width: 2
            }
            delegate: Item {
                required property int index
                required property var model
                readonly property string caption: model.caption
                width: win.cell
                height: win.cell
                Kirigami.Icon {
                    anchors.centerIn: parent
                    width: 32
                    height: 32
                    source: model.icon
                    opacity: model.minimized ? 0.7 : 1
                    animated: false
                }
                TapHandler {
                    onTapped: {
                        if (index === icons.currentIndex) {
                            tabBox.model.activate(index);
                        } else {
                            icons.currentIndex = index;
                        }
                    }
                }
            }
            Connections {
                target: tabBox
                function onCurrentIndexChanged() { icons.currentIndex = tabBox.currentIndex; }
            }
        }

        Bevel {
            sunken: true
            x: 14
            y: icons.y + icons.height + 10
            width: win.width - 28
            height: 26
            face: Kirigami.Theme.backgroundColor
            Text {
                anchors.fill: parent
                anchors.margins: 4
                text: icons.currentItem ? icons.currentItem.caption : i18ndc("kwin", "@info:placeholder no entries in the task switcher", "No open windows")
                textFormat: Text.PlainText
                elide: Text.ElideMiddle
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Kirigami.Theme.textColor
                font: Kirigami.Theme.defaultFont
            }
        }

        Item {
            anchors.fill: parent
            focus: true
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Left) {
                    icons.moveCurrentIndexLeft();
                } else if (event.key === Qt.Key_Right) {
                    icons.moveCurrentIndexRight();
                } else if (event.key === Qt.Key_Up) {
                    icons.moveCurrentIndexUp();
                } else if (event.key === Qt.Key_Down) {
                    icons.moveCurrentIndexDown();
                }
            }
        }
    }
}
