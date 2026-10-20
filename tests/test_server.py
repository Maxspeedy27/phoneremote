import http.client
import json
import threading
import unittest

from phoneremote.pairing import Pairing
from phoneremote.server import RemoteServer

from helpers import Approver, FakeBackend, temp_store
from test_pairing import Phone


class ServerTest(unittest.TestCase):
    """Runs the real HTTP server on localhost with a fake input backend."""

    def setUp(self):
        self.backend = FakeBackend()
        self.pairing = Pairing(temp_store(self), Approver(True), host="laptop")
        self.logs = []
        self.server = RemoteServer(("127.0.0.1", 0), self.backend, self.pairing, log=self.logs.append)
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
        for path in ("/static/app.js", "/static/crypto.js", "/static/nacl-fast.min.js", "/static/style.css"):
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


if __name__ == "__main__":
    unittest.main()
