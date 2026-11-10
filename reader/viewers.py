"""Text and web viewers (PDF and video live in pdfview.py / videoview.py and load on first use).
All viewers expose load_source(src), set_alpha(a) and zoom(step)."""
import json
import time
from pathlib import Path

from PySide6.QtCore import (QBuffer, QByteArray, QIODevice, QPoint, QRect, QRunnable, Qt, QThreadPool,
                            QTimer, QUrl, Signal)
from PySide6.QtGui import QColor, QImage
from PySide6.QtWebEngineCore import QWebEngineScript, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from PySide6.QtWidgets import QTextBrowser


def _bar_frac(w) -> float:
    b = w.verticalScrollBar()
    return b.value() / b.maximum() if b.maximum() > 0 else 0.0


def _bar_set(w, f: float):
    b = w.verticalScrollBar()
    b.setValue(round(max(0.0, min(1.0, f)) * b.maximum()))


def _bar_px(w, dy: float):
    w._acc = getattr(w, "_acc", 0.0) + dy              # scrollbars are integer: keep the fraction
    n = int(w._acc)
    if n:
        w._acc -= n
        b = w.verticalScrollBar()
        b.setValue(b.value() + n)


def _bar_pages(w, n: float):
    b = w.verticalScrollBar()
    b.setValue(b.value() + round(b.pageStep() * 0.9 * n))


class TextViewer(QTextBrowser):
    """Plain text and Markdown."""
    scrolled = Signal(float)

    def __init__(self):
        super().__init__()
        self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # the glass rail replaces the bar
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bar = self.verticalScrollBar()
        bar.valueChanged.connect(lambda _v: self.scrolled.emit(self.scroll_frac()))
        bar.rangeChanged.connect(lambda *_: self.scrolled.emit(self.scroll_frac()))
        self._alpha, self._fs = 0.55, 16
        self._style()

    def _style(self):
        self.setStyleSheet(
            f"QTextBrowser {{ background: rgba(14,14,20,{self._alpha:.2f}); color:#ececec; border:none;"
            f"border-radius:14px; padding:26px 34px; font-size:{self._fs}px; }}")

    def set_alpha(self, a: float):
        self._alpha = a
        self._style()

    def zoom(self, step: int):
        self._fs = max(10, min(40, self._fs + 2 * step))
        self._style()

    def scroll_frac(self): return _bar_frac(self)
    def set_scroll_frac(self, f): _bar_set(self, f)
    def scroll_px(self, dy): _bar_px(self, dy)
    def scroll_pages(self, n): _bar_pages(self, n)

    def restore(self, f):
        QTimer.singleShot(80, lambda: self.set_scroll_frac(f))

    def load_source(self, path: str):
        text = Path(path).read_text("utf-8", errors="replace")
        if Path(path).suffix.lower() in (".md", ".markdown"):
            self.setMarkdown(text)
        else:
            self.setPlainText(text)


# Runs inside every page. A constructed stylesheet is used because it is not blocked
# by a site's Content-Security-Policy (an injected <style> tag can be).
_JS = """(()=>{try{const c=__CSS__;let s=window.__arSheet;
if(!s||window.__arDoc!==document){s=window.__arSheet=new CSSStyleSheet();window.__arDoc=document;
document.adoptedStyleSheets=[...document.adoptedStyleSheets,s]}s.replaceSync(c)}catch(e){}})()"""


# Live video layer: a fixed <img> behind the page content (above the html background), fed by Python.
# Two stacked <img>: the next frame is loaded + decoded in the hidden one, then both are swapped in the
# same instant, so the page never shows a blank/black frame while an image is still decoding.
_LIVE_JS = """((a)=>{try{let d=document.getElementById('ar-live');
if(!d){d=document.createElement('div');d.id='ar-live';
d.style.cssText='position:fixed;left:0;top:0;width:100%;height:100%;z-index:-2147483648;pointer-events:none;overflow:hidden;will-change:transform';
const s='position:absolute;max-width:none;max-height:none;visibility:hidden';
d.innerHTML='<img style="'+s+'"><img style="'+s+'"><div style="position:absolute;left:0;top:0;width:100%;height:100%"></div>';
document.documentElement.appendChild(d);d._cur=0;d._pend=false}
const im=[d.children[0],d.children[1]],v=d.children[2],k=a.x+','+a.y+','+a.w+','+a.h+','+a.vw+','+a.vh+a.veil;
if(d._k!==k){d._k=k;for(const i of im){i.style.left=(a.x/a.vw*100)+'vw';i.style.top=(a.y/a.vh*100)+'vh';i.style.width=(a.w/a.vw*100)+'vw';i.style.height=(a.h/a.vh*100)+'vh'}v.style.background=a.veil}
if(d._pend)return;
const n=im[1-d._cur],o=im[d._cur];d._pend=true;n.src=a.src;
n.decode().then(()=>{n.style.visibility='visible';o.style.visibility='hidden';d._cur=1-d._cur},()=>{}).finally(()=>{d._pend=false})
}catch(e){}})(__ARGS__)"""
_REMOVE_LIVE_JS = "(()=>{for(const id of ['ar-live','ar-vid']){const d=document.getElementById(id);if(d)d.remove()}})()"
_POS_JS = "(()=>{const e=document.scrollingElement||document.documentElement;const m=e.scrollHeight-innerHeight;return m>0?e.scrollTop/m:0})()"
_REMOVE_VID_JS = "(()=>{const d=document.getElementById('ar-vid');if(d)d.remove()})()"

# Native layer: a real <video> (decoded by the browser engine, GPU-accelerated when the codec allows it).
_VID_JS = """(()=>{try{const a=__ARGS__;let d=document.getElementById('ar-vid');
if(!d){d=document.createElement('div');d.id='ar-vid';
d.style.cssText='position:fixed;left:0;top:0;width:100%;height:100%;z-index:-2147483648;pointer-events:none;overflow:hidden;will-change:transform';
const v=document.createElement('video');v.muted=true;v.setAttribute('muted','');v.loop=true;v.autoplay=true;v.playsInline=true;
v.disablePictureInPicture=true;v.style.cssText='position:absolute;max-width:none;max-height:none';v.src=a.src;
const o=document.createElement('div');o.style.cssText='position:absolute;left:0;top:0;width:100%;height:100%';
d.append(v,o);document.documentElement.appendChild(d);const p=v.play();if(p)p.catch(()=>{})}
const v=d.firstChild,o=d.lastChild;if(v.getAttribute('src')!==a.src){v.src=a.src;const q=v.play();if(q)q.catch(()=>{})}
v.style.left=(a.x/a.vw*100)+'vw';v.style.top=(a.y/a.vh*100)+'vh';v.style.width=(a.w/a.vw*100)+'vw';v.style.height=(a.h/a.vh*100)+'vh';
o.style.background=a.veil}catch(e){}})()"""
# 1 = playing, 0 = not started yet, -1 = error (codec/CSP), -2 = layer missing
_CHECK_JS = "(()=>{const v=document.querySelector('#ar-vid video');if(!v)return -2;if(v.error)return -1;return v.videoWidth>0&&!v.paused?1:0})()"
LIVE_INTERVAL = 0.03           # guard only; the 25 fps cadence comes from the window's timer
LIVE_MAX = (1920, 1080)        # frames sent to web pages are capped at 1080p


class _EncodeTask(QRunnable):
    """Scales + JPEG-encodes one frame on a worker thread, so the window stays responsive."""
    def __init__(self, view, img, geo, veil, max_w):
        super().__init__()
        self.view, self.img, self.geo, self.veil, self.max_w = view, img, geo, veil, max_w

    def run(self):
        small = self.img
        if small.width() > self.max_w:                       # downscale only, never upscale
            small = small.scaledToWidth(self.max_w, Qt.SmoothTransformation)
        small = small.convertToFormat(QImage.Format_RGB888)   # the JPEG writer's native format: no extra pass
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        small.save(buf, "JPEG", 70)
        x, y, w, h, vw, vh = self.geo
        args = json.dumps({
            "src": "data:image/jpeg;base64," + bytes(ba.toBase64()).decode(),
            "x": x, "y": y, "w": w, "h": h, "vw": vw, "vh": vh, "veil": self.veil})
        self.view.encoded.emit(_LIVE_JS.replace("__ARGS__", args))     # final script is built here, off the GUI thread


_WALL_CACHE: dict = {}          # (path, mtime, size) -> (base64 jpeg, w, h); re-opening a preset is then instant
_WALL_CACHE_MAX = 4


class _WallTask(QRunnable):
    """Loads (if needed), scales and JPEG-encodes the still wallpaper off the GUI thread."""
    def __init__(self, view, gen, key, path, img):
        super().__init__()
        self.view, self.gen, self.key, self.path, self.img = view, gen, key, path, img

    def run(self):
        img = self.img if (self.img is not None and not self.img.isNull()) else QImage(self.path)
        if img.isNull():
            self.view.wall_encoded.emit(self.gen, self.key, "", 0, 0)
            return
        if img.width() > 2560:
            img = img.scaledToWidth(2560, Qt.SmoothTransformation)
        img = img.convertToFormat(QImage.Format_RGB32)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "JPEG", 82)
        self.view.wall_encoded.emit(self.gen, self.key, bytes(ba.toBase64()).decode(), img.width(), img.height())


class WebViewer(QWebEngineView):
    """Live web pages. The wallpaper is painted *inside* the page (aligned with the
    window wallpaper), so it shows through even on sites with opaque backgrounds."""
    encoded = Signal(str)               # emitted from the worker thread, handled on the GUI thread
    wall_encoded = Signal(int, object, str, int, int)   # (generation, cache key, base64, w, h) from a worker
    scrolled = Signal(float)
    mode_changed = Signal(str)          # '' | 'native' | 'frames'  (how the wallpaper video reaches the page)

    def __init__(self, anchor):
        super().__init__()
        self.anchor = anchor                     # widget that holds the window wallpaper
        self.page().setBackgroundColor(QColor(14, 14, 20))
        self.enabled, self.alpha = True, 0.55
        self._b64, self._iw, self._ih = "", 0, 0
        self._live, self._busy_until, self._last_push = False, 0.0, 0.0
        self.encoded.connect(self._send)
        self._wall_gen = 0
        self.wall_encoded.connect(self._on_wall_encoded)
        self._server, self._vurl, self._vsize = None, "", (0, 0)
        self._sfrac, self._pending = 0.0, None
        self._poll = QTimer(self, interval=250)
        self._poll.timeout.connect(self._poll_scroll)
        self._mode, self._native_bad, self._native_ok, self._tries = "frames", False, False, 0
        self._chk = QTimer(self, singleShot=True, interval=1500)
        self._chk.timeout.connect(self._check_native)
        self.loadStarted.connect(self._on_load_started)
        self.loadFinished.connect(self._on_load_finished)
        self.settings().setAttribute(QWebEngineSettings.PlaybackRequiresUserGesture, False)
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self._install)

    # ---- public API ----
    def set_alpha(self, a: float):
        self.alpha = a
        self._timer.start()

    def set_glass(self, on: bool):
        self.enabled = on
        self._install()
        if not on:
            self.page().runJavaScript(_REMOVE_LIVE_JS)

    def set_wallpaper(self, path: str, img=None):
        """Still wallpaper for web pages. `img` (already decoded by the window) saves a second decode."""
        self._wall_gen += 1
        if not (path and Path(path).is_file()):
            self._b64 = ""
            self._install()
            return
        st = Path(path).stat()
        key = (path, st.st_mtime_ns, st.st_size)
        hit = _WALL_CACHE.get(key)
        if hit:
            self._b64, self._iw, self._ih = hit
            self._install()
        else:
            QThreadPool.globalInstance().start(_WallTask(self, self._wall_gen, key, path, img))

    def set_wallpaper_image(self, img: QImage):
        self._wall_gen += 1
        if img.isNull():
            self._b64 = ""
            self._install()
        else:
            QThreadPool.globalInstance().start(_WallTask(self, self._wall_gen, None, "", img))

    def _on_wall_encoded(self, gen: int, key, b64: str, w: int, h: int):      # GUI thread
        if gen != self._wall_gen:
            return                                           # a newer wallpaper was requested meanwhile
        self._b64, self._iw, self._ih = b64, w, h
        if key is not None and b64:
            _WALL_CACHE[key] = (b64, w, h)
            while len(_WALL_CACHE) > _WALL_CACHE_MAX:
                _WALL_CACHE.pop(next(iter(_WALL_CACHE)))
        self._install()

    # ---- video wallpaper inside the page ----
    def set_live(self, on: bool, path: str = ""):
        """on=True while the wallpaper is a video. First tries the browser's own (GPU) video playback;
        if it can't play the file, decoded frames are streamed into the page instead."""
        self._live, self._busy_until, self._vsize = on, 0.0, (0, 0)
        self._native_bad = self._native_ok = False
        self._vurl, self._tries = "", 0
        self._chk.stop()
        if on and path:
            if self._server is None:
                from .mediaserver import MediaServer            # loaded only when a video wallpaper first needs it
                self._server = MediaServer()
            self._server.set_file(path)
            self._vurl = self._server.url()
        self._mode = "native" if self._vurl else "frames"
        self.mode_changed.emit("")
        if not on:
            self.page().runJavaScript(_REMOVE_LIVE_JS)
        else:
            self._chk.start()

    def _geo(self, iw: int, ih: int):
        """Where the video sits inside this view so it lines up with the window wallpaper."""
        W, H = self.anchor.width(), self.anchor.height()
        if W <= 0 or H <= 0 or iw <= 0 or ih <= 0:
            return None
        k = max(W / iw, H / ih)                              # same "cover" maths as the window
        dw, dh = iw * k, ih * k
        p = self.mapTo(self.anchor, QPoint(0, 0))
        a = self.alpha
        veil = (f"linear-gradient(rgba(14,14,20,{a:.2f}),rgba(14,14,20,{a:.2f})),"
                "linear-gradient(rgba(0,0,0,.24),rgba(0,0,0,.24))")
        return (round((W - dw) / 2 - p.x()), round((H - dh) / 2 - p.y()), round(dw), round(dh), veil)

    def _install_native(self):
        scripts = self.page().scripts()
        for s in scripts.find("ar-vid"):
            scripts.remove(s)
        if not (self._live and self.enabled and self._mode == "native" and self._vurl):
            return
        geo = self._geo(*self._vsize)
        if geo is None:
            return
        x, y, w, h, veil = geo
        js = _VID_JS.replace("__ARGS__", json.dumps({"src": self._vurl, "x": x, "y": y, "w": w, "h": h,
                                                          "vw": self.width(), "vh": self.height(), "veil": veil}))
        s = QWebEngineScript()
        s.setName("ar-vid")
        s.setInjectionPoint(QWebEngineScript.DocumentReady)
        s.setWorldId(QWebEngineScript.MainWorld)
        s.setRunsOnSubFrames(False)
        s.setSourceCode(js)
        scripts.insert(s)                                    # future pages ...
        self.page().runJavaScript(js)                        # ... and the one that is open now

    def _on_load_started(self):
        self._chk.stop()
        self._tries = 0
        if self._live and self._vurl and not self._native_bad:
            self._mode = "native"                            # a failure on one page doesn't ban native playback

    def _on_load_finished(self, _ok):
        if self._mode == "native":
            self._chk.start()
        if self._pending is not None:
            f, self._pending = self._pending, None
            QTimer.singleShot(600, lambda: self.set_scroll_frac(f))

    def _check_native(self):
        if self._mode != "native" or not self._live:
            return
        if not self.isVisible():
            self._chk.start()
            return
        self.page().runJavaScript(_CHECK_JS, 0, self._on_check)

    def _on_check(self, r):
        if self._mode != "native" or not self._live:
            return
        if r == 1:
            self._native_ok = True
            self.mode_changed.emit("native")
        elif r == -1 or self._tries >= 3:                    # can't play it here -> stream frames instead
            if not self._native_ok:
                self._native_bad = True                      # never worked: probably an unsupported codec
            self._mode = "frames"
            self.page().runJavaScript(_REMOVE_VID_JS)
            self.mode_changed.emit("frames")
        else:
            self._tries += 1
            self._chk.start()

    def push_frame(self, img: QImage):
        if not (self._live and self.enabled) or img.isNull():
            return
        size = (img.width(), img.height())
        if size != self._vsize:
            self._vsize = size
            self._timer.start()                              # video size known -> (re)place the native layer
        now = time.monotonic()
        if (self._mode == "native" or not self.isVisible()
                or now < self._busy_until or now - self._last_push < LIVE_INTERVAL):
            return                                           # native playback needs no frames from us
        geo = self._geo(*size)
        if geo is None:
            return
        x, y, w, h, veil = geo
        self._last_push = now
        # never send more pixels than are shown on screen, and never more than 1080p
        max_w = int(min(size[0], LIVE_MAX[0], LIVE_MAX[1] * size[0] / size[1], w * self.devicePixelRatioF()))
        self._busy_until = now + 1.0                         # one frame in flight at a time
        QThreadPool.globalInstance().start(_EncodeTask(self, img, (x, y, w, h, self.width(), self.height()), veil, max(2, max_w)))

    def _send(self, js: str):                                # GUI thread
        if not self._live:
            self._busy_until = 0.0
            return
        self.page().runJavaScript(js, 0, lambda _r: setattr(self, "_busy_until", 0.0))

    @property
    def native_active(self) -> bool:
        return self._mode == "native" and self._native_ok and self.isVisible()

    # ---- scrolling (driven by the glass rail) ----
    def _poll_scroll(self):
        if self.window().isMinimized():                      # nobody sees the rail: skip the page round-trip
            return
        self.page().runJavaScript(_POS_JS, 0, self._on_pos)

    def _on_pos(self, r):
        try:
            f = max(0.0, min(1.0, float(r)))
        except (TypeError, ValueError):
            return
        if abs(f - self._sfrac) > 0.0005:
            self._sfrac = f
            self.scrolled.emit(f)

    def scroll_frac(self): return self._sfrac

    def set_scroll_frac(self, f):
        self.page().runJavaScript("(f=>{const e=document.scrollingElement||document.documentElement;"
                                  "e.scrollTo(0,f*(e.scrollHeight-innerHeight))})(%f)" % f)

    def scroll_px(self, dy): self.page().runJavaScript("window.scrollBy(0,%f)" % dy)

    def scroll_pages(self, n):
        self.page().runJavaScript("window.scrollBy({top:innerHeight*.9*%f,behavior:'smooth'})" % n)

    def restore(self, f): self._pending = f

    def load_source(self, src: str):
        self.load(QUrl.fromUserInput(src))

    def zoom(self, step: int):
        self.setZoomFactor(max(0.3, min(3.0, self.zoomFactor() + 0.1 * step)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._timer.start()
        self._sync_cover()

    def moveEvent(self, e):
        super().moveEvent(e)
        self._sync_cover()

    def showEvent(self, e):
        super().showEvent(e)
        self._sync_cover()
        self._poll.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        self._sync_cover()
        self._poll.stop()

    def _sync_cover(self):
        """Tell the window which area this (opaque) view hides, so it skips painting video there."""
        r = QRect(self.mapTo(self.anchor, QPoint(0, 0)), self.size()) if self.isVisible() else QRect()
        self.anchor.set_covered(r)

    # ---- internals ----
    def _css(self) -> str:
        if not self.enabled:
            return ""
        a, W, H = self.alpha, self.anchor.width(), self.anchor.height()
        veil = f"linear-gradient(rgba(14,14,20,{a:.2f}),rgba(14,14,20,{a:.2f}))"
        if self._b64 and W > 0 and H > 0:
            s = max(W / self._iw, H / self._ih)            # same "cover" maths as the window
            dw, dh = self._iw * s, self._ih * s
            p = self.mapTo(self.anchor, QPoint(0, 0))
            x, y = (W - dw) / 2 - p.x(), (H - dh) / 2 - p.y()
            VW, VH = max(1, self.width()), max(1, self.height())       # viewport units: unaffected by page zoom
            bg = (f"background-image:{veil},linear-gradient(rgba(0,0,0,.24),rgba(0,0,0,.24)),"
                  f"url(data:image/jpeg;base64,{self._b64})!important;"
                  f"background-size:100% 100%,100% 100%,{dw / VW * 100:.4f}vw {dh / VH * 100:.4f}vh!important;"
                  f"background-position:0 0,0 0,{x / VW * 100:.4f}vw {y / VH * 100:.4f}vh!important;")
        else:
            bg = f"background-image:{veil}!important;"
        return (":root{color-scheme:dark}html{scrollbar-width:none}::-webkit-scrollbar{display:none}"
                f"html{{background-color:#0e0e14!important;{bg}background-repeat:no-repeat!important;"
                "background-attachment:fixed!important}"
                "*{background-color:transparent!important}"
                "body,body *{color:#e8e8e8!important}a,a *{color:#8ab4ff!important}"
                "input,textarea,select,button{background-color:rgba(0,0,0,.4)!important;"
                "border-color:rgba(255,255,255,.25)!important}")

    def _install(self):
        scripts = self.page().scripts()
        for s in scripts.find("ar-glass"):
            scripts.remove(s)
        js = _JS.replace("__CSS__", json.dumps(self._css()))
        if self.enabled:                          # also applies to every future navigation
            s = QWebEngineScript()
            s.setName("ar-glass")
            s.setInjectionPoint(QWebEngineScript.DocumentCreation)
            s.setWorldId(QWebEngineScript.MainWorld)
            s.setRunsOnSubFrames(False)
            s.setSourceCode(js)
            scripts.insert(s)
        self.page().runJavaScript(js)             # and to the page that is open now
        self._install_native()


