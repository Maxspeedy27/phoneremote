import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from phoneremote import cli, hostui
from phoneremote.runtime import Runtime, Settings

from helpers import FakeBackend, temp_store


class PanelTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.settings = Settings(self.dir / "settings.json")
        self.panel = hostui.Panel(None, self.settings, "9.9")
        self.backend = FakeBackend()
        self.rt = Runtime(self.backend, temp_store(self), self.panel.approve, port=0, log=self.panel.log)
        self.addCleanup(self.rt.server.server_close)
        self.panel.runtime = self.rt
        self.server = hostui.PanelServer(self.panel)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host = f"127.0.0.1:{self.server.port}"

    def call(self, action, body=None, token=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("POST", f"/api/{action}", json.dumps(body or {}),
                     {"Content-Type": "application/json", "Host": host or self.host,
                      "X-Panel-Token": self.panel.token if token is None else token})
        r = conn.getresponse()
        return r.status, json.loads(r.read())

    def test_page_needs_the_right_host(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        self.addCleanup(conn.close)
        conn.request("GET", "/", headers={"Host": self.host})
        r = conn.getresponse()
        self.assertEqual(r.status, 200)
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        r.read()
        # A DNS-rebinding page would arrive with its own host name.
        conn.request("GET", "/", headers={"Host": f"evil.example:{self.server.port}"})
        r = conn.getresponse()
        r.read()
        self.assertEqual(r.status, 421)

    def test_api_needs_token_and_host(self):
        self.assertEqual(self.call("state", token="wrong")[0], 403)
        self.assertEqual(self.call("state", token="")[0], 403)
        self.assertEqual(self.call("state", host=f"evil.example:{self.server.port}")[0], 403)
        self.assertEqual(self.call("nonsense")[0], 400)

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_state_shows_qr_and_settings(self):
        status, state = self.call("state")
        self.assertEqual(status, 200)
        self.assertTrue(state["url"].startswith(f"http://{self.rt.ip}:{self.rt.port}/#k="))
        self.assertIn("<svg", state["qr"])
        self.assertIsNone(state["device"])
        self.assertEqual((state["https"]["on"], state["version"]), (False, "9.9"))

    def test_approval_from_the_panel(self):
        result = {}
        thread = threading.Thread(target=lambda: result.update(ok=self.panel.approve("Pixel (Chrome)", "123456", 10)))
        with mock.patch.object(hostui.webbrowser, "open"):
            thread.start()
            for _ in range(100):
                state = self.call("state")[1]
                if state["pending"]:
                    break
                time.sleep(0.02)
        self.assertEqual((state["pending"]["name"], state["pending"]["code"]), ("Pixel (Chrome)", "123456"))
        self.assertEqual(self.call("answer", {"allow": True})[1], {"ok": True})
        thread.join(5)
        self.assertTrue(result["ok"])
        self.assertIsNone(self.call("state")[1]["pending"])
        self.assertIn("Paired with Pixel (Chrome).", [e["text"] for e in self.call("state")[1]["log"]])

    def test_unanswered_request_times_out_refused(self):
        with mock.patch.object(hostui.webbrowser, "open") as opened:
            self.panel.url = "http://127.0.0.1:1/#t=x"
            self.assertFalse(self.panel.approve("Phone", "000000", 0.05))
        opened.assert_called_once()   # nobody was watching the panel, so it was brought up

    def test_switches_are_saved(self):
        self.call("screen", {"on": False})
        self.assertFalse(self.rt.screen.enabled)
        self.assertFalse(Settings(self.dir / "settings.json")["screen"])
        with mock.patch("phoneremote.runtime.config_dir", return_value=self.dir):
            status, reply = self.call("https", {"on": True})
        self.assertEqual((status, reply["ok"]), (200, True))
        state = self.call("state")[1]
        self.assertTrue(state["url"].startswith("https://"))
        self.assertTrue(state["https"]["fingerprint"])
        self.assertTrue(Settings(self.dir / "settings.json")["https"])
        self.assertEqual(self.call("address", {"ip": "203.0.113.9"})[0], 400)

    def test_internet_relay_qr_and_switch(self):
        from test_relay import FakeRelay, wait_for

        fake = FakeRelay()
        self.addCleanup(fake.close)
        self.panel.relay_url = fake.url
        with mock.patch("phoneremote.runtime.config_dir", return_value=self.dir):
            self.rt.set_relay(fake.url)
            self.rt.start()
            self.addCleanup(self.rt.close)
            self.assertTrue(wait_for(lambda: self.call("state")[1]["relay"]["state"] == "online"))
            relay_state = self.call("state")[1]["relay"]
            self.assertTrue(relay_state["url"].startswith(f"{fake.url}/r/{self.rt.relay.room}/#k="))
            self.assertIn("<svg", relay_state["qr"])
            # Both codes carry the same one-time pairing key.
            self.assertEqual(relay_state["url"].split("#")[1], self.call("state")[1]["url"].split("#")[1])
            self.call("relay", {"on": False})
            state = self.call("state")[1]["relay"]
            self.assertEqual((state["enabled"], state["state"], state["url"]), (False, "off", None))
            self.assertFalse(Settings(self.dir / "settings.json")["relay"])
            self.call("relay", {"on": True})
            self.assertTrue(wait_for(lambda: self.call("state")[1]["relay"]["state"] == "online"))
        self.assertTrue((self.dir / "relay.json").exists())   # the room secret, kept for next time

    def test_second_launch_finds_the_running_app(self):
        path = self.dir / "panel.json"
        self.assertIsNone(hostui.existing_panel(path))
        hostui.remember_panel(path, self.server)
        self.assertEqual(hostui.existing_panel(path), self.panel.url)
        path.write_text(json.dumps({"port": self.server.port, "token": "stale"}))
        self.assertIsNone(hostui.existing_panel(path))

    def test_quit(self):
        self.assertEqual(self.call("quit")[1], {"ok": True})
        self.assertTrue(self.panel.quit.is_set())


class AppEntryTest(unittest.TestCase):
    def run_entry(self, argv, tty):
        stdin = mock.Mock()
        stdin.isatty.return_value = tty
        with mock.patch.object(cli.sys, "argv", ["PhoneRemote"] + argv), \
             mock.patch.object(cli.sys, "stdin", stdin), mock.patch.object(cli, "main") as main:
            cli.app_main()
        return main.call_args[0][0]

    def test_icon_launch_runs_the_app_and_terminal_launch_the_cli(self):
        self.assertEqual(self.run_entry([], tty=False), ["--app"])
        self.assertEqual(self.run_entry(["-psn_0_12345"], tty=False), ["--app"])
        self.assertEqual(self.run_entry([], tty=True), [])
        self.assertEqual(self.run_entry(["--https"], tty=False), ["--https"])


if __name__ == "__main__":
    unittest.main()
