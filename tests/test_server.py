import http.client
import json
import socket
import ssl
import tempfile
import threading
import unittest
from pathlib import Path

from kumpas import tls
from kumpas.crypto import b64d, unseal
from kumpas.pairing import Pairing
from kumpas.screen import ScreenUnavailable
from kumpas.server import RemoteServer

from helpers import Approver, FakeBackend, temp_store
from test_pairing import Phone


class FakeScreen:
    def __init__(self, reason=None):
        self.reason = reason
        self.viewing = False
        self.requests = []

    def grab(self, monitor, width):
        if self.reason:
            raise ScreenUnavailable(self.reason)
        self.requests.append((monitor, width))
        self.viewing = True
        return b"\xff\xd8jpeg", monitor, 2, [0.25, 0.5]

    def point(self, monitor, fx, fy):
        return round(fx * 1000), round(fy * 100) + monitor

    def cursor(self, monitor):
        if self.reason:
            raise ScreenUnavailable(self.reason)
        return [0.125, 0.75]


class ServerTest(unittest.TestCase):
    """Runs the real HTTP server on localhost with a fake input backend."""

    def setUp(self):
        self.backend = FakeBackend()
        self.pairing = Pairing(temp_store(self), Approver(True), host="laptop")
        self.logs = []
        self.screen = FakeScreen()
        self.server = RemoteServer(("127.0.0.1", 0), self.backend, self.pairing, screen=self.screen,
                                   log=self.logs.append)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        self.addCleanup(self.conn.close)

    def get(self, path):
        self.conn.request("GET", path)
        r = self.conn.getresponse()
        return r, r.read()

    def post(self, path, body):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.conn.request("POST", path, raw, {"Content-Type": "application/json"})
        r = self.conn.getresponse()
        return r.status, json.loads(r.read())

    def paired_phone(self):
        phone = Phone(self.pairing.pairing_fragment())
        status, reply = self.post("/api/pair", phone.pair_message())
        self.assertEqual(status, 200)
        phone.accept_pairing(reply)
        status, reply = self.post("/api/hello", phone.hello_message())
        self.assertEqual(status, 200)
        phone.accept_session(reply)
        return phone

    def test_page_and_assets_served_with_security_headers(self):
        r, body = self.get("/")
        self.assertEqual(r.status, 200)
        self.assertIn(b"/static/app.js", body)
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(r.getheader("Referrer-Policy"), "no-referrer")
        for path in ("/static/app.js", "/static/crypto.js", "/static/nacl-fast.min.js", "/static/style.css",
                     "/manifest.webmanifest", "/static/icon-192.png", "/static/icon-512.png",
                     "/apple-touch-icon.png", "/static/icon.svg"):
            with self.subTest(path=path):
                r, body = self.get(path)
                self.assertEqual(r.status, 200)
                self.assertGreater(len(body), 100)

    def test_unknown_paths_404(self):
        for path in ("/static/../pairing.py", "/api/cmd", "/secret"):
            with self.subTest(path=path):
                r, _ = self.get(path)
                self.assertEqual(r.status, 404)

    def test_end_to_end_commands_over_one_connection(self):
        phone = self.paired_phone()
        status, reply = self.post("/api/cmd", phone.command([{"a": "move", "dx": 3, "dy": 4},
                                                            {"a": "key", "k": "next"}]))
        self.assertEqual((status, reply), (200, {"ok": True}))
        self.assertEqual(self.backend.calls[0], ("move", 3, 4))
        self.assertEqual(len(self.backend.calls), 2)
        self.assertIn("Test phone connected", self.logs[0])

    def test_replay_over_http_rejected(self):
        phone = self.paired_phone()
        msg = phone.command([{"a": "key", "k": "next"}])
        self.assertEqual(self.post("/api/cmd", msg)[0], 200)
        status, reply = self.post("/api/cmd", msg)
        self.assertEqual((status, reply["code"]), (401, "session"))
        self.assertEqual(len(self.backend.calls), 1)

    def test_unpaired_and_garbage_requests_rejected(self):
        status, reply = self.post("/api/cmd", {"d": "nobody", "n": "AAAA", "c": "AAAA"})
        self.assertEqual((status, reply["code"]), (401, "unpaired"))
        status, reply = self.post("/api/cmd", b"not json")
        self.assertEqual((status, reply["code"]), (400, "bad-request"))
        status, reply = self.post("/api/pair", {"n": "AAAA", "c": "AAAA"})
        self.assertEqual((status, reply["code"]), (403, "pairing-expired"))
        self.assertEqual(self.backend.calls, [])

    def test_invalid_operation_reports_error(self):
        phone = self.paired_phone()
        status, reply = self.post("/api/cmd", phone.command([{"a": "key", "k": "nope"}]))
        self.assertEqual((status, reply["error"]), (400, "unknown key"))
        # The connection is still usable afterwards.
        self.assertEqual(self.post("/api/cmd", phone.command([]))[0], 200)

    def test_oversized_body_rejected_without_reading_it(self):
        self.conn.putrequest("POST", "/api/cmd")
        self.conn.putheader("Content-Length", str(10 * 1024 * 1024))
        self.conn.endheaders()
        r = self.conn.getresponse()
        r.read()
        self.assertEqual(r.status, 413)

    def test_screen_frames_are_encrypted_for_the_phone(self):
        phone = self.paired_phone()
        status, reply = self.post("/api/frame", phone.frame(monitor=2, width=500))
        self.assertEqual(status, 200)
        self.assertNotIn("img", reply)   # only ciphertext on the wire
        frame = unseal(phone.device_key, reply)
        self.assertEqual((b64d(frame["img"]), frame["m"], frame["n"], frame["c"]),
                         (b"\xff\xd8jpeg", 2, 2, [0.25, 0.5]))
        self.assertEqual(self.screen.requests, [(2, 500)])
        self.assertIn("Test phone is viewing the screen.", self.logs)
        # Commands still work after frames: separate counters.
        self.assertEqual(self.post("/api/cmd", phone.command([]))[0], 200)

    def test_cursor_polls_are_encrypted_and_light(self):
        phone = self.paired_phone()
        status, reply = self.post("/api/cursor", phone.cursor_poll(monitor=2))
        self.assertEqual(status, 200)
        self.assertEqual(unseal(phone.device_key, reply), {"t": "cursor", "c": [0.125, 0.75], "m": 2})
        self.assertEqual(self.screen.requests, [])      # no screenshot taken for a poll
        self.screen.reason = "Screen view is turned off on the laptop."
        self.assertEqual(self.post("/api/cursor", phone.cursor_poll())[1]["code"], "screen")

    def test_touchscreen_tap_clicks_at_the_point(self):
        phone = self.paired_phone()
        ops = [{"a": "abs", "x": 0.5, "y": 0.25, "m": 1}, {"a": "click", "b": "left"}]
        self.assertEqual(self.post("/api/cmd", phone.command(ops))[0], 200)
        self.assertEqual(self.backend.calls, [("move_to", 500, 26), ("click", "left")])
        self.server.screen = None   # screen view turned off: no touch control
        status, reply = self.post("/api/cmd", phone.command(ops))
        self.assertEqual(status, 400)
        self.assertIn("screen view", reply["error"])

    def test_frames_need_pairing_and_report_unavailable_screen(self):
        status, reply = self.post("/api/frame", {"d": "nobody", "n": "AAAA", "c": "AAAA"})
        self.assertEqual((status, reply["code"]), (401, "unpaired"))
        phone = self.paired_phone()
        self.screen.reason = "Screen view is turned off on the laptop."
        status, reply = self.post("/api/frame", phone.frame())
        self.assertEqual((status, reply["code"], reply["error"]), (503, "screen", self.screen.reason))
        self.server.screen = None
        self.assertEqual(self.post("/api/frame", phone.frame())[1]["code"], "screen")


class HttpsServerTest(unittest.TestCase):
    """The same server with a self-signed certificate."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cert, key = tls.self_signed(Path(tmp.name), ["127.0.0.1"], "testhost")
        self.server = RemoteServer(("127.0.0.1", 0), FakeBackend(),
                                   Pairing(temp_store(self), Approver(True), host="laptop"),
                                   ssl_context=tls.server_context(cert, key), log=lambda m: None)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.client_context = ssl.create_default_context(cafile=str(cert))

    def test_page_served_over_tls_with_the_certificate(self):
        conn = http.client.HTTPSConnection("127.0.0.1", self.port, context=self.client_context, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", "/")
        r = conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn(b"/static/app.js", r.read())
        self.assertEqual(self.server.scheme, "https")

    def test_plain_http_is_redirected_to_https(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", "/static/app.js?x=1")
        r = conn.getresponse()
        self.assertEqual((r.status, r.getheader("Location")),
                         (301, f"https://127.0.0.1:{self.port}/static/app.js?x=1"))

    def test_redirect_refuses_header_injection(self):
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(b"GET / HTTP/1.1\r\nHost: evil.example\rLocation: x\r\n\r\n")
            self.assertTrue(s.recv(200).startswith(b"HTTP/1.1 400"))
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as s:
            s.sendall(b"GET / HTTP/1.1\r\nHost: a b\r\n\r\n")
            self.assertTrue(s.recv(200).startswith(b"HTTP/1.1 400"))

    def test_failed_handshake_does_not_stop_the_server(self):
        bad = ssl.create_default_context()   # doesn't trust the self-signed certificate
        with socket.create_connection(("127.0.0.1", self.port), timeout=10) as raw:
            with self.assertRaises(ssl.SSLError):
                bad.wrap_socket(raw, server_hostname="127.0.0.1")
        self.test_page_served_over_tls_with_the_certificate()


if __name__ == "__main__":
    unittest.main()
