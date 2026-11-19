"""The tile service's front door (burndown 8.3): the Application's port.

Serves ``/registry.json`` (the public view of the tile-set registry, which the
UI builds its layers from) and passes every other request to tileserver-gl-light
on an internal port, streaming the response. It is also where per-tile-set
access checks (markings, section 13) and credentials for customer tile servers
(8.6) belong, because every tile request passes through here.

Standard library only: a threading HTTP server, one upstream connection per
request thread.
"""
from __future__ import annotations

import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
              "trailers", "transfer-encoding", "upgrade"}


class Front:
    def __init__(self, upstream_port: int, registry_public: dict):
        self.upstream_port = upstream_port
        self.registry_body = json.dumps(registry_public, indent=1).encode()
        self.local = threading.local()

    def upstream(self) -> http.client.HTTPConnection:
        conn = getattr(self.local, "conn", None)
        if conn is None:
            conn = self.local.conn = http.client.HTTPConnection("127.0.0.1", self.upstream_port, timeout=60)
        return conn

    def reset(self) -> None:
        conn = getattr(self.local, "conn", None)
        if conn is not None:
            conn.close()
        self.local.conn = None


def make_handler(front: Front):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):   # tileserver already logs every request
            pass

        def _registry(self, head: bool) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(front.registry_body)))
            self.send_header("Access-Control-Allow-Origin", "*")   # the UI is another Application
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if not head:
                self.wfile.write(front.registry_body)

        def _proxy(self) -> None:
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP | {"host"}}
            for attempt in (1, 2):    # a kept-alive upstream connection may have been closed
                try:
                    conn = front.upstream()
                    conn.request(self.command, self.path, headers=headers)
                    resp = conn.getresponse()
                    break
                except (http.client.HTTPException, OSError):
                    front.reset()
                    if attempt == 2:
                        self.send_error(502, "tile server unavailable")
                        return
            body = resp.read()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP | {"content-length"}:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/registry.json":
                self._registry(head=False)
            else:
                self._proxy()

        def do_HEAD(self):
            if self.path.split("?", 1)[0] == "/registry.json":
                self._registry(head=True)
            else:
                self._proxy()

        def do_OPTIONS(self):
            self._proxy()

    return Handler


def serve(port: int, upstream_port: int, registry_public: dict, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(Front(upstream_port, registry_public)))
    server.daemon_threads = True
    return server
