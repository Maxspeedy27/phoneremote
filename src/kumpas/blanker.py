"""Private black/white screen: blank the projector but not the phone's view.

Pressing B or W in a slideshow app blanks the screen itself, so the phone's
screen view goes black too, and moving to another slide un-blanks it. Instead,
on Linux (X11) Kumpas sets the display's gamma ramp to all-black or all-white.
The ramp is applied as the picture leaves the graphics card, after any screen
capture reads it, so the phone still sees the real screen and the presenter
can change slides while the audience sees nothing.

With an external display (a projector) connected, only external displays are
blanked and the laptop's own panel stays visible. The original ramps are saved
to a file before blanking, so a crash can't leave the projector dark: the next
start puts them back.

Elsewhere (Wayland, Windows, macOS) available is False and the caller falls
back to the slideshow app's own B/W keys.
"""

import ctypes
import ctypes.util
import json
import os
import sys
import threading

from .system import config_dir

INTERNAL_PREFIXES = ("eDP", "LVDS", "DSI")   # a laptop's built-in panel
REAPPLY_SECONDS = 1.0   # e.g. Night Light rewrites the ramp now and then


class _ScreenResources(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("configTimestamp", ctypes.c_ulong),
                ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("noutput", ctypes.c_int), ("outputs", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int), ("modes", ctypes.c_void_p)]


class _OutputInfo(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("crtc", ctypes.c_ulong),
                ("name", ctypes.c_char_p), ("nameLen", ctypes.c_int),
                ("mm_width", ctypes.c_ulong), ("mm_height", ctypes.c_ulong),
                ("connection", ctypes.c_ushort), ("subpixel_order", ctypes.c_ushort),
                ("ncrtc", ctypes.c_int), ("crtcs", ctypes.POINTER(ctypes.c_ulong)),
                ("nclone", ctypes.c_int), ("clones", ctypes.POINTER(ctypes.c_ulong)),
                ("nmode", ctypes.c_int), ("npreferred", ctypes.c_int),
                ("modes", ctypes.POINTER(ctypes.c_ulong))]


class _Gamma(ctypes.Structure):
    _fields_ = [("size", ctypes.c_int), ("red", ctypes.POINTER(ctypes.c_ushort)),
                ("green", ctypes.POINTER(ctypes.c_ushort)), ("blue", ctypes.POINTER(ctypes.c_ushort))]


class X11Gamma:
    """Read and write the gamma ramps of the X server's displays (XRandR)."""

    def __init__(self):
        x11 = ctypes.util.find_library("X11")
        xrandr = ctypes.util.find_library("Xrandr")
        if not x11 or not xrandr:
            raise OSError("libX11/libXrandr not found")
        self.x = x = ctypes.CDLL(x11)
        self.xr = xr = ctypes.CDLL(xrandr)
        x.XOpenDisplay.restype = ctypes.c_void_p
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ctypes.c_ulong
        x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x.XFlush.argtypes = [ctypes.c_void_p]
        x.XCloseDisplay.argtypes = [ctypes.c_void_p]
        xr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(_ScreenResources)
        xr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xr.XRRFreeScreenResources.argtypes = [ctypes.POINTER(_ScreenResources)]
        xr.XRRGetOutputInfo.restype = ctypes.POINTER(_OutputInfo)
        xr.XRRGetOutputInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ScreenResources), ctypes.c_ulong]
        xr.XRRFreeOutputInfo.argtypes = [ctypes.POINTER(_OutputInfo)]
        xr.XRRGetCrtcGamma.restype = ctypes.POINTER(_Gamma)
        xr.XRRGetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        xr.XRRAllocGamma.restype = ctypes.POINTER(_Gamma)
        xr.XRRAllocGamma.argtypes = [ctypes.c_int]
        xr.XRRSetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_Gamma)]
        xr.XRRFreeGamma.argtypes = [ctypes.POINTER(_Gamma)]
        with self._display():
            pass   # fail now, not mid-talk, if there's no X server

    class _Open:
        def __init__(self, x):
            self.x = x
            self.dpy = x.XOpenDisplay(None)
            if not self.dpy:
                raise OSError("can't open the X display")

        def __enter__(self):
            return self.dpy

        def __exit__(self, *exc):
            self.x.XFlush(self.dpy)
            self.x.XCloseDisplay(self.dpy)

    def _display(self):
        return self._Open(self.x)

    def displays(self):
        """[(crtc, output name)] for each lit display."""
        found = []
        with self._display() as dpy:
            res = self.xr.XRRGetScreenResourcesCurrent(dpy, self.x.XDefaultRootWindow(dpy))
            if not res:
                return found
            try:
                for i in range(res.contents.noutput):
                    info = self.xr.XRRGetOutputInfo(dpy, res, res.contents.outputs[i])
                    if not info:
                        continue
                    try:
                        if info.contents.crtc:
                            name = (info.contents.name or b"").decode(errors="replace")
                            found.append((int(info.contents.crtc), name))
                    finally:
                        self.xr.XRRFreeOutputInfo(info)
            finally:
                self.xr.XRRFreeScreenResources(res)
        return found

    def get(self, crtc):
        """The CRTC's ramps as [red, green, blue] lists."""
        with self._display() as dpy:
            g = self.xr.XRRGetCrtcGamma(dpy, crtc)
            if not g:
                raise OSError("can't read the gamma ramp")
            try:
                n = g.contents.size
                return [g.contents.red[:n], g.contents.green[:n], g.contents.blue[:n]]
            finally:
                self.xr.XRRFreeGamma(g)

    def set(self, crtc, ramps):
        n = len(ramps[0])
        with self._display() as dpy:
            g = self.xr.XRRAllocGamma(n)
            if not g:
                raise OSError("can't allocate a gamma ramp")
            try:
                for channel, values in zip((g.contents.red, g.contents.green, g.contents.blue), ramps):
                    for i, v in enumerate(values):
                        channel[i] = v
                self.xr.XRRSetCrtcGamma(dpy, crtc, g)
            finally:
                self.xr.XRRFreeGamma(g)


def _x11_available():
    if not sys.platform.startswith("linux") or not os.environ.get("DISPLAY"):
        return False
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return False   # Xwayland's gamma doesn't reach the real screen
    return True


class Blanker:
    """Toggles a private black or white screen. mode is None, "black" or "white"."""

    def __init__(self, gamma=None, state_file=None, reapply_seconds=REAPPLY_SECONDS):
        self.mode = None
        self.problem = None
        self._saved = {}             # crtc -> original ramps, while blanked
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._reapply_seconds = reapply_seconds
        self.state_file = state_file if state_file is not None else config_dir() / "blank-gamma.json"
        if gamma is None and _x11_available():
            try:
                gamma = X11Gamma()
            except OSError as exc:
                self.problem = str(exc)
        self.gamma = gamma
        if self.gamma is not None:
            self._recover()

    @property
    def available(self):
        return self.gamma is not None

    def targets(self):
        """CRTCs to blank: the external displays if any, else every display."""
        displays = self.gamma.displays()
        external = [c for c, name in displays if not name.startswith(INTERNAL_PREFIXES)]
        crtcs = external or [c for c, _ in displays]
        return list(dict.fromkeys(crtcs))

    def toggle(self, mode):
        """Press of the phone's Black or White button. Returns the new mode."""
        with self._lock:
            if self.mode == mode:
                self._restore()
            else:
                self._blank(mode)
            return self.mode

    def restore(self):
        with self._lock:
            self._restore()

    close = restore

    # ----- inside the lock -----

    def _blank(self, mode):
        if not self._saved:
            self._saved = {c: self.gamma.get(c) for c in self.targets()}
            self._write_state()
        self.mode = mode
        self._apply()
        if not getattr(self, "_thread", None) or not self._thread.is_alive():
            self._wake.clear()
            self._thread = threading.Thread(target=self._keep_applied, daemon=True)
            self._thread.start()

    def _apply(self):
        value = 0 if self.mode == "black" else 65535
        for crtc, ramps in self._saved.items():
            n = len(ramps[0])
            try:
                self.gamma.set(crtc, [[value] * n] * 3)
            except OSError:
                pass   # that display was unplugged

    def _restore(self):
        self.mode = None
        self._wake.set()
        for crtc, ramps in self._saved.items():
            try:
                self.gamma.set(crtc, ramps)
            except OSError:
                pass
        self._saved = {}
        try:
            self.state_file.unlink()
        except OSError:
            pass

    def _keep_applied(self):
        while not self._wake.wait(self._reapply_seconds):
            with self._lock:
                if self.mode is None:
                    return
                self._apply()

    # ----- crash safety -----

    def _write_state(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.state_file.write_text(json.dumps({str(c): r for c, r in self._saved.items()}))
        except OSError:
            pass

    def _recover(self):
        """A previous run blanked the screen and didn't get to undo it: undo it now."""
        try:
            saved = json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return
        for crtc, ramps in saved.items():
            try:
                self.gamma.set(int(crtc), ramps)
            except (OSError, ValueError, TypeError):
                pass
        try:
            self.state_file.unlink()
        except OSError:
            pass
