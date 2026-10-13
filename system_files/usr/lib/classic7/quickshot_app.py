"""Quick Shot: screen capture in the style of Lightshot.

Ctrl+Up or PrtSc darkens the screen; drag over the part you want. A toolbar beside the area has
Pen, Line, Arrow, Rectangle, Marker, Text, Colour and Undo (the mouse wheel changes the line
width or text size); the bar under it has Open in Paint, E-mail, Print, Copy (Ctrl+C), Save
(Ctrl+S) and Close (Esc). Shift+PrtSc saves the whole screen straight to the screenshot folder.
Quick Shot stays in the notification area so a capture starts at once.

The picture comes from KWin's ScreenShot2 D-Bus interface through the small classic7-grab
helper (Spectacle as a fallback)."""
from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import (ClassInfo, QObject, QPoint, QPointF, QRect, QRectF, QSettings, QSize, Qt, QTimer, Slot)
from PySide6.QtDBus import QDBusConnection
from PySide6.QtGui import (QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QImage, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QSpinBox, QSystemTrayIcon, QTextEdit, QToolButton, QVBoxLayout, QWidget)

import accessories as acc

APP = "Quick Shot"
ICON = ("spectacle", "camera-photo", "applets-screenshooter")
SERVICE = "org.classic7.QuickShot"
PALETTE = ["#ff0000", "#ff8000", "#ffff00", "#00c000", "#00ffff", "#0060ff", "#8000ff", "#ff00ff",
           "#ffffff", "#c0c0c0", "#808080", "#000000", "#800000", "#008000", "#000080", "#804000"]
TOOLS = [("pen", "Pen", "draw-freehand"), ("line", "Line", "draw-line"), ("arrow", "Arrow", "draw-arrow"),
         ("rect", "Rectangle", "draw-rectangle"), ("marker", "Marker", "draw-highlight"),
         ("text", "Text", "draw-text")]


# ---- capturing ------------------------------------------------------------------------------
def grab_workspace() -> QImage | None:
    """The whole desktop (all screens) at full resolution, without Quick Shot's own windows."""
    img = _grab_kwin()
    if img is None:
        img = _grab_spectacle()
    return img


GRABBER = "/usr/libexec/classic7-grab"


def _grab_kwin() -> QImage | None:
    """KWin's ScreenShot2 through classic7-grab. KWin hands out screen pictures only to programs it
    knows by path (their desktop file asks for it), which a Python script can't be. The helper
    writes "width height stride format scale" on one line, then the pixels."""
    if not os.access(GRABBER, os.X_OK):
        return None
    try:
        p = subprocess.run([GRABBER], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    head, sep, data = p.stdout.partition(b"\n")
    if p.returncode != 0 or not sep:
        return None
    try:
        width, height, stride, fmt = (int(x) for x in head.split()[:4])
    except ValueError:
        return None
    if width <= 0 or height <= 0 or len(data) < stride * height:
        return None
    try:
        return QImage(data, width, height, stride, QImage.Format(fmt)).copy()
    except (ValueError, TypeError):
        return None


def _grab_spectacle() -> QImage | None:
    out = Path(tempfile.gettempdir()) / f"classic7-quickshot-{os.getpid()}.png"
    try:
        subprocess.run(["spectacle", "-b", "-n", "-f", "-o", str(out)], timeout=15, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        img = QImage(str(out))
        return None if img.isNull() else img
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        try:
            out.unlink()
        except OSError:
            pass


# ---- annotations ----------------------------------------------------------------------------
@dataclass
class Mark:
    kind: str                       # pen, line, arrow, rect, marker, text
    color: QColor
    width: int
    points: list = field(default_factory=list)     # QPointF in selection coordinates
    text: str = ""

    def paint(self, p: QPainter):
        if self.kind == "text":
            if not self.points or not self.text:
                return
            f = QFont()
            f.setPixelSize(self.width)
            f.setBold(True)
            p.setFont(f)
            p.setPen(self.color)
            fm = QFontMetrics(f)
            x, y = self.points[0].x(), self.points[0].y()
            for i, line in enumerate(self.text.split("\n")):
                p.drawText(QPointF(x, y + fm.ascent() + i * fm.lineSpacing()), line)
            return
        if not self.points:
            return
        color = QColor(self.color)
        if self.kind == "marker":
            color.setAlpha(110)
        pen = QPen(color, self.width, Qt.SolidLine, Qt.RoundCap if self.kind != "marker" else Qt.SquareCap,
                   Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        a = self.points[0]
        b = self.points[-1]
        if self.kind in ("pen", "marker"):
            if len(self.points) == 1:
                p.drawPoint(a)
            else:
                path = QPainterPath(a)
                for q in self.points[1:]:
                    path.lineTo(q)
                p.drawPath(path)
        elif self.kind == "line":
            p.drawLine(a, b)
        elif self.kind == "rect":
            p.drawRect(QRectF(a, b).normalized())
        elif self.kind == "arrow":
            p.drawLine(a, b)
            ang = math.atan2(b.y() - a.y(), b.x() - a.x())
            size = 8 + self.width * 3
            left = QPointF(b.x() - size * math.cos(ang - 0.45), b.y() - size * math.sin(ang - 0.45))
            right = QPointF(b.x() - size * math.cos(ang + 0.45), b.y() - size * math.sin(ang + 0.45))
            p.setBrush(color)
            p.setPen(QPen(color, 1))
            p.drawPolygon(QPolygonF([b, left, right]))


# ---- the dark screen ----------------------------------------------------------------------
class ToolBar(QFrame):
    def __init__(self, parent, vertical: bool):
        super().__init__(parent)
        self.setStyleSheet("ToolBar { background: #f4f4f4; border: 1px solid #8a8a8a; border-radius: 3px; }"
                           "QToolButton { border: 1px solid transparent; border-radius: 2px; padding: 2px; }"
                           "QToolButton:hover { border-color: #7aa7e0; background: #e3eefc; }"
                           "QToolButton:checked { border-color: #4b7bc2; background: #cfe0fa; }")
        self.lay = QVBoxLayout(self) if vertical else QHBoxLayout(self)
        self.lay.setContentsMargins(2, 2, 2, 2)
        self.lay.setSpacing(1)

    def button(self, icon_names: tuple, tip: str, slot, checkable=False, text="") -> QToolButton:
        b = QToolButton(self)
        ic = acc.icon(*icon_names)
        if ic.isNull() and text:
            b.setText(text)
        else:
            b.setIcon(ic)
        b.setIconSize(QSize(20, 20))
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(slot)
        self.lay.addWidget(b)
        return b


class Overlay(QWidget):
    """One per screen: the frozen picture of that screen, darkened except the chosen area."""

    def __init__(self, shot: "Capture", screen, image: QImage):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.shot = shot
        self.screen_ = screen
        self.image = image                     # this screen's part, device pixels
        self.dpr = image.width() / max(1, screen.geometry().width())
        self.pix = QPixmap.fromImage(image)
        self.pix.setDevicePixelRatio(self.dpr)
        self.setWindowTitle("Quick Shot")
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_DeleteOnClose)

    def paintEvent(self, _):
        p = QPainter(self)
        p.drawPixmap(0, 0, self.pix)
        p.fillRect(self.rect(), QColor(0, 0, 0, 115))
        sel = self.shot.selection if self.shot.owner is self else None
        if sel is None or sel.isEmpty():
            if self.shot.owner is None:
                p.setPen(QColor("white"))
                f = self.font()
                f.setPixelSize(15)
                p.setFont(f)
                if self.underMouse() or self.screen_ is QGuiApplication.screenAt(QCursor.pos()):
                    p.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                               "Drag over the part of the screen you want.  Esc cancels.")
            return
        p.drawPixmap(QRectF(sel), self.pix, QRectF(sel.x() * self.dpr, sel.y() * self.dpr,
                                                   sel.width() * self.dpr, sel.height() * self.dpr))
        p.save()
        p.setClipRect(sel)
        p.translate(sel.topLeft())
        for m in self.shot.marks:
            m.paint(p)
        if self.shot.drawing is not None:
            self.shot.drawing.paint(p)
        p.restore()
        pen = QPen(QColor("#ffffff"), 1, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(sel.adjusted(0, 0, -1, -1))
        p.setPen(QPen(QColor("#000000"), 1, Qt.DotLine))
        p.drawRect(sel.adjusted(-1, -1, 0, 0))
        if not self.shot.marks and self.shot.tool is None:
            for h in self.shot.handles(sel).values():
                p.fillRect(h, QColor("white"))
                p.setPen(QColor("#333"))
                p.drawRect(h)
        # size label: "640 x 480"
        w = round(sel.width() * self.dpr)
        h = round(sel.height() * self.dpr)
        label = f"{w} x {h}"
        f = self.font()
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetrics(f)
        box = QRect(0, 0, fm.horizontalAdvance(label) + 10, fm.height() + 4)
        box.moveBottomLeft(QPoint(sel.left(), sel.top() - 3))
        if box.top() < 0:
            box.moveTopLeft(QPoint(sel.left() + 3, sel.top() + 3))
        p.fillRect(box, QColor(0, 0, 0, 170))
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignCenter, label)

    def mousePressEvent(self, e):
        self.shot.press(self, e)

    def mouseMoveEvent(self, e):
        self.shot.move(self, e)

    def mouseReleaseEvent(self, e):
        self.shot.release(self, e)

    def mouseDoubleClickEvent(self, e):
        if self.shot.selection is not None and self.shot.selection.contains(e.position().toPoint()) \
                and self.shot.tool is None:
            self.shot.copy()

    def wheelEvent(self, e):
        self.shot.wheel(e.angleDelta().y())

    def keyPressEvent(self, e):
        self.shot.key(e)


class Capture(QObject):
    """One capture: the overlays, the chosen area, the marks and the two toolbars."""

    def __init__(self, app: "QuickShot", image: QImage):
        super().__init__()
        self.app = app
        self.settings = app.settings
        self.full = image
        self.overlays: list[Overlay] = []
        self.owner: Overlay | None = None
        self.selection: QRect | None = None
        self.marks: list[Mark] = []
        self.drawing: Mark | None = None
        self.tool: str | None = None
        self.color = QColor(self.settings.value("color", "#ff0000"))
        self.widths = {"pen": 3, "line": 3, "arrow": 3, "rect": 3, "marker": 18, "text": 22}
        self.drag_mode: str | None = None     # new, move, a handle name
        self.drag_start = QPoint()
        self.sel_start = QRect()
        self.text_edit: QTextEdit | None = None
        self.side: ToolBar | None = None
        self.bottom: ToolBar | None = None
        self.tool_buttons: dict[str, QToolButton] = {}
        screens = QGuiApplication.screens()
        virt = QRect()
        for s in screens:
            virt = virt.united(s.geometry())
        scale = image.width() / max(1, virt.width())
        for s in screens:
            g = s.geometry()
            part = image.copy(QRect(round((g.x() - virt.x()) * scale), round((g.y() - virt.y()) * scale),
                                    round(g.width() * scale), round(g.height() * scale)))
            ov = Overlay(self, s, part)
            ov.setScreen(s)
            ov.setGeometry(g)
            self.overlays.append(ov)
        for ov in self.overlays:
            ov.showFullScreen()
            ov.raise_()
        if self.overlays:
            target = QGuiApplication.screenAt(QCursor.pos())
            focus = next((o for o in self.overlays if o.screen_ is target), self.overlays[0])
            focus.activateWindow()
            focus.setFocus()

    # ---- geometry -------------------------------------------------------------------------
    @staticmethod
    def handles(sel: QRect) -> dict[str, QRect]:
        s = 7
        cx, cy = sel.center().x(), sel.center().y()
        pts = {"tl": (sel.left(), sel.top()), "t": (cx, sel.top()), "tr": (sel.right(), sel.top()),
               "l": (sel.left(), cy), "r": (sel.right(), cy), "bl": (sel.left(), sel.bottom()),
               "b": (cx, sel.bottom()), "br": (sel.right(), sel.bottom())}
        return {k: QRect(x - s // 2, y - s // 2, s, s) for k, (x, y) in pts.items()}

    def _handle_at(self, pos: QPoint) -> str | None:
        if self.selection is None or self.marks or self.tool:
            return None
        for name, r in self.handles(self.selection).items():
            if r.adjusted(-3, -3, 3, 3).contains(pos):
                return name
        return None

    def _update(self):
        for ov in self.overlays:
            ov.update()

    # ---- mouse --------------------------------------------------------------------------------
    def press(self, ov: Overlay, e):
        pos = e.position().toPoint()
        if e.button() == Qt.RightButton:
            if self.selection is None:
                self.close()
            return
        if e.button() != Qt.LeftButton:
            return
        self._commit_text()
        if self.selection is not None and ov is self.owner:
            if self.tool and self.selection.contains(pos):
                local = QPointF(pos - self.selection.topLeft())
                if self.tool == "text":
                    self._start_text(ov, pos)
                    return
                self.drawing = Mark(self.tool, QColor(self.color), self.widths[self.tool], [local])
                self.drag_mode = "draw"
                return
            if self.tool:
                return          # drawing happens inside the area only
            handle = self._handle_at(pos)
            if handle:
                self.drag_mode = handle
            elif self.selection.contains(pos) and not self.marks:
                self.drag_mode = "move"
            elif not self.marks:
                self.drag_mode = "new"
                self.selection = QRect(pos, pos)
            else:
                return
        else:
            if self.marks:
                return
            self._hide_bars()
            self.owner = ov
            self.selection = QRect(pos, pos)
            self.drag_mode = "new"
        self.drag_start = pos
        self.sel_start = QRect(self.selection)
        self._update()

    def move(self, ov: Overlay, e):
        pos = e.position().toPoint()
        if self.drag_mode is None:
            if self.selection is not None and ov is self.owner:
                h = self._handle_at(pos)
                cursors = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
                           "bl": Qt.SizeBDiagCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
                           "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor}
                if h:
                    ov.setCursor(cursors[h])
                elif self.tool and self.selection.contains(pos):
                    ov.setCursor(Qt.IBeamCursor if self.tool == "text" else Qt.CrossCursor)
                elif self.selection.contains(pos) and not self.marks and not self.tool:
                    ov.setCursor(Qt.SizeAllCursor)
                else:
                    ov.setCursor(Qt.CrossCursor)
            else:
                ov.update()
            return
        if ov is not self.owner:
            return
        bounds = ov.rect()
        if self.drag_mode == "draw" and self.drawing is not None:
            local = QPointF(pos - self.selection.topLeft())
            if self.drawing.kind in ("pen", "marker"):
                self.drawing.points.append(local)
            else:
                self.drawing.points = [self.drawing.points[0], local]
                if e.modifiers() & Qt.ShiftModifier and self.drawing.kind in ("line", "arrow"):
                    a = self.drawing.points[0]
                    d = local - a
                    if abs(d.x()) > abs(d.y()):
                        self.drawing.points[1] = QPointF(local.x(), a.y())
                    else:
                        self.drawing.points[1] = QPointF(a.x(), local.y())
            ov.update()
            return
        d = pos - self.drag_start
        r = QRect(self.sel_start)
        if self.drag_mode == "new":
            r = QRect(self.drag_start, pos).normalized()
        elif self.drag_mode == "move":
            r.translate(d)
            r.moveLeft(max(0, min(r.left(), bounds.width() - r.width())))
            r.moveTop(max(0, min(r.top(), bounds.height() - r.height())))
        else:
            if "l" in self.drag_mode:
                r.setLeft(r.left() + d.x())
            if "r" in self.drag_mode:
                r.setRight(r.right() + d.x())
            if "t" in self.drag_mode:
                r.setTop(r.top() + d.y())
            if "b" in self.drag_mode:
                r.setBottom(r.bottom() + d.y())
            r = r.normalized()
        self.selection = r.intersected(bounds)
        ov.update()

    def release(self, ov: Overlay, e):
        if e.button() != Qt.LeftButton:
            return
        if self.drag_mode == "draw" and self.drawing is not None:
            if len(self.drawing.points) > 1 or self.drawing.kind in ("pen", "marker"):
                self.marks.append(self.drawing)
            self.drawing = None
        self.drag_mode = None
        if self.selection is not None and (self.selection.width() < 3 or self.selection.height() < 3):
            # a click without dragging: the whole screen it was on
            self.selection = ov.rect()
            self.owner = ov
        if self.selection is not None:
            self._show_bars()
        self._update()

    def wheel(self, delta: int):
        if not self.tool:
            return
        step = 1 if delta > 0 else -1
        lo, hi = (8, 96) if self.tool == "text" else ((6, 60) if self.tool == "marker" else (1, 30))
        mult = 2 if self.tool in ("text", "marker") else 1
        self.widths[self.tool] = max(lo, min(hi, self.widths[self.tool] + step * mult))
        if self.text_edit is not None and self.tool == "text":
            f = self.text_edit.font()
            f.setPixelSize(self.widths["text"])
            self.text_edit.setFont(f)
        self.owner.setToolTip(f"Size: {self.widths[self.tool]}")

    def key(self, e):
        k, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        if k == Qt.Key_Escape:
            if self.text_edit is not None:
                self._commit_text()
                return
            self.close()
        elif ctrl and k == Qt.Key_C:
            self.copy()
        elif ctrl and k == Qt.Key_S:
            self.save()
        elif ctrl and k == Qt.Key_P:
            self.print_()
        elif ctrl and k == Qt.Key_Z:
            self.undo()
        elif ctrl and k == Qt.Key_A:
            target = self.owner or next((o for o in self.overlays if o.screen_ is
                                         QGuiApplication.screenAt(QCursor.pos())), self.overlays[0])
            if not self.marks:
                self.owner = target
                self.selection = target.rect()
                self._show_bars()
                self._update()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.selection is not None:
            self.copy()

    # ---- text ---------------------------------------------------------------------------------
    def _start_text(self, ov: Overlay, pos: QPoint):
        ed = QTextEdit(ov)
        ed.setFrameStyle(0)
        ed.setAcceptRichText(False)
        ed.setStyleSheet(f"QTextEdit {{ background: transparent; color: {self.color.name()};"
                         " border: 1px dashed #ffffff; }")
        f = ed.font()
        f.setPixelSize(self.widths["text"])
        f.setBold(True)
        ed.setFont(f)
        ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.document().setDocumentMargin(0)
        sel = self.selection
        ed.setGeometry(QRect(pos, QSize(max(60, sel.right() - pos.x()), max(30, sel.bottom() - pos.y()))))
        ed.show()
        ed.setFocus()
        self.text_edit = ed
        self.text_pos = QPointF(pos - sel.topLeft())

    def _commit_text(self):
        ed = self.text_edit
        if ed is None:
            return
        self.text_edit = None
        text = ed.toPlainText().rstrip()
        if text:
            self.marks.append(Mark("text", QColor(self.color), ed.font().pixelSize(), [self.text_pos], text))
        ed.hide()
        ed.deleteLater()
        self._update()

    # ---- toolbars -------------------------------------------------------------------------------
    def _hide_bars(self):
        for bar in (self.side, self.bottom):
            if bar is not None:
                bar.deleteLater()
        self.side = self.bottom = None

    def _show_bars(self):
        ov = self.owner
        if ov is None or self.selection is None:
            return
        if self.side is None or self.side.parent() is not ov:
            self._hide_bars()
            self.side = ToolBar(ov, vertical=True)
            self.tool_buttons = {}
            for key, tip, icon_name in TOOLS:
                self.tool_buttons[key] = self.side.button((icon_name, "draw-freehand"), tip,
                                                          lambda _c=False, k=key: self.set_tool(k), checkable=True,
                                                          text=tip[0])
            self.color_btn = self.side.button(("color-picker", "color-management"), "Colour",
                                              self.choose_color, text="C")
            self._paint_color_button()
            self.side.button(("edit-undo",), "Undo (Ctrl+Z)", self.undo, text="U")
            self.bottom = ToolBar(ov, vertical=False)
            self.bottom.button(("kolourpaint", "applications-graphics"), "Open in Paint", self.open_in_paint,
                               text="Paint")
            self.bottom.button(("mail-send", "mail-message-new"), "Send by e-mail", self.email, text="Mail")
            self.bottom.button(("document-print",), "Print (Ctrl+P)", self.print_, text="Print")
            self.bottom.button(("edit-copy",), "Copy (Ctrl+C)", self.copy, text="Copy")
            self.bottom.button(("document-save",), "Save (Ctrl+S)", self.save, text="Save")
            self.bottom.button(("window-close",), "Close (Esc)", self.close, text="X")
            self.side.adjustSize()
            self.bottom.adjustSize()
            self.side.show()
            self.bottom.show()
        sel = self.selection
        b = ov.rect()
        sw, sh = self.side.width(), self.side.height()
        x = sel.right() + 6
        if x + sw > b.right():
            x = sel.left() - sw - 6 if sel.left() - sw - 6 >= 0 else sel.right() - sw - 4
        y = max(0, min(sel.top(), b.bottom() - sh))
        self.side.move(x, y)
        bw, bh = self.bottom.width(), self.bottom.height()
        bx = max(0, min(sel.right() - bw + 1, b.right() - bw))
        by = sel.bottom() + 6
        if by + bh > b.bottom():
            by = sel.top() - bh - 6 if sel.top() - bh - 6 >= 0 else sel.bottom() - bh - 4
        self.bottom.move(bx, by)
        self.side.raise_()
        self.bottom.raise_()

    def _paint_color_button(self):
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setPen(QColor("#333"))
        p.setBrush(self.color)
        p.drawRoundedRect(2, 2, 15, 15, 3, 3)
        p.end()
        self.color_btn.setIcon(QIcon(pm))

    def set_tool(self, key: str):
        self._commit_text()
        self.tool = None if self.tool == key else key
        for k, b in self.tool_buttons.items():
            b.setChecked(k == self.tool)
        self._update()

    def choose_color(self):
        menu = QMenu(self.owner)
        grid_w = QWidget()
        grid = QGridLayout(grid_w)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setSpacing(3)
        for i, c in enumerate(PALETTE):
            b = QToolButton()
            b.setFixedSize(20, 20)
            b.setStyleSheet(f"QToolButton {{ background: {c}; border: 1px solid #555; }}")
            b.clicked.connect(lambda _c=False, col=c: (self._set_color(col), menu.close()))
            grid.addWidget(b, i // 8, i % 8)
        from PySide6.QtWidgets import QWidgetAction
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(grid_w)
        menu.addAction(wa)
        menu.addSeparator()
        more = menu.addAction("More colours...")

        def pick_more():
            from PySide6.QtWidgets import QColorDialog
            c = QColorDialog.getColor(self.color, self.owner, "Colour")
            if c.isValid():
                self._set_color(c.name())
        more.triggered.connect(pick_more)
        menu.exec(self.color_btn.mapToGlobal(QPoint(self.color_btn.width(), 0)))

    def _set_color(self, name: str):
        self.color = QColor(name)
        self.settings.setValue("color", name)
        self._paint_color_button()
        if self.text_edit is not None:
            self.text_edit.setStyleSheet(f"QTextEdit {{ background: transparent; color: {name};"
                                         " border: 1px dashed #ffffff; }")

    def undo(self):
        if self.text_edit is not None:
            self.text_edit.deleteLater()
            self.text_edit = None
        elif self.marks:
            self.marks.pop()
        self._update()

    # ---- results ----------------------------------------------------------------------------
    def result(self) -> QImage | None:
        self._commit_text()
        ov, sel = self.owner, self.selection
        if ov is None or sel is None or sel.isEmpty():
            return None
        dpr = ov.dpr
        src = QRect(round(sel.x() * dpr), round(sel.y() * dpr), round(sel.width() * dpr), round(sel.height() * dpr))
        img = ov.image.copy(src).convertToFormat(QImage.Format_ARGB32)
        if self.marks:
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.scale(dpr, dpr)
            for m in self.marks:
                m.paint(p)
            p.end()
        return img

    def copy(self):
        img = self.result()
        if img is not None:
            QApplication.clipboard().setImage(img)
        self.close()

    def save(self):
        img = self.result()
        if img is None:
            return
        for ov in self.overlays:
            ov.hide()
        path = self.app.ask_save_path()
        if path:
            self.app.write_image(img, path)
            self.close()
        else:
            for ov in self.overlays:
                ov.showFullScreen()
            if self.owner:
                self.owner.activateWindow()

    def _temp_file(self) -> str | None:
        img = self.result()
        if img is None:
            return None
        d = Path(tempfile.gettempdir()) / "classic7-quickshot"
        d.mkdir(exist_ok=True)
        path = d / f"Screenshot {time.strftime('%Y-%m-%d %H.%M.%S')}.png"
        img.save(str(path), "PNG")
        return str(path)

    def open_in_paint(self):
        path = self._temp_file()
        if path:
            subprocess.Popen(["classic7-paint", path], start_new_session=True)
        self.close()

    def email(self):
        path = self._temp_file()
        if path:
            try:
                subprocess.Popen(["classic7-mail", "--compose", "--attach", path], start_new_session=True)
            except OSError:
                pass
        self.close()

    def print_(self):
        img = self.result()
        if img is None:
            return
        for ov in self.overlays:
            ov.hide()
        printer = QPrinter(QPrinter.HighResolution)
        dlg = QPrintDialog(printer)
        if dlg.exec() == QDialog.Accepted:
            p = QPainter(printer)
            page = printer.pageLayout().paintRectPixels(printer.resolution())
            size = img.size().scaled(page.size(), Qt.KeepAspectRatio)
            if img.width() * 3 < page.width():         # small captures at their real size
                size = img.size() * (printer.resolution() / 96)
            p.drawImage(QRect(QPoint(0, 0), size), img)
            p.end()
        self.close()

    def close(self):
        self._hide_bars()
        for ov in self.overlays:
            ov.close()
        self.overlays = []
        self.app.capture_done(self)


@ClassInfo({"D-Bus Interface": SERVICE})
class DBusApi(QObject):
    def __init__(self, app: "QuickShot"):
        super().__init__()
        self.app = app

    @Slot(str)
    def Capture(self, mode: str):  # noqa: N802 - D-Bus method name
        QTimer.singleShot(0, lambda: self.app.capture(mode or "region"))


class Options(QDialog):
    def __init__(self, app: "QuickShot"):
        super().__init__()
        self.app = app
        s = app.settings
        self.setWindowTitle(f"{APP} Options")
        self.setWindowIcon(acc.icon(*ICON))
        form = QFormLayout(self)
        row = QHBoxLayout()
        self.folder = QLineEdit(app.folder())
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        form.addRow("Save screenshots in:", row)
        self.fmt = QComboBox()
        self.fmt.addItems(["PNG", "JPEG", "BMP"])
        self.fmt.setCurrentText(s.value("format", "PNG"))
        form.addRow("Image format:", self.fmt)
        self.quality = QSpinBox()
        self.quality.setRange(10, 100)
        self.quality.setSuffix(" %")
        self.quality.setValue(int(s.value("quality", 90)))
        form.addRow("JPEG quality:", self.quality)
        self.tray = QCheckBox("Show the icon in the notification area")
        self.tray.setChecked(s.value("tray", True, bool))
        form.addRow(self.tray)
        keys = QLabel("<b>Ctrl+Up</b> or <b>PrtSc</b>: select an area<br><b>Shift+PrtSc</b>: save the whole screen"
                      "<br><small>Change them in Control Panel &gt; Keyboard &gt; Shortcuts.</small>")
        keys.setTextFormat(Qt.RichText)
        form.addRow("Keys:", keys)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Save screenshots in", self.folder.text())
        if d:
            self.folder.setText(d)

    def accept(self):
        s = self.app.settings
        s.setValue("folder", self.folder.text())
        s.setValue("format", self.fmt.currentText())
        s.setValue("quality", self.quality.value())
        s.setValue("tray", self.tray.isChecked())
        self.app.tray.setVisible(self.tray.isChecked())
        super().accept()


class QuickShot(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.settings = QSettings("Classic7", "QuickShot")
        self.current: Capture | None = None
        self.tray = QSystemTrayIcon(acc.icon(*ICON))
        self.tray.setToolTip(f"{APP}: Ctrl+Up or PrtSc to capture")
        menu = QMenu()
        menu.addAction("Capture an area\tCtrl+Up", lambda: self.capture("region"))
        menu.addAction("Save the whole screen\tShift+PrtSc", lambda: self.capture("full"))
        menu.addSeparator()
        menu.addAction("Open screenshot folder", self.open_folder)
        menu.addAction("Options...", lambda: Options(self).exec())
        menu.addSeparator()
        menu.addAction("About Quick Shot", lambda: acc.about(None, APP, ICON,
                                                            "Screen capture in the style of Lightshot."))
        menu.addAction("Exit", qapp.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: reason == QSystemTrayIcon.Trigger and self.capture("region"))
        self.tray.setVisible(self.settings.value("tray", True, bool))
        self.api = DBusApi(self)
        bus = QDBusConnection.sessionBus()
        self.registered = bus.registerService(SERVICE) and bus.registerObject("/QuickShot", self.api,
                                                                              QDBusConnection.ExportAllSlots)

    def folder(self) -> str:
        return self.settings.value("folder", str(Path(acc.pictures_dir()) / "Screenshots"))

    def next_name(self, ext: str) -> str:
        d = Path(self.folder())
        n = 1
        while (d / f"Screenshot_{n}.{ext}").exists():
            n += 1
        return str(d / f"Screenshot_{n}.{ext}")

    def ask_save_path(self) -> str | None:
        fmt = self.settings.value("format", "PNG")
        ext = {"PNG": "png", "JPEG": "jpg", "BMP": "bmp"}.get(fmt, "png")
        last = self.settings.value("last_dir", self.folder())
        Path(last).mkdir(parents=True, exist_ok=True)
        start = str(Path(last) / Path(self.next_name(ext)).name)
        path, _f = QFileDialog.getSaveFileName(None, "Save As", start,
                                               "PNG (*.png);;JPEG (*.jpg *.jpeg);;BMP (*.bmp)")
        if path:
            self.settings.setValue("last_dir", str(Path(path).parent))
        return path or None

    def write_image(self, img: QImage, path: str) -> bool:
        ext = Path(path).suffix.lower().lstrip(".") or "png"
        if ext not in ("png", "jpg", "jpeg", "bmp"):
            path += ".png"
            ext = "png"
        q = int(self.settings.value("quality", 90)) if ext in ("jpg", "jpeg") else -1
        if ext in ("jpg", "jpeg", "bmp"):
            img = img.convertToFormat(QImage.Format_RGB32)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        ok = img.save(path, None, q)
        if not ok:
            QMessageBox.warning(None, APP, f"The picture could not be saved:\n{path}")
        return ok

    def capture(self, mode: str = "region"):
        if self.current is not None:
            return
        img = grab_workspace()
        if img is None or img.isNull():
            QMessageBox.warning(None, APP, "The screen could not be captured.")
            return
        if mode == "full":
            fmt = self.settings.value("format", "PNG")
            ext = {"PNG": "png", "JPEG": "jpg", "BMP": "bmp"}.get(fmt, "png")
            path = self.next_name(ext)
            if self.write_image(img, path):
                QApplication.clipboard().setImage(img)
                try:
                    subprocess.Popen(["notify-send", "-a", APP, "-i", "spectacle", "Screenshot saved", path],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    pass
            return
        self.current = Capture(self, img)

    def capture_done(self, cap: Capture):
        if self.current is cap:
            self.current = None
            cap.deleteLater()

    def open_folder(self):
        d = Path(self.folder())
        d.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(d)], start_new_session=True)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-quickshot")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-quickshot")
    app.setQuitOnLastWindowClosed(False)
    mode = "region"
    if "--full" in argv:
        mode = "full"
    shot = QuickShot(app)
    if not shot.registered:
        # another Quick Shot runs: let it do the capture
        from PySide6.QtDBus import QDBusInterface
        other = QDBusInterface(SERVICE, "/QuickShot", SERVICE, QDBusConnection.sessionBus())
        if other.isValid() and "--background" not in argv:
            other.call("Capture", mode)
        return 0
    if "--background" not in argv:
        QTimer.singleShot(0, lambda: shot.capture(mode))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
