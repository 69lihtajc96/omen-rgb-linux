#!/usr/bin/env python3
"""
HP OMEN 17 RGB Controller for Linux
Modes: Static, Rainbow
Features:
 - Smooth static transitions (fast)
 - Rainbow mode (very fast)
 - Single-instance system tray
 - Persist last mode via QSettings
 - High-DPI scaling
"""
import os
import sys
import time
import subprocess
from pathlib import Path
from threading import Event
from PyQt5.QtCore import Qt, QThread, QSettings, QCoreApplication, pyqtSlot
from PyQt5.QtGui import QColor, QIcon
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem,
    QGroupBox, QPushButton, QColorDialog, QSystemTrayIcon, QMenu, QAction
)

# ---------- CONFIGURATION ---------- #
APP_NAME = "hp-omen-rgb"
ORG_NAME = "OmenTools"
ZONE_PATH = Path("/sys/devices/platform/hp-wmi/rgb_zones/zone00")
STATIC_DURATION_MS = 100  # fast static transition
RAIN_DELAY_MS = 10       # very fast rainbow tick delay
PRESETS = {
    "Red": "ff0000", "Green": "00ff00", "Blue": "0000ff",
    "Purple": "800080", "White": "ffffff", "Orange": "ff7f00",
}

# ---------- UTILITIES ---------- #

def hex_to_rgb(h):
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(c):
    return f"{c[0]:02x}{c[1]:02x}{c[2]:02x}"

_last_color = None

def sudo_write(col_hex):
    subprocess.run(["sudo", "tee", str(ZONE_PATH)], input=col_hex.encode(),
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# Smooth transition over STATIC_DURATION_MS
def set_color(col_hex, duration_ms=None):
    global _last_color
    if duration_ms and _last_color and _last_color.lower() != col_hex.lower():
        r0, g0, b0 = hex_to_rgb(_last_color)
        r1, g1, b1 = hex_to_rgb(col_hex)
        steps = 20
        delay = duration_ms / steps / 1000.0
        for i in range(1, steps + 1):
            t = i / steps
            ir = int(r0 + (r1 - r0) * t)
            ig = int(g0 + (g1 - g0) * t)
            ib = int(b0 + (b1 - b0) * t)
            sudo_write(rgb_to_hex((ir, ig, ib)))
            time.sleep(delay)
    else:
        sudo_write(col_hex)
    _last_color = col_hex

# ---------- THREADS ---------- #
class RainbowThread(QThread):
    def __init__(self, delay_ms):
        super().__init__()
        self.delay_s = delay_ms / 1000.0
        self.hue = 0
        self.stop_event = Event()

    def run(self):
        while not self.stop_event.is_set():
            col = QColor.fromHsv(self.hue % 360, 255, 255).name()[1:]
            sudo_write(col)
            self.hue += 1
            self.stop_event.wait(self.delay_s)

    def stop(self):
        self.stop_event.set()
        self.wait()

# ---------- GUI ---------- #
class RGBController(QWidget):
    def __init__(self):
        super().__init__()
        self.rain_thread = None
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.init_tray()
        self.init_ui()
        self.load_settings()

    def init_tray(self):
        icon = QIcon.fromTheme("keyboard")
        self.tray = QSystemTrayIcon(icon, self)
        menu = QMenu()
        menu.addAction(QAction("Show", self, triggered=self.show))
        menu.addAction(QAction("Exit", self, triggered=self.exit_app))
        self.tray.setContextMenu(menu)
        self.tray.show()

    def init_ui(self):
        self.setWindowTitle("HP OMEN RGB Controller")
        layout = QVBoxLayout(self)
        # Mode selector
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for m in ["Static Color", "Rainbow Mode"]:
            QTreeWidgetItem(self.tree, [m])
        self.tree.itemClicked.connect(self.on_mode)
        layout.addWidget(self.tree)
        # Options box
        self.options_box = QGroupBox("Options")
        self.options_layout = QVBoxLayout(self.options_box)
        layout.addWidget(self.options_box)
        self.show()

    def clear_opts(self):
        while self.options_layout.count():
            w = self.options_layout.takeAt(0).widget()
            if w:
                w.deleteLater()

    def on_mode(self, item, _):
        self.stop_rainbow()
        self.clear_opts()
        mode = item.text(0)
        self.settings.setValue("lastMode", mode)
        if mode == "Static Color":
            for name, hexc in PRESETS.items():
                btn = QPushButton(name)
                btn.clicked.connect(lambda _, c=hexc: set_color(c, STATIC_DURATION_MS))
                self.options_layout.addWidget(btn)
            cust = QPushButton("Choose Custom Color")
            cust.clicked.connect(self.pick_color)
            self.options_layout.addWidget(cust)
        else:  # Rainbow Mode
            # Auto-start very fast rainbow
            self.start_rainbow(RAIN_DELAY_MS)

    @pyqtSlot()
    def pick_color(self):
        c = QColorDialog.getColor()
        if c.isValid():
            set_color(c.name()[1:], STATIC_DURATION_MS)

    def start_rainbow(self, delay_ms):
        self.stop_rainbow()
        self.rain_thread = RainbowThread(delay_ms)
        self.rain_thread.start()

    def stop_rainbow(self):
        if self.rain_thread:
            self.rain_thread.stop()
            self.rain_thread = None

    @pyqtSlot()
    def exit_app(self):
        self.stop_rainbow()
        self.tray.hide()
        QApplication.quit()

    def load_settings(self):
        m = self.settings.value("lastMode", "Static Color")
        items = self.tree.findItems(m, Qt.MatchExactly)
        if items:
            self.on_mode(items[0], 0)

    def closeEvent(self, event):
        # Proper exit under both X11 and Wayland
        event.accept()
        self.exit_app()

# ---------- ENTRY ---------- #
if __name__ == "__main__":
    if os.geteuid() == 0:
        print("[ERR] Do not run as sudo; use udev rules for access.")
        sys.exit(1)
    if os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland")
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    app = QApplication(sys.argv)
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    controller = RGBController()
    sys.exit(app.exec_())
