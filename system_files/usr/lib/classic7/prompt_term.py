"""A small terminal emulator widget: bash in a pseudo-terminal, drawn with pyte.

Enough for everyday shell work and full-screen programs (htop, nano, less, vim):
colours (16/256/true colour), bold/italic/underline/reverse, cursor, scrollback,
selection and copy/paste, bracketed paste, application cursor keys, window title.
"""
from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import signal
import struct
import termios

import pyte
from PySide6.QtCore import QPoint, QRect, QSocketNotifier, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QGuiApplication, QKeyEvent,
                           QPainter)
from PySide6.QtWidgets import QWidget

# Windows Console (cmd.exe, Windows 7) colour table
ANSI = {
    "black": "#000000", "red": "#800000", "green": "#008000", "brown": "#808000",
    "blue": "#1f4fd8", "magenta": "#800080", "cyan": "#008080", "white": "#c0c0c0",
    "brightblack": "#808080", "brightred": "#ff0000", "brightgreen": "#00ff00", "brightbrown": "#ffff00",
    "brightblue": "#5b8cff", "brightmagenta": "#ff00ff", "brightcyan": "#00ffff", "brightwhite": "#ffffff",
}
ANSI["yellow"] = ANSI["brown"]
ANSI["brightyellow"] = ANSI["brightbrown"]
DEFAULT_FG = "#c0c0c0"
DEFAULT_BG = "#000000"

DECCKM = 1 << 5                # application cursor keys (private mode 1)
BRACKETED_PASTE = 2004 << 5

KEYS = {
    Qt.Key_Return: b"\r", Qt.Key_Enter: b"\r", Qt.Key_Backspace: b"\x7f", Qt.Key_Tab: b"\t",
    Qt.Key_Backtab: b"\x1b[Z", Qt.Key_Escape: b"\x1b", Qt.Key_Insert: b"\x1b[2~", Qt.Key_Delete: b"\x1b[3~",
    Qt.Key_PageUp: b"\x1b[5~", Qt.Key_PageDown: b"\x1b[6~",
    Qt.Key_F1: b"\x1bOP", Qt.Key_F2: b"\x1bOQ", Qt.Key_F3: b"\x1bOR", Qt.Key_F4: b"\x1bOS",
    Qt.Key_F5: b"\x1b[15~", Qt.Key_F6: b"\x1b[17~", Qt.Key_F7: b"\x1b[18~", Qt.Key_F8: b"\x1b[19~",
    Qt.Key_F9: b"\x1b[20~", Qt.Key_F10: b"\x1b[21~", Qt.Key_F11: b"\x1b[23~", Qt.Key_F12: b"\x1b[24~",
}
CURSOR_KEYS = {Qt.Key_Up: "A", Qt.Key_Down: "B", Qt.Key_Right: "C", Qt.Key_Left: "D",
               Qt.Key_Home: "H", Qt.Key_End: "F"}


class Screen(pyte.HistoryScreen):
    """HistoryScreen that keeps the OSC window title and ignores unknown sequences quietly."""

    def __init__(self, cols, rows):
        super().__init__(cols, rows, history=5000, ratio=0.5)
        self.title_changed = None

    def set_title(self, param):
        super().set_title(param)
        if self.title_changed:
            self.title_changed(param)

    def write_process_input(self, data):   # answers to device status queries (cursor position)
        if self.respond:
            self.respond(data.encode())

    respond = None

    def debug(self, *args, **kwargs):       # unknown escape sequences
        pass


class TerminalWidget(QWidget):
    titleChanged = Signal(str)
    finished = Signal(int)          # exit status of the shell
    outputArrived = Signal()

    def __init__(self, argv: list[str] | None = None, cwd: str | None = None, font_size: int = 11,
                 parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WA_InputMethodEnabled, True)
        self.setCursor(Qt.IBeamCursor)
        self.setMinimumSize(200, 100)

        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        for family in ("Liberation Mono", "DejaVu Sans Mono", "Noto Sans Mono", "Monospace"):
            if family in QFontDatabase.families():
                font = QFont(family)
                break
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(font_size)
        self.set_terminal_font(font)

        self.cols, self.rows = 80, 24
        self.vt = Screen(self.cols, self.rows)
        self.vt.respond = self._write
        self.vt.title_changed = lambda t: self.titleChanged.emit(t)
        self.stream = pyte.ByteStream(self.vt)
        self._ready = True
        self.scroll = 0                 # lines scrolled back into history
        self.sel_start = self.sel_end = None   # (abs_line, col)
        self._selecting = False
        self.cursor_on = True
        self.pid = 0
        self.fd = -1
        self.exit_status = None

        self._blink = QTimer(self, interval=530, timeout=self._toggle_cursor)
        self._blink.start()
        self._repaint = QTimer(self, singleShot=True, interval=12, timeout=self.update)
        self._spawn(argv or [os.environ.get("SHELL", "/bin/bash") if os.path.basename(os.environ.get("SHELL", "")) in
                             ("bash", "zsh", "fish") else "/bin/bash", "-i"], cwd)

    # -- font and geometry ----------------------------------------------------------------
    def set_terminal_font(self, font: QFont):
        self.term_font = font
        self.bold_font = QFont(font)
        self.bold_font.setBold(True)
        fm = QFontMetricsF(font)
        self.cw = fm.horizontalAdvance("M")
        self.ch = fm.height()
        self.ascent = fm.ascent()
        if getattr(self, "_ready", False):
            self.resizeEvent(None)
            self.update()

    def zoom(self, delta: int):
        f = QFont(self.term_font)
        f.setPointSize(max(6, min(40, f.pointSize() + delta)))
        self.set_terminal_font(f)

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(int(self.cw * 100) + 8, int(self.ch * 28) + 8)

    def resizeEvent(self, event):
        cols = max(10, int((self.width() - 8) // self.cw))
        rows = max(3, int((self.height() - 8) // self.ch))
        if (cols, rows) != (self.cols, self.rows):
            self.cols, self.rows = cols, rows
            self.vt.resize(rows, cols)
            self._set_winsize()
        self.update()

    def _set_winsize(self):
        if self.fd >= 0:
            try:
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))
            except OSError:
                pass

    # -- process ---------------------------------------------------------------------------
    def _spawn(self, argv, cwd):
        env = dict(os.environ)
        env.update(TERM="xterm-256color", COLORTERM="truecolor", CLASSIC7_PROMPT="1")
        env.pop("COLUMNS", None)
        env.pop("LINES", None)
        pid, fd = pty.fork()
        if pid == 0:
            try:
                if cwd:
                    os.chdir(cwd)
                os.execvpe(argv[0], argv, env)
            except Exception as e:  # noqa: BLE001
                os.write(2, f"Could not start {argv[0]}: {e}\n".encode())
            os._exit(127)
        self.pid, self.fd = pid, fd
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._set_winsize()
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Read, self)
        self._notifier.activated.connect(self._read)

    def _read(self, *_):
        chunks = []
        while True:
            try:
                data = os.read(self.fd, 65536)
            except OSError as e:
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    break
                data = b""
            if not data:
                self._child_exited()
                break
            chunks.append(data)
            if len(data) < 65536:
                break
        if chunks:
            at_bottom = self.scroll == 0
            self.stream.feed(b"".join(chunks))
            if at_bottom:
                self.scroll = 0
            self.cursor_on = True
            if not self._repaint.isActive():
                self._repaint.start()
            self.outputArrived.emit()

    def _child_exited(self):
        if self.exit_status is not None:
            return
        self._notifier.setEnabled(False)
        try:
            _, status = os.waitpid(self.pid, 0)
            self.exit_status = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            self.exit_status = 0
        self.finished.emit(self.exit_status)

    def _write(self, data: bytes):
        if self.fd < 0 or self.exit_status is not None:
            return
        while data:
            try:
                n = os.write(self.fd, data)
                data = data[n:]
            except BlockingIOError:
                QGuiApplication.processEvents()
            except OSError:
                return

    def send_text(self, text: str):
        self.scroll = 0
        self._write(text.encode())

    def run_command(self, command: str):
        """Type a command line into the shell and press Enter."""
        self.scroll = 0
        self._write(b"\x15")        # Ctrl+U: clear whatever is half-typed
        self._write(command.encode() + b"\r")
        self.setFocus()

    def paste(self, text: str):
        text = text.replace("\r\n", "\n").replace("\n", "\r")
        if BRACKETED_PASTE in self.vt.mode:
            text = "\x1b[200~" + text + "\x1b[201~"
        self.send_text(text)

    def interrupt(self):
        self._write(b"\x03")

    def shell_cwd(self) -> str:
        """Current folder of the program running in the terminal (the shell or its child)."""
        try:
            fg = os.tcgetpgrp(self.fd)
            return os.readlink(f"/proc/{fg}/cwd")
        except OSError:
            try:
                return os.readlink(f"/proc/{self.pid}/cwd")
            except OSError:
                return os.path.expanduser("~")

    def foreground_is_shell(self) -> bool:
        try:
            return os.tcgetpgrp(self.fd) == self.pid
        except OSError:
            return True

    def close_terminal(self):
        if self.exit_status is None and self.pid:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGHUP)
            except OSError:
                pass

    # -- text access -------------------------------------------------------------------------
    def _all_lines(self):
        """History lines followed by the screen lines (pyte line dicts)."""
        hist = list(self.vt.history.top)
        buf = [self.vt.buffer[y] for y in range(self.rows)]
        return hist, buf

    @staticmethod
    def _line_text(line, cols) -> str:
        return "".join(line[x].data for x in range(cols)).rstrip()

    def text_lines(self) -> list[str]:
        hist, buf = self._all_lines()
        lines = [self._line_text(line, self.cols) for line in hist + buf]
        while lines and not lines[-1]:
            lines.pop()
        return lines

    def recent_output(self, max_lines: int = 60) -> str:
        return "\n".join(self.text_lines()[-max_lines:])

    def selected_text(self) -> str:
        if not self.sel_start or not self.sel_end or self.sel_start == self.sel_end:
            return ""
        (l1, c1), (l2, c2) = sorted([self.sel_start, self.sel_end])
        hist, buf = self._all_lines()
        lines = hist + buf
        out = []
        for ln in range(l1, l2 + 1):
            if ln >= len(lines):
                break
            text = "".join(lines[ln][x].data for x in range(self.cols))
            a = c1 if ln == l1 else 0
            b = c2 if ln == l2 else self.cols
            out.append(text[a:b].rstrip())
        return "\n".join(out)

    def clear_selection(self):
        self.sel_start = self.sel_end = None
        self.update()

    # -- painting ----------------------------------------------------------------------------
    def _color(self, name, default, bold=False):
        if name == "default":
            return QColor(default)
        if name in ANSI:
            if bold and not name.startswith("bright") and default == DEFAULT_FG:
                name = "bright" + name
            return QColor(ANSI.get(name, default))
        if re.fullmatch(r"[0-9a-fA-F]{6}", name):
            return QColor("#" + name)
        return QColor(default)

    def _first_visible(self, hist_len):
        return hist_len - self.scroll

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(DEFAULT_BG))
        hist, buf = self._all_lines()
        top = self._first_visible(len(hist))
        lines = hist + buf
        sel = sorted([self.sel_start, self.sel_end]) if self.sel_start and self.sel_end else None
        x0, y0 = 4, 4
        for row in range(self.rows):
            ln = top + row
            if ln < 0 or ln >= len(lines):
                continue
            line = lines[ln]
            y = y0 + row * self.ch
            col = 0
            while col < self.cols:
                char = line[col]
                fg = self._color(char.fg, DEFAULT_FG, char.bold)
                bg = self._color(char.bg, DEFAULT_BG)
                if char.reverse:
                    fg, bg = bg, fg
                selected = bool(sel) and sel[0] <= (ln, col) < sel[1]
                if selected:
                    fg, bg = QColor("#ffffff"), QColor("#0a246a")
                # group runs of identical style for speed
                run = char.data
                end = col + 1
                while end < self.cols:
                    nxt = line[end]
                    nsel = bool(sel) and sel[0] <= (ln, end) < sel[1]
                    if (nxt.fg, nxt.bg, nxt.bold, nxt.italics, nxt.underscore, nxt.reverse, nsel) != \
                       (char.fg, char.bg, char.bold, char.italics, char.underscore, char.reverse, selected):
                        break
                    run += nxt.data
                    end += 1
                rect = QRect(int(x0 + col * self.cw), int(y), int((end - col) * self.cw) + 1, int(self.ch) + 1)
                if bg != QColor(DEFAULT_BG):
                    p.fillRect(rect, bg)
                if run.strip():
                    f = self.bold_font if char.bold else self.term_font
                    if char.italics or char.underscore:
                        f = QFont(f)
                        f.setItalic(char.italics)
                        f.setUnderline(char.underscore)
                    p.setFont(f)
                    p.setPen(fg)
                    # draw per cell so wide/narrow glyphs stay on the grid
                    for i, ch in enumerate(run):
                        if ch and ch != " ":
                            p.drawText(int(x0 + (col + i) * self.cw), int(y + self.ascent), ch)
                col = end
        # cursor
        if self.scroll == 0 and not self.vt.cursor.hidden and self.exit_status is None:
            cx, cy = self.vt.cursor.x, self.vt.cursor.y
            rect = QRect(int(x0 + cx * self.cw), int(y0 + cy * self.ch), int(self.cw), int(self.ch))
            if self.hasFocus():
                if self.cursor_on:
                    p.fillRect(rect, QColor(DEFAULT_FG))
                    ch = buf[cy][cx].data if cy < len(buf) else " "
                    if ch.strip():
                        p.setFont(self.term_font)
                        p.setPen(QColor(DEFAULT_BG))
                        p.drawText(rect.x(), int(rect.y() + self.ascent), ch)
            else:
                p.setPen(QColor(DEFAULT_FG))
                p.drawRect(rect.adjusted(0, 0, -1, -1))
        # scrolled-back indicator
        if self.scroll:
            p.setPen(QColor("#ffff00"))
            p.setFont(self.term_font)
            label = f" scrolled back {self.scroll} lines - Shift+PgDn or type to return "
            w = int(len(label) * self.cw)
            p.fillRect(self.width() - w - 4, 2, w, int(self.ch), QColor("#000080"))
            p.drawText(self.width() - w - 4, int(2 + self.ascent), label)
        p.end()

    def _toggle_cursor(self):
        self.cursor_on = not self.cursor_on
        cx, cy = self.vt.cursor.x, self.vt.cursor.y
        self.update(QRect(int(4 + cx * self.cw) - 1, int(4 + cy * self.ch) - 1, int(self.cw) + 2, int(self.ch) + 2))

    # -- keyboard --------------------------------------------------------------------------------
    def event(self, ev):
        # keep Tab/Backtab for the shell instead of focus switching
        if ev.type() == ev.Type.KeyPress and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            self.keyPressEvent(ev)
            return True
        return super().event(ev)

    def keyPressEvent(self, ev: QKeyEvent):
        key, mods, text = ev.key(), ev.modifiers(), ev.text()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        alt = bool(mods & Qt.AltModifier)

        if ctrl and shift and key == Qt.Key_C:
            QGuiApplication.clipboard().setText(self.selected_text())
            return
        if ctrl and shift and key == Qt.Key_V:
            self.paste(QGuiApplication.clipboard().text())
            return
        if shift and key in (Qt.Key_PageUp, Qt.Key_PageDown):
            step = self.rows - 1
            self.scroll_by(step if key == Qt.Key_PageUp else -step)
            return
        if ctrl and key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom(+1)
            return
        if ctrl and key == Qt.Key_Minus:
            self.zoom(-1)
            return

        data = b""
        if key in CURSOR_KEYS:
            letter = CURSOR_KEYS[key]
            if mods & (Qt.ShiftModifier | Qt.ControlModifier | Qt.AltModifier):
                mod = 1 + (1 if shift else 0) + (2 if alt else 0) + (4 if ctrl else 0)
                data = f"\x1b[1;{mod}{letter}".encode()
            elif DECCKM in self.vt.mode:
                data = f"\x1bO{letter}".encode()
            else:
                data = f"\x1b[{letter}".encode()
        elif key in KEYS:
            data = KEYS[key]
            if key == Qt.Key_Backspace and ctrl:
                data = b"\x17"           # Ctrl+Backspace: delete word
        elif ctrl and Qt.Key_A <= key <= Qt.Key_Z:
            data = bytes([key - Qt.Key_A + 1])
        elif ctrl and key == Qt.Key_Space:
            data = b"\x00"
        elif ctrl and key in (Qt.Key_BracketLeft,):
            data = b"\x1b"
        elif ctrl and key == Qt.Key_Backslash:
            data = b"\x1c"
        elif text:
            data = text.encode()
        if not data:
            return super().keyPressEvent(ev)
        if alt and key not in CURSOR_KEYS:
            data = b"\x1b" + data
        self.clear_selection()
        self.scroll = 0
        self.cursor_on = True
        self._write(data)

    def inputMethodEvent(self, ev):
        if ev.commitString():
            self.send_text(ev.commitString())
        ev.accept()

    def focusNextPrevChild(self, nxt):
        return False

    # -- mouse -------------------------------------------------------------------------------------
    def scroll_by(self, lines: int):
        self.scroll = max(0, min(len(self.vt.history.top), self.scroll + lines))
        self.update()

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            self.zoom(1 if ev.angleDelta().y() > 0 else -1)
            return
        steps = ev.angleDelta().y() // 40
        self.scroll_by(steps)

    def _cell_at(self, pos: QPoint):
        col = int(max(0, min(self.cols, round((pos.x() - 4) / self.cw))))
        row = int(max(0, min(self.rows - 1, (pos.y() - 4) // self.ch)))
        return (self._first_visible(len(self.vt.history.top)) + row, col)

    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == Qt.LeftButton:
            self.sel_start = self.sel_end = self._cell_at(ev.position().toPoint())
            self._selecting = True
            self.update()
        elif ev.button() == Qt.MiddleButton:
            self.paste(QGuiApplication.clipboard().text(QGuiApplication.clipboard().Mode.Selection))
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._selecting:
            self.sel_end = self._cell_at(ev.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._selecting:
            self._selecting = False
            text = self.selected_text()
            if text:
                QGuiApplication.clipboard().setText(text, QGuiApplication.clipboard().Mode.Selection)

    def mouseDoubleClickEvent(self, ev):
        ln, col = self._cell_at(ev.position().toPoint())
        hist, buf = self._all_lines()
        lines = hist + buf
        if 0 <= ln < len(lines):
            text = "".join(lines[ln][x].data for x in range(self.cols))
            word = re.compile(r"[\w./~:@%+=-]")
            a = min(col, self.cols - 1)
            if not word.match(text[a]):
                return
            b = a
            while a > 0 and word.match(text[a - 1]):
                a -= 1
            while b < self.cols and word.match(text[b]):
                b += 1
            self.sel_start, self.sel_end = (ln, a), (ln, b)
            self.update()
