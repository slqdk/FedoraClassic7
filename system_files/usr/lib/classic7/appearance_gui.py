"""Classic 7 Personalization (PySide6): the theme (Aero, Basic or Classic), the Aero window
colour, the Classic colour scheme and font size, and the Explorer layout."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
    QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSlider, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

import classic7aero as aero
import classic7appearance as backend
import classic7theme as t

PREVIEW_W, PREVIEW_H = 420, 250       # Appearance tab: the Classic sample windows
SCENE_W, SCENE_H = 460, 260           # Window Color tab: a desktop at real size
THUMB_W, THUMB_H = 184, 115           # Theme tab pictures ...
THUMB_SCENE_W, THUMB_SCENE_H = 480, 300   # ... drawn at this size, then made smaller
LOOK_NAMES = {"aero": "Aero", "basic": "Basic", "classic": "Classic"}
LOOK_TEXT = {
    "aero": "Glass windows in the colour you choose, the round Start button and task buttons with icons",
    "basic": "Light blue windows without glass, for slower graphics",
    "classic": "Grey 3D windows, the Start button and Quick Launch, in a colour scheme you choose",
}
HEAD = "#1E3987"                      # headings, as in Control Panel
BLUE = "#1F4E9C"                      # links
PAGES = ("theme", "color", "appearance", "explorer")


# =============================================================================
# Pictures
# =============================================================================
def render_svg(painter: QPainter, svg: str, rect: QRectF):
    QSvgRenderer(QByteArray(svg.encode())).render(painter, rect)


def svg_pixmap(svg: str, w: int, h: int, ratio: float) -> QPixmap:
    pm = QPixmap(int(w * ratio), int(h * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    render_svg(painter, svg, QRectF(0, 0, w, h))
    painter.end()
    return pm


_wallpaper: QImage | None = None


def wallpaper() -> QImage:
    """The Aero wallpaper (installed, or the repository's copy when run from a checkout)."""
    global _wallpaper
    if _wallpaper is None:
        here = Path(__file__).resolve().parents[2] / "share/wallpapers/Classic7Aero"
        for base in (Path(backend.AERO_WALLPAPER), here):
            for name in ("1920x1080.jpg", "2560x1440.jpg"):
                img = QImage(str(base / "contents/images" / name))
                if not img.isNull():
                    _wallpaper = img
                    return img
        _wallpaper = QImage(16, 9, QImage.Format_RGB32)
        _wallpaper.fill(QColor(backend.AERO_DESKTOP))
    return _wallpaper


def soften(img: QImage, factor: int = 7) -> QImage:
    """A cheap blur (like KWin's behind glass): down to 1/factor and back up, smoothly."""
    small = img.scaled(max(1, img.width() // factor), max(1, img.height() // factor),
                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = small.scaled(max(1, small.width() // 2), max(1, small.height() // 2),
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(img.width(), img.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def draw_cover(painter: QPainter, img: QImage, w: float, h: float):
    """Draw img over (0, 0, w, h), cropped to fill it (like a wallpaper set to Scaled and Cropped)."""
    iw, ih = img.width(), img.height()
    scale = max(w / iw, h / ih)
    sw, sh = w / scale, h / scale
    painter.drawImage(QRectF(0, 0, w, h), img, QRectF((iw - sw) / 2, (ih - sh) / 2, sw, sh))


def look_image(look: str, glass: aero.Glass, palette: t.Palette, w: int, h: int, ratio: float = 1.0) -> QImage:
    """A small desktop in a look: two windows and the taskbar (over the wallpaper for Aero and
    Basic, with the glass softening what is behind it as KWin's blur does)."""
    img = QImage(int(w * ratio), int(h * ratio), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(ratio)
    img.fill(Qt.transparent)
    painter = QPainter(img)
    painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
    if look == "classic":
        render_svg(painter, t.classic_scene_svg(palette, w, h), QRectF(0, 0, w, h))
        painter.end()
        return img
    draw_cover(painter, wallpaper(), w, h)
    painter.end()
    for svg, glass_areas in aero.scene(look, glass, w, h):
        behind = soften(img) if glass_areas else None
        painter = QPainter(img)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        if behind is not None:
            path = QPainterPath()
            path.setFillRule(Qt.OddEvenFill)
            for ring in glass_areas:
                for poly in ring:
                    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))
                    path.closeSubpath()
            painter.save()
            painter.setClipPath(path)
            painter.drawImage(QRectF(0, 0, w, h), behind)
            painter.restore()
        render_svg(painter, svg, QRectF(0, 0, w, h))
        painter.end()
    return img


def thumbnail(look: str, glass: aero.Glass, palette: t.Palette, ratio: float) -> QPixmap:
    img = look_image(look, glass, palette, THUMB_SCENE_W, THUMB_SCENE_H, 1.0)
    img = img.scaled(int(THUMB_W * ratio), int(THUMB_H * ratio), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    img.setDevicePixelRatio(ratio)
    pm = QPixmap.fromImage(img)
    painter = QPainter(pm)
    painter.setPen(QPen(QColor("#7A8A99"), 1))
    painter.drawRect(QRectF(0.5, 0.5, THUMB_W - 1, THUMB_H - 1))
    painter.end()
    return pm


def glass_swatch(color: str, size: int = 34, ratio: float = 1.0) -> QIcon:
    """A glossy colour tile, as in the Window Color page."""
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(0.5, 0.5, size - 1, size - 1)
    p.setPen(QPen(QColor("#4D4D4D"), 1))
    p.setBrush(QColor(color))
    p.drawRoundedRect(r, 4, 4)
    gloss = QLinearGradient(0, 0, 0, size)
    gloss.setColorAt(0, QColor(255, 255, 255, 170))
    gloss.setColorAt(0.48, QColor(255, 255, 255, 60))
    gloss.setColorAt(0.5, QColor(255, 255, 255, 0))
    gloss.setColorAt(1, QColor(255, 255, 255, 30))
    p.setPen(QPen(QColor(255, 255, 255, 150), 1))
    p.setBrush(gloss)
    p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3, 3)
    p.end()
    return QIcon(pm)


def swatch(color: str, w: int = 34, h: int = 14) -> QIcon:
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    painter = QPainter(pm)
    painter.setPen(QColor("#000000"))
    painter.drawRect(0, 0, w - 1, h - 1)
    painter.end()
    return QIcon(pm)


def heading(text: str) -> QLabel:
    lab = QLabel(text)
    f = lab.font()
    f.setPointSizeF(f.pointSizeF() * 1.3)
    lab.setFont(f)
    lab.setStyleSheet(f"color: {HEAD};")
    lab.setWordWrap(True)
    return lab


def section(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(f"color: {HEAD};")
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    return lab


def link(text: str, slot) -> QToolButton:
    b = QToolButton()
    b.setText(text)
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(f"QToolButton {{ color: {BLUE}; border: none; padding: 1px; }}"
                    "QToolButton:hover { text-decoration: underline; }")
    b.clicked.connect(slot)
    return b


def launch(cmd: list[str]):
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


class ColorButton(QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIconSize(QSize(34, 14))
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.setMinimumWidth(48)
        self._color = "#000000"

    def set_color(self, color: str | None):
        self.setEnabled(color is not None)
        if color:
            self._color = color
            self.setIcon(swatch(color))
        else:
            self.setIcon(swatch("#D4D0C8"))

    def color(self) -> str:
        return self._color


class Preview(QLabel):
    def __init__(self, w: int = PREVIEW_W, h: int = PREVIEW_H, parent=None):
        super().__init__(parent)
        self.w, self.h = w, h
        self.setFixedSize(w + 4, h + 4)
        self.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.setLineWidth(2)

    def show_palette(self, p: t.Palette):
        self.setPixmap(svg_pixmap(t.appearance_preview_svg(p, self.w, self.h), self.w, self.h,
                                  self.devicePixelRatioF()))

    def show_look(self, look: str, glass: aero.Glass, p: t.Palette):
        self.setPixmap(QPixmap.fromImage(look_image(look, glass, p, self.w, self.h, self.devicePixelRatioF())))


# =============================================================================
# Theme
# =============================================================================
class ThemeTab(QWidget):
    """Win7's Personalization page: click a theme; Desktop Background, Window Color, Sounds and
    Screen Saver below."""
    look_chosen = Signal(str)

    def __init__(self, dialog: "PersonalizationDialog", look: str):
        super().__init__()
        self.dialog = dialog
        self.lists: dict[str, QListWidget] = {}
        self.items: dict[str, QListWidgetItem] = {}

        lay = QVBoxLayout(self)
        lay.addWidget(heading("Change the visuals on your computer"))
        sub = QLabel("Click a theme to change the window borders, taskbar, Start menu and controls all at once.")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(6)

        row = QHBoxLayout()
        for title, looks in (("Aero Theme", ("aero",)), ("Basic and Classic Themes", ("basic", "classic"))):
            col = QVBoxLayout()
            col.addWidget(section(title))
            lw = QListWidget()
            lw.setViewMode(QListWidget.IconMode)
            lw.setMovement(QListWidget.Static)
            lw.setResizeMode(QListWidget.Adjust)
            lw.setWrapping(False)
            lw.setIconSize(QSize(THUMB_W, THUMB_H))
            lw.setGridSize(QSize(THUMB_W + 22, THUMB_H + 44))
            lw.setSelectionMode(QAbstractItemView.SingleSelection)
            lw.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            lw.setFrameShape(QFrame.NoFrame)
            lw.setFixedSize((THUMB_W + 22) * len(looks) + 6, THUMB_H + 50)
            lw.setWordWrap(True)
            for lk in looks:
                it = QListWidgetItem(LOOK_NAMES[lk])
                it.setData(Qt.UserRole, lk)
                it.setToolTip(LOOK_TEXT[lk])
                it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
                lw.addItem(it)
                self.items[lk] = it
                self.lists[lk] = lw
            lw.itemSelectionChanged.connect(lambda lw=lw: self._picked(lw))
            col.addWidget(lw)
            row.addLayout(col)
        row.addStretch(1)
        lay.addLayout(row)

        self.about = QLabel()
        self.about.setWordWrap(True)
        self.about.setMinimumHeight(self.fontMetrics().height() * 2 + 4)
        lay.addWidget(self.about)
        lay.addStretch(1)

        # the four links along the bottom of Windows 7's Personalization window
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        lay.addWidget(sep)
        bottom = QHBoxLayout()
        self.color_link = QToolButton()
        for b, (text, icon, slot) in zip(
                [QToolButton(), self.color_link, QToolButton(), QToolButton()],
                [("Desktop\nBackground", "preferences-desktop-wallpaper",
                  lambda: launch(["kcmshell6", "kcm_wallpaper"])),
                 ("Window Color", "preferences-desktop-color", self._window_color),
                 ("Sounds", "preferences-desktop-sound", lambda: launch(["kcmshell6", "kcm_soundtheme"])),
                 ("Screen Saver", "preferences-desktop-screensaver",
                  lambda: launch(["classic7-screensaver", "--settings"]))]):
            b.setText(text)
            b.setIcon(QIcon.fromTheme(icon))
            b.setIconSize(QSize(32, 32))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setAutoRaise(True)
            b.setMinimumWidth(110)
            b.clicked.connect(slot)
            bottom.addWidget(b)
        bottom.addStretch(1)
        lay.addLayout(bottom)
        self.select(look)

    def select(self, look: str):
        it = self.items.get(look) or self.items["aero"]
        it.listWidget().setCurrentItem(it)
        it.setSelected(True)

    def look(self) -> str:
        for lk, it in self.items.items():
            if it.isSelected():
                return lk
        return self._last if hasattr(self, "_last") else "aero"

    def _picked(self, lw: QListWidget):
        sel = lw.selectedItems()
        if not sel:
            # keep one theme chosen: clicking empty space doesn't unselect it
            if not any(it.isSelected() for it in self.items.values()):
                QTimer.singleShot(0, lambda: self.select(getattr(self, "_last", "aero")))
            return
        lk = sel[0].data(Qt.UserRole)
        for other in set(self.lists.values()):
            if other is not lw:
                other.blockSignals(True)
                other.clearSelection()
                other.blockSignals(False)
        changed = lk != getattr(self, "_last", None)
        self._last = lk
        self.about.setText(f"<b>{LOOK_NAMES[lk]}</b>: {LOOK_TEXT[lk]}.")
        if changed:
            self.look_chosen.emit(lk)

    def set_pictures(self, glass: aero.Glass, palette: t.Palette):
        ratio = self.devicePixelRatioF()
        for lk, it in self.items.items():
            it.setIcon(QIcon(thumbnail(lk, glass, palette, ratio)))

    def set_color_name(self, look: str, glass: aero.Glass, palette: t.Palette):
        name = {"aero": glass.name, "basic": "Light blue"}.get(look, palette.name)
        self.color_link.setText(f"Window Color\n{name}")

    def _window_color(self):
        self.dialog.show_page("color" if self.look() == "aero" else "appearance")

    def restore_default(self):
        self.select("aero")


# =============================================================================
# Window Color (Aero)
# =============================================================================
class ColorTab(QWidget):
    changed = Signal()

    def __init__(self, dialog: "PersonalizationDialog", glass: aero.Glass):
        super().__init__()
        self.dialog = dialog
        self.glass = replace(glass)
        self.preview = Preview(SCENE_W, SCENE_H)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._redraw)

        lay = QVBoxLayout(self)
        lay.addWidget(heading("Change the color of your window borders, Start menu, and taskbar"))
        self.note = QLabel("Window colors belong to the Aero theme. Choose <b>Aero</b> on the Theme tab to use them; "
                           "for Basic and Classic see the Appearance tab.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("background: #FFFFE1; border: 1px solid #C9C38F; padding: 4px;")
        lay.addWidget(self.note)
        lay.addWidget(self.preview, 0, Qt.AlignHCenter)

        self.controls = QWidget()
        cl = QVBoxLayout(self.controls)
        cl.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        grid.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        ratio = self.devicePixelRatioF()
        self.swatches: dict[str, QToolButton] = {}
        for i, (name, color) in enumerate(aero.GLASS_COLORS):
            b = QToolButton()
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setIcon(glass_swatch(color, 34, ratio))
            b.setIconSize(QSize(34, 34))
            b.setToolTip(name)
            b.setAccessibleName(name)
            b.setStyleSheet("QToolButton { padding: 2px; border: 1px solid transparent; border-radius: 3px; }"
                            "QToolButton:checked { border: 1px solid #3C7FB1; background: #CCE8FF; }"
                            "QToolButton:hover { border: 1px solid #7EB4EA; background: #E5F3FB; }")
            self.group.addButton(b, i)
            grid.addWidget(b, i // 8, i % 8)
            self.swatches[color.upper()] = b
        self.group.idClicked.connect(self._swatch)
        # the colours on the left; the name, transparency and intensity beside them
        row = QHBoxLayout()
        row.addLayout(grid)
        row.addSpacing(12)
        side = QVBoxLayout()
        self.current = QLabel()
        side.addWidget(self.current)
        self.transparency = QCheckBox("Enable &transparency")
        self.transparency.toggled.connect(self._transparency)
        side.addWidget(self.transparency)
        ilab = QLabel("Color &intensity:")
        self.intensity = QSlider(Qt.Horizontal)
        self.intensity.setRange(0, 100)
        self.intensity.setPageStep(10)
        ilab.setBuddy(self.intensity)
        self.intensity.valueChanged.connect(self._intensity)
        side.addWidget(ilab)
        side.addWidget(self.intensity)
        side.addStretch(1)
        row.addLayout(side, 1)
        cl.addLayout(row)

        self.mixer_button = QToolButton()
        self.mixer_button.setText("Show color &mixer")
        self.mixer_button.setCheckable(True)
        self.mixer_button.setAutoRaise(True)
        self.mixer_button.setArrowType(Qt.RightArrow)
        self.mixer_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.mixer_button.toggled.connect(self._show_mixer)
        cl.addWidget(self.mixer_button)
        self.mixer = QWidget()
        ml = QGridLayout(self.mixer)
        ml.setContentsMargins(20, 0, 0, 0)
        self.hue, self.sat, self.val = (QSlider(Qt.Horizontal) for _ in range(3))
        for r, (label, s, top) in enumerate((("&Hue:", self.hue, 359), ("&Saturation:", self.sat, 255),
                                             ("&Brightness:", self.val, 255))):
            lab = QLabel(label)
            lab.setBuddy(s)
            s.setRange(0, top)
            s.valueChanged.connect(self._mixed)
            ml.addWidget(lab, r, 0)
            ml.addWidget(s, r, 1)
        self.mixer.setVisible(False)
        cl.addWidget(self.mixer)
        lay.addWidget(self.controls)
        lay.addWidget(link("Advanced appearance settings…", lambda: self.dialog.show_page("appearance")),
                      0, Qt.AlignLeft)
        lay.addStretch(1)
        self._load(self.glass)

    # --- state -----------------------------------------------------------------------
    def _load(self, g: aero.Glass):
        self.glass = replace(g)
        b = self.swatches.get(g.color.upper())
        if b is not None:
            b.setChecked(True)
        else:
            self._uncheck_swatches()
        for w in (self.transparency, self.intensity):
            w.blockSignals(True)
        self.transparency.setChecked(g.transparency)
        self.intensity.setValue(round(g.intensity * 100))
        for w in (self.transparency, self.intensity):
            w.blockSignals(False)
        self._set_mixer(g.color)
        self._update_label()
        self._timer.start()

    def _uncheck_swatches(self):
        self.group.setExclusive(False)
        for b in self.group.buttons():
            b.setChecked(False)
        self.group.setExclusive(True)

    def _set_mixer(self, color: str):
        h, s, v, _ = QColor(color).getHsv()
        for sl, val in ((self.hue, max(h, 0)), (self.sat, s), (self.val, v)):
            sl.blockSignals(True)
            sl.setValue(val)
            sl.blockSignals(False)

    def _update_label(self):
        self.current.setText(f"Current color: {self.glass.name}")

    def _changed(self):
        self._update_label()
        self._timer.start()
        self.changed.emit()
        self.dialog.mark_dirty()

    def _swatch(self, idx: int):
        name, color = aero.GLASS_COLORS[idx]
        self.glass = replace(self.glass, name=name, color=color)
        self._set_mixer(color)
        self._changed()

    def _transparency(self, on: bool):
        self.glass = replace(self.glass, transparency=on)
        self._changed()

    def _intensity(self, value: int):
        self.glass = replace(self.glass, intensity=value / 100)
        self._changed()

    def _show_mixer(self, on: bool):
        self.mixer.setVisible(on)
        self.mixer_button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.mixer_button.setText("Hide color &mixer" if on else "Show color &mixer")

    def _mixed(self):
        color = QColor.fromHsv(self.hue.value(), self.sat.value(), self.val.value()).name().upper()
        match = next((n for n, c in aero.GLASS_COLORS if c.upper() == color), None)
        if match:
            self.swatches[color].setChecked(True)
        else:
            self._uncheck_swatches()
        self.glass = replace(self.glass, name=match or "Custom", color=color)
        self._changed()

    def _redraw(self):
        self.preview.show_look("aero", self.glass, self.dialog.palette())

    def set_enabled_for(self, look: str):
        self.note.setVisible(look != "aero")
        self.controls.setEnabled(look == "aero")

    def restore_default(self):
        self._load(aero.Glass())
        self.changed.emit()
        self.dialog.mark_dirty()


# =============================================================================
# Appearance (Classic colour scheme, font size)
# =============================================================================
class AppearanceTab(QWidget):
    changed = Signal()

    def __init__(self, dialog: "PersonalizationDialog", palette: t.Palette):
        super().__init__()
        self.dialog = dialog
        self.user_schemes = backend.load_user_schemes()
        self.palette = palette

        self.note = QLabel("The color scheme is used by the Classic theme. The font size is used by every theme.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("background: #FFFFE1; border: 1px solid #C9C38F; padding: 4px;")
        self.preview = Preview()

        self.scheme_box = QComboBox()
        self.save_btn = QPushButton("Save As…")
        self.delete_btn = QPushButton("Delete")
        self.item_box = QComboBox()
        for label, *_ in t.ITEMS:
            self.item_box.addItem(label)
        self.color1 = ColorButton()
        self.color2 = ColorButton()
        self.text_color = ColorButton()
        self.size_box = QComboBox()
        for label in t.FONT_SIZES:
            self.size_box.addItem(label)

        grid = QGridLayout()
        grid.addWidget(QLabel("Color &scheme:"), 0, 0)
        grid.itemAtPosition(0, 0).widget().setBuddy(self.scheme_box)
        row0 = QHBoxLayout()
        row0.addWidget(self.scheme_box, 1)
        row0.addWidget(self.save_btn)
        row0.addWidget(self.delete_btn)
        grid.addLayout(row0, 0, 1, 1, 7)

        grid.addWidget(QLabel("&Item:"), 1, 0)
        grid.itemAtPosition(1, 0).widget().setBuddy(self.item_box)
        grid.addWidget(self.item_box, 1, 1, 1, 2)
        grid.addWidget(QLabel("Color 1:"), 1, 3)
        grid.addWidget(self.color1, 1, 4)
        grid.addWidget(QLabel("Color 2:"), 1, 5)
        grid.addWidget(self.color2, 1, 6)

        grid.addWidget(QLabel("Font si&ze:"), 2, 0)
        grid.itemAtPosition(2, 0).widget().setBuddy(self.size_box)
        grid.addWidget(self.size_box, 2, 1, 1, 2)
        grid.addWidget(QLabel("Text:"), 2, 3)
        grid.addWidget(self.text_color, 2, 4)
        grid.setColumnStretch(2, 1)

        lay = QVBoxLayout(self)
        lay.addWidget(self.note)
        lay.addWidget(self.preview, 0, Qt.AlignHCenter)
        lay.addSpacing(6)
        lay.addLayout(grid)
        lay.addStretch(1)

        self._fill_schemes()
        self._select_scheme_by_name(self.palette.name)
        self.size_box.setCurrentText(self._size_label(self.palette.font_size))
        self._update_item()
        self.preview.show_palette(self.palette)

        self.scheme_box.activated.connect(self._scheme_chosen)
        self.item_box.currentIndexChanged.connect(self._update_item)
        self.color1.clicked.connect(lambda: self._pick(1))
        self.color2.clicked.connect(lambda: self._pick(2))
        self.text_color.clicked.connect(lambda: self._pick(3))
        self.size_box.activated.connect(self._size_chosen)
        self.save_btn.clicked.connect(self._save_as)
        self.delete_btn.clicked.connect(self._delete)

    # --- schemes -------------------------------------------------------------------
    def _all_schemes(self) -> list[t.Palette]:
        return t.SCHEMES + self.user_schemes

    def _fill_schemes(self):
        self.scheme_box.clear()
        for p in t.SCHEMES:
            self.scheme_box.addItem(p.name)
        if self.user_schemes:
            self.scheme_box.insertSeparator(self.scheme_box.count())
            for p in self.user_schemes:
                self.scheme_box.addItem(p.name)

    def _select_scheme_by_name(self, name: str):
        idx = self.scheme_box.findText(name)
        if idx < 0:
            self.scheme_box.addItem(name)
            idx = self.scheme_box.count() - 1
        self.scheme_box.setCurrentIndex(idx)
        self.delete_btn.setEnabled(any(p.name == name for p in self.user_schemes))

    def _scheme_chosen(self, idx: int):
        name = self.scheme_box.itemText(idx)
        for p in self._all_schemes():
            if p.name == name:
                self._set_palette(replace(p, font_size=self.palette.font_size))
                break
        self._select_scheme_by_name(name)

    def _save_as(self):
        name, ok = QInputDialog.getText(self, "Save Scheme", "Save this color scheme as:",
                                        text=self.palette.name if self.palette.name not in
                                        [p.name for p in t.SCHEMES] else "")
        name = name.strip()
        if not ok or not name:
            return
        if name in [p.name for p in t.SCHEMES]:
            QMessageBox.warning(self, "Save Scheme", "A built-in scheme already has that name.")
            return
        self.user_schemes = [p for p in self.user_schemes if p.name != name] + [self.palette.renamed(name)]
        backend.save_user_schemes(self.user_schemes)
        self.palette = self.palette.renamed(name)
        self._fill_schemes()
        self._select_scheme_by_name(name)
        self.dialog.mark_dirty()

    def _delete(self):
        name = self.scheme_box.currentText()
        if QMessageBox.question(self, "Delete Scheme", f"Delete the color scheme “{name}”?") != QMessageBox.Yes:
            return
        self.user_schemes = [p for p in self.user_schemes if p.name != name]
        backend.save_user_schemes(self.user_schemes)
        self._fill_schemes()
        self._set_palette(replace(t.STANDARD, font_size=self.palette.font_size))
        self._select_scheme_by_name(t.STANDARD.name)

    # --- items & colours ----------------------------------------------------------
    def _update_item(self):
        _, f1, f2, ft = t.ITEMS[self.item_box.currentIndex()]
        self.color1.set_color(getattr(self.palette, f1))
        self.color2.set_color(getattr(self.palette, f2) if f2 else None)
        self.text_color.set_color(getattr(self.palette, ft) if ft else None)

    def _pick(self, which: int):
        _, f1, f2, ft = t.ITEMS[self.item_box.currentIndex()]
        field_name = {1: f1, 2: f2, 3: ft}[which]
        if not field_name:
            return
        current = QColor(getattr(self.palette, field_name))
        color = QColorDialog.getColor(current, self, "Color")
        if not color.isValid():
            return
        changes = {field_name: color.name().upper()}
        if field_name == "face":
            # new 3D face: derive the bevel shades again
            changes.update(hilight=None, light=None, shadow=None, dkshadow=None)
        self._set_palette(replace(self.palette, **changes))

    def _size_label(self, size: int) -> str:
        for label, value in t.FONT_SIZES.items():
            if value == size:
                return label
        return "Normal"

    def _size_chosen(self, _idx: int):
        self._set_palette(replace(self.palette, font_size=t.FONT_SIZES[self.size_box.currentText()]))

    def _set_palette(self, p: t.Palette):
        self.palette = p
        self._update_item()
        self.preview.show_palette(p)
        self.changed.emit()
        self.dialog.mark_dirty()

    def set_look(self, look: str):
        self.note.setVisible(look != "classic")

    def restore_default(self):
        self._set_palette(t.STANDARD)
        self._select_scheme_by_name(t.STANDARD.name)
        self.size_box.setCurrentText("Normal")


# =============================================================================
# Explorer layout, taskbar
# =============================================================================
class ExplorerTab(QWidget):
    def __init__(self, dialog: "PersonalizationDialog"):
        super().__init__()
        self.dialog = dialog
        text = QLabel(
            "<p>Set up the file manager (Dolphin) like Windows Explorer:</p>"
            "<ul>"
            "<li>The navigation pane on the left (F7 adds the folder tree)</li>"
            "<li>Back, Forward, Up and a clickable address bar</li>"
            "<li>A command bar: Cut, Copy, Paste, Move to Trash, Create Folder, View Mode, Properties</li>"
            "<li>Details view with Name, Date modified, Type and Size</li>"
            "<li>No menu bar (the menus are in the ☰ button; Ctrl+M shows the bar) and a "
            "full-width status bar</li>"
            "<li>Right-click menus like Windows: Open, Send to, Cut, Copy, Create shortcut, "
            "Delete, Rename, Properties; on the desktop: Display Configuration and "
            "Configure Desktop and Wallpaper</li>"
            "</ul>"
            "<p>New accounts already start this way. Use the button below for an account that "
            "existed before Classic 7, or to undo your own changes to Dolphin's layout. "
            "Open Dolphin windows will be closed; the desktop menu changes from the next login.</p>")
        text.setWordWrap(True)
        text.setTextFormat(Qt.RichText)
        self.button = QPushButton("Use Classic 7 &Explorer Layout and Menus")
        self.button.clicked.connect(self._apply)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay = QVBoxLayout(self)
        lay.addWidget(text)
        row = QHBoxLayout()
        row.addWidget(self.button)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.status)

        self.bar = QLabel()
        self.bar.setWordWrap(True)
        self.bar.setTextFormat(Qt.RichText)
        self.bar_button = QPushButton("Restore &Taskbar")
        self.bar_button.clicked.connect(self._taskbar)
        lay.addWidget(self.bar)
        row2 = QHBoxLayout()
        row2.addWidget(self.bar_button)
        row2.addStretch(1)
        lay.addLayout(row2)
        lay.addStretch(1)
        self.set_look(backend.State.load().look)

    def set_look(self, look: str):
        """Describe the taskbar of the look that is in use (the button rebuilds that one)."""
        if look == "classic":
            parts = "the Start button on the left, Quick Launch, task buttons, notification area and clock"
        else:
            parts = "the Start orb on the left, task buttons with icons (pinned programs too), " \
                    "notification area, clock and Show desktop"
        self.bar.setText(f"<p><b>Taskbar</b><br>Put the taskbar back the Classic 7 way: {parts}. Use it if the "
                         "Start button is in the wrong place or the taskbar got changed.</p>")

    def _taskbar(self):
        res = backend.reset_taskbar()
        self.status.setText("The taskbar was rebuilt." if res.ok else "Could not rebuild the taskbar: "
                            + "; ".join(res.notes))

    def _apply(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = backend.explorer_layout()
        finally:
            QApplication.restoreOverrideCursor()
        self.status.setText("Done. Open the file manager to see the new layout."
                            if res.ok else "Some files were missing: " + "; ".join(res.notes))


# =============================================================================
# The dialog
# =============================================================================
class ApplyWorker(QThread):
    """Applies the look off the GUI thread, so the dialog never freezes."""
    finished_with = Signal(object)

    def __init__(self, palette, look, glass, parent=None):
        super().__init__(parent)
        self.palette, self.look, self.glass = palette, look, glass

    def run(self):
        import traceback
        try:
            res = backend.apply(self.palette, look=self.look, glass=self.glass)
        except Exception as e:  # noqa: BLE001 - shown in the dialog and logged
            backend.Runner().note("ERROR\n" + traceback.format_exc())
            res = backend.Result(ok=False, notes=[f"{type(e).__name__}: {e}"], commands=[])
        self.finished_with.emit(res)


class PersonalizationDialog(QDialog):
    def __init__(self, page: str = "theme"):
        super().__init__()
        self.setWindowTitle("Personalization")
        self.setWindowIcon(QIcon.fromTheme("preferences-desktop-theme"))
        state = backend.State.load()
        self._dirty = False
        self.tabs = QTabWidget()
        self.tabs.setUsesScrollButtons(False)
        self.appearance = AppearanceTab(self, state.palette)
        self.color = ColorTab(self, state.glass)
        self.theme = ThemeTab(self, state.look)
        self.explorer = ExplorerTab(self)
        self.tabs.addTab(self.theme, "Theme")
        self.tabs.addTab(self.color, "Window Color")
        self.tabs.addTab(self.appearance, "Appearance")
        self.tabs.addTab(self.explorer, "Explorer")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
            | QDialogButtonBox.RestoreDefaults)
        self.restore = self.buttons.button(QDialogButtonBox.RestoreDefaults)
        self.restore.setText("Restore &Default")
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Apply).clicked.connect(lambda: self._apply(False))
        self.restore.clicked.connect(self._restore_default)
        # Apply is always available: applying again also brings this account up to date after
        # a system update (Start button, taskbar, lock screen).

        self.status = QLabel()
        self.status.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(self.status)
        lay.addWidget(self.buttons)

        self._pictures = QTimer(self)
        self._pictures.setSingleShot(True)
        self._pictures.setInterval(250)
        self._pictures.timeout.connect(self._refresh_pictures)
        self.theme.look_chosen.connect(self._look_chosen)
        self.color.changed.connect(self._pictures.start)
        self.appearance.changed.connect(self._pictures.start)
        self.tabs.currentChanged.connect(self._tab_changed)
        self._look_chosen(self.theme.look(), initial=True)
        self._refresh_pictures()
        self.show_page(page)
        self._dirty = False

    def palette(self) -> t.Palette:
        return self.appearance.palette

    def show_page(self, page: str):
        idx = {"theme": 0, "color": 1, "appearance": 2, "explorer": 3}.get(page, 0)
        self.tabs.setCurrentIndex(idx)
        self._tab_changed(idx)

    def _tab_changed(self, idx: int):
        self.restore.setEnabled(self.tabs.widget(idx) is not self.explorer)

    def _look_chosen(self, look: str, initial: bool = False):
        self.color.set_enabled_for(look)
        self.appearance.set_look(look)
        self.theme.set_color_name(look, self.color.glass, self.palette())
        if not initial:
            self.mark_dirty()

    def _refresh_pictures(self):
        self.theme.set_pictures(self.color.glass, self.palette())
        self.theme.set_color_name(self.theme.look(), self.color.glass, self.palette())

    def _restore_default(self):
        page = self.tabs.currentWidget()
        if page in (self.theme, self.color, self.appearance):
            page.restore_default()

    def mark_dirty(self):
        self._dirty = True
        self.status.clear()

    def _apply(self, close_after: bool = False):
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        look, glass, p = self.theme.look(), replace(self.color.glass), self.palette()
        name = LOOK_NAMES[look] + (f" ({p.name})" if look == "classic" else
                                   f" ({glass.name})" if look == "aero" else "")
        self.status.setText(f"Applying {name}…")
        self.buttons.setEnabled(False)
        self.tabs.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self._worker = ApplyWorker(p, look, glass, self)
        self._worker.finished_with.connect(lambda res: self._applied(res, name, look, close_after))
        self._worker.start()

    def _applied(self, res, name: str, look: str, close_after: bool):
        self._worker.wait(5000)        # it has emitted its result; let the thread end
        QApplication.restoreOverrideCursor()
        self.buttons.setEnabled(True)
        self.tabs.setEnabled(True)
        self._dirty = False
        self.explorer.set_look(look)
        problems = [n for n in res.notes if not n.startswith("Restart open")]
        if res.ok and not problems:
            self.status.setText(f"{name} is applied. "
                                + ("Restart open GTK apps (Firefox, Steam…) to see their new colours."
                                   if look == "classic" else
                                   "Programs that are open get the new controls when they start again."))
            if close_after:
                self.accept()
            return
        log = backend.Runner.logfile()
        self.status.setText(f"{name} was applied with problems:\n" + "\n".join(problems[:4])
                            + f"\nDetails: {log}")
        # stay open after OK so the message can be read

    def _ok(self):
        # OK always applies what is shown (also when only the scheme list was used)
        self._apply(close_after=True)

    def _busy(self) -> bool:
        return getattr(self, "_worker", None) is not None and self._worker.isRunning()

    def closeEvent(self, ev):
        if self._busy():
            ev.ignore()
            return
        super().closeEvent(ev)

    def done(self, result: int):
        # Escape and Cancel come here too: an Apply that is still running must not be cut off
        if self._busy():
            return
        super().done(result)


# the old name (scripts and tests)
AppearanceDialog = PersonalizationDialog


def main(argv=None, page: str = "theme"):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("classic7-appearance")
    app.setDesktopFileName("classic7-appearance")
    dlg = PersonalizationDialog(page if page in PAGES else "theme")
    dlg.show()
    return app.exec()
