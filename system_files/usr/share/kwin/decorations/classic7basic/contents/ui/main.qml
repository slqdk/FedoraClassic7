/*
    Classic 7 window borders (Classic 7 Basic), laid out like Windows 7: the caption buttons hang from
    the top edge, the window icon and the title sit lower, in the middle of the title bar.
    The pictures are the SVG files in svgDir. Written by classic7aero.py: change it there.
*/
import QtQuick
import org.kde.kwin.decoration
import org.kde.ksvg 1.0 as KSvg

Decoration {
    id: root
    readonly property string svgDir: "/usr/share/aurorae/themes/Classic7Basic"
    readonly property bool hasGlow: false
    readonly property bool isMax: decoration.client.maximized
    readonly property int shadowPad: isMax ? 0 : 0
    readonly property int barHeight: isMax ? 23 : 30
    property alias decorationMask: maskItem.mask
    property alias supportsMask: backgroundSvg.supportsMask

    function has(list, value) {
        for (var i = 0; i < list.length; i++) {
            if (list[i] === value) {
                return true;
            }
        }
        return false;
    }

    Component.onCompleted: {
        borders.left = 8;
        borders.right = 8;
        borders.top = 30;
        borders.bottom = 8;
        maximizedBorders.left = 0;
        maximizedBorders.right = 0;
        maximizedBorders.top = 23;
        maximizedBorders.bottom = 0;
        padding.left = 0;
        padding.right = 0;
        padding.top = 0;
        padding.bottom = 0;
    }
    DecorationOptions {
        id: options
        deco: decoration
    }
    Item {
        // the title bar for dragging and double-clicks, where KWin expects it
        id: titleRect
        x: root.isMax ? 0 : 8
        y: 0
        width: decoration.client.width
        height: root.barHeight
        Component.onCompleted: decoration.installTitleItem(titleRect)
    }
    KSvg.FrameSvg {
        id: backgroundSvg
        property bool supportsInactive: hasElementPrefix("decoration-inactive")
        property bool supportsMask: hasElementPrefix("mask")
        property bool supportsMaximized: hasElementPrefix("decoration-maximized")
        property bool supportsMaximizedInactive: hasElementPrefix("decoration-maximized-inactive")
        imagePath: root.svgDir + "/decoration.svg"
    }
    KSvg.FrameSvgItem {
        id: decorationActive
        property bool shown: (!root.isMax || !backgroundSvg.supportsMaximized) && (decoration.client.active || !backgroundSvg.supportsInactive)
        anchors.fill: parent
        imagePath: backgroundSvg.imagePath
        prefix: "decoration"
        opacity: shown ? 1 : 0
        enabledBorders: root.isMax ? KSvg.FrameSvg.NoBorder : KSvg.FrameSvg.TopBorder | KSvg.FrameSvg.BottomBorder | KSvg.FrameSvg.LeftBorder | KSvg.FrameSvg.RightBorder
    }
    KSvg.FrameSvgItem {
        id: decorationInactive
        anchors.fill: parent
        imagePath: backgroundSvg.imagePath
        prefix: "decoration-inactive"
        opacity: (!decoration.client.active && backgroundSvg.supportsInactive) ? 1 : 0
        enabledBorders: root.isMax ? KSvg.FrameSvg.NoBorder : KSvg.FrameSvg.TopBorder | KSvg.FrameSvg.BottomBorder | KSvg.FrameSvg.LeftBorder | KSvg.FrameSvg.RightBorder
    }
    KSvg.FrameSvgItem {
        id: decorationMaximized
        property bool shown: root.isMax && backgroundSvg.supportsMaximized && (decoration.client.active || !backgroundSvg.supportsMaximizedInactive)
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        imagePath: backgroundSvg.imagePath
        prefix: "decoration-maximized"
        height: 23
        opacity: shown ? 1 : 0
        enabledBorders: KSvg.FrameSvg.NoBorder
    }
    KSvg.FrameSvgItem {
        id: decorationMaximizedInactive
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        imagePath: backgroundSvg.imagePath
        prefix: "decoration-maximized-inactive"
        height: 23
        opacity: (!decoration.client.active && root.isMax && backgroundSvg.supportsMaximizedInactive) ? 1 : 0
        enabledBorders: KSvg.FrameSvg.NoBorder
    }
    Row {
        // Minimize, Maximize and Close (the buttons chosen for the right side)
        id: buttonRow
        anchors.right: parent.right
        anchors.rightMargin: root.isMax ? 2 : root.shadowPad + 6
        y: root.isMax ? 0 : root.shadowPad + 1
        Repeater {
            model: options.titleButtonsRight
            delegate: CaptionButton {
                buttonType: modelData
                svgDir: root.svgDir
            }
        }
    }
    MenuButton {
        // the window icon: click for the window menu, double-click to close
        id: windowIcon
        visible: root.has(options.titleButtonsLeft, DecorationOptions.DecorationButtonMenu)
        width: 16
        height: 16
        x: root.isMax ? 4 : root.shadowPad + 8
        y: root.isMax ? 4 : root.shadowPad + 7
    }
    KSvg.FrameSvgItem {
        id: glow
        visible: root.hasGlow && caption.text.length > 0 && caption.width > 0
        imagePath: root.hasGlow ? root.svgDir + "/glow.svg" : ""
        x: caption.x - 12 - 2
        width: Math.min(caption.contentWidth, caption.width) + 2 * (12 + 2)
        height: root.isMax ? 23 : 28
        y: caption.y + Math.round((caption.height - height) / 2)
    }
    Text {
        id: caption
        text: decoration.client.caption
        textFormat: Text.PlainText
        elide: Text.ElideRight
        renderType: Text.NativeRendering
        font: options.titleFont
        color: decoration.client.active ? "#000000" : "#434E54"
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: Text.AlignLeft
        x: windowIcon.visible ? windowIcon.x + windowIcon.width + 6 : (root.isMax ? 4 : root.shadowPad + 8)
        width: Math.max(0, buttonRow.x - 6 - x)
        y: root.isMax ? 0 : root.shadowPad
        height: root.barHeight
    }
    KSvg.FrameSvgItem {
        // where KWin blurs behind the glass (the "mask" pieces of decoration.svg)
        id: maskItem
        anchors.fill: parent
        anchors.margins: 1
        imagePath: backgroundSvg.imagePath
        opacity: 0
        enabledBorders: KSvg.FrameSvg.TopBorder | KSvg.FrameSvg.BottomBorder | KSvg.FrameSvg.LeftBorder | KSvg.FrameSvg.RightBorder
    }
}
