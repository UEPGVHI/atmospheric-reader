"""Video viewer. Imported only when the first video is opened, so QtMultimediaWidgets is not loaded at start-up."""
from pathlib import Path

from PySide6.QtCore import QSize, QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout

from . import icons


def _fmt(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


class VideoViewer(QFrame):
    """Local video file (or direct video URL) with simple transport controls."""
    playing_changed = Signal(bool)      # lets the window duck the background music
    scrolled = Signal(float)

    def __init__(self):
        super().__init__()
        self.setObjectName("video")
        self.setStyleSheet("QFrame#video { background: rgba(0,0,0,215); border-radius:14px; }")
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)

        self.play_btn = QPushButton()
        self.play_btn.setIcon(icons.icon("pause"))
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setObjectName("icon")
        self.play_btn.clicked.connect(self.toggle)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("0:00 / 0:00")
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(80)
        self.vol.setFixedWidth(90)
        self.vol.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.status = QLabel("")
        self.status.setStyleSheet("color:#ff9a9a;")

        ctl = QHBoxLayout()
        for w in (self.play_btn, self.seek, self.time, icons.label("volume"), self.vol):
            ctl.addWidget(w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(self.video, 1)
        lay.addWidget(self.status)
        lay.addLayout(ctl)

        self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
        self.player.positionChanged.connect(self._on_pos)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.errorOccurred.connect(lambda _e, msg: self.status.setText(f"Cannot play this video: {msg}"))

    def _on_pos(self, pos: int):
        if not self.seek.isSliderDown():
            self.seek.setValue(pos)
        self.time.setText(f"{_fmt(pos)} / {_fmt(self.player.duration())}")

    def _on_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setIcon(icons.icon("pause" if playing else "play"))
        self.playing_changed.emit(playing)

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop(self):
        self.player.stop()

    def load_source(self, src: str):
        self.status.clear()
        self.player.setSource(QUrl.fromLocalFile(src) if Path(src).is_file() else QUrl(src))
        self.player.play()

    def set_alpha(self, a: float):
        pass

    def zoom(self, step: int):
        pass

    def scroll_frac(self): return 0.0
    def set_scroll_frac(self, f): pass
    def scroll_px(self, dy): pass
    def scroll_pages(self, n): pass
    def restore(self, f): pass
