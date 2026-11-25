import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kumpas import cli
from kumpas.runtime import Settings

BUILT_IN = "https://relay.test"


class RelayIsOptInTest(unittest.TestCase):
    """Nothing leaves the local network unless the user turns the relay on."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.settings = Settings(Path(tmp.name) / "settings.json")
        patcher = mock.patch("kumpas.relay.DEFAULT_RELAY_URL", BUILT_IN)
        patcher.start()
        self.addCleanup(patcher.stop)

    def relay(self, *argv, settings=None):
        return cli.relay_url(cli.parse_args(list(argv)), settings)

    def test_off_by_default_even_with_a_built_in_relay(self):
        self.assertIsNone(self.relay())
        self.assertFalse(self.settings["relay"])
        self.assertIsNone(self.relay("--app", settings=self.settings))

    def test_terminal_turns_it_on_with_the_flag(self):
        self.assertEqual(self.relay("--relay"), BUILT_IN)
        self.assertEqual(self.relay("--relay", "https://mine.example"), "https://mine.example")
        self.assertIsNone(self.relay("--relay", "--no-relay"))

    def test_panel_switch_turns_it_on(self):
        self.settings["relay"] = True
        self.assertEqual(self.relay("--app", settings=self.settings), BUILT_IN)
        self.settings["relay_url"] = "https://saved.example"
        self.assertEqual(self.relay("--app", settings=self.settings), "https://saved.example")
        self.assertIsNone(self.relay("--app", "--no-relay", settings=self.settings))

    def test_flag_overrides_the_panel_switch(self):
        self.assertEqual(self.relay("--app", "--relay", "https://mine.example", settings=self.settings),
                         "https://mine.example")

    def test_nothing_to_connect_to_without_any_relay(self):
        with mock.patch("kumpas.relay.DEFAULT_RELAY_URL", ""):
            self.assertIsNone(self.relay("--relay"))


if __name__ == "__main__":
    unittest.main()
