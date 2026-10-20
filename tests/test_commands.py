import unittest

from phoneremote.commands import MAX_MOVE, MAX_OPS, run_ops
from phoneremote.shortcuts import SHORTCUTS

from helpers import FakeBackend


class CommandsTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()

    def run_ok(self, *ops):
        run_ops(self.backend, list(ops))
        return self.backend.calls

    def test_move_scroll_click_key_type(self):
        calls = self.run_ok(
            {"a": "move", "dx": 5, "dy": -3},
            {"a": "move", "dx": 0, "dy": 0},
            {"a": "scroll", "dy": 12.5},
            {"a": "click", "b": "right"},
            {"a": "key", "k": "next"},
            {"a": "type", "s": "hi"},
        )
        self.assertEqual(calls, [
            ("move", 5, -3), ("scroll", 12.5), ("click", "right"),
            ("hotkey",) + SHORTCUTS["next"], ("type", "hi"),
        ])

    def test_moves_are_clamped(self):
        self.assertEqual(self.run_ok({"a": "move", "dx": 10**9, "dy": -10**9}),
                         [("move", MAX_MOVE, -MAX_MOVE)])

    def test_hold_then_click_releases_first(self):
        calls = self.run_ok({"a": "down"}, {"a": "down"}, {"a": "click", "b": "left"}, {"a": "up"})
        self.assertEqual(calls, [("button", "left", True), ("button", "left", False), ("click", "left")])

    def test_invalid_operations_rejected(self):
        bad = [
            "x", {"a": "explode"}, {"a": "key", "k": "rm -rf"}, {"a": "key", "k": "__class__"},
            {"a": "click", "b": "middle"}, {"a": "move", "dx": "5", "dy": 0},
            {"a": "move", "dx": True, "dy": 0}, {"a": "move", "dx": float("nan"), "dy": 0},
            {"a": "type", "s": 5}, {"a": "type", "s": "x" * 5000},
        ]
        for op in bad:
            with self.subTest(op=op), self.assertRaises(ValueError):
                run_ops(FakeBackend(), [op])

    def test_ops_must_be_a_bounded_list(self):
        for ops in (None, {}, "abc", [{"a": "up"}] * (MAX_OPS + 1)):
            with self.subTest(ops=type(ops)), self.assertRaises(ValueError):
                run_ops(self.backend, ops)


if __name__ == "__main__":
    unittest.main()
