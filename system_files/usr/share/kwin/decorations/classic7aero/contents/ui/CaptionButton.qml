/*
    A caption button (Minimize, Maximize/Restore, Close) drawn from <svgDir>/<kind>.svg.
    Written by classic7aero.py: change it there.
*/
import QtQuick
import org.kde.kwin.decoration
import org.kde.ksvg 1.0 as KSvg

DecorationButton {
    id: button
    property string svgDir
    readonly property string kind: {
        switch (buttonType) {
        case DecorationOptions.DecorationButtonMinimize:
            return "minimize";
        case DecorationOptions.DecorationButtonMaximizeRestore:
            return decoration.client.maximized ? "restore" : "maximize";
        case DecorationOptions.DecorationButtonClose:
            return "close";
        default:
            return "";
        }
    }
    visible: kind !== ""
    width: kind === "" ? 0 : (kind === "close" ? 47 : 27)
    height: 20
    KSvg.FrameSvgItem {
        anchors.fill: parent
        visible: button.kind !== ""
        imagePath: button.kind === "" ? "" : button.svgDir + "/" + button.kind + ".svg"
        prefix: {
            var a = decoration.client.active;
            if (!button.enabled) {
                return a ? "deactivated" : "deactivated-inactive";
            }
            if (button.pressed) {
                return a ? "pressed" : "pressed-inactive";
            }
            if (button.hovered) {
                return a ? "hover" : "hover-inactive";
            }
            return a ? "active" : "inactive";
        }
    }
}
