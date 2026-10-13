/*
    Classic 7 Action Center flag: the messages of `classic7-actioncenter --json` (firewall,
    updates, disk space, programs that stopped working). A red mark on the flag when one of them
    is important; click for the list, each message opens what fixes it.
*/
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PC3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    property var data: ({messages: [], count: 0, important: 0})
    readonly property var current: (data.messages || []).filter(m => !m.archived)

    function run(cmd) {
        exec.connectSource(cmd + " # " + Date.now());
    }
    function refresh() {
        exec.connectSource(exec.jsonCmd);
    }
    function quote(args) {
        return args.map(a => "'" + String(a).replace(/'/g, "'\\''") + "'").join(" ");
    }

    Plasmoid.icon: "flag"
    toolTipMainText: i18n("Action Center")
    toolTipSubText: {
        if (!data.count) return i18n("No current issues detected");
        let lines = [];
        if (data.important) lines.push(i18np("1 important message", "%1 important messages", data.important));
        lines.push(i18np("1 total message", "%1 total messages", data.count));
        return lines.join("\n");
    }

    P5Support.DataSource {
        id: exec
        readonly property string jsonCmd: "classic7-actioncenter --json"
        engine: "executable"
        connectedSources: []
        onNewData: (source, d) => {
            if (source === jsonCmd) {
                try {
                    root.data = JSON.parse(d["stdout"] || "{}");
                } catch (e) {
                    root.data = {messages: [], count: 0, important: 0};
                }
            }
            disconnectSource(source);
        }
    }
    Timer {
        interval: 10 * 60 * 1000
        repeat: true
        running: true
        onTriggered: root.refresh()
    }
    onExpandedChanged: if (expanded) refresh()

    compactRepresentation: MouseArea {
        Layout.minimumWidth: height
        Layout.minimumHeight: width
        anchors.fill: parent
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded
        Kirigami.Icon {
            id: flag
            anchors.fill: parent
            source: "flag"
            active: parent.containsMouse
        }
        Kirigami.Icon {
            visible: root.data.important > 0
            source: "emblem-error"
            width: Math.round(flag.width * 0.55)
            height: width
            anchors.right: flag.right
            anchors.bottom: flag.bottom
        }
    }

    fullRepresentation: PlasmaExtras.Representation {
        collapseMarginsHint: true
        Layout.minimumWidth: Kirigami.Units.gridUnit * 19
        Layout.minimumHeight: column.implicitHeight + Kirigami.Units.largeSpacing * 2
        Layout.maximumHeight: Layout.minimumHeight

        ColumnLayout {
            id: column
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            PC3.Label {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.1
                color: "#1e3287"
                text: root.data.important ? i18np("Solve 1 important message", "Solve %1 important messages", root.data.important)
                    : (root.data.count ? i18np("Solve 1 message", "Solve %1 messages", root.data.count) : i18n("No current issues detected"))
            }
            PC3.Label {
                visible: root.data.count > 0
                opacity: 0.75
                text: i18np("1 total message", "%1 total messages", root.data.count)
            }
            Kirigami.Separator {
                Layout.fillWidth: true
                visible: root.current.length > 0
            }
            Repeater {
                model: root.current
                RowLayout {
                    required property var modelData
                    Layout.fillWidth: true
                    spacing: Kirigami.Units.smallSpacing
                    Kirigami.Icon {
                        Layout.preferredWidth: Kirigami.Units.iconSizes.small
                        Layout.preferredHeight: Kirigami.Units.iconSizes.small
                        Layout.alignment: Qt.AlignTop
                        source: modelData.important ? "emblem-error" : "emblem-important"
                    }
                    LinkText {
                        Layout.fillWidth: true
                        wrapMode: Text.WordWrap
                        text: modelData.title
                        onClicked: {
                            root.expanded = false;
                            root.run(root.quote(modelData.fix));
                        }
                    }
                }
            }
            Kirigami.Separator {
                Layout.fillWidth: true
            }
            LinkText {
                text: i18n("Open Action Center")
                onClicked: {
                    root.expanded = false;
                    root.run("classic7-actioncenter");
                }
            }
        }
    }

    Component.onCompleted: {
        Plasmoid.removeInternalAction("configure");
        refresh();
    }
}
