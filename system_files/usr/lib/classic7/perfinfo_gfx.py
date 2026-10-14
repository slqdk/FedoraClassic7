#!/usr/bin/python3
"""The Experience Index's graphics tests, each in its own process. Prints one line of JSON.

    perfinfo_gfx.py desktop    a window that is redrawn completely for every picture the screen shows
                               (as moving windows and programs ask of the desktop): pictures a second,
                               and how many come late
    perfinfo_gfx.py 3d         Qt Quick drawing 120 large see-through layers that turn, off the screen and
                               as fast as the graphics can (no waiting for the screen): pictures a second
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time

WARMUP = 0.6
SECONDS = 3.0
_KEEP: list = []        # Qt objects live until os._exit: tidying the graphics up can crash and isn't needed


def _stats(times: list[float], refresh: float) -> dict:
    gaps = [(b - a) * 1000 for a, b in zip(times, times[1:])]
    if len(gaps) < 5:
        return {"error": "the window was hardly drawn"}
    fps = len(gaps) / (times[-1] - times[0])
    s = sorted(gaps)
    return {"fps": round(fps, 1), "refresh": round(refresh, 2), "frames": len(gaps),
            "median_ms": round(statistics.median(gaps), 2), "p95_ms": round(s[int(len(s) * 0.95) - 1], 1),
            "slowest_ms": round(s[-1], 1),
            # later than one and a half pictures: at 60 a second (what the eye sees as a jerk) and at this
            # screen's own rate
            "late_60": round(sum(1 for g in gaps if g > 25.0) / len(gaps), 3),
            "late": round(sum(1 for g in gaps if g > 1.5 * 1000 / refresh) / len(gaps), 3)}


def desktop() -> dict:
    from PySide6.QtCore import QRectF, Qt, QTimer
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QRasterWindow

    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("classic7-perfinfo")
    app.setDesktopFileName("classic7-perfinfo")
    times: list[float] = []

    class Win(QRasterWindow):
        frame = 0
        started = None

        def paintEvent(self, _e):
            now = time.perf_counter()
            if self.started is None:
                self.started = now
            elif now - self.started > WARMUP:
                times.append(now)
            self.frame += 1
            p = QPainter(self)
            w, h = self.width(), self.height()
            g = QLinearGradient(0, 0, w, h)
            hue = (self.frame * 3) % 360
            g.setColorAt(0, QColor.fromHsv(hue, 120, 230))
            g.setColorAt(1, QColor.fromHsv((hue + 120) % 360, 160, 160))
            p.fillRect(0, 0, w, h, g)
            p.setRenderHint(QPainter.Antialiasing)
            p.setFont(QFont("Noto Sans", 11))
            p.setBrush(QColor(255, 255, 255, 170))
            p.setPen(QColor(40, 70, 120))
            for i in range(60):
                x = (i * 97 + self.frame * 5) % max(1, w - 140)
                y = (i * 53 + self.frame * 3) % max(1, h - 50)
                p.drawRoundedRect(QRectF(x, y, 130, 40), 6, 6)
                p.drawText(QRectF(x, y, 130, 40), Qt.AlignCenter, f"Classic 7 {i}")
            p.end()
            if times and times[-1] - self.started > WARMUP + SECONDS:
                QTimer.singleShot(0, app.quit)
            else:
                self.update()                 # the next picture, when the screen can show one

    win = Win()
    _KEEP.extend([app, win])
    win.setTitle("Assessing desktop graphics")
    screen = app.primaryScreen()
    geo = screen.availableGeometry()
    win.resize(max(640, int(geo.width() * 0.6)), max(400, int(geo.height() * 0.6)))
    win.show()
    QTimer.singleShot(int((WARMUP + SECONDS + 15) * 1000), app.quit)       # never hang
    app.exec()
    screen = win.screen() or screen
    res = _stats(times, screen.refreshRate() or 60.0)
    res["size"] = f"{round(win.width() * win.devicePixelRatio())}x{round(win.height() * win.devicePixelRatio())}"
    res["platform"] = app.platformName()
    return res


QML = b"""
import QtQuick
Rectangle {
    id: root
    width: 1280; height: 720
    color: "#103050"
    property real turn: 0
    Repeater {
        model: 120
        Rectangle {
            required property int index
            x: -160; y: -280
            width: root.width + 320; height: root.height + 560
            opacity: 0.06
            rotation: root.turn + index * 3
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.hsla((index * 0.031) % 1, 0.7, 0.6, 1) }
                GradientStop { position: 1; color: Qt.hsla((index * 0.017 + 0.5) % 1, 0.7, 0.4, 1) }
            }
        }
    }
    Text { anchors.centerIn: parent; text: "Classic 7"; font.pixelSize: 64; color: "white" }
}
"""


def _gl_string(f, name: int) -> str:
    try:
        v = f.glGetString(name)
        return (v.decode(errors="replace") if isinstance(v, (bytes, bytearray)) else str(v or "")).strip()
    except Exception:  # noqa: BLE001 - only for the report
        return ""


def three_d() -> dict:
    """Qt Quick (OpenGL) renders into a picture that is never shown, frame after frame, waiting each
    time until the graphics have finished: how many pictures a second the graphics can make."""
    os.environ.pop("QT_QUICK_BACKEND", None)
    os.environ.pop("QSG_RHI_BACKEND", None)
    from PySide6.QtCore import QSize, QUrl
    from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtOpenGL import QOpenGLTexture
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import (QQuickGraphicsDevice, QQuickRenderControl, QQuickRenderTarget, QQuickWindow,
                                 QSGRendererInterface)

    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)
    app = QGuiApplication(sys.argv[:1])
    app.setApplicationName("classic7-perfinfo")
    _KEEP.append(app)
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        return {"error": "no OpenGL", "no_gl": True}
    surface = QOffscreenSurface()
    surface.setFormat(ctx.format())
    surface.create()
    _KEEP.extend([ctx, surface])
    if not ctx.makeCurrent(surface):
        return {"error": "the OpenGL context could not be used", "no_gl": True}
    f = ctx.functions()
    gl = {"renderer": _gl_string(f, 0x1F01), "vendor": _gl_string(f, 0x1F00), "version": _gl_string(f, 0x1F02)}

    control = QQuickRenderControl()
    win = QQuickWindow(control)
    _KEEP.extend([control, win])
    win.setGraphicsDevice(QQuickGraphicsDevice.fromOpenGLContext(ctx))
    if not control.initialize():
        return {"error": "Qt Quick could not draw with OpenGL", **gl}
    size = QSize(1280, 720)
    tex = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
    tex.setSize(size.width(), size.height())
    tex.setFormat(QOpenGLTexture.TextureFormat.RGBA8_UNorm)
    tex.allocateStorage()
    _KEEP.append(tex)
    win.setRenderTarget(QQuickRenderTarget.fromOpenGLTexture(tex.textureId(), size))
    win.resize(size)
    engine = QQmlEngine()
    comp = QQmlComponent(engine)
    comp.setData(QML, QUrl("perfinfo3d.qml"))
    root = comp.create()
    _KEEP.extend([engine, comp, root])
    if root is None:
        return {"error": "; ".join(e.toString() for e in comp.errors())[:200] or "QML failed", **gl}
    root.setParentItem(win.contentItem())
    win.contentItem().setSize(size.toSizeF())

    times: list[float] = []
    t0 = time.perf_counter()
    frame = 0
    while True:
        root.setProperty("turn", (frame * 3) % 360)
        ctx.makeCurrent(surface)
        control.beginFrame()
        control.polishItems()
        control.sync()
        control.render()
        control.endFrame()
        f.glFinish()                         # wait until the picture is really made
        frame += 1
        now = time.perf_counter()
        if now - t0 > WARMUP:
            times.append(now)
        if now - t0 > WARMUP + SECONDS or len(times) > 20000:
            break
        app.processEvents()
    if len(times) < 3:
        # very slow: count from the start instead
        return {"fps": round(frame / max(1e-6, time.perf_counter() - t0), 2), "frames": frame, **gl}
    fps = (len(times) - 1) / max(1e-6, times[-1] - times[0])
    return {"fps": round(fps, 1), "frames": len(times), "size": "1280x720", **gl}


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        result = desktop() if kind == "desktop" else three_d() if kind == "3d" else {"error": "desktop or 3d"}
    except Exception as e:  # noqa: BLE001
        result = {"error": f"{type(e).__name__}: {e}"[:200]}
    print(json.dumps(result), flush=True)
    os._exit(0)                              # don't wait for the graphics to tidy up
