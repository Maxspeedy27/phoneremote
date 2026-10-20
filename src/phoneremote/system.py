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
