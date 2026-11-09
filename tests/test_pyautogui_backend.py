import unittest
from unittest import mock

from phoneremote.backends import pyautogui_backend as pb
from phoneremote.shortcuts import SHORTCUTS


class FakeGui:
    """Records what the backend asks pyautogui to do, without a display."""

    def __init__(self):
        self.calls = []
        self.platformModule = self

    def hotkey(self, *keys):
        self.calls.append(("hotkey",) + keys)

    def _specialKeyEvent(self, key, up_down):
        self.calls.append(("special", key, up_down))


def make_backend():
    backend = object.__new__(pb.PyAutoGuiBackend)   # skip importing pyautogui
    backend.gui = FakeGui()
    return backend


class MediaKeysTest(unittest.TestCase):
    MEDIA = {"playpause", "nexttrack", "prevtrack", "volumeup", "volumedown", "volumemute"}

    def test_every_media_shortcut_is_mapped(self):
        for name in self.MEDIA:
            with self.subTest(name=name):
                (key,) = SHORTCUTS[name]
                self.assertIn(key, pb.MEDIA_KEYS)

    def test_windows_uses_pyautogui_hotkey(self):
        backend = make_backend()
        with mock.patch.object(pb, "IS_WIN", True), mock.patch.object(pb, "IS_MAC", False):
            backend.hotkey("playpause")
        self.assertEqual(backend.gui.calls, [("hotkey", "playpause")])

    def test_macos_sends_system_defined_events(self):
        backend = make_backend()
        with mock.patch.object(pb, "IS_WIN", False), mock.patch.object(pb, "IS_MAC", True):
            backend.hotkey("volumeup")
        self.assertEqual(backend.gui.calls, [
            ("special", "KEYTYPE_SOUND_UP", "down"),
            ("special", "KEYTYPE_SOUND_UP", "up"),
        ])

    def test_ordinary_keys_still_use_hotkey(self):
        backend = make_backend()
        with mock.patch.object(pb, "IS_WIN", False), mock.patch.object(pb, "IS_MAC", True):
            backend.hotkey("ctrl", "=")
            backend.hotkey("w")
        self.assertEqual(backend.gui.calls, [("hotkey", "ctrl", "="), ("hotkey", "w")])


if __name__ == "__main__":
    unittest.main()
