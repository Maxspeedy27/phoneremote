"""Named actions the phone may trigger, mapped to this OS's key combinations.

The phone only sends these names, never raw key names, so it can't press
arbitrary key combinations. Key names follow pyautogui's spelling; the uinput
backend translates them to Linux keycodes.
"""

from .system import IS_MAC, MOD

SHORTCUTS = {
    # Slides. On macOS "start" is PowerPoint for Mac's shortcut; Keynote uses
    # ("option", "command", "p").
    "next": ("right",),
    "prev": ("left",),
    "start": ("command", "shift", "enter") if IS_MAC else ("f5",),
    "exit": ("esc",),
    "blank": ("b",),
    "white": ("w",),
    "first": ("home",),
    "last": ("end",),
    # Browser / websites
    "back": ("command", "[") if IS_MAC else ("alt", "left"),
    "pageup": ("pageup",),
    "pagedown": ("pagedown",),
    "fullscreen": ("ctrl", "command", "f") if IS_MAC else ("f11",),
    "zoomin": (MOD, "="),
    "zoomout": (MOD, "-"),
    "zoomreset": (MOD, "0"),
    # Media and volume. pyautogui spells these names; the backends turn them
    # into the OS's media keys.
    "playpause": ("playpause",),
    "nexttrack": ("nexttrack",),
    "prevtrack": ("prevtrack",),
    "volumeup": ("volumeup",),
    "volumedown": ("volumedown",),
    "volumemute": ("volumemute",),
    "space": ("space",),   # play/pause in video players and YouTube
    # Typing
    "enter": ("enter",),
    "backspace": ("backspace",),
}
