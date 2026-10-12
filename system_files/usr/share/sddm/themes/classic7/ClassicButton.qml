import QtQuick

// Push button in the Classic style: raised bevel, sunken while pressed, dotted focus rectangle,
// black outer line on the default button.
FocusScope {
    id: button
    property alias text: label.text
    property bool isDefault: false
    property string fontFamily: "Noto Sans"
    signal clicked()

    implicitWidth: Math.max(75, label.implicitWidth + 24)
    implicitHeight: 23
    activeFocusOnTab: true

    readonly property bool down: mouse.pressed && mouse.containsMouse || keyDown
    property bool keyDown: false
    readonly property bool framed: isDefault || activeFocus

    Rectangle {
        anchors.fill: parent
        color: "#000000"
        visible: button.framed
    }
    Bevel {
        anchors.fill: parent
        anchors.margins: button.framed ? 1 : 0
        sunken: button.down
        dark: button.down ? "#808080" : "#404040"
    }
    Text {
        id: label
        anchors.centerIn: parent
        anchors.horizontalCenterOffset: button.down ? 1 : 0
        anchors.verticalCenterOffset: button.down ? 1 : 0
        font.family: button.fontFamily
        font.pixelSize: 12
        color: button.enabled ? "#000000" : "#808080"
        style: button.enabled ? Text.Normal : Text.Raised
        styleColor: "#FFFFFF"
    }
    // dotted focus rectangle
    Rectangle {
        anchors.fill: parent
        anchors.margins: 4
        color: "transparent"
        border.width: 1
        border.color: "#000000"
        visible: button.activeFocus
        opacity: 0.6
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: button.enabled
        onClicked: { button.forceActiveFocus(); button.clicked() }
    }
    Keys.onPressed: function (event) {
        if (event.key === Qt.Key_Space && !event.isAutoRepeat) { keyDown = true; event.accepted = true }
        else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && button.enabled) {
            event.accepted = true; button.clicked()
        }
    }
    Keys.onReleased: function (event) {
        if (event.key === Qt.Key_Space && !event.isAutoRepeat && keyDown) {
            keyDown = false; event.accepted = true
            if (button.enabled) button.clicked()
        }
    }
}
