import struct
import unittest

from kumpas.backends.uinput import UinputBackend, us_keymap
from kumpas.shortcuts import SHORTCUTS


def ioc(direction, size, nr):
    """_IOC() from linux/ioctl.h for the uinput ('U') ioctl type."""
    return (direction << 30) | (size << 16) | (ord("U") << 8) | nr


class UinputTablesTest(unittest.TestCase):
    """Checks the hand-copied kernel constants without opening /dev/uinput."""

    def test_ioctl_numbers_match_kernel_formula(self):
        B = UinputBackend
        self.assertEqual(B.UI_SET_EVBIT, ioc(1, 4, 100))
        self.assertEqual(B.UI_SET_KEYBIT, ioc(1, 4, 101))
        self.assertEqual(B.UI_SET_RELBIT, ioc(1, 4, 102))
        self.assertEqual(B.UI_DEV_SETUP, ioc(1, B.SETUP.size, 3))
        self.assertEqual(B.UI_DEV_CREATE, ioc(0, 0, 1))
        self.assertEqual(B.UI_DEV_DESTROY, ioc(0, 0, 2))

    def test_struct_sizes(self):
        self.assertEqual(UinputBackend.SETUP.size, 92)
        self.assertEqual(UinputBackend.EVENT.size, 2 * struct.calcsize("l") + 8)

    def test_every_shortcut_has_a_keycode(self):
        # Only checks Linux key names; on macOS SHORTCUTS uses "command".
        for name, combo in SHORTCUTS.items():
            if "command" in combo:
                continue
            with self.subTest(name=name):
                for key in combo:
                    UinputBackend.keycode(key)

    def test_us_keymap(self):
        table = us_keymap()
        self.assertEqual(table["a"], (30, False))
        self.assertEqual(table["A"], (30, True))
        self.assertEqual(table["/"], (53, False))
        self.assertEqual(table["?"], (53, True))
        self.assertEqual(table["\n"], (28, False))
        printable = {chr(c) for c in range(32, 127)}
        self.assertEqual(printable - set(table), set())

    def test_shifted_characters_are_not_bare_keys(self):
        with self.assertRaises(ValueError):
            UinputBackend.keycode("A")


if __name__ == "__main__":
    unittest.main()
