import tempfile
import time
import unittest
from pathlib import Path

from kumpas.blanker import Blanker
from kumpas.commands import run_ops

from helpers import FakeBackend

LINEAR = [[0, 32767, 65535]] * 3


class FakeGamma:
    """Stands in for the X server's displays."""

    def __init__(self, displays):
        self._displays = displays          # [(crtc, name)]
        self.ramps = {c: [list(r) for r in LINEAR] for c, _ in displays}
        self.sets = 0

    def displays(self):
        return list(self._displays)

    def get(self, crtc):
        return [list(r) for r in self.ramps[crtc]]

    def set(self, crtc, ramps):
        self.sets += 1
        self.ramps[crtc] = [list(r) for r in ramps]


class BlankerTest(unittest.TestCase):
    def make(self, displays, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "blank-gamma.json"
        gamma = FakeGamma(displays)
        blanker = Blanker(gamma=gamma, state_file=self.state, **kwargs)
        self.addCleanup(blanker.close)
        return blanker, gamma

    def test_black_then_black_again_restores(self):
        b, g = self.make([(1, "eDP-1")])
        self.assertEqual(b.toggle("black"), "black")
        self.assertEqual(g.ramps[1], [[0, 0, 0]] * 3)
        self.assertTrue(self.state.exists())
        self.assertIsNone(b.toggle("black"))
        self.assertEqual(g.ramps[1], LINEAR)
        self.assertFalse(self.state.exists())

    def test_white_and_switching_between_black_and_white(self):
        b, g = self.make([(1, "eDP-1")])
        b.toggle("white")
        self.assertEqual(g.ramps[1], [[65535] * 3] * 3)
        self.assertEqual(b.toggle("black"), "black")   # straight to black, not back on
        self.assertEqual(g.ramps[1], [[0] * 3] * 3)
        b.toggle("black")
        self.assertEqual(g.ramps[1], LINEAR)           # the original, not the white ramp

    def test_only_the_projector_is_blanked_when_one_is_connected(self):
        b, g = self.make([(1, "eDP-1"), (2, "HDMI-1")])
        b.toggle("black")
        self.assertEqual(g.ramps[1], LINEAR)           # laptop panel stays visible
        self.assertEqual(g.ramps[2], [[0] * 3] * 3)

    def test_a_crash_while_blanked_is_undone_on_the_next_start(self):
        b, g = self.make([(1, "HDMI-1")])
        b.toggle("black")
        b2 = Blanker(gamma=g, state_file=self.state)   # the next run
        self.assertEqual(g.ramps[1], LINEAR)
        self.assertFalse(self.state.exists())
        self.assertIsNone(b2.mode)

    def test_blank_is_kept_up_if_something_rewrites_the_ramp(self):
        b, g = self.make([(1, "eDP-1")], reapply_seconds=0.01)
        b.toggle("black")
        g.ramps[1] = [list(r) for r in LINEAR]          # e.g. Night Light
        deadline = time.monotonic() + 5
        while g.ramps[1] != [[0] * 3] * 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(g.ramps[1], [[0] * 3] * 3)

    def test_unavailable_without_a_display(self):
        b = Blanker(gamma=None, state_file=Path("/nonexistent/x"))
        b.gamma = None
        self.assertFalse(b.available)


class CommandTest(unittest.TestCase):
    def test_black_and_white_buttons_use_the_blanker_instead_of_keys(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        backend, gamma = FakeBackend(), FakeGamma([(1, "eDP-1")])
        blanker = Blanker(gamma=gamma, state_file=Path(tmp.name) / "s.json")
        self.addCleanup(blanker.close)
        run_ops(backend, [{"a": "key", "k": "blank"}, {"a": "key", "k": "next"}], blanker=blanker)
        self.assertEqual(backend.calls, [("hotkey", "right")])   # B never reaches the slideshow
        self.assertEqual(blanker.mode, "black")
        run_ops(backend, [{"a": "key", "k": "white"}], blanker=blanker)
        self.assertEqual(blanker.mode, "white")

    def test_falls_back_to_the_slideshow_keys(self):
        backend = FakeBackend()
        unavailable = Blanker(gamma=None, state_file=Path("/nonexistent/x"))
        unavailable.gamma = None
        for blanker in (None, unavailable):
            run_ops(backend, [{"a": "key", "k": "blank"}, {"a": "key", "k": "white"}], blanker=blanker)
        self.assertEqual(backend.calls, [("hotkey", "b"), ("hotkey", "w")] * 2)


if __name__ == "__main__":
    unittest.main()
