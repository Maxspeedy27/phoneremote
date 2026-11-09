"""HTTP server: serves the phone page and receives encrypted commands."""

import json
import re
import socket
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlsplit

from .commands import run_ops
from .crypto import b64e, seal
from .pairing import PairingError
from .screen import ScreenUnavailable

MAX_BODY = 64 * 1024

# URL path -> (file under web/, content type). Nothing else is served.
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/crypto.js": ("crypto.js", "text/javascript; charset=utf-8"),
    "/static/nacl-fast.min.js": ("vendor/nacl-fast.min.js", "text/javascript; charset=utf-8"),
    "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
    "/static/icon.svg": ("icon.svg", "image/svg+xml"),
    "/static/icon-192.png": ("icon-192.png", "image/png"),
    "/static/icon-512.png": ("icon-512.png", "image/png"),
    "/apple-touch-icon.png": ("icon-180.png", "image/png"),
}

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' blob:; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def load_static():
    web = files("phoneremote") / "web"
    return {path: (web.joinpath(name).read_bytes(), ctype) for path, (name, ctype) in STATIC_FILES.items()}


def _error_body(code, message):
    return {"ok": False, "code": code, "error": message}


HOST_HEADER = re.compile(r"^[A-Za-z0-9.:\[\]-]{1,255}$")
SAFE_PATH = re.compile(r"^/[\x21-\x7e]{0,1000}$")


class RemoteServer(ThreadingHTTPServer):
    """Serves the phone page and API, over HTTPS when given an SSL context.

    TLS handshakes run on the per-connection thread, so a slow or stalled
    client can't hold up accepting others. A plain-HTTP request sent to the
    HTTPS port (an old bookmark) is redirected to https://.
    """

    daemon_threads = True

    def __init__(self, address, backend, pairing, screen=None, ssl_context=None, log=print):
        self.backend = backend
        self.pairing = pairing
        self.screen = screen
        self.ssl_context = ssl_context
        self.log = log
        self.static = load_static()
        self.input_lock = threading.Lock()  # backends aren't thread-safe; serialize all input
        super().__init__(address, RemoteHandler)

    # ----- the phone API, shared by HTTP requests and the internet relay -----

    def handle_api(self, path, msg, client="?"):
        """Handle one phone request; returns (HTTP status, JSON-able body)."""
        route = {
            "/api/pair": self._pair,
            "/api/hello": self._hello,
            "/api/cmd": self._command,
            "/api/frame": self._frame,
            "/api/cursor": self._cursor,
        }.get(path)
        if route is None:
            return 404, _error_body("not-found", "Not found")
        try:
            return 200, route(msg, client)
        except PairingError as exc:
            return exc.status, _error_body(exc.code, str(exc))
        except ScreenUnavailable as exc:
            return 503, _error_body("screen", str(exc))
        except ValueError as exc:
            return 400, _error_body("bad-request", str(exc))
        except Exception as exc:
            return 500, _error_body("error", f"{type(exc).__name__}: {exc}")

    def _pair(self, msg, client):
        return self.pairing.pair(msg)

    def _hello(self, msg, client):
        device, reply = self.pairing.hello(msg)
        self.log(f"{device.name} connected from {client}.")
        return reply

    def _command(self, msg, client):
        ops = self.pairing.open_command(msg)
        with self.input_lock:
            run_ops(self.backend, ops, self.screen)
        return {"ok": True}

    def _cursor(self, msg, client):
        device, request = self.pairing.open_cursor(msg)
        if self.screen is None:
            raise ScreenUnavailable("Screen view is turned off on the laptop.")
        monitor = request.get("m", 1)
        return seal(device.key, {"t": "cursor", "c": self.screen.cursor(monitor), "m": monitor})

    def _frame(self, msg, client):
        device, request = self.pairing.open_frame(msg)
        screen = self.screen
        if screen is None:
            raise ScreenUnavailable("Screen view is turned off on the laptop.")
        was_viewing = screen.viewing
        jpeg, monitor, count, cursor = screen.grab(request.get("m", 1), request.get("w", 720))
        if not was_viewing:
            self.log(f"{device.name} is viewing the screen.")
        return seal(device.key, {"t": "frame", "img": b64e(jpeg), "m": monitor, "n": count, "c": cursor})

    @property
    def scheme(self):
        return "https" if self.ssl_context else "http"

    def finish_request(self, request, client_address):
        if self.ssl_context is None:
            return super().finish_request(request, client_address)
        request.settimeout(10)
        try:
            first = request.recv(1, socket.MSG_PEEK)
            if not first:
                return
            if first != b"\x16":   # not a TLS ClientHello: plain HTTP
                return self._redirect_to_https(request)
            tls = self.ssl_context.wrap_socket(request, server_side=True)
        except (OSError, ssl.SSLError):
            return  # handshake failed, e.g. the phone rejected the certificate
        try:
            tls.settimeout(None)
            super().finish_request(tls, client_address)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def _redirect_to_https(self, sock):
        head = sock.recv(8192).decode("latin-1", "replace")
        lines = head.split("\r\n")
        parts = lines[0].split(" ")
        path = parts[1] if len(parts) == 3 and SAFE_PATH.match(parts[1]) else "/"
        host = next((line.split(":", 1)[1].strip() for line in lines[1:]
                     if line.lower().startswith("host:")), "")
        if not HOST_HEADER.match(host):
            sock.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            return
        sock.sendall((f"HTTP/1.1 301 Moved Permanently\r\nLocation: https://{host}{path}\r\n"
                      "Content-Length: 0\r\nConnection: close\r\n\r\n").encode("latin-1"))


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

        try:
            msg = json.loads(raw)
        except ValueError:
            return self._error(400, "bad-request", "Body must be JSON")
        status, body = self.server.handle_api(urlsplit(self.path).path, msg, self.client_address[0])
        self._send_json(status, body)
