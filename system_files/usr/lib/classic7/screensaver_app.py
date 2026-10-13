"""Screen savers, as in Windows 7: Blank, Bubbles, Mystify, Photos, Ribbons, 3D Pipes and 3D Text,
and the Screen Saver Settings window.

    classic7-screensaver --settings        Screen Saver Settings
    classic7-screensaver --run [NAME]      run one now, until the mouse or keyboard is used
                         [--lock]          and show the lock screen when it ends
    classic7-screensaver --list            the names

The waiting is done by the session helper (classic7-sessiond) with /usr/libexec/classic7-idle:
after the chosen minutes without mouse or keyboard it starts the screen saver, unless a program
keeps the screen on (a video, a game asking for it), a full-screen window is in front or the
screen is locked. "On resume, display logon screen" locks the session when the screen saver
ends, after it has run for 5 seconds (Windows' grace period). Settings are in
~/.config/classic7/screensaver.json."""
from __future__ import annotations

import colorsys
import json
import math
import os
import random
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTime, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QIcon, QImage, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPen, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

APP = "Screen Saver Settings"
SETTINGS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "classic7" / "screensaver.json"
# Plasma dims the screen after 5 idle minutes and turns it off after 10 (on mains power), so the
# screen saver comes before that
DEFAULTS = {"saver": "mystify", "minutes": 4, "lock": False, "photos": "", "text": "Classic 7", "text_time": False}
FPS = 30
GRACE = 5.0          # seconds: ending the screen saver this soon never locks
SETTINGS_ENV = "CLASSIC7_SCREENSAVER_SETTINGS"      # the settings window's unsaved choices, for Preview


def load_settings() -> dict:
    try:
        data = json.loads(os.environ.get(SETTINGS_ENV) or SETTINGS.read_text())
        return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    except (OSError, ValueError, AttributeError):
        return dict(DEFAULTS)


def lock_screen() -> bool:
    """Lock the session (the screen locker answers once the lock screen is up)."""
    try:
        import dbus
        dbus.SessionBus().get_object("org.freedesktop.ScreenSaver", "/ScreenSaver").Lock(
            dbus_interface="org.freedesktop.ScreenSaver", timeout=10)
        return True
    except Exception:  # noqa: BLE001 - no KDE screen locker: ask logind
        pass
    try:
        return subprocess.run(["loginctl", "lock-session"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def screen_locked() -> bool:
    try:
        import dbus
        return bool(dbus.SessionBus().get_object("org.freedesktop.ScreenSaver", "/ScreenSaver").GetActive(
            dbus_interface="org.freedesktop.ScreenSaver", timeout=3))
    except Exception:  # noqa: BLE001
        return False


def save_settings(s: dict):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=1) + "\n")
    tmp.replace(SETTINGS)


# ---- the savers ---------------------------------------------------------------------------------
class Saver(QWidget):
    """Base: a black widget that animates at 30 frames a second."""
    options = False

    def __init__(self, settings: dict, preview: bool = False):
        super().__init__()
        self.settings = settings
        self.preview = preview
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.started = False

    def showEvent(self, e):
        super().showEvent(e)
        if not self.started:
            self.started = True
            self.reset()
            self.timer.start(1000 // FPS)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.started:
            self.reset()

    def reset(self):
        pass

    def step(self):
        pass

    def _tick(self):
        self.step()
        self.update()

    def scale(self) -> float:
        """Sizes are made for a 1920-wide screen; the preview is small."""
        return max(0.12, self.width() / 1920)


class Blank(Saver):
    def paintEvent(self, _):
        QPainter(self).fillRect(self.rect(), Qt.black)

    def reset(self):
        self.timer.stop()


class Mystify(Saver):
    """Two four-cornered shapes bouncing around, leaving trails, slowly changing colour."""

    TRAIL = 7

    def reset(self):
        w, h = max(1, self.width()), max(1, self.height())
        self.shapes = []
        for _ in range(2):
            pts = [[random.uniform(0, w), random.uniform(0, h)] for _ in range(4)]
            vel = [[random.choice((-1, 1)) * random.uniform(2, 6), random.choice((-1, 1)) * random.uniform(2, 6)]
                   for _ in range(4)]
            self.shapes.append({"pts": pts, "vel": vel, "trail": [], "hue": random.random()})
        self.frame = 0

    def step(self):
        w, h = self.width(), self.height()
        s = self.scale() if self.preview else 1.0
        for sh in self.shapes:
            for p, v in zip(sh["pts"], sh["vel"]):
                p[0] += v[0] * s
                p[1] += v[1] * s
                if p[0] < 0 or p[0] > w:
                    v[0] = -v[0]
                    p[0] = min(max(p[0], 0), w)
                if p[1] < 0 or p[1] > h:
                    v[1] = -v[1]
                    p[1] = min(max(p[1], 0), h)
            if self.frame % 2 == 0:
                sh["trail"].append([tuple(p) for p in sh["pts"]])
                del sh["trail"][:-self.TRAIL]
            sh["hue"] = (sh["hue"] + 0.0015) % 1.0
        self.frame += 1

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        p.setRenderHint(QPainter.Antialiasing)
        width = max(1.0, 1.6 * (self.scale() if self.preview else 1.0))
        for sh in self.shapes:
            n = len(sh["trail"])
            for i, pts in enumerate(sh["trail"]):
                r, g, b = colorsys.hsv_to_rgb(sh["hue"], 1, 1)
                c = QColor(int(r * 255), int(g * 255), int(b * 255), int(60 + 195 * (i + 1) / max(1, n)))
                p.setPen(QPen(c, width))
                path = QPainterPath(QPointF(*pts[0]))
                for q in pts[1:]:
                    path.lineTo(QPointF(*q))
                path.closeSubpath()
                p.drawPath(path)


class Bubbles(Saver):
    """Soap bubbles floating over a picture of the desktop."""

    def __init__(self, settings, preview=False):
        super().__init__(settings, preview)
        self.background: QImage | None = None        # this screen's part of the desktop (run())

    def reset(self):
        w, h = max(1, self.width()), max(1, self.height())
        s = self.scale()
        self.bubbles = []
        for _ in range(14):
            r = random.uniform(40, 110) * s
            self.bubbles.append({"x": random.uniform(r, max(r + 1, w - r)), "y": random.uniform(r, max(r + 1, h - r)),
                                 "vx": random.uniform(-2.2, 2.2) * s * 1.5, "vy": random.uniform(-2.2, 2.2) * s * 1.5,
                                 "r": r, "hue": random.random()})

    def step(self):
        w, h = self.width(), self.height()
        for b in self.bubbles:
            b["x"] += b["vx"]
            b["y"] += b["vy"]
            if b["x"] - b["r"] < 0 or b["x"] + b["r"] > w:
                b["vx"] = -b["vx"]
            if b["y"] - b["r"] < 0 or b["y"] + b["r"] > h:
                b["vy"] = -b["vy"]
            b["hue"] = (b["hue"] + 0.004) % 1.0
        # bubbles bounce off each other
        for i, a in enumerate(self.bubbles):
            for b in self.bubbles[i + 1:]:
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                d = math.hypot(dx, dy)
                if 0 < d < a["r"] + b["r"]:
                    nx, ny = dx / d, dy / d
                    rel = (a["vx"] - b["vx"]) * nx + (a["vy"] - b["vy"]) * ny
                    if rel > 0:
                        a["vx"] -= rel * nx
                        a["vy"] -= rel * ny
                        b["vx"] += rel * nx
                        b["vy"] += rel * ny

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.background is not None and not self.background.isNull():
            p.drawImage(QRectF(self.rect()), self.background)
        else:
            p.fillRect(self.rect(), Qt.black)
        for b in self.bubbles:
            c = QPointF(b["x"], b["y"])
            r = b["r"]
            g = QRadialGradient(c, r)
            r1, g1, b1 = colorsys.hsv_to_rgb(b["hue"], 0.7, 1)
            r2, g2, b2 = colorsys.hsv_to_rgb((b["hue"] + 0.33) % 1, 0.7, 1)
            g.setColorAt(0.0, QColor(255, 255, 255, 8))
            g.setColorAt(0.75, QColor(int(r1 * 255), int(g1 * 255), int(b1 * 255), 28))
            g.setColorAt(0.93, QColor(int(r2 * 255), int(g2 * 255), int(b2 * 255), 120))
            g.setColorAt(1.0, QColor(255, 255, 255, 30))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(c, r, r)
            hl = QRadialGradient(QPointF(c.x() - r * 0.4, c.y() - r * 0.45), r * 0.35)
            hl.setColorAt(0, QColor(255, 255, 255, 190))
            hl.setColorAt(1, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(hl))
            p.drawEllipse(QPointF(c.x() - r * 0.4, c.y() - r * 0.45), r * 0.35, r * 0.3)


class Ribbons(Saver):
    """Coloured ribbons drawing curves across the screen and fading away."""

    def reset(self):
        self.ribbons = []
        for _ in range(4):
            self.ribbons.append(self._new())

    def _new(self) -> dict:
        w, h = max(1, self.width()), max(1, self.height())
        return {"pts": [], "x": random.uniform(0, w), "y": random.uniform(0, h), "a": random.uniform(0, 2 * math.pi),
                "turn": random.uniform(-0.05, 0.05), "hue": random.random(), "life": random.randint(260, 420)}

    def step(self):
        w, h = self.width(), self.height()
        s = self.scale()
        for i, rb in enumerate(self.ribbons):
            rb["life"] -= 1
            if rb["life"] > 0:
                rb["turn"] += random.uniform(-0.006, 0.006)
                rb["turn"] = max(-0.06, min(0.06, rb["turn"]))
                rb["a"] += rb["turn"]
                rb["x"] += math.cos(rb["a"]) * 9 * s
                rb["y"] += math.sin(rb["a"]) * 9 * s
                if not (0 <= rb["x"] <= w and 0 <= rb["y"] <= h):
                    rb["a"] += math.pi * 0.6
                rb["pts"].append((rb["x"], rb["y"], rb["a"]))
                del rb["pts"][:-160]
                rb["hue"] = (rb["hue"] + 0.002) % 1
            else:
                del rb["pts"][:6]
                if not rb["pts"]:
                    self.ribbons[i] = self._new()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.scale()
        for rb in self.ribbons:
            pts = rb["pts"]
            n = len(pts)
            for i in range(1, n):
                x0, y0, a0 = pts[i - 1]
                x1, y1, a1 = pts[i]
                t = i / n
                twist = math.sin(i * 0.12 + rb["hue"] * 10)
                half = (12 + 10 * twist) * s
                r, g, b = colorsys.hsv_to_rgb((rb["hue"] + t * 0.15) % 1, 0.85, 0.5 + 0.5 * abs(twist))
                c = QColor(int(r * 255), int(g * 255), int(b * 255), int(255 * t))
                nx0, ny0 = -math.sin(a0) * half, math.cos(a0) * half
                nx1, ny1 = -math.sin(a1) * half, math.cos(a1) * half
                path = QPainterPath(QPointF(x0 + nx0, y0 + ny0))
                path.lineTo(QPointF(x1 + nx1, y1 + ny1))
                path.lineTo(QPointF(x1 - nx1, y1 - ny1))
                path.lineTo(QPointF(x0 - nx0, y0 - ny0))
                path.closeSubpath()
                p.fillPath(path, c)


class Pipes(Saver):
    """3D Pipes: pipes growing through a grid, turning with shaded joints, until the screen is
    full; then it starts again."""

    COLORS = [QColor("#c83232"), QColor("#32a032"), QColor("#3264c8"), QColor("#c8a032"), QColor("#a032c8"),
              QColor("#32b4b4"), QColor("#c8c8c8")]
    DIRS = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]

    def reset(self):
        self.cell = max(6.0, 46 * self.scale())
        self.nx = max(4, int(self.width() / self.cell) + 2)
        self.ny = max(4, int(self.height() / self.cell) + 2)
        self.nz = 8
        self.used: set[tuple[int, int, int]] = set()
        self.segments: list[tuple] = []        # (kind, p0, p1, color) in drawing order
        self.pipes = []
        self.canvas = QImage(self.size(), QImage.Format_RGB32)
        self.canvas.fill(Qt.black)
        self.total = 0
        self._new_pipe()

    def _proj(self, x: float, y: float, z: float) -> QPointF:
        # an oblique view: depth goes up and to the right
        return QPointF((x - self.nz * 0.35 + z * 0.35) * self.cell, (y + self.nz * 0.25 - z * 0.25) * self.cell)

    def _new_pipe(self):
        for _ in range(40):
            pos = (random.randrange(self.nx), random.randrange(self.ny), random.randrange(self.nz))
            if pos not in self.used:
                break
        else:
            return False
        self.used.add(pos)
        color = random.choice(self.COLORS)
        self.pipes = [{"pos": pos, "dir": random.choice(self.DIRS), "color": color, "len": 0}]
        self._ball(pos, color, 0.5)
        return True

    def _depth(self, color: QColor, z: float) -> QColor:
        return color.darker(100 + int(z * 70 / max(1, self.nz - 1)))

    def _ball(self, pos, color, size):
        p = QPainter(self.canvas)
        p.setRenderHint(QPainter.Antialiasing)
        color = self._depth(color, pos[2])
        c = self._proj(*pos)
        r = self.cell * size * 0.5
        g = QRadialGradient(QPointF(c.x() - r * 0.35, c.y() - r * 0.35), r * 1.3)
        g.setColorAt(0, color.lighter(170))
        g.setColorAt(0.5, color)
        g.setColorAt(1, color.darker(260))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, r, r)
        p.end()

    def _tube(self, a, b, color):
        p = QPainter(self.canvas)
        p.setRenderHint(QPainter.Antialiasing)
        color = self._depth(color, (a[2] + b[2]) / 2)
        pa, pb = self._proj(*a), self._proj(*b)
        dx, dy = pb.x() - pa.x(), pb.y() - pa.y()
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length
        r = self.cell * 0.21
        g = QLinearGradient(QPointF(pa.x() + nx * r, pa.y() + ny * r), QPointF(pa.x() - nx * r, pa.y() - ny * r))
        g.setColorAt(0, color.darker(250))
        g.setColorAt(0.35, color.lighter(160))
        g.setColorAt(0.6, color)
        g.setColorAt(1, color.darker(300))
        path = QPainterPath(QPointF(pa.x() + nx * r, pa.y() + ny * r))
        path.lineTo(QPointF(pb.x() + nx * r, pb.y() + ny * r))
        path.lineTo(QPointF(pb.x() - nx * r, pb.y() - ny * r))
        path.lineTo(QPointF(pa.x() - nx * r, pa.y() - ny * r))
        path.closeSubpath()
        p.fillPath(path, QBrush(g))
        p.end()

    def step(self):
        if not self.pipes:
            if not self._new_pipe():
                self.reset()
            return
        for _ in range(1):
            pipe = self.pipes[0]
            x, y, z = pipe["pos"]
            dirs = list(self.DIRS)
            if random.random() < 0.8:
                dirs.remove(pipe["dir"])
                dirs.insert(0, pipe["dir"])
            else:
                random.shuffle(dirs)
            for d in dirs:
                nxt = (x + d[0], y + d[1], z + d[2])
                if (0 <= nxt[0] < self.nx and 0 <= nxt[1] < self.ny and 0 <= nxt[2] < self.nz
                        and nxt not in self.used):
                    if d != pipe["dir"] and pipe["len"]:
                        self._ball(pipe["pos"], pipe["color"], 0.42)
                    self._tube(pipe["pos"], nxt, pipe["color"])
                    self.used.add(nxt)
                    pipe["pos"], pipe["dir"] = nxt, d
                    pipe["len"] += 1
                    self.total += 1
                    break
            else:
                self._ball(pipe["pos"], pipe["color"], 0.5)
                self.pipes = []
                return
            if pipe["len"] > 60 or random.random() < 0.01:
                self._ball(pipe["pos"], pipe["color"], 0.5)
                self.pipes = []
                return
        if self.total > self.nx * self.ny * 0.8:      # full enough: start again
            self.reset()

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawImage(0, 0, self.canvas)


class Text3D(Saver):
    """3D Text: the chosen words, or the time, turning slowly in space as solid letters."""
    options = True

    def reset(self):
        self.angle = 0.0
        self.x, self.y = self.width() / 2, self.height() / 2
        s = self.scale()
        self.vx, self.vy = 2.0 * s, 1.4 * s

    def step(self):
        self.angle = (self.angle + 1.6) % 360
        self.x += self.vx
        self.y += self.vy
        if not (self.width() * 0.25 < self.x < self.width() * 0.75):
            self.vx = -self.vx
        if not (self.height() * 0.3 < self.y < self.height() * 0.7):
            self.vy = -self.vy

    def text(self) -> str:
        if self.settings.get("text_time"):
            return QTime.currentTime().toString("h:mm:ss AP")
        return self.settings.get("text") or "Classic 7"

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.scale()
        f = QFont("Noto Sans", 10, QFont.Bold)
        f.setPixelSize(max(8, int(200 * s)))
        path = QPainterPath()
        path.addText(0, 0, f, self.text())
        br = path.boundingRect()
        t = QTransform()
        t.translate(self.x, self.y)
        t.rotate(self.angle, Qt.YAxis, 1400.0 * s)
        t.rotate(12 * math.sin(math.radians(self.angle * 0.7)), Qt.XAxis, 1400.0 * s)
        t.translate(-br.center().x(), -br.center().y())
        # the sides: the letters repeated a little further back, darkest at the back
        depth = 12
        for d in range(depth, 0, -1):
            p.setTransform(t * QTransform.fromTranslate(d * 0.8 * s, d * 0.8 * s))
            shade = 35 + (depth - d) * 7
            p.fillPath(path, QColor(shade // 4, shade // 2, shade))
        p.setTransform(t)
        g = QLinearGradient(br.topLeft(), br.bottomLeft())
        g.setColorAt(0, QColor("#c4dcf6"))
        g.setColorAt(0.45, QColor("#5d9be0"))
        g.setColorAt(1, QColor("#1b4f96"))
        p.fillPath(path, QBrush(g))


class Photos(Saver):
    """Photos: pictures from a folder, one after another with a cross-fade."""
    options = True

    def reset(self):
        folder = Path(self.settings.get("photos") or "") if self.settings.get("photos") else None
        if folder is None or not folder.is_dir():
            from PySide6.QtCore import QStandardPaths
            folder = Path(QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or Path.home())
        exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
        self.files = []
        for root, _dirs, files in os.walk(folder):
            for f in files:
                if Path(f).suffix.lower() in exts:
                    self.files.append(os.path.join(root, f))
            if len(self.files) > 2000:
                break
        random.shuffle(self.files)
        self.index = -1
        self.current: QImage | None = None
        self.previous: QImage | None = None
        self.fade = 1.0
        self.hold = 0
        self._next()

    def _load(self, path: str) -> QImage | None:
        r = QImageReader(path)
        r.setAutoTransform(True)
        size = r.size()
        if size.isValid() and (size.width() > self.width() * 1.5 or size.height() > self.height() * 1.5):
            size.scale(QSize(int(self.width() * 1.5), int(self.height() * 1.5)), Qt.KeepAspectRatio)
            r.setScaledSize(size)
        img = r.read()
        return None if img.isNull() else img

    def _next(self):
        for _ in range(min(20, len(self.files))):
            self.index = (self.index + 1) % len(self.files)
            img = self._load(self.files[self.index])
            if img is not None:
                self.previous, self.current = self.current, img
                self.fade = 0.0
                self.hold = FPS * 6
                return

    def step(self):
        if self.fade < 1.0:
            self.fade = min(1.0, self.fade + 1 / (FPS * 1.2))
        elif self.hold > 0:
            self.hold -= 1
        elif self.files:
            self._next()

    def _draw(self, p: QPainter, img: QImage | None, opacity: float):
        if img is None:
            return
        s = img.size().scaled(self.size(), Qt.KeepAspectRatio)
        x, y = (self.width() - s.width()) / 2, (self.height() - s.height()) / 2
        p.setOpacity(opacity)
        p.drawImage(QRectF(x, y, s.width(), s.height()), img)

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), Qt.black)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self.files:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "No pictures were found in the folder.")
            return
        self._draw(p, self.previous, 1.0 - self.fade)
        self._draw(p, self.current, self.fade)


SAVERS = {"blank": ("Blank", Blank), "bubbles": ("Bubbles", Bubbles), "mystify": ("Mystify", Mystify),
          "photos": ("Photos", Photos), "ribbons": ("Ribbons", Ribbons), "pipes": ("3D Pipes", Pipes),
          "text": ("3D Text", Text3D)}


# ---- running ------------------------------------------------------------------------------------
class SaverWindow(QWidget):
    """One screen's full-screen window; any key, click or real mouse movement ends it."""
    done = Signal()

    def __init__(self, cls, settings: dict, screen):
        super().__init__()
        self.setWindowTitle("Classic 7 Screen Saver")
        self.setCursor(Qt.BlankCursor)
        self.setMouseTracking(True)
        self.saver = cls(settings)
        self.saver.setMouseTracking(True)
        self.saver.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.saver)
        self.setStyleSheet("background: black;")
        self.start_pos = None
        if screen is not None:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())

    def mouseMoveEvent(self, e):
        pos = e.globalPosition()
        if self.start_pos is None:
            self.start_pos = pos          # the first event only says where the pointer is
        elif (pos - self.start_pos).manhattanLength() > 12:
            self.done.emit()

    def mousePressEvent(self, _):
        self.done.emit()

    def keyPressEvent(self, _):
        self.done.emit()

    def wheelEvent(self, _):
        self.done.emit()


def desktop_parts(screens) -> dict:
    """Each screen's part of a picture of the whole desktop (for Bubbles), taken before the
    screen saver covers it."""
    try:
        import quickshot_app
        img = quickshot_app.grab_workspace()
    except Exception:  # noqa: BLE001 - no picture of the desktop: bubbles on black
        img = None
    if img is None or img.isNull() or not screens:
        return {}
    virtual = QRect()
    for sc in screens:
        virtual = virtual.united(sc.geometry())
    ratio = img.width() / max(1, virtual.width())
    parts = {}
    for sc in screens:
        g = sc.geometry().translated(-virtual.topLeft())
        parts[sc.name()] = img.copy(round(g.x() * ratio), round(g.y() * ratio),
                                    round(g.width() * ratio), round(g.height() * ratio))
    return parts


def run(name: str, settings: dict, lock_after: bool) -> int:
    app = QApplication.instance()
    cls = SAVERS.get(name, SAVERS["mystify"])[1]
    screens = QGuiApplication.screens()
    backgrounds = desktop_parts(screens) if cls is Bubbles else {}
    windows = []
    started = time.monotonic()
    state = {"ending": False}

    def end(by_user=True):
        if state["ending"]:
            return
        state["ending"] = True
        if by_user and lock_after and time.monotonic() - started >= GRACE:
            lock_screen()             # the lock screen is up before the screen saver goes
        for w in windows:
            w.close()
        app.quit()
    for screen in screens:
        w = SaverWindow(cls, settings, screen)
        if screen.name() in backgrounds:
            w.saver.background = backgrounds[screen.name()]
        w.done.connect(end)
        w.showFullScreen()
        windows.append(w)
    # the session helper stops the screen saver with SIGTERM when the mouse or keyboard is used
    # (it locks the screen itself); Python sees the signal when it next runs, so keep it running
    signal.signal(signal.SIGTERM, lambda *_: QTimer.singleShot(0, lambda: end(False)))
    signal.signal(signal.SIGINT, lambda *_: QTimer.singleShot(0, lambda: end(False)))
    tick = QTimer()
    tick.timeout.connect(lambda: None)
    tick.start(250)
    # bring the windows to the front through KWin (a program started in the background may not
    # take the front on its own), so the key that wakes the screen doesn't go to the program behind
    QTimer.singleShot(300, lambda: _front(os.getpid()))
    app.exec()
    return 0


def _front(pid: int):
    try:
        from kwin_bridge import KWinBridge
        b = KWinBridge("Saver")
        if b.available():
            b.script("""
for (const w of workspace.windowList()) {
    if (w.pid !== %d) continue;
    w.keepAbove = true;
    w.skipTaskbar = true;
    w.skipSwitcher = true;
    w.skipPager = true;
    workspace.activeWindow = w;
}
""" % pid)
            _front.bridge = b      # keep it alive until the script has run
    except Exception:  # noqa: BLE001 - not on KWin
        pass


# ---- settings -----------------------------------------------------------------------------------
class Monitor(QFrame):
    """The little monitor in the settings window, with the screen saver running in it."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(220, 196)
        self.screen_area = QWidget(self)
        self.screen_area.setGeometry(22, 18, 176, 132)
        self.lay = QVBoxLayout(self.screen_area)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.current: QWidget | None = None

    def show_saver(self, cls, settings: dict):
        if self.current is not None:
            self.current.timer.stop()
            self.current.deleteLater()
        self.current = cls(settings, preview=True) if cls is not None else None
        if self.current is not None:
            self.lay.addWidget(self.current)
            self.current.show()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, 0, 160)
        g.setColorAt(0, QColor("#d8d8d8"))
        g.setColorAt(1, QColor("#9a9a9a"))
        p.setBrush(QBrush(g))
        p.setPen(QPen(QColor("#555"), 1))
        p.drawRoundedRect(QRectF(10, 6, 200, 156), 8, 8)
        p.fillRect(QRectF(22, 18, 176, 132), QColor("#3a6ea5") if self.current is None else Qt.black)
        p.setBrush(QColor("#8a8a8a"))
        p.drawRect(QRectF(95, 162, 30, 14))
        p.drawRoundedRect(QRectF(65, 174, 90, 12), 4, 4)


class SettingsWindow(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.setWindowIcon(QIcon.fromTheme("preferences-desktop-screensaver"))
        self.settings = load_settings()
        v = QVBoxLayout(self)
        tabs = QTabWidget()
        page = QWidget()
        pv = QVBoxLayout(page)
        self.monitor = Monitor()
        pv.addWidget(self.monitor, 0, Qt.AlignHCenter)
        box = QGroupBox("Screen saver")
        bl = QVBoxLayout(box)
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.addItem("(None)", "none")
        for key, (title, _cls) in sorted(SAVERS.items(), key=lambda kv: kv[1][0]):
            self.combo.addItem(title, key)
        self.combo.setCurrentIndex(max(0, self.combo.findData(self.settings["saver"])))
        self.combo.currentIndexChanged.connect(self._changed)
        row.addWidget(self.combo, 1)
        self.opts = QPushButton("Settings...")
        self.opts.clicked.connect(self._options)
        row.addWidget(self.opts)
        self.prev = QPushButton("Preview")
        self.prev.clicked.connect(self._preview)
        row.addWidget(self.prev)
        bl.addLayout(row)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Wait:"))
        self.wait = QSpinBox()
        self.wait.setRange(1, 9999)
        self.wait.setValue(int(self.settings["minutes"]))
        self.wait.valueChanged.connect(lambda _v: self.apply_btn.setEnabled(True))
        row2.addWidget(self.wait)
        row2.addWidget(QLabel("minutes"))
        self.lock = QCheckBox("On resume, display logon screen")
        self.lock.setChecked(bool(self.settings["lock"]))
        self.lock.toggled.connect(lambda _v: self.apply_btn.setEnabled(True))
        row2.addSpacing(12)
        row2.addWidget(self.lock)
        row2.addStretch(1)
        bl.addLayout(row2)
        pv.addWidget(box)
        power = QGroupBox("Power management")
        pl = QVBoxLayout(power)
        t = QLabel("Conserve energy or maximize performance by adjusting display brightness and other power settings.")
        t.setWordWrap(True)
        pl.addWidget(t)
        link = QLabel("<a href='#'>Change power settings</a>")
        link.linkActivated.connect(lambda _l: subprocess.Popen(["kcmshell6", "kcm_powerdevilprofilesconfig"],
                                                               start_new_session=True))
        pl.addWidget(link)
        pv.addWidget(power)
        tabs.addTab(page, "Screen Saver")
        v.addWidget(tabs)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        self.apply_btn = bb.button(QDialogButtonBox.Apply)
        self.apply_btn.setEnabled(False)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        self.apply_btn.clicked.connect(self._apply)
        v.addWidget(bb)
        self._changed()
        self.apply_btn.setEnabled(False)
        self.setFixedSize(max(420, self.sizeHint().width()), self.sizeHint().height())

    def _changed(self, *_):
        key = self.combo.currentData()
        cls = SAVERS[key][1] if key in SAVERS else None
        self.monitor.show_saver(cls, self.settings)
        self.opts.setEnabled(key in SAVERS)
        self.prev.setEnabled(key in SAVERS)
        self.wait.setEnabled(key != "none")
        self.lock.setEnabled(key != "none")
        self.apply_btn.setEnabled(True)

    def _options(self):
        key = self.combo.currentData()
        if key == "photos":
            d = QFileDialog.getExistingDirectory(self, "Browse For Folder", self.settings.get("photos") or
                                                 str(Path.home() / "Pictures"))
            if d:
                self.settings["photos"] = d
                self.apply_btn.setEnabled(True)
                self._changed()
        elif key == "text":
            dlg = QDialog(self)
            dlg.setWindowTitle("3D Text Settings")
            lay = QVBoxLayout(dlg)
            box = QGroupBox("Text")
            bl = QVBoxLayout(box)
            group = QButtonGroup(dlg)
            time_btn = QRadioButton("Time")
            custom_btn = QRadioButton("Custom text:")
            group.addButton(time_btn)
            group.addButton(custom_btn)
            edit = QLineEdit(self.settings.get("text") or "Classic 7")
            edit.setMaxLength(40)
            bl.addWidget(time_btn)
            row = QHBoxLayout()
            row.addWidget(custom_btn)
            row.addWidget(edit, 1)
            bl.addLayout(row)
            (time_btn if self.settings.get("text_time") else custom_btn).setChecked(True)
            edit.setEnabled(custom_btn.isChecked())
            custom_btn.toggled.connect(edit.setEnabled)
            lay.addWidget(box)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            lay.addWidget(bb)
            dlg.setMinimumWidth(320)
            if dlg.exec() == QDialog.Accepted:
                self.settings["text"] = edit.text() or "Classic 7"
                self.settings["text_time"] = time_btn.isChecked()
                self.apply_btn.setEnabled(True)
                self._changed()
        else:
            QMessageBox.information(self, "Screen Saver", "This screen saver has no options that you can set.")

    def _preview(self):
        """Full screen until the mouse or keyboard is used, with the choices made here (not
        saved yet, as in Windows)."""
        env = dict(os.environ)
        env[SETTINGS_ENV] = json.dumps(self.settings)
        subprocess.Popen([sys.executable, sys.argv[0], "--run", self.combo.currentData()], env=env,
                         start_new_session=True)

    def _apply(self):
        self.settings.update({"saver": self.combo.currentData(), "minutes": self.wait.value(),
                              "lock": self.lock.isChecked()})
        try:
            save_settings(self.settings)
        except OSError as e:
            QMessageBox.warning(self, APP, f"The settings could not be saved: {e.strerror or e}")
        self.apply_btn.setEnabled(False)

    def _ok(self):
        self._apply()
        self.accept()


# ---- the idle watch (used by classic7-sessiond) ------------------------------------------------
class IdleWatch:
    """Starts the screen saver after the chosen minutes without input, unless something keeps the
    screen on, a full-screen window is in front or the screen is locked (then it looks again every
    minute while nobody is back), and stops it when input comes back. With "On resume, display
    logon screen" the session is locked before the screen saver goes away."""

    IDLE = "/usr/libexec/classic7-idle"
    SAVER = "/usr/bin/classic7-screensaver"
    RETRY_MS = 60_000

    def __init__(self, log=None):
        from PySide6.QtCore import QFileSystemWatcher, QProcess
        self.QProcess = QProcess
        self.log = log or (lambda _t: None)
        self.idle: QProcess | None = None
        self.saver: QProcess | None = None
        self.saver_started = 0.0
        self.saver_lock = False
        self.minutes = None
        self.failures = 0
        self.away = False            # idle, and not back yet
        self.asking = False          # waiting for KWin's list of windows
        self.bridge = None
        self.retry = QTimer()
        self.retry.setSingleShot(True)
        self.retry.timeout.connect(self._idle)
        self.watch = QFileSystemWatcher()
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            self.watch.addPath(str(SETTINGS.parent))
        except OSError:
            pass
        self.watch.directoryChanged.connect(lambda _p: QTimer.singleShot(300, self.configure))
        self.configure()

    def configure(self):
        s = load_settings()
        try:
            minutes = None if s["saver"] == "none" else max(1, int(s["minutes"]))
        except (TypeError, ValueError):
            minutes = DEFAULTS["minutes"]
        if minutes == self.minutes and (self.idle is not None or minutes is None):
            return
        self.minutes = minutes
        if self.idle is not None:
            self.idle.readyReadStandardOutput.disconnect()
            self.idle.finished.disconnect()
            self.idle.kill()
            self.idle.waitForFinished(1000)
            self.idle = None
        self.away = False
        self.retry.stop()
        if minutes is None or not os.access(self.IDLE, os.X_OK):
            self.log("screen saver off" if minutes is None else f"screen saver: {self.IDLE} is missing")
            return
        self.idle = self.QProcess()
        self.idle.setProgram(self.IDLE)
        self.idle.setArguments([str(minutes * 60)])
        self.idle.readyReadStandardOutput.connect(self._read)
        self.idle.finished.connect(self._idle_gone)
        self.idle.start()
        self.log(f"screen saver after {minutes} minute{'s' if minutes != 1 else ''}")

    def _idle_gone(self, *_):
        """classic7-idle stopped on its own: start it again, a few times."""
        self.idle = None
        self.failures += 1
        if self.failures <= 5:
            self.log("screen saver: the idle watch stopped, starting it again")
            self.minutes = None
            QTimer.singleShot(30_000 * self.failures, self.configure)

    def _read(self):
        if self.idle is None:
            return
        for line in bytes(self.idle.readAllStandardOutput()).decode(errors="ignore").split():
            if line == "idle":
                self.away = True
                self._idle()
            elif line == "resume":
                self.away = False
                self.retry.stop()
                self._resume()

    @staticmethod
    def inhibited() -> bool:
        """A program keeps the screen on (a film, a game, a presentation)."""
        try:
            import dbus
            bus = dbus.SessionBus()
            agent = bus.get_object("org.kde.Solid.PowerManagement.PolicyAgent",
                                   "/org/kde/Solid/PowerManagement/PolicyAgent")
            # PolicyAgent::ChangeScreenSettings, which org.freedesktop.ScreenSaver.Inhibit holds
            return bool(agent.HasInhibition(dbus.UInt32(4), dbus_interface="org.kde.Solid.PowerManagement.PolicyAgent",
                                            timeout=3))
        except Exception:  # noqa: BLE001
            pass
        try:
            import dbus
            inh = dbus.SessionBus().get_object("org.freedesktop.PowerManagement.Inhibit",
                                               "/org/freedesktop/PowerManagement/Inhibit")
            return bool(inh.HasInhibit(dbus_interface="org.freedesktop.PowerManagement.Inhibit", timeout=3))
        except Exception:  # noqa: BLE001
            return False

    def _idle(self):
        if not self.away or self.saver is not None or self.asking:
            return
        if self.inhibited() or screen_locked():
            self.retry.start(self.RETRY_MS)
            return
        try:
            from kwin_bridge import KWinBridge
            if self.bridge is None:
                self.bridge = KWinBridge("ScreenSaver")
                self.bridge.windowsChanged.connect(self._windows)
            if self.bridge.available():
                self.asking = True
                self.bridge.refresh()
                QTimer.singleShot(3000, self._no_answer)
                return
        except Exception:  # noqa: BLE001 - not on KWin: no full-screen check
            pass
        self._start()

    def _no_answer(self):
        if self.asking:
            self.asking = False
            self._start()

    def _windows(self, windows: list):
        if not self.asking:
            return
        self.asking = False
        if not self.away:
            return
        if any(w.get("active") and w.get("fullScreen") for w in windows):
            self.retry.start(self.RETRY_MS)       # a game or a film in front: no screen saver
            return
        self._start()

    def _start(self):
        if self.saver is not None or not self.away:
            return
        s = load_settings()
        if s["saver"] == "none":
            return
        self.saver_lock = bool(s["lock"])
        self.saver = self.QProcess()
        self.saver.setProgram(self.SAVER)
        self.saver.setArguments(["--run", s["saver"]] + (["--lock"] if self.saver_lock else []))
        self.saver.finished.connect(self._ended)
        self.saver_started = time.monotonic()
        self.saver.start()
        self.log(f"screen saver {s['saver']} started")

    def _ended(self, *_):
        proc, self.saver = self.saver, None
        if proc is not None:
            proc.deleteLater()

    def _resume(self):
        if self.saver is None:
            return
        if self.saver_lock and time.monotonic() - self.saver_started >= GRACE:
            lock_screen()             # before the screen saver goes, so the desktop never shows
        proc = self.saver
        proc.terminate()
        QTimer.singleShot(3000, lambda: proc.kill() if self.saver is proc else None)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(textwrap.dedent(__doc__.split("\n\n")[1]).strip("\n"))
        return 0
    if argv[0] == "--list":
        for key, (title, _cls) in SAVERS.items():
            print(f"{key}\t{title}")
        return 0
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-screensaver")
    app.setDesktopFileName("classic7-screensaver")
    if argv[0] == "--run":
        s = load_settings()
        name = argv[1] if len(argv) > 1 and not argv[1].startswith("--") else s["saver"]
        if name == "none":
            return 0
        return run(name, s, "--lock" in argv)
    app.setApplicationDisplayName(APP)
    w = SettingsWindow()
    w.show()
    w.finished.connect(app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
