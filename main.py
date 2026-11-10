"""Atmospheric Document & Web Reader - entry point.  Run: python main.py"""
import os
import sys
from pathlib import Path

# Optional: extra Chromium GPU flags. Off by default (they can cause flicker on some GPUs);
# to try them run:  set AR_FAST_GPU=1  before starting the app.
if os.environ.get("AR_FAST_GPU"):
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
        + " --ignore-gpu-blocklist --enable-gpu-rasterization").strip()

from PySide6.QtCore import Qt, QCoreApplication, QTimer

# Must be set before QApplication is created (needed by QtWebEngine)
QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from reader.window import MainWindow


def resource_path(name: str) -> str:
    """Works both from source and inside the PyInstaller bundle."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return str(base / name)


def main():
    if sys.platform == "win32":     # own taskbar identity, so the taskbar shows our icon
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AtmosphericReader.App")
    app = QApplication(sys.argv)
    app.setApplicationName("AtmosphericReader")   # decides the app-data folder
    app.setOrganizationName("AtmosphericReader")
    app.setWindowIcon(QIcon(resource_path("icon.ico")))
    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    QTimer.singleShot(0, win.begin)         # the window is up first; the startup atmosphere loads right after
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
