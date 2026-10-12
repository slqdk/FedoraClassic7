import QtQuick
import org.kde.plasma.components as PC3
import org.kde.kirigami as Kirigami

// A blue text link, like the ones at the bottom of the Windows 7 network popup
PC3.Label {
    id: link
    signal clicked()
    color: Kirigami.Theme.linkColor
    font.underline: mouse.containsMouse
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: link.clicked()
    }
}
