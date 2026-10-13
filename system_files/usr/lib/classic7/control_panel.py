"""Control Panel, in the style of Windows 7: Category view, category pages, All Control Panel
Items (large or small icons) and search. The items are in control_items.py. It opens in Small icons
until the "View by" choice is changed; the choice is kept in ~/.config/classic7/controlpanel.json."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QLinearGradient, QPalette, QShortcut
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMenu, QScrollArea, QSizePolicy, QToolBar, QToolButton, QVBoxLayout, QWidget)

import control_items as ci

VIEWS = ("category", "large", "small")
DEFAULT_VIEW = "small"
SETTINGS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "classic7" / "controlpanel.json"


def saved_view() -> str:
    try:
        view = json.loads(SETTINGS.read_text()).get("view")
    except (OSError, ValueError, AttributeError):
        view = None
    return view if view in VIEWS else DEFAULT_VIEW


def save_view(view: str):
    try:
        data = json.loads(SETTINGS.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data["view"] = view
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(data, indent=1) + "\n")
    except OSError:
        pass


GREEN = QColor(0x1e, 0x7b, 0x1e)      # category and item titles
BLUE = QColor(0x1f, 0x4e, 0x9c)       # task links
HEAD = QColor(0x1e, 0x39, 0x87)       # "Adjust your computer's settings"
NAV_TOP = QColor(0xdf, 0xea, 0xf7)


def icon(name: str, fallback: str = "preferences-system") -> QIcon:
    ic = QIcon.fromTheme(name)
    return ic if not ic.isNull() else QIcon.fromTheme(fallback)


class Link(QLabel):
    """Text that is underlined under the mouse and acts like a link."""
    clicked = Signal()

    def __init__(self, text: str, color: QColor = BLUE, size: float | None = None, bold: bool = False):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setTextFormat(Qt.PlainText)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        f = self.font()
        if size:
            f.setPointSizeF(size)
        f.setBold(bold)
        self.setFont(f)
        self.color = color
        self._style(False)

    def _style(self, hover: bool):
        c = self.color.lighter(130) if hover else self.color
        self.setStyleSheet(f"color: {c.name()}; text-decoration: {'underline' if hover else 'none'};"
                           " background: transparent;")

    def enterEvent(self, e):
        self._style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._style(False)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self._style(True)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._style(False)
        super().focusOutEvent(e)


class NavPane(QWidget):
    """The light blue pane on the left of category pages."""

    def __init__(self):
        super().__init__()
        self.setFixedWidth(210)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(14, 14, 10, 14)
        self.lay.setSpacing(7)

    def paintEvent(self, _):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, NAV_TOP)
        g.setColorAt(1, QColor(255, 255, 255))
        p.fillRect(self.rect(), g)
        p.setPen(QColor(0xc9, 0xd7, 0xe8))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())


class ControlPanel(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Control Panel")
        self.setWindowIcon(icon("preferences-system"))
        self.resize(900, 640)
        self.history: list[tuple[str, str | None]] = []
        self.pos = -1
        self.view_mode = saved_view()     # category, large, small
        self._toolbar()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameStyle(QFrame.NoFrame)
        self.setCentralWidget(self.scroll)
        QShortcut(QKeySequence("Alt+Left"), self, self.back)
        QShortcut(QKeySequence("Alt+Right"), self, self.forward)
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.search.setFocus())
        QShortcut(QKeySequence("F3"), self, lambda: self.search.setFocus())
        self.go("home")

    # ---- chrome -------------------------------------------------------------------------
    def _toolbar(self):
        nav = QToolBar("Navigation")
        nav.setMovable(False)
        nav.setIconSize(QSize(22, 22))
        self.back_act = nav.addAction(icon("go-previous"), "Back", self.back)
        self.fwd_act = nav.addAction(icon("go-next"), "Forward", self.forward)
        self.address = QLineEdit()
        self.address.setReadOnly(True)
        self.address.addAction(icon("preferences-system"), QLineEdit.LeadingPosition)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Control Panel")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._search_changed)
        nav.addWidget(self.address)
        nav.addWidget(self.search)
        self.addToolBar(Qt.TopToolBarArea, nav)

    def _set_address(self, parts: list[str]):
        self.address.setText("  ▸ " + " ▸ ".join(parts) + " ▸")

    # ---- navigation ---------------------------------------------------------------------
    def go(self, page: str, arg: str | None = None, record: bool = True):
        if record:
            self.history = self.history[: self.pos + 1] + [(page, arg)]
            self.pos = len(self.history) - 1
        self.back_act.setEnabled(self.pos > 0)
        self.fwd_act.setEnabled(self.pos < len(self.history) - 1)
        if page == "home":
            if self.view_mode == "category":
                self._home()
            else:
                self._all_items()
        elif page == "category":
            self._category(arg)
        elif page == "search":
            self._results(arg or "")
        self._show_page()

    def _show_page(self):
        if getattr(self, "_pending", None) is not None:
            self.scroll.setWidget(self._pending)
            self._pending = None
        self.scroll.verticalScrollBar().setValue(0)

    def back(self):
        if self.pos > 0:
            self.pos -= 1
            self.go(*self.history[self.pos], record=False)

    def forward(self):
        if self.pos < len(self.history) - 1:
            self.pos += 1
            self.go(*self.history[self.pos], record=False)

    def _search_changed(self, text: str):
        if text.strip():
            if self.history and self.history[self.pos][0] == "search":
                self.history[self.pos] = ("search", text)
                self._results(text)
                self._show_page()
            else:
                self.go("search", text)
        elif self.history and self.history[self.pos][0] == "search":
            self.back()

    def open_item(self, it: ci.Item):
        ci.launch(it.run)

    def run_task(self, t: ci.Task):
        ci.launch(t.run)

    # ---- page parts ---------------------------------------------------------------------
    def _page(self, with_nav: bool):
        page = QWidget()
        page.setAutoFillBackground(True)
        pal = page.palette()
        pal.setColor(QPalette.Window, QColor(255, 255, 255))
        page.setPalette(pal)
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        nav = None
        if with_nav:
            nav = NavPane()
            row.addWidget(nav)
        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(24, 16, 24, 16)
        body_lay.setSpacing(10)
        row.addWidget(body, 1)
        self._pending = page          # set into the scroll area once it is filled
        return nav, body_lay

    def _view_by(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel("View by:"))
        names = {"category": "Category", "large": "Large icons", "small": "Small icons"}
        b = QToolButton()
        b.setText(names[self.view_mode] + " ▾")
        b.setAutoRaise(True)
        b.setStyleSheet(f"color: {BLUE.name()};")
        m = QMenu(b)
        for key, text in names.items():
            a = m.addAction(text, lambda k=key: self._set_view(k))
            a.setCheckable(True)
            a.setChecked(key == self.view_mode)
        b.setMenu(m)
        b.setPopupMode(QToolButton.InstantPopup)
        lay.addWidget(b)
        return w

    def _set_view(self, mode: str):
        self.view_mode = mode
        save_view(mode)
        self.go("home")

    def _heading(self, lay: QVBoxLayout, text: str, view_by: bool = True):
        row = QHBoxLayout()
        h = QLabel(text)
        f = h.font()
        f.setPointSizeF(f.pointSizeF() + 4)
        h.setFont(f)
        h.setStyleSheet(f"color: {HEAD.name()};")
        row.addWidget(h)
        row.addStretch(1)
        if view_by:
            row.addWidget(self._view_by())
        lay.addLayout(row)

    # ---- pages --------------------------------------------------------------------------
    def _home(self):
        self.setWindowTitle("Control Panel")
        self._set_address(["Control Panel"])
        _, lay = self._page(False)
        self._heading(lay, "Adjust your computer's settings")
        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(22)
        cats = [c for c in ci.CATEGORIES if ci.in_category(c.id)]
        half = (len(cats) + 1) // 2
        for i, c in enumerate(cats):
            col, row = (0, i) if i < half else (1, i - half)
            grid.addWidget(self._category_tile(c), row, col)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

    def _category_tile(self, c: ci.Category) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icon(c.icon).pixmap(48, 48))
        ic.setFixedSize(52, 52)
        ic.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        ic.setCursor(Qt.PointingHandCursor)
        ic.mousePressEvent = lambda _e, cid=c.id: self.go("category", cid)
        row.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        title = Link(c.title, GREEN, size=QApplication.font().pointSizeF() + 2.5)
        title.clicked.connect(lambda cid=c.id: self.go("category", cid))
        col.addWidget(title, 0, Qt.AlignLeft)
        for text, target in c.links:
            it = ci.by_id(target)
            if it is None:
                continue
            link = Link(text, BLUE)
            task = next((t for t in it.tasks if t.text.lower() == text.lower()), None)
            link.clicked.connect(lambda it=it, task=task: self.run_task(task) if task else self.open_item(it))
            col.addWidget(link, 0, Qt.AlignLeft)
        col.addStretch(1)
        row.addLayout(col, 1)
        return w

    def _category(self, cat_id: str):
        c = ci.category(cat_id)
        if c is None:
            self.go("home")
            return
        self.setWindowTitle(c.title)
        self._set_address(["Control Panel", c.title])
        nav, lay = self._page(True)
        home = Link("Control Panel Home", BLUE)
        home.clicked.connect(lambda: self.go("home"))
        nav.lay.addWidget(home, 0, Qt.AlignLeft)
        nav.lay.addSpacing(6)
        for other in ci.CATEGORIES:
            if not ci.in_category(other.id):
                continue
            if other.id == cat_id:
                lab = QLabel(other.title)
                f = lab.font()
                f.setBold(True)
                lab.setFont(f)
                lab.setWordWrap(True)
                nav.lay.addWidget(lab)
            else:
                ln = Link(other.title, BLUE)
                ln.setWordWrap(True)
                ln.clicked.connect(lambda oid=other.id: self.go("category", oid))
                nav.lay.addWidget(ln)
        nav.lay.addStretch(1)
        for i, it in enumerate(ci.in_category(cat_id)):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet("color: #e3e8ef;")
                lay.addWidget(line)
            lay.addWidget(self._item_block(it))
        lay.addStretch(1)

    def _item_block(self, it: ci.Item, tasks: list[ci.Task] | None = None) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(12)
        ic = QLabel()
        ic.setPixmap(icon(it.icon).pixmap(40, 40))
        ic.setFixedSize(44, 44)
        ic.setCursor(Qt.PointingHandCursor)
        ic.mousePressEvent = lambda _e, it=it: self.open_item(it)
        row.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        title = Link(it.title, GREEN, size=QApplication.font().pointSizeF() + 2.5)
        title.clicked.connect(lambda it=it: self.open_item(it))
        col.addWidget(title, 0, Qt.AlignLeft)
        flow = QWidget()
        fl = FlowRow(flow)
        tasks = it.tasks if tasks is None else tasks
        for t in tasks:
            ln = Link(t.text, BLUE)
            ln.setWordWrap(False)
            ln.clicked.connect(lambda t=t: self.run_task(t))
            fl.addWidget(ln)
        col.addWidget(flow)
        row.addLayout(col, 1)
        return w

    def _all_items(self):
        self.setWindowTitle("All Control Panel Items")
        self._set_address(["Control Panel", "All Control Panel Items"])
        _, lay = self._page(False)
        self._heading(lay, "Adjust your computer's settings")
        large = self.view_mode == "large"
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10 if large else 4)
        cols = 3 if large else 4
        all_items = sorted(ci.items(), key=lambda i: i.title.lower())
        per_col = (len(all_items) + cols - 1) // cols
        for n, it in enumerate(all_items):
            c, r = divmod(n, per_col)
            cell = QWidget()
            h = QHBoxLayout(cell)
            h.setContentsMargins(2, 2, 2, 2)
            h.setSpacing(8)
            ic = QLabel()
            size = 32 if large else 16
            ic.setPixmap(icon(it.icon).pixmap(size, size))
            ic.setFixedSize(size + 2, size + 2)
            h.addWidget(ic)
            ln = Link(it.title, BLUE)
            ln.clicked.connect(lambda it=it: self.open_item(it))
            h.addWidget(ln)
            h.addStretch(1)
            grid.addWidget(cell, r, c)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        lay.addLayout(grid)
        lay.addStretch(1)

    def _results(self, text: str):
        self.setWindowTitle("Search Results")
        self._set_address(["Control Panel", f"Search results for \"{text}\""])
        nav, lay = self._page(True)
        home = Link("Control Panel Home", BLUE)
        home.clicked.connect(lambda: (self.search.clear(), self.go("home")))
        nav.lay.addWidget(home)
        nav.lay.addStretch(1)
        found = ci.search(text)
        if not found:
            lab = QLabel(f"Nothing in Control Panel matches \"{text}\".")
            lay.addWidget(lab)
        for i, (it, tasks) in enumerate(found):
            if i:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setStyleSheet("color: #e3e8ef;")
                lay.addWidget(line)
            lay.addWidget(self._item_block(it, tasks))
        lay.addStretch(1)


class FlowRow(QVBoxLayout):
    """Task links under an item title, side by side with a separator, wrapping as needed."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(2)
        self.row = None
        self.count_in_row = 0
        self.width_in_row = 0

    def addWidget(self, w, *args):
        hint = w.sizeHint().width() + 24
        if self.row is None or self.width_in_row + hint > 560:
            self.row = QHBoxLayout()
            self.row.setSpacing(6)
            self.row.addStretch(1)
            super().addLayout(self.row)
            self.count_in_row = 0
            self.width_in_row = 0
        if self.count_in_row:
            sep = QLabel("|")
            sep.setStyleSheet("color: #b8c4d6;")
            self.row.insertWidget(self.row.count() - 1, sep)
        self.row.insertWidget(self.row.count() - 1, w)
        self.count_in_row += 1
        self.width_in_row += hint


def main(argv: list[str]) -> int:
    arg = " ".join(argv).strip()
    if arg:
        kind, value = ci.resolve(arg)
        if kind == "item":
            target = value.run
            if not ci.launch(target):
                print(f"control: can't open {arg}", file=sys.stderr)
                return 1
            return 0
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("Control Panel")
    app.setDesktopFileName("classic7-control-panel")
    w = ControlPanel()
    if arg:
        kind, value = ci.resolve(arg)
        if kind == "category":
            w.go("category", value)
        elif kind == "all" and w.view_mode == "category":
            w.view_mode = "small"        # All Control Panel Items: the icons, without changing the choice
            w.go("home", record=False)
    w.show()
    return app.exec()
