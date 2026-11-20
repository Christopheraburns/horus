"""The signing proxy (burndown 8.9): tile files in object storage, served to tileserver on localhost.

tileserver-gl-light reads PMTiles from a local file or an unauthenticated
http(s) URL. This serves ``http://127.0.0.1:<port>/<id>.pmtiles`` with HTTP
byte ranges and reads each range from the bucket with the service's own
credentials (bucket.py: RAZ-signed on CDP in AWS). It listens on 127.0.0.1
only, so neither the browser nor anything outside the Application reaches it.

Every range read through RAZ costs about 70 ms (measured 2026-11-20), so ranges
are kept in memory (TILE_CACHE_MB, default 256), most recently used first.
Tile files never change in place (a new version is a new file), so the cache
never needs invalidating. tileserver's PMTiles library already caches the
header and directories; this cache mostly holds tiles.
"""
from __future__ import annotations

import re
import sys
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")
MAX_RANGE = 64 * 1024 * 1024     # tileserver asks for directories and tiles, never whole files


class RangeCache:
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        self.size = 0
        self.items: OrderedDict = OrderedDict()
        self.lock = threading.Lock()
        self.hits = self.misses = 0

    def get(self, key):
        with self.lock:
            v = self.items.get(key)
            if v is None:
                self.misses += 1
                return None
            self.items.move_to_end(key)
            self.hits += 1
            return v

    def put(self, key, value: tuple) -> None:
        n = len(value[0])
        if n > self.max_bytes // 8:   # one huge range shouldn't empty the cache
            return
        with self.lock:
            if key in self.items:
                return
            self.items[key] = value
            self.size += n
            while self.size > self.max_bytes:
                _, old = self.items.popitem(last=False)
                self.size -= len(old[0])


class Source:
    """One tile file: where it is and how to read a range of it."""

    def __init__(self, size: int, get_range: Callable[[int, int], tuple[bytes, int, str]]):
        self.size = size
        self.get_range = get_range


class QuietServer(ThreadingHTTPServer):
    """A client closing a kept-alive connection (the Workbench ingress, tileserver's
    connection pool) is normal; don't print a traceback for it."""

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)

def make_handler(sources: dict, cache: RangeCache, log: Callable[..., None]):
    denied = set()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def _send(self, status: int, headers: dict, body: bytes = b"") -> None:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            id_ = self.path.split("?", 1)[0].lstrip("/")
            id_ = id_[:-len(".pmtiles")] if id_.endswith(".pmtiles") else None
            src = sources.get(id_)
            if src is None:
                return self._send(404, {"Content-Type": "text/plain"}, b"no such tile file\n")
            m = RANGE_RE.match(self.headers.get("Range", ""))
            if not m:   # FetchSource always sends a single range; whole files are never served
                return self._send(416, {"Content-Range": f"bytes */{src.size}"})
            start = int(m.group(1))
            end = min(int(m.group(2)) if m.group(2) else src.size - 1, src.size - 1, start + MAX_RANGE - 1)
            if start >= src.size:
                return self._send(416, {"Content-Range": f"bytes */{src.size}"})
            key = (id_, start, end)
            hit = cache.get(key)
            if hit is None:
                try:
                    data, total, etag = src.get_range(start, end)
                except Exception as e:   # noqa: BLE001 -- the reason goes in the log, the request fails
                    name = type(e).__name__
                    if "Unauthorized" in name or "AccessDenied" in str(e):
                        if id_ not in denied:
                            denied.add(id_)
                            log(f"DENIED reading {id_}: {e} (Ranger S3 policy on the tiles prefix; Ranger -> Audits)")
                        return self._send(403, {"Content-Type": "text/plain"}, b"denied\n")
                    log(f"ERROR reading {id_} bytes {start}-{end}: {name}: {e}")
                    return self._send(502, {"Content-Type": "text/plain"}, b"bucket read failed\n")
                hit = (data, total or src.size, etag)
                cache.put(key, hit)
            data, total, etag = hit
            headers = {"Content-Type": "application/octet-stream",
                       "Content-Range": f"bytes {start}-{start + len(data) - 1}/{total}",
                       "Accept-Ranges": "bytes"}
            if etag:
                headers["ETag"] = etag
            self._send(206, headers, data)

        do_HEAD = do_GET

    return Handler


def serve(port: int, sources: dict, cache_bytes: int, log: Callable[..., None]) -> tuple[ThreadingHTTPServer, RangeCache]:
    """Listens on 127.0.0.1 only. ``sources``: id -> Source."""
    cache = RangeCache(cache_bytes)
    server = QuietServer(("127.0.0.1", port), make_handler(sources, cache, log))
    server.daemon_threads = True
    return server, cache
