/*
    Classic 7's "Logging off..." / "Shutting down..." / "Restarting..." screen, shown by KWin itself
    (loaded as a KWin script by classic7-goodbye), so it stays up until the session has ended.
    It appears once the programs' own windows are gone: until then their "Save changes?" questions
    must stay visible.
*/
import QtQuick
import QtQuick.Window
import QtQml
import org.kde.kwin
import "file:///usr/share/sddm/themes/classic7" as Logon

Item {
    id: root
    property string message: "Shutting down..."
    property bool shown: false

    function appWindows() {
        let n = 0;
        const list = Workspace.windowList();
        for (let i = 0; i < list.length; i++) {
            const w = list[i];
            if (!w || w.deleted || !w.managed || w.specialWindow || w.popupWindow) {
                continue;
            }
            if (!(w.normalWindow || w.dialog)) {
                continue;
            }
            if (String(w.resourceClass).indexOf("plasmashell") !== -1) {
                continue;
            }
            n++;
        }
        return n;
    }

    Timer {
        interval: 200
        repeat: true
        running: !root.shown
        triggeredOnStart: true
        onTriggered: if (root.appWindows() === 0) root.shown = true
    }

    Instantiator {
        model: root.shown ? Qt.application.screens : []
        delegate: Window {
            required property var modelData
            x: modelData.virtualX
            y: modelData.virtualY
            width: modelData.width
            height: modelData.height
            flags: Qt.FramelessWindowHint | Qt.BypassWindowManagerHint
            color: "#3A6EA5"
            visible: true
            title: root.message

            Item {
                id: box
                width: 428
                height: 150
                anchors.centerIn: parent
                Rectangle { x: 4; y: 4; width: parent.width; height: parent.height; color: "#000000"; opacity: 0.25 }
                Logon.Bevel { anchors.fill: parent; window: true }
                Logon.Banner {
                    id: banner
                    x: 4
                    y: 4
                    width: parent.width - 8
                }
                // the colour band under the banner runs, as the classic shutdown screens did
                Item {
                    x: 4
                    y: 4 + banner.height - 6
                    width: parent.width - 8
                    height: 6
                    clip: true
                    Rectangle {
                        id: runner
                        width: parent.width / 3
                        height: parent.height
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0.0; color: "#00FFFFFF" }
                            GradientStop { position: 0.5; color: "#C0FFFFFF" }
                            GradientStop { position: 1.0; color: "#00FFFFFF" }
                        }
                        NumberAnimation on x {
                            from: -runner.width
                            to: box.width
                            duration: 1400
                            loops: Animation.Infinite
                        }
                    }
                }
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 26
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 24
                    text: root.message
                    font.family: "Noto Sans"
                    font.pixelSize: 15
                    color: "#000000"
                }
            }
        }
    }
}
