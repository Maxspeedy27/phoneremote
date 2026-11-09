import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kumpas import system


class ConfigDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.current, self.old = base / "kumpas", base / "phoneremote"
        patcher = mock.patch.object(system, "_config_dirs", return_value=(self.current, self.old))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_moves_settings_from_before_the_rename(self):
        self.old.mkdir()
        (self.old / "device.json").write_text("{}")
        self.assertEqual(system.config_dir(), self.current)
        self.assertTrue((self.current / "device.json").exists())
        self.assertFalse(self.old.exists())

    def test_keeps_current_folder_when_both_exist(self):
        self.old.mkdir()
        self.current.mkdir()
        self.assertEqual(system.config_dir(), self.current)
        self.assertTrue(self.old.exists())

    def test_fresh_install(self):
        self.assertEqual(system.config_dir(), self.current)
        self.assertFalse(self.current.exists())


if __name__ == "__main__":
    unittest.main()
