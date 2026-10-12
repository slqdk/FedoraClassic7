import QtQuick

// The logon banner: a small classic window picture, "Classic 7" and a thin colour band.
Item {
    id: banner
    property string fontFamily: "Noto Sans"
    height: 78

    Rectangle {
        anchors.fill: parent
        anchors.bottomMargin: 6
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#FFFFFF" }
            GradientStop { position: 0.55; color: "#FFFFFF" }
            GradientStop { position: 1.0; color: "#C9D6E8" }
        }
    }
    // picture: a little classic window
    Item {
        x: 22; y: 14
        width: 54; height: 44
        Rectangle { x: 3; y: 3; width: 54; height: 44; color: "#000000"; opacity: 0.2 }
        Bevel { anchors.fill: parent; window: true }
        Rectangle {
            x: 3; y: 3; width: parent.width - 6; height: 9
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0.0; color: "#0A246A" }
                GradientStop { position: 1.0; color: "#A6CAF0" }
            }
        }
        Rectangle { x: 5; y: 15; width: parent.width - 10; height: parent.height - 20; color: "#3A6EA5"; border.color: "#808080" }
        Rectangle { x: 9; y: 19; width: 16; height: 3; color: "#FFFFFF" }
        Rectangle { x: 9; y: 25; width: 26; height: 3; color: "#FFFFFF"; opacity: 0.8 }
        Rectangle { x: 9; y: 31; width: 20; height: 3; color: "#FFFFFF"; opacity: 0.6 }
    }
    Row {
        x: 92
        y: 13
        spacing: 6
        Text {
            text: "Classic"
            font.family: banner.fontFamily
            font.pixelSize: 30
            font.bold: true
            color: "#1E395B"
        }
        Text {
            text: "7"
            font.family: banner.fontFamily
            font.pixelSize: 30
            font.bold: true
            color: "#D86A1E"
        }
    }
    Text {
        x: 94
        y: 52
        text: "Built on Fedora Atomic · Bazzite"
        font.family: banner.fontFamily
        font.pixelSize: 11
        color: "#404040"
    }
    // colour band under the banner
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 6
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "#0A246A" }
            GradientStop { position: 0.5; color: "#3A6EA5" }
            GradientStop { position: 1.0; color: "#A6CAF0" }
        }
    }
}
