# PyInstaller spec for Kumpas. Build with:  python packaging/build.py
# (or: pyinstaller --noconfirm --distpath dist --workpath build packaging/kumpas.spec)
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
WEB = ROOT / "src" / "kumpas" / "web"
ICONS = ROOT / "packaging" / "icons"
sys.path.insert(0, str(ROOT / "src"))
from kumpas import __version__  # noqa: E402

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

hidden = ["kumpas.backends.pyautogui_backend", "kumpas.relay", "websockets.sync.client",
          *collect_submodules("mss")]
if IS_WIN:
    hidden += ["pyautogui._pyautogui_win"]
elif IS_MAC:
    hidden += ["pyautogui._pyautogui_osx", "Quartz", "AppKit"]
else:
    hidden += ["pyautogui._pyautogui_x11", "kumpas.backends.uinput", "Xlib.ext.xtest"]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(WEB), "kumpas/web"), (str(ROOT / "LICENSE"), ".")],
    hiddenimports=hidden,
    # tkinter is only used by pyautogui's optional message boxes and mouse-info
    # helper, which Kumpas never calls.
    excludes=["tkinter", "mouseinfo", "pymsgbox", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)

name = "Kumpas" if (IS_WIN or IS_MAC) else "kumpas"
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=name,
    console=not (IS_WIN or IS_MAC),   # Linux keeps a console so `kumpas` works in a terminal
    icon=str(ICONS / ("kumpas.ico" if IS_WIN else "kumpas.icns")) if (IS_WIN or IS_MAC) else None,
    version=str(ROOT / "build" / "win-version.txt") if IS_WIN else None,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name=name, upx=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="Kumpas.app",
        icon=str(ICONS / "kumpas.icns"),
        bundle_identifier="app.kumpas.desktop",
        version=__version__,
        info_plist={
            "CFBundleName": "Kumpas",
            "CFBundleDisplayName": "Kumpas",
            "CFBundleShortVersionString": __version__,
            "NSHighResolutionCapable": True,
            # No windows of its own (the control panel opens in the browser),
            # so stay out of the Dock; open the app again to show the panel.
            "LSUIElement": True,
            "NSHumanReadableCopyright": "Copyright © 2026 Macley Domingo. Free software under the GNU GPL v3 or later.",
        },
    )
