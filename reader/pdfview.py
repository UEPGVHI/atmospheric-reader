"""PDF viewer. Imported only when the first PDF is opened, so QtPdf is not loaded at start-up.

Why this is not a plain QPdfView any more: QPdfView paints an opaque fill over its whole viewport
(and white page sheets on top of it), so the window's wallpaper - image or video - could never show
through a PDF. This viewer draws the pages itself onto a transparent viewport: the wallpaper stays
visible around and *through* the pages, the same way it does for text and web pages.
"""
from collections import OrderedDict
from bisect import bisect_right

from PySide6.QtCore import QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QAbstractScrollArea, QFrame

from .viewers import _bar_frac, _bar_pages, _bar_px, _bar_set

MARGIN, GAP, RADIUS = 18, 14, 14
CACHE_MAX = 14


class PdfViewer(QAbstractScrollArea):
    scrolled = Signal(float)

    def __init__(self):
        super().__init__()
        self.doc = QPdfDocument(self)
        self.setFrameShape(QFrame.NoFrame)
        self.viewport().setAutoFillBackground(False)            # let the wallpaper behind us show
        self.viewport().setAttribute(Qt.WA_NoSystemBackground, True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # the glass rail replaces the bar
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._a, self._z, self.invert = 0.55, 1.0, True           # veil opacity, zoom (1 = fit width), dark pages
        self._pending, self._pending_page = None, None
        self._tops, self._hs, self._pw, self._total = [], [], 0, 0
        self._cache = OrderedDict()
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(lambda _v: self.scrolled.emit(self.scroll_frac()))
        bar.rangeChanged.connect(lambda *_: self.scrolled.emit(self.scroll_frac()))
        self.doc.statusChanged.connect(self._on_status)

    # ---- look ----
    def set_alpha(self, a: float):
        self._a = a
        self.viewport().update()

    def set_invert(self, on: bool):
        self.invert = on
        self._cache.clear()
        self.viewport().update()

    def zoom(self, step: int):
        f = self.scroll_frac()
        self._z = max(0.3, min(4.0, self._z + 0.15 * step))
        self._relayout()
        self.set_scroll_frac(f)

    # ---- layout ----
    def _relayout(self):
        n = self.doc.pageCount() if self._ready() else 0
        vw, vh = self.viewport().width(), self.viewport().height()
        self._pw = max(40, round((vw - 2 * MARGIN) * self._z))
        self._tops, self._hs, y = [], [], MARGIN
        for i in range(n):
            s = self.doc.pagePointSize(i)
            h = round(self._pw * s.height() / s.width()) if s.width() > 0 else self._pw
            self._tops.append(y)
            self._hs.append(h)
            y += h + GAP
        self._total = max(0, y - GAP + MARGIN) if n else 0
        v, h = self.verticalScrollBar(), self.horizontalScrollBar()
        v.setRange(0, max(0, self._total - vh))
        v.setPageStep(vh)
        v.setSingleStep(48)
        h.setRange(0, max(0, self._pw + 2 * MARGIN - vw))
        h.setPageStep(vw)
        self.viewport().update()

    def resizeEvent(self, e):
        f = self.scroll_frac()
        super().resizeEvent(e)
        self._cache.clear()
        self._relayout()
        self.set_scroll_frac(f)

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()                  # repaint (a pixel copy would smear the translucent pages)

    # ---- painting ----
    def _page_image(self, i: int, w: int, h: int, dpr: float) -> QImage:
        key = (i, w, h, dpr, self.invert)
        img = self._cache.get(key)
        if img is not None:
            self._cache.move_to_end(key)
            return img
        pw, ph = max(1, round(w * dpr)), max(1, round(h * dpr))
        k = min(1.0, 4096 / max(pw, ph))
        size = QSize(max(1, round(pw * k)), max(1, round(ph * k)))
        raw = self.doc.render(i, size)
        base = QImage(size, QImage.Format_RGB32)       # always start from a white sheet, whatever render() returns
        base.fill(Qt.white)
        q = QPainter(base)
        if not raw.isNull():
            q.drawImage(0, 0, raw)
        q.end()
        img = base
        if self.invert:
            # ink mask: dark pixels of the page become light, opaque "ink"; white paper becomes fully transparent
            gray = base.convertToFormat(QImage.Format_Grayscale8)
            gray.invertPixels(QImage.InvertRgb)
            img = QImage(size, QImage.Format_ARGB32)
            img.fill(QColor(240, 240, 244))
            img.setAlphaChannel(gray)
        img.setDevicePixelRatio(dpr * k)
        self._cache[key] = img
        while len(self._cache) > CACHE_MAX:
            self._cache.popitem(last=False)
        return img

    def paintEvent(self, _):
        vp = self.viewport()
        p = QPainter(vp)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(vp.rect()), RADIUS, RADIUS)
        p.setClipPath(clip)
        p.fillRect(vp.rect(), QColor(14, 14, 20, int(self._a * 200)))      # the same veil the other viewers use
        if self._tops:
            vh, vw = vp.height(), vp.width()
            sy, sx = self.verticalScrollBar().value(), self.horizontalScrollBar().value()
            x = (vw - self._pw) / 2 if self._pw + 2 * MARGIN <= vw else MARGIN - sx
            dpr = self.devicePixelRatioF()
            first = max(0, bisect_right(self._tops, sy) - 1)
            for i in range(first, len(self._tops)):
                top = self._tops[i] - sy
                if top > vh:
                    break
                h = self._hs[i]
                if top + h < 0:
                    continue
                r = QRectF(x, top, self._pw, h)
                img = self._page_image(i, self._pw, h, dpr)
                if self.invert:
                    # dark glass sheet (the wallpaper still shows through it), then the light ink on top, fully opaque
                    p.fillRect(r, QColor(10, 10, 16, 150 + int(90 * self._a)))
                    p.drawImage(r, img)
                else:
                    p.setOpacity(0.3 + 0.7 * self._a)
                    p.drawImage(r, img)
                    p.setOpacity(1.0)

    # ---- scrolling ----
    def scroll_frac(self): return _bar_frac(self)
    def set_scroll_frac(self, f): _bar_set(self, f)
    def scroll_px(self, dy): _bar_px(self, dy)
    def scroll_pages(self, n): _bar_pages(self, n)

    def _ready(self) -> bool:
        return self.doc.status() == QPdfDocument.Status.Ready

    def restore(self, f):
        """Resume at a scroll fraction (the automatic reading position)."""
        self._pending, self._pending_page = f, None
        if self._ready():                       # local files load synchronously: Ready may already have fired
            self._on_status(QPdfDocument.Status.Ready)

    def restore_page(self, page: int):
        """Resume at a bookmarked page. Takes the place of any automatic position."""
        self._pending, self._pending_page = None, page
        if self._ready():
            self._on_status(QPdfDocument.Status.Ready)

    def _on_status(self, status):
        if status != QPdfDocument.Status.Ready:
            return
        self._cache.clear()
        self._relayout()
        if self._pending_page is not None:
            page, self._pending_page = self._pending_page, None
            QTimer.singleShot(300, lambda: self._go_to_page(page))
        elif self._pending is not None:
            f, self._pending = self._pending, None
            QTimer.singleShot(300, lambda: self.set_scroll_frac(f))

    def _go_to_page(self, page: int):
        if not self._tops:
            return
        page = max(0, min(len(self._tops) - 1, page))
        self.verticalScrollBar().setValue(max(0, self._tops[page] - MARGIN))

    # ---- bookmark support ----
    def page_count(self) -> int:
        return self.doc.pageCount() if self._ready() else 0

    def current_page(self) -> int:
        """0-based page at the top of the view (0 until the document is loaded)."""
        if not self._tops:
            return 0
        y = self.verticalScrollBar().value() + MARGIN + 1
        return max(0, min(len(self._tops) - 1, bisect_right(self._tops, y) - 1))

    def load_source(self, path: str):
        self._pending, self._pending_page = None, None
        self._cache.clear()
        self.doc.load(path)
