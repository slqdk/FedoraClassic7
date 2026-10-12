import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import org.kde.plasma.networkmanagement as PlasmaNM
import org.kde.networkmanager as NMQt

PlasmaExtras.Representation {
    id: popup

    required property PlasmaNM.Handler nmHandler
    required property PlasmaNM.NetworkStatus nmStatus
    property var details: ({})
    signal run(string cmd)
    signal configure()

    collapseMarginsHint: true
    implicitHeight: column.implicitHeight + Kirigami.Units.largeSpacing * 2

    readonly property string connectivityText: {
        switch (nmStatus.connectivity) {
        case NMQt.NetworkManager.Full: return i18n("Internet access");
        case NMQt.NetworkManager.Limited: return i18n("No Internet access");
        case NMQt.NetworkManager.Portal: return i18n("Sign-in required");
        case NMQt.NetworkManager.NoConnectivity: return i18n("No network access");
        default: return "";
        }
    }

    PlasmaNM.NetworkModel {
        id: networkModel
    }
    PlasmaNM.AppletProxyModel {
        id: proxyModel
        sourceModel: networkModel
    }

    PC3.ScrollView {
        anchors.fill: parent
        anchors.margins: Kirigami.Units.largeSpacing
        contentWidth: availableWidth

        ColumnLayout {
            id: column
            width: parent.width
            spacing: Kirigami.Units.smallSpacing

            // ---- Currently connected to ------------------------------------------------
            PC3.Label {
                text: activeRepeater.shown > 0 ? i18n("Currently connected to:") : i18n("Not connected")
                font.bold: true
            }
            Repeater {
                id: activeRepeater
                property int shown: 0
                model: proxyModel
                delegate: ActiveItem {
                    Layout.fillWidth: true
                    popup: popup
                    onVisibleChanged: activeRepeater.recount()
                    Component.onCompleted: activeRepeater.recount()
                    Component.onDestruction: Qt.callLater(activeRepeater.recount)
                }
                function recount() {
                    let n = 0;
                    for (let i = 0; i < count; i++) {
                        const it = itemAt(i);
                        if (it && it.isActive) n++;
                    }
                    shown = n;
                }
            }

            Kirigami.Separator {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
                visible: otherRepeater.shown > 0
            }

            // ---- other connections -----------------------------------------------------
            PC3.Label {
                text: i18n("Other connections:")
                font.bold: true
                visible: otherRepeater.shown > 0
            }
            Repeater {
                id: otherRepeater
                property int shown: 0
                model: proxyModel
                delegate: OtherItem {
                    Layout.fillWidth: true
                    popup: popup
                    onVisibleChanged: otherRepeater.recount()
                    Component.onCompleted: otherRepeater.recount()
                    Component.onDestruction: Qt.callLater(otherRepeater.recount)
                }
                function recount() {
                    let n = 0;
                    for (let i = 0; i < count; i++) {
                        const it = itemAt(i);
                        if (it && it.isOther) n++;
                    }
                    shown = n;
                }
            }

            Kirigami.Separator {
                Layout.fillWidth: true
                Layout.topMargin: Kirigami.Units.smallSpacing
            }

            // ---- links -----------------------------------------------------------------
            RowLayout {
                Layout.fillWidth: true
                LinkText {
                    text: i18n("Open Network Connections")
                    onClicked: popup.run("classic7-network")
                }
                Item { Layout.fillWidth: true }
                LinkText {
                    text: i18n("Network settings…")
                    onClicked: popup.configure()
                }
            }
        }
    }
}
