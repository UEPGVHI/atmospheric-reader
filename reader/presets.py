"""Preset model + JSON persistence + asset management."""
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def data_dir() -> Path:
    """Per-user data folder (e.g. ~/.local/share/AtmosphericReader, %APPDATA%\\...)."""
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    path = Path(base) if base else Path.home() / ".atmospheric_reader"
    (path / "assets").mkdir(parents=True, exist_ok=True)
    return path


def import_asset(src: str) -> str:
    """Copy a background/music file into the app's assets folder so the preset
    keeps working even if the original file is moved or deleted."""
    if not src:
        return ""
    s, assets = Path(src), data_dir() / "assets"
    if not s.is_file() or assets in s.parents:
        return str(s)
    if s.stat().st_size > 200 * 1024 * 1024:      # huge videos stay where they are
        return str(s)
    dest = assets / f"{uuid.uuid4().hex[:8]}_{s.name}"
    shutil.copy2(s, dest)
    return str(dest)


VIDEO_EXT = (".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".wmv")


def is_video_file(path: str) -> bool:
    return bool(path) and path.lower().endswith(VIDEO_EXT) and Path(path).is_file()


def detect_kind(source: str) -> str:
    """Returns 'none' (no content), 'web', 'pdf', 'text' or 'video'."""
    source = (source or "").strip()
    if not source:
        return "none"
    low = source.lower().split("?")[0]
    if Path(source).is_file():
        if low.endswith(VIDEO_EXT):
            return "video"
        return "pdf" if low.endswith(".pdf") else "text"
    if low.startswith(("http://", "https://")) and low.endswith(VIDEO_EXT):
        return "video"          # direct link to a video file
    return "web"


@dataclass
class Preset:
    name: str
    source: str                 # URL, or path to .pdf / .txt / .md
    background: str = ""        # image path
    music: str = ""             # audio path
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    bookmark: int = -1          # PDF atmospheres: 0-based page to resume at (-1 = none)


class PresetStore:
    DEFAULTS = {"volume": 0.5, "opacity": 0.55, "web_wallpaper": True, "last": "", "positions": {},
                "pause_unfocused": False, "scroll_speed": 0.25, "convert_dir": "",
                "startup": "", "startup_open": True}

    def __init__(self):
        self.file = data_dir() / "presets.json"
        self.presets: list[Preset] = []
        # How the sidebar is arranged (UI only, nothing is created on disk). A list of top-level entries:
        #   {"p": preset_id}                                   an atmosphere outside any folder
        #   {"f": folder_id, "name": str, "open": bool, "items": [preset_id, ...]}   a folder
        self.layout: list[dict] = []
        self.settings = dict(self.DEFAULTS)
        self._saved = ""                      # last JSON written: unchanged state = no disk write
        try:
            data = json.loads(self.file.read_text("utf-8"))
            self.presets = [Preset(**p) for p in data.get("presets", [])]
            self.settings.update(data.get("settings", {}))
            self.layout = data.get("layout", [])
        except (FileNotFoundError, ValueError, TypeError):
            pass
        self._reconcile()

    def _reconcile(self):
        """Makes `layout` match the presets: unknown ids dropped, duplicates removed, missing presets appended."""
        ids = {p.id for p in self.presets}
        seen: set = set()

        def take(pid) -> bool:
            ok = isinstance(pid, str) and pid in ids and pid not in seen
            if ok:
                seen.add(pid)
            return ok

        out = []
        for e in (self.layout if isinstance(self.layout, list) else []):
            if not isinstance(e, dict):
                continue
            if "f" in e:
                items = [i for i in (e.get("items") or []) if take(i)]
                out.append({"f": str(e["f"]), "name": str(e.get("name") or "Folder"),
                            "open": bool(e.get("open", True)), "items": items})
            elif take(e.get("p")):
                out.append({"p": e["p"]})
        out += [{"p": p.id} for p in self.presets if p.id not in seen]
        self.layout = out
        if self.settings.get("startup") not in ids:
            self.settings["startup"] = ""

    def save(self):
        self._reconcile()
        payload = json.dumps({"presets": [asdict(p) for p in self.presets], "layout": self.layout,
                              "settings": self.settings}, indent=2)
        if payload == self._saved:            # the 15 s autosave usually has nothing new to write
            return
        tmp = self.file.with_name(self.file.name + ".tmp")
        tmp.write_text(payload, "utf-8")
        os.replace(tmp, self.file)            # atomic: a crash mid-write can't leave a corrupt presets.json
        self._saved = payload

    def upsert(self, preset: Preset):
        for i, p in enumerate(self.presets):
            if p.id == preset.id:
                self.presets[i] = preset
                break
        else:
            self.presets.append(preset)
        self.save()

    def remove(self, preset_id: str):
        self.presets = [p for p in self.presets if p.id != preset_id]
        self.save()

    # ---------- folders / startup slot (arrangement only) ----------
    def folder(self, folder_id: str) -> dict | None:
        return next((e for e in self.layout if e.get("f") == folder_id), None)

    def folder_of(self, preset_id: str) -> str:
        return next((e["f"] for e in self.layout if "f" in e and preset_id in e["items"]), "")

    def new_folder(self, name: str) -> str:
        fid = uuid.uuid4().hex[:8]
        self.layout.insert(0, {"f": fid, "name": name.strip() or "Folder", "open": True, "items": []})
        self.save()
        return fid

    def rename_folder(self, folder_id: str, name: str):
        if (f := self.folder(folder_id)) and name.strip():
            f["name"] = name.strip()
            self.save()

    def set_open(self, folder_id: str, is_open: bool):
        if f := self.folder(folder_id):
            f["open"] = is_open                       # saved by the autosave / on exit

    def delete_folder(self, folder_id: str):
        """Removes the folder only; its atmospheres stay, in the folder's place."""
        for i, e in enumerate(self.layout):
            if e.get("f") == folder_id:
                self.layout[i:i + 1] = [{"p": pid} for pid in e["items"]]
                break
        self.save()

    def move_folder(self, folder_id: str, delta: int):
        """Moves a folder up (-1) or down (+1) among the folders."""
        idx = [i for i, e in enumerate(self.layout) if "f" in e]
        pos = next((k for k, i in enumerate(idx) if self.layout[i]["f"] == folder_id), None)
        if pos is None or not 0 <= pos + delta < len(idx):
            return
        a, b = idx[pos], idx[pos + delta]
        self.layout[a], self.layout[b] = self.layout[b], self.layout[a]
        self.save()

    def _detach(self, preset_id: str):
        self.layout = [e for e in self.layout if e.get("p") != preset_id]
        for e in self.layout:
            if "f" in e and preset_id in e["items"]:
                e["items"].remove(preset_id)

    def move_to_folder(self, preset_id: str, folder_id: str):
        """folder_id "" = outside any folder."""
        self._detach(preset_id)
        if (f := self.folder(folder_id)) is not None:
            f["items"].append(preset_id)
        else:
            self.layout.append({"p": preset_id})
        self.save()

    def add_after(self, orig_id: str, preset: Preset):
        """Adds a preset right after `orig_id` (same folder)."""
        self.presets.insert(next((i for i, p in enumerate(self.presets) if p.id == orig_id), len(self.presets) - 1) + 1,
                            preset)
        for i, e in enumerate(self.layout):
            if e.get("p") == orig_id:
                self.layout.insert(i + 1, {"p": preset.id})
                break
            if "f" in e and orig_id in e["items"]:
                e["items"].insert(e["items"].index(orig_id) + 1, preset.id)
                break
        self.save()

    def set_startup(self, preset_id: str):
        """The atmosphere pinned in the Startup slot, opened every time the app starts ("" = none)."""
        self.settings["startup"] = preset_id
        self.save()

    def set_layout(self, layout: list, startup: str):
        self.layout, self.settings["startup"] = layout, startup
        self.save()
