/*
    Classic 7 network popup: "Currently connected to" with the IP address shown at once,
    the other connections to connect to, and links to Network Connections (ncpa.cpl).
    Connection handling is Plasma's own (org.kde.plasma.networkmanagement), the address
    details come from `classic7-network --json` (nmcli).
*/
import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import org.kde.plasma.components as PC3
import org.kde.plasma.extras as PlasmaExtras
import org.kde.kirigami as Kirigami
import org.kde.plasma.networkmanagement as PlasmaNM
import org.kde.networkmanager as NMQt
import org.kde.kcmutils as KCMUtils
import org.kde.plasma.plasma5support as P5Support

PlasmoidItem {
    id: root

    // adapter details by interface name: {enp3s0: {ipv4: [[ip, mask, prefix]], gateway, dns, ...}}
    property var details: ({})
    readonly property bool inPanel: Plasmoid.location === PlasmaCore.Types.TopEdge
        || Plasmoid.location === PlasmaCore.Types.RightEdge
        || Plasmoid.location === PlasmaCore.Types.BottomEdge
        || Plasmoid.location === PlasmaCore.Types.LeftEdge

    function firstAddress() {
        for (const dev in details) {
            const d = details[dev];
            if (d.ipv4 && d.ipv4.length && String(d.state).indexOf("connected") === 0) {
                return d.ipv4[0][0];
            }
        }
        return "";
    }

    function run(cmd) {
        // unique source name, so the same program can be started again while it runs
        exec.connectSource(cmd + " # " + Date.now());
    }

    function refresh() {
        exec.connectSource(exec.jsonCmd);
    }

    Plasmoid.icon: inPanel ? connectionIcon.connectionIcon + "-symbolic" : connectionIcon.connectionTooltipIcon
    Plasmoid.busy: connectionIcon.connecting
    toolTipMainText: i18n("Network")
    toolTipSubText: {
        const ip = firstAddress();
        const active = networkStatus.activeConnections;
        return ip ? (active ? active + "\n" : "") + i18n("IPv4 address: %1", ip) : active;
    }
    switchWidth: Kirigami.Units.gridUnit * 10
    switchHeight: Kirigami.Units.gridUnit * 10

    onExpandedChanged: if (expanded) { refresh(); handler.requestScan(); }

    P5Support.DataSource {
        id: exec
        readonly property string jsonCmd: "classic7-network --json"
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            if (source === jsonCmd) {
                try {
                    root.details = JSON.parse(data["stdout"] || "{}");
                } catch (e) {
                    root.details = {};
                }
            }
            disconnectSource(source);
        }
    }

    Timer {
        // keep the addresses fresh while the popup is open (DHCP, cable plugged in ...)
        interval: 3000
        repeat: true
        running: root.expanded
        onTriggered: root.refresh()
    }
    Timer {
        // and now and then for the tooltip
        interval: 30000
        repeat: true
        running: !root.expanded
        onTriggered: root.refresh()
    }
    Timer {
        interval: 10200
        repeat: true
        running: root.expanded
        onTriggered: handler.requestScan()
    }

    PlasmaNM.NetworkStatus {
        id: networkStatus
        onActiveConnectionsChanged: root.refresh()
    }
    PlasmaNM.ConnectionIcon {
        id: connectionIcon
        connectivity: networkStatus.connectivity
    }
    PlasmaNM.Handler {
        id: handler
    }
    PlasmaNM.EnabledConnections {
        id: enabledConnections
    }
    PlasmaNM.AvailableDevices {
        id: availableDevices
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: i18n("Open Network Connections")
            icon.name: "preferences-system-network"
            onTriggered: root.run("classic7-network")
        },
        PlasmaCore.Action {
            text: i18n("Enable Wi-Fi")
            icon.name: "network-wireless-on"
            checkable: true
            checked: enabledConnections.wirelessEnabled
            visible: enabledConnections.wirelessHwEnabled && availableDevices.wirelessDeviceAvailable
            onTriggered: checked => handler.enableWireless(checked)
        }
    ]

    PlasmaCore.Action {
        id: configureAction
        text: i18n("&Configure Network Connections…")
        icon.name: "configure"
        onTriggered: KCMUtils.KCMLauncher.openSystemSettings("kcm_networkmanagement")
    }

    fullRepresentation: PopupDialog {
        Layout.minimumWidth: Kirigami.Units.gridUnit * 22
        Layout.minimumHeight: Kirigami.Units.gridUnit * 14
        Layout.preferredHeight: implicitHeight
        Layout.maximumHeight: Kirigami.Units.gridUnit * 34
        nmHandler: handler
        nmStatus: networkStatus
        details: root.details
        onRun: cmd => root.run(cmd)
        onConfigure: configureAction.trigger()
    }

    Component.onCompleted: {
        Plasmoid.setInternalAction("configure", configureAction);
        refresh();
    }
}
