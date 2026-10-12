import QtQuick

// Classic 3D border: raised (buttons, dialogs) or sunken (text fields). Two pixel lines per side.
Item {
    id: bevel
    property bool sunken: false
    property bool window: false          // dialog frame: light grey outer highlight
    property color face: "#D4D0C8"
    property color light: "#FFFFFF"
    property color mid: window ? "#D4D0C8" : "#FFFFFF"
    property color shadow: "#808080"
    property color dark: "#404040"

    readonly property color tl1: sunken ? shadow : (window ? mid : light)
    readonly property color tl2: sunken ? dark : (window ? light : face)
    readonly property color br1: sunken ? light : dark
    readonly property color br2: sunken ? face : shadow

    Rectangle { anchors.fill: parent; color: bevel.face }
    // outer lines
    Rectangle { x: 0; y: 0; width: parent.width; height: 1; color: bevel.tl1 }
    Rectangle { x: 0; y: 0; width: 1; height: parent.height; color: bevel.tl1 }
    Rectangle { x: 0; y: parent.height - 1; width: parent.width; height: 1; color: bevel.br1 }
    Rectangle { x: parent.width - 1; y: 0; width: 1; height: parent.height; color: bevel.br1 }
    // inner lines
    Rectangle { x: 1; y: 1; width: parent.width - 2; height: 1; color: bevel.tl2 }
    Rectangle { x: 1; y: 1; width: 1; height: parent.height - 2; color: bevel.tl2 }
    Rectangle { x: 1; y: parent.height - 2; width: parent.width - 2; height: 1; color: bevel.br2 }
    Rectangle { x: parent.width - 2; y: 1; width: 1; height: parent.height - 2; color: bevel.br2 }
}
