"""ffmpeg built into the app, costing nothing until a conversion actually needs it.

Build time (AtmosphericReader.spec): ffmpeg.exe is LZMA-compressed into `ffmpeg.packed` and embedded in
AtmosphericReader.exe as a Windows resource. A resource is mapped from the exe file on demand, so, unlike
files bundled the normal way, it is NOT unpacked to the temp folder on every start of the single-file exe.

Run time: nothing happens at start-up. The first conversion unpacks ffmpeg once into the user's cache folder;
every later conversion (and later runs of the app) reuses that copy. If the exe was built with
AR_FFMPEG_MODE=data, the packed file travels as an ordinary bundled data file and is read from there instead.

This module must stay free of Qt imports: the build script imports it too."""
import hashlib
import os
import sys
from pathlib import Path

PACKED_NAME = "ffmpeg.packed"
RES_NAME = "FFMPEG"                  # name of the exe resource (type RT_RCDATA)
RT_RCDATA = 10
_MAGIC = "ARFF1"                     # header line:  ARFF1 <unpacked size> <tag>\n  then one .xz stream
_CHUNK = 1 << 20


# ---------------------------------------------------------------- build time
def pack(src: str, dst: str) -> None:
    """Compresses ffmpeg(.exe) into `dst` (atomic: a half-written file never replaces a good one)."""
    import lzma
    h, size = hashlib.sha256(), 0
    with open(src, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
            size += len(chunk)
    comp = lzma.LZMACompressor(format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32, preset=6)
    tmp = dst + ".tmp"
    with open(src, "rb") as f, open(tmp, "wb") as out:
        out.write(f"{_MAGIC} {size} {h.hexdigest()[:16]}\n".encode())
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            out.write(comp.compress(chunk))
        out.write(comp.flush())
    os.replace(tmp, dst)


# ---------------------------------------------------------------- run time
class _Packed:
    """Read-only view of the packed bytes (an exe resource or a memory-mapped file)."""
    def __init__(self, view: memoryview, keep=None):
        self.view, self._keep = view, keep

    def close(self):
        self.view.release()
        if self._keep is not None and hasattr(self._keep, "close"):
            try:
                self._keep.close()
            except (BufferError, OSError, ValueError):
                pass


def _resource_view():
    """The ffmpeg resource of the running exe (Windows, frozen build only), or None."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        vp = ctypes.c_void_p
        k32.GetModuleHandleW.argtypes, k32.GetModuleHandleW.restype = [wintypes.LPCWSTR], vp
        k32.FindResourceW.argtypes, k32.FindResourceW.restype = [vp, vp, vp], vp     # (module, NAME, TYPE)
        k32.SizeofResource.argtypes, k32.SizeofResource.restype = [vp, vp], wintypes.DWORD
        k32.LoadResource.argtypes, k32.LoadResource.restype = [vp, vp], vp
        k32.LockResource.argtypes, k32.LockResource.restype = [vp], vp
        module = k32.GetModuleHandleW(None)
        name = ctypes.create_unicode_buffer(RES_NAME)
        res = k32.FindResourceW(module, ctypes.cast(name, vp), vp(RT_RCDATA))
        if not res:
            return None
        size = k32.SizeofResource(module, res)
        ptr = k32.LockResource(k32.LoadResource(module, res))
        if not size or not ptr:
            return None
        arr = (ctypes.c_char * size).from_address(ptr)      # points into the mapped exe: no copy, no read yet
        return _Packed(memoryview(arr).cast("B"), arr)
    except (OSError, AttributeError, ValueError, TypeError):
        return None


def _file_view():
    """ffmpeg.packed shipped as a data file (AR_FFMPEG_MODE=data builds, or running from the sources)."""
    import mmap
    bases = (getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable),
             str(Path(__file__).resolve().parent.parent))
    for base in bases:
        p = Path(base) / PACKED_NAME if base else None
        if p and p.is_file() and p.stat().st_size > 64:
            with open(p, "rb") as f:
                mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            return _Packed(memoryview(mm), mm)
    return None


def available() -> bool:
    """True if this build carries an embedded ffmpeg. Cheap: nothing is read or unpacked."""
    pk = _resource_view() or _file_view()
    if pk is None:
        return False
    pk.close()
    return True


def _exe_name(tag: str) -> str:
    return f"ffmpeg-{tag}" + (".exe" if sys.platform == "win32" else "")


def ensure(cache_dir: str, progress=None) -> str:
    """Path of an unpacked ffmpeg inside `cache_dir`, unpacking it first if this is the first time.
    `progress(fraction)` may return False to cancel. Returns "" if there is no embedded ffmpeg, it could not be
    unpacked, or the user cancelled."""
    import lzma
    pk = _resource_view() or _file_view()
    if pk is None:
        return ""
    view = pk.view
    try:
        head = bytes(view[:96])
        nl = head.find(b"\n")
        line = head[:nl].decode("ascii", "replace").split() if nl > 0 else []
        if len(line) != 3 or line[0] != _MAGIC:
            return ""
        size, tag, start = int(line[1]), line[2], nl + 1
        folder = Path(cache_dir)
        out = folder / _exe_name(tag)
        if out.is_file() and out.stat().st_size == size:
            return str(out)                                  # unpacked earlier: reuse it
        folder.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(f"{out.name}.{os.getpid()}.part")
        dec, written, pos, total = lzma.LZMADecompressor(), 0, start, len(view)
        cancelled = False
        try:
            with open(tmp, "wb") as f:
                while pos < total and not dec.eof:
                    data = dec.decompress(bytes(view[pos:pos + _CHUNK]))
                    pos += _CHUNK
                    f.write(data)
                    written += len(data)
                    if progress and progress(min(1.0, pos / total)) is False:
                        cancelled = True
                        break
            if cancelled or written != size:
                tmp.unlink(missing_ok=True)
                return ""
            if sys.platform != "win32":
                os.chmod(tmp, 0o755)
            try:
                os.replace(tmp, out)
            except OSError:                                  # another instance unpacked it meanwhile and is running it
                tmp.unlink(missing_ok=True)
                if not (out.is_file() and out.stat().st_size == size):
                    return ""
        except (OSError, lzma.LZMAError, ValueError):
            tmp.unlink(missing_ok=True)
            return ""
        for old in folder.glob("ffmpeg-*"):                  # drop copies from older builds (best effort)
            if old != out and not old.name.endswith(".part"):
                try:
                    old.unlink()
                except OSError:
                    pass
        return str(out)
    finally:
        pk.close()
