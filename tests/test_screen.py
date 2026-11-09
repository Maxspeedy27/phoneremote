import io
import types
import unittest
from unittest import mock

from PIL import Image

from kumpas import screen


class FakeShot:
    def __init__(self, width, height):
        self.size = (width, height)
        self.bgra = bytes([0, 0, 255, 0]) * (width * height)   # pure red in BGRX


class FakeMss:
    def __init__(self, monitors):
        self.monitors = monitors
        self.grabbed = []

    def grab(self, monitor):
        self.grabbed.append(monitor)
        return FakeShot(monitor["width"], monitor["height"])


ONE = [{"left": 0, "top": 0, "width": 1920, "height": 1080}] * 2
TWO = [{"left": 0, "top": 0, "width": 3200, "height": 1080},
       {"left": 0, "top": 0, "width": 1920, "height": 1080},
       {"left": 1920, "top": 0, "width": 1280, "height": 720}]


class ScreenGrabberTest(unittest.TestCase):
    def grabber(self, monitors=ONE):
        g = screen.ScreenGrabber()
        fake = FakeMss(monitors)
        patches = [mock.patch.object(screen, "IS_WAYLAND", False),
                   mock.patch.object(screen, "_open_mss", lambda: fake)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return g, fake

    def test_jpeg_is_scaled_to_requested_width(self):
        g, _ = self.grabber()
        jpeg, monitor, count, _ = g.grab(1, 640)
        image = Image.open(io.BytesIO(jpeg))
        self.assertEqual((image.format, image.size, monitor, count), ("JPEG", (640, 360), 1, 1))
        r, gr, b = image.getpixel((10, 10))
        self.assertGreater(r, 200)   # colour channels in the right order
        self.assertLess(b, 60)

    def test_width_is_clamped_and_monitor_checked(self):
        g, fake = self.grabber(TWO)
        jpeg, monitor, count, _ = g.grab(7, 99999)
        self.assertEqual((monitor, count), (1, 2))   # unknown monitor falls back to the first
        self.assertEqual(Image.open(io.BytesIO(jpeg)).width, screen.MAX_WIDTH)
        g._cache = None
        _, monitor, _, _ = g.grab(0, 100)               # 0 = all screens together
        self.assertEqual((monitor, fake.grabbed[-1]["width"]), (0, 3200))
        for bad in ("1", True, 1.5, None):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                g.grab(bad, 640)

    def test_repeated_requests_reuse_a_fresh_frame(self):
        g, fake = self.grabber()
        g.grab(1, 640)
        g.grab(1, 640)
        self.assertEqual(len(fake.grabbed), 1)
        self.assertTrue(g.viewing)

    def test_cursor_position_and_touch_points(self):
        g, _ = self.grabber(TWO)
        with mock.patch.object(g, "_cursor_position", return_value=(1920 + 640, 360)):
            *_, cursor = g.grab(2, 640)
            self.assertEqual(cursor, [round(640 / 1279, 4), round(360 / 719, 4)])
            g._cache = None
            *_, cursor = g.grab(1, 640)
            self.assertIsNone(cursor)   # the pointer is on the other monitor
        # Fractions of a monitor map back to screen coordinates, offset included.
        self.assertEqual(g.point(2, 0, 0), (1920, 0))
        self.assertEqual(g.point(2, 1, 1), (1920 + 1279, 719))
        self.assertEqual(g.point(1, 0.5, 0.5), (960, 540))
        with self.assertRaises(ValueError):
            g.point(5, 0.5, 0.5)
        with mock.patch.object(g, "_cursor_position", return_value=None):
            self.assertIsNone(g.grab(1, 640)[3])

    def test_cursor_poll_between_frames(self):
        g, fake = self.grabber(TWO)
        with self.assertRaises(screen.ScreenUnavailable):
            g.cursor(1)                       # no frame yet: monitor layout unknown
        g.grab(1, 640)
        with mock.patch.object(g, "_cursor_position", return_value=(959.5, 539.5)):
            self.assertEqual(g.cursor(1), [round(959.5 / 1919, 4), round(539.5 / 1079, 4)])
            self.assertIsNone(g.cursor(2))
        self.assertEqual(len(fake.grabbed), 1)   # polls never capture the screen
        g.enabled = False
        with self.assertRaises(screen.ScreenUnavailable):
            g.cursor(1)

    def test_touch_points_need_the_screen_view(self):
        g = screen.ScreenGrabber()
        with self.assertRaises(ValueError):
            g.point(1, 0.5, 0.5)       # no frame yet: no monitor layout
        g, _ = self.grabber()
        g.grab(1, 640)
        g.enabled = False
        with self.assertRaises(ValueError):
            g.point(1, 0.5, 0.5)

    def test_unavailable_when_disabled_or_on_wayland(self):
        g = screen.ScreenGrabber(enabled=False)
        with self.assertRaises(screen.ScreenUnavailable):
            g.grab(1, 640)
        with mock.patch.object(screen, "IS_WAYLAND", True):
            reason = screen.ScreenGrabber().unavailable_reason()
        self.assertIn("Wayland", reason)
        self.assertFalse(screen.ScreenGrabber().viewing)

    def test_macos_without_permission_asks_once_the_phone_looks(self):
        asked = []

        def allowed(ask=False):
            asked.append(ask)
            return False

        with mock.patch.object(screen, "IS_WAYLAND", False), mock.patch.object(screen, "IS_MAC", True), \
             mock.patch.object(screen, "mac_screen_capture_allowed", allowed):
            self.assertIn("Screen Recording", screen.ScreenGrabber().unavailable_reason())
            self.assertEqual(asked, [False])   # the panel's check never pops up the prompt
            with self.assertRaises(screen.ScreenUnavailable):
                screen.ScreenGrabber().grab(1, 640)
        self.assertEqual(asked, [False, True])

    def test_capture_failure_becomes_unavailable(self):
        g = screen.ScreenGrabber()
        broken = types.SimpleNamespace(monitors=ONE, grab=mock.Mock(side_effect=OSError("no display")))
        with mock.patch.object(screen, "IS_WAYLAND", False), mock.patch.object(screen, "_open_mss", lambda: broken):
            with self.assertRaises(screen.ScreenUnavailable) as ctx:
                g.grab(1, 640)
        self.assertIn("no display", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
