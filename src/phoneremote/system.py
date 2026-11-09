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


def config_dir():
    """Per-user settings folder, following each OS's convention."""
    if IS_WIN:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "PhoneRemote"
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / "PhoneRemote"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "phoneremote"


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
