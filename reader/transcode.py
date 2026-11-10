"""Automatic MP4 (or any other video) -> WebM/VP9 conversion for video wallpapers.

Chromium plays VP9 WebM on the GPU, so web pages get the wallpaper with almost no CPU instead of the
frame-stream fallback. Resolution and frame rate are left exactly as in the source (no scale, no -r)."""
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QEventLoop, QProcess, QStandardPaths, Qt
from PySide6.QtWidgets import QApplication, QProgressDialog

from . import ffmpeg_pack
from .presets import VIDEO_EXT, data_dir

_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_OUT_TIME = re.compile(r"out_time_us=(\d+)")
NO_FFMPEG = ("ffmpeg was not found, so the video could not be converted.\n\n"
             "This copy of the app has no built-in ffmpeg. Use the AtmosphericReader.exe built with "
             "build_exe.bat, or put ffmpeg.exe next to the app (or on PATH).")


def _cache_dir() -> str:
    """Where the built-in ffmpeg is unpacked the first time it is needed (per user, outside the roaming data)."""
    base = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
    return str(Path(base or Path.home() / ".atmospheric_reader" / "cache") / "bin")


def _sibling_ffmpeg() -> str:
    """An ffmpeg the user put next to the exe / the sources: it wins over the built-in one."""
    name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    for base in (getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable),
                 str(Path(__file__).resolve().parent.parent)):
        if base and (Path(base) / name).is_file():
            return str(Path(base) / name)
    return ""


def find_ffmpeg(progress=None) -> str:
    """ffmpeg to run, or "". Only called when a conversion is about to start: a user-supplied copy next to the
    app first, then the built-in one (unpacked once, here, on first use), then PATH."""
    return (_sibling_ffmpeg() or ffmpeg_pack.ensure(_cache_dir(), progress)
            or shutil.which("ffmpeg") or "")


def needs_conversion(path: str) -> bool:
    p = Path(path)
    return p.is_file() and p.suffix.lower() in VIDEO_EXT and p.suffix.lower() != ".webm"


def build_args(src: str, out: str) -> list[str]:
    return ["-y", "-hide_banner", "-nostats", "-progress", "pipe:1", "-i", src,
            "-map", "0:v:0", "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30", "-pix_fmt", "yuv420p",
            "-row-mt", "1", "-tile-columns", "2", "-threads", str(os.cpu_count() or 4),
            "-deadline", "good", "-cpu-used", "3", "-an", out]


def unique_path(folder: Path, stem: str) -> Path:
    """folder/stem.webm, or stem_2.webm, stem_3.webm... if that name is taken (never overwrites a file)."""
    out, n = folder / f"{stem}.webm", 2
    while out.exists():
        out = folder / f"{stem}_{n}.webm"
        n += 1
    return out


def convert_to_webm(parent, src: str, out_dir: str = "") -> tuple[str, str]:
    """Converts `src` into `out_dir` (default: the app's assets folder) with a modal, cancellable progress dialog.
    Returns (webm_path, "") on success, or ("", message) on failure ("" message = user cancelled)."""
    folder = Path(out_dir) if out_dir else data_dir() / "assets"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return "", f"Cannot use the folder “{folder}”:\n{e}"
    out = unique_path(folder, Path(src).stem)

    dlg = QProgressDialog("Preparing the video converter…", "Cancel", 0, 100, parent)
    dlg.setWindowTitle("Optimizing wallpaper")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setValue(0)

    def unpacking(frac: float):                              # first use only: the built-in ffmpeg is unpacked now
        dlg.setLabelText("Preparing the video converter (first time only)…")
        dlg.setValue(min(99, int(frac * 100)))
        QApplication.processEvents()
        return not dlg.wasCanceled()

    exe = find_ffmpeg(unpacking)
    if dlg.wasCanceled():
        dlg.close()
        return "", ""
    if not exe:
        dlg.close()
        return "", NO_FFMPEG
    dlg.setLabelText(f"Converting “{Path(src).name}” to WebM (VP9)…\nThis only happens once.")
    dlg.setValue(0)

    proc = QProcess(parent)
    proc.setProgram(exe)
    proc.setArguments(build_args(src, str(out)))
    st = {"dur": 0.0, "err": "", "cancel": False}
    loop = QEventLoop()

    def on_err():                                            # ffmpeg prints "Duration: hh:mm:ss.xx" on stderr
        st["err"] += bytes(proc.readAllStandardError()).decode("utf-8", "replace")
        if not st["dur"]:
            m = _DURATION.search(st["err"])
            if m:
                st["dur"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
        st["err"] = st["err"][-4000:]

    def on_out():                                            # "-progress pipe:1" prints out_time_us=...
        times = _OUT_TIME.findall(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"))
        if times and st["dur"]:
            dlg.setValue(min(99, int(int(times[-1]) / 1e6 / st["dur"] * 100)))

    def on_cancel():
        # QProgressDialog also emits canceled() when it is merely closed (which we do once ffmpeg is done):
        # that must not count as a user cancel, or the finished file would be deleted.
        if proc.state() == QProcess.NotRunning:
            return
        st["cancel"] = True
        proc.kill()

    proc.readyReadStandardError.connect(on_err)
    proc.readyReadStandardOutput.connect(on_out)
    proc.finished.connect(lambda *_: loop.quit())
    dlg.canceled.connect(on_cancel)
    proc.start()
    if not proc.waitForStarted(5000):
        dlg.canceled.disconnect(on_cancel)
        dlg.close()
        return "", f"Could not start ffmpeg ({exe})."
    loop.exec()
    dlg.canceled.disconnect(on_cancel)
    dlg.close()

    ok = (not st["cancel"] and proc.exitStatus() == QProcess.NormalExit and proc.exitCode() == 0
          and out.is_file() and out.stat().st_size > 0)
    if ok:
        return str(out), ""
    out.unlink(missing_ok=True)                              # never leave a partial file behind
    if st["cancel"]:
        return "", ""
    tail = st["err"].strip().splitlines()[-3:]
    return "", "ffmpeg could not convert this video:\n" + "\n".join(tail)
