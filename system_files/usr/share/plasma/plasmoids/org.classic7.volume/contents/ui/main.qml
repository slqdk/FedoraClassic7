/*
    Classic 7 volume: the speaker icon in the notification area. Click: the Windows 7 popup with
    the speakers' name, one tall slider, the mute button and the Mixer link; a "ding" plays when
    the slider is let go. Middle-click mutes, the mouse wheel changes the volume. Sound handling
    is Plasma's own (org.kde.plasma.private.volume); the volume keys keep working through KDE's
    audio shortcuts service.
*/
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PC3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import org.kde.plasma.plasma5support as P5Support
import org.kde.plasma.private.volume

PlasmoidItem {
    id: root

    readonly property var sink: PreferredDevice.sink
    readonly property bool hasSink: !!sink && sink.name !== "auto_null"
    readonly property int percent: hasSink ? Math.round(sink.volume / PulseAudio.NormalVolume * 100) : 0
    readonly property bool muted: hasSink ? sink.muted : true
    readonly property string deviceName: hasSink ? (sink.description || sink.name) : i18n("No audio device")

    function run(cmd) {
        exec.connectSource(cmd + " # " + Date.now());
    }
    function shortName(name) {
        // "Speakers (Realtek ...)" -> "Speakers"; the full name is the tooltip
        const i = name.indexOf(" (");
        return i > 0 && name.length > 18 ? name.substring(0, i) : name;
    }

    P5Support.DataSource {
        id: exec
        engine: "executable"
        connectedSources: []
        onNewData: source => disconnectSource(source)
    }
    GlobalConfig {
        id: config
    }
    VolumeFeedback {
        id: feedback
    }

    Plasmoid.icon: AudioIcon.forVolume(percent, muted, "")
    toolTipMainText: hasSink ? shortName(deviceName) + ": " + (muted ? i18n("Muted") : percent + "%") : deviceName
    toolTipSubText: hasSink ? i18n("Middle-click to mute") : ""
    switchWidth: Kirigami.Units.gridUnit * 5
    switchHeight: Kirigami.Units.gridUnit * 10

    compactRepresentation: MouseArea {
        property int wheelDelta: 0
        property bool wasExpanded: false
        Layout.minimumWidth: height
        Layout.minimumHeight: width
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton
        onPressed: mouse => {
            if (mouse.button === Qt.LeftButton) {
                wasExpanded = root.expanded;
            } else if (mouse.button === Qt.MiddleButton && root.hasSink) {
                root.sink.muted = !root.sink.muted;
            }
        }
        onClicked: mouse => {
            if (mouse.button === Qt.LeftButton) {
                root.expanded = !wasExpanded;
            }
        }
        onWheel: wheel => {
            const delta = (wheel.inverted ? -1 : 1) * (wheel.angleDelta.y ? wheel.angleDelta.y : -wheel.angleDelta.x);
            if ((wheelDelta > 0 && delta < 0) || (wheelDelta < 0 && delta > 0)) {
                wheelDelta = 0;
            }
            wheelDelta += delta;
            while (wheelDelta >= 120) {
                wheelDelta -= 120;
                GlobalService.volumeUp();
            }
            while (wheelDelta <= -120) {
                wheelDelta += 120;
                GlobalService.volumeDown();
            }
        }
        Kirigami.Icon {
            anchors.fill: parent
            source: Plasmoid.icon
            active: parent.containsMouse
        }
    }

    fullRepresentation: PlasmaExtras.Representation {
        collapseMarginsHint: true
        Layout.minimumWidth: Kirigami.Units.gridUnit * 6
        Layout.maximumWidth: Kirigami.Units.gridUnit * 6
        Layout.minimumHeight: Kirigami.Units.gridUnit * 17
        Layout.maximumHeight: Kirigami.Units.gridUnit * 17

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Kirigami.Units.smallSpacing
            spacing: Kirigami.Units.smallSpacing

            PC3.ToolButton {
                Layout.alignment: Qt.AlignHCenter
                icon.name: "audio-speakers"
                icon.width: Kirigami.Units.iconSizes.medium
                icon.height: Kirigami.Units.iconSizes.medium
                display: PC3.AbstractButton.IconOnly
                enabled: root.hasSink
                onClicked: {
                    root.expanded = false;
                    root.run("kcmshell6 kcm_pulseaudio");
                }
                PC3.ToolTip.text: root.deviceName
                PC3.ToolTip.visible: hovered
                PC3.ToolTip.delay: Kirigami.Units.toolTipDelay
            }
            PC3.Label {
                Layout.fillWidth: true
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: root.shortName(root.deviceName)
            }
            PC3.Slider {
                id: slider
                Layout.alignment: Qt.AlignHCenter
                Layout.fillHeight: true
                orientation: Qt.Vertical
                enabled: root.hasSink
                from: PulseAudio.MinimalVolume
                to: PulseAudio.NormalVolume
                stepSize: PulseAudio.NormalVolume / 100
                value: root.hasSink ? root.sink.volume : 0
                opacity: root.muted ? 0.6 : 1
                onMoved: {
                    if (root.hasSink) {
                        root.sink.volume = value;
                        root.sink.muted = false;
                    }
                }
                onPressedChanged: {
                    if (!pressed && root.hasSink && config.audioFeedback) {
                        feedback.play(root.sink.index);
                    }
                }
                PC3.ToolTip.text: root.percent + "%"
                PC3.ToolTip.visible: pressed || hovered
            }
            PC3.ToolButton {
                Layout.alignment: Qt.AlignHCenter
                icon.name: AudioIcon.forVolume(root.percent, root.muted, "")
                icon.width: Kirigami.Units.iconSizes.smallMedium
                icon.height: Kirigami.Units.iconSizes.smallMedium
                display: PC3.AbstractButton.IconOnly
                checkable: true
                checked: root.muted
                enabled: root.hasSink
                onClicked: root.sink.muted = !root.sink.muted
                PC3.ToolTip.text: root.muted ? i18n("Unmute %1", root.shortName(root.deviceName)) : i18n("Mute %1", root.shortName(root.deviceName))
                PC3.ToolTip.visible: hovered
                PC3.ToolTip.delay: Kirigami.Units.toolTipDelay
            }
            Kirigami.Separator {
                Layout.fillWidth: true
            }
            LinkText {
                Layout.alignment: Qt.AlignHCenter
                text: i18n("Mixer")
                onClicked: {
                    root.expanded = false;
                    root.run("classic7-mixer");
                }
            }
        }
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Open Volume Mixer")
            icon.name: "audio-volume-high"
            onTriggered: root.run("classic7-mixer")
        },
        PlasmaCore.Action {
            isSeparator: true
        },
        PlasmaCore.Action {
            text: i18n("Playback devices")
            icon.name: "audio-speakers"
            onTriggered: root.run("kcmshell6 kcm_pulseaudio")
        },
        PlasmaCore.Action {
            text: i18n("Recording devices")
            icon.name: "audio-input-microphone"
            onTriggered: root.run("kcmshell6 kcm_pulseaudio")
        },
        PlasmaCore.Action {
            text: i18n("Sounds")
            icon.name: "preferences-desktop-sound"
            onTriggered: root.run("kcmshell6 kcm_soundtheme")
        }
    ]

    Component.onCompleted: Plasmoid.removeInternalAction("configure")
}
