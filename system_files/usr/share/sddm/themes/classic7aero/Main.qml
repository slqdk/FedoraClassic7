import QtQuick

// Classic 7 login screen for Aero and Basic: the Windows 7 Welcome screen. The account picture in
// its glass frame with the name and the password box under it (several accounts: a row of pictures
// to choose from first), "Welcome" while logging on, the red power button with its menu at the
// bottom right, the keyboard layout at the bottom left and the name at the bottom.
// SDDM gives us: sddm (login, powerOff, reboot, suspend, hibernate, can*), userModel,
// sessionModel, keyboard (capsLock, layouts, currentLayout) and config (theme.conf).
Item {
    id: root
    width: 1024
    height: 768

    readonly property string fam: config.font || "Noto Sans"
    readonly property bool several: userModel.count > 1
    // -1: the list of accounts; otherwise the chosen account
    property int chosen: -1
    // "", "welcome" (logging on) or "failed"
    property string phase: ""

    // one account: straight to its password; several: their pictures first, as Windows 7
    function startIndex() {
        return userModel.count === 1 ? 0 : -1
    }
    function choose(i) {
        chosen = i
        phase = ""
        password.text = ""
        if (i >= 0)
            password.forceActiveFocus()
        else
            listFocus.forceActiveFocus()
    }
    function login() {
        if (chosen < 0 || !users.itemAt(chosen))
            return
        phase = "welcome"
        sddm.login(users.itemAt(chosen).name, password.text,
                   sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0)
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.phase = "failed"
            password.text = ""
            failedOk.forceActiveFocus()
        }
        function onLoginSucceeded() { root.phase = "welcome" }
    }

    // the accounts (name, real name and picture), for the tiles and the logon
    Repeater {
        id: users
        model: userModel
        delegate: Item {
            required property var model
            readonly property string name: model.name
            readonly property string label: model.realName ? model.realName : model.name
            // SDDM's grey stand-in (sddm/faces/.face.icon) counts as no picture: ours is drawn instead
            readonly property string icon: model.icon && model.icon.indexOf("/sddm/faces/.face.icon") < 0 ? model.icon : ""
        }
    }

    // ---- background ------------------------------------------------------------------------
    Rectangle { anchors.fill: parent; color: config.color || "#1C5A9E" }
    Image {
        anchors.fill: parent
        source: config.background ? (config.background.indexOf("/") === 0 ? "file://" + config.background
                                                                          : config.background) : ""
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        smooth: true
    }

    // ---- pieces ----------------------------------------------------------------------------
    // the account picture in Windows 7's glass frame; a plain figure when there is no picture
    component Tile: Item {
        id: tile
        property string icon
        property int size: 126
        property bool lit: false
        width: size + 24
        height: size + 24
        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: 11
            color: "#5FC4FF"
            opacity: tile.lit ? 0.45 : 0
        }
        Rectangle {
            anchors.fill: parent
            radius: 8
            border.color: Qt.rgba(1, 1, 1, 0.75)
            border.width: 1
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.62) }
                GradientStop { position: 0.45; color: Qt.rgba(1, 1, 1, 0.30) }
                GradientStop { position: 0.55; color: Qt.rgba(1, 1, 1, 0.16) }
                GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.34) }
            }
        }
        Rectangle {
            id: well
            anchors.centerIn: parent
            width: tile.size + 2
            height: tile.size + 2
            color: "#30000000"
            border.color: Qt.rgba(0, 0, 0, 0.35)
        }
        Item {
            anchors.centerIn: parent
            width: tile.size
            height: tile.size
            clip: true
            // no picture: a figure on blue, like Windows 7's generic account picture
            Rectangle {
                anchors.fill: parent
                visible: picture.status !== Image.Ready
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#9FD4F5" }
                    GradientStop { position: 1.0; color: "#2F7FC4" }
                }
                Rectangle {
                    width: parent.width * 0.34; height: width; radius: width / 2
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height * 0.18
                    color: "#EAF6FF"
                }
                Rectangle {
                    width: parent.width * 0.62; height: parent.height * 0.42
                    radius: width * 0.42
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: parent.height * 0.58
                    color: "#EAF6FF"
                }
            }
            Image {
                id: picture
                anchors.fill: parent
                source: tile.icon ? (tile.icon.indexOf("/") === 0 ? "file://" + tile.icon : tile.icon) : ""
                fillMode: Image.PreserveAspectCrop
                sourceSize.width: tile.size * 2
                sourceSize.height: tile.size * 2
                smooth: true
            }
        }
    }

    // a round glossy button (the blue arrow after the password, the red power button)
    component Orb: Item {
        id: orb
        // not "top"/"bottom": those are Item properties that can't be redefined
        property color hiColor: "#7CC4F5"
        property color loColor: "#1663B3"
        property string glyph: "arrow"
        property bool down: area.pressed && area.containsMouse
        signal clicked()
        width: 30
        height: 30
        activeFocusOnTab: true
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            border.color: Qt.rgba(0, 0, 0, 0.55)
            gradient: Gradient {
                GradientStop { position: 0.0; color: orb.down ? Qt.darker(orb.hiColor, 1.25) : (area.containsMouse ? Qt.lighter(orb.hiColor, 1.12) : orb.hiColor) }
                GradientStop { position: 0.5; color: orb.down ? Qt.darker(orb.loColor, 1.2) : (area.containsMouse ? Qt.lighter(orb.loColor, 1.15) : orb.loColor) }
                GradientStop { position: 1.0; color: orb.down ? Qt.darker(orb.hiColor, 1.35) : orb.hiColor }
            }
        }
        Rectangle {
            x: parent.width * 0.18; y: 2
            width: parent.width * 0.64; height: parent.height * 0.42
            radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.38)
        }
        Rectangle {
            anchors.fill: parent
            anchors.margins: -2
            radius: width / 2
            color: "transparent"
            border.color: Qt.rgba(1, 1, 1, 0.8)
            border.width: 1
            visible: orb.activeFocus
        }
        Canvas {
            anchors.fill: parent
            onPaint: {
                var c = getContext("2d")
                var w = width, h = height
                c.reset()
                c.strokeStyle = "#FFFFFF"
                c.fillStyle = "#FFFFFF"
                c.lineWidth = Math.max(2, w / 11)
                c.lineCap = "round"
                if (orb.glyph === "arrow") {
                    c.beginPath(); c.moveTo(w * 0.27, h / 2); c.lineTo(w * 0.70, h / 2); c.stroke()
                    c.beginPath(); c.moveTo(w * 0.52, h * 0.31); c.lineTo(w * 0.72, h / 2); c.lineTo(w * 0.52, h * 0.69); c.stroke()
                } else {
                    c.beginPath(); c.arc(w / 2, h / 2 + 1, w * 0.24, -Math.PI * 0.32, Math.PI * 1.32, false); c.stroke()
                    c.beginPath(); c.moveTo(w / 2, h * 0.20); c.lineTo(w / 2, h * 0.50); c.stroke()
                }
            }
        }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            onClicked: orb.clicked()
        }
        Keys.onReturnPressed: orb.clicked()
        Keys.onEnterPressed: orb.clicked()
        Keys.onSpacePressed: orb.clicked()
    }

    // a Windows 7 push button (OK)
    component PushButton: Item {
        id: push
        property alias text: label.text
        signal clicked()
        implicitWidth: Math.max(86, label.implicitWidth + 30)
        implicitHeight: 26
        activeFocusOnTab: true
        Rectangle {
            anchors.fill: parent
            radius: 3
            border.color: push.activeFocus ? "#3C7FB1" : "#707070"
            gradient: Gradient {
                GradientStop { position: 0.0; color: hover.containsMouse ? "#EAF6FD" : "#F2F2F2" }
                GradientStop { position: 0.5; color: hover.containsMouse ? "#D9F0FC" : "#EBEBEB" }
                GradientStop { position: 0.51; color: hover.containsMouse ? "#BEE6FD" : "#DDDDDD" }
                GradientStop { position: 1.0; color: hover.containsMouse ? "#A7D9F5" : "#CFCFCF" }
            }
        }
        Text {
            id: label
            anchors.centerIn: parent
            font.family: config.font || "Noto Sans"
            font.pixelSize: 13
            color: "#000000"
        }
        MouseArea { id: hover; anchors.fill: parent; hoverEnabled: true; onClicked: push.clicked() }
        Keys.onReturnPressed: push.clicked()
        Keys.onEnterPressed: push.clicked()
        Keys.onSpacePressed: push.clicked()
    }

    // ---- the accounts to choose from (more than one, none chosen yet) ----------------------
    FocusScope {
        id: listFocus
        anchors.fill: parent
        visible: root.chosen < 0
        property int current: Math.max(0, userModel.lastIndex)
        Keys.onLeftPressed: current = Math.max(0, current - 1)
        Keys.onRightPressed: current = Math.min(userModel.count - 1, current + 1)
        Keys.onReturnPressed: root.choose(current)
        Keys.onEnterPressed: root.choose(current)
        Row {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -30
            spacing: 34
            Repeater {
                model: userModel
                delegate: Column {
                    required property var model
                    required property int index
                    spacing: 10
                    Tile {
                        icon: model.icon && model.icon.indexOf("/sddm/faces/.face.icon") < 0 ? model.icon : ""
                        size: 96
                        lit: tileArea.containsMouse || (listFocus.activeFocus && listFocus.current === index)
                        anchors.horizontalCenter: parent.horizontalCenter
                        MouseArea {
                            id: tileArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.choose(index)
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: model.realName ? model.realName : model.name
                        font.family: root.fam
                        font.pixelSize: 17
                        color: "#FFFFFF"
                        style: Text.Raised
                        styleColor: "#40000000"
                    }
                }
            }
        }
    }

    // ---- the chosen account ----------------------------------------------------------------
    Column {
        id: one
        visible: root.chosen >= 0
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -40
        spacing: 12

        Tile {
            anchors.horizontalCenter: parent.horizontalCenter
            icon: root.chosen >= 0 && users.itemAt(root.chosen) ? users.itemAt(root.chosen).icon : ""
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.chosen >= 0 && users.itemAt(root.chosen) ? users.itemAt(root.chosen).label : ""
            font.family: root.fam
            font.pixelSize: 26
            color: "#FFFFFF"
            style: Text.Raised
            styleColor: "#50000000"
        }
        Item { width: 1; height: 4 }

        // the password box and the arrow
        Item {
            id: entry
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.phase === ""
            width: 232 + 8 + 30
            height: 30
            Rectangle {
                id: box
                width: 232
                height: 26
                y: 2
                radius: 2
                color: "#FFFFFF"
                border.color: password.activeFocus ? "#3D7BAD" : "#8E8F8F"
                TextInput {
                    id: password
                    anchors.fill: parent
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    verticalAlignment: TextInput.AlignVCenter
                    echoMode: TextInput.Password
                    passwordCharacter: "●"
                    font.family: root.fam
                    font.pixelSize: 13
                    color: "#000000"
                    selectionColor: "#3399FF"
                    clip: true
                    focus: true
                    onAccepted: root.login()
                    Keys.onEscapePressed: {
                        if (password.text !== "")
                            password.text = ""
                        else if (root.several)
                            root.choose(-1)
                    }
                }
                Text {
                    anchors.fill: parent
                    anchors.leftMargin: 7
                    verticalAlignment: Text.AlignVCenter
                    visible: password.text === ""
                    text: "Password"
                    font.family: root.fam
                    font.pixelSize: 13
                    font.italic: true
                    color: "#6D6D6D"
                }
            }
            Orb {
                x: box.width + 8
                onClicked: root.login()
            }
        }
        // Caps Lock, as Windows says it under the box
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.phase === "" && keyboard.capsLock
            width: capsText.implicitWidth + 40
            height: 28
            radius: 4
            color: "#FFFFE1"
            border.color: "#767676"
            Text {
                x: 10
                anchors.verticalCenter: parent.verticalCenter
                text: "⚠"
                font.pixelSize: 14
                color: "#C08000"
            }
            Text {
                id: capsText
                x: 30
                anchors.verticalCenter: parent.verticalCenter
                text: "Caps Lock is on."
                font.family: root.fam
                font.pixelSize: 12
                color: "#000000"
            }
        }

        // "Welcome" while logging on
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.phase === "welcome"
            spacing: 14
            Item {
                width: 30; height: 30
                anchors.verticalCenter: parent.verticalCenter
                Repeater {
                    model: 8
                    delegate: Rectangle {
                        required property int index
                        width: 5; height: 5; radius: 2.5
                        color: "#FFFFFF"
                        opacity: 0.25 + 0.75 * (((index - spinner.step) % 8 + 8) % 8) / 7
                        x: 12.5 + 12 * Math.cos(index * Math.PI / 4)
                        y: 12.5 + 12 * Math.sin(index * Math.PI / 4)
                    }
                }
                Timer {
                    id: spinner
                    property int step: 0
                    interval: 110
                    repeat: true
                    running: root.phase === "welcome"
                    onTriggered: step = (step + 1) % 8
                }
            }
            Text {
                text: "Welcome"
                font.family: root.fam
                font.pixelSize: 30
                color: "#FFFFFF"
                style: Text.Raised
                styleColor: "#50000000"
            }
        }

        // a refused logon
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: root.phase === "failed"
            spacing: 16
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "The user name or password is incorrect."
                font.family: root.fam
                font.pixelSize: 16
                color: "#FFFFFF"
                style: Text.Raised
                styleColor: "#50000000"
            }
            PushButton {
                id: failedOk
                anchors.horizontalCenter: parent.horizontalCenter
                text: "OK"
                onClicked: { root.phase = ""; password.forceActiveFocus() }
                Keys.onEscapePressed: clicked()
            }
        }
    }

    // back to the accounts (more than one)
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: brand.top
        anchors.bottomMargin: 34
        visible: root.several && root.chosen >= 0 && root.phase !== "welcome"
        width: switchText.implicitWidth + 34
        height: 30
        radius: 4
        color: switchArea.containsMouse ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(1, 1, 1, 0.08)
        border.color: Qt.rgba(1, 1, 1, switchArea.containsMouse ? 0.75 : 0.45)
        Text {
            id: switchText
            anchors.centerIn: parent
            text: "Switch User"
            font.family: root.fam
            font.pixelSize: 14
            color: "#FFFFFF"
        }
        MouseArea { id: switchArea; anchors.fill: parent; hoverEnabled: true; onClicked: root.choose(-1) }
    }

    // ---- bottom of the screen --------------------------------------------------------------
    // the keyboard layout (only with more than one), click for the next
    Rectangle {
        x: 26
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30
        visible: keyboard.layouts.length > 1
        width: 40; height: 26
        radius: 3
        color: layoutArea.containsMouse ? Qt.rgba(1, 1, 1, 0.25) : Qt.rgba(1, 1, 1, 0.12)
        border.color: Qt.rgba(1, 1, 1, 0.5)
        Text {
            anchors.centerIn: parent
            text: keyboard.layouts.length > keyboard.currentLayout && keyboard.currentLayout >= 0
                  ? keyboard.layouts[keyboard.currentLayout].shortName.toUpperCase() : ""
            font.family: root.fam
            font.pixelSize: 13
            font.bold: true
            color: "#FFFFFF"
        }
        MouseArea {
            id: layoutArea
            anchors.fill: parent
            hoverEnabled: true
            onClicked: keyboard.currentLayout = (keyboard.currentLayout + 1) % keyboard.layouts.length
        }
    }

    // the name of the system, where Windows 7 shows its logo
    Row {
        id: brand
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 34
        spacing: 12
        Image {
            source: "file:///usr/share/classic7/start-orb.svg"
            sourceSize.height: 44
            fillMode: Image.PreserveAspectFit
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: config.title || "Classic 7"
            font.family: root.fam
            font.pixelSize: 30
            font.weight: Font.Light
            color: "#FFFFFF"
            anchors.verticalCenter: parent.verticalCenter
            style: Text.Raised
            styleColor: "#40000000"
        }
    }

    // the power button: shuts down; the arrow beside it has Restart, Sleep and Hibernate too
    ListModel { id: powerActions }
    Row {
        id: power
        anchors.right: parent.right
        anchors.rightMargin: 30
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30
        spacing: 3
        visible: sddm.canPowerOff || sddm.canReboot
        Orb {
            width: 32; height: 32
            hiColor: "#F08A73"; loColor: "#B5250F"
            glyph: "power"
            onClicked: sddm.canPowerOff ? sddm.powerOff() : sddm.reboot()
        }
        Rectangle {
            width: 18; height: 32
            radius: 4
            border.color: Qt.rgba(0, 0, 0, 0.55)
            gradient: Gradient {
                GradientStop { position: 0.0; color: menuArea.containsMouse ? "#F6A28E" : "#F08A73" }
                GradientStop { position: 0.5; color: menuArea.containsMouse ? "#CB3A20" : "#B5250F" }
                GradientStop { position: 1.0; color: "#E07A63" }
            }
            Text {
                anchors.centerIn: parent
                text: "▸"
                font.pixelSize: 12
                color: "#FFFFFF"
            }
            MouseArea {
                id: menuArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    powerActions.clear()
                    if (sddm.canReboot) powerActions.append({ name: "Restart", key: "reboot" })
                    if (sddm.canSuspend) powerActions.append({ name: "Sleep", key: "suspend" })
                    if (sddm.canHibernate) powerActions.append({ name: "Hibernate", key: "hibernate" })
                    if (sddm.canPowerOff) powerActions.append({ name: "Shut down", key: "poweroff" })
                    powerMenu.visible = !powerMenu.visible
                }
            }
        }
    }
    Rectangle {
        id: powerMenu
        visible: false
        anchors.right: power.right
        anchors.bottom: power.top
        anchors.bottomMargin: 6
        width: 150
        height: menuColumn.height + 6
        color: "#F0F0F0"
        border.color: "#979797"
        Column {
            id: menuColumn
            x: 3; y: 3
            width: parent.width - 6
            Repeater {
                model: powerActions
                delegate: Rectangle {
                    required property var model
                    width: menuColumn.width
                    height: 24
                    radius: 3
                    color: itemArea.containsMouse ? "#DCEBFC" : "transparent"
                    border.color: itemArea.containsMouse ? "#7DA2CE" : "transparent"
                    Text {
                        x: 28
                        anchors.verticalCenter: parent.verticalCenter
                        text: model.name
                        font.family: root.fam
                        font.pixelSize: 13
                        color: "#000000"
                    }
                    MouseArea {
                        id: itemArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            powerMenu.visible = false
                            if (model.key === "reboot") sddm.reboot()
                            else if (model.key === "suspend") sddm.suspend()
                            else if (model.key === "hibernate") sddm.hibernate()
                            else if (model.key === "poweroff") sddm.powerOff()
                        }
                    }
                }
            }
        }
    }

    Component.onCompleted: root.choose(root.startIndex())
}
