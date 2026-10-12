import QtQuick

// Dialog window in the Classic style: raised frame and a gradient title bar.
Item {
    id: dlg
    property alias title: titleText.text
    property string fontFamily: "Noto Sans"
    property bool active: true
    default property alias content: body.data
    property int contentWidth: 300
    property int contentHeight: 100

    width: contentWidth + 8
    height: contentHeight + 8 + 20

    // drop shadow, like a window on the desktop
    Rectangle { x: 4; y: 4; width: parent.width; height: parent.height; color: "#000000"; opacity: 0.25 }
    Bevel { anchors.fill: parent; window: true }
    Rectangle {
        id: titleBar
        x: 4; y: 4
        width: parent.width - 8
        height: 18
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: dlg.active ? "#0A246A" : "#808080" }
            GradientStop { position: 1.0; color: dlg.active ? "#A6CAF0" : "#C0C0C0" }
        }
        Text {
            id: titleText
            anchors.left: parent.left
            anchors.leftMargin: 4
            anchors.verticalCenter: parent.verticalCenter
            color: dlg.active ? "#FFFFFF" : "#D4D0C8"
            font.family: dlg.fontFamily
            font.pixelSize: 12
            font.bold: true
        }
    }
    Item {
        id: body
        x: 4
        y: 24
        width: dlg.contentWidth
        height: dlg.contentHeight
    }
}
