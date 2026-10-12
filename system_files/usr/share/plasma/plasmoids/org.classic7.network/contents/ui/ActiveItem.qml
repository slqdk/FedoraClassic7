import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC3
import org.kde.kirigami as Kirigami
import org.kde.plasma.networkmanagement as PlasmaNM

// One active connection: name, internet access, and its addresses right away
ColumnLayout {
    id: item
    required property var model
    required property int index
    property var popup

    readonly property bool isActive: model.ConnectionState === PlasmaNM.Enums.Activated
    readonly property string device: String(model.DeviceName || "").replace(/[^A-Za-z0-9_.:-]/g, "")
    readonly property var info: (popup && popup.details && device) ? (popup.details[device] || null) : null

    visible: isActive
    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing
        Kirigami.Icon {
            source: item.model.ConnectionIcon
            Layout.preferredWidth: Kirigami.Units.iconSizes.medium
            Layout.preferredHeight: Kirigami.Units.iconSizes.medium
        }
        ColumnLayout {
            spacing: 0
            Layout.fillWidth: true
            PC3.Label {
                text: item.model.Name
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
            PC3.Label {
                text: item.model.Type === PlasmaNM.Enums.Vpn ? i18n("Connected") : item.popup.connectivityText
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                visible: text !== ""
            }
        }
    }

    // the addresses (selectable, so they can be copied)
    GridLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.iconSizes.medium + Kirigami.Units.largeSpacing
        columns: 2
        columnSpacing: Kirigami.Units.largeSpacing
        rowSpacing: 0
        visible: item.info !== null

        Repeater {
            model: item.info ? item.info.ipv4 : []
            delegate: PC3.Label {
                required property var modelData
                required property int index
                Layout.row: index
                Layout.column: 0
                text: index === 0 ? i18n("IPv4 address:") : ""
            }
        }
        Repeater {
            model: item.info ? item.info.ipv4 : []
            delegate: TextEdit {
                required property var modelData
                required property int index
                Layout.row: index
                Layout.column: 1
                text: modelData[0] + "  /  " + modelData[1]
                readOnly: true
                selectByMouse: true
                color: Kirigami.Theme.textColor
                selectionColor: Kirigami.Theme.highlightColor
                font.bold: index === 0
            }
        }
        PC3.Label {
            Layout.row: 20
            Layout.column: 0
            text: i18n("Gateway:")
            visible: item.info !== null && item.info.gateway !== ""
        }
        TextEdit {
            Layout.row: 20
            Layout.column: 1
            text: item.info ? item.info.gateway : ""
            visible: text !== ""
            readOnly: true
            selectByMouse: true
            color: Kirigami.Theme.textColor
        }
        PC3.Label {
            Layout.row: 21
            Layout.column: 0
            text: i18n("DNS:")
            visible: item.info !== null && item.info.dns.length > 0
        }
        TextEdit {
            Layout.row: 21
            Layout.column: 1
            text: item.info ? item.info.dns.join(", ") : ""
            visible: text !== ""
            readOnly: true
            selectByMouse: true
            color: Kirigami.Theme.textColor
        }
        PC3.Label {
            Layout.row: 22
            Layout.column: 0
            text: i18n("Obtained:")
            visible: item.info !== null
        }
        PC3.Label {
            Layout.row: 22
            Layout.column: 1
            text: item.info ? (item.info.dhcp ? i18n("Automatically (DHCP)") : i18n("Fixed address")) : ""
            visible: item.info !== null
        }
    }

    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.iconSizes.medium + Kirigami.Units.largeSpacing
        PC3.Button {
            text: i18n("Status")
            visible: item.device !== ""
            onClicked: item.popup.run("classic7-network --status '" + item.device + "'")
        }
        PC3.Button {
            text: i18n("IP Settings…")
            visible: item.device !== "" && item.model.Type !== PlasmaNM.Enums.Vpn
            onClicked: item.popup.run("classic7-network --ipv4 '" + item.device + "'")
        }
        Item { Layout.fillWidth: true }
        PC3.Button {
            text: i18n("Disconnect")
            onClicked: item.popup.nmHandler.deactivateConnection(item.model.ConnectionPath, item.model.DevicePath)
        }
    }
}
