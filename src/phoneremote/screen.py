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

from .system import IS_MAC, IS_WAYLAND, mac_screen_capture_allowed

MAX_WIDTH = 1280
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
        """Return (jpeg bytes, monitor actually used, number of monitors)."""
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
                return self._cache[2]
            from PIL import Image

            try:
                sct = self._sct()
                monitors = sct.monitors          # [all combined, monitor 1, monitor 2, ...]
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
            return result
