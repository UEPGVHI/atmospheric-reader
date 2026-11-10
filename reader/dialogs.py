"""Create / edit preset dialog."""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton, QWidget)
from pathlib import Path

from .presets import Preset, import_asset
from .transcode import convert_to_webm, needs_conversion


class PresetDialog(QDialog):
    def __init__(self, parent=None, preset: Preset | None = None):
        super().__init__(parent)
        self.setWindowTitle("Atmospheric Preset")
        self.setMinimumWidth(540)
        self.preset = preset or Preset(name="", source="")
        self._tried: set[str] = set()       # videos we already tried to convert (no repeat prompts)
        self._converted = ""                # a WebM we made in a folder the user chose: kept there, not copied
        p = self.preset

        self.name = QLineEdit(p.name)
        self.name.setPlaceholderText("e.g. Cozy Tavern")
        self.source = QLineEdit(p.source)
        self.source.setPlaceholderText("optional: URL, PDF, text or video file")
        self.bg, self.music = QLineEdit(p.background), QLineEdit(p.music)

        form = QFormLayout(self)
        form.addRow("Name", self.name)
        form.addRow("Content", self._row(self.source, "Documents and videos (*.pdf *.txt *.md *.markdown *.mp4 *.mkv *.webm *.mov *.avi *.m4v *.wmv);;All (*)"))
        form.addRow("Background", self._row(self.bg, "Images and videos (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.webm *.mkv *.mov *.avi *.m4v *.wmv)", convert=True))
        form.addRow("Music", self._row(self.music, "Audio (*.mp3 *.wav *.ogg *.flac *.m4a)"))
        hint = QLabel("Only the name is required. With no content, the wallpaper and music are "
                      "applied to whatever page is already open.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        form.addRow(box)

    def _row(self, edit: QLineEdit, flt: str, convert=False) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit)
        btn = QPushButton("Browse…")
        btn.clicked.connect(lambda: self._browse(edit, flt, convert))
        h.addWidget(btn)
        return w

    def _browse(self, edit: QLineEdit, flt: str, convert=False):
        path, _ = QFileDialog.getOpenFileName(self, "Select file", "", flt)
        if path:
            edit.setText(path)
            if convert:
                self._convert_bg()                      # MP4 etc. -> WebM right after it is chosen

    def _pick_folder(self, src: str) -> str:
        """Asks where the converted WebM goes; starts in the last folder used (or the video's own folder)."""
        store = getattr(self.parent(), "store", None)
        start = (store.settings.get("convert_dir", "") if store else "") or str(Path(src).parent)
        d = QFileDialog.getExistingDirectory(self, "Choose the folder for the converted WebM", start)
        if d and store:
            store.settings["convert_dir"] = d
            store.save()
        return d

    def _convert_bg(self):
        """Video wallpaper that isn't WebM -> convert it so the browser engine can play it on the GPU."""
        path = self.bg.text().strip().strip('"')
        if path in self._tried or not needs_conversion(path):
            return
        self._tried.add(path)
        folder = self._pick_folder(path)
        if not folder:
            return                                          # no folder chosen = skip the conversion
        out, msg = convert_to_webm(self, path, folder)
        if out:
            self.bg.setText(out)
            self._converted = out
            QMessageBox.information(self, "Wallpaper converted", f"Saved to:\n{out}")
        elif msg:
            QMessageBox.information(self, "Wallpaper not converted",
                                    msg + "\n\nThe original file will be used instead (web pages then get its "
                                          "frames streamed, which uses more CPU).")

    def _accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Missing name", "Please give the preset a name.")
            return
        p = self.preset
        p.name = self.name.text().strip()
        new_source = self.source.text().strip()
        if new_source != p.source:
            p.bookmark = -1                                   # a bookmark belongs to the file it was made in
        p.source = new_source
        self._convert_bg()                                    # also covers a path typed or pasted by hand
        bg = self.bg.text().strip()
        # a WebM saved in the folder the user picked stays exactly there; anything else is copied into app assets
        p.background = bg if (bg and bg == self._converted) else import_asset(bg)
        p.music = import_asset(self.music.text().strip())
        self.accept()
