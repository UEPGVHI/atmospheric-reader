"""Wallpaper canvas (image or silent looping video), frosted-glass panels and the right-hand scroll rail."""
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from . import icons
from .presets import is_video_file

BLUR_DIV = 16          # the frosted look = a 1/16-size copy of the wallpaper, scaled back up (very cheap blur)


class BackgroundWidget(QWidget):
    """Paints the wallpaper (still image or looping silent video), a soft veil, and keeps a blurred copy."""
    still_ready = Signal(QImage)      # a still of a video wallpaper (used inside web pages)
    live_frame = Signal(QImage)       # every 25 fps frame, for the frame-stream fallback
    blur_changed = Signal()
    covered_changed = Signal()

    def __init__(self):
        super().__init__()
        self._src, self._src_img, self._cache = QPixmap(), QImage(), QPixmap()
        self._frame, self._blur, self._gen = QImage(), QImage(), 0
        self._latest, self._dirty, self._n = None, False, 0
        self._covered, self._has_video, self._paused = QRect(), False, False
        self.blur_serial = 0                             # bumped whenever the blurred copy changes (panel cache key)
        self.want_blur = True
        self._player = self._sink = None                 # created by _video_player() when a video wallpaper first plays
        self._tick = QTimer(self)                        # steady 25 fps whatever the video's own fps is
        self._tick.setTimerType(Qt.PreciseTimer)
        self._tick.setInterval(40)
        self._tick.timeout.connect(self._on_tick)        # only runs while a video wallpaper is actually playing
        self._blur_t = QTimer(self, singleShot=True, interval=90)
        self._blur_t.timeout.connect(self._rebuild_blur)

    def _video_player(self) -> QMediaPlayer:
        """The silent wallpaper player. Built lazily: most sessions never use a video wallpaper."""
        if self._player is None:
            self._player = QMediaPlayer(self)            # no audio output -> silent
            self._sink = QVideoSink(self)
            self._player.setVideoSink(self._sink)
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
            self._sink.videoFrameChanged.connect(self._on_frame)
        return self._player

    # ---- state used by the window / panels ----
    def blurred(self) -> QImage:
        return self._blur

    def source_image(self) -> QImage:
        """The decoded still wallpaper (null for video / none), so others needn't decode the file again."""
        return self._src_img

    def coverage(self) -> float:
        c = self._covered
        return (c.width() * c.height()) / max(1, self.width() * self.height())

    def set_covered(self, rect: QRect):
        """Area fully hidden behind the opaque web view: no need to paint video there."""
        if rect != self._covered:
            self._covered = rect
            self.update()
            self.covered_changed.emit()

    def set_paused(self, paused: bool):
        if paused != self._paused:
            self._paused = paused
            if self._has_video:
                if paused:
                    self._player.pause()
                    self._tick.stop()
                else:
                    self._player.play()
                    self._tick.start()

    def set_image(self, path: str):
        self._gen += 1
        if self._player is not None:
            self._player.stop()
            self._player.setSource(QUrl())
        self._frame, self._src, self._src_img, self._cache = QImage(), QPixmap(), QImage(), QPixmap()
        self._latest, self._dirty, self._paused = None, False, False
        self._has_video = is_video_file(path)
        self._tick.stop()
        if self._has_video:
            self._tick.start()
            player = self._video_player()
            player.setSource(QUrl.fromLocalFile(path))
            player.play()
            gen = self._gen
            QTimer.singleShot(1500, lambda: self._emit_still(gen))
        elif path and Path(path).is_file():
            self._src_img = QImage(path)
            self._src = QPixmap.fromImage(self._src_img)
        self._rebuild_blur()
        self.update()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._blur_t.start()

    # ---- internals ----
    def _rebuild_blur(self):
        if not self.want_blur or self.width() < 2:
            return
        img = self._frame if not self._frame.isNull() else self._src_img
        if img.isNull():
            self._blur = QImage()
        else:
            W, H = max(1, self.width() // BLUR_DIV), max(1, self.height() // BLUR_DIV)
            if img.width() > W * 8 and img.height() > H * 8:
                # a smooth shrink of a 1080p/4K frame down to ~1/16 touches every source pixel; shrinking to 4x the
                # target with the (nearly free) fast filter first gives the same blurred look for a fraction of the CPU
                img = img.scaled(W * 4, H * 4, Qt.KeepAspectRatioByExpanding, Qt.FastTransformation)
            s = img.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            self._blur = s.copy((s.width() - W) // 2, (s.height() - H) // 2, W, H)
        self.blur_serial += 1
        self.blur_changed.emit()

    def _emit_still(self, gen: int):
        if gen == self._gen and not self._frame.isNull():
            self.still_ready.emit(self._frame.copy())

    def _on_frame(self, frame):                          # every decoded frame: just remember it (cheap)
        self._latest, self._dirty = frame, True

    def _on_tick(self):                                  # every 40 ms: convert + paint + feed web pages
        if self._paused or not self._dirty or self._latest is None or self.window().isMinimized():
            return
        self._dirty = False
        img = self._latest.toImage()
        if img.isNull():
            return
        self._frame = img
        # repaint only what is visible: scaling 1080p video under the web view would be wasted CPU
        self.update(QRegion(self.rect()).subtracted(QRegion(self._covered)))
        self.live_frame.emit(img)
        self._n += 1
        if self.want_blur and (self._blur.isNull() or self._n % 4 == 0):   # glass blur refreshes at ~6 fps
            self._rebuild_blur()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(10, 10, 16))
        W, H = self.width(), self.height()
        if not self._frame.isNull():
            iw, ih = self._frame.width(), self._frame.height()
            k = max(W / iw, H / ih)
            dw, dh = iw * k, ih * k
            p.drawImage(QRectF((W - dw) / 2, (H - dh) / 2, dw, dh), self._frame)
            p.fillRect(self.rect(), QColor(0, 0, 0, 60))
        elif not self._src.isNull():
            if self._cache.isNull() or self._cache.size() != self.size():
                s = self._src.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self._cache = s.copy((s.width() - W) // 2, (s.height() - H) // 2, W, H)
            p.drawPixmap(0, 0, self._cache)
            p.fillRect(self.rect(), QColor(0, 0, 0, 60))   # keep in sync with the 0.24 veil in viewers.py


class GlassPanel(QFrame):
    """Frosted glass: blurred wallpaper + dark tint + soft sheen + light border. inset>0 paints only the
    frame ring (the inside is covered by an opaque child such as the web view, so it isn't painted)."""
    def __init__(self, bg: BackgroundWidget, radius=18, inset=0, dark=(12, 14, 26, 105)):
        super().__init__()
        self.setObjectName("panel")
        self.bg, self.radius, self.inset, self.dark = bg, radius, inset, dark
        self._cache, self._key = QPixmap(), None
        bg.blur_changed.connect(self.update)

    def paintEvent(self, _):
        # The glass look (blur crop + tint + sheen + border) only changes when the panel, its place over the wallpaper
        # or the blurred wallpaper changes. Hover/focus repaints of child widgets just blit the cached pixmap.
        dpr, o, bg = self.devicePixelRatioF(), self.mapTo(self.bg, QPoint(0, 0)), self.bg
        key = (self.width(), self.height(), dpr, bg.blur_serial, o.x(), o.y(), bg.width(), bg.height())
        if key != self._key:
            pm = QPixmap(max(1, round(self.width() * dpr)), max(1, round(self.height() * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            self._render(q, o)
            q.end()
            self._cache, self._key = pm, key
        QPainter(self).drawPixmap(0, 0, self._cache)

    def _render(self, p: QPainter, o: QPoint):
        p.setRenderHint(QPainter.Antialiasing)
        outer = QPainterPath()
        outer.addRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), self.radius, self.radius)
        clip = outer
        if self.inset:
            hole = QPainterPath()
            hole.addRect(QRectF(self.rect()).adjusted(self.inset, self.inset, -self.inset, -self.inset))
            clip = outer.subtracted(hole)
        p.setClipPath(clip)
        blur, bg = self.bg.blurred(), self.bg
        if not blur.isNull() and bg.width() > 0 and bg.height() > 0:
            kx, ky = blur.width() / bg.width(), blur.height() / bg.height()
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRectF(self.rect()), blur, QRectF(o.x() * kx, o.y() * ky, self.width() * kx, self.height() * ky))
        p.fillRect(self.rect(), QColor(*self.dark))
        sheen = QLinearGradient(0, 0, 0, self.height())
        sheen.setColorAt(0, QColor(255, 255, 255, 40))
        sheen.setColorAt(1, QColor(255, 255, 255, 6))
        p.fillRect(self.rect(), sheen)
        p.setClipping(False)
        p.setPen(QPen(QColor(255, 255, 255, 72), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(outer)


class _Track(QWidget):
    """Vertical slider track: draggable, glass-styled."""
    moved = Signal(float)

    def __init__(self):
        super().__init__()
        self._f, self._drag = 0.0, False
        self.setMinimumHeight(70)
        self.setCursor(Qt.PointingHandCursor)

    def set_fraction(self, f: float):
        if not self._drag:
            self._f = max(0.0, min(1.0, f))
            self.update()

    def _set(self, y: float):
        top, bot = 12.0, self.height() - 12.0
        self._f = max(0.0, min(1.0, (y - top) / max(1.0, bot - top)))
        self.update()
        self.moved.emit(self._f)

    def mousePressEvent(self, e):
        self._drag = True
        self._set(e.position().y())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set(e.position().y())

    def mouseReleaseEvent(self, e):
        self._drag = False

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, top, bot = self.width() / 2, 12.0, self.height() - 12.0
        y = top + self._f * (bot - top)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 55))
        p.drawRoundedRect(QRectF(cx - 2, top, 4, bot - top), 2, 2)
        p.setBrush(QColor(138, 180, 255, 210))
        p.drawRoundedRect(QRectF(cx - 2, top, 4, max(0.0, y - top)), 2, 2)
        p.setPen(QPen(QColor(255, 255, 255, 140), 1))
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawEllipse(QPointF(cx, y), 8, 8)


class ScrollRail(GlassPanel):
    """Right-hand glass rail that scrolls whatever is open: top / page up / drag track / page down / bottom / auto."""
    def __init__(self, bg: BackgroundWidget):
        super().__init__(bg, radius=20)
        self.setFixedWidth(50)
        self.track = _Track()
        self.btn_top, self.btn_up = self._btn("to_top", "Top"), self._btn("chevron_up", "Page up")
        self.btn_down, self.btn_bottom = self._btn("chevron_down", "Page down"), self._btn("to_bottom", "Bottom")
        self.btn_auto = self._btn("play", "Auto-scroll (speed in the sidebar)")
        self.btn_auto.setCheckable(True)
        self.pct = QLabel("0%", alignment=Qt.AlignCenter)
        self.pct.setObjectName("muted")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(7, 10, 7, 10)
        lay.setSpacing(6)
        for w in (self.btn_top, self.btn_up):
            lay.addWidget(w)
        lay.addWidget(self.track, 1)
        for w in (self.btn_down, self.btn_bottom, self.pct, self.btn_auto):
            lay.addWidget(w)

    @staticmethod
    def _btn(icon_name: str, tip: str) -> QPushButton:
        b = QPushButton()
        b.setIcon(icons.icon(icon_name))
        b.setIconSize(QSize(18, 18))
        b.setObjectName("icon")
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def set_fraction(self, f: float):
        self.track.set_fraction(f)
        self.pct.setText(f"{round(max(0.0, min(1.0, f)) * 100)}%")
