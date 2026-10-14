"""Start-up work that can wait until the window is on the screen.

after_first_paint(fn) calls fn once, just after the program has drawn its first window (or after
latest_ms if nothing is drawn by then). A window should appear at once; what fills part of it later
(spelling dictionaries, the web view for a message) can come a moment after.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication


class _FirstPaint(QObject):
    """Watches the program's events until something is drawn. Qt draws a window and puts it on the
    screen in one go, so a call queued then runs after the picture is shown."""

    def __init__(self, fn, latest_ms: int):
        app = QApplication.instance()
        super().__init__(app)
        self.fn = fn
        self.done = False
        app.installEventFilter(self)
        QTimer.singleShot(latest_ms, self._run)

    def eventFilter(self, obj, event):
        if not self.done and event.type() == QEvent.Paint:
            QApplication.instance().removeEventFilter(self)
            QTimer.singleShot(0, self._run)
        return False

    def _run(self):
        if self.done:
            return
        self.done = True
        QApplication.instance().removeEventFilter(self)
        self.deleteLater()
        self.fn()


def after_first_paint(fn, latest_ms: int = 2000) -> None:
    if QApplication.instance() is None:
        fn()
        return
    _FirstPaint(fn, latest_ms)
