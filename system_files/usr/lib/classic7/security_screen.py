"""The Ctrl+Alt+Del screen of Windows 7: Lock this computer, Switch User, Log off,
Change a password..., Start Task Manager, Cancel; Ease of Access and the power button."""
from __future__ import annotations

import os
import pty
import pwd
import re
import select
import sys
import threading
import time

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QIcon, QKeySequence, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

import session_actions as sa

WHITE = QColor(255, 255, 255)


def paint_background(p: QPainter, r: QRect):
    """Windows 7's sign-in blue with soft light streaks."""
    g = QLinearGradient(0, r.top(), 0, r.bottom())
    g.setColorAt(0.0, QColor(16, 62, 122))
    g.setColorAt(0.45, QColor(30, 98, 168))
    g.setColorAt(1.0, QColor(10, 40, 92))
    p.fillRect(r, g)
    p.setRenderHint(QPainter.Antialiasing)
    w, h = r.width(), r.height()
    glow = QRadialGradient(QPointF(w * 0.42, h * 0.48), max(w, h) * 0.55)
    glow.setColorAt(0.0, QColor(110, 180, 240, 90))
    glow.setColorAt(1.0, QColor(110, 180, 240, 0))
    p.fillRect(r, glow)
    p.setPen(Qt.NoPen)
    for i, (y0, y1, alpha) in enumerate(((0.62, 0.30, 26), (0.70, 0.42, 20), (0.80, 0.55, 16), (0.55, 0.20, 12))):
        path = QPainterPath()
        path.moveTo(-w * 0.05, h * y0)
        path.cubicTo(w * 0.30, h * (y0 - 0.18), w * 0.62, h * (y1 + 0.22), w * 1.05, h * y1)
        path.lineTo(w * 1.05, h * (y1 + 0.03 + i * 0.01))
        path.cubicTo(w * 0.62, h * (y1 + 0.27), w * 0.30, h * (y0 - 0.12), -w * 0.05, h * (y0 + 0.05))
        path.closeSubpath()
        p.setBrush(QColor(200, 230, 255, alpha))
        p.drawPath(path)


class Option(QPushButton):
    """A white text choice that lights up under the mouse."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        f = self.font()
        f.setPointSizeF(f.pointSizeF() + 5)
        self.setFont(f)
        self.setMinimumWidth(300)
        self.setStyleSheet(
            "QPushButton { color: white; background: transparent; border: 1px solid transparent;"
            " border-radius: 3px; padding: 7px 18px; text-align: left; }"
            "QPushButton:hover, QPushButton:focus { background: rgba(255,255,255,40);"
            " border: 1px solid rgba(255,255,255,110); }"
            "QPushButton:pressed { background: rgba(255,255,255,70); }")


class GlassButton(QPushButton):
    """The rounded Cancel / OK buttons."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(QSize(96, 30))
        self.setStyleSheet(
            "QPushButton { color: white; border: 1px solid rgba(255,255,255,150); border-radius: 4px;"
            " padding: 4px 22px; background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 rgba(255,255,255,70), stop:0.5 rgba(255,255,255,30), stop:0.51 rgba(0,20,60,60),"
            " stop:1 rgba(40,90,160,80)); }"
            "QPushButton:hover, QPushButton:focus { border: 1px solid white; background:"
            " qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(255,255,255,110),"
            " stop:0.5 rgba(255,255,255,50), stop:0.51 rgba(30,80,160,90), stop:1 rgba(80,150,230,120)); }")


class PowerButton(QToolButton):
    """The red shut-down button in the corner."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(QSize(38, 30))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Shut down")
        self.hover = False

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        g = QLinearGradient(0, 0, 0, r.height())
        top, bottom = (QColor(255, 120, 100), QColor(170, 20, 10)) if self.hover else \
            (QColor(230, 90, 70), QColor(140, 16, 8))
        g.setColorAt(0, top)
        g.setColorAt(0.5, top.darker(115))
        g.setColorAt(0.51, bottom)
        g.setColorAt(1, bottom.lighter(130))
        p.setBrush(g)
        p.setPen(QPen(QColor(255, 255, 255, 170), 1))
        p.drawRoundedRect(r, 4, 4)
        c = r.center()
        rad = 7
        p.setPen(QPen(WHITE, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(c.x() - rad, c.y() - rad + 1, 2 * rad, 2 * rad), 120 * 16, 300 * 16)
        p.drawLine(QPointF(c.x(), c.y() - rad - 1), QPointF(c.x(), c.y() + 1))


class PasswordChanger(QWidget):
    """Change a password: the account picture, three fields and an arrow, like Windows 7."""
    done = Signal(bool, str)
    cancel = Signal()

    def __init__(self):
        super().__init__()
        self.user = pwd.getpwuid(os.getuid()).pw_name
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignHCenter)
        pic = QLabel()
        pic.setFixedSize(QSize(132, 132))
        pic.setAlignment(Qt.AlignCenter)
        pic.setPixmap(account_picture(120))
        pic.setStyleSheet("background: rgba(255,255,255,60); border: 1px solid rgba(255,255,255,150);"
                          " border-radius: 8px;")
        lay.addWidget(pic, 0, Qt.AlignHCenter)
        name = QLabel(display_name())
        f = name.font()
        f.setPointSizeF(f.pointSizeF() + 6)
        name.setFont(f)
        name.setStyleSheet("color: white;")
        lay.addWidget(name, 0, Qt.AlignHCenter)
        style = ("QLineEdit { padding: 4px 6px; border: 1px solid #6f8fb5; border-radius: 2px;"
                 " background: white; color: black; min-width: 220px; }")
        self.old = QLineEdit()
        self.new = QLineEdit()
        self.again = QLineEdit()
        for field, text in ((self.old, "Old password"), (self.new, "New password"),
                            (self.again, "Confirm password")):
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText(text)
            field.setStyleSheet(style)
            field.returnPressed.connect(self._next)
        lay.addWidget(self.old, 0, Qt.AlignHCenter)
        lay.addWidget(self.new, 0, Qt.AlignHCenter)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.again)
        self.go = QToolButton()
        self.go.setText("➔")
        self.go.setFixedSize(QSize(30, 28))
        self.go.setStyleSheet("QToolButton { color: white; border: 1px solid rgba(255,255,255,160);"
                              " border-radius: 3px; background: rgba(40,110,200,200); font-weight: bold; }"
                              "QToolButton:hover { background: rgba(70,150,240,230); }")
        self.go.clicked.connect(self.submit)
        row.addWidget(self.go)
        row.addStretch(1)
        lay.addLayout(row)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: white;")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setWordWrap(True)
        self.msg.setMaximumWidth(420)
        lay.addWidget(self.msg, 0, Qt.AlignHCenter)
        lay.addSpacing(20)
        cancel = GlassButton("Cancel")
        cancel.clicked.connect(self.cancel.emit)
        lay.addWidget(cancel, 0, Qt.AlignHCenter)
        self.done.connect(self._finished)

    def start(self):
        for f in (self.old, self.new, self.again):
            f.clear()
            f.setEnabled(True)
        self.msg.setText("")
        self.old.setFocus()

    def _next(self):
        fields = [self.old, self.new, self.again]
        i = fields.index(self.sender()) if self.sender() in fields else 2
        if i < 2:
            fields[i + 1].setFocus()
        else:
            self.submit()

    def submit(self):
        if self.new.text() != self.again.text():
            self.msg.setText("The passwords you typed do not match. Type the new password in both boxes.")
            self.new.clear()
            self.again.clear()
            self.new.setFocus()
            return
        if not self.new.text():
            self.msg.setText("Type a new password.")
            return
        for f in (self.old, self.new, self.again):
            f.setEnabled(False)
        self.msg.setText("Please wait...")
        old, new = self.old.text(), self.new.text()
        threading.Thread(target=lambda: self.done.emit(*change_password(old, new)), daemon=True).start()

    def _finished(self, ok: bool, text: str):
        for f in (self.old, self.new, self.again):
            f.setEnabled(True)
        if ok:
            self.msg.setText("Your password has been changed.")
            QTimer.singleShot(1800, self.cancel.emit)
        else:
            self.msg.setText(text or "The password could not be changed.")
            self.old.selectAll()
            self.old.setFocus()


def change_password(old: str, new: str, timeout: float = 25.0) -> tuple[bool, str]:
    """Run passwd on a terminal and answer its questions. Returns (ok, message)."""
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["LC_ALL"] = "C"
        os.execvp("passwd", ["passwd"])
    out = ""
    answers = [old, new, new]
    end = time.time() + timeout
    status = None
    try:
        while time.time() < end:
            r, _, _ = select.select([fd], [], [], 0.3)
            if r:
                try:
                    chunk = os.read(fd, 1024).decode(errors="replace")
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
                tail = out.rsplit("\n", 1)[-1].lower()
                if re.search(r"password[^:]*:\s*$", tail):
                    if not answers:          # asked again: the new password was refused
                        os.kill(pid, 9)
                        break
                    os.write(fd, (answers.pop(0) + "\n").encode())
                    out += "\n"
            wpid, st = os.waitpid(pid, os.WNOHANG)
            if wpid:
                status = st
                break
    finally:
        if status is None:
            try:
                _, status = os.waitpid(pid, 0)
            except ChildProcessError:
                status = 1
        os.close(fd)
    ok = os.waitstatus_to_exitcode(status) == 0 if status is not None else False
    lines = [l.strip() for l in out.splitlines() if l.strip() and "password:" not in l.lower()
             and not l.lower().startswith("changing password")]
    msg = lines[-1] if lines else ""
    if not ok:
        if "authentication" in msg.lower() or "failure" in msg.lower():
            msg = "The user name or old password is incorrect."
        msg = re.sub(r"^passwd:\s*", "", msg)
        bad = re.search(r"BAD PASSWORD:\s*(.*)", out)
        if bad:
            msg = bad.group(1).strip().rstrip(".") + "."
    return ok, msg


def display_name() -> str:
    pw = pwd.getpwuid(os.getuid())
    return (pw.pw_gecos.split(",")[0] or pw.pw_name).strip() or pw.pw_name


def account_picture(size: int) -> QPixmap:
    for path in (os.path.expanduser("~/.face.icon"), os.path.expanduser("~/.face"),
                 f"/var/lib/AccountsService/icons/{pwd.getpwuid(os.getuid()).pw_name}"):
        if os.path.isfile(path):
            pm = QPixmap(path)
            if not pm.isNull():
                return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return QIcon.fromTheme("user-identity", QIcon.fromTheme("system-users")).pixmap(size, size)


class SecurityScreen(QWidget):
    def __init__(self, main: bool = True):
        super().__init__()
        self.setWindowTitle("Classic 7 Security")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setCursor(Qt.ArrowCursor)
        self.main = main
        if not main:
            return
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 18)
        outer.addStretch(3)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        outer.addWidget(self.stack, 0, Qt.AlignHCenter)
        # the choices
        menu = QWidget()
        ml = QVBoxLayout(menu)
        ml.setSpacing(4)
        self.options = []
        for text, fn in (("Lock this computer", self._lock), ("Switch User", self._switch),
                         ("Log off", self._logoff), ("Change a password...", self._password),
                         ("Start Task Manager", self._taskmgr)):
            b = Option(text)
            b.clicked.connect(fn)
            ml.addWidget(b)
            self.options.append(b)
        ml.addSpacing(26)
        cancel = GlassButton("Cancel")
        cancel.clicked.connect(self.close_all)
        ml.addWidget(cancel, 0, Qt.AlignHCenter)
        self.stack.addWidget(menu)
        self.changer = PasswordChanger()
        self.changer.cancel.connect(self._back)
        self.stack.addWidget(self.changer)
        outer.addStretch(4)
        # bottom row: Ease of Access, the name, the power button
        bottom = QHBoxLayout()
        ease = QToolButton()
        ease.setIcon(QIcon.fromTheme("preferences-desktop-accessibility"))
        ease.setIconSize(QSize(30, 30))
        ease.setAutoRaise(True)
        ease.setToolTip("Ease of Access")
        ease.setStyleSheet("QToolButton { border: none; } QToolButton:hover { background: rgba(255,255,255,40);"
                           " border-radius: 4px; }")
        ease.clicked.connect(lambda: (sa._run(["kcmshell6", "kcm_access"]), self.close_all()))
        bottom.addWidget(ease, 0, Qt.AlignBottom)
        bottom.addStretch(1)
        brand = QLabel("Classic 7")
        f = brand.font()
        f.setPointSizeF(f.pointSizeF() + 10)
        f.setWeight(QFont.Light)
        brand.setFont(f)
        brand.setStyleSheet("color: rgba(255,255,255,220);")
        bottom.addWidget(brand, 0, Qt.AlignBottom)
        bottom.addStretch(1)
        power = PowerButton()
        power.clicked.connect(lambda: self._do(sa.shut_down))
        bottom.addWidget(power, 0, Qt.AlignBottom)
        more = QToolButton()
        more.setText("▸")
        more.setFixedSize(QSize(18, 30))
        more.setCursor(Qt.PointingHandCursor)
        more.setStyleSheet("QToolButton { color: white; border: 1px solid rgba(255,255,255,150); border-radius: 3px;"
                           " background: rgba(160,30,20,200); } QToolButton:hover { background: rgba(220,70,50,230); }"
                           " QToolButton::menu-indicator { image: none; }")
        m = QMenu(more)
        m.addAction("Sleep", lambda: self._do(sa.sleep))
        if sa.can_hibernate():
            m.addAction("Hibernate", lambda: self._do(sa.hibernate))
        m.addAction("Restart", lambda: self._do(sa.restart))
        m.addAction("Shut down", lambda: self._do(sa.shut_down))
        more.setMenu(m)
        more.setPopupMode(QToolButton.InstantPopup)
        bottom.addWidget(more, 0, Qt.AlignBottom)
        outer.addLayout(bottom)
        QShortcut(QKeySequence("Esc"), self, self._escape)
        QShortcut(QKeySequence("Down"), self, lambda: self.focusNextChild())
        QShortcut(QKeySequence("Up"), self, lambda: self.focusPreviousChild())
        QTimer.singleShot(50, lambda: self.options[0].setFocus())

    def paintEvent(self, _):
        p = QPainter(self)
        paint_background(p, self.rect())

    def close_all(self):
        QApplication.instance().quit()

    def _escape(self):
        if self.stack.currentIndex() == 1:
            self._back()
        else:
            self.close_all()

    def _back(self):
        self.stack.setCurrentIndex(0)
        self.options[3].setFocus()

    def _do(self, fn):
        fn()
        self.close_all()

    def _lock(self):
        self._do(sa.lock)

    def _switch(self):
        self._do(sa.switch_user)

    def _logoff(self):
        self._do(sa.log_off)

    def _taskmgr(self):
        self._do(sa.task_manager)

    def _password(self):
        self.stack.setCurrentIndex(1)
        self.changer.start()


def main(argv: list[str]) -> int:
    app = QApplication.instance() or QApplication([sys.argv[0]] + argv)
    app.setApplicationName("Classic 7 Security")
    app.setDesktopFileName("classic7-security")
    from PySide6.QtDBus import QDBusConnection
    bus = QDBusConnection.sessionBus()
    if bus.isConnected() and not bus.registerService("org.classic7.SecurityScreen"):
        return 0      # already showing
    windows = []
    primary = QGuiApplication.primaryScreen()
    for screen in QGuiApplication.screens():
        w = SecurityScreen(main=screen is primary)
        w.setScreen(screen)
        w.setGeometry(screen.geometry())
        w.showFullScreen()
        windows.append(w)
    main_win = next(w for w in windows if w.main)
    main_win.raise_()
    main_win.activateWindow()
    return app.exec()
