"""Mail: Outlook 2007 colours and the small widgets shared by the windows."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSizePolicy, QToolButton, QWidget

APP = "Mail"

# Office 2007 "Blue"
FRAME = "#BFDBFF"
TITLE = "#15428B"
BORDER = "#6593CF"
HEADER_TOP = "#E3EFFF"
HEADER_BOTTOM = "#AFD2FF"
TOOLBAR_TOP = "#E3EFFF"
TOOLBAR_BOTTOM = "#C4DDFF"
SELECT = "#C2DCFD"
SELECT_BORDER = "#7DA2CE"
SELECT_INACTIVE = "#E2E2E2"
HOT_TOP, HOT_BOTTOM = "#FFFCD9", "#FFE6A0"
ON_TOP, ON_BOTTOM = "#FFD98C", "#FFB843"
GROUP_LINE = "#A5BFE1"
UNREAD_COUNT = "#0000FF"

STYLE = f"""
QMainWindow, QDialog#mailDialog {{ background: {FRAME}; }}
QMainWindow::separator {{ background: {FRAME}; width: 5px; height: 5px; }}
QSplitter::handle {{ background: {FRAME}; }}
QToolBar#standard {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {TOOLBAR_TOP}, stop:1 {TOOLBAR_BOTTOM});
    border: none; border-bottom: 1px solid {BORDER}; spacing: 1px; padding: 2px 3px;
}}
QToolBar#standard QToolButton {{ border: 1px solid transparent; border-radius: 2px; padding: 1px 3px; color: #000; }}
QToolBar#standard QToolButton:hover {{
    border-color: #DBCE99;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {HOT_TOP}, stop:1 {HOT_BOTTOM});
}}
QToolBar#standard QToolButton:pressed, QToolBar#standard QToolButton:checked {{
    border-color: #C2A257;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {ON_TOP}, stop:1 {ON_BOTTOM});
}}
QToolBar#standard QToolButton[popupMode="1"] {{ padding-right: 14px; }}
QToolBar#standard QToolButton::menu-button {{ border: none; width: 12px; }}
QStatusBar {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #567DB1, stop:1 #4A6FA5);
    color: white; border-top: 1px solid #3B5E91;
}}
QStatusBar QLabel {{ color: white; padding: 0 6px; }}
QStatusBar::item {{ border: none; }}
#pane {{ background: white; border: 1px solid {BORDER}; }}
QTreeView#folders, QListView#messages, QListView#cards, QTreeView#phoneList {{
    background: white; border: none; outline: 0;
}}
QTreeView#folders::item {{ padding: 1px 0; }}
QTreeView#folders::item:selected {{ background: {SELECT}; color: black; border: 1px solid {SELECT_BORDER}; }}
QTreeView#folders::item:selected:!active {{ background: {SELECT_INACTIVE}; border-color: #C0C0C0; }}
QLineEdit#search {{
    border: 1px solid #A5ACB5; padding: 2px 4px; background: white; color: #404040;
}}
QFrame#infobar {{ background: #FFFFE1; border-bottom: 1px solid #D8D8B0; }}
QFrame#infobar QLabel {{ color: #000; }}
QFrame#readHeader {{
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #FFFFFF, stop:1 #E8EFF9);
    border-bottom: 1px solid #C6D4E8;
}}
"""


class PaneHeader(QWidget):
    """The gradient title bar at the top of each pane ("Mail", "Inbox", "Contacts")."""

    def __init__(self, text: str = "", size: float = 12.5, parent=None):
        super().__init__(parent)
        self.text = text
        self.font_ = QFont()
        self.font_.setPointSizeF(size)
        self.font_.setBold(True)
        self.setFixedHeight(int(size * 2.4) + 4)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 4, 0)
        self.lay.addStretch(1)

    def set_text(self, text: str):
        self.text = text
        self.update()

    def add_right(self, w: QWidget):
        self.lay.addWidget(w)

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(HEADER_TOP))
        g.setColorAt(1, QColor(HEADER_BOTTOM))
        p.fillRect(self.rect(), g)
        p.setPen(QPen(QColor(BORDER)))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.setFont(self.font_)
        p.setPen(QColor(TITLE))
        right = sum(self.lay.itemAt(i).widget().width() + 6 for i in range(1, self.lay.count())
                    if self.lay.itemAt(i).widget() and self.lay.itemAt(i).widget().isVisible())
        p.drawText(QRectF(6, 0, self.width() - 12 - right, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(self.text, Qt.ElideRight, max(10, self.width() - 12 - right)))


class SubHeader(QWidget):
    """Smaller bar ("Favorite Folders", "Mail Folders", "Arranged By: Date")."""

    clicked = Signal()

    def __init__(self, text: str = "", right_text: str = "", parent=None):
        super().__init__(parent)
        self.text = text
        self.right_text = right_text
        self.setFixedHeight(20)
        self.setCursor(Qt.ArrowCursor)

    def set_text(self, text: str, right: str | None = None):
        self.text = text
        if right is not None:
            self.right_text = right
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#F4F8FD"))
        g.setColorAt(1, QColor("#D5E4F7"))
        p.fillRect(self.rect(), g)
        p.setPen(QColor("#9EBAE1"))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(TITLE))
        p.drawText(QRectF(6, 0, self.width() - 12, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        if self.right_text:
            f.setBold(False)
            p.setFont(f)
            p.drawText(QRectF(6, 0, self.width() - 12, self.height()), Qt.AlignVCenter | Qt.AlignRight,
                       self.right_text)


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "Search", parent=None):
        super().__init__(parent)
        self.setObjectName("search")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(150)


class NavButton(QToolButton):
    """The big Mail / Contacts buttons at the bottom of the Navigation Pane."""

    def __init__(self, text: str, icon, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setIcon(icon)
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setFixedHeight(32)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setIconSize(QSize(24, 24))
        f = self.font()
        f.setBold(True)
        self.setFont(f)
        self.hover = False

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        r = self.rect()
        g = QLinearGradient(0, 0, 0, r.height())
        if self.isChecked():
            top, bottom = (ON_TOP, ON_BOTTOM) if not self.hover else ("#FFC97A", "#FFA83A")
        elif self.hover:
            top, bottom = HOT_TOP, HOT_BOTTOM
        else:
            top, bottom = "#E3EFFF", "#C4DDFF"
        g.setColorAt(0, QColor(top))
        g.setColorAt(0.45, QColor(top).darker(103))
        g.setColorAt(0.5, QColor(bottom).lighter(104))
        g.setColorAt(1, QColor(bottom))
        p.fillRect(r, g)
        p.setPen(QColor(BORDER))
        p.drawLine(0, 0, r.width(), 0)
        self.icon().paint(p, 8, (r.height() - 24) // 2, 24, 24)
        p.setFont(self.font())
        p.setPen(QColor(TITLE))
        p.drawText(r.adjusted(40, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text().replace("&", ""))


def bold(label: QLabel, size: float | None = None) -> QLabel:
    f = label.font()
    f.setBold(True)
    if size:
        f.setPointSizeF(size)
    label.setFont(f)
    return label
