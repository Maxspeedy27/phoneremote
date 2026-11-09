"""The desktop app's control panel: a page in the laptop's own browser.

Using the browser instead of a GUI toolkit keeps the app small and identical on
Windows, macOS and Linux. The panel server only listens on 127.0.0.1, checks
the Host header (against DNS rebinding) and requires a secret token in a custom
header on every API call, so neither other devices nor other websites open in
the same browser can approve a pairing.
"""

import hmac
import json
import secrets
import threading
import time
import urllib.request
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import urlsplit

from .system import IS_MAC, IS_WIN, mac_accessibility_trusted

PANEL_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/panel.js": ("panel.js", "text/javascript; charset=utf-8"),
    "/panel.css": ("panel.css", "text/css; charset=utf-8"),
}
PANEL_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
             "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MAX_BODY = 4096


def qr_svg(text):
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, border=2,
                        error_correction=qrcode.constants.ERROR_CORRECT_L)
    svg = image.to_string()
    return svg.decode("utf-8") if isinstance(svg, bytes) else svg


class Panel:
    """State shown in the control panel, and the pairing approver it drives."""

    def __init__(self, runtime, settings, version, problem=None):
        self.runtime = runtime
        self.settings = settings
        self.version = version
        self.problem = problem
        self.relay_url = None           # the relay in use (--relay or saved), for switching back on
        self.default_relay = ""
        self.token = secrets.token_urlsafe(24)
        self.url = None                 # set once the panel server is listening
        self.quit = threading.Event()
        self.log_lines = deque(maxlen=40)
        self._pending = None            # dict while a phone waits for approval
        self._lock = threading.Lock()
        self._last_poll = 0.0
        self._qr = {}                   # url -> svg, for the current URLs only

    # ----- activity log -----

    def log(self, text):
        self.log_lines.appendleft((time.time(), str(text)))

    # ----- pairing approval -----

    def approve(self, name, code, timeout):
        """Pairing approver: waits for Allow/Refuse in the panel."""
        decided = threading.Event()
        pending = {"name": name, "code": code, "deadline": time.monotonic() + timeout,
                   "event": decided, "answer": False}
        with self._lock:
            self._pending = pending
        self.log(f"{name} asked to pair (code {code[:3]} {code[3:]}).")
        if time.monotonic() - self._last_poll > 4 and self.url:
            webbrowser.open(self.url)   # nobody is looking at the panel: bring it up
        decided.wait(timeout)
        with self._lock:
            self._pending = None
        if pending["answer"]:
            self.log(f"Paired with {name}.")
        else:
            self.log(f"Pairing with {name} {'refused' if decided.is_set() else 'timed out'}.")
        return pending["answer"]

    def answer(self, allow):
        with self._lock:
            pending = self._pending
        if pending is None:
            return False
        pending["answer"] = bool(allow)
        pending["event"].set()
        return True

    # ----- state for the page -----

    def _qr_for(self, url, keep):
        if url and url not in self._qr:
            try:
                self._qr[url] = qr_svg(url)
            except Exception:
                self._qr[url] = None
        self._qr = {u: svg for u, svg in self._qr.items() if u in keep}
        return self._qr.get(url)

    def state(self):
        self._last_poll = time.monotonic()
        rt = self.runtime
        state = {"version": self.version, "problem": self.problem,
                 "log": [{"t": t, "text": text} for t, text in self.log_lines]}
        if rt is None:
            return state
        device = rt.pairing.device
        with self._lock:
            pending = self._pending
        url = rt.pairing_url
        relay = rt.relay
        relay_url = rt.relay_pairing_url if rt.relay_online else None
        keep = {url, relay_url}
        state.update({
            "url": url,
            "base": rt.base_url,
            "qr": self._qr_for(url, keep),
            "relay": {
                "available": bool(relay is not None or self.default_relay),
                "enabled": relay is not None,
                "state": relay.state if relay else "off",
                "url": relay_url,
                "home": relay.phone_url if relay else None,
                "qr": self._qr_for(relay_url, keep) if relay_url else None,
            },
            "addresses": [{"ip": ip, "kind": kind} for ip, kind in rt.addresses],
            "ip": rt.ip,
            "network": rt.network,
            "device": device and {"name": device.name, "paired_at": device.paired_at},
            "pending": pending and {
                "name": pending["name"], "code": pending["code"],
                "left": max(0, round(pending["deadline"] - time.monotonic())),
            },
            "screen": {"on": rt.screen.enabled, "viewing": rt.screen.viewing,
                       "problem": rt.screen.unavailable_reason() if rt.screen.enabled else None},
            "https": {"on": rt.https, "self_signed": rt.self_signed, "fingerprint": rt.fingerprint,
                      "problem": rt.https_problem},
            "backend": rt.backend.name,
            "os": "mac" if IS_MAC else "windows" if IS_WIN else "linux",
            "accessibility": mac_accessibility_trusted() if IS_MAC else None,
        })
        return state

    # ----- actions from the page -----

    def act(self, action, body):
        rt = self.runtime
        if action == "state":
            return self.state()
        if action == "ping":
            return {"ok": True}
        if action == "quit":
            self.log("Stopping.")
            self.quit.set()
            return {"ok": True}
        if rt is None:
            raise ValueError("Phone Remote isn't running; see the problem above.")
        if action == "answer":
            return {"ok": self.answer(body.get("allow") is True)}
        if action == "forget":
            rt.pairing.forget()
            self.log("Forgot the paired phone.")
            return {"ok": True}
        if action == "screen":
            rt.screen.enabled = body.get("on") is True
            self.settings["screen"] = rt.screen.enabled
            self.log("Screen view " + ("allowed." if rt.screen.enabled else "turned off."))
            return {"ok": True}
        if action == "https":
            on = body.get("on") is True
            ok = rt.set_https(on)
            if ok:
                self.settings["https"] = on
                self.log("HTTPS " + ("on: the phone needs to scan the new QR code once." if on else "off."))
            return {"ok": ok, "error": rt.https_problem}
        if action == "relay":
            on = body.get("on") is True
            self.settings["relay"] = on
            rt.set_relay((self.relay_url or self.default_relay) if on else None)
            self.log("Internet connection " + ("on: connecting to the relay." if on else "off: local network only."))
            return {"ok": True}
        if action == "address":
            rt.refresh_addresses()
            rt.set_ip(body.get("ip"))
            self.log(f"QR code now uses {rt.ip}.")
            return {"ok": True}
        if action == "accessibility" and IS_MAC:
            import subprocess
            subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"],
                           check=False)
            return {"ok": True}
        raise ValueError("unknown action")


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, panel, port=0):
        self.panel = panel
        web = files("phoneremote") / "web" / "panel"
        self.static = {path: (web.joinpath(name).read_bytes(), ctype) for path, (name, ctype) in PANEL_FILES.items()}
        super().__init__(("127.0.0.1", port), PanelHandler)
        self.port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        panel.url = f"http://127.0.0.1:{self.port}/#t={panel.token}"


class PanelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PhoneRemote"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, content_type):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if content_type.startswith("text/html"):
            self.send_header("Content-Security-Policy", PANEL_CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj), "application/json")

    def _host_ok(self):
        return self.headers.get("Host", "") in self.server.allowed_hosts

    def do_GET(self):
        if not self._host_ok():
            return self._send(421, "Wrong host", "text/plain; charset=utf-8")
        path = urlsplit(self.path).path
        if path in self.server.static:
            body, ctype = self.server.static[path]
            return self._send(200, body, ctype)
        self._send(404, "Not found", "text/plain; charset=utf-8")

    do_HEAD = do_GET

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self.close_connection = True
            return self._json(400, {"ok": False, "error": "bad request"})
        raw = self.rfile.read(length)
        token = self.headers.get("X-Panel-Token", "")
        if not self._host_ok() or not hmac.compare_digest(token.encode(), self.server.panel.token.encode()):
            return self._json(403, {"ok": False, "error": "forbidden"})
        path = urlsplit(self.path).path
        if not path.startswith("/api/"):
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            body = json.loads(raw or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be an object")
            result = self.server.panel.act(path[len("/api/"):], body)
        except ValueError as exc:
            return self._json(400, {"ok": False, "error": str(exc)})
        except Exception as exc:
            return self._json(500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        self._json(200, result)


def existing_panel(path):
    """If the app is already running, return its panel URL (else None)."""
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
        port, token = int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/ping", data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-Panel-Token": token, "Host": f"127.0.0.1:{port}"})
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            if json.loads(response.read()).get("ok"):
                return f"http://127.0.0.1:{port}/#t={token}"
    except (OSError, ValueError):
        pass
    return None


def remember_panel(path, server):
    import os

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"port": server.port, "token": server.panel.token}, f)
