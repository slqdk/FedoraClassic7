#!/usr/bin/env python3
"""
Generate Dolphin's saved window layout (QMainWindow state) for the Classic 7 Explorer look:
  - left: Places on top, Folders tree below (like the Windows 7 navigation pane)
  - Information, Terminal panels hidden
  - toolbars: mainToolBar (Back/Forward/Up + address bar), then commandBar on its own row

Qt restores dock and toolbar layout by objectName, so a stand-in window using Dolphin's
names produces a state Dolphin accepts. Writes etc/skel/.local/state/dolphinstaterc.

    pip install PySide6-Essentials
    QT_QPA_PLATFORM=offscreen python3 tools/make_dolphin_state.py
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QMainWindow, QToolBar

OUT = Path(__file__).resolve().parent.parent / "system_files/etc/skel/.local/state/dolphinstaterc"

app = QApplication([])
win = QMainWindow()
win.setCentralWidget(QLabel("view"))
win.resize(960, 640)

main_tb = QToolBar("Main Toolbar")
main_tb.setObjectName("mainToolBar")
win.addToolBar(Qt.TopToolBarArea, main_tb)
win.addToolBarBreak(Qt.TopToolBarArea)
cmd_tb = QToolBar("Command Bar")
cmd_tb.setObjectName("commandBar")
win.addToolBar(Qt.TopToolBarArea, cmd_tb)
for tb in (main_tb, cmd_tb):
    tb.addAction("x")


def dock(name: str, area) -> QDockWidget:
    d = QDockWidget(name)
    d.setObjectName(name)
    d.setWidget(QLabel(name))
    win.addDockWidget(area, d)
    return d


places = dock("placesDock", Qt.LeftDockWidgetArea)
folders = dock("foldersDock", Qt.LeftDockWidgetArea)
win.splitDockWidget(places, folders, Qt.Vertical)
info = dock("infoDock", Qt.RightDockWidgetArea)
terminal = dock("terminalDock", Qt.BottomDockWidgetArea)

win.show()
app.processEvents()
win.resizeDocks([places], [230], Qt.Horizontal)
win.resizeDocks([places, folders], [230, 330], Qt.Vertical)
info.hide()
terminal.hide()
app.processEvents()

state = bytes(win.saveState().toBase64()).decode()
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(f"[MainWindow]\nState={state}\n")
print("wrote", OUT, f"({len(state)} chars)")
