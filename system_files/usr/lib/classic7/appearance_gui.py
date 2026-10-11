"""Classic 7 Appearance dialog (PySide6)."""
from __future__ import annotations

import sys
from dataclasses import replace

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
    QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

import classic7appearance as backend
import classic7theme as t

PREVIEW_W, PREVIEW_H = 420, 250


def swatch(color: str, w: int = 34, h: int = 14) -> QIcon:
    pm = QPixmap(w, h)
    pm.fill(QColor(color))
    painter = QPainter(pm)
    painter.setPen(QColor("#000000"))
    painter.drawRect(0, 0, w - 1, h - 1)
    painter.end()
    return QIcon(pm)


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PREVIEW_W + 4, PREVIEW_H + 4)
        self.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.setLineWidth(2)

    def show_palette(self, p: t.Palette):
        svg = t.appearance_preview_svg(p, PREVIEW_W, PREVIEW_H)
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        ratio = self.devicePixelRatioF()
        pm = QPixmap(int(PREVIEW_W * ratio), int(PREVIEW_H * ratio))
        pm.setDevicePixelRatio(ratio)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        renderer.render(painter, QRectF(0, 0, PREVIEW_W, PREVIEW_H))
        painter.end()
        self.setPixmap(pm)


class AppearanceTab(QWidget):
    def __init__(self, dialog: "AppearanceDialog"):
        super().__init__()
        self.dialog = dialog
        self.user_schemes = backend.load_user_schemes()
        state = backend.State.load()
        self.palette = state.palette

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
        self.dialog.mark_dirty()

    def restore_default(self):
        self._set_palette(t.STANDARD)
        self._select_scheme_by_name(t.STANDARD.name)
        self.size_box.setCurrentText("Normal")


class ExplorerTab(QWidget):
    def __init__(self, dialog: "AppearanceDialog"):
        super().__init__()
        self.dialog = dialog
        text = QLabel(
            "<p>Set up the file manager (Dolphin) like Windows Explorer:</p>"
            "<ul>"
            "<li>Places and a folder tree on the left</li>"
            "<li>Back, Forward, Up and a clickable address bar</li>"
            "<li>A command bar: Cut, Copy, Paste, Move to Trash, Create Folder, View Mode, Properties</li>"
            "<li>Details view with Name, Date modified, Type and Size</li>"
            "<li>Menu bar and a full-width status bar</li>"
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
        lay.addStretch(1)

    def _apply(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = backend.explorer_layout()
        finally:
            QApplication.restoreOverrideCursor()
        self.status.setText("Done. Open the file manager to see the new layout."
                            if res.ok else "Some files were missing: " + "; ".join(res.notes))


class AppearanceDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Appearance")
        self.setWindowIcon(QIcon.fromTheme("preferences-desktop-theme"))
        self.tabs = QTabWidget()
        self.appearance = AppearanceTab(self)
        self.explorer = ExplorerTab(self)
        self.tabs.addTab(self.appearance, "Appearance")
        self.tabs.addTab(self.explorer, "Explorer")

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply
            | QDialogButtonBox.RestoreDefaults)
        self.buttons.button(QDialogButtonBox.RestoreDefaults).setText("Restore &Default")
        self.buttons.accepted.connect(self._ok)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        self.buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self.appearance.restore_default)
        self.buttons.button(QDialogButtonBox.Apply).setEnabled(False)

        self.status = QLabel()
        self.status.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(self.status)
        lay.addWidget(self.buttons)

    def mark_dirty(self):
        self.buttons.button(QDialogButtonBox.Apply).setEnabled(True)
        self.status.clear()

    def _apply(self) -> bool:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = backend.apply(self.appearance.palette)
        finally:
            QApplication.restoreOverrideCursor()
        self.buttons.button(QDialogButtonBox.Apply).setEnabled(False)
        self.status.setText(" ".join(res.notes))
        return res.ok

    def _ok(self):
        if self.buttons.button(QDialogButtonBox.Apply).isEnabled():
            self._apply()
        self.accept()


def main(argv=None):
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("classic7-appearance")
    app.setDesktopFileName("classic7-appearance")
    dlg = AppearanceDialog()
    dlg.show()
    return app.exec()
