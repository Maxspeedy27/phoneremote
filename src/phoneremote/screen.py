"""Small JPEG snapshots of the laptop screen for the phone's live view.

Snapshots are only taken while the paired phone asks for them, and travel
encrypted like everything else. Capturing uses mss (Windows, macOS, Linux on
X11) and Pillow for scaling and JPEG encoding. Wayland deliberately doesn't let
apps read the screen; the screenshot portal is far too slow for a live view
(seconds per frame, a file saved per shot), so it isn't supported there yet.
"""

import io
import threading
import time

from .system import IS_MAC, IS_WAYLAND, IS_WIN, mac_screen_capture_allowed

MAX_WIDTH = 1920      # fullscreen on a large phone, or zoomed in
MIN_WIDTH = 160
QUALITY = 60
MIN_INTERVAL = 0.15   # seconds; repeated requests within this get the cached frame


class ScreenUnavailable(Exception):
    """The screen can't be captured here; the message says why, for the phone."""


def _open_mss():
    import mss
    factory = getattr(mss, "MSS", None) or mss.mss   # mss 10 renamed mss.mss to mss.MSS
    return factory()


class ScreenGrabber:
    """Takes snapshots of one monitor, or of all of them (monitor 0).

    Call from any thread; captures are serialized. mss handles are per-thread
    on some platforms, so one is opened per capture thread and kept.
    """

    def __init__(self, enabled=True):
        self.enabled = enabled
        self._lock = threading.Lock()
        self._local = threading.local()
        self._cache = None        # (key, time, result)
        self._monitors = None     # mss monitor rectangles from the last capture
        self._xdisplay = None     # X11 connection for reading the cursor position
        self._cursor_lock = threading.Lock()   # separate, so polls don't wait for a capture
        self.last_request = 0.0   # when the phone last asked, for "viewing" indicators

    def unavailable_reason(self, ask=False):
        """Why the screen can't be shown, or None. ask=True may show the
        macOS permission prompt (only do that when the phone asks)."""
        if not self.enabled:
            return "Screen view is turned off on the laptop."
        if IS_WAYLAND:
            return ("Screen view isn't available on Wayland yet. "
                    "Log in to an X11 (Xorg) session on the laptop to use it.")
        try:
            import mss  # noqa: F401
            import PIL  # noqa: F401
        except ImportError:
            return "Screen view needs the mss and Pillow packages on the laptop (pip install mss pillow)."
        if IS_MAC and mac_screen_capture_allowed(ask=ask) is False:
            # Without permission macOS returns just the wallpaper, so say so.
            return ("Allow Phone Remote under System Settings > Privacy & Security > Screen Recording "
                    "on the Mac, then restart Phone Remote.")
        return None

    @property
    def viewing(self):
        """True while the phone is actively watching (asked in the last few seconds)."""
        return time.monotonic() - self.last_request < 3

    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = self._local.sct = _open_mss()
        return sct

    def grab(self, monitor=1, width=720):
        """Return (jpeg bytes, monitor used, number of monitors, cursor).

        cursor is the mouse pointer's position as [x, y] fractions of the
        monitor's width and height (so the phone can draw it, since screen
        captures leave it out), or None when it's on another monitor.
        """
        reason = self.unavailable_reason(ask=True)
        if reason:
            raise ScreenUnavailable(reason)
        if not isinstance(width, int) or isinstance(width, bool):
            raise ValueError("bad width")
        if not isinstance(monitor, int) or isinstance(monitor, bool):
            raise ValueError("bad monitor")
        width = max(MIN_WIDTH, min(MAX_WIDTH, width))
        self.last_request = time.monotonic()

        with self._lock:
            key = (monitor, width)
            now = time.monotonic()
            if self._cache and self._cache[0] == key and now - self._cache[1] < MIN_INTERVAL:
                return self._cache[2] + (self._cursor_fraction(self._cache[2][1]),)
            from PIL import Image

            try:
                sct = self._sct()
                monitors = sct.monitors          # [all combined, monitor 1, monitor 2, ...]
                self._monitors = [dict(m) for m in monitors]
                count = len(monitors) - 1
                if not 0 <= monitor <= count:
                    monitor = 1
                shot = sct.grab(monitors[monitor])
            except Exception as exc:
                self._local.sct = None
                raise ScreenUnavailable(f"Couldn't capture the screen ({exc}).") from exc
            image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            if image.width > width:
                image = image.resize((width, max(1, round(image.height * width / image.width))),
                                     Image.Resampling.BILINEAR)
            out = io.BytesIO()
            image.save(out, "JPEG", quality=QUALITY, optimize=False)
            result = (out.getvalue(), monitor, count)
            self._cache = (key, time.monotonic(), result)
            return result + (self._cursor_fraction(monitor),)

    def point(self, monitor, fx, fy):
        """Screen coordinates of a point given as fractions of a monitor.

        Used for touchscreen control: the phone sends where on the picture
        it was tapped. Coordinates are in the same units as the input backend
        (pixels; points on macOS), as both follow the OS's coordinate system.
        """
        if not self.enabled or self._monitors is None:
            raise ValueError("Touch control needs the screen view; open it on the phone first.")
        if not isinstance(monitor, int) or isinstance(monitor, bool) or not 0 <= monitor < len(self._monitors):
            raise ValueError("bad monitor")
        m = self._monitors[monitor]
        x = m["left"] + round(fx * (m["width"] - 1))
        y = m["top"] + round(fy * (m["height"] - 1))
        return x, y

    def cursor(self, monitor):
        """Just the pointer position (see grab), for frequent polls between frames."""
        if self.unavailable_reason() or self._monitors is None:
            raise ScreenUnavailable(self.unavailable_reason() or "Open the screen view first.")
        if not isinstance(monitor, int) or isinstance(monitor, bool):
            raise ValueError("bad monitor")
        return self._cursor_fraction(monitor)

    def _cursor_fraction(self, monitor):
        with self._cursor_lock:
            pos = self._cursor_position()
        if pos is None or not self._monitors or not 0 <= monitor < len(self._monitors):
            return None
        m = self._monitors[monitor]
        fx = (pos[0] - m["left"]) / max(1, m["width"] - 1)
        fy = (pos[1] - m["top"]) / max(1, m["height"] - 1)
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            return None
        return [round(fx, 4), round(fy, 4)]

    def _cursor_position(self):
        """The mouse pointer in screen coordinates, or None if unknown."""
        try:
            import ctypes

            if IS_WIN:
                class POINT(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
                pt = POINT()
                if not ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                    return None
                return pt.x, pt.y
            if IS_MAC:
                class CGPoint(ctypes.Structure):
                    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]
                cg = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
                cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
                cg.CGEventCreate.restype = ctypes.c_void_p
                cg.CGEventCreate.argtypes = [ctypes.c_void_p]
                cg.CGEventGetLocation.restype = CGPoint
                cg.CGEventGetLocation.argtypes = [ctypes.c_void_p]
                cf.CFRelease.argtypes = [ctypes.c_void_p]
                event = cg.CGEventCreate(None)
                if not event:
                    return None
                try:
                    p = cg.CGEventGetLocation(event)
                finally:
                    cf.CFRelease(event)
                return p.x, p.y
            if self._xdisplay is None:
                from Xlib import display
                self._xdisplay = display.Display()
            p = self._xdisplay.screen().root.query_pointer()
            return p.root_x, p.root_y
        except Exception:
            self._xdisplay = None
            return None
