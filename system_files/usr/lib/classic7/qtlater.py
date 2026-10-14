"""Start-up work that can wait until the window is on the screen.

after_first_paint(fn) calls fn once, just after the program's window has been drawn (or after
latest_ms if nothing is drawn by then). A window should appear at once; what fills part of it later
(spelling dictionaries, the web view for a message) can come a moment after.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication

_DRAWN = (QEvent.Expose, QEvent.UpdateRequest)


class _FirstPaint(QObject):
    """Watches the shown windows (not every widget: that would slow the start down) until one is
    drawn. Qt draws a window and puts it on the screen while it handles that event, so a call
    queued then runs after the picture is shown."""

    def __init__(self, fn, latest_ms: int):
        super().__init__(QApplication.instance())
        self.fn = fn
        self.done = False
        self.watched = []
        QTimer.singleShot(0, self._watch)          # once the event loop runs: the window is shown by then
        QTimer.singleShot(latest_ms, self._run)

    def _watch(self):
        if self.done:
            return
        for w in QApplication.topLevelWidgets():
            handle = w.windowHandle() if w.isVisible() else None
            if handle is not None:
                handle.installEventFilter(self)
                self.watched.append(handle)

    def eventFilter(self, obj, event):
        if not self.done and event.type() in _DRAWN:
            QTimer.singleShot(0, self._run)
        return False

    def _run(self):
        if self.done:
            return
        self.done = True
        for handle in self.watched:
            try:
                handle.removeEventFilter(self)
            except RuntimeError:            # the window is gone
                pass
        self.watched = []
        self.deleteLater()
        self.fn()


def after_first_paint(fn, latest_ms: int = 2000) -> None:
    if QApplication.instance() is None:
        fn()
        return
    _FirstPaint(fn, latest_ms)
