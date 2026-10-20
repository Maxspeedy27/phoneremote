import sys
import time

from ..system import IS_MAC, IS_WIN, MOD
from .base import Backend


class PyAutoGuiBackend(Backend):
    """Windows, macOS and Linux on X11."""

    name = "pyautogui"

    # pyautogui.scroll() units differ per OS. The phone sends finger travel in
    # CSS pixels; this converts to native units (positive = scroll up).
    #   Windows: raw wheel delta, 120 = one notch (~100 px in a browser)
    #   macOS:   lines
    #   Linux:   whole wheel notches (button 4/5 clicks, ~50 px each)
    if IS_WIN:
        SCROLL_UNITS_PER_PX = 1.2
    elif IS_MAC:
        SCROLL_UNITS_PER_PX = 0.1
    else:
        SCROLL_UNITS_PER_PX = 0.025

    def __init__(self):
        # pyautogui imports mouseinfo (a GUI helper we don't use), which calls
        # sys.exit() on Linux when tkinter is missing. Blocking it makes
        # pyautogui skip it cleanly.
        sys.modules.setdefault("mouseinfo", None)
        try:
            import pyautogui
        except Exception as exc:  # ImportError, or Xlib errors when there is no display
            raise RuntimeError(
                f"Could not load pyautogui: {exc}\n"
                "Install it with:  pip install pyautogui\n"
                "Linux: pyautogui needs an X11 desktop session; under Wayland use --backend uinput."
            ) from exc
        pyautogui.PAUSE = 0          # no artificial delay after every call
        pyautogui.FAILSAFE = False   # don't abort when the cursor reaches a corner
        self.gui = pyautogui
        self.scroll_acc = 0.0        # fractional scroll units not yet sent

    def move(self, dx, dy):
        if IS_MAC and self.holding:
            # On macOS a plain "mouse moved" event doesn't drag; send "dragged" events.
            x, y = self.gui.position()
            self.gui.platformModule._dragTo(x + dx, y + dy, "left")
        else:
            self.gui.moveRel(dx, dy, duration=0)

    def scroll(self, px):
        self.scroll_acc += px * self.SCROLL_UNITS_PER_PX
        units = int(self.scroll_acc)
        if units:
            self.scroll_acc -= units
            self.gui.scroll(units)

    def button(self, name, down):
        (self.gui.mouseDown if down else self.gui.mouseUp)(button=name)

    def click(self, name):
        self.gui.click(button=name)

    def hotkey(self, *keys):
        self.gui.hotkey(*keys)

    def type_text(self, text):
        if all(32 <= ord(c) < 127 or c in "\n\t" for c in text):
            self.gui.write(text, interval=0)
            return
        # pyautogui.write silently drops non-ASCII characters, so paste instead.
        try:
            import pyperclip  # installed as a pyautogui dependency
            previous = pyperclip.paste()
            pyperclip.copy(text)
            self.gui.hotkey(MOD, "v")
            time.sleep(0.15)
            pyperclip.copy(previous)
        except Exception as exc:
            raise ValueError(f"can't type non-ASCII text ({exc})") from exc
