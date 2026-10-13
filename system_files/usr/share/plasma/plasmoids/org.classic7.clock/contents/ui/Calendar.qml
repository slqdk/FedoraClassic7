import QtQuick
import QtQuick.Layouts
import org.kde.plasma.components as PC3
import org.kde.kirigami as Kirigami

// The Windows 7 calendar: a month of days; clicking the title shows the months of the year,
// clicking again the years of the decade; the arrows page back and forward.
ColumnLayout {
    id: cal
    property date today: new Date()
    property int year: today.getFullYear()
    property int month: today.getMonth()      // 0-11
    property int decade: Math.floor(year / 10) * 10
    property string view: "month"             // month | year | decade
    property date selected: today
    readonly property var loc: Qt.locale()
    readonly property int cell: Kirigami.Units.gridUnit * 1.7
    spacing: Kirigami.Units.smallSpacing

    function showToday() {
        view = "month";
        year = today.getFullYear();
        month = today.getMonth();
        selected = today;
    }
    function page(step) {
        if (view === "month") {
            let m = month + step;
            year += Math.floor(m / 12);
            month = ((m % 12) + 12) % 12;
        } else if (view === "year") {
            year += step;
        } else {
            decade += 10 * step;
        }
    }
    function title() {
        if (view === "month") return loc.standaloneMonthName(month, Locale.LongFormat) + " " + year;
        if (view === "year") return String(year);
        return decade + " - " + (decade + 9);
    }
    function sameDay(a, b) {
        return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
    }
    // the 42 days shown for the month, starting on the locale's first day of the week
    function days() {
        const first = new Date(year, month, 1);
        const offset = (first.getDay() - loc.firstDayOfWeek + 7) % 7;
        const start = new Date(year, month, 1 - (offset === 0 ? 7 : offset));
        const out = [];
        for (let i = 0; i < 42; i++) {
            out.push(new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
        }
        return out;
    }

    RowLayout {
        Layout.fillWidth: true
        PC3.ToolButton {
            icon.name: "go-previous"
            display: PC3.AbstractButton.IconOnly
            onClicked: cal.page(-1)
            Accessible.name: i18n("Previous")
        }
        PC3.ToolButton {
            Layout.fillWidth: true
            text: cal.title()
            font.bold: true
            onClicked: cal.view = cal.view === "month" ? "year" : "decade"
        }
        PC3.ToolButton {
            icon.name: "go-next"
            display: PC3.AbstractButton.IconOnly
            onClicked: cal.page(1)
            Accessible.name: i18n("Next")
        }
    }

    // ---- days --------------------------------------------------------------------------
    GridLayout {
        visible: cal.view === "month"
        columns: 7
        rowSpacing: 0
        columnSpacing: 0
        Repeater {
            model: 7
            PC3.Label {
                Layout.preferredWidth: cal.cell
                horizontalAlignment: Text.AlignHCenter
                text: cal.loc.dayName((cal.loc.firstDayOfWeek + index) % 7, Locale.ShortFormat).substring(0, 2)
                opacity: 0.7
            }
        }
        Repeater {
            model: cal.view === "month" ? cal.days() : []
            Rectangle {
                required property var modelData
                readonly property bool inMonth: modelData.getMonth() === cal.month
                readonly property bool isToday: cal.sameDay(modelData, cal.today)
                readonly property bool isSelected: cal.sameDay(modelData, cal.selected)
                Layout.preferredWidth: cal.cell
                Layout.preferredHeight: cal.cell * 0.82
                color: isSelected ? Qt.rgba(0.80, 0.90, 0.99, 1) : (dayMouse.containsMouse ? Qt.rgba(0.90, 0.95, 1, 1) : "transparent")
                border.color: isToday ? "#3399ff" : (isSelected ? "#99ccff" : "transparent")
                border.width: 1
                PC3.Label {
                    anchors.centerIn: parent
                    text: modelData.getDate()
                    opacity: inMonth ? 1 : 0.4
                }
                MouseArea {
                    id: dayMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        cal.selected = modelData;
                        if (!inMonth) {
                            cal.year = modelData.getFullYear();
                            cal.month = modelData.getMonth();
                        }
                    }
                }
            }
        }
    }

    // ---- months of the year, years of the decade --------------------------------------
    GridLayout {
        visible: cal.view !== "month"
        columns: 4
        rowSpacing: Kirigami.Units.smallSpacing
        columnSpacing: Kirigami.Units.smallSpacing
        Repeater {
            model: cal.view === "year" ? 12 : (cal.view === "decade" ? 12 : 0)
            Rectangle {
                required property int index
                readonly property int value: cal.view === "year" ? index : cal.decade - 1 + index
                readonly property bool current: cal.view === "year" ? (value === cal.today.getMonth() && cal.year === cal.today.getFullYear())
                                                                    : value === cal.today.getFullYear()
                readonly property bool outside: cal.view === "decade" && (index === 0 || index === 11)
                Layout.preferredWidth: cal.cell * 1.75 - Kirigami.Units.smallSpacing
                Layout.preferredHeight: cal.cell * 1.4
                color: cellMouse.containsMouse ? Qt.rgba(0.90, 0.95, 1, 1) : "transparent"
                border.color: current ? "#3399ff" : "transparent"
                PC3.Label {
                    anchors.centerIn: parent
                    text: cal.view === "year" ? cal.loc.standaloneMonthName(value, Locale.ShortFormat) : value
                    opacity: outside ? 0.4 : 1
                }
                MouseArea {
                    id: cellMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        if (cal.view === "year") {
                            cal.month = value;
                            cal.view = "month";
                        } else {
                            cal.year = value;
                            cal.decade = Math.floor(value / 10) * 10;
                            cal.view = "year";
                        }
                    }
                }
            }
        }
    }
}
