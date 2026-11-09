"""Ways of turning remote commands into real keyboard and mouse input."""

from ..system import IS_LINUX, IS_WAYLAND
from .base import Backend

CHOICES = ("auto", "pyautogui", "uinput")


def create_backend(choice="auto"):
    """Create the input backend; raises RuntimeError with advice if it can't."""
    if choice == "auto":
        choice = "uinput" if IS_WAYLAND else "pyautogui"
    if choice == "pyautogui":
        from .pyautogui_backend import PyAutoGuiBackend
        return PyAutoGuiBackend()
    if not IS_LINUX:
        raise RuntimeError("The uinput backend only exists on Linux.")
    from .uinput import SETUP_HELP, UinputBackend
    try:
        return UinputBackend()
    except FileNotFoundError:
        raise RuntimeError("/dev/uinput is missing. Load the kernel module with:  sudo modprobe uinput")
    except PermissionError:
        raise RuntimeError(SETUP_HELP)


__all__ = ["Backend", "CHOICES", "create_backend"]
