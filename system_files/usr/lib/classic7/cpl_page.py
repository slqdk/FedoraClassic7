"""A Control Panel page window, as Windows 7 shows Action Center or Windows Firewall: the address
bar ("Control Panel > System and Security > ..."), the light blue task pane on the left with
"Control Panel Home" and the page's own links, and a white page with a blue heading."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMainWindow, QScrollArea, QToolBar, QVBoxLayout, QWidget

import control_items as ci
from control_panel import BLUE, HEAD, AddressBar, Link, NavPane, open_place, page_address


class PageWindow(QMainWindow):
    def __init__(self, title: str, path: list[str], icon_name: str, category: str = "system"):
        """path: the page's place under its category ("System and Security", "Action Center"); the
        address bar shows it under the category or under All Control Panel Items, as Control Panel's
        "View by" is set."""
        super().__init__()
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon.fromTheme(icon_name))
        self.resize(900, 620)
        self.category = category
        cat = ci.category(category)
        self.trail = [p for p in path if not (cat and p == cat.title)]
        nav_bar = QToolBar("Navigation")
        nav_bar.setMovable(False)
        nav_bar.setIconSize(QSize(22, 22))
        back = nav_bar.addAction(QIcon.fromTheme("go-previous"), "Back", self._back)
        back.setToolTip("Back")
        self.address = AddressBar(icon_name, self._go)
        self.set_trail(self.trail)
        nav_bar.addWidget(self.address)
        self.addToolBar(Qt.TopToolBarArea, nav_bar)
        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.nav = NavPane()
        home = Link("Control Panel Home", BLUE)
        home.clicked.connect(lambda: ci.launch(["classic7-control"]))
        self.nav.lay.addWidget(home)
        self.nav.lay.addSpacing(10)
        self._nav_end = QWidget()
        self.nav.lay.addWidget(self._nav_end)
        self.nav.lay.addStretch(1)
        self.see_also = QVBoxLayout()
        self.nav.lay.addLayout(self.see_also)
        outer.addWidget(self.nav)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        page = QWidget()
        page.setAutoFillBackground(True)
        pal = page.palette()
        pal.setColor(page.backgroundRole(), QColor("white"))
        page.setPalette(pal)
        self.body = QVBoxLayout(page)
        self.body.setContentsMargins(22, 16, 22, 16)
        self.body.setSpacing(8)
        scroll.setWidget(page)
        outer.addWidget(scroll, 1)
        self.setCentralWidget(central)
        QShortcut(QKeySequence("F5"), self, self.refresh)

    def set_trail(self, trail: list):
        """The page's own part of the address (after the category or All Control Panel Items): texts,
        or (text, function) for places inside this window."""
        self.address.set_parts(page_address(self.category, trail))

    def _go(self, target):
        if callable(target):
            target()
        elif open_place(target):
            self.close()            # Windows 7 shows the new place in the same window

    def _back(self):
        parent = page_address(self.category, [])[-1][1]
        if open_place(parent):
            self.close()

    def nav_link(self, text: str, slot, icon_name: str = "") -> Link:
        link = Link(text, BLUE)
        link.clicked.connect(slot)
        idx = self.nav.lay.indexOf(self._nav_end)
        if icon_name:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(5)
            pic = QLabel()
            pic.setPixmap(QIcon.fromTheme(icon_name).pixmap(16, 16))
            h.addWidget(pic)
            h.addWidget(link, 1)
            self.nav.lay.insertWidget(idx, row)
        else:
            self.nav.lay.insertWidget(idx, link)
        return link

    def see_also_link(self, text: str, slot):
        if self.see_also.count() == 0:
            lab = QLabel("See also")
            lab.setStyleSheet("color: #444;")
            self.see_also.addWidget(lab)
        link = Link(text, BLUE)
        link.clicked.connect(slot)
        self.see_also.addWidget(link)

    @staticmethod
    def heading(text: str, size: float = 1.45) -> QLabel:
        lab = QLabel(text)
        f = lab.font()
        f.setPointSizeF(f.pointSizeF() * size)
        lab.setFont(f)
        lab.setStyleSheet(f"color: {HEAD.name()};")
        return lab

    def clear_body(self):
        while self.body.count():
            it = self.body.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                _clear_layout(it.layout())

    def refresh(self):
        pass


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget() is not None:
            it.widget().deleteLater()
        elif it.layout() is not None:
            _clear_layout(it.layout())
