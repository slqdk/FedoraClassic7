import QtQuick

// Single-line text box with a sunken border.
FocusScope {
    id: field
    property alias text: input.text
    property alias echoMode: input.echoMode
    property alias input: input
    property string fontFamily: "Noto Sans"
    signal accepted()

    implicitHeight: 21
    implicitWidth: 200
    activeFocusOnTab: true

    Bevel {
        anchors.fill: parent
        sunken: true
        face: field.enabled ? "#FFFFFF" : "#D4D0C8"
        mid: "#FFFFFF"
    }
    TextInput {
        id: input
        anchors.fill: parent
        anchors.leftMargin: 4
        anchors.rightMargin: 4
        verticalAlignment: TextInput.AlignVCenter
        focus: true
        clip: true
        enabled: field.enabled
        font.family: field.fontFamily
        font.pixelSize: 12
        color: "#000000"
        selectionColor: "#0A246A"
        selectedTextColor: "#FFFFFF"
        selectByMouse: true
        passwordCharacter: "●"
        onAccepted: field.accepted()
    }
}
