import sys
import time

from ..system import IS_MAC, IS_WIN, MOD
from .base import Backend

# pyautogui media key name -> (macOS system-defined key, X11 XF86 keysym)
MEDIA_KEYS = {
    "playpause": ("KEYTYPE_PLAY", 0x1008FF14),        # XF86AudioPlay
    "nexttrack": ("KEYTYPE_NEXT", 0x1008FF17),        # XF86AudioNext
    "prevtrack": ("KEYTYPE_PREVIOUS", 0x1008FF16),    # XF86AudioPrev
    "volumeup": ("KEYTYPE_SOUND_UP", 0x1008FF13),     # XF86AudioRaiseVolume
    "volumedown": ("KEYTYPE_SOUND_DOWN", 0x1008FF11), # XF86AudioLowerVolume
    "volumemute": ("KEYTYPE_MUTE", 0x1008FF12),       # XF86AudioMute
}


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
        if len(keys) == 1 and keys[0] in MEDIA_KEYS and not IS_WIN:
            self._media_key(keys[0])
        else:
            self.gui.hotkey(*keys)

    def _media_key(self, name):
        # pyautogui.hotkey() handles media keys on Windows only. On macOS they
        # are "system-defined" events that its keyDown() rejects, and on X11
        # it has no mapping for them, so send them the native way here.
        mac_name, x11_keysym = MEDIA_KEYS[name]
        platform = self.gui.platformModule
        if IS_MAC:
            platform._specialKeyEvent(mac_name, "down")
            platform._specialKeyEvent(mac_name, "up")
            return
        from Xlib import X
        from Xlib.ext.xtest import fake_input

        display = platform._display
        keycode = display.keysym_to_keycode(x11_keysym)
        if not keycode:
            raise ValueError(f"this X11 keyboard map has no {name} key")
        fake_input(display, X.KeyPress, keycode)
        fake_input(display, X.KeyRelease, keycode)
        display.sync()

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
