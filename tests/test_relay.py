import base64
import hashlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from websockets.sync.server import serve

from phoneremote import relay
from phoneremote.relay import RelayClient, host_socket_url, load_room_secret, phone_url, room_id


def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeRelay:
    """A stand-in for relay/src/worker.js: checks the laptop's secret, then
    lets the test send phone requests and collects the laptop's replies."""

    def __init__(self, accept=True):
        self.accept = accept
        self.connections = []
        self.paths = []
        self.auths = []
        self.replies = []
        self.server = serve(self._handler, "127.0.0.1", 0)
        self.url = f"http://127.0.0.1:{self.server.socket.getsockname()[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def _handler(self, ws):
        self.paths.append(ws.request.path)
        auth = json.loads(ws.recv())
        self.auths.append(auth)
        if not self.accept:
            ws.send(json.dumps({"t": "error", "error": "This laptop is not allowed in this room."}))
            return
        ws.send(json.dumps({"t": "ready"}))
        self.connections.append(ws)
        for message in ws:
            if message == "ping":
                ws.send("pong")
            else:
                phone, _, raw = message.partition(" ")
                self.replies.append((phone, json.loads(raw)))

    def ask(self, phone, req_id, path, body):
        self.connections[-1].send(f"{phone} " + json.dumps({"i": req_id, "p": path, "b": body}))

    def drop(self):
        self.connections[-1].close()

    def close(self):
        self.server.shutdown()


class RoomTest(unittest.TestCase):
    def test_room_id_is_a_hash_of_the_secret(self):
        secret = "s3cret-for-testing-only-0123456789abcdef"
        expected = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()[:16]).rstrip(b"=").decode()
        self.assertEqual(room_id(secret), expected)
        self.assertRegex(room_id(secret), r"^[A-Za-z0-9_-]{22}$")   # what the relay's URLs accept

    def test_secret_is_created_once_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conf" / "relay.json"
            first = load_room_secret(path)
            self.assertEqual(load_room_secret(path), first)
            self.assertGreaterEqual(len(first), 32)
            path.write_text("garbage")
            self.assertNotEqual(load_room_secret(path), first)   # unreadable: start a new room

    def test_urls(self):
        self.assertEqual(phone_url("https://relay.example/", "R" * 22), "https://relay.example/r/" + "R" * 22 + "/")
        self.assertEqual(host_socket_url("https://relay.example", "abc"), "wss://relay.example/ws/host/abc")
        self.assertEqual(host_socket_url("http://127.0.0.1:8787", "abc"), "ws://127.0.0.1:8787/ws/host/abc")


class RelayClientTest(unittest.TestCase):
    def setUp(self):
        self.relay = FakeRelay()
        self.addCleanup(self.relay.close)
        self.handled = []
        self.states = []
        self.release_pairing = threading.Event()

    def handle(self, path, body, client):
        self.handled.append((path, body, client))
        if path == "/api/pair":
            self.release_pairing.wait(5)   # like waiting for approval on the laptop
        return 200, {"echo": body, "path": path}

    def client(self):
        c = RelayClient(self.relay.url, "secret-" + "x" * 40, self.handle, log=lambda m: None,
                        on_change=self.states.append)
        self.addCleanup(c.stop)
        c.start()
        self.assertTrue(wait_for(lambda: c.state == "online"), c.error)
        return c

    def test_connects_to_its_room_with_the_secret(self):
        c = self.client()
        self.assertEqual(self.relay.paths, [f"/ws/host/{c.room}"])
        self.assertEqual(self.relay.auths, [{"t": "auth", "secret": "secret-" + "x" * 40}])
        self.assertEqual(self.states, ["online"])
        self.assertEqual(c.phone_url, f"{self.relay.url}/r/{c.room}/")

    def test_answers_phone_requests_through_the_api(self):
        self.client()
        self.relay.ask("phoneA", 7, "/api/hello", {"n": "x"})
        self.assertTrue(wait_for(lambda: self.relay.replies))
        self.assertEqual(self.relay.replies[0], ("phoneA", {"i": 7, "s": 200,
                                                            "b": {"echo": {"n": "x"}, "path": "/api/hello"}}))
        self.assertEqual(self.handled[0][2], "the internet relay")

    def test_commands_stay_in_order_while_pairing_waits(self):
        self.client()
        self.relay.ask("phoneB", 1, "/api/pair", {})          # blocks until "approved"
        for n in range(2, 12):
            self.relay.ask("phoneA", n, "/api/cmd", {"n": n})
        self.assertTrue(wait_for(lambda: len(self.relay.replies) == 10))
        self.assertEqual([r[1]["i"] for r in self.relay.replies], list(range(2, 12)))
        self.release_pairing.set()
        self.assertTrue(wait_for(lambda: len(self.relay.replies) == 11))
        self.assertEqual(self.relay.replies[-1][0], "phoneB")

    def test_ignores_malformed_messages(self):
        self.client()
        conn = self.relay.connections[-1]
        for junk in ("nonsense", "phone {not json", 'ph-one {"i":1,"p":"/api/cmd","b":{}}', "pong"):
            conn.send(junk)
        self.relay.ask("ok", 1, "/api/cmd", {})
        self.assertTrue(wait_for(lambda: self.relay.replies))
        self.assertEqual(len(self.handled), 1)

    def test_reconnects_after_the_connection_drops(self):
        c = self.client()
        self.relay.drop()
        self.assertTrue(wait_for(lambda: c.state == "offline"))
        self.assertTrue(wait_for(lambda: c.state == "online", timeout=8))
        self.assertEqual(len(self.relay.auths), 2)
        self.relay.ask("phoneA", 1, "/api/cmd", {})
        self.assertTrue(wait_for(lambda: self.relay.replies))

    def test_refused_by_the_relay(self):
        self.relay.accept = False
        c = RelayClient(self.relay.url, "wrong-" + "y" * 40, self.handle, log=lambda m: None)
        self.addCleanup(c.stop)
        c.start()
        self.assertTrue(wait_for(lambda: c.state == "offline"))
        self.assertIn("not allowed", c.error)

    def test_unreachable_relay_is_offline_not_fatal(self):
        c = RelayClient("http://127.0.0.1:9", "s" * 40, self.handle, log=lambda m: None)
        self.addCleanup(c.stop)
        c.start()
        self.assertTrue(wait_for(lambda: c.state == "offline"))
        self.assertTrue(c.error)


if __name__ == "__main__":
    unittest.main()
