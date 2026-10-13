"""Sticky Notes, as in Windows 7: coloured notes on the desktop with + (new note) and x (delete),
rich text (Ctrl+B/I/U/T, Ctrl+Shift+L list, Ctrl+Shift+> and < size), six colours, resize grip.
Notes are kept in ~/.config/classic7/stickynotes.json and come back at login.

Wayland doesn't let a program place its own windows, so the notes are placed (and their places
read back) through a small KWin script, the same way Task Manager lists windows."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QLinearGradient, QPainter, QShortcut, QTextCharFormat, QTextListFormat
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (QApplication, QCheckBox, QMessageBox, QSizeGrip, QTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

import accessories as acc

APP = "Sticky Notes"
ICON = ("knotes", "view-pim-notes")
STORE = acc.config_dir() / "stickynotes.json"
SETTINGS = acc.config_dir() / "stickynotes-settings.json"
AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "classic7-stickynotes.desktop"
SERVER = f"classic7-stickynotes-{os.getuid()}"

# body colour, top strip colour (Windows 7's six)
COLORS = {"Blue": ("#c9ecf8", "#a7dcef"), "Green": ("#c5f7c1", "#a3e89e"), "Pink": ("#f1c3f1", "#e3a3e3"),
          "Purple": ("#d4cdf3", "#bab0ea"), "White": ("#f5f5f5", "#e0e0e0"), "Yellow": ("#fdfdc9", "#f6f39a")}


class Strip(QWidget):
    """The top bar of a note: + on the left, x on the right, drag to move."""

    def __init__(self, note: "Note"):
        super().__init__(note)
        self.note = note
        self.setFixedHeight(22)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.add = QToolButton(self)
        self.add.setText("+")
        self.add.setToolTip("New Note (Ctrl+N)")
        self.add.setAutoRaise(True)
        self.add.clicked.connect(lambda: note.app.new_note(near=note))
        self.close_btn = QToolButton(self)
        self.close_btn.setText("×")
        self.close_btn.setToolTip("Delete Note (Ctrl+D)")
        self.close_btn.setAutoRaise(True)
        self.close_btn.clicked.connect(note.ask_delete)
        for b in (self.add, self.close_btn):
            b.setFixedSize(22, 20)
            f = b.font()
            f.setBold(True)
            f.setPixelSize(15)
            b.setFont(f)
            b.setStyleSheet("QToolButton { border: none; color: #555; background: transparent; }"
                            "QToolButton:hover { color: black; background: rgba(255,255,255,0.45); }")

    def resizeEvent(self, _e):
        self.add.move(2, 1)
        self.close_btn.move(self.width() - 24, 1)

    def paintEvent(self, _):
        p = QPainter(self)
        body, strip = COLORS[self.note.color]
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor(strip).lighter(108))
        g.setColorAt(1, QColor(strip))
        p.fillRect(self.rect(), g)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            handle = self.note.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.note.app.schedule_save(read_places=True)
        super().mouseReleaseEvent(e)


class Note(QWidget):
    def __init__(self, app: "StickyNotes", data: dict):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.app = app
        self.id = data.get("id") or uuid.uuid4().hex[:12]
        self.color = data.get("color", "Yellow") if data.get("color") in COLORS else "Yellow"
        self.setWindowTitle(f"Sticky Note {self.id}")
        self.setWindowIcon(acc.icon(*ICON))
        self.place = (data.get("x"), data.get("y"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)
        self.strip = Strip(self)
        lay.addWidget(self.strip)
        self.text = QTextEdit()
        self.text.setFrameStyle(0)
        self.text.setAcceptRichText(True)
        f = QFont(self.text.font())
        f.setPointSizeF(11)
        self.text.setFont(f)
        self.text.setHtml(data.get("html", ""))
        self.text.textChanged.connect(lambda: self.app.schedule_save())
        self.text.setContextMenuPolicy(Qt.CustomContextMenu)
        self.text.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.text, 1)
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(14, 14)
        self.resize(int(data.get("w", 200)), int(data.get("h", 200)))
        self.setMinimumSize(QSize(120, 80))
        self._apply_color()
        for keys, slot in (("Ctrl+N", lambda: app.new_note(near=self)), ("Ctrl+D", self.ask_delete),
                           ("Ctrl+B", lambda: self._toggle("bold")), ("Ctrl+I", lambda: self._toggle("italic")),
                           ("Ctrl+U", lambda: self._toggle("underline")), ("Ctrl+T", lambda: self._toggle("strike")),
                           ("Ctrl+Shift+L", self._list), ("Ctrl+Shift+>", lambda: self._size(1.15)),
                           ("Ctrl+Shift+<", lambda: self._size(1 / 1.15))):
            QShortcut(QKeySequence(keys), self, slot)

    def resizeEvent(self, e):
        self.grip.move(self.width() - self.grip.width() - 1, self.height() - self.grip.height() - 1)
        self.grip.raise_()
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QColor(COLORS[self.color][1]).darker(125))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def _apply_color(self):
        body = COLORS[self.color][0]
        self.setStyleSheet(f"Note {{ background: {body}; }}")
        self.text.setStyleSheet(f"QTextEdit {{ background: {body}; color: black; border: none; }}")
        self.strip.update()
        self.update()

    def set_color(self, name: str):
        self.color = name
        self._apply_color()
        self.app.schedule_save()

    def _menu(self, pos):
        m = self.text.createStandardContextMenu()
        m.addSeparator()
        for name in ("Blue", "Green", "Pink", "Purple", "White", "Yellow"):
            a = QAction(name, m)
            a.setCheckable(True)
            a.setChecked(name == self.color)
            a.triggered.connect(lambda _c=False, n=name: self.set_color(n))
            m.addAction(a)
        m.exec(self.text.mapToGlobal(pos))

    def _toggle(self, what: str):
        c = self.text.textCursor()
        fmt = QTextCharFormat()
        cur = c.charFormat()
        if what == "bold":
            fmt.setFontWeight(QFont.Normal if cur.fontWeight() > QFont.Normal else QFont.Bold)
        elif what == "italic":
            fmt.setFontItalic(not cur.fontItalic())
        elif what == "underline":
            fmt.setFontUnderline(not cur.fontUnderline())
        else:
            fmt.setFontStrikeOut(not cur.fontStrikeOut())
        c.mergeCharFormat(fmt)
        self.text.mergeCurrentCharFormat(fmt)

    def _list(self):
        c = self.text.textCursor()
        if c.currentList():
            lst = c.currentList()
            lst.remove(c.block())
            c.blockFormat()
            fmt = c.blockFormat()
            fmt.setIndent(0)
            c.setBlockFormat(fmt)
        else:
            c.createList(QTextListFormat.ListDisc)

    def _size(self, factor: float):
        c = self.text.textCursor()
        size = c.charFormat().fontPointSize() or self.text.font().pointSizeF()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(max(6.0, min(72.0, size * factor)))
        c.mergeCharFormat(fmt)
        self.text.mergeCurrentCharFormat(fmt)

    def ask_delete(self):
        settings = self.app.settings
        if not settings.get("no_confirm"):
            box = QMessageBox(QMessageBox.Warning, APP, "Are you sure you want to delete this note?",
                              QMessageBox.Yes | QMessageBox.No, self)
            check = QCheckBox("Don't display this message again")
            box.setCheckBox(check)
            if box.exec() != QMessageBox.Yes:
                return
            if check.isChecked():
                settings["no_confirm"] = True
                self.app.save_settings()
        self.app.delete_note(self)

    def data(self) -> dict:
        return {"id": self.id, "html": self.text.toHtml(), "color": self.color, "w": self.width(),
                "h": self.height(), "x": self.place[0], "y": self.place[1]}

    def closeEvent(self, e):
        # closing a note window (e.g. Alt+F4) closes Sticky Notes like Windows does; notes are kept
        self.app.quit_all()
        e.accept()


class StickyNotes:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.notes: list[Note] = []
        self.settings = self._load_json(SETTINGS, {})
        self.save_timer = QTimer()
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(800)
        self.save_timer.timeout.connect(self.save)
        self.places_timer = QTimer()
        self.places_timer.setInterval(15000)
        self.places_timer.timeout.connect(self.read_places)
        self.places_timer.start()
        self.bridge = None
        try:
            from kwin_bridge import KWinBridge
            self.bridge = KWinBridge("StickyNotes")
            if not self.bridge.available():
                self.bridge = None
            else:
                self.bridge.windowsChanged.connect(self._got_places)
        except Exception:  # noqa: BLE001 - X11 or no KWin: notes still work, just not placed
            self.bridge = None
        self.server = QLocalServer()
        QLocalServer.removeServer(SERVER)
        self.server.listen(SERVER)
        self.server.newConnection.connect(self._other_instance)
        self.quitting = False

    @staticmethod
    def _load_json(path: Path, default):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return default

    def save_settings(self):
        try:
            SETTINGS.write_text(json.dumps(self.settings))
        except OSError:
            pass

    def start(self, new: bool = False):
        for d in self._load_json(STORE, []):
            self._add(d)
        if not self.notes or new:
            self.new_note()
        self.place_all()
        self._autostart(bool(self.notes))

    def _add(self, data: dict) -> Note:
        n = Note(self, data)
        self.notes.append(n)
        n.show()
        return n

    def new_note(self, near: Note | None = None):
        data = {"color": near.color if near else "Yellow"}
        if near is not None and near.place[0] is not None:
            data["x"], data["y"] = near.place[0] + 30, near.place[1] + 30
        n = self._add(data)
        n.text.setFocus()
        self.place_all()
        self.schedule_save()
        self._autostart(True)

    def delete_note(self, note: Note):
        if note in self.notes:
            self.notes.remove(note)
        note.hide()
        note.deleteLater()
        self.save()
        if not self.notes:
            self._autostart(False)
            self.quitting = True
            self.qapp.quit()

    def quit_all(self):
        if self.quitting:
            return
        self.quitting = True
        self.save()
        for n in list(self.notes):
            n.hide()
        self.qapp.quit()

    def schedule_save(self, read_places: bool = False):
        self.save_timer.start()
        if read_places:
            QTimer.singleShot(400, self.read_places)

    def save(self):
        if not self.notes and not self.quitting:
            return
        try:
            tmp = STORE.with_suffix(".tmp")
            tmp.write_text(json.dumps([n.data() for n in self.notes], indent=1))
            tmp.replace(STORE)
        except OSError:
            pass

    # ---- places (Wayland: through KWin) -----------------------------------------------------
    def place_all(self):
        if not self.bridge:
            for n in self.notes:
                if n.place[0] is not None:
                    n.move(QPoint(int(n.place[0]), int(n.place[1])))
            return
        moves = []
        for n in self.notes:
            g = {"x": n.place[0], "y": n.place[1]}
            moves.append({"caption": n.windowTitle(), "x": g["x"], "y": g["y"]})
        # Qt adds " — Sticky Notes" to the title, and KWin " <2>" to a repeated one
        js = """
const moves = %s;
const pid = %d;
for (const w of workspace.windowList()) {
    for (const m of moves) {
        const c = w.caption || "";
        if (w.pid !== pid || (c !== m.caption && !c.startsWith(m.caption + " "))) continue;
        w.skipTaskbar = true;
        w.skipPager = true;
        if (m.x !== null && m.x !== undefined) {
            const g = w.frameGeometry;
            w.frameGeometry = {x: m.x, y: m.y, width: g.width, height: g.height};
        }
    }
}
""" % (json.dumps(moves), os.getpid())
        QTimer.singleShot(300, lambda: self.bridge.script(js))

    def read_places(self):
        if self.bridge and self.notes:
            self.bridge.refresh()

    def _got_places(self, windows: list):
        changed = False
        for w in windows:
            for n in self.notes:
                cap, title = w.get("caption") or "", n.windowTitle()
                if w.get("pid") in (None, os.getpid()) and (cap == title or cap.startswith(title + " ")):
                    if n.place != (w.get("x"), w.get("y")):
                        n.place = (w.get("x"), w.get("y"))
                        changed = True
        if changed:
            self.save()

    # ---- one instance, autostart --------------------------------------------------------
    def _other_instance(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        sock.waitForReadyRead(500)
        msg = bytes(sock.readAll()).decode(errors="ignore")
        sock.close()
        if "new" in msg or not self.notes:
            self.new_note()
        for n in self.notes:
            n.show()
            n.raise_()
            n.activateWindow()

    @staticmethod
    def _autostart(on: bool):
        try:
            if on:
                AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                AUTOSTART.write_text("[Desktop Entry]\nType=Application\nName=Sticky Notes\nExec=classic7-stickynotes\n"
                                     "Icon=knotes\nNoDisplay=true\nX-KDE-autostart-phase=2\n")
            elif AUTOSTART.exists():
                AUTOSTART.unlink()
        except OSError:
            pass


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-stickynotes")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-stickynotes")
    app.setQuitOnLastWindowClosed(False)
    sock = QLocalSocket()
    sock.connectToServer(SERVER)
    if sock.waitForConnected(300):
        sock.write(b"new" if "--new" in argv else b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return 0
    notes = StickyNotes(app)
    notes.start(new="--new" in argv)
    app.aboutToQuit.connect(notes.save)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
