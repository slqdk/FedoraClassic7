"""Shared bits for the Windows 7 accessories (Notepad, Calculator, Character Map, Sticky Notes,
Paint, Quick Shot): the About box, icons, one-instance helpers and file dialogs."""
from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

BUILD_INFO = Path("/usr/share/classic7/build-info.json")


def icon(*names: str) -> QIcon:
    for n in names:
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return QIcon()


def build_text() -> str:
    try:
        info = json.loads(BUILD_INFO.read_text())
        return f"Version 7 (build {info.get('build', '')[:10] or 'local'})"
    except (OSError, ValueError):
        return "Version 7"


def about(parent: QWidget | None, title: str, icon_names: tuple[str, ...], extra: str = "") -> None:
    """The Windows 7 "About <program>" box: logo banner, version, a line about the program."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"About {title}")
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(0, 0, 0, 12)
    banner = QLabel("  Classic 7")
    banner.setFixedHeight(64)
    f = banner.font()
    f.setPointSizeF(f.pointSizeF() * 2.2)
    banner.setFont(f)
    banner.setStyleSheet("color: white; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0a246a,"
                         " stop:1 #3a6ea5); padding-left: 16px;")
    lay.addWidget(banner)
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    lay.addWidget(line)
    row = QHBoxLayout()
    row.setContentsMargins(16, 8, 16, 8)
    pic = QLabel()
    pic.setPixmap(icon(*icon_names).pixmap(48, 48))
    pic.setAlignment(Qt.AlignTop)
    row.addWidget(pic)
    text = QLabel(f"<b>{title}</b><br>Classic 7<br>{build_text()}<br><br>"
                  f"{extra or 'Part of Classic 7, free software.'}")
    text.setWordWrap(True)
    text.setTextFormat(Qt.RichText)
    row.addWidget(text, 1)
    lay.addLayout(row)
    ok = QPushButton("OK")
    ok.setDefault(True)
    ok.clicked.connect(dlg.accept)
    btn = QHBoxLayout()
    btn.addStretch(1)
    btn.addWidget(ok)
    btn.setContentsMargins(16, 0, 16, 0)
    lay.addLayout(btn)
    dlg.setFixedWidth(420)
    dlg.exec()


def documents_dir() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())


def pictures_dir() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home())


def config_dir() -> Path:
    """~/.config/classic7 (not created here: modules ask for it at import time, also during the
    image build where there is no home folder)."""
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "classic7"
