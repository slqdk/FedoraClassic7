"""Volume Mixer, as in Windows 7 (sndvol): the speakers' volume, and a volume and mute button for
each program that is playing sound.

    classic7-mixer

Works through pactl (PipeWire's PulseAudio side) and follows changes as they happen."""
from __future__ import annotations

import json
import subprocess
import sys

from PySide6.QtCore import QProcess, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea, QSlider, QToolButton,
                               QVBoxLayout, QWidget)

APP = "Volume Mixer"
COL_W = 92


def pactl_json(*args: str):
    try:
        r = subprocess.run(["pactl", "-f", "json", *args], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def pactl(*args: str):
    """Fire and forget, so dragging a slider never waits on the sound server."""
    QProcess.startDetached("pactl", list(args))


def percent(vol: dict) -> int:
    vals = []
    for ch in (vol or {}).values():
        try:
            vals.append(int(str(ch.get("value_percent", "0")).rstrip("%")))
        except (ValueError, AttributeError):
            pass
    return max(vals) if vals else 0


def volume_icon(pct: int, muted: bool) -> str:
    if muted or pct <= 0:
        return "audio-volume-muted"
    return "audio-volume-low" if pct < 34 else ("audio-volume-medium" if pct < 67 else "audio-volume-high")


class Column(QFrame):
    """One volume control: icon, name, a tall slider and the mute button."""

    def __init__(self, title: str, icon: QIcon, on_volume, on_mute, on_icon=None, tip: str = ""):
        super().__init__()
        self.on_volume = on_volume
        self.on_mute = on_mute
        self.setFixedWidth(COL_W)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 6, 4, 6)
        v.setSpacing(4)
        self.icon = QToolButton()
        self.icon.setIcon(icon)
        self.icon.setIconSize(QSize(32, 32))
        self.icon.setAutoRaise(True)
        self.icon.setToolTip(tip or title)
        if on_icon:
            self.icon.clicked.connect(on_icon)
        v.addWidget(self.icon, 0, Qt.AlignHCenter)
        self.label = QLabel(title)
        self.label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.label.setWordWrap(True)
        self.label.setFixedHeight(self.label.fontMetrics().height() * 2 + 2)
        v.addWidget(self.label)
        self.slider = QSlider(Qt.Vertical)
        self.slider.setRange(0, 100)
        self.slider.setPageStep(10)
        self.slider.setTickPosition(QSlider.TicksBothSides)
        self.slider.setTickInterval(10)
        self.slider.setMinimumHeight(170)
        self.slider.valueChanged.connect(self._moved)
        v.addWidget(self.slider, 1, Qt.AlignHCenter)
        self.mute = QToolButton()
        self.mute.setIconSize(QSize(22, 22))
        self.mute.setCheckable(True)
        self.mute.clicked.connect(lambda on: self.on_mute(on))
        v.addWidget(self.mute, 0, Qt.AlignHCenter)
        self.pending = None
        self.send = QTimer(self)
        self.send.setSingleShot(True)
        self.send.setInterval(60)
        self.send.timeout.connect(self._send)
        self.holding = False

    def set_state(self, pct: int, muted: bool):
        if not self.slider.isSliderDown() and not self.send.isActive():
            self.slider.blockSignals(True)
            self.slider.setValue(min(100, pct))
            self.slider.blockSignals(False)
        self.mute.setChecked(muted)
        self.mute.setIcon(QIcon.fromTheme(volume_icon(pct, muted)))
        self.mute.setToolTip(f"Unmute {self.label.text()}" if muted else f"Mute {self.label.text()}")
        self.slider.setToolTip(f"{pct}%")

    def _moved(self, value: int):
        self.pending = value
        self.slider.setToolTip(f"{value}%")
        if not self.send.isActive():
            self.send.start()

    def _send(self):
        if self.pending is not None:
            self.on_volume(self.pending)
            self.pending = None


class Mixer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QIcon.fromTheme("audio-volume-high"))
        self.columns: dict[str, Column] = {}
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 8, 8, 8)
        dev_box = QVBoxLayout()
        dev_box.addWidget(QLabel("Device"))
        self.device = Column("Speakers", QIcon.fromTheme("audio-speakers", QIcon.fromTheme("audio-card")),
                             lambda v: pactl("set-sink-volume", "@DEFAULT_SINK@", f"{v}%"),
                             lambda on: pactl("set-sink-mute", "@DEFAULT_SINK@", "1" if on else "0"),
                             lambda: QProcess.startDetached("kcmshell6", ["kcm_pulseaudio"]))
        dev_box.addWidget(self.device)
        h.addLayout(dev_box)
        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setFrameShadow(QFrame.Sunken)
        h.addWidget(line)
        apps_box = QVBoxLayout()
        apps_box.addWidget(QLabel("Applications"))
        self.apps_area = QScrollArea()
        self.apps_area.setWidgetResizable(True)
        self.apps_area.setFrameShape(QFrame.NoFrame)
        self.apps_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.apps_widget = QWidget()
        self.apps = QHBoxLayout(self.apps_widget)
        self.apps.setContentsMargins(0, 0, 0, 0)
        self.apps.setSpacing(6)
        self.apps.addStretch(1)
        self.apps_area.setWidget(self.apps_widget)
        apps_box.addWidget(self.apps_area, 1)
        self.none = QLabel("No other programs are playing sound.")
        self.none.setStyleSheet("color: #666;")
        apps_box.addWidget(self.none)
        h.addLayout(apps_box, 1)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(150)
        self.debounce.timeout.connect(self.refresh)
        self.watch = QProcess(self)
        self.watch.readyReadStandardOutput.connect(self._events)
        self.watch.start("pactl", ["subscribe"])
        self.refresh()
        self.resize(560, 380)

    def _events(self):
        data = bytes(self.watch.readAllStandardOutput()).decode(errors="ignore")
        if "sink" in data or "server" in data or "client" in data:
            self.debounce.start()

    def refresh(self):
        default = ""
        try:
            default = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True,
                                     timeout=5).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
        sinks = pactl_json("list", "sinks") or []
        sink = next((s for s in sinks if s.get("name") == default), sinks[0] if sinks else None)
        if sink:
            desc = sink.get("description") or sink.get("name", "Speakers")
            short = desc.split(" (")[0] if len(desc) > 24 else desc
            self.device.label.setText(short)
            self.device.icon.setToolTip(desc)
            self.device.set_state(percent(sink.get("volume")), bool(sink.get("mute")))
            self.device.setEnabled(True)
            self.setWindowTitle(f"{APP} - {desc}")
        else:
            self.device.setEnabled(False)
            self.setWindowTitle(APP)
        streams = pactl_json("list", "sink-inputs") or []
        groups: dict[str, list[dict]] = {}
        for s in streams:
            props = s.get("properties", {})
            if props.get("media.role") == "event" or props.get("application.id") == "org.kde.kmix":
                key = "System Sounds"
            else:
                key = (props.get("application.name") or props.get("application.process.binary")
                       or props.get("media.name") or f"Stream {s.get('index')}")
            groups.setdefault(key, []).append(s)
        for key in list(self.columns):
            if key not in groups:
                col = self.columns.pop(key)
                self.apps.removeWidget(col)
                col.deleteLater()
        for key, items in sorted(groups.items(), key=lambda kv: (kv[0] != "System Sounds", kv[0].lower())):
            idx = [str(s.get("index")) for s in items]
            col = self.columns.get(key)
            if col is None:
                props = items[0].get("properties", {})
                icon_name = "preferences-desktop-sound" if key == "System Sounds" else (
                    props.get("application.icon_name") or props.get("application.process.binary") or "")
                icon = QIcon.fromTheme(icon_name, QIcon.fromTheme("applications-multimedia"))
                col = Column(key, icon, lambda v, k=key: self._set_volume(k, v), lambda on, k=key: self._set_mute(k, on),
                             tip=props.get("media.name", key))
                self.columns[key] = col
                self.apps.insertWidget(self.apps.count() - 1, col)
            col.ids = idx
            col.set_state(max(percent(s.get("volume")) for s in items), all(bool(s.get("mute")) for s in items))
        self.none.setVisible(not groups)

    def _set_volume(self, key: str, v: int):
        for i in getattr(self.columns.get(key), "ids", []):
            pactl("set-sink-input-volume", i, f"{v}%")

    def _set_mute(self, key: str, on: bool):
        for i in getattr(self.columns.get(key), "ids", []):
            pactl("set-sink-input-mute", i, "1" if on else "0")

    def closeEvent(self, e):
        self.watch.kill()
        self.watch.waitForFinished(1000)
        super().closeEvent(e)


def main(argv=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("classic7-mixer")
    app.setDesktopFileName("classic7-mixer")
    w = Mixer()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
