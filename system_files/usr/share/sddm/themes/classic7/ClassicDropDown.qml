import QtQuick

// Drop-down list in the Classic style (sunken box + arrow button, list opens below).
// Works with SDDM's user and session models: give textRole (and keyRole for the value).
FocusScope {
    id: dd
    property var model
    property string textRole: "name"
    property string keyRole: "name"
    property int currentIndex: 0
    readonly property string currentText: items.count > currentIndex && currentIndex >= 0 && items.itemAt(currentIndex)
                                          ? items.itemAt(currentIndex).label : ""
    readonly property string currentKey: items.count > currentIndex && currentIndex >= 0 && items.itemAt(currentIndex)
                                         ? items.itemAt(currentIndex).key : ""
    property bool open: false
    property string fontFamily: "Noto Sans"
    signal activated(int index)

    implicitHeight: 21
    implicitWidth: 200
    activeFocusOnTab: true
    z: open ? 100 : 0

    function select(i) {
        currentIndex = i
        open = false
        activated(i)
    }

    Bevel { anchors.fill: parent; sunken: true; face: "#FFFFFF"; mid: "#FFFFFF" }
    Rectangle {
        id: textBox
        x: 3; y: 3
        width: parent.width - 6 - arrow.width
        height: parent.height - 6
        color: dd.activeFocus && !dd.open ? "#0A246A" : "#FFFFFF"
        Text {
            anchors.fill: parent
            anchors.leftMargin: 2
            verticalAlignment: Text.AlignVCenter
            text: dd.currentText
            elide: Text.ElideRight
            font.family: dd.fontFamily
            font.pixelSize: 12
            color: dd.activeFocus && !dd.open ? "#FFFFFF" : "#000000"
        }
    }
    Item {
        id: arrow
        width: 16
        anchors.right: parent.right
        anchors.rightMargin: 2
        anchors.top: parent.top
        anchors.topMargin: 2
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 2
        Bevel { anchors.fill: parent; sunken: arrowMouse.pressed }
        Canvas {
            anchors.centerIn: parent
            width: 7; height: 4
            onPaint: {
                var c = getContext("2d")
                c.fillStyle = "#000000"
                c.beginPath(); c.moveTo(0, 0); c.lineTo(7, 0); c.lineTo(3.5, 4); c.closePath(); c.fill()
            }
        }
        MouseArea { id: arrowMouse; anchors.fill: parent }
    }
    MouseArea {
        anchors.fill: parent
        onClicked: { dd.forceActiveFocus(); dd.open = !dd.open }
    }

    // the list
    Rectangle {
        id: popup
        visible: dd.open
        y: dd.height
        width: dd.width
        height: column.height + 2
        color: "#FFFFFF"
        border.color: "#000000"
        Column {
            id: column
            x: 1; y: 1
            width: parent.width - 2
            Repeater {
                id: items
                model: dd.model
                delegate: Rectangle {
                    required property int index
                    required property var model
                    readonly property string label: String(model[dd.textRole] || model[dd.keyRole] || "")
                    readonly property string key: String(model[dd.keyRole] || "")
                    width: column.width
                    height: 18
                    readonly property bool hl: hover.containsMouse || index === dd.currentIndex
                    color: hl ? "#0A246A" : "#FFFFFF"
                    Text {
                        anchors.fill: parent
                        anchors.leftMargin: 3
                        verticalAlignment: Text.AlignVCenter
                        text: parent.label
                        elide: Text.ElideRight
                        font.family: dd.fontFamily
                        font.pixelSize: 12
                        color: parent.hl ? "#FFFFFF" : "#000000"
                    }
                    MouseArea {
                        id: hover
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: dd.select(parent.index)
                    }
                }
            }
        }
    }

    Keys.onPressed: function (event) {
        var n = items.count
        if (event.key === Qt.Key_Down && (event.modifiers & Qt.AltModifier)) { open = !open; event.accepted = true }
        else if (event.key === Qt.Key_Down && n) { currentIndex = Math.min(n - 1, currentIndex + 1); if (!open) activated(currentIndex); event.accepted = true }
        else if (event.key === Qt.Key_Up && n) { currentIndex = Math.max(0, currentIndex - 1); if (!open) activated(currentIndex); event.accepted = true }
        else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter) && open) { select(currentIndex); event.accepted = true }
        else if (event.key === Qt.Key_Escape && open) { open = false; event.accepted = true }
    }
    onActiveFocusChanged: if (!activeFocus) open = false
}
