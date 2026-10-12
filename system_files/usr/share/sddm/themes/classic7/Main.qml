import QtQuick

// Classic 7 login screen: the classic "Log On" dialog on the desktop colour.
// SDDM gives us: sddm (login, powerOff, reboot, suspend, hibernate, can*), userModel,
// sessionModel, keyboard (capsLock) and config (theme.conf).
Rectangle {
    id: root
    width: 1024
    height: 768
    color: config.background || "#3A6EA5"

    readonly property string fam: config.font || "Noto Sans"
    property bool showOptions: false
    property bool busy: false

    function login() {
        if (userField.text.trim() === "")
            return
        busy = true
        message.visible = false
        sddm.login(userField.text.trim(), passwordField.text, sessionList.currentIndex)
    }
    function cancel() {
        passwordField.text = ""
        userList.open = false
        passwordField.forceActiveFocus()
    }
    function realName(i) {
        return i >= 0 && i < users.count && users.itemAt(i) ? users.itemAt(i).user : ""
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.busy = false
            passwordField.text = ""
            message.text = "The system could not log you on. Make sure your User name and password are correct, "
                         + "then type your password again. Letters in passwords must be typed using the correct case."
            message.visible = true
            messageOk.forceActiveFocus()
        }
        function onLoginSucceeded() { root.busy = true }
        function onInformationMessage(msg) {
            message.text = msg
            message.visible = true
            messageOk.forceActiveFocus()
        }
    }

    // user names from SDDM, used by the user list
    Repeater {
        id: users
        model: userModel
        delegate: Item {
            required property var model
            readonly property string user: model.name
            readonly property string label: model.realName && model.realName !== model.name
                                            ? model.realName + " (" + model.name + ")" : model.name
        }
    }

    // ---- Log On dialog ---------------------------------------------------------------------
    ClassicDialog {
        id: logon
        anchors.centerIn: parent
        fontFamily: root.fam
        title: config.title || "Log On to Classic 7"
        active: !message.visible && !shutdown.visible
        contentWidth: 420
        contentHeight: banner.height + form.height + 14
        enabled: !root.busy

        Banner { id: banner; width: 420; fontFamily: root.fam }

        Item {
            id: form
            y: banner.height + 10
            width: 420
            height: buttons.y + buttons.height + 2

            readonly property int labelW: 92
            readonly property int fieldX: 100
            readonly property int fieldW: 300

            Text {
                x: 10; y: 12
                text: "Copyright © Classic 7 contributors. Fedora and Bazzite are their projects' marks."
                visible: false
            }

            Text { x: 10; y: 4; height: 21; verticalAlignment: Text.AlignVCenter
                   text: "<u>U</u>ser name:"; textFormat: Text.StyledText
                   font.family: root.fam; font.pixelSize: 12 }
            ClassicField {
                id: userField
                x: form.fieldX; y: 4; width: form.fieldW - 18
                fontFamily: root.fam
                text: userModel.lastUser || root.realName(0)
                KeyNavigation.tab: passwordField
                onAccepted: passwordField.forceActiveFocus()
            }
            // arrow button with the list of accounts on this computer
            Item {
                x: form.fieldX + form.fieldW - 18; y: 4
                width: 18; height: 21
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
                MouseArea { id: arrowMouse; anchors.fill: parent; onClicked: userList.open = !userList.open }
            }

            Text { x: 10; y: 32; height: 21; verticalAlignment: Text.AlignVCenter
                   text: "<u>P</u>assword:"; textFormat: Text.StyledText
                   font.family: root.fam; font.pixelSize: 12 }
            ClassicField {
                id: passwordField
                x: form.fieldX; y: 32; width: form.fieldW
                fontFamily: root.fam
                echoMode: TextInput.Password
                focus: true
                KeyNavigation.backtab: userField
                KeyNavigation.tab: root.showOptions ? sessionList : okButton
                onAccepted: root.login()
            }
            Text {
                x: form.fieldX; y: 56
                visible: keyboard.capsLock
                text: "⚠  Caps Lock is on."
                font.family: root.fam; font.pixelSize: 11
                color: "#800000"
            }

            Text { x: 10; y: 74; height: 21; verticalAlignment: Text.AlignVCenter
                   visible: root.showOptions
                   text: "<u>S</u>ession:"; textFormat: Text.StyledText
                   font.family: root.fam; font.pixelSize: 12 }
            ClassicDropDown {
                id: sessionList
                x: form.fieldX; y: 74; width: form.fieldW
                visible: root.showOptions
                fontFamily: root.fam
                model: sessionModel
                textRole: "name"
                currentIndex: sessionModel.lastIndex >= 0 ? sessionModel.lastIndex : 0
                KeyNavigation.tab: okButton
            }

            Row {
                id: buttons
                anchors.right: parent.right
                anchors.rightMargin: 10
                y: root.showOptions ? 108 : 76
                spacing: 6
                ClassicButton { id: okButton; text: "OK"; isDefault: true; fontFamily: root.fam
                                onClicked: root.login(); KeyNavigation.tab: cancelButton }
                ClassicButton { id: cancelButton; text: "Cancel"; fontFamily: root.fam
                                onClicked: root.cancel(); KeyNavigation.tab: shutdownButton }
                ClassicButton { id: shutdownButton; text: "Shut Down..."; fontFamily: root.fam
                                onClicked: shutdown.show(); KeyNavigation.tab: optionsButton }
                ClassicButton { id: optionsButton; text: root.showOptions ? "Options <<" : "Options >>"
                                fontFamily: root.fam; KeyNavigation.tab: userField
                                onClicked: root.showOptions = !root.showOptions }
            }

            // account list (over the other fields)
            Rectangle {
                id: userList
                property bool open: false
                visible: open
                z: 100
                x: form.fieldX; y: 4 + 21
                width: form.fieldW
                height: userColumn.height + 2
                color: "#FFFFFF"
                border.color: "#000000"
                Column {
                    id: userColumn
                    x: 1; y: 1
                    width: parent.width - 2
                    Repeater {
                        model: userModel
                        delegate: Rectangle {
                            required property var model
                            width: userColumn.width
                            height: 18
                            color: hov.containsMouse ? "#0A246A" : "#FFFFFF"
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 3
                                verticalAlignment: Text.AlignVCenter
                                text: model.realName && model.realName !== model.name
                                      ? model.realName + " (" + model.name + ")" : model.name
                                font.family: root.fam; font.pixelSize: 12
                                color: hov.containsMouse ? "#FFFFFF" : "#000000"
                            }
                            MouseArea {
                                id: hov
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: {
                                    userField.text = model.name
                                    userList.open = false
                                    passwordField.text = ""
                                    passwordField.forceActiveFocus()
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // ---- Shut Down dialog ------------------------------------------------------------------
    ListModel { id: powerActions }
    ClassicDialog {
        id: shutdown
        objectName: "shutdown"
        visible: false
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 40
        fontFamily: root.fam
        title: "Shut Down Classic 7"
        contentWidth: 380
        contentHeight: 150

        function show() {
            powerActions.clear()
            if (sddm.canPowerOff) powerActions.append({ name: "Shut down", key: "poweroff",
                text: "Ends your session and shuts down the computer so that you can safely turn off the power." })
            if (sddm.canReboot) powerActions.append({ name: "Restart", key: "reboot",
                text: "Ends your session, shuts down the computer and starts it again." })
            if (sddm.canSuspend) powerActions.append({ name: "Sleep", key: "suspend",
                text: "Keeps your work in memory and puts the computer in a low-power state." })
            if (sddm.canHibernate) powerActions.append({ name: "Hibernate", key: "hibernate",
                text: "Saves your work to disk and turns off the computer." })
            powerList.currentIndex = 0
            visible = true
            powerList.forceActiveFocus()
        }
        function run() {
            var k = powerList.currentKey
            visible = false
            if (k === "poweroff") sddm.powerOff()
            else if (k === "reboot") sddm.reboot()
            else if (k === "suspend") sddm.suspend()
            else if (k === "hibernate") sddm.hibernate()
        }

        // power icon: a classic monitor with a red button
        Item {
            x: 12; y: 12; width: 40; height: 40
            Bevel { x: 2; y: 0; width: 36; height: 28 }
            Rectangle { x: 6; y: 4; width: 28; height: 20; color: "#000080" }
            Rectangle { x: 12; y: 28; width: 16; height: 4; color: "#808080" }
            Rectangle { x: 6; y: 32; width: 28; height: 5; color: "#C0C0C0"; border.color: "#808080" }
            Rectangle { x: 28; y: 33; width: 4; height: 3; color: "#C00000" }
        }
        Text { x: 64; y: 12; text: "What do you want the computer to do?"
               font.family: root.fam; font.pixelSize: 12 }
        ClassicDropDown {
            id: powerList
            objectName: "powerList"
            x: 64; y: 32; width: 300
            fontFamily: root.fam
            model: powerActions
            textRole: "name"
            keyRole: "key"
            KeyNavigation.tab: powerOk
        }
        Text {
            x: 64; y: 60; width: 300
            wrapMode: Text.WordWrap
            text: powerActions.count > powerList.currentIndex && powerList.currentIndex >= 0
                  ? powerActions.get(powerList.currentIndex).text : ""
            font.family: root.fam; font.pixelSize: 11
            color: "#000000"
        }
        Row {
            anchors.right: parent.right
            anchors.rightMargin: 10
            y: 118
            spacing: 6
            ClassicButton { id: powerOk; text: "OK"; isDefault: true; fontFamily: root.fam
                            onClicked: shutdown.run(); KeyNavigation.tab: powerCancel }
            ClassicButton { id: powerCancel; text: "Cancel"; fontFamily: root.fam
                            onClicked: { shutdown.visible = false; passwordField.forceActiveFocus() }
                            KeyNavigation.tab: powerList }
        }
        Keys.onEscapePressed: { visible = false; passwordField.forceActiveFocus() }
    }

    // ---- Logon Message box -----------------------------------------------------------------
    ClassicDialog {
        id: message
        property alias text: messageText.text
        visible: false
        anchors.centerIn: parent
        anchors.verticalCenterOffset: 30
        fontFamily: root.fam
        title: "Logon Message"
        contentWidth: 420
        contentHeight: Math.max(48, messageText.height) + 56

        // the classic error icon: a red circle with a white cross
        Rectangle {
            x: 14; y: 14; width: 32; height: 32; radius: 16
            color: "#E00000"; border.color: "#800000"
            Text { anchors.centerIn: parent; text: "✕"; color: "#FFFFFF"
                   font.pixelSize: 18; font.bold: true }
        }
        Text {
            id: messageText
            x: 60; y: 14; width: 345
            wrapMode: Text.WordWrap
            font.family: root.fam; font.pixelSize: 12
        }
        ClassicButton {
            id: messageOk
            text: "OK"; isDefault: true; fontFamily: root.fam
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(48, messageText.height) + 24
            onClicked: { message.visible = false; passwordField.forceActiveFocus() }
        }
        Keys.onEscapePressed: { visible = false; passwordField.forceActiveFocus() }
    }

    // keyboard shortcuts of the classic dialog: Alt+U, Alt+P, Alt+S, Esc
    Shortcut { sequence: "Alt+U"; onActivated: userField.forceActiveFocus() }
    Shortcut { sequence: "Alt+P"; onActivated: passwordField.forceActiveFocus() }
    Shortcut { sequence: "Alt+S"; onActivated: { root.showOptions = true; sessionList.forceActiveFocus() } }
    Shortcut { sequence: "Esc"; enabled: !message.visible && !shutdown.visible && !userList.open
               onActivated: root.cancel() }

    Component.onCompleted: {
        if (userField.text === "")
            userField.forceActiveFocus()
        else
            passwordField.forceActiveFocus()
    }
}
