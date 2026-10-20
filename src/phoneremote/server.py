"""HTTP server: serves the phone page and receives encrypted commands."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlsplit

from .commands import run_ops
from .pairing import PairingError

MAX_BODY = 64 * 1024

# URL path -> (file under web/, content type). Nothing else is served.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/crypto.js": ("crypto.js", "text/javascript; charset=utf-8"),
    "/static/nacl-fast.min.js": ("vendor/nacl-fast.min.js", "text/javascript; charset=utf-8"),
}

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def load_static():
    web = files("phoneremote") / "web"
    return {path: (web.joinpath(name).read_bytes(), ctype) for path, (name, ctype) in STATIC_FILES.items()}


class RemoteServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, backend, pairing, log=print):
        self.backend = backend
        self.pairing = pairing
        self.log = log
        self.static = load_static()
        self.input_lock = threading.Lock()  # backends aren't thread-safe; serialize all input
        super().__init__(address, RemoteHandler)


class RemoteHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: the phone reuses one connection
    server_version = "PhoneRemote"
    sys_version = ""

    def setup(self):
        super().setup()
        try:  # send small responses immediately instead of batching them
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet; one line per mouse move would flood it

    def _send(self, code, body, content_type="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type.startswith("text/html"):
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _error(self, status, code, message):
        self._send_json(status, {"ok": False, "code": code, "error": message})

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/index.html":
            path = "/"
        if path in self.server.static:
            body, content_type = self.server.static[path]
            return self._send(200, body, content_type)
        if path == "/favicon.ico":
            return self._send(204, b"")
        self._send(404, "Not found")

    do_HEAD = do_GET

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.close_connection = True
            return self._error(411, "bad-request", "Content-Length required")
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            return self._error(413, "bad-request", "Request too large")
        # Always read the body, even when rejecting, so the kept-alive
        # connection stays in sync for the next request.
        raw = self.rfile.read(length)

        route = {
            "/api/pair": self._pair,
            "/api/hello": self._hello,
            "/api/cmd": self._command,
        }.get(urlsplit(self.path).path)
        if route is None:
            return self._error(404, "not-found", "Not found")
        try:
            msg = json.loads(raw)
        except ValueError:
            return self._error(400, "bad-request", "Body must be JSON")
        try:
            route(msg)
        except PairingError as exc:
            self._error(exc.status, exc.code, str(exc))
        except ValueError as exc:
            self._error(400, "bad-request", str(exc))
        except Exception as exc:
            self._error(500, "error", f"{type(exc).__name__}: {exc}")

    def _pair(self, msg):
        self._send_json(200, self.server.pairing.pair(msg))

    def _hello(self, msg):
        device, reply = self.server.pairing.hello(msg)
        self.server.log(f"{device.name} connected from {self.client_address[0]}.")
        self._send_json(200, reply)

    def _command(self, msg):
        ops = self.server.pairing.open_command(msg)
        with self.server.input_lock:
            run_ops(self.server.backend, ops)
        self._send_json(200, {"ok": True})
