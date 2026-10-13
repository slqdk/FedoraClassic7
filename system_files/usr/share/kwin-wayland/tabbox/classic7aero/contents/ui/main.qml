/*
    Alt+Tab in the Windows 7 Aero and Basic looks: a glass panel (the Plasma style's popup
    background) with a preview of every window and its icon, the chosen one lit by a glass box,
    and its title above the previews.

    SPDX-License-Identifier: GPL-2.0-or-later
*/
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.core as PlasmaCore
import org.kde.kirigami as Kirigami
import org.kde.kwin as KWin

KWin.TabBoxSwitcher {
    id: tabBox

    Instantiator {
        active: tabBox.visible
        delegate: PlasmaCore.Dialog {
            location: PlasmaCore.Types.Floating
            visible: true
            flags: Qt.Popup | Qt.X11BypassWindowManagerHint
            x: tabBox.screenGeometry.x + (tabBox.screenGeometry.width - mainItem.width) / 2
            y: tabBox.screenGeometry.y + (tabBox.screenGeometry.height - mainItem.height) / 2

            mainItem: FocusScope {
                id: main
                focus: true
                readonly property int cellW: 160
                readonly property int cellH: 124
                readonly property int perRow: Math.max(1, Math.min(Math.floor(tabBox.screenGeometry.width * 0.85 / cellW),
                                                                   grid.count))
                width: perRow * cellW + 16
                height: title.height + 10 + Math.max(1, Math.ceil(grid.count / perRow)) * cellH + 12

                Text {
                    id: title
                    x: 8
                    y: 6
                    width: main.width - 16
                    height: 26
                    text: grid.currentItem ? grid.currentItem.caption
                                           : i18ndc("kwin", "@info:placeholder no entries in the task switcher", "No open windows")
                    textFormat: Text.PlainText
                    elide: Text.ElideMiddle
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: Kirigami.Theme.textColor
                    style: Text.Raised
                    styleColor: "#80000000"
                    font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.15
                }

                GridView {
                    id: grid
                    x: 8
                    y: title.y + title.height + 6
                    width: main.perRow * main.cellW
                    height: Math.max(1, Math.ceil(count / main.perRow)) * main.cellH
                    cellWidth: main.cellW
                    cellHeight: main.cellH
                    interactive: false
                    keyNavigationWraps: true
                    focus: true
                    model: tabBox.model
                    currentIndex: tabBox.currentIndex
                    highlightMoveDuration: 0
                    highlight: Rectangle {
                        width: main.cellW
                        height: main.cellH
                        radius: 5
                        border.color: "#B3FFFFFF"
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#59FFFFFF" }
                            GradientStop { position: 0.5; color: "#26FFFFFF" }
                            GradientStop { position: 1; color: "#40FFFFFF" }
                        }
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: 1
                            radius: 4
                            color: "transparent"
                            border.color: "#80000000"
                        }
                    }
                    delegate: Item {
                        id: cell
                        required property int index
                        required property var model
                        readonly property string caption: model.caption
                        width: main.cellW
                        height: main.cellH
                        Item {
                            anchors.fill: parent
                            anchors.margins: 10
                            anchors.bottomMargin: 16
                            KWin.WindowThumbnail {
                                anchors.fill: parent
                                wId: cell.model.windowId
                            }
                        }
                        Kirigami.Icon {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 4
                            width: 32
                            height: 32
                            source: cell.model.icon
                            animated: false
                        }
                        TapHandler {
                            onTapped: {
                                if (cell.index === grid.currentIndex) {
                                    tabBox.model.activate(cell.index);
                                } else {
                                    grid.currentIndex = cell.index;
                                }
                            }
                        }
                    }
                    onCurrentIndexChanged: tabBox.currentIndex = currentIndex
                    Connections {
                        target: tabBox
                        function onCurrentIndexChanged() { grid.currentIndex = tabBox.currentIndex; }
                    }
                }

                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Left) {
                        grid.moveCurrentIndexLeft();
                    } else if (event.key === Qt.Key_Right) {
                        grid.moveCurrentIndexRight();
                    } else if (event.key === Qt.Key_Up) {
                        grid.moveCurrentIndexUp();
                    } else if (event.key === Qt.Key_Down) {
                        grid.moveCurrentIndexDown();
                    }
                }
            }
        }
    }
}
