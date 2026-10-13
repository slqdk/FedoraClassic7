/*
    Classic 7 taskbar clock: the time (and the date when the taskbar is tall enough), the long
    date as tooltip, and the Windows 7 popup: today's date as a link, a month calendar (click the
    title for months and years), a clock face, and "Change date and time settings...".
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

    property date now: new Date()
    readonly property var loc: Qt.locale()
    readonly property string timeText: Qt.formatTime(now, loc.timeFormat(Locale.ShortFormat))
    readonly property string dateText: Qt.formatDate(now, loc.dateFormat(Locale.ShortFormat))
    readonly property string longDate: now.toLocaleDateString(loc, Locale.LongFormat)

    Plasmoid.backgroundHints: PlasmaCore.Types.NoBackground
    preferredRepresentation: compactRepresentation
    switchWidth: Kirigami.Units.gridUnit * 16
    switchHeight: Kirigami.Units.gridUnit * 12
    toolTipMainText: longDate
    toolTipSubText: ""

    function run(cmd) {
        exec.connectSource(cmd + " # " + Date.now());
    }

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        onNewData: source => disconnectSource(source)
    }

    Timer {
        // every second; the taskbar text only changes with the minute, the clock face every second
        interval: 1000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: {
            const d = new Date();
            if (root.expanded || d.getMinutes() !== root.now.getMinutes() || d.getHours() !== root.now.getHours()
                    || d.getDate() !== root.now.getDate()) {
                root.now = d;
            }
        }
    }

    compactRepresentation: MouseArea {
        id: compact
        readonly property bool twoLines: height >= Kirigami.Units.gridUnit * 2.4
        Layout.minimumWidth: Math.max(timeLabel.implicitWidth, twoLines ? dateLabel.implicitWidth : 0) + Kirigami.Units.largeSpacing * 2
        Layout.preferredWidth: Layout.minimumWidth
        hoverEnabled: true
        onClicked: root.expanded = !root.expanded

        Rectangle {
            // the pressed look of the Windows 7 clock
            anchors.fill: parent
            anchors.margins: 1
            visible: root.expanded || compact.containsMouse
            color: "transparent"
            border.color: root.expanded ? Qt.darker(Kirigami.Theme.backgroundColor, 1.5) : Qt.lighter(Kirigami.Theme.backgroundColor, 1.25)
            radius: 2
        }
        ColumnLayout {
            anchors.centerIn: parent
            spacing: 0
            PC3.Label {
                id: timeLabel
                Layout.alignment: Qt.AlignHCenter
                text: root.timeText
            }
            PC3.Label {
                id: dateLabel
                Layout.alignment: Qt.AlignHCenter
                visible: compact.twoLines
                text: root.dateText
            }
        }
    }

    fullRepresentation: PlasmaExtras.Representation {
        id: popup
        collapseMarginsHint: true
        Layout.minimumWidth: Kirigami.Units.gridUnit * 25
        Layout.minimumHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2
        Layout.maximumHeight: Layout.minimumHeight

        ColumnLayout {
            id: content
            anchors.fill: parent
            anchors.margins: Kirigami.Units.largeSpacing
            spacing: Kirigami.Units.smallSpacing

            LinkText {
                text: root.longDate
                font.pointSize: Kirigami.Theme.defaultFont.pointSize * 1.15
                onClicked: calendar.showToday()
            }
            Kirigami.Separator { Layout.fillWidth: true }
            RowLayout {
                spacing: Kirigami.Units.largeSpacing * 2
                Calendar {
                    id: calendar
                    Layout.alignment: Qt.AlignTop
                    today: root.now
                }
                ColumnLayout {
                    Layout.alignment: Qt.AlignTop
                    spacing: Kirigami.Units.smallSpacing
                    AnalogClock {
                        Layout.alignment: Qt.AlignHCenter
                        implicitWidth: Kirigami.Units.gridUnit * 8
                        implicitHeight: implicitWidth
                        time: root.now
                    }
                    PC3.Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: Qt.formatTime(root.now, root.loc.timeFormat(Locale.LongFormat).replace(/\s*t\s*/, ""))
                    }
                    PC3.Label {
                        Layout.alignment: Qt.AlignHCenter
                        text: root.loc.dayName(root.now.getDay(), Locale.LongFormat)
                        opacity: 0.8
                    }
                }
            }
            Kirigami.Separator { Layout.fillWidth: true }
            LinkText {
                Layout.alignment: Qt.AlignHCenter
                text: i18n("Change date and time settings...")
                onClicked: {
                    root.expanded = false;
                    root.run("classic7-timedate");
                }
            }
        }
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Adjust date/time")
            icon.name: "preferences-system-time"
            onTriggered: root.run("classic7-timedate")
        }
    ]

    Component.onCompleted: {
        // "Configure" would offer settings this clock doesn't have
        Plasmoid.removeInternalAction("configure");
    }
}
