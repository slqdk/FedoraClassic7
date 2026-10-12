"""Photo Viewer: look at the pictures of a folder one at a time, in the style of Windows 7.

    Left / Right       previous / next picture (wraps around)
    Ctrl+. / Ctrl+,    turn clockwise / counterclockwise (saved when you leave the picture)
    Ctrl+Shift+H / V   flip horizontally / vertically
    Wheel, Ctrl +/-    zoom; drag to move a zoomed picture
    Ctrl+0             fit to window; Ctrl+Alt+0 actual size
    F11, F5            slide show (Esc ends it)
    Del                move to the Recycle Bin; F2 rename; Ctrl+C copy; Ctrl+P print
"""
from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import sys
import tempfile
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QFile, QFileSystemWatcher, QMimeData, QObject, QPointF, QRectF, QSettings, QSize,
                            Qt, QTimer, QUrl, QVariantAnimation, Signal)
from PySide6.QtGui import (QAction, QColor, QColorSpace, QCursor, QGuiApplication, QIcon, QImage, QImageReader,
                           QKeySequence, QLinearGradient, QMovie, QPainter, QPen, QPixmap, QTransform)
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu,
                               QMessageBox, QSizePolicy, QSlider, QToolButton, QVBoxLayout, QWidget)

import photos_core as core
from photos_icons import GlyphButton, app_icon_pixmap

APP = "Photo Viewer"
NOT_PICTURES = {"pdf", "ps", "eps", "epsf", "epsi"}
MAX_ZOOM = 16.0
FIT_MARGIN = 10
SLIDE_SPEEDS = {"slow": 7000, "medium": 4000, "fast": 2000}


def picture_extensions() -> set[str]:
    exts = {bytes(f).decode().lower() for f in QImageReader.supportedImageFormats()} - NOT_PICTURES
    if exts & {"jpg", "jpeg"}:
        exts |= {"jpg", "jpeg", "jpe", "jfif"}
    if exts & {"tif", "tiff"}:
        exts |= {"tif", "tiff"}
    if exts & {"heif", "heic"}:
        exts |= {"heif", "heic", "hif"}
    return exts


def apply_op(img: QImage, op) -> QImage:
    if op == core.IDENTITY or img.isNull():
        return img
    a, b, c, d = op
    return img.transformed(QTransform(a, c, b, d, 0, 0))


def human_size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n} {unit}" if unit == "bytes" else f"{n:.1f} {unit}".replace(".0 ", " ")
        n /= 1024
    return str(n)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


# ---- loading pictures in the background ------------------------------------------------------
class Loaded:
    def __init__(self, path: Path):
        self.path = path
        self.image = QImage()
        self.error = ""
        self.animated = False
        self.fmt = ""
        self.mtime = _mtime(path)


def _prepare(img: QImage) -> QImage:
    try:
        cs = img.colorSpace()
        if cs.isValid() and cs != QColorSpace(QColorSpace.NamedColorSpace.SRgb):
            if img.format() in (QImage.Format_Indexed8, QImage.Format_Mono, QImage.Format_MonoLSB):
                img = img.convertToFormat(QImage.Format_ARGB32)
            img.convertToColorSpace(QColorSpace(QColorSpace.NamedColorSpace.SRgb))
    except Exception:   # noqa: BLE001 (odd profiles: show the picture as it is)
        pass
    want = QImage.Format_ARGB32_Premultiplied if img.hasAlphaChannel() else QImage.Format_RGB32
    return img if img.format() == want else img.convertToFormat(want)


def _pil_load(path: Path) -> QImage:
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGBA")
            data = im.tobytes("raw", "RGBA")
            return QImage(data, im.width, im.height, 4 * im.width, QImage.Format_RGBA8888).copy()
    except Exception:   # noqa: BLE001
        return QImage()


def load_picture(path: Path) -> Loaded:
    res = Loaded(path)
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    res.fmt = bytes(reader.format()).decode()
    res.animated = bool(reader.supportsAnimation() and reader.imageCount() > 1)
    img = reader.read()
    if img.isNull():
        err = reader.errorString()
        img = _pil_load(path)
        if img.isNull():
            if not path.exists():
                err = "the file was moved or deleted"
            elif "Unsupported" in err or "unknown" in err.lower():
                err = "the file type isn't supported, or the file is damaged"
            res.error = err[:1].lower() + err[1:] if err else "the file is damaged"
            return res
    res.image = _prepare(img)
    return res


class Loader(QObject):
    done = Signal(object)
    _finished = Signal(object)

    def __init__(self, keep: int = 4):
        super().__init__()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.cache: OrderedDict[str, Loaded] = OrderedDict()
        self.pending: set[str] = set()
        self.keep = keep
        self.closed = False
        self._finished.connect(self._store)

    def get(self, path: Path) -> Loaded | None:
        e = self.cache.get(str(path))
        if e is not None and e.mtime == _mtime(path):
            self.cache.move_to_end(str(path))
            return e
        return None

    def put(self, res: Loaded):
        self.cache[str(res.path)] = res
        self.cache.move_to_end(str(res.path))
        while len(self.cache) > self.keep:
            self.cache.popitem(last=False)

    def forget(self, path: Path):
        self.cache.pop(str(path), None)

    def request(self, path: Path):
        key = str(path)
        if self.closed or key in self.pending or self.get(path) is not None:
            return
        self.pending.add(key)
        fut = self.pool.submit(load_picture, path)
        fut.add_done_callback(lambda f: self._finished.emit(f.result()))

    def _store(self, res: Loaded):
        self.pending.discard(str(res.path))
        if not res.error:
            self.put(res)
        self.done.emit(res)


# ---- the picture area ------------------------------------------------------------------------
class Canvas(QWidget):
    zoomChanged = Signal()
    doubleClicked = Signal()
    menuRequested = Signal(object)

    def __init__(self, dark: bool = False, parent=None):
        super().__init__(parent)
        self.dark = dark
        self.img = QImage()
        self.message = ""
        self.scale: float | None = None        # None: fit to the window
        self.focus = QPointF()                 # picture point shown in the middle of the window
        self._scaled_key = None
        self._scaled = QImage()
        self._drag = None
        self._old: tuple[QImage, QRectF] | None = None
        self._fade = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(700)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._fade_step)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # -- state
    def set_image(self, img: QImage, keep_view: bool = False, fade: bool = False):
        if fade and not self.img.isNull():
            r = self.target_rect()
            self._old = (self._scaled_for(self.eff_scale()), r)
            self._fade = 0.0
            self._anim.stop()
            self._anim.start()
        else:
            self._old = None
            self._fade = 1.0
        self.img = img
        self.message = ""
        if not keep_view or self.img.isNull():
            self.scale = None
            self.focus = QPointF(img.width() / 2, img.height() / 2)
        self._clamp()
        self._update_cursor()
        self.update()
        self.zoomChanged.emit()

    def set_message(self, text: str):
        self.img = QImage()
        self._old = None
        self.message = text
        self.scale = None
        self._update_cursor()
        self.update()
        self.zoomChanged.emit()

    def _fade_step(self, v):
        self._fade = float(v)
        if self._fade >= 1.0:
            self._old = None
        self.update()

    def fit_scale(self) -> float:
        if self.img.isNull():
            return 1.0
        m = 0 if self.dark else 2 * FIT_MARGIN
        return min(1.0, max(1, self.width() - m) / self.img.width(), max(1, self.height() - m) / self.img.height())

    def eff_scale(self) -> float:
        return self.fit_scale() if self.scale is None else self.scale

    def min_scale(self) -> float:
        return min(self.fit_scale(), 1.0)

    def is_fit(self) -> bool:
        return self.scale is None

    def can_pan(self) -> bool:
        if self.img.isNull():
            return False
        s = self.eff_scale()
        return self.img.width() * s > self.width() + 0.5 or self.img.height() * s > self.height() + 0.5

    def set_zoom(self, s: float | None, anchor: QPointF | None = None):
        if self.img.isNull():
            return
        if s is not None:
            s = max(self.min_scale(), min(MAX_ZOOM, s))
            if s <= self.fit_scale() + 1e-6:
                s = None
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        old = self.eff_scale()
        pt = self.focus + (anchor - QPointF(self.width() / 2, self.height() / 2)) / old
        self.scale = s
        new = self.eff_scale()
        if s is None:
            self.focus = QPointF(self.img.width() / 2, self.img.height() / 2)
        else:
            self.focus = pt - (anchor - QPointF(self.width() / 2, self.height() / 2)) / new
        self._clamp()
        self._update_cursor()
        self.update()
        self.zoomChanged.emit()

    def zoom_by(self, factor: float, anchor: QPointF | None = None):
        self.set_zoom(self.eff_scale() * factor, anchor)

    def _clamp(self):
        if self.img.isNull():
            return
        s = self.eff_scale()
        w, h = self.img.width(), self.img.height()
        x, y = self.focus.x(), self.focus.y()
        half_w, half_h = self.width() / 2 / s, self.height() / 2 / s
        x = w / 2 if w <= 2 * half_w else max(half_w, min(w - half_w, x))
        y = h / 2 if h <= 2 * half_h else max(half_h, min(h - half_h, y))
        self.focus = QPointF(x, y)

    def target_rect(self) -> QRectF:
        s = self.eff_scale()
        dpr = self.devicePixelRatioF()
        x0 = self.width() / 2 - self.focus.x() * s
        y0 = self.height() / 2 - self.focus.y() * s
        x0, y0 = round(x0 * dpr) / dpr, round(y0 * dpr) / dpr
        return QRectF(x0, y0, self.img.width() * s, self.img.height() * s)

    def _scaled_for(self, s: float) -> QImage:
        dpr = self.devicePixelRatioF()
        w = max(1, round(self.img.width() * s * dpr))
        h = max(1, round(self.img.height() * s * dpr))
        key = (self.img.cacheKey(), w, h)
        if key != self._scaled_key:
            self._scaled = self.img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._scaled.setDevicePixelRatio(dpr)
            self._scaled_key = key
        return self._scaled

    # -- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        if self.dark:
            p.fillRect(r, QColor("#000000"))
        else:
            g = QLinearGradient(0, 0, 0, r.height())
            g.setColorAt(0, QColor("#FDFEFF"))
            g.setColorAt(1, QColor("#E3EBF5"))
            p.fillRect(r, g)
        if self.img.isNull():
            if self.message:
                p.setPen(QColor("#C8D4E4") if self.dark else QColor("#4A5D78"))
                f = p.font()
                f.setPointSizeF(f.pointSizeF() * 1.1)
                p.setFont(f)
                p.drawText(r.adjusted(40, 40, -40, -40), Qt.AlignCenter | Qt.TextWordWrap, self.message)
            return
        if self._old is not None and self._fade < 1.0:
            p.drawImage(self._old[1].topLeft(), self._old[0])
            p.setOpacity(self._fade)
        s = self.eff_scale()
        dpr = self.devicePixelRatioF()
        tr = self.target_rect()
        if s * dpr < 1 - 1e-6:
            p.drawImage(tr.topLeft(), self._scaled_for(s))
        else:
            vis = tr.intersected(QRectF(r))
            if vis.isEmpty():
                return
            src = QRectF((vis.x() - tr.x()) / s, (vis.y() - tr.y()) / s, vis.width() / s, vis.height() / s)
            p.setRenderHint(QPainter.SmoothPixmapTransform, s * dpr < 3)
            p.drawImage(vis, self.img, src)

    def resizeEvent(self, e):
        self._clamp()
        self._update_cursor()
        super().resizeEvent(e)
        self.zoomChanged.emit()

    # -- mouse
    def _update_cursor(self):
        if self._drag is not None:
            self.setCursor(Qt.ClosedHandCursor)
        elif self.can_pan():
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.unsetCursor()

    def wheelEvent(self, e):
        if self.img.isNull():
            return
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.zoom_by(1.25 ** steps, e.position())
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.can_pan():
            self._drag = (e.position(), QPointF(self.focus))
            self._update_cursor()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            start, focus = self._drag
            self.focus = focus - (e.position() - start) / self.eff_scale()
            self._clamp()
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._drag is not None:
            self._drag = None
            self._update_cursor()
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.doubleClicked.emit()

    def contextMenuEvent(self, e):
        self.menuRequested.emit(e.globalPos())


# ---- the bars --------------------------------------------------------------------------------
TOP_STYLE = """
QWidget#topbar { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FAFCFE, stop:0.5 #E9F0F8,
                 stop:0.51 #DCE6F3, stop:1 #D3DFEE); border-bottom: 1px solid #A0AFC3; }
QToolButton { color: #1E395B; background: transparent; border: 1px solid transparent; border-radius: 3px;
              padding: 3px 8px; }
QToolButton:hover { border-color: #A9C4E6; background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #FFFFFF, stop:0.5 #EAF3FD, stop:1 #D7E8FB); }
QToolButton:pressed, QToolButton:open { border-color: #7DA2CE; background: qlineargradient(x1:0, y1:0, x2:0,
                    y2:1, stop:0 #DBE8F7, stop:1 #C3D8F1); }
QToolButton::menu-indicator { image: none; }
"""


class TopBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("topbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(TOP_STYLE)
        self.setFixedHeight(32)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(6, 2, 6, 2)
        self.lay.setSpacing(2)

    def button(self, text: str, menu: QMenu | None = None, right: bool = False) -> QToolButton:
        b = QToolButton(self)
        b.setText(text + ("  ▾" if menu is not None else ""))
        b.setAutoRaise(True)
        b.setFocusPolicy(Qt.NoFocus)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.InstantPopup)
        if right:
            self.lay.addWidget(b)
        else:
            self.lay.insertWidget(self.lay.count() - 1 if self._has_stretch() else self.lay.count(), b)
        return b

    def _has_stretch(self) -> bool:
        return any(self.lay.itemAt(i).spacerItem() is not None for i in range(self.lay.count()))


class BottomBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(54)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 2, 8, 2)
        self.lay.setSpacing(4)
        self.lay.addStretch(1)

    def add(self, w: QWidget):
        self.lay.addWidget(w, 0, Qt.AlignVCenter)

    def separator(self):
        line = QFrame(self)
        line.setFixedSize(2, 26)
        line.setStyleSheet("border-left: 1px solid #8297B3; border-right: 1px solid #FFFFFF;")
        self.lay.addSpacing(6)
        self.lay.addWidget(line, 0, Qt.AlignVCenter)
        self.lay.addSpacing(6)

    def finish(self):
        self.lay.addStretch(1)

    def paintEvent(self, _e):
        p = QPainter(self)
        r = self.rect()
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor("#E7EEF7"))
        g.setColorAt(0.45, QColor("#D5E1EF"))
        g.setColorAt(0.46, QColor("#C9D7E9"))
        g.setColorAt(1, QColor("#BFCFE4"))
        p.fillRect(r, g)
        p.setPen(QPen(QColor("#9AAAC0")))
        p.drawLine(0, 0, r.width(), 0)
        p.setPen(QPen(QColor(255, 255, 255, 170)))
        p.drawLine(0, 1, r.width(), 1)


class ZoomPopup(QFrame):
    """The zoom slider that drops up from the magnifier button."""

    def __init__(self, canvas: Canvas, parent=None):
        super().__init__(parent, Qt.Popup)
        self.canvas = canvas
        self.setFrameShape(QFrame.Box)
        self.setStyleSheet("ZoomPopup { background: #F4F7FB; border: 1px solid #8DA2BF; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 8, 6, 8)
        self.slider = QSlider(Qt.Vertical, self)
        self.slider.setRange(0, 1000)
        self.slider.setFixedHeight(150)
        lay.addWidget(self.slider, 0, Qt.AlignHCenter)
        self.slider.valueChanged.connect(self._moved)
        self._sync = False

    def _range(self):
        lo = self.canvas.min_scale()
        return lo, max(lo * 1.01, MAX_ZOOM)

    def popup_at(self, button: QWidget):
        lo, hi = self._range()
        import math
        s = self.canvas.eff_scale()
        self._sync = True
        self.slider.setValue(int(1000 * math.log(s / lo) / math.log(hi / lo)) if s > lo else 0)
        self._sync = False
        self.adjustSize()
        pos = button.mapToGlobal(button.rect().topLeft())
        self.move(pos.x() + (button.width() - self.width()) // 2, pos.y() - self.height() - 2)
        self.show()

    def _moved(self, v):
        if self._sync:
            return
        lo, hi = self._range()
        self.canvas.set_zoom(lo * (hi / lo) ** (v / 1000.0))


# ---- dialogs ---------------------------------------------------------------------------------
def picture_details(path: Path, img: QImage) -> list[tuple[str, str]]:
    rows = [("Name", path.name), ("Folder", str(path.parent))]
    try:
        st = path.stat()
        rows.append(("Size", f"{human_size(st.st_size)} ({st.st_size:,} bytes)".replace(",", ".")))
        rows.append(("Date modified", datetime.fromtimestamp(st.st_mtime).strftime("%d-%m-%Y %H:%M")))
    except OSError:
        pass
    if not img.isNull():
        rows.append(("Dimensions", f"{img.width()} x {img.height()}"))
    try:
        from PIL import ExifTags, Image
        with Image.open(path) as im:
            rows.insert(2, ("Type", f"{im.format} picture" if im.format else path.suffix.upper()[1:]))
            mode_bits = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32, "CMYK": 32, "I;16": 16, "I": 32, "F": 32}
            if im.mode in mode_bits:
                rows.append(("Bit depth", str(mode_bits[im.mode])))
            exif = im.getexif()
            sub = exif.get_ifd(0x8769) if exif else {}
            names = {v: k for k, v in ExifTags.TAGS.items()}

            def tag(name, src=None):
                src = src if src is not None else sub
                return src.get(names.get(name, -1))
            taken = tag("DateTimeOriginal") or exif.get(306)
            if taken:
                try:
                    taken = datetime.strptime(str(taken).strip("\0"), "%Y:%m:%d %H:%M:%S").strftime(
                        "%d-%m-%Y %H:%M")
                except ValueError:
                    pass
                rows.append(("Date taken", str(taken)))
            make, model = exif.get(271), exif.get(272)
            if make or model:
                rows.append(("Camera", " ".join(str(x).strip("\0 ") for x in (make, model) if x)))
            exp = tag("ExposureTime")
            if exp:
                e = float(exp)
                rows.append(("Exposure time", f"1/{round(1 / e)} sec." if 0 < e < 1 else f"{e:g} sec."))
            fn = tag("FNumber")
            if fn:
                rows.append(("F-stop", f"f/{float(fn):.1f}"))
            iso = tag("ISOSpeedRatings") or tag("PhotographicSensitivity")
            if iso:
                rows.append(("ISO speed", f"ISO-{iso[0] if isinstance(iso, tuple) else iso}"))
            fl = tag("FocalLength")
            if fl:
                rows.append(("Focal length", f"{float(fl):g} mm"))
            flash = tag("Flash")
            if flash is not None:
                rows.append(("Flash", "Flash" if int(flash) & 1 else "No flash"))
    except Exception:   # noqa: BLE001 (no Pillow support for this type: just the basics)
        rows.insert(2, ("Type", path.suffix.upper()[1:] + " file"))
    return rows


class PropertiesDialog(QDialog):
    def __init__(self, path: Path, img: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{path.name} Properties")
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        thumb = QLabel()
        if not img.isNull():
            thumb.setPixmap(QPixmap.fromImage(img.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        top.addWidget(thumb)
        name = QLineEdit(path.name)
        name.setReadOnly(True)
        top.addWidget(name, 1)
        lay.addLayout(top)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        lay.addWidget(line)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        for k, v in picture_details(path, img)[1:]:
            lab = QLabel(v)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            form.addRow(k + ":", lab)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        lay.addWidget(bb)
        self.setMinimumWidth(380)


MAIL_SIZES = [("Smaller: 640 x 480", 640, 480), ("Small: 800 x 600", 800, 600),
              ("Medium: 1024 x 768", 1024, 768), ("Large: 1280 x 1024", 1280, 1024), ("Original Size", 0, 0)]


class AttachDialog(QDialog):
    """Windows 7's "Attach Files": pick the picture size before it goes into an e-mail."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle("Attach Files")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.combo = QComboBox()
        for text, _w, _h in MAIL_SIZES:
            self.combo.addItem(text)
        self.combo.setCurrentIndex(2)
        form.addRow("Picture size:", self.combo)
        self.total = QLabel()
        form.addRow("Total estimated size:", self.total)
        lay.addLayout(form)
        bb = QDialogButtonBox()
        bb.addButton("Attach", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.combo.currentIndexChanged.connect(self._estimate)
        self._estimate()

    def _estimate(self):
        _t, w, h = MAIL_SIZES[self.combo.currentIndex()]
        if not w:
            self.total.setText(human_size(self.path.stat().st_size) if self.path.exists() else "")
        else:
            self.total.setText(f"about {human_size(int(w * h * 0.35))}")

    def attachment(self) -> Path:
        _t, w, h = MAIL_SIZES[self.combo.currentIndex()]
        if not w:
            return self.path
        from PIL import Image, ImageOps
        out_dir = Path(tempfile.mkdtemp(prefix="photos-mail-",
                                        dir=core_cache_dir()))
        with Image.open(self.path) as im:
            im = ImageOps.exif_transpose(im)
            if max(im.size) > max(w, h) or min(im.size) > min(w, h):
                box = (w, h) if im.width >= im.height else (h, w)
                im.thumbnail(box, Image.Resampling.LANCZOS)
            keep_png = im.mode in ("RGBA", "LA", "P") and self.path.suffix.lower() in (".png", ".gif", ".webp")
            if keep_png:
                out = out_dir / (self.path.stem + ".png")
                im.save(out, "PNG", optimize=True)
            else:
                out = out_dir / (self.path.stem + ".jpg")
                im.convert("RGB").save(out, "JPEG", quality=85, optimize=True)
        return out


def core_cache_dir() -> str:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "classic7" / "photos"
    base.mkdir(parents=True, exist_ok=True)
    return str(base)


# ---- programs that can open a picture ---------------------------------------------------------
def _app_dirs() -> list[Path]:
    dirs = [Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")]
    dirs += [Path(d) for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    for extra in (Path.home() / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share")):
        if extra not in dirs:
            dirs.append(extra)
    return [d / "applications" for d in dirs]


def programs_for(mime: str) -> list[tuple[str, str, Path]]:
    """(name, icon, desktop file) of the programs that say they open this type."""
    seen, out = set(), []
    family = mime.split("/")[0] + "/*"
    for d in _app_dirs():
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.desktop")):
            did = str(f.relative_to(d)).replace("/", "-")
            if did in seen:
                continue
            seen.add(did)
            if did == "classic7-photos.desktop":
                continue
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("NoDisplay", "false") == "true" or e.get("Hidden", "false") == "true":
                continue
            mimes = [m.strip() for m in e.get("MimeType", "").split(";") if m.strip()]
            if mime in mimes or family in mimes:
                out.append((e.get("Name", f.stem), e.get("Icon", ""), f))
    return sorted(out, key=lambda t: t[0].lower())


def launch_desktop(desktop: Path, file: Path) -> bool:
    if shutil.which("gio"):
        try:
            subprocess.Popen(["gio", "launch", str(desktop), str(file)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            pass
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.read(desktop, encoding="utf-8")
    exe = cp["Desktop Entry"].get("Exec", "")
    import shlex
    args = []
    for a in shlex.split(exe):
        if a in ("%f", "%F", "%u", "%U"):
            args.append(str(file))
        elif not (len(a) == 2 and a.startswith("%")):
            args.append(a)
    try:
        subprocess.Popen(args, start_new_session=True)
        return True
    except OSError:
        return False


# ---- the slide show --------------------------------------------------------------------------
class SlideShow(QWidget):
    finished = Signal(object)          # the picture shown last

    def __init__(self, files: list[Path], index: int, loader: Loader, settings: QSettings):
        super().__init__(None, Qt.Window)
        self.setWindowTitle(f"{APP} Slide Show")
        self.files, self.index, self.loader, self.settings = files, index, loader, settings
        self.canvas = Canvas(dark=True, parent=self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)
        self.canvas.menuRequested.connect(self._menu)
        self.speed = str(settings.value("slideshow/speed", "medium"))
        if self.speed not in SLIDE_SPEEDS:
            self.speed = "medium"
        self.loop = True
        self.paused = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.step(1, fade=True))
        self.hide_mouse = QTimer(self)
        self.hide_mouse.setSingleShot(True)
        self.hide_mouse.setInterval(2000)
        self.hide_mouse.timeout.connect(lambda: self.setCursor(Qt.BlankCursor))
        self.setMouseTracking(True)
        self.canvas.setMouseTracking(True)
        self.canvas.installEventFilter(self)
        loader.done.connect(self._loaded)
        self.setStyleSheet("background: black;")

    def start(self):
        scr = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.setGeometry(scr.geometry())
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setCursor(Qt.BlankCursor)
        self._show(fade=False)

    def eventFilter(self, obj, e):
        if e.type() == e.Type.MouseMove:
            self.unsetCursor()
            self.hide_mouse.start()
        elif e.type() == e.Type.MouseButtonPress and e.button() == Qt.LeftButton:
            self.step(1)
            return True
        return False

    def _show(self, fade: bool):
        path = self.files[self.index]
        res = self.loader.get(path)
        if res is not None:
            self._display(res, fade)
        else:
            self._want_fade = fade
            self.loader.request(path)

    def _display(self, res: Loaded, fade: bool):
        if res.error:
            self.canvas.set_message(f"{res.path.name}\n\nPhoto Viewer can't open this picture because {res.error}.")
        else:
            self.canvas.set_image(res.image, fade=fade)
        self.loader.request(self.files[(self.index + 1) % len(self.files)])
        self._arm()

    def _loaded(self, res: Loaded):
        if self.isVisible() and self.files and res.path == self.files[self.index]:
            self._display(res, getattr(self, "_want_fade", False))

    def _arm(self):
        self.timer.stop()
        if not self.paused and len(self.files) > 1:
            if not self.loop and self.index == len(self.files) - 1:
                return
            self.timer.start(SLIDE_SPEEDS[self.speed])

    def step(self, delta: int, fade: bool = False):
        if not self.files:
            return
        self.index = (self.index + delta) % len(self.files)
        self._show(fade)

    def keyPressEvent(self, e):
        k = e.key()
        if k in (Qt.Key_Escape, Qt.Key_F11, Qt.Key_F5):
            self.close()
        elif k in (Qt.Key_Right, Qt.Key_PageDown, Qt.Key_Down, Qt.Key_Return, Qt.Key_Enter):
            self.step(1)
        elif k in (Qt.Key_Left, Qt.Key_PageUp, Qt.Key_Up, Qt.Key_Backspace):
            self.step(-1)
        elif k == Qt.Key_Space:
            self.paused = not self.paused
            self._arm()
        elif k == Qt.Key_Home:
            self.index = 0
            self._show(False)
        elif k == Qt.Key_End:
            self.index = len(self.files) - 1
            self._show(False)

    def _menu(self, pos):
        self.unsetCursor()
        m = QMenu(self)
        m.addAction("Play" if self.paused else "Pause", self._toggle_pause)
        m.addAction("Next", lambda: self.step(1))
        m.addAction("Back", lambda: self.step(-1))
        m.addSeparator()
        for key, label in (("slow", "Slide Show Speed - Slow"), ("medium", "Slide Show Speed - Medium"),
                           ("fast", "Slide Show Speed - Fast")):
            a = m.addAction(label, lambda k=key: self._set_speed(k))
            a.setCheckable(True)
            a.setChecked(self.speed == key)
        m.addSeparator()
        a = m.addAction("Loop", self._toggle_loop)
        a.setCheckable(True)
        a.setChecked(self.loop)
        m.addSeparator()
        m.addAction("Exit", self.close)
        m.exec(pos)

    def _toggle_pause(self):
        self.paused = not self.paused
        self._arm()

    def _toggle_loop(self):
        self.loop = not self.loop
        self._arm()

    def _set_speed(self, key):
        self.speed = key
        self.settings.setValue("slideshow/speed", key)
        self._arm()

    def closeEvent(self, e):
        self.timer.stop()
        try:
            self.loader.done.disconnect(self._loaded)
        except (RuntimeError, TypeError):
            pass
        self.finished.emit(self.files[self.index] if self.files else None)
        super().closeEvent(e)


# ---- the main window -------------------------------------------------------------------------
class PhotoViewer(QMainWindow):
    def __init__(self, path: Path | None = None):
        super().__init__()
        self.settings = QSettings("classic7", "photos")
        self.loader = Loader()
        self.loader.done.connect(self._loaded)
        self.exts = picture_extensions()
        self.files: list[Path] = []
        self.index = -1
        self.path: Path | None = None
        self.current: Loaded | None = None
        self.base = QImage()
        self.op = core.IDENTITY
        self.movie: QMovie | None = None
        self.slideshow: SlideShow | None = None
        self._told_no_save = False
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _d: self._rescan_timer.start())
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(400)
        self._rescan_timer.timeout.connect(self._rescan)

        self.setWindowIcon(QIcon(app_icon_pixmap(64)))
        self.setAcceptDrops(True)
        central = QWidget(self)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.top = TopBar(central)
        self.canvas = Canvas(parent=central)
        self.bottom = BottomBar(central)
        lay.addWidget(self.top)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.bottom)
        self.setCentralWidget(central)
        self._actions()
        self._build_top()
        self._build_bottom()
        self.canvas.zoomChanged.connect(self._update_buttons)
        self.canvas.doubleClicked.connect(self.toggle_actual)
        self.canvas.menuRequested.connect(self._context_menu)
        self.zoom_popup = ZoomPopup(self.canvas, self)

        geo = self.settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            scr = QGuiApplication.primaryScreen().availableGeometry()
            self.resize(min(1100, int(scr.width() * 0.8)), min(780, int(scr.height() * 0.85)))
        if path is not None:
            self.open_path(path)
        else:
            self._set_title()
            self.canvas.set_message("Open a picture to look at it.\n\nFile ▸ Open...  (Ctrl+O)")
            self._update_buttons()

    # -- actions and bars
    def _act(self, text, slot, keys=(), tip=""):
        a = QAction(text, self)
        a.triggered.connect(lambda _c=False: slot())
        if keys:
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.setShortcutContext(Qt.WindowShortcut)
        if tip:
            a.setToolTip(tip)
        self.addAction(a)
        return a

    def _actions(self):
        A = self._act
        self.a_open = A("Open...", self.open_dialog, ["Ctrl+O"])
        self.a_copyfile = A("Make a copy...", self.make_copy)
        self.a_rename = A("Rename", self.rename, ["F2"])
        self.a_delete = A("Delete", self.delete, ["Del"])
        self.a_props = A("Properties", self.properties, ["Alt+Return"])
        self.a_exit = A("Exit", self.close)
        self.a_print = A("Print...", self.print_picture, ["Ctrl+P"])
        self.a_mail = A("E-mail...", self.email)
        self.a_copy = A("Copy", self.copy, ["Ctrl+C"])
        self.a_next = A("Next", lambda: self.navigate(1), ["Right", "PgDown"])
        self.a_prev = A("Previous", lambda: self.navigate(-1), ["Left", "PgUp", "Backspace"])
        self.a_first = A("First picture", lambda: self.go_to(0), ["Home"])
        self.a_last = A("Last picture", lambda: self.go_to(len(self.files) - 1), ["End"])
        self.a_cw = A("Rotate clockwise", lambda: self.turn(core.ROT_CW), ["Ctrl+."])
        self.a_ccw = A("Rotate counterclockwise", lambda: self.turn(core.ROT_CCW), ["Ctrl+,"])
        self.a_fliph = A("Flip horizontally", lambda: self.turn(core.FLIP_H), ["Ctrl+Shift+H"])
        self.a_flipv = A("Flip vertically", lambda: self.turn(core.FLIP_V), ["Ctrl+Shift+V"])
        self.a_zin = A("Zoom in", lambda: self.canvas.zoom_by(1.25), ["Ctrl++", "Ctrl+=", "+"])
        self.a_zout = A("Zoom out", lambda: self.canvas.zoom_by(0.8), ["Ctrl+-", "-"])
        self.a_fit = A("Fit to window", lambda: self.canvas.set_zoom(None), ["Ctrl+0"])
        self.a_actual = A("Actual size", lambda: self.canvas.set_zoom(1.0), ["Ctrl+Alt+0", "Ctrl+1"])
        self.a_show = A("Play slide show", self.start_slideshow, ["F11", "F5"])
        self.a_wall = A("Set as desktop background", self.set_wallpaper)
        self.a_location = A("Open file location", self.open_location)
        self.a_help = A("About Photo Viewer", self.about, ["F1"])

    def _build_top(self):
        file_menu = QMenu(self)
        for a in (self.a_open, None, self.a_copyfile, None, self.a_delete, self.a_rename, None, self.a_props,
                  None, self.a_exit):
            file_menu.addSeparator() if a is None else file_menu.addAction(a)
        print_menu = QMenu(self)
        print_menu.addAction(self.a_print)
        self.open_menu = QMenu(self)
        self.open_menu.aboutToShow.connect(self._fill_open_menu)
        self.top.button("File", file_menu)
        self.top.button("Print", print_menu)
        mail = self.top.button("E-mail")
        mail.clicked.connect(self.email)
        self.top.button("Open", self.open_menu)
        self.top.lay.addStretch(1)
        help_btn = self.top.button("?", right=True)
        help_btn.setToolTip("Help")
        help_btn.clicked.connect(self.about)

    def _build_bottom(self):
        b = self.bottom
        self.b_zoom = GlyphButton("zoom", 26, b, "Change the display size (zoom)")
        self.b_zoom.clicked.connect(lambda: self.zoom_popup.popup_at(self.b_zoom))
        self.b_actual = GlyphButton("actual", 26, b, "Actual size (Ctrl+Alt+0)")
        self.b_actual.clicked.connect(self.toggle_actual)
        self.b_prev = GlyphButton("prev", 30, b, "Previous (Left Arrow)")
        self.b_prev.clicked.connect(lambda: self.navigate(-1))
        self.b_play = GlyphButton("play", 40, b, "Play slide show (F11)")
        self.b_play.clicked.connect(self.start_slideshow)
        self.b_next = GlyphButton("next", 30, b, "Next (Right Arrow)")
        self.b_next.clicked.connect(lambda: self.navigate(1))
        self.b_ccw = GlyphButton("rotccw", 28, b, "Rotate counterclockwise (Ctrl+,)")
        self.b_ccw.clicked.connect(lambda: self.turn(core.ROT_CCW))
        self.b_cw = GlyphButton("rotcw", 28, b, "Rotate clockwise (Ctrl+.)")
        self.b_cw.clicked.connect(lambda: self.turn(core.ROT_CW))
        self.b_fliph = GlyphButton("fliph", 26, b, "Flip horizontally (Ctrl+Shift+H)")
        self.b_fliph.clicked.connect(lambda: self.turn(core.FLIP_H))
        self.b_flipv = GlyphButton("flipv", 26, b, "Flip vertically (Ctrl+Shift+V)")
        self.b_flipv.clicked.connect(lambda: self.turn(core.FLIP_V))
        self.b_delete = GlyphButton("delete", 26, b, "Delete (Del)")
        self.b_delete.clicked.connect(self.delete)
        b.add(self.b_zoom)
        b.add(self.b_actual)
        b.separator()
        b.add(self.b_prev)
        b.add(self.b_play)
        b.add(self.b_next)
        b.separator()
        b.add(self.b_ccw)
        b.add(self.b_cw)
        b.add(self.b_fliph)
        b.add(self.b_flipv)
        b.separator()
        b.add(self.b_delete)
        b.finish()

    def _update_buttons(self):
        has_img = not self.canvas.img.isNull()
        has_file = self.path is not None and self.path.exists()
        many = len(self.files) > 1
        for w in (self.b_zoom,):
            w.setEnabled(has_img)
        fit = self.canvas.is_fit()
        self.b_actual.set_kind("actual" if fit else "fit")
        self.b_actual.setToolTip("Actual size (Ctrl+Alt+0)" if fit else "Fit to window (Ctrl+0)")
        self.b_actual.setEnabled(has_img and not (fit and self.canvas.fit_scale() >= 1.0))
        self.b_prev.setEnabled(many)
        self.b_next.setEnabled(many)
        self.b_play.setEnabled(bool(self.files))
        for w in (self.b_ccw, self.b_cw, self.b_fliph, self.b_flipv):
            w.setEnabled(has_img)
        self.b_delete.setEnabled(has_file)
        for a in (self.a_copyfile, self.a_rename, self.a_delete, self.a_props, self.a_print, self.a_location,
                  self.a_wall):
            a.setEnabled(has_file)
        self.a_mail.setEnabled(has_file)
        self.a_print.setEnabled(has_img)
        self.a_copy.setEnabled(has_img)

    def _set_title(self):
        self.setWindowTitle(f"{self.path.name} - {APP}" if self.path else APP)

    # -- opening and moving between pictures
    def open_path(self, path: Path):
        self.commit()
        path = Path(os.path.abspath(path))
        if path.is_dir():
            pics = core.folder_pictures(path / ".", self.exts)
            if not pics:
                self.canvas.set_message(f"There are no pictures in {path}.")
                return
            path = pics[0]
        old_dirs = self.watcher.directories()
        if old_dirs:
            self.watcher.removePaths(old_dirs)
        if path.parent.is_dir():
            self.watcher.addPath(str(path.parent))
        self.path = path
        self.files = core.folder_pictures(path, self.exts)
        self.index = self.files.index(path) if path in self.files else -1
        self.show_current()

    def _rescan(self):
        if self.path is None:
            return
        files = core.folder_pictures(self.path, self.exts) if self.path.exists() else \
            core.folder_pictures(self.path.parent / ".", self.exts)
        self.files = files
        if self.path in files:
            self.index = files.index(self.path)
        elif files:
            self.index = min(max(self.index, 0), len(files) - 1)
            self.path = files[self.index]
            self.show_current()
        else:
            self.index = -1
            self.path = None
            self._stop_movie()
            self._set_title()
            self.canvas.set_message("There are no more pictures in this folder.")
        self._update_buttons()

    def navigate(self, delta: int):
        if not self.files:
            return
        self.commit()
        if self.index < 0:
            self.index = 0
        else:
            self.index = (self.index + delta) % len(self.files)
        self.path = self.files[self.index]
        self.show_current()

    def go_to(self, i: int):
        if 0 <= i < len(self.files):
            self.commit()
            self.index = i
            self.path = self.files[i]
            self.show_current()

    def show_current(self):
        self._stop_movie()
        self.op = core.IDENTITY
        self.current = None
        self.base = QImage()
        self._set_title()
        if self.path is None:
            return
        res = self.loader.get(self.path)
        if res is not None:
            self._display(res)
        else:
            self.loader.request(self.path)
            QTimer.singleShot(150, self._maybe_loading)
        self._update_buttons()

    def _maybe_loading(self):
        if self.current is None and self.path is not None:
            self.canvas.set_message("Loading picture...")

    def _loaded(self, res: Loaded):
        if self.slideshow is not None or self.loader.closed:
            return
        if self.path is not None and res.path == self.path and self.current is None:
            self._display(res)

    def _display(self, res: Loaded):
        self.current = res
        if res.error:
            self.base = QImage()
            self.canvas.set_message(f"Photo Viewer can't open this picture because {res.error}.")
        else:
            self.base = res.image
            self.canvas.set_image(apply_op(self.base, self.op))
            if res.animated:
                self._start_movie(res.path)
        self._update_buttons()
        if len(self.files) > 1:
            self.loader.request(self.files[(self.index + 1) % len(self.files)])
            self.loader.request(self.files[(self.index - 1) % len(self.files)])

    def _start_movie(self, path: Path):
        self.movie = QMovie(str(path), parent=self)
        self.movie.setCacheMode(QMovie.CacheAll)
        self.movie.frameChanged.connect(self._frame)
        self.movie.start()

    def _frame(self, _n):
        if self.movie is not None:
            frame = _prepare(self.movie.currentImage())
            self.canvas.set_image(apply_op(frame, self.op), keep_view=True)

    def _stop_movie(self):
        if self.movie is not None:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None

    # -- turning
    def turn(self, op):
        if self.base.isNull():
            return
        self.op = core.mul(op, self.op)
        if self.movie is not None:
            self._frame(0)
            self.canvas.set_zoom(None)
        else:
            self.canvas.set_image(apply_op(self.base, self.op))
        if not self._saveable() and not self._told_no_save:
            self._told_no_save = True
            QMessageBox.information(
                self, APP, "This picture is only turned while you look at it.\n\n"
                "Photo Viewer can't save turned pictures of this type"
                + (" (animated pictures)." if self.current and self.current.animated else
                   f" (.{self.path.suffix.lower().lstrip('.')} files)."))

    def _saveable(self) -> bool:
        return (self.path is not None and self.current is not None and not self.current.animated
                and core.can_turn(self.path))

    def commit(self) -> bool:
        """Save a pending turn to the file. False if it couldn't be saved."""
        if self.op == core.IDENTITY or self.path is None or self.current is None or self.current.error:
            self.op = core.IDENTITY
            return True
        if not self._saveable():
            return True                     # turned on screen only
        op, self.op = self.op, core.IDENTITY
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            core.save_turn(self.path, op)
        except Exception as e:   # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP, f"Photo Viewer can't save the turned picture \"{self.path.name}\".\n\n{e}")
            return False
        QApplication.restoreOverrideCursor()
        self.base = apply_op(self.base, op)
        res = Loaded(self.path)
        res.image, res.fmt = self.base, self.current.fmt
        self.current = res
        self.loader.put(res)
        return True

    # -- zoom
    def toggle_actual(self):
        if self.canvas.img.isNull():
            return
        if self.canvas.is_fit() and self.canvas.fit_scale() < 1.0:
            self.canvas.set_zoom(1.0)
        else:
            self.canvas.set_zoom(None)

    # -- File menu
    def open_dialog(self):
        pats = " ".join(f"*.{e}" for e in sorted(self.exts))
        start = str(self.path.parent) if self.path else str(Path.home() / "Pictures")
        fn, _ = QFileDialog.getOpenFileName(self, "Open", start, f"All Pictures ({pats});;All Files (*)")
        if fn:
            self.open_path(Path(fn))

    def make_copy(self):
        if not self.path or not self.commit():
            return
        suggestion = self.path.with_name(f"{self.path.stem} - Copy{self.path.suffix}")
        fn, _ = QFileDialog.getSaveFileName(self, "Make a Copy", str(suggestion),
                                            f"{self.path.suffix.upper()[1:]} file (*{self.path.suffix})")
        if not fn:
            return
        try:
            shutil.copy2(self.path, fn)
        except OSError as e:
            QMessageBox.warning(self, APP, f"The copy couldn't be made.\n\n{e.strerror or e}")

    def rename(self):
        if not self.path or not self.commit():
            return
        dlg = QInputDialog(self)
        dlg.setWindowTitle("Rename")
        dlg.setLabelText("New name:")
        dlg.setTextValue(self.path.name)
        dlg.resize(380, dlg.sizeHint().height())
        edit = dlg.findChild(QLineEdit)
        if edit is not None:
            QTimer.singleShot(0, lambda: edit.setSelection(0, len(self.path.stem)))
        if dlg.exec() != QDialog.Accepted:
            return
        name = dlg.textValue().strip()
        if not name or name == self.path.name:
            return
        if "/" in name:
            QMessageBox.warning(self, APP, "A file name can't contain /.")
            return
        new = self.path.with_name(name)
        if new.exists():
            QMessageBox.warning(self, APP, f"There is already a file named \"{name}\" in this folder.")
            return
        try:
            self.path.rename(new)
        except OSError as e:
            QMessageBox.warning(self, APP, f"The file couldn't be renamed.\n\n{e.strerror or e}")
            return
        self.loader.forget(self.path)
        if self.current is not None:
            self.current.path = new
            self.current.mtime = _mtime(new)
            self.loader.put(self.current)
        self.path = new
        self.files = core.folder_pictures(new, self.exts)
        self.index = self.files.index(new) if new in self.files else 0
        self._set_title()
        self._update_buttons()

    def delete(self):
        if not self.path or not self.path.exists():
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete File")
        box.setText("Are you sure you want to move this file to the Recycle Bin?")
        info = [self.path.name]
        if not self.base.isNull():
            box.setIconPixmap(QPixmap.fromImage(apply_op(self.base, self.op).scaled(
                96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
            info.append(f"Dimensions: {self.base.width()} x {self.base.height()}")
        else:
            box.setIcon(QMessageBox.Warning)
        try:
            info.append(f"Size: {human_size(self.path.stat().st_size)}")
        except OSError:
            pass
        box.setInformativeText("\n".join(info))
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec() != QMessageBox.Yes:
            return
        self.op = core.IDENTITY
        self._stop_movie()
        gone = self.path
        ok = QFile.moveToTrash(str(gone))
        if isinstance(ok, tuple):
            ok = ok[0]
        if not ok:
            ans = QMessageBox.question(
                self, "Delete File", f"\"{gone.name}\" can't be moved to the Recycle Bin.\n\n"
                "Do you want to delete it permanently?")
            if ans != QMessageBox.Yes:
                return
            try:
                gone.unlink()
            except OSError as e:
                QMessageBox.warning(self, APP, f"The file couldn't be deleted.\n\n{e.strerror or e}")
                return
        self.loader.forget(gone)
        i = self.index
        self.files = [f for f in self.files if f != gone]
        if not self.files:
            self.path, self.index, self.current = None, -1, None
            self._set_title()
            self.canvas.set_message("There are no more pictures in this folder.")
            self._update_buttons()
            return
        self.index = i % len(self.files)
        self.path = self.files[self.index]
        self.show_current()

    def properties(self):
        if self.path:
            PropertiesDialog(self.path, apply_op(self.base, self.op), self).exec()

    # -- printing, e-mail, copying, opening with other programs
    def print_picture(self):
        img = self.canvas.img if self.movie is None else apply_op(self.base, self.op)
        if img.isNull():
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(self.path.name if self.path else APP)
        if img.width() > img.height():
            from PySide6.QtGui import QPageLayout
            printer.setPageOrientation(QPageLayout.Landscape)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("Print Pictures")
        if dlg.exec() != QDialog.Accepted:
            return
        p = QPainter(printer)
        page = QRectF(printer.pageLayout().paintRectPixels(printer.resolution()))
        page.moveTo(0, 0)
        size = QSize(img.width(), img.height()).scaled(page.size().toSize(), Qt.KeepAspectRatio)
        target = QRectF(page.x() + (page.width() - size.width()) / 2, page.y() + (page.height() - size.height()) / 2,
                        size.width(), size.height())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(target, img)
        p.end()

    def email(self):
        if not self.path or not self.commit():
            return
        dlg = AttachDialog(self.path, self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            file = dlg.attachment()
        except Exception as e:   # noqa: BLE001
            QMessageBox.warning(self, APP, f"The picture couldn't be made smaller.\n\n{e}")
            return
        mail = shutil.which("classic7-mail") or "classic7-mail"
        try:
            subprocess.Popen([mail, "--compose", "--attach", str(file)], start_new_session=True)
        except OSError as e:
            QMessageBox.warning(self, APP, f"Mail couldn't be started.\n\n{e}")

    def copy(self):
        img = self.canvas.img
        if img.isNull():
            return
        md = QMimeData()
        md.setImageData(img)
        if self.path and self.op == core.IDENTITY:
            md.setUrls([QUrl.fromLocalFile(str(self.path))])
        QApplication.clipboard().setMimeData(md)

    def _fill_open_menu(self):
        m = self.open_menu
        m.clear()
        if not self.path:
            a = m.addAction("(no picture)")
            a.setEnabled(False)
            return
        from PySide6.QtCore import QMimeDatabase
        mime = QMimeDatabase().mimeTypeForFile(str(self.path)).name()
        for name, icon, desktop in programs_for(mime):
            a = m.addAction(QIcon.fromTheme(icon) if icon and not icon.startswith("/") else QIcon(icon), name)
            a.triggered.connect(lambda _c=False, d=desktop: self._open_with(d))
        if not m.actions():
            a = m.addAction("(no other programs)")
            a.setEnabled(False)
        m.addSeparator()
        m.addAction(self.a_location)

    def _open_with(self, desktop: Path):
        if self.path and self.commit():
            launch_desktop(desktop, self.path)

    def open_location(self):
        if not self.path:
            return
        if shutil.which("dolphin"):
            subprocess.Popen(["dolphin", "--select", str(self.path)], start_new_session=True)
        else:
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path.parent)))

    def set_wallpaper(self):
        if not self.path or not self.commit():
            return
        tool = shutil.which("plasma-apply-wallpaperimage")
        if not tool:
            QMessageBox.warning(self, APP, "The desktop background can't be changed from here.")
            return
        subprocess.Popen([tool, str(self.path)], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _context_menu(self, pos):
        m = QMenu(self)
        m.addAction(self.a_show)
        m.addSeparator()
        m.addAction(self.a_wall)
        m.addSeparator()
        m.addAction(self.a_copy)
        m.addAction(self.a_delete)
        m.addSeparator()
        m.addAction(self.a_cw)
        m.addAction(self.a_ccw)
        m.addAction(self.a_fliph)
        m.addAction(self.a_flipv)
        m.addSeparator()
        m.addAction(self.a_location)
        m.addAction(self.a_props)
        m.exec(pos)

    def about(self):
        QMessageBox.about(self, f"About {APP}",
                          f"<b>{APP}</b><p>Look at the pictures in a folder one at a time, turn and flip them, "
                          "play them as a slide show, print them or send them by e-mail.</p>"
                          "<p>Left and Right arrows: previous and next picture.<br>Ctrl+. and Ctrl+, : turn."
                          "<br>Mouse wheel: zoom. F11: slide show. Del: move to the Recycle Bin.</p>"
                          "<p>Part of Classic 7.</p>")

    # -- slide show
    def start_slideshow(self):
        if not self.files or self.slideshow is not None:
            return
        self.commit()
        self._stop_movie()
        self.slideshow = SlideShow(list(self.files), max(self.index, 0), self.loader, self.settings)
        self.slideshow.finished.connect(self._slideshow_done)
        self.slideshow.start()

    def _slideshow_done(self, last):
        self.slideshow = None
        if last is not None and last in self.files:
            self.index = self.files.index(last)
            self.path = last
        self.show_current()
        self.activateWindow()

    # -- window
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.open_path(Path(url.toLocalFile()))
                break

    def closeEvent(self, e):
        self.commit()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.loader.closed = True
        self.loader.pool.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(e)


def _path_arg(arg: str) -> Path:
    if arg.startswith("file://"):
        return Path(QUrl(arg).toLocalFile())
    return Path(arg)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    QImageReader.setAllocationLimit(4096)
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName("classic7-photos")
    app.setApplicationDisplayName(APP)
    app.setDesktopFileName("classic7-photos")
    files = [a for a in argv if not a.startswith("-")]
    slideshow = "--slideshow" in argv
    win = PhotoViewer(_path_arg(files[0]) if files else None)
    win.show()
    if slideshow:
        QTimer.singleShot(200, win.start_slideshow)
    return app.exec()
