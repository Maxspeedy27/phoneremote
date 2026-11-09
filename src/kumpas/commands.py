"""Validating the phone's operations and applying them to an input backend."""

from .shortcuts import SHORTCUTS

MAX_OPS = 200
MAX_MOVE = 4000
MAX_TEXT = 2000


def _number(value, limit):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise ValueError("expected a number")
    return max(-limit, min(limit, value))


def _fraction(value):
    return max(0.0, min(1.0, float(_number(value, 1))))


def run_op(backend, op, screen=None):
    if not isinstance(op, dict):
        raise ValueError("bad operation")
    action = op.get("a")
    if action == "abs":
        # Touchscreen mode: put the pointer where the phone's picture of the
        # screen was touched, given as fractions of that monitor.
        if screen is None:
            raise ValueError("Touch control needs the screen view, which is turned off on the laptop.")
        x, y = screen.point(op.get("m"), _fraction(op.get("x")), _fraction(op.get("y")))
        backend.move_to(x, y)
    elif action == "move":
        dx = int(_number(op.get("dx"), MAX_MOVE))
        dy = int(_number(op.get("dy"), MAX_MOVE))
        if dx or dy:
            backend.move(dx, dy)
    elif action == "scroll":
        backend.scroll(_number(op.get("dy"), MAX_MOVE))
    elif action == "click":
        button = op.get("b")
        if button not in ("left", "right"):
            raise ValueError("bad button")
        backend.mouse_up()
        backend.click(button)
    elif action == "down":
        backend.mouse_down()
    elif action == "up":
        backend.mouse_up()
    elif action == "key":
        combo = SHORTCUTS.get(op.get("k"))
        if combo is None:
            raise ValueError("unknown key")
        backend.hotkey(*combo)
    elif action == "type":
        text = op.get("s")
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError("bad text")
        if text:
            backend.type_text(text)
    else:
        raise ValueError("unknown action")


def run_ops(backend, ops, screen=None):
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise ValueError("ops must be a list")
    for op in ops:
        run_op(backend, op, screen)
