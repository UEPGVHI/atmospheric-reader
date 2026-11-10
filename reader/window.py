"""Main window: wallpaper, frosted-glass sidebar / toolbar / reader frame, scroll rail, audio controls."""
import uuid
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QSlider, QStackedWidget,
                               QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator, QVBoxLayout)

from . import icons
from .audio import AudioManager
from .dialogs import PresetDialog
from .glass import BackgroundWidget, GlassPanel, ScrollRail
from .presets import PresetStore, Preset, detect_kind, is_video_file
from .viewers import TextViewer, WebViewer       # PDF / video viewers load on first use

ACCENT = "#8ab4ff"
KIND_ICON = {"web": "globe", "pdf": "pdf", "text": "text", "video": "video", "none": "scene"}

STYLE = """
QFrame#panel { background: transparent; border: none; }
QDialog, QMessageBox { background: #181c2a; }
QLabel { color:#f1f3f8; }
QLabel#title { font-size:19px; font-weight:600; letter-spacing:0.3px; }
QLabel#muted { color: rgba(255,255,255,130); font-size:10px; letter-spacing:1px; }
QCheckBox { color:#f1f3f8; spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; border-radius:5px; border:1px solid rgba(255,255,255,85); background: rgba(255,255,255,20); }
QCheckBox::indicator:checked { background:@A; border:1px solid rgba(255,255,255,170); }
QTreeWidget { background:transparent; color:#f4f6fb; border:none; font-size:14px; outline:0; }
QTreeWidget::item { padding:9px 6px; border-radius:10px; margin:1px 0; }
QTreeWidget::item:hover { background: rgba(255,255,255,26); }
QTreeWidget::item:selected { color:#fff; border:1px solid rgba(200,222,255,120);
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(138,180,255,125), stop:1 rgba(138,180,255,50)); }
QTreeView::branch { background: transparent; image: none; border-image: none; }
QPushButton { color:#f4f6fb; border:1px solid rgba(255,255,255,52); border-radius:10px; padding:7px 12px;
    background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,58), stop:1 rgba(255,255,255,18)); }
QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(255,255,255,88), stop:1 rgba(255,255,255,32)); }
QPushButton:pressed { background: rgba(255,255,255,16); }
QPushButton:checked { background: rgba(138,180,255,125); border:1px solid rgba(200,222,255,175); }
QPushButton:disabled { color: rgba(255,255,255,70); background: rgba(255,255,255,10); border:1px solid rgba(255,255,255,20); }
QPushButton#icon { min-width:20px; max-width:20px; padding:7px 8px; font-size:14px; }
QLineEdit { background: rgba(255,255,255,22); color:#f4f6fb; border:1px solid rgba(255,255,255,55);
    border-radius:10px; padding:7px 11px; selection-background-color:@A; }
QLineEdit:focus { border:1px solid @A; background: rgba(255,255,255,30); }
QFrame#rule { background: rgba(255,255,255,34); max-height:1px; min-height:1px; }
QSlider::groove:horizontal { height:4px; background:rgba(255,255,255,50); border-radius:2px; }
QSlider::sub-page:horizontal { background:@A; border-radius:2px; }
QSlider::handle:horizontal { width:14px; height:14px; margin:-5px 0; border-radius:8px; background:#fff; border:1px solid rgba(255,255,255,150); }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar::handle:vertical { background:rgba(255,255,255,70); border-radius:4px; min-height:30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:transparent; }
QToolTip { background:#1b1f2e; color:#f1f3f8; border:1px solid rgba(255,255,255,70); padding:5px 8px; }
QMenu { background:#1b1f2e; color:#f1f3f8; border:1px solid rgba(255,255,255,60); border-radius:10px; padding:6px; }
QMenu::item { padding:7px 22px; border-radius:6px; }
QMenu::item:selected { background: rgba(138,180,255,110); }
""".replace("@A", ACCENT)

WELCOME = """# Atmospheric Reader

Press **＋ New** to create a *preset*: a web page, PDF, text file or video bundled with a
wallpaper (image or video) and looping music. A preset needs only a name: leave the content empty
and it simply changes the atmosphere around whatever is already open.

**F10** zen mode · **F11** fullscreen · **Ctrl+B** sidebar · **Ctrl +/−** zoom
Drop a PDF / .txt / .md / video onto the window to open it.
"""


ROLE_KIND, ROLE_ID = Qt.UserRole + 1, Qt.UserRole + 2      # Qt.UserRole itself holds the Preset object


class PresetTree(QTreeWidget):
    """The sidebar list: a Startup slot, collapsible folders and loose atmospheres. Presets can be dragged
    between folders and re-ordered; folders and the Startup slot only accept drops on themselves."""
    reordered = Signal()
    startup_dropped = Signal(str)       # a preset was dropped on the Startup slot

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setRootIsDecorated(False)
        self.setIndentation(16)
        self.setExpandsOnDoubleClick(False)             # one click opens/closes a folder (handled by the window)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setDefaultDropAction(Qt.MoveAction)
        self.set_reorder(True)

    def set_reorder(self, on: bool):
        self.setDragDropMode(QAbstractItemView.InternalMove if on else QAbstractItemView.NoDragDrop)

    def dropEvent(self, e):
        target = self.itemAt(e.position().toPoint())
        kind = target.data(0, ROLE_KIND) if target is not None else None
        parent = target.parent() if target is not None else None
        if kind in ("startup", "hint") or (parent is not None and parent.data(0, ROLE_KIND) == "startup"):
            moved = self.currentItem()                  # the Startup slot holds one preset: the window handles it
            e.ignore()
            if (moved is not None and moved.data(0, ROLE_KIND) == "preset"
                    and (kind == "hint" or (kind == "startup"
                                            and self.dropIndicatorPosition() == QAbstractItemView.OnItem))):
                self.startup_dropped.emit(moved.data(0, ROLE_ID))
            return
        self.blockSignals(True)          # moving a row must not re-open the preset
        super().dropEvent(e)
        self.blockSignals(False)
        self.reordered.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Atmospheric Reader")
        self.setAcceptDrops(True)
        self.store = PresetStore()
        st = self.store.settings
        self.audio = AudioManager(st["volume"])
        self.setStyleSheet(STYLE)
        self._zen, self._cur_src, self._cur_view, self._cur_kind = False, "", None, ""

        root = self.bg = BackgroundWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # ---------- sidebar ----------
        self.sidebar = GlassPanel(root, radius=22)
        self.sidebar.setFixedWidth(292)
        sb = QVBoxLayout(self.sidebar)
        sb.setContentsMargins(16, 16, 16, 14)
        sb.setSpacing(9)
        sb.addWidget(QLabel("Atmospheres", objectName="title"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search presets…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        sb.addWidget(self.search)
        self.list = PresetTree()
        self.list.setMinimumHeight(110)
        self.list.setIconSize(QSize(18, 18))
        self.list.currentItemChanged.connect(self._on_select)
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.itemExpanded.connect(lambda it: self._on_fold(it, True))
        self.list.itemCollapsed.connect(lambda it: self._on_fold(it, False))
        self.list.reordered.connect(self._on_reorder)
        self.list.startup_dropped.connect(self._on_startup_dropped)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        sb.addWidget(self.list, 1)
        row = QHBoxLayout()
        for text, fn in (("＋ New", self.new_preset), ("Edit", self.edit_preset), ("Delete", self.delete_preset)):
            row.addWidget(self._btn(text, fn))
        row.addWidget(self._ibtn("folder_plus", self.new_folder, "New folder"))
        sb.addLayout(row)
        sb.addWidget(self._btn("Open file or URL…", self.quick_open))
        sb.addWidget(QFrame(objectName="rule"))

        sb.addWidget(QLabel("NOW PLAYING", objectName="muted"))
        self.now_playing = QLabel("—")
        self.now_playing.setWordWrap(True)
        sb.addWidget(self.now_playing)
        arow = QHBoxLayout()
        self.play_btn = self._ibtn("play", self.audio.toggle, "Play / pause music")
        self.vol = self._slider(st["volume"], self._on_volume)
        arow.addWidget(self.play_btn)
        arow.addWidget(icons.label("volume"))
        arow.addWidget(self.vol)
        sb.addLayout(arow)
        sb.addWidget(QFrame(objectName="rule"))

        sb.addWidget(QLabel("READER", objectName="muted"))
        self.opacity = self._slider(st["opacity"], self._on_opacity, 10, 95)
        self.speed = self._slider(st["scroll_speed"], self._on_speed)
        for label, slider in (("Veil", self.opacity), ("Auto-scroll", self.speed)):
            r = QHBoxLayout()
            r.addWidget(QLabel(label))
            r.addWidget(slider)
            sb.addLayout(r)
        self.wall = QCheckBox("Wallpaper behind web pages")
        self.wall.setChecked(st["web_wallpaper"])
        self.wall.toggled.connect(self._on_wall)
        sb.addWidget(self.wall)
        self.pause_bg = QCheckBox("Pause video when unfocused")
        self.pause_bg.setChecked(st["pause_unfocused"])
        self.pause_bg.toggled.connect(self._on_pause_bg)
        sb.addWidget(self.pause_bg)
        self.vmode = QLabel("", objectName="muted")
        self.vmode.setWordWrap(True)
        sb.addWidget(self.vmode)
        sb.addWidget(QLabel("F10 zen  ·  F11 fullscreen  ·  Ctrl+B sidebar\nDrag presets to reorder  ·  right-click for more",
                            objectName="muted"))
        layout.addWidget(self.sidebar)

        # ---------- reader ----------
        right = QVBoxLayout()
        right.setSpacing(12)
        self.web, self.text = WebViewer(root), TextViewer()
        self._pdf = self._video = None                       # created the first time a PDF / video is opened
        self.bar = GlassPanel(root, radius=16)
        nav = QHBoxLayout(self.bar)
        nav.setContentsMargins(10, 8, 10, 8)
        self.back = self._ibtn("chevron_left", self.web.back, "Back")
        self.fwd = self._ibtn("chevron_right", self.web.forward, "Forward")
        self.reload = self._ibtn("reload", self.web.reload, "Reload")
        self.address = QLineEdit()
        self.address.setPlaceholderText("Type a URL or file path and press Enter")
        self.address.returnPressed.connect(lambda: self.show_source(self.address.text().strip().strip('"')))
        self.web.urlChanged.connect(lambda u: self.address.setText(u.toString()))
        nav.addWidget(self._ibtn("sidebar", self.toggle_sidebar, "Show / hide sidebar (Ctrl+B)"))
        for w in (self.back, self.fwd, self.reload, self.address):
            nav.addWidget(w)
        nav.addWidget(self._ibtn("text_smaller", lambda: self.zoom(-1), "Smaller text (Ctrl+−)"))
        nav.addWidget(self._ibtn("text_larger", lambda: self.zoom(1), "Larger text (Ctrl++)"))
        nav.addWidget(self._ibtn("zen", self.toggle_zen, "Zen mode (F10)"))
        self.fs_btn = self._ibtn("fullscreen", self.toggle_fullscreen, "Fullscreen (F11)")
        nav.addWidget(self.fs_btn)
        right.addWidget(self.bar)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.frame = GlassPanel(root, radius=22, inset=8)          # glass bezel around the content
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(8, 8, 8, 8)
        self.stack = QStackedWidget()
        for v in (self.web, self.text):
            self.stack.addWidget(v)
        fl.addWidget(self.stack)
        body.addWidget(self.frame, 1)
        self.rail = ScrollRail(root)
        body.addWidget(self.rail)
        right.addLayout(body, 1)
        layout.addLayout(right, 1)

        # ---------- wiring ----------
        for v in (self.web, self.text):
            self._wire(v)
        self.rail.track.moved.connect(lambda f: self.stack.currentWidget().set_scroll_frac(f))
        self.rail.btn_top.clicked.connect(lambda *_: self.stack.currentWidget().set_scroll_frac(0.0))
        self.rail.btn_bottom.clicked.connect(lambda *_: self.stack.currentWidget().set_scroll_frac(1.0))
        self.rail.btn_up.clicked.connect(lambda *_: self.stack.currentWidget().scroll_pages(-1))
        self.rail.btn_down.clicked.connect(lambda *_: self.stack.currentWidget().scroll_pages(1))
        self.rail.btn_auto.toggled.connect(self._on_auto)
        self._auto = QTimer(self, interval=33)
        self._auto.timeout.connect(self._auto_tick)
        self._autosave = QTimer(self, interval=15000)
        self._autosave.timeout.connect(self._save_all)
        self._autosave.start()

        self.audio.player.playbackStateChanged.connect(self._on_play_state)
        self.bg.still_ready.connect(self.web.set_wallpaper_image)
        self.bg.live_frame.connect(self.web.push_frame)
        self.bg.covered_changed.connect(lambda: QTimer.singleShot(0, self._sync_decode))
        self.web.mode_changed.connect(self._on_vmode)
        for key, fn in (("F11", self.toggle_fullscreen), ("Ctrl+B", self.toggle_sidebar), ("F10", self.toggle_zen),
                        ("Esc", self._on_escape),
                        ("Ctrl+=", lambda: self.zoom(1)), ("Ctrl++", lambda: self.zoom(1)), ("Ctrl+-", lambda: self.zoom(-1))):
            QShortcut(QKeySequence(key), self, activated=fn)

        self._apply_alpha()
        self.web.set_glass(self.wall.isChecked())
        # the Startup slot always opens first; it is activated by begin(), once the window is on screen
        self.refresh_list(select=st.get("startup") or st.get("last", ""), activate=False)
        if self.current_preset() is None:
            self.text.setMarkdown(WELCOME)
            self.stack.setCurrentWidget(self.text)
        self.rail.setVisible(self.stack.currentWidget() is not self._video)
        QTimer.singleShot(0, self._sync_decode)

    def begin(self):
        """Called right after the window is shown: opens the startup atmosphere (wallpaper decode, music, page load)
        so the window itself appears at once instead of after all of that."""
        p = self.current_preset()
        if p:
            self.activate(p)

    # ---------- viewers that are built on demand ----------
    def _wire(self, v):
        v.scrolled.connect(lambda f, v=v: self.rail.set_fraction(f) if v is self.stack.currentWidget() else None)

    def _viewer_for(self, kind: str):
        if kind == "web":
            return self.web
        if kind == "text":
            return self.text
        if kind == "pdf":
            if self._pdf is None:
                from .pdfview import PdfViewer
                self._pdf = PdfViewer()
                self._pdf.set_alpha(self.opacity.value() / 100)
                self.stack.addWidget(self._pdf)
                self._wire(self._pdf)
            return self._pdf
        if self._video is None:
            from .videoview import VideoViewer
            self._video = VideoViewer()
            self._video.playing_changed.connect(self.audio.duck)
            self.stack.addWidget(self._video)
            self._wire(self._video)
        return self._video

    # ---------- small helpers ----------
    @staticmethod
    def _btn(text, slot, icon=False):
        b = QPushButton(text)
        if icon:
            b.setObjectName("icon")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False: slot())
        return b

    @staticmethod
    def _ibtn(name, slot, tip=""):
        """Square icon button (vector icon from icons.py)."""
        b = QPushButton()
        b.setObjectName("icon")
        b.setIcon(icons.icon(name))
        b.setIconSize(QSize(18, 18))
        b.setToolTip(tip)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False: slot())
        return b

    @staticmethod
    def _slider(value, slot, lo=0, hi=100):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(int(value * 100))
        s.valueChanged.connect(slot)
        return s

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def toggle_fullscreen(self):
        """Fullscreen, used by both the F11 key and the toolbar button.
        Only the fullscreen flag is flipped, so leaving it returns to exactly the previous state
        (normal or maximized, same size and place) instead of always dropping to a normal window."""
        self.setWindowState(self.windowState() ^ Qt.WindowFullScreen)

    def _on_escape(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
        elif self._zen:
            self.toggle_zen()

    def _sync_fullscreen_button(self):
        full = self.isFullScreen()
        self.fs_btn.setIcon(icons.icon("fullscreen_exit" if full else "fullscreen"))
        self.fs_btn.setToolTip("Exit fullscreen (F11 / Esc)" if full else "Fullscreen (F11)")

    def toggle_zen(self):
        """Zen mode: only the wallpaper and the content. Hides sidebar, toolbar and rail."""
        self._zen = not self._zen
        for w in (self.sidebar, self.bar):
            w.setVisible(not self._zen)
        self.rail.setVisible(not self._zen and self.stack.currentWidget() is not self._video)
        self.bg.want_blur = not self._zen                    # no glass panels -> no blur to compute
        QTimer.singleShot(0, self._sync_decode)

    def zoom(self, step):
        self.stack.currentWidget().zoom(step)

    def current_preset(self) -> Preset | None:
        item = self.list.currentItem()
        return item.data(0, Qt.UserRole) if item and item.data(0, ROLE_KIND) == "preset" else None

    def _sync_decode(self):
        """Stop decoding the window's own video copy whenever nobody can see it."""
        if not hasattr(self, "_autosave"):        # window still being built
            return
        hidden = self.web.native_active and self.bg.coverage() >= 0.85    # browser plays it, web view covers us
        unfocused = self.pause_bg.isChecked() and not self.isActiveWindow()
        self.bg.set_paused(self.isMinimized() or hidden or unfocused)

    def changeEvent(self, e):
        if e.type() in (QEvent.WindowStateChange, QEvent.ActivationChange):
            self._sync_decode()
        if e.type() == QEvent.WindowStateChange and hasattr(self, "fs_btn"):
            self._sync_fullscreen_button()                  # also follows changes made by the OS (e.g. Win+Up)
        super().changeEvent(e)

    # ---------- presets ----------
    # ---------- sidebar tree: startup slot, folders, atmospheres ----------
    @staticmethod
    def _header(kind: str, key: str, text: str, icon_name: str) -> QTreeWidgetItem:
        it = QTreeWidgetItem([text])
        it.setIcon(0, icons.icon(icon_name))
        it.setData(0, ROLE_KIND, kind)
        it.setData(0, ROLE_ID, key)
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)       # not selectable: clicking only opens / closes
        return it

    @staticmethod
    def _preset_item(p: Preset) -> QTreeWidgetItem:
        it = QTreeWidgetItem([p.name])
        it.setIcon(0, icons.icon(KIND_ICON[detect_kind(p.source)]))
        it.setData(0, Qt.UserRole, p)
        it.setData(0, ROLE_KIND, "preset")
        it.setData(0, ROLE_ID, p.id)
        tip = p.source or "(no content: wallpaper and music only)"
        if p.bookmark >= 0 and detect_kind(p.source) == "pdf":
            tip += f"\nBookmark: page {p.bookmark + 1}"
        it.setToolTip(0, tip)
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
        return it

    def refresh_list(self, select: str = "", load: bool = True, activate: bool = True):
        st, presets = self.store.settings, {p.id: p for p in self.store.presets}
        startup = st.get("startup", "")
        tree = self.list
        tree.blockSignals(True)
        tree.clear()
        head = self._header("startup", "", "Startup", "star")
        tree.addTopLevelItem(head)
        if startup in presets:
            head.addChild(self._preset_item(presets[startup]))
        else:
            hint = QTreeWidgetItem(["Empty: right-click an atmosphere"])
            hint.setData(0, ROLE_KIND, "hint")
            hint.setToolTip(0, "Right-click an atmosphere → “Set as startup atmosphere”, or drag it here.\n"
                               "It will be the first one opened every time the app starts.")
            hint.setFlags(Qt.NoItemFlags)
            head.addChild(hint)
        for e in self.store.layout:
            if "f" in e:
                f = self._header("folder", e["f"], e["name"], "folder_open" if e["open"] else "folder")
                tree.addTopLevelItem(f)
                for pid in e["items"]:
                    if pid in presets and pid != startup:
                        f.addChild(self._preset_item(presets[pid]))
                f.setExpanded(bool(e["open"]))
            elif e["p"] in presets and e["p"] != startup:
                tree.addTopLevelItem(self._preset_item(presets[e["p"]]))
        head.setExpanded(bool(st.get("startup_open", True)))
        tree.blockSignals(False)
        found = self._find_preset_item(select)
        if found:
            tree.blockSignals(True)
            tree.setCurrentItem(found)
            tree.blockSignals(False)
        self._filter(self.search.text())
        if activate and self.current_preset():
            self.activate(self.current_preset(), load)

    def _find_preset_item(self, preset_id: str):
        if not preset_id:
            return None
        it = QTreeWidgetItemIterator(self.list)
        while it.value():
            node = it.value()
            if node.data(0, ROLE_KIND) == "preset" and node.data(0, ROLE_ID) == preset_id:
                return node
            it += 1
        return None

    def _on_item_clicked(self, item, _col):
        if item.data(0, ROLE_KIND) in ("folder", "startup") and not self.search.text().strip():
            item.setExpanded(not item.isExpanded())

    def _on_fold(self, item, opened: bool):
        kind = item.data(0, ROLE_KIND)
        if kind == "folder":
            item.setIcon(0, icons.icon("folder_open" if opened else "folder"))
            self.store.set_open(item.data(0, ROLE_ID), opened)
        elif kind == "startup":
            self.store.settings["startup_open"] = opened

    def _filter(self, text: str):
        t = text.strip().lower()
        tree = self.list
        tree.blockSignals(True)                              # search-driven open/close must not be remembered
        for i in range(tree.topLevelItemCount()):
            it = tree.topLevelItem(i)
            kind = it.data(0, ROLE_KIND)
            if kind == "preset":
                it.setHidden(bool(t) and t not in it.text(0).lower())
                continue
            matches = 0
            for j in range(it.childCount()):
                c = it.child(j)
                hit = c.data(0, ROLE_KIND) == "preset" and (not t or t in c.text(0).lower())
                c.setHidden(bool(t) and not hit)
                matches += hit
            it.setHidden(bool(t) and not matches)
            if t:
                it.setExpanded(bool(matches))
            else:                                            # back to the remembered open / closed state
                opened = (self.store.settings.get("startup_open", True) if kind == "startup"
                          else bool((self.store.folder(it.data(0, ROLE_ID)) or {}).get("open", True)))
                it.setExpanded(opened)
            if kind == "folder":
                it.setIcon(0, icons.icon("folder_open" if it.isExpanded() else "folder"))
        tree.blockSignals(False)
        tree.set_reorder(not t)                              # dragging only makes sense on the full list

    def _on_reorder(self):
        """A preset was dragged: read the new arrangement back from the tree and save it."""
        tree, st = self.list, self.store.settings
        old_startup, new_startup, layout = st.get("startup", ""), st.get("startup", ""), []

        def ids(parent):
            return [parent.child(i).data(0, ROLE_ID) for i in range(parent.childCount())
                    if parent.child(i).data(0, ROLE_KIND) == "preset"]

        for i in range(tree.topLevelItemCount()):
            it = tree.topLevelItem(i)
            kind = it.data(0, ROLE_KIND)
            if kind == "startup":
                inside = ids(it)
                new_startup = inside[0] if inside else ""    # dragged out of the slot = no startup atmosphere
            elif kind == "folder":
                layout.append({"f": it.data(0, ROLE_ID), "name": it.text(0), "open": it.isExpanded(),
                               "items": ids(it)})
            elif kind == "preset":
                layout.append({"p": it.data(0, ROLE_ID)})
        self.store.set_layout(layout, new_startup)
        if new_startup != old_startup:                       # the slot's look changes: rebuild once the drag is over
            QTimer.singleShot(150, lambda: self.refresh_list(select=st.get("last", ""), activate=False))

    def _on_startup_dropped(self, preset_id: str):
        QTimer.singleShot(0, lambda: self._set_startup(preset_id))

    def _set_startup(self, preset_id: str):
        self.store.set_startup(preset_id)
        self.refresh_list(select=self.store.settings.get("last", ""), activate=False)

    def _on_select(self, item, _prev):
        if item and item.data(0, ROLE_KIND) == "preset":
            self.activate(item.data(0, Qt.UserRole))

    # ---------- folders ----------
    def new_folder(self):
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        if ok and name.strip():
            self.store.new_folder(name)
            self.refresh_list(select=self.store.settings.get("last", ""), activate=False)

    def rename_folder(self, fid: str):
        f = self.store.folder(fid)
        name, ok = QInputDialog.getText(self, "Rename folder", "Folder name:", text=f["name"] if f else "")
        if ok and name.strip():
            self.store.rename_folder(fid, name)
            self.refresh_list(select=self.store.settings.get("last", ""), activate=False)

    def delete_folder(self, fid: str):
        f = self.store.folder(fid)
        if f and QMessageBox.question(self, "Delete folder",
                                      f"Delete the folder “{f['name']}”?\nIts atmospheres are kept.") == QMessageBox.Yes:
            self.store.delete_folder(fid)
            self.refresh_list(select=self.store.settings.get("last", ""), activate=False)

    def _restructure(self, fn, *args):
        fn(*args)
        self.refresh_list(select=self.store.settings.get("last", ""), activate=False)

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        kind = it.data(0, ROLE_KIND) if it else None
        # Every action only *records* what to do. It runs after the menu has closed and the tree's mouse
        # handling has finished: rebuilding the tree (clear()) from inside a menu / dialog opened by the
        # click that is still being processed left Qt with dangling items and crashed on the 2nd or 3rd use.
        todo = {}
        m = QMenu(self)

        def add(menu, text, fn, checked=None, enabled=True):
            act = QAction(text, menu)
            act.setEnabled(enabled)
            if checked is not None:
                act.setCheckable(True)
                act.setChecked(checked)
            todo[act] = fn
            menu.addAction(act)

        if kind == "preset":
            p = it.data(0, Qt.UserRole)
            is_startup = self.store.settings.get("startup") == p.id
            add(m, "Edit…", lambda: self.edit_preset(p))
            add(m, "Duplicate", lambda: self.duplicate_preset(p))
            if detect_kind(p.source) == "web":               # only for URL atmospheres
                found = self._chapter_to_update()
                add(m, "Update chapter to the current page", lambda: self._update_chapter(p),
                    enabled=bool(found and found[0].id == p.id))
            if detect_kind(p.source) == "pdf":                # only for PDF atmospheres
                found = self._page_to_save()
                here = bool(found and found[0].id == p.id)
                label = f"Save bookmark here (page {found[1] + 1})" if here else "Save bookmark here"
                add(m, label, lambda: self._save_page(p), enabled=here and found[1] != max(0, p.bookmark))
                add(m, "Remove bookmark", lambda: self._clear_bookmark(p), enabled=p.bookmark >= 0)
            m.addSeparator()
            if is_startup:
                add(m, "Remove from Startup", lambda: self._restructure(self.store.set_startup, ""))
            else:
                add(m, "★  Set as startup atmosphere", lambda: self._restructure(self.store.set_startup, p.id))
            sub = m.addMenu("Move to folder")
            here = self.store.folder_of(p.id)
            for fid, name in [("", "(no folder)")] + [(e["f"], e["name"]) for e in self.store.layout if "f" in e]:
                add(sub, name, lambda fid=fid: self._restructure(self.store.move_to_folder, p.id, fid),
                    checked=(fid == here and not is_startup))
            add(m, "New folder…", self.new_folder)
            m.addSeparator()
            add(m, "Delete", lambda: self.delete_preset(p))
        elif kind == "folder":
            fid = it.data(0, ROLE_ID)
            add(m, "Rename…", lambda: self.rename_folder(fid))
            add(m, "Move up", lambda: self._restructure(self.store.move_folder, fid, -1))
            add(m, "Move down", lambda: self._restructure(self.store.move_folder, fid, 1))
            m.addSeparator()
            add(m, "Delete folder (keeps the atmospheres)", lambda: self.delete_folder(fid))
        elif kind == "startup":
            if self.store.settings.get("startup"):
                add(m, "Remove from Startup", lambda: self._restructure(self.store.set_startup, ""))
            else:
                m.deleteLater()
                return
        else:
            add(m, "New folder…", self.new_folder)
        chosen = m.exec(self.list.viewport().mapToGlobal(pos))
        fn = todo.get(chosen)
        m.deleteLater()
        if fn:
            QTimer.singleShot(0, fn)                         # after the event that opened the menu is done

    def activate(self, p: Preset, load: bool = True):
        self.bg.set_image(p.background)
        video_bg = is_video_file(p.background)
        self.web.set_live(video_bg, p.background if video_bg else "")
        self.web.set_wallpaper("" if video_bg else p.background, self.bg.source_image())
        self.audio.play(p.music)
        self.now_playing.setText(Path(p.music).name.split("_", 1)[-1] if p.music else "(no music)")
        self.setWindowTitle(f"{p.name} — Atmospheric Reader")
        if load:                       # empty source = keep the page that is already open
            self.show_source(p.source, page=p.bookmark if p.bookmark >= 0 else None)
        self.store.settings["last"] = p.id
        QTimer.singleShot(0, self._sync_decode)

    def show_source(self, src: str, page: int | None = None):
        """`page`: a PDF bookmark. It is always honoured and replaces the automatic reading position."""
        kind = detect_kind(src)
        if kind == "none":
            return
        self._save_pos()
        viewer = self._viewer_for(kind)
        if viewer is not self._video:
            if self._video is not None:
                self._video.stop()
        else:
            self.rail.btn_auto.setChecked(False)
        for w in (self.back, self.fwd, self.reload):
            w.setEnabled(kind == "web")
        self.address.setText(src)
        viewer.load_source(src)
        f = self.store.settings["positions"].get(self._pos_key(src, kind))
        if kind == "pdf" and page is not None:
            viewer.restore_page(page)                        # the bookmark wins, every time
            f = None
        elif f:
            viewer.restore(f)                                # resume where you stopped reading
        self._cur_src, self._cur_view, self._cur_kind = src, viewer, kind
        self.stack.setCurrentWidget(viewer)
        self.rail.setVisible(not self._zen and viewer is not self._video)
        self.rail.set_fraction(f or 0.0)
        QTimer.singleShot(0, self._sync_decode)

    @staticmethod
    def _pos_key(src: str, kind: str) -> str:
        return QUrl.fromUserInput(src).toString() if kind == "web" else str(Path(src).resolve())

    def _save_pos(self):
        v, kind = self._cur_view, self._cur_kind
        if v is None or kind == "video":
            return
        key = self.web.url().toString() if kind == "web" else self._pos_key(self._cur_src, kind)
        pos = self.store.settings["positions"]
        if key:
            pos[key] = round(v.scroll_frac(), 4)
            while len(pos) > 300:
                pos.pop(next(iter(pos)))

    def _save_all(self):
        self._save_pos()
        self.store.save()

    def new_preset(self):
        dlg = PresetDialog(self)
        if dlg.exec():
            self.store.upsert(dlg.preset)
            self.refresh_list(select=dlg.preset.id)

    def edit_preset(self, p: Preset | None = None):
        p = p or self.current_preset()
        old = p.source if p else ""
        if p and (dlg := PresetDialog(self, p)).exec():
            self.store.upsert(dlg.preset)
            # only reload the content if its source changed; wallpaper/music apply instantly
            self.refresh_list(select=p.id, load=(dlg.preset.source != old))

    def duplicate_preset(self, p: Preset | None = None):
        p = p or self.current_preset()
        if p:
            c = replace(p, id=uuid.uuid4().hex[:10], name=f"{p.name} (copy)")
            self.store.add_after(p.id, c)
            self.refresh_list(select=self.store.settings.get("last", ""), load=False)

    def delete_preset(self, p: Preset | None = None):
        p = p or self.current_preset()
        if p and QMessageBox.question(self, "Delete", f"Delete preset “{p.name}”?") == QMessageBox.Yes:
            self.store.remove(p.id)
            self.refresh_list()

    def quick_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open document", "",
                                              "Documents and videos (*.pdf *.txt *.md *.markdown *.mp4 *.mkv *.webm *.mov *.avi *.m4v *.wmv)")
        if path:
            self.show_source(path)
        else:
            self.address.setFocus()
            self.address.selectAll()

    # ---------- drag & drop ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.show_source(u.toLocalFile())
                break

    # ---------- audio / look / scrolling ----------
    def _on_volume(self, v):
        self.audio.set_volume(v / 100)
        self.store.settings["volume"] = v / 100

    def _on_play_state(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_btn.setIcon(icons.icon("pause" if playing else "play"))

    def _on_opacity(self, v):
        self.store.settings["opacity"] = v / 100
        self._apply_alpha()

    def _apply_alpha(self):
        a = self.opacity.value() / 100
        for v in (self.web, self._pdf, self.text):
            if v is not None:
                v.set_alpha(a)

    def _on_speed(self, v):
        self.store.settings["scroll_speed"] = v / 100

    def _on_auto(self, on: bool):
        self.rail.btn_auto.setIcon(icons.icon("pause" if on else "play"))
        self._auto.start() if on else self._auto.stop()

    def _auto_tick(self):
        v = self.stack.currentWidget()
        v.scroll_px((15 + 285 * self.speed.value() / 100) * 0.033)      # 15..300 px per second
        if v.scroll_frac() >= 0.999:
            self.rail.btn_auto.setChecked(False)

    def _on_vmode(self, mode: str):
        self.vmode.setText({"native": "WEB VIDEO: GPU PLAYBACK", "frames": "WEB VIDEO: FRAME STREAM (CPU)"}.get(mode, ""))
        self.vmode.setToolTip("Frame stream is used when the browser engine can't play this video format.\n"
                              "Re-encoding the wallpaper as WebM (VP9) lets it play natively on the GPU.")
        QTimer.singleShot(0, self._sync_decode)

    def _on_wall(self, on):
        self.store.settings["web_wallpaper"] = on
        self.web.set_glass(on)

    def _on_pause_bg(self, on):
        self.store.settings["pause_unfocused"] = on
        self._sync_decode()

    def _open_page_url(self) -> str:
        """Address of the web page being read ("" if the open content is not a normal web page)."""
        url = self.web.url()
        if self._cur_kind != "web" or url.scheme() not in ("http", "https"):
            return ""                                        # blank / error pages are never offered
        return url.toString()

    @staticmethod
    def _same_address(a: str, b: str) -> bool:
        return QUrl.fromUserInput(a).toString().rstrip("/") == QUrl.fromUserInput(b).toString().rstrip("/")

    def _chapter_to_update(self):
        """(preset, url) when the open web page differs from the active atmosphere's web address, else None."""
        p = self.current_preset()
        new = self._open_page_url()
        if p is None or not new or detect_kind(p.source) != "web":
            return None
        return None if self._same_address(new, p.source) else (p, new)

    def _startup_chapter_to_update(self):
        """(startup preset, url, current preset): the user is in an atmosphere with no web address while reading a
        web page, and the Startup atmosphere has a different web address. Else None."""
        cur, new = self.current_preset(), self._open_page_url()
        sid = self.store.settings.get("startup", "")
        start = next((q for q in self.store.presets if q.id == sid), None)
        if cur is None or not new or start is None or cur.id == start.id:
            return None
        if detect_kind(cur.source) != "none" or detect_kind(start.source) != "web":
            return None
        return None if self._same_address(new, start.source) else (start, new, cur)

    def _offer_startup_update(self):
        """Before leaving, from an atmosphere without a web address: offers to save the page being read as the web
        address of the Startup atmosphere. Only that atmosphere's URL changes."""
        found = self._startup_chapter_to_update()
        if not found:
            return
        start, url, cur = found
        shown = url if len(url) <= 110 else url[:107] + "…"
        box = QMessageBox(QMessageBox.Question, "Update the Startup atmosphere",
                          f"Update the Startup atmosphere “{start.name}” before leaving?", QMessageBox.Yes | QMessageBox.No, self)
        box.setInformativeText(f"You are in “{cur.name}”, which has no web address. If you choose Yes, the Startup "
                               f"atmosphere “{start.name}” will open at this page next time:\n{shown}\n\n"
                               f"Only its web address changes.")
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec() == QMessageBox.Yes:
            self.store.upsert(replace(start, source=url))

    def _update_chapter(self, p: Preset):
        """Right-click action: saves the page being read as this atmosphere's address (only the URL changes)."""
        found = self._chapter_to_update()
        if found and found[0].id == p.id:
            self.store.upsert(replace(p, source=found[1]))
            self.refresh_list(select=p.id, activate=False)

    def _offer_chapter_update(self):
        """Before leaving: offers to save the page being read as the atmosphere's address. Only the URL changes."""
        found = self._chapter_to_update()
        if not found:
            return
        p, url = found
        shown = url if len(url) <= 110 else url[:107] + "…"
        box = QMessageBox(QMessageBox.Question, "Update the chapter",
                          "Update the chapter before leaving?", QMessageBox.Yes | QMessageBox.No, self)
        box.setInformativeText(f"“{p.name}” will open at this page next time:\n{shown}")
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec() == QMessageBox.Yes:
            self.store.upsert(replace(p, source=url))        # nothing but the URL is touched

    def _page_to_save(self):
        """(preset, 0-based page, page count) when the open PDF is the active atmosphere's own file, else None."""
        p = self.current_preset()
        if p is None or self._cur_kind != "pdf" or self._pdf is None or detect_kind(p.source) != "pdf":
            return None
        try:
            if Path(self._cur_src).resolve() != Path(p.source).resolve():
                return None                                  # another PDF was opened: never bookmark the wrong file
        except OSError:
            return None
        n = self._pdf.page_count()
        return (p, self._pdf.current_page(), n) if n > 0 else None

    def _save_page(self, p: Preset):
        """Right-click action: remembers the page being read as this atmosphere's bookmark."""
        found = self._page_to_save()
        if found and found[0].id == p.id:
            self.store.upsert(replace(p, bookmark=found[1]))
            self.refresh_list(select=p.id, activate=False)

    def _clear_bookmark(self, p: Preset):
        self.store.upsert(replace(p, bookmark=-1))
        self.refresh_list(select=p.id, activate=False)

    def _offer_page_save(self):
        """Before leaving: offers to bookmark the page being read. It is where the atmosphere will reopen."""
        found = self._page_to_save()
        if not found or found[1] == max(0, found[0].bookmark):
            return
        p, page, n = found
        box = QMessageBox(QMessageBox.Question, "Save your page",
                          "Save your page before leaving?", QMessageBox.Yes | QMessageBox.No, self)
        box.setInformativeText(f"“{p.name}” will reopen at page {page + 1} of {n}.")
        box.setDefaultButton(QMessageBox.Yes)
        if box.exec() == QMessageBox.Yes:
            self.store.upsert(replace(p, bookmark=page))

    def closeEvent(self, e):
        self._offer_page_save()
        self._offer_chapter_update()
        self._offer_startup_update()
        self._save_all()
        super().closeEvent(e)
