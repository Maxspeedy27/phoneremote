"""Facts about the operating system the laptop side runs on."""

import os
import sys
from pathlib import Path

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")
IS_WAYLAND = IS_LINUX and (
    os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or "WAYLAND_DISPLAY" in os.environ
)
MOD = "command" if IS_MAC else "ctrl"


def _config_dirs():
    """(current, pre-rename) per-user settings folders, following each OS's convention."""
    if IS_WIN:
        base = Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
        return base / "Kumpas", base / "PhoneRemote"
    if IS_MAC:
        base = Path.home() / "Library" / "Application Support"
        return base / "Kumpas", base / "PhoneRemote"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    return base / "kumpas", base / "phoneremote"


def config_dir():
    """Per-user settings folder. The app used to be called Phone Remote: its
    folder is moved over the first time, so the paired phone and relay room stay."""
    current, old = _config_dirs()
    if not current.exists() and old.is_dir():
        try:
            old.rename(current)
        except OSError:
            return old
    return current


def _mac_framework_bool(framework, function):
    """Call a no-argument macOS framework function returning a bool; None if unavailable."""
    try:
        import ctypes

        lib = ctypes.cdll.LoadLibrary(f"/System/Library/Frameworks/{framework}.framework/{framework}")
        fn = getattr(lib, function)
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


def mac_accessibility_trusted():
    """macOS: may this app send keyboard and mouse input? None if unknown."""
    return _mac_framework_bool("ApplicationServices", "AXIsProcessTrusted")


def mac_screen_capture_allowed(ask=False):
    """macOS 10.15+: may this app capture the screen? With ask=True, shows the
    system prompt the first time. None if unknown."""
    return _mac_framework_bool("CoreGraphics",
                               "CGRequestScreenCaptureAccess" if ask else "CGPreflightScreenCaptureAccess")
