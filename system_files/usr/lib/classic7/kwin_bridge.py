"""Talk to KWin (Plasma 6, Wayland): list the open windows, switch to one, close one.

Wayland gives programs no list of other programs' windows, so this loads a small KWin
script over D-Bus; the script calls back into this process with what it found. The same
way kdotool works.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid

from PySide6.QtCore import ClassInfo, QObject, QTimer, Signal, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

LIST_JS = """
const out = [];
const active = workspace.activeWindow;
for (const w of workspace.windowList()) {
    if (!w.normalWindow || w.skipTaskbar || w.desktopWindow || w.dock || w.specialWindow) continue;
    out.push({id: w.internalId.toString(), caption: w.caption, cls: w.resourceClass, pid: w.pid,
              desktopFile: w.desktopFileName || "", minimized: w.minimized, active: w === active});
}
callDBus("%(service)s", "/", "org.classic7.KWinBridge", "windows", JSON.stringify(out));
"""

ACT_JS = """
for (const w of workspace.windowList()) {
    if (w.internalId.toString() !== "%(id)s") continue;
    %(body)s
}
"""

BODIES = {
    "activate": "if (w.minimized) w.minimized = false; workspace.activeWindow = w;",
    "close": "w.closeWindow();",
    "minimize": "w.minimized = true;",
    "maximize": "if (w.minimized) w.minimized = false; w.setMaximize(true, true); workspace.activeWindow = w;",
    "restore": "w.minimized = false; w.setMaximize(false, false);",
}


@ClassInfo({"D-Bus Interface": "org.classic7.KWinBridge"})
class _Receiver(QObject):
    got = Signal(str)

    @Slot(str)
    def windows(self, data: str):
        self.got.emit(data)


class KWinBridge(QObject):
    windowsChanged = Signal(list)       # [dict(id, caption, cls, pid, desktopFile, minimized, active)]

    def __init__(self, name: str = "TaskManager", parent=None):
        super().__init__(parent)
        self.bus = QDBusConnection.sessionBus()
        self.service = f"org.classic7.KWinBridge.{name}{os.getpid()}"
        self.receiver = _Receiver()
        self.receiver.got.connect(self._got)
        self.ok = (self.bus.isConnected() and self.bus.registerService(self.service)
                   and self.bus.registerObject("/", self.receiver, QDBusConnection.ExportAllSlots))
        self.kwin = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", self.bus)
        self.windows: list[dict] = []

    def available(self) -> bool:
        return bool(self.ok and self.kwin.isValid())

    def _got(self, data: str):
        try:
            self.windows = json.loads(data)
        except ValueError:
            return
        self.windowsChanged.emit(self.windows)

    def _run(self, js: str):
        if not self.available():
            return
        name = f"classic7-{uuid.uuid4().hex[:10]}"
        fd, path = tempfile.mkstemp(prefix="classic7-kwin-", suffix=".js")
        with os.fdopen(fd, "w") as f:
            f.write(js)
        reply = self.kwin.call("loadScript", path, name)
        args = reply.arguments() if reply.type() == QDBusMessage.ReplyMessage else []
        if args and isinstance(args[0], int) and args[0] >= 0:
            for obj in (f"/Scripting/Script{args[0]}", f"/{args[0]}"):
                script = QDBusInterface("org.kde.KWin", obj, "org.kde.kwin.Script", self.bus)
                if script.isValid():
                    script.call("run")
                    break

        def cleanup():
            self.kwin.call("unloadScript", name)
            try:
                os.unlink(path)
            except OSError:
                pass
        QTimer.singleShot(1500, cleanup)

    def refresh(self):
        self._run(LIST_JS % {"service": self.service})

    def act(self, window_id: str, what: str):
        if what in BODIES and all(c in "0123456789abcdef-{}" for c in window_id.lower()):
            self._run(ACT_JS % {"id": window_id, "body": BODIES[what]})
