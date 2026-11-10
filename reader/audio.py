"""Background-music manager: looping playback, volume, cross-fades, ducking."""
from pathlib import Path
from PySide6.QtCore import QObject, QUrl, QVariantAnimation
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class AudioManager(QObject):
    DUCK = 0.15      # music level (x volume) while a video is playing

    def __init__(self, volume=0.5, parent=None):
        super().__init__(parent)
        self.volume, self._duck = volume, False
        self.output = QAudioOutput()
        self.output.setVolume(volume)
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.output)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)   # loop forever
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(lambda v: self.output.setVolume(float(v)))
        self._anim.finished.connect(self._fade_done)
        self._after = None

    def _target(self) -> float:
        return self.volume * (self.DUCK if self._duck else 1.0)

    def _fade(self, end: float, ms: int, after=None):
        self._anim.stop()
        self._after = after
        self._anim.setStartValue(float(self.output.volume()))
        self._anim.setEndValue(float(end))
        self._anim.setDuration(ms)
        self._anim.start()

    def _fade_done(self):
        cb, self._after = self._after, None
        if cb:
            cb()

    def play(self, path: str):
        """Switch track with a short fade-out/fade-in. Empty path = silence."""
        valid = bool(path) and Path(path).is_file()

        def start():
            if not valid:
                self.player.stop()
                return
            self.player.setSource(QUrl.fromLocalFile(path))
            self.player.play()
            self._fade(self._target(), 900)

        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._fade(0.0, 500, start)
        else:
            self.output.setVolume(0.0)
            start()

    def set_volume(self, v: float):
        self.volume = v
        self._anim.stop()
        self.output.setVolume(self._target())

    def duck(self, on: bool):
        """Lower the music while a video plays, restore it afterwards."""
        self._duck = bool(on)
        self._fade(self._target(), 400)

    def toggle(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.player.source().isValid():
            self.player.play()
