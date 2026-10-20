import os
import shutil
import struct
import subprocess
import time

from .base import Backend

SETUP_HELP = """\
No permission to use /dev/uinput, which is needed to control the desktop under Wayland.
Run these once to let the logged-in user create virtual input devices:

  echo 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' | sudo tee /etc/udev/rules.d/60-phone-remote-uinput.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger --name-match=uinput

Then start Phone Remote again. (Alternatively log in to an X11/Xorg session.)"""


def us_keymap():
    """Character -> (Linux keycode, needs Shift) for a US keyboard layout."""
    table = {" ": (57, False), "\n": (28, False), "\t": (15, False)}
    rows = [
        (2, "1234567890-=", "!@#$%^&*()_+"),
        (16, "qwertyuiop[]", "QWERTYUIOP{}"),
        (30, "asdfghjkl;'`", 'ASDFGHJKL:"~'),
        (43, "\\zxcvbnm,./", "|ZXCVBNM<>?"),
    ]
    for first_code, plain, shifted in rows:
        for offset, (p, s) in enumerate(zip(plain, shifted)):
            table[p] = (first_code + offset, False)
            table[s] = (first_code + offset, True)
    return table


class UinputBackend(Backend):
    """Linux virtual keyboard + mouse created through /dev/uinput.

    The kernel presents it like a real USB device, so it works under Wayland
    (which ignores pyautogui's X11 input) as well as X11. Typing assumes a US
    keyboard layout.
    """

    name = "uinput (virtual keyboard + mouse)"

    # From linux/input-event-codes.h and linux/uinput.h
    EV_SYN, EV_KEY, EV_REL = 0x00, 0x01, 0x02
    SYN_REPORT = 0
    REL_X, REL_Y, REL_WHEEL, REL_WHEEL_HI_RES = 0x00, 0x01, 0x08, 0x0B
    UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
    UI_DEV_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x5501, 0x5502
    SETUP = struct.Struct("HHHH80sI")  # struct uinput_setup: input_id, name[80], ff_effects_max
    EVENT = struct.Struct("llHHi")     # struct input_event: timeval, type, code, value
    BUTTONS = {"left": 0x110, "right": 0x111, "middle": 0x112}
    KEYS = {
        "esc": 1, "backspace": 14, "tab": 15, "enter": 28, "ctrl": 29, "shift": 42,
        "alt": 56, "space": 57, "f5": 63, "f11": 87, "home": 102, "up": 103,
        "pageup": 104, "left": 105, "right": 106, "end": 107, "down": 108,
        "pagedown": 109, "delete": 111,
    }
    CHARS = us_keymap()

    # High-resolution wheel: 120 units = one notch, about 50 px in a browser.
    HI_RES_PER_NOTCH = 120
    WHEEL_UNITS_PER_PX = 2.4

    def __init__(self):
        import fcntl  # Unix-only, so imported here rather than at the top

        self.ioctl = fcntl.ioctl
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        try:
            self.ioctl(self.fd, self.UI_SET_EVBIT, self.EV_KEY)
            self.ioctl(self.fd, self.UI_SET_EVBIT, self.EV_REL)
            key_codes = (set(self.KEYS.values()) | set(self.BUTTONS.values())
                         | {code for code, _ in self.CHARS.values()})
            for code in sorted(key_codes):
                self.ioctl(self.fd, self.UI_SET_KEYBIT, code)
            for code in (self.REL_X, self.REL_Y, self.REL_WHEEL, self.REL_WHEEL_HI_RES):
                self.ioctl(self.fd, self.UI_SET_RELBIT, code)
            # bustype USB, vendor/product ids from the pid.codes open-source range
            setup = self.SETUP.pack(0x03, 0x1209, 0x7072, 1, b"Phone Remote", 0)
            self.ioctl(self.fd, self.UI_DEV_SETUP, setup)
            self.ioctl(self.fd, self.UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise
        self.wheel_acc = 0.0   # fractional hi-res wheel units not yet sent
        self.notch_acc = 0     # hi-res units not yet reported as a whole notch
        time.sleep(0.5)        # give the desktop a moment to pick up the new device

    def _emit(self, *events):
        data = b"".join(self.EVENT.pack(0, 0, type_, code, value) for type_, code, value in events)
        os.write(self.fd, data + self.EVENT.pack(0, 0, self.EV_SYN, self.SYN_REPORT, 0))

    def _key(self, code, down):
        self._emit((self.EV_KEY, code, 1 if down else 0))

    @classmethod
    def keycode(cls, name):
        if name in cls.KEYS:
            return cls.KEYS[name]
        code, shifted = cls.CHARS.get(name, (None, True))
        if code is None or shifted:
            raise ValueError(f"no key for {name!r}")
        return code

    def move(self, dx, dy):
        self._emit((self.EV_REL, self.REL_X, dx), (self.EV_REL, self.REL_Y, dy))

    def scroll(self, px):
        self.wheel_acc += px * self.WHEEL_UNITS_PER_PX
        hi_res = int(self.wheel_acc)
        if not hi_res:
            return
        self.wheel_acc -= hi_res
        # Real smooth-scrolling mice report both axes: hi-res units every time,
        # plus a classic notch whenever 120 hi-res units have accumulated.
        self.notch_acc += hi_res
        notches = int(self.notch_acc / self.HI_RES_PER_NOTCH)
        self.notch_acc -= notches * self.HI_RES_PER_NOTCH
        events = [(self.EV_REL, self.REL_WHEEL_HI_RES, hi_res)]
        if notches:
            events.append((self.EV_REL, self.REL_WHEEL, notches))
        self._emit(*events)

    def button(self, name, down):
        self._key(self.BUTTONS[name], down)

    def click(self, name):
        self.button(name, True)
        self.button(name, False)

    def hotkey(self, *keys):
        codes = [self.keycode(k) for k in keys]
        for code in codes:
            self._key(code, True)
        time.sleep(0.01)
        for code in reversed(codes):
            self._key(code, False)

    def type_text(self, text):
        if any(c not in self.CHARS for c in text):
            return self._paste(text)
        shift = self.KEYS["shift"]
        for ch in text:
            code, shifted = self.CHARS[ch]
            if shifted:
                self._key(shift, True)
            self._key(code, True)
            self._key(code, False)
            if shifted:
                self._key(shift, False)
            time.sleep(0.002)

    def _paste(self, text):
        # Characters with no key on a US layout (accents, emoji) go via the clipboard.
        if not shutil.which("wl-copy"):
            raise ValueError("typing non-ASCII text needs wl-clipboard (sudo apt install wl-clipboard)")
        subprocess.run(["wl-copy", "--", text], check=True, timeout=3)
        self.hotkey("ctrl", "v")

    def close(self):
        try:
            self.ioctl(self.fd, self.UI_DEV_DESTROY)
        finally:
            os.close(self.fd)
