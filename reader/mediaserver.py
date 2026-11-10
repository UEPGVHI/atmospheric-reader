"""Tiny loopback-only HTTP server (with Range support) so the embedded browser can play the wallpaper
video itself, with hardware decoding. Listens on 127.0.0.1 only, behind a random token."""
import os
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_MIME = {".webm": "video/webm", ".mkv": "video/webm", ".mp4": "video/mp4",
         ".m4v": "video/mp4", ".mov": "video/quicktime"}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_HEAD(self):
        self._serve(False)

    def do_GET(self):
        self._serve(True)

    def _serve(self, body: bool):
        srv, path = self.server, self.server.file
        if self.path.split("?")[0] != "/" + srv.token or not path:
            return self.send_error(404)
        try:
            size = os.path.getsize(path)
        except OSError:
            return self.send_error(404)
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", "").strip())
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
            else:                                            # "bytes=-N": the last N bytes
                start = max(0, size - int(m.group(2)))
            end = min(end, size - 1)
            if start > end:
                return self.send_error(416)
            code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", _MIME.get(os.path.splitext(path)[1].lower(), "video/mp4"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not body:
            return
        try:
            with open(path, "rb") as f:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
        except OSError:                                      # browser closed the connection (seek/loop)
            pass


class MediaServer:
    def __init__(self):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._srv.daemon_threads = True
        self._srv.token, self._srv.file = secrets.token_urlsafe(9), ""
        self._ver = 0                                        # bumped per file, so each video gets its own URL
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def set_file(self, path: str):
        if path != self._srv.file:
            self._ver += 1
        self._srv.file = path

    def url(self) -> str:
        # the handler ignores the query; a new ?v= makes the page's <video> load the new file instead of the old one
        return f"http://127.0.0.1:{self._srv.server_address[1]}/{self._srv.token}?v={self._ver}"
