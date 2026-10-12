import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC3
import org.kde.kirigami as Kirigami
import org.kde.plasma.networkmanagement as PlasmaNM

// A connection or Wi-Fi network that is not active: Connect (asks for the Wi-Fi password)
ColumnLayout {
    id: item
    required property var model
    required property int index
    property var popup
    property bool askPassword: false

    readonly property bool activating: model.ConnectionState === PlasmaNM.Enums.Activating
    readonly property bool isOther: model.ConnectionState !== PlasmaNM.Enums.Activated
    readonly property bool wireless: model.Type === PlasmaNM.Enums.Wireless
    readonly property bool needsPassword: wireless && !model.Uuid
        && [PlasmaNM.Enums.StaticWep, PlasmaNM.Enums.WpaPsk, PlasmaNM.Enums.Wpa2Psk, PlasmaNM.Enums.SAE]
            .indexOf(model.SecurityType) !== -1

    visible: isOther
    spacing: Kirigami.Units.smallSpacing

    function connectNow() {
        const h = popup.nmHandler;
        if (model.Uuid) {
            h.activateConnection(model.ConnectionPath, model.DevicePath, model.SpecificPath);
        } else if (needsPassword) {
            if (!askPassword) {
                askPassword = true;
                password.forceActiveFocus();
                return;
            }
            if (password.text === "") {
                return;
            }
            h.addAndActivateConnection(model.DevicePath, model.SpecificPath, password.text);
            askPassword = false;
            password.text = "";
        } else {
            h.addAndActivateConnection(model.DevicePath, model.SpecificPath);
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.largeSpacing
        Kirigami.Icon {
            source: item.model.ConnectionIcon
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
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
                text: item.activating ? i18n("Connecting…")
                    : item.wireless ? (item.model.SecurityTypeString + (item.model.Signal ? " · " + item.model.Signal + " %" : ""))
                    : (item.model.LastUsed || "")
                opacity: 0.7
                font: Kirigami.Theme.smallFont
                visible: text !== ""
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
        PC3.Button {
            text: item.activating ? i18n("Cancel") : i18n("Connect")
            onClicked: item.activating
                ? item.popup.nmHandler.deactivateConnection(item.model.ConnectionPath, item.model.DevicePath)
                : item.connectNow()
        }
    }
    RowLayout {
        Layout.fillWidth: true
        Layout.leftMargin: Kirigami.Units.iconSizes.smallMedium + Kirigami.Units.largeSpacing
        visible: item.askPassword
        PC3.TextField {
            id: password
            Layout.fillWidth: true
            echoMode: TextInput.Password
            placeholderText: i18n("Security key")
            onAccepted: item.connectNow()
        }
    }
}
